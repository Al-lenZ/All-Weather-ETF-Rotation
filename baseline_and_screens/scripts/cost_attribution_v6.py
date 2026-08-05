"""
v6/scripts/cost_attribution_v6.py
=================================
Phase 6.5 — cost-burn attribution on the Phase 9.1 baselines.

Decomposes each ensemble book's weekly turnover into two channels:

    selection : |Δw| on names that entered *or* exited the book between
                bar t-1 and bar t (one side had zero weight).
    sizing    : |Δw| on names present in *both* bars (both sides non-zero) —
                pure weight adjustment, driven by σ_causal_26w rolling and
                by top-K denominator renormalization when a co-holding
                rotates in/out.

By construction these partition |Δw| exactly:
    Σ|Δw| = selection + sizing   (per bar, per cell)

For each cell, we also compute gross vs net Sharpe by rerunning port_ret
without the 10 bp turnover cost. Gross uses the *same* weight panel and
fwd_1w that produced the checked-in ``ensemble_net_ret.csv`` — no new
alpha, no new selection.

Cells covered (the four Phase 9.1 baselines):
    long_q05, long_q10, long_q20, ls_q20

The ls_q05 and ls_q10 cells have empty kept sets (no factors passed the
screen at those q's, see ``book_xs_v6_report.md``) and are skipped.

Outputs
-------
    data/v6_static/cost_attribution/summary.csv       — one row per cell
    data/v6_static/cost_attribution/{cell}_bar.csv    — per-bar breakdown
    reports/cost_attribution_v6_report.md             — narrative + tables

Run
---
    python v6/scripts/cost_attribution_v6.py
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

COST_PER_TRADE = E.DEFAULT_COST_PER_TRADE   # 10 bp / side; matches Phase 9.1
OUT_ROOT = C.DATA_DIR / "v6_static" / "cost_attribution"


# ---------------------------------------------------------------------- #
# Loaders
# ---------------------------------------------------------------------- #
def _cell_tag(mode: str, q: float) -> str:
    return f"{mode}_q{int(round(q * 100)):02d}"


def _load_cell(mode: str, q: float,
               data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (weights, fwd_1w) reindexed to the weight panel's grid."""
    cell = _cell_tag(mode, q)
    src = data_dir / "v6_static" / cell
    W = pd.read_parquet(src / "ensemble_weights.parquet")
    fwd = pd.read_parquet(data_dir / "panels_v6" / "fwd_1w.parquet")
    fwd = fwd.reindex(index=W.index, columns=W.columns).fillna(0.0)
    return W, fwd


# ---------------------------------------------------------------------- #
# Attribution
# ---------------------------------------------------------------------- #
@dataclass
class BarAttribution:
    """Per-bar decomposition of |Δw| into selection + sizing channels."""
    total:     pd.Series   # Σ|Δw_t|
    selection: pd.Series   # |Δw| on names with pos_prev XOR pos_cur
    sizing:    pd.Series   # |Δw| on names with pos_prev AND pos_cur


def decompose_turnover(W: pd.DataFrame) -> BarAttribution:
    """Selection vs sizing channels of weekly turnover.

    A "position" is any non-zero weight. Bar-t turnover is:
      - selection : names where exactly one of (w_{t-1}, w_t) is non-zero
                    (enters or exits)
      - sizing    : names where both are non-zero (pure resize)

    First bar has no predecessor → its turnover is fully attributed to
    selection (initial deploy). Zero-weight bars (flat book) contribute 0.
    """
    W_prev = W.shift(1).fillna(0.0)
    dW = (W - W_prev).abs()

    pos_prev = W_prev.ne(0.0)
    pos_cur  = W.ne(0.0)

    both = pos_prev & pos_cur
    xor  = pos_prev ^ pos_cur

    sizing    = dW.where(both, 0.0).sum(axis=1)
    selection = dW.where(xor,  0.0).sum(axis=1)
    total     = dW.sum(axis=1)

    # Sanity: partition must be tight to numeric floor.
    residual = (total - selection - sizing).abs().max()
    assert residual < 1e-9, f"decomposition residual {residual:.3g} exceeds tol"
    return BarAttribution(total=total, selection=selection, sizing=sizing)


# ---------------------------------------------------------------------- #
# Sharpe helpers  (mirror xs_engine_v6._window_sharpe minus the CAGR / DD
# fields we don't need here)
# ---------------------------------------------------------------------- #
def _sharpe(net: pd.Series) -> float:
    if len(net) < 2:
        return 0.0
    vol = float(net.std(ddof=1)) * np.sqrt(C.WEEKS_PER_YEAR)
    if vol <= 0.0:
        return 0.0
    return float(net.mean()) * C.WEEKS_PER_YEAR / vol


def _split_windows(s: pd.Series) -> dict[str, pd.Series]:
    idx = s.index
    is_mask  = idx <= C.IN_SAMPLE_END
    oos_mask = (idx >= C.OOS_START) & (idx <= C.OOS_END)
    return {
        "is":   s[is_mask],
        "oos":  s[oos_mask],
        "full": s[is_mask | oos_mask],
    }


# ---------------------------------------------------------------------- #
# Cell driver
# ---------------------------------------------------------------------- #
def analyze_cell(mode: str, q: float, data_dir: Path,
                 cost_per_trade: float = COST_PER_TRADE) -> dict:
    """One-shot: load weights + fwd, decompose turnover, compute gross/net
    Sharpe per window, return a summary dict (also written to disk)."""
    cell = _cell_tag(mode, q)
    W, fwd = _load_cell(mode, q, data_dir)

    port_ret = (W * fwd).sum(axis=1)     # gross (no cost)
    attrib = decompose_turnover(W)
    cost = attrib.total * cost_per_trade
    net_ret = port_ret - cost

    # Restrict all summary stats to bars that reach the IS or OOS window
    # (matches xs_engine_v6.summarize_book — hold-out beyond OOS_END is
    # excluded).
    win_gross = _split_windows(port_ret)
    win_net   = _split_windows(net_ret)
    win_cost  = _split_windows(cost)
    win_total = _split_windows(attrib.total)
    win_sel   = _split_windows(attrib.selection)
    win_size  = _split_windows(attrib.sizing)

    def _cost_bps_yr(cost_series: pd.Series) -> float:
        # mean per-bar cost × 52  → fractional annual cost. ×1e4 → bps.
        return float(cost_series.mean() * C.WEEKS_PER_YEAR * 1e4)

    def _mean_ret_bps_yr(ret: pd.Series) -> float:
        return float(ret.mean() * C.WEEKS_PER_YEAR * 1e4)

    row = {
        "cell":        cell,
        "mode":        mode,
        "q":           q,
        "n_bars":      int(len(win_net["full"])),
        # Sharpe by window (gross vs net)
        "gross_sharpe_is":   _sharpe(win_gross["is"]),
        "net_sharpe_is":     _sharpe(win_net["is"]),
        "gross_sharpe_oos":  _sharpe(win_gross["oos"]),
        "net_sharpe_oos":    _sharpe(win_net["oos"]),
        "gross_sharpe_full": _sharpe(win_gross["full"]),
        "net_sharpe_full":   _sharpe(win_net["full"]),
        # Return drag (full window, bps/yr)
        "gross_ret_bps_yr":  _mean_ret_bps_yr(win_gross["full"]),
        "net_ret_bps_yr":    _mean_ret_bps_yr(win_net["full"]),
        "cost_bps_yr":       _cost_bps_yr(win_cost["full"]),
        # Turnover decomposition (avg per-bar |Δw|, full window)
        "turnover_total":     float(win_total["full"].mean()),
        "turnover_selection": float(win_sel["full"].mean()),
        "turnover_sizing":    float(win_size["full"].mean()),
    }
    denom = row["turnover_total"] if row["turnover_total"] > 0 else np.nan
    row["sizing_share"]    = float(row["turnover_sizing"]    / denom) if denom else 0.0
    row["selection_share"] = float(row["turnover_selection"] / denom) if denom else 0.0
    row["cost_share_of_gross"] = (
        float(row["cost_bps_yr"] / row["gross_ret_bps_yr"])
        if row["gross_ret_bps_yr"] > 0 else np.nan
    )

    # Per-bar CSV — restrict to IS ∪ OOS (drop pre-panel warmup + hold-out).
    keep_idx = win_net["full"].index
    bar_df = pd.DataFrame({
        "port_ret":       port_ret,
        "net_ret":        net_ret,
        "cost":           cost,
        "turnover":       attrib.total,
        "turn_selection": attrib.selection,
        "turn_sizing":    attrib.sizing,
    }).reindex(keep_idx)
    bar_df.to_csv(OUT_ROOT / f"{cell}_bar.csv")

    return row


# ---------------------------------------------------------------------- #
# Grid + gate
# ---------------------------------------------------------------------- #
SIZING_SHARE_GATE = 0.30    # if sizing share ≥ this in ≥ 2 cells → run EQW
CELLS_TRIP_GATE   = 2


def run(data_dir: Path | None = None) -> pd.DataFrame:
    data_dir = Path(data_dir) if data_dir else C.DATA_DIR
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    rows = [analyze_cell(mode, q, data_dir) for mode, q in CELLS]
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT_ROOT / "summary.csv", index=False)

    n_trip = int((summary["sizing_share"] >= SIZING_SHARE_GATE).sum())
    print(f"\nsizing_share ≥ {SIZING_SHARE_GATE:.0%} in {n_trip}/"
          f"{len(summary)} cells (gate: ≥ {CELLS_TRIP_GATE}).")
    if n_trip >= CELLS_TRIP_GATE:
        print("→ gate TRIPS: equal-weight rebook experiment is warranted.")
    else:
        print("→ gate holds: sizing channel is not the dominant cost driver.")

    for _, r in summary.iterrows():
        print(
            f"  {r['cell']:>8s}  "
            f"turn={r['turnover_total']:.3f}  "
            f"(sel={r['turnover_selection']:.3f}, "
            f"size={r['turnover_sizing']:.3f}, size%={r['sizing_share']:.0%})  "
            f"cost={r['cost_bps_yr']:.0f} bps/yr  "
            f"gross→net Sharpe (full)= {r['gross_sharpe_full']:+.3f} → "
            f"{r['net_sharpe_full']:+.3f}"
        )

    print(f"\nwrote {OUT_ROOT / 'summary.csv'}")
    return summary


if __name__ == "__main__":
    run()
