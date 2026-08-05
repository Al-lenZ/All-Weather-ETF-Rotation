"""
v6/scripts/baseline_diagnostics_v6.py
=====================================
Follow-up diagnostics on the Phase 9.1 static baselines. Complements
``cost_attribution_v6.py`` by drilling into three questions:

1. **Marginal churn.** Cost attribution showed 85–87% of turnover comes
   from the *selection* channel (top-K rotation). This report asks how
   much of that selection turnover is "marginal" — names that flip in
   and out because their rank sits ε-close to the K boundary — versus
   deep moves where alpha actually crossed most of the ranking. For each
   flip event we log distance from the boundary and count round-trip
   flips (exit at t → re-enter within 1 / 2 / 4 weeks).

2. **Per-year performance table.** Calendar-year Sharpe, annualized
   return, and max drawdown per cell, on the checked-in net-return
   series. Restricted to years fully inside IS ∪ OOS (i.e. drops the
   sealed 2026 hold-out).

3. **Drawdown attribution.** Locate each cell's full-window max DD
   (peak → trough on net NAV) and decompose the loss by name:
       net_contrib_i = Σ_t w_{i,t}·fwd_{i,t}  −  cost·Σ_t |Δw_{i,t}|
   Σ_i net_contrib_i equals the DD's absolute NAV change by
   construction. Also reports each contributor's average weight during
   the DD window and its own compound return over the same window.

Same source-of-truth as ``cost_attribution_v6.py``: reads persisted
``ensemble_weights.parquet`` + ``ensemble_alpha.parquet`` from each cell
under ``data/v6_static/{cell}/`` — no re-screen.

Outputs
-------
    data/v6_static/baseline_diagnostics/marginal_churn_summary.csv
    data/v6_static/baseline_diagnostics/{cell}_flip_events.csv
    data/v6_static/baseline_diagnostics/{cell}_marginal_histogram.csv
    data/v6_static/baseline_diagnostics/annual_stats.csv
    data/v6_static/baseline_diagnostics/drawdown_summary.csv
    data/v6_static/baseline_diagnostics/{cell}_dd_attribution.csv
    reports/baseline_diagnostics_v6.md

Run
---
    python v6/scripts/baseline_diagnostics_v6.py
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# --- v6/common sys.path bootstrap ---
import sys as _v6_sys
from pathlib import Path as _V6Path
_v6_p = _V6Path(__file__).resolve().parent
while _v6_p.name != "v6" and _v6_p.parent != _v6_p:
    _v6_p = _v6_p.parent
_v6_sys.path.insert(0, str(_v6_p / "common"))
del _v6_p
# --------------------------------------
import _common_v6 as C
import xs_engine_v6 as E


CELLS: tuple[tuple[str, float], ...] = (
    ("long", 0.05),
    ("long", 0.10),
    ("long", 0.20),
    ("ls",   0.20),
)

COST_PER_TRADE   = E.DEFAULT_COST_PER_TRADE   # 10 bp/side
MARGINAL_BAND    = 2                          # |rank − K_t| ≤ this = "marginal"
ROUND_TRIP_HORIZONS = (1, 2, 4)               # weeks; exit→re-entry gap
OUT_ROOT = C.DATA_DIR / "v6_static" / "baseline_diagnostics"


def _cell_tag(mode: str, q: float) -> str:
    return f"{mode}_q{int(round(q * 100)):02d}"


# ---------------------------------------------------------------------- #
# Loader
# ---------------------------------------------------------------------- #
@dataclass
class CellPanels:
    cell:       str
    mode:       str
    q:          float
    W:          pd.DataFrame        # weights
    A:          pd.DataFrame        # ensemble α (raw, pre-mask)
    A_e:        pd.DataFrame        # α masked by eligibility (α∧σ>0∧member)
    fwd:        pd.DataFrame        # forward 1w returns
    net_ret:    pd.Series           # checked-in net_ret (cost-baked)
    K_t:        pd.Series           # per-bar book size (long-side count in LS)
    N_t:        pd.Series           # per-bar eligible count


def _load_cell(mode: str, q: float, membership: pd.DataFrame) -> CellPanels:
    cell = _cell_tag(mode, q)
    src = C.DATA_DIR / "v6_static" / cell
    W = pd.read_parquet(src / "ensemble_weights.parquet")
    A = pd.read_parquet(src / "ensemble_alpha.parquet")
    sig = pd.read_parquet(C.DATA_DIR / "panels_v6" / "sigma_causal_26w.parquet")
    fwd = pd.read_parquet(C.DATA_DIR / "panels_v6" / "fwd_1w.parquet")

    sig = sig.reindex(index=W.index, columns=W.columns)
    fwd = fwd.reindex(index=W.index, columns=W.columns).fillna(0.0)
    mem = membership.reindex(index=W.index, columns=W.columns).fillna(False).astype(bool)

    eligible = A.notna() & sig.notna() & (sig > 0) & mem
    A_e = A.where(eligible)
    N_t = eligible.sum(axis=1).astype(int)

    # K_t = size of long leg for both modes (LS has short leg of same size)
    if mode == "long":
        K_t = (W > 0).sum(axis=1).astype(int)
    else:
        K_t = (W > 0).sum(axis=1).astype(int)

    net_ret = (pd.read_csv(src / "ensemble_net_ret.csv", index_col=0,
                           parse_dates=True)["net_ret"])
    net_ret = net_ret.reindex(W.index).fillna(0.0)

    return CellPanels(cell=cell, mode=mode, q=q, W=W, A=A, A_e=A_e,
                      fwd=fwd, net_ret=net_ret, K_t=K_t, N_t=N_t)


# ---------------------------------------------------------------------- #
# 1. Marginal churn / rank-flip analysis
# ---------------------------------------------------------------------- #
def _per_bar_ranks(A_e: pd.DataFrame) -> pd.DataFrame:
    """Row-wise descending rank of A_e (rank 1 = highest α, ties broken
    by first-occurrence to match xs_engine_v6.build_static_weights).
    Non-eligible cells stay NaN."""
    return A_e.rank(axis=1, method="first", ascending=False)


def _leg_labels(cp: CellPanels) -> pd.DataFrame:
    """Per-cell/per-bar leg label as int: +1 long, -1 short, 0 flat."""
    leg = pd.DataFrame(0, index=cp.W.index, columns=cp.W.columns, dtype=np.int8)
    leg = leg.mask(cp.W > 0,  1)
    leg = leg.mask(cp.W < 0, -1)
    return leg


def analyze_marginal_churn(cp: CellPanels) -> tuple[pd.DataFrame,
                                                     pd.DataFrame,
                                                     dict]:
    """Log every entry/exit event per bar + summary stats.

    Event columns:
      date, code, side ('long'/'short'), event ('entry'/'exit'),
      rank_prev, rank_cur, K_prev, K_cur, boundary_prev, boundary_cur,
      dist_prev, dist_cur, dw (|Δw| contribution to selection turnover),
      round_trip_h  (min gap to matching opposite event within max H, or NaN).
    """
    W    = cp.W
    A_e  = cp.A_e
    K_t  = cp.K_t
    N_t  = cp.N_t
    ranks = _per_bar_ranks(A_e)

    # Restrict analysis to IS ∪ OOS bars (matches cost_attribution windowing)
    keep = (W.index <= C.OOS_END)
    W = W.loc[keep]
    A_e = A_e.loc[keep]
    ranks = ranks.loc[keep]
    K_t = K_t.loc[keep]
    N_t = N_t.loc[keep]

    leg      = _leg_labels(CellPanels(cp.cell, cp.mode, cp.q,
                                       W, cp.A.loc[keep], A_e,
                                       cp.fwd.loc[keep], cp.net_ret.loc[keep],
                                       K_t, N_t))
    leg_prev = leg.shift(1).fillna(0).astype(np.int8)
    dW_abs   = (W - W.shift(1).fillna(0.0)).abs()

    dates  = W.index.to_list()
    events = []
    for side_val, side_name in ((1, "long"), (-1, "short")):
        if side_name == "short" and cp.mode != "ls":
            continue
        # Entry: was not on this side at t-1, is on this side at t
        entry_mask = (leg != side_val) & (leg == side_val) if False else (
            (leg == side_val) & (leg_prev != side_val)
        )
        # Exit: was on this side at t-1, is not on this side at t
        exit_mask = (leg != side_val) & (leg_prev == side_val)

        for mask, event in ((entry_mask, "entry"), (exit_mask, "exit")):
            # Iterate per bar (fast enough — 400 bars × few dozen flips)
            idx_pairs = np.argwhere(mask.to_numpy())
            for ti, ci in idx_pairs:
                t = dates[ti]
                code = W.columns[ci]
                r_cur = ranks.iat[ti, ci]
                r_prev = ranks.iat[ti - 1, ci] if ti > 0 else np.nan
                Kc = int(K_t.iat[ti])
                Kp = int(K_t.iat[ti - 1]) if ti > 0 else 0
                Nc = int(N_t.iat[ti])
                Np = int(N_t.iat[ti - 1]) if ti > 0 else 0
                # Boundary depends on side. For long side, boundary rank = K.
                # For short side, boundary rank = N - K + 1  (rank > N-K is
                # bottom-K).  Distance sign convention: positive = "outside
                # the book", negative = "inside".
                if side_name == "long":
                    boundary_cur  = Kc
                    boundary_prev = Kp
                    dist_cur  = (r_cur  - Kc) if pd.notna(r_cur)  else np.nan
                    dist_prev = (r_prev - Kp) if pd.notna(r_prev) else np.nan
                else:
                    boundary_cur  = Nc - Kc
                    boundary_prev = Np - Kp
                    # For short leg, being IN means rank > (N - K).  Distance
                    # "outside" = (N - K) - rank  (positive when rank ≤ N-K,
                    # i.e. name is outside the short leg).
                    dist_cur  = (boundary_cur  - r_cur)  if pd.notna(r_cur)  else np.nan
                    dist_prev = (boundary_prev - r_prev) if pd.notna(r_prev) else np.nan

                events.append({
                    "date": t, "code": code, "side": side_name, "event": event,
                    "rank_prev": r_prev, "rank_cur": r_cur,
                    "K_prev": Kp, "K_cur": Kc,
                    "N_prev": Np, "N_cur": Nc,
                    "boundary_prev": boundary_prev, "boundary_cur": boundary_cur,
                    "dist_prev": dist_prev, "dist_cur": dist_cur,
                    "dw": float(dW_abs.iat[ti, ci]),
                })

    ev = pd.DataFrame(events)
    if ev.empty:
        return ev, pd.DataFrame(), {"cell": cp.cell,
                                     "n_events": 0,
                                     "n_entries": 0, "n_exits": 0}

    # --- Round-trip tagging ------------------------------------------ #
    # For each exit (code, date_exit), find the next entry of the same
    # code on the same side within max(H) bars; record the gap in weeks.
    # For each entry, symmetric: gap to prior matching exit within H.
    H_max = max(ROUND_TRIP_HORIZONS)
    ev = ev.sort_values(["side", "code", "date"]).reset_index(drop=True)
    ev["round_trip_h"] = np.nan  # gap in weeks
    for (side_name, code), grp in ev.groupby(["side", "code"], sort=False):
        # Walk paired exit/entry within the same code+side sequence.
        rows = grp[["date", "event"]].to_dict("records")
        idxs = grp.index.to_list()
        for i, row in enumerate(rows):
            if row["event"] != "exit":
                continue
            # scan forward for the next entry
            for j in range(i + 1, len(rows)):
                if rows[j]["event"] == "entry":
                    gap = int(round((rows[j]["date"] - row["date"]).days / 7))
                    if gap <= H_max:
                        ev.at[idxs[i], "round_trip_h"] = gap
                        ev.at[idxs[j], "round_trip_h"] = gap
                    break
    ev = ev.sort_values("date").reset_index(drop=True)

    # --- Histogram of (dist relative to boundary) for flip events ---- #
    def _flip_dist(row) -> float:
        # "Flip distance" = max(|dist_prev|, |dist_cur|) on the joining side.
        # For an exit, dist_prev ≤ 0 (was inside), dist_cur > 0 (now outside).
        # For an entry, dist_prev > 0, dist_cur ≤ 0.
        # Report the *outside* distance (magnitude of how far past the
        # boundary the name lived when it was on the other side).
        if row["event"] == "exit":
            return float(row["dist_cur"]) if pd.notna(row["dist_cur"]) else np.nan
        else:
            return float(row["dist_prev"]) if pd.notna(row["dist_prev"]) else np.nan

    ev["flip_dist"] = ev.apply(_flip_dist, axis=1)

    # Histogram bins: 1, 2, 3, ≤5, ≤10, ≤25, >25 (in rank-slots outside K).
    bins = [0.5, 1.5, 2.5, 3.5, 5.5, 10.5, 25.5, np.inf]
    labels = ["1", "2", "3", "4-5", "6-10", "11-25", ">25"]
    ev["flip_bin"] = pd.cut(ev["flip_dist"], bins=bins, labels=labels,
                             include_lowest=True)
    hist = (ev.groupby(["side", "event", "flip_bin"], observed=True)
              .agg(n_events=("dw", "size"), dw_sum=("dw", "sum"))
              .reset_index())

    # --- Summary ---------------------------------------------------- #
    total_dw = float(ev["dw"].sum())
    marginal_dw = float(ev.loc[ev["flip_dist"].abs() <= MARGINAL_BAND, "dw"].sum())
    n_exits = int((ev["event"] == "exit").sum())
    n_entries = int((ev["event"] == "entry").sum())

    round_trip_stats = {}
    exit_rows = ev[ev["event"] == "exit"]
    entry_rows = ev[ev["event"] == "entry"]
    for h in ROUND_TRIP_HORIZONS:
        rt_exits = int((exit_rows["round_trip_h"] <= h).sum())
        rt_entries = int((entry_rows["round_trip_h"] <= h).sum())
        rt_dw = float(ev.loc[ev["round_trip_h"].le(h), "dw"].sum())
        round_trip_stats[f"rt{h}w_exits"]        = rt_exits
        round_trip_stats[f"rt{h}w_entries"]      = rt_entries
        round_trip_stats[f"rt{h}w_dw"]           = rt_dw
        round_trip_stats[f"rt{h}w_dw_share"]     = rt_dw / total_dw if total_dw else np.nan
        round_trip_stats[f"rt{h}w_exit_share"]   = rt_exits / n_exits if n_exits else np.nan

    summary = {
        "cell": cp.cell,
        "n_events": int(len(ev)),
        "n_entries": n_entries,
        "n_exits": n_exits,
        "selection_dw_total": total_dw,
        "marginal_band": MARGINAL_BAND,
        f"dw_marginal_pm{MARGINAL_BAND}":       marginal_dw,
        f"dw_marginal_pm{MARGINAL_BAND}_share": marginal_dw / total_dw if total_dw else np.nan,
        **round_trip_stats,
    }
    return ev, hist, summary


# ---------------------------------------------------------------------- #
# 2. Per-year performance
# ---------------------------------------------------------------------- #
def analyze_annual(cp: CellPanels) -> pd.DataFrame:
    """Per calendar-year Sharpe / annualized return / max DD on net_ret.

    Restricts to years fully or partially inside IS ∪ OOS (i.e. drops
    2026 sealed hold-out and any pre-panel warmup bars where W is flat).
    """
    net = cp.net_ret.copy()
    # Restrict to IS ∪ OOS window (matches cost_attribution scoping)
    keep = (net.index <= C.OOS_END)
    net = net.loc[keep]

    rows = []
    for year, grp in net.groupby(net.index.year, sort=True):
        n = int(len(grp))
        if n == 0:
            continue
        ann_ret = float(grp.mean() * C.WEEKS_PER_YEAR)
        vol     = float(grp.std(ddof=1) * np.sqrt(C.WEEKS_PER_YEAR)) if n > 1 else 0.0
        sharpe  = (ann_ret / vol) if vol > 0 else 0.0
        nav = 1.0 + grp.cumsum()
        cummax = nav.cummax()
        # DD as fraction of running peak within the year
        dd = ((nav - cummax) / cummax).min()
        rows.append({
            "cell": cp.cell,
            "year": int(year),
            "n_bars": n,
            "ann_ret": ann_ret,
            "sharpe":  sharpe,
            "max_dd":  float(dd),
            "vol":     vol,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------- #
# 3. Drawdown attribution
# ---------------------------------------------------------------------- #
def _locate_max_dd(net_ret: pd.Series) -> tuple[pd.Timestamp,
                                                pd.Timestamp,
                                                float, float, float]:
    """Return (peak_date, trough_date, dd_pct, nav_peak, nav_trough).

    NAV = 1 + cumsum(net_ret). DD is defined as (NAV - cummax)/cummax; the
    trough is the argmin of that ratio, and the peak is the argmax of NAV
    up to and including that trough (last running peak).
    """
    nav = 1.0 + net_ret.cumsum()
    cummax = nav.cummax()
    dd = (nav - cummax) / cummax
    trough = dd.idxmin()
    # Peak: last time NAV set its running maximum ≤ trough
    up_to = nav.loc[:trough]
    peak = up_to.idxmax()
    return (peak, trough,
            float(dd.loc[trough]),
            float(nav.loc[peak]),
            float(nav.loc[trough]))


def analyze_drawdown(cp: CellPanels) -> tuple[dict, pd.DataFrame]:
    """Locate max DD on net-NAV (IS ∪ OOS) and decompose by name.

    Contribution decomposition (bars t = peak+1 .. trough):
        gross_contrib_i = Σ w_{i,t} · fwd_{i,t}
        cost_contrib_i  = cost_rate · Σ |Δw_{i,t}|
        net_contrib_i   = gross_contrib_i − cost_contrib_i
    Σ_i net_contrib_i  ==  Σ_t net_ret_t  ==  NAV_trough − NAV_peak.

    Also reports each name's average |weight| during the window and its
    compound close-to-close return over the same window (independent of
    the book).
    """
    net = cp.net_ret[cp.net_ret.index <= C.OOS_END]
    peak, trough, dd_pct, nav_peak, nav_trough = _locate_max_dd(net)

    # Window: bars *after* peak up to and including trough.
    win_idx = net.index[(net.index > peak) & (net.index <= trough)]
    if len(win_idx) == 0:
        empty = pd.DataFrame(columns=["code", "gross_contrib", "cost_contrib",
                                       "net_contrib", "avg_abs_weight",
                                       "name_return"])
        return ({
            "cell": cp.cell,
            "peak": peak, "trough": trough,
            "dd_pct": dd_pct, "nav_peak": nav_peak, "nav_trough": nav_trough,
            "n_bars": 0, "residual": 0.0,
        }, empty)

    W    = cp.W.loc[win_idx]
    fwd  = cp.fwd.loc[win_idx]
    # For dW we need one bar before peak; if peak is the first bar, prev = 0.
    W_prev_first = cp.W.loc[peak] if peak in cp.W.index else pd.Series(0.0, index=cp.W.columns)
    W_shift = W.shift(1)
    W_shift.iloc[0] = W_prev_first
    dW_abs = (W - W_shift).abs()

    gross_by_name = (W * fwd).sum(axis=0)
    cost_by_name  = COST_PER_TRADE * dW_abs.sum(axis=0)
    net_by_name   = gross_by_name - cost_by_name

    # Diagnostic — per-name summed weight (proxy for "how much did we hold")
    avg_abs_w = W.abs().mean(axis=0)

    # Standalone name return during the window (compound close-to-close),
    # independent of book weight, for interpretability.
    ret = (1.0 + fwd).prod(axis=0) - 1.0

    attribution = pd.DataFrame({
        "code":           cp.W.columns,
        "gross_contrib":  gross_by_name.values,
        "cost_contrib":   cost_by_name.values,
        "net_contrib":    net_by_name.values,
        "avg_abs_weight": avg_abs_w.values,
        "name_return":    ret.values,
    })
    # Drop dead rows to keep the CSV skimmable
    keep_row = (attribution["avg_abs_weight"] > 0) | (attribution["net_contrib"].abs() > 0)
    attribution = attribution.loc[keep_row].reset_index(drop=True)
    attribution = attribution.sort_values("net_contrib").reset_index(drop=True)

    residual = float(net.loc[win_idx].sum() - attribution["net_contrib"].sum())

    header = {
        "cell":       cp.cell,
        "peak":       peak,
        "trough":     trough,
        "dd_pct":     dd_pct,
        "nav_peak":   nav_peak,
        "nav_trough": nav_trough,
        "n_bars":     int(len(win_idx)),
        "residual":   residual,
    }
    return header, attribution


# ---------------------------------------------------------------------- #
# Driver
# ---------------------------------------------------------------------- #
def run() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    _codes, _blocks, membership = C.load_universe("v6")

    marginal_rows, dd_rows, annual_rows = [], [], []
    for mode, q in CELLS:
        cell = _cell_tag(mode, q)
        cp = _load_cell(mode, q, membership)

        # 1. Marginal churn
        ev, hist, msum = analyze_marginal_churn(cp)
        ev.to_csv(OUT_ROOT / f"{cell}_flip_events.csv", index=False)
        hist.to_csv(OUT_ROOT / f"{cell}_marginal_histogram.csv", index=False)
        marginal_rows.append(msum)

        # 2. Per-year
        ann = analyze_annual(cp)
        annual_rows.append(ann)

        # 3. Drawdown attribution
        dd_header, attrib = analyze_drawdown(cp)
        attrib.to_csv(OUT_ROOT / f"{cell}_dd_attribution.csv", index=False)
        dd_rows.append(dd_header)

        print(f"  {cell:>8s}  events={msum['n_events']}  "
              f"marginal±{MARGINAL_BAND}_share="
              f"{msum[f'dw_marginal_pm{MARGINAL_BAND}_share']:.1%}  "
              f"DD {dd_header['dd_pct']:.2%} "
              f"({dd_header['peak'].date()}→{dd_header['trough'].date()}, "
              f"{dd_header['n_bars']}w)")

    pd.DataFrame(marginal_rows).to_csv(OUT_ROOT / "marginal_churn_summary.csv",
                                        index=False)
    pd.DataFrame(dd_rows).to_csv(OUT_ROOT / "drawdown_summary.csv", index=False)
    pd.concat(annual_rows, ignore_index=True).to_csv(
        OUT_ROOT / "annual_stats.csv", index=False)

    print(f"\nwrote {OUT_ROOT}/")


if __name__ == "__main__":
    run()
