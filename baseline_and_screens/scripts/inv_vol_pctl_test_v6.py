"""
v6/scripts/inv_vol_pctl_test_v6.py
==================================
Post-close experiment on the solo defensive book — swap the plain
``inv_vol`` sizing for ``inv_vol_pctl``, which multiplies 1/σ by
exp(β·(0.5 − p_i,t)) where p_i,t is the per-ETF trailing-26w
percentile of the ETF's own σ history and β = ln(2).

Motivation (user)
-----------------
The current 1/σ kernel measures each ETF's σ on an absolute scale.
Two ETFs with identical σ get the same weight, but they may sit at
very different points *in their own recent history* — one might be
at its historical median (business as usual) while the other is
spiking to its historical peak (regime shift). Per-ETF trailing
percentile normalizes that: p = 0.5 → no adjustment, p = 0 → ×√2
upweight (ETF is unusually calm), p = 1 → ÷√2 downweight (ETF is
unusually agitated). Selection and hysteresis are unchanged, so
this is a *sizing-only* comparison against the Phase 11.2-closing
finalist (solo defensive @ long_q20 replace ε=0.20).

Locked configuration
--------------------
    cell         : long_q20 replace ε=0.20
    control      : inv_vol
    treatment    : inv_vol_pctl  (window=26, β=ln 2)
    cost         : 10 bp / side

Windows
-------
    IS       : ≤ 2023-12-31
    OOS      : 2024-01-01 → 2025-07-31
    full     : IS ∪ OOS
    hold-out : > 2025-07-31 (sealed)

Outputs
-------
    data/v6_static/inv_vol_pctl/summary.csv        — 2 books × 3 windows
    data/v6_static/inv_vol_pctl/bar_{book}.csv     — per-bar detail
    data/v6_static/inv_vol_pctl/mult_stats.csv     — per-bar multiplier
                                                     distribution stats
                                                     (mean, quantiles)
    data/v6_static/inv_vol_pctl/block_alloc.csv    — mean block share

Run
---
    python v6/scripts/inv_vol_pctl_test_v6.py
"""
from __future__ import annotations

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
import hysteresis_engine_v6_sizing as HS
import sizing_sweep_v6 as SS


# ---------------------------------------------------------------------- #
# Locked config
# ---------------------------------------------------------------------- #
CELL_MODE     = "long"
CELL_Q        = 0.20
CELL_RULE     = "replace"
CELL_EPSILON  = 0.20

CONTROL_SIZING   = "inv_vol"
TREATMENT_SIZING = "inv_vol_pctl"

COST_PER_TRADE = E.DEFAULT_COST_PER_TRADE
OUT_ROOT       = C.DATA_DIR / "v6_static" / "inv_vol_pctl"

IS_END    = C.IN_SAMPLE_END
OOS_START = C.OOS_START
OOS_END   = C.OOS_END


# ---------------------------------------------------------------------- #
# Window handling
# ---------------------------------------------------------------------- #
def _split_windows(net_ret: pd.Series) -> dict[str, pd.Series]:
    idx = net_ret.index
    is_mask  = idx <= IS_END
    oos_mask = (idx >= OOS_START) & (idx <= OOS_END)
    return {
        "IS":   net_ret[is_mask],
        "OOS":  net_ret[oos_mask],
        "full": net_ret[is_mask | oos_mask],
    }


def _window_stats(net: pd.Series, turnover: pd.Series | None) -> dict:
    n = int(len(net))
    if n < 2:
        return {"n_bars": n, "sharpe": 0.0, "ann_ret": 0.0, "ann_vol": 0.0,
                "cumret": 0.0, "cagr": 0.0, "max_dd": 0.0, "cost_bps_yr": 0.0}
    ann_vol = float(net.std(ddof=1)) * np.sqrt(C.WEEKS_PER_YEAR)
    ann_ret = float(net.mean()) * C.WEEKS_PER_YEAR
    sharpe  = (ann_ret / ann_vol) if ann_vol > 0 else 0.0
    cumret  = float(net.sum())
    n_years = max(n / C.WEEKS_PER_YEAR, 1e-3)
    cagr    = max(1.0 + cumret, 1e-9) ** (1.0 / n_years) - 1.0
    nav     = 1.0 + net.cumsum()
    cummax  = nav.cummax()
    max_dd  = float(((nav - cummax) / cummax).min())
    cost_bps_yr = (float(turnover.reindex(net.index).mean())
                   * COST_PER_TRADE * C.WEEKS_PER_YEAR * 1e4
                   if turnover is not None else 0.0)
    return {"n_bars": n, "sharpe": sharpe, "ann_ret": ann_ret,
            "ann_vol": ann_vol, "cumret": cumret, "cagr": cagr,
            "max_dd": max_dd, "cost_bps_yr": cost_bps_yr}


# ---------------------------------------------------------------------- #
# Multiplier diagnostic — how much is the pctl adjustment actually moving
# per-cell weights? Only defined on eligible cells with a full-window
# percentile (i.e., not in warmup).
# ---------------------------------------------------------------------- #
def _multiplier_stats(sigma: pd.DataFrame,
                      eligible: pd.DataFrame) -> pd.DataFrame:
    p = HS._sigma_trailing_percentile(sigma, window=HS.INV_VOL_PCTL_WINDOW)
    mult = np.exp(HS.INV_VOL_PCTL_BETA * (0.5 - p))
    # Only consider bars/cells where p is defined AND the cell is eligible.
    mask = p.notna() & eligible
    per_bar = []
    for t, row_mask in mask.iterrows():
        row_p    = p.loc[t][row_mask]
        row_mult = mult.loc[t][row_mask]
        if len(row_p) == 0:
            continue
        per_bar.append({
            "date":       t,
            "n_defined":  int(len(row_p)),
            "pct_p05":    float(row_p.quantile(0.05)),
            "pct_p50":    float(row_p.quantile(0.50)),
            "pct_p95":    float(row_p.quantile(0.95)),
            "mult_min":   float(row_mult.min()),
            "mult_p50":   float(row_mult.median()),
            "mult_max":   float(row_mult.max()),
            "mult_mean":  float(row_mult.mean()),
        })
    return pd.DataFrame(per_bar).set_index("date")


# ---------------------------------------------------------------------- #
# Top-level
# ---------------------------------------------------------------------- #
def run(data_dir: Path | None = None) -> pd.DataFrame:
    data_dir = Path(data_dir) if data_dir else C.DATA_DIR
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    shared    = SS._load_shared(data_dir)
    alpha     = SS._load_ensemble_alpha(data_dir, CELL_MODE, CELL_Q)
    block_tag = SS._load_block_tag(data_dir)

    print(f"Locked config: {CELL_MODE}_q{int(CELL_Q*100):02d} "
          f"{CELL_RULE} ε={CELL_EPSILON}   cost={COST_PER_TRADE*1e4:.0f} bp/side")
    print(f"  control   = {CONTROL_SIZING}")
    print(f"  treatment = {TREATMENT_SIZING}   "
          f"(window={HS.INV_VOL_PCTL_WINDOW}, β=ln 2 ≈ {HS.INV_VOL_PCTL_BETA:.4f})")
    print()

    # Build both books.
    books = {}
    for label, sizing in (("solo_defensive_inv_vol",       CONTROL_SIZING),
                          ("solo_defensive_inv_vol_pctl",  TREATMENT_SIZING)):
        W, N_t, K_t = HS.build_hysteresis_weights_sized(
            alpha, shared["sigma"], shared["membership"],
            q=CELL_Q, mode=CELL_MODE, epsilon=CELL_EPSILON,
            rule=CELL_RULE, sizing=sizing)
        res = E.run_book(W, shared["fwd_1w"],
                         cost_per_trade=COST_PER_TRADE, N_t=N_t, K_t=K_t)
        books[label] = {"res": res, "W": W}

    # -------------------- summary table ------------------------------
    rows = []
    for label, pack in books.items():
        for wname, series in _split_windows(pack["res"].net_ret).items():
            rows.append({"book": label, "window": wname,
                         **_window_stats(series, pack["res"].turnover)})
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT_ROOT / "summary.csv", index=False)

    # -------------------- print summary ------------------------------
    print("=" * 100)
    print("IS / OOS / full window summary (net of 10 bp/side)")
    print("=" * 100)
    for wname in ("IS", "OOS", "full"):
        print(f"\n[{wname}]")
        hdr = (f'{"book":>32s}  {"n":>4s}  {"Sharpe":>8s}  '
               f'{"CAGR":>8s}  {"max_DD":>8s}  {"ann_vol":>8s}  '
               f'{"cost_bps/yr":>12s}')
        print(hdr)
        print("-" * len(hdr))
        for label in books:
            r = summary[(summary["book"] == label) & (summary["window"] == wname)].iloc[0]
            print(f'{label:>32s}  {int(r["n_bars"]):>4d}  '
                  f'{r["sharpe"]:>+8.3f}  {r["cagr"]*100:>+7.2f}%  '
                  f'{r["max_dd"]*100:>+7.2f}%  {r["ann_vol"]*100:>7.2f}%  '
                  f'{r["cost_bps_yr"]:>12.1f}')

    # -------------------- Δ table ------------------------------------
    print()
    print("Δ (treatment − control) per window:")
    hdr = f'{"window":>7s}  {"ΔSharpe":>9s}  {"ΔCAGR pp":>9s}  {"ΔmaxDD pp":>10s}'
    print(hdr)
    print("-" * len(hdr))
    for wname in ("IS", "OOS", "full"):
        c = summary[(summary["book"] == "solo_defensive_inv_vol") &
                    (summary["window"] == wname)].iloc[0]
        t = summary[(summary["book"] == "solo_defensive_inv_vol_pctl") &
                    (summary["window"] == wname)].iloc[0]
        print(f"{wname:>7s}  {t['sharpe']-c['sharpe']:>+9.3f}  "
              f"{(t['cagr']-c['cagr'])*100:>+9.2f}  "
              f"{(t['max_dd']-c['max_dd'])*100:>+10.2f}")

    # -------------------- multiplier stats ---------------------------
    print()
    print("=" * 100)
    print("Multiplier distribution (per-bar, over eligible cells)")
    print("=" * 100)
    # Reproduce eligibility mask used inside the engine.
    S = shared["sigma"].reindex(index=alpha.index, columns=alpha.columns)
    M = (shared["membership"].reindex(index=alpha.index, columns=alpha.columns)
                                .astype("boolean").fillna(False).astype(bool))
    eligible = alpha.notna() & S.notna() & (S > 0.0) & M

    mult_df = _multiplier_stats(S, eligible)
    mult_df.to_csv(OUT_ROOT / "mult_stats.csv")

    is_mask   = mult_df.index <= IS_END
    oos_mask  = (mult_df.index >= OOS_START) & (mult_df.index <= OOS_END)
    full_mask = is_mask | oos_mask

    for wname, mask in (("IS", is_mask), ("OOS", oos_mask), ("full", full_mask)):
        sub = mult_df[mask]
        if len(sub) == 0:
            continue
        print(f"[{wname}]  n_bars={len(sub)}   "
              f"per-bar median-of-median mult = {sub['mult_p50'].median():.3f}   "
              f"mult range 5%-95% (avg per bar) = "
              f"[{sub['mult_min'].mean():.3f}, {sub['mult_max'].mean():.3f}]   "
              f"mult_mean = {sub['mult_mean'].mean():.3f}")

    # -------------------- persist per-bar detail + block-alloc -------
    for label, pack in books.items():
        pd.DataFrame({
            "port_ret":  pack["res"].port_ret,
            "net_ret":   pack["res"].net_ret,
            "turnover":  pack["res"].turnover,
            "K":         pack["res"].K_t,
            "N":         pack["res"].N_t,
        }).to_csv(OUT_ROOT / f"bar_{label}.csv")

    # Block allocation on IS + OOS separately (local helper — the SS
    # variant hard-codes IS filtering, which drops all rows when we
    # feed it an OOS-only W panel).
    def _block_alloc_local(W: pd.DataFrame,
                           block_tag: pd.Series) -> pd.Series:
        abs_W = W.abs()
        row_sum = abs_W.sum(axis=1).replace(0.0, np.nan)
        share = abs_W.div(row_sum, axis=0)
        tag = block_tag.reindex(share.columns).fillna("unknown")
        return share.T.groupby(tag).sum().T.mean(axis=0)

    block_rows = {}
    for label, pack in books.items():
        widx = pack["W"].index
        w_is  = widx <= IS_END
        w_oos = (widx >= OOS_START) & (widx <= OOS_END)
        w_full = w_is | w_oos
        for wname, wmask in (("IS", w_is), ("OOS", w_oos), ("full", w_full)):
            W_win = pack["W"].loc[wmask]
            block_rows[f"{label}__{wname}"] = _block_alloc_local(W_win, block_tag)
    block_df = pd.DataFrame(block_rows).fillna(0.0)
    block_df.to_csv(OUT_ROOT / "block_alloc.csv")

    print()
    print(f"wrote {OUT_ROOT / 'summary.csv'}")
    print(f"wrote {OUT_ROOT / 'mult_stats.csv'}")
    print(f"wrote {OUT_ROOT / 'block_alloc.csv'}")
    return summary


if __name__ == "__main__":
    run()
