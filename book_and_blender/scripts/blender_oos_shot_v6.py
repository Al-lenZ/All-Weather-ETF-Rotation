"""
v6/scripts/blender_oos_shot_v6.py
=================================
Phase 11.2 — one-shot OOS opening on the alpha_prop + ramp + fwd_4w_rv
finalist. Per user request, this is the "upper-bound" test: the
oracle blender uses actual next-4-week realized RV, so any Sharpe /
CAGR it earns on OOS is the ceiling of what a realistic HAR forecast
could reach.

Locked configuration (frozen BEFORE opening OOS — do not change)
----------------------------------------------------------------
    cell              : long_q20 replace ε=0.20
    aggressive kernel : alpha_prop
                        (w_i ∝ α_i − min(α_held) + rng/H, v4pool/v5)
    defensive kernel  : inv_vol
                        (w_i ∝ 1/σ_causal_26w, unchanged since Phase 9.2)
    schedule          : ramp (piecewise linear)
    gates             : lower = 0.30, upper = 0.90
    warmup_lambda     : 0.50
    percentile        : expanding causal rank, min_history = 26 bars
    vol_source        : fwd_4w_rv (mean of *actual weekly RV* over
                        bars t+1..t+4; NOT shifted trailing σ)
    transient NaN     : hold_through_transient_nan (post-warmup NaN
                        holds the last known percentile so holiday
                        weeks don't cause spurious λ churn)
    cost              : 10 bp / side

Any deviation from this config makes the OOS shot invalid — the whole
point of an OOS shot is a *one-shot, pre-registered* evaluation. If
we want to test something else we open a new hold-out.

Windows evaluated (from _common_v6)
------------------------------------
    IS       : bars ≤ 2023-12-31    (292 bars, ~5.6 yr)
    OOS      : 2024-01-01 → 2025-07-31   (82 bars, ~1.6 yr)
    full     : IS ∪ OOS   (374 bars)
    hold-out : > 2025-07-31   (kept sealed — not evaluated)

Books compared side-by-side in every window
--------------------------------------------
    solo_defensive       : the fallback baseline
    solo_aggressive_ap   : the aggressive leg alone
    blend_fwd_4w_rv      : the oracle blender under test

Outputs
-------
    data/v6_static/oos_shot_ap/summary.csv           — 3 books × 3 windows
    data/v6_static/oos_shot_ap/bar_{book}.csv        — per-bar detail
                                                       (IS + OOS combined)
    data/v6_static/oos_shot_ap/lambdas.csv           — λ + score + pct
                                                       for blend, full-sample
    data/v6_static/oos_shot_ap/regime_by_window.csv  — λ regime histogram
    data/v6_static/oos_shot_ap/high_vol_spread.csv   — def−agg return in
                                                       high-vol weeks, per
                                                       window

Run
---
    python v6/scripts/blender_oos_shot_v6.py
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
import cost_attribution_v6 as CA
import two_book_blender_v6 as B
import sizing_sweep_v6 as SS


# ---------------------------------------------------------------------- #
# Locked configuration
# ---------------------------------------------------------------------- #
CELL_MODE     = "long"
CELL_Q        = 0.20
CELL_RULE     = "replace"
CELL_EPSILON  = 0.20

AGG_SIZING    = "alpha_prop"
DEF_SIZING    = "inv_vol"

SCHEDULE      = "ramp"
LOWER_GATE    = 0.30
UPPER_GATE    = 0.90
WARMUP_LAMBDA = 0.50
MIN_HISTORY   = 26
VOL_SOURCE    = "fwd_4w_rv"

COST_PER_TRADE = E.DEFAULT_COST_PER_TRADE
OUT_ROOT       = C.DATA_DIR / "v6_static" / "oos_shot_ap"

BLEND_LABEL   = "blend_fwd_4w_rv"


# ---------------------------------------------------------------------- #
# Window definitions
# ---------------------------------------------------------------------- #
IS_END    = C.IN_SAMPLE_END
OOS_START = C.OOS_START
OOS_END   = C.OOS_END


def _split_windows(net_ret: pd.Series) -> dict[str, pd.Series]:
    idx = net_ret.index
    is_mask   = idx <= IS_END
    oos_mask  = (idx >= OOS_START) & (idx <= OOS_END)
    full_mask = is_mask | oos_mask
    return {
        "IS":   net_ret[is_mask],
        "OOS":  net_ret[oos_mask],
        "full": net_ret[full_mask],
    }


def _window_stats(net: pd.Series, turnover: pd.Series | None) -> dict:
    """Sharpe / CAGR / max_dd / ann_vol / cost on a window."""
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
# Build the three books
# ---------------------------------------------------------------------- #
def _build_book(alpha, shared, sizing):
    return HS.build_hysteresis_weights_sized(
        alpha, shared["sigma"], shared["membership"],
        q=CELL_Q, mode=CELL_MODE, epsilon=CELL_EPSILON,
        rule=CELL_RULE, sizing=sizing,
    )


def _score_book(W, shared, N_t, K_t):
    return E.run_book(W, shared["fwd_1w"], cost_per_trade=COST_PER_TRADE,
                      N_t=N_t, K_t=K_t)


def _build_blender_lambda(shared, block_tag, rv_panel):
    score_raw = B.equity_risk_score_raw(
        shared["sigma"], shared["membership"], block_tag,
        vol_source=VOL_SOURCE, rv_panel=rv_panel)
    score_pct = B.score_to_percentile(score_raw, min_history=MIN_HISTORY)
    score_pct = B.hold_through_transient_nan(score_pct)
    lam = B.lambda_schedule(
        score_pct,
        lower_gate=LOWER_GATE, upper_gate=UPPER_GATE,
        warmup_lambda=WARMUP_LAMBDA, invert=False)
    return score_raw, score_pct, lam


# ---------------------------------------------------------------------- #
# Regime histogram + high-vol spread per window
# ---------------------------------------------------------------------- #
def _regime_hist(lam: pd.Series, mask: pd.Series) -> dict:
    l = lam[mask].dropna()
    n = len(l)
    return {
        "n_bars":         n,
        "share_full_agg": float((l == 1.0).mean()) if n else float("nan"),
        "share_full_def": float((l == 0.0).mean()) if n else float("nan"),
        "share_ramp":     float(((l > 0.0) & (l < 1.0)).mean()) if n else float("nan"),
        "mean_lambda":    float(l.mean()) if n else float("nan"),
    }


def _def_minus_agg_high_vol(spread: pd.Series, pct: pd.Series,
                            mask: pd.Series) -> dict:
    m = mask & (pct.reindex(spread.index) > UPPER_GATE) & spread.notna()
    n = int(m.sum())
    if n == 0:
        return {"n_high_bars": 0,
                "mean_def_minus_agg_pct_wk": float("nan"),
                "annualized_pct": float("nan"),
                "share_of_window": 0.0}
    def_minus_agg = -spread
    mean_pct = float(def_minus_agg[m].mean() * 100)
    return {
        "n_high_bars":              n,
        "mean_def_minus_agg_pct_wk": mean_pct,
        "annualized_pct":           mean_pct * C.WEEKS_PER_YEAR,
        "share_of_window":          n / int(mask.sum()),
    }


# ---------------------------------------------------------------------- #
# Top-level
# ---------------------------------------------------------------------- #
def run(data_dir: Path | None = None) -> pd.DataFrame:
    data_dir = Path(data_dir) if data_dir else C.DATA_DIR
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    shared    = SS._load_shared(data_dir)
    alpha     = SS._load_ensemble_alpha(data_dir, CELL_MODE, CELL_Q)
    block_tag = SS._load_block_tag(data_dir)
    rv_panel  = pd.read_parquet(data_dir / "vol_forecast_v6" / "rv_panel.parquet")

    print("Locked config:")
    print(f"  cell         = {CELL_MODE}_q{int(CELL_Q*100):02d} "
          f"{CELL_RULE} ε={CELL_EPSILON}")
    print(f"  aggressive   = {AGG_SIZING}    defensive = {DEF_SIZING}")
    print(f"  schedule     = {SCHEDULE}   gates = ({LOWER_GATE}, {UPPER_GATE})   "
          f"warmup_λ = {WARMUP_LAMBDA}")
    print(f"  vol_source   = {VOL_SOURCE}  (min_history = {MIN_HISTORY})")
    print()

    # Build the two solo books.
    W_agg, N_t, K_t = _build_book(alpha, shared, sizing=AGG_SIZING)
    W_def, _, _      = _build_book(alpha, shared, sizing=DEF_SIZING)

    # Build the blender λ + score panels.
    score_raw, score_pct, lam = _build_blender_lambda(shared, block_tag, rv_panel)
    W_blend = B.blend_weights(W_agg, W_def, lam)

    # Score all three books over the full time series.
    res_def   = _score_book(W_def,   shared, N_t, K_t)
    res_agg   = _score_book(W_agg,   shared, N_t, K_t)
    res_blend = _score_book(W_blend, shared, N_t, K_t)

    books = {
        "solo_defensive":     res_def,
        "solo_aggressive_ap": res_agg,
        BLEND_LABEL:          res_blend,
    }

    # -------------------- summary table ------------------------------
    summary_rows = []
    for name, res in books.items():
        for window_name, series in _split_windows(res.net_ret).items():
            stats = _window_stats(series, res.turnover)
            summary_rows.append({
                "book":    name,
                "window":  window_name,
                **stats,
            })
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(OUT_ROOT / "summary.csv", index=False)

    # -------------------- print summary ------------------------------
    print("=" * 100)
    print("IS / OOS / full window summary (net of 10 bp/side)")
    print("=" * 100)
    for window in ("IS", "OOS", "full"):
        print(f"\n[{window}]")
        header = (f'{"book":>22s}  {"n":>4s}  {"Sharpe":>8s}  '
                  f'{"CAGR":>8s}  {"max_DD":>8s}  {"ann_vol":>8s}  '
                  f'{"cost_bps/yr":>12s}')
        print(header)
        print("-" * len(header))
        for name in books:
            r = summary[(summary["book"] == name) & (summary["window"] == window)].iloc[0]
            print(f'{name:>22s}  {int(r["n_bars"]):>4d}  '
                  f'{r["sharpe"]:>+8.3f}  {r["cagr"]*100:>+7.2f}%  '
                  f'{r["max_dd"]*100:>+7.2f}%  {r["ann_vol"]*100:>7.2f}%  '
                  f'{r["cost_bps_yr"]:>12.1f}')

    # -------------------- persist per-bar detail ---------------------
    for name, res in books.items():
        pd.DataFrame({
            "port_ret":  res.port_ret,
            "net_ret":   res.net_ret,
            "turnover":  res.turnover,
            "K":         res.K_t,
            "N":         res.N_t,
        }).to_csv(OUT_ROOT / f"bar_{name}.csv")

    # -------------------- persist λ + score --------------------------
    pd.DataFrame({
        "score_raw":  score_raw,
        "score_pct":  score_pct,
        "lambda":     lam,
    }).to_csv(OUT_ROOT / "lambdas.csv")

    # -------------------- λ regime histogram per window ---------------
    print()
    print("=" * 100)
    print("λ regime by window (blender only)")
    print("=" * 100)
    idx = lam.index
    windows_masks = {
        "IS":   pd.Series(idx <= IS_END, index=idx),
        "OOS":  pd.Series((idx >= OOS_START) & (idx <= OOS_END), index=idx),
        "full": pd.Series((idx <= OOS_END), index=idx),
    }
    reg_rows = []
    header = (f'{"window":>8s}  {"n_bars":>7s}  {"mean_lambda":>12s}  '
              f'{"share_full_agg":>15s}  {"share_full_def":>15s}  '
              f'{"share_ramp":>11s}')
    print(header)
    print("-" * len(header))
    for wname, mask in windows_masks.items():
        stats = _regime_hist(lam, mask)
        reg_rows.append({"window": wname, **stats})
        print(f'{wname:>8s}  {int(stats["n_bars"]):>7d}  '
              f'{stats["mean_lambda"]:>12.3f}  '
              f'{stats["share_full_agg"]:>15.1%}  '
              f'{stats["share_full_def"]:>15.1%}  '
              f'{stats["share_ramp"]:>11.1%}')
    pd.DataFrame(reg_rows).to_csv(OUT_ROOT / "regime_by_window.csv", index=False)

    # -------------------- high-vol def-agg spread per window ---------
    print()
    print("=" * 100)
    print("Def − agg_ap return in high-vol weeks (pct > 0.9), per window")
    print("=" * 100)
    header = (f'{"window":>8s}  {"n_high":>7s}  '
              f'{"share_of_window":>16s}  '
              f'{"mean_pct/wk":>13s}  {"annualized%":>13s}')
    print(header)
    print("-" * len(header))
    spread = (res_agg.net_ret - res_def.net_ret).rename("spread")
    hv_rows = []
    for wname, mask in windows_masks.items():
        r = _def_minus_agg_high_vol(spread, score_pct, mask)
        hv_rows.append({"window": wname, **r})
        print(f'{wname:>8s}  {int(r["n_high_bars"]):>7d}  '
              f'{r["share_of_window"]:>16.1%}  '
              f'{r["mean_def_minus_agg_pct_wk"]:>+13.4f}  '
              f'{r["annualized_pct"]:>+13.2f}')
    pd.DataFrame(hv_rows).to_csv(OUT_ROOT / "high_vol_spread.csv", index=False)

    # -------------------- OOS pass-rule verdict ----------------------
    def_oos = summary[(summary["book"] == "solo_defensive")
                       & (summary["window"] == "OOS")].iloc[0]
    ble_oos = summary[(summary["book"] == BLEND_LABEL)
                       & (summary["window"] == "OOS")].iloc[0]
    agg_oos = summary[(summary["book"] == "solo_aggressive_ap")
                       & (summary["window"] == "OOS")].iloc[0]

    print()
    print("=" * 100)
    print("OOS verdict — blender vs defensive")
    print("=" * 100)
    d_sh = ble_oos["sharpe"] - def_oos["sharpe"]
    d_cg = (ble_oos["cagr"] - def_oos["cagr"]) * 100
    d_dd = (ble_oos["max_dd"] - def_oos["max_dd"]) * 100
    print(f'  OOS Δ Sharpe  (blender − defensive) = {d_sh:+.3f}')
    print(f'  OOS Δ CAGR    (pp)                  = {d_cg:+.2f}')
    print(f'  OOS Δ max_DD  (pp; negative = worse) = {d_dd:+.2f}')
    print()
    print(f'  Blender OOS: Sharpe {ble_oos["sharpe"]:+.3f} / '
          f'CAGR {ble_oos["cagr"]*100:+.2f}% / DD {ble_oos["max_dd"]*100:+.2f}%')
    print(f'  Defensive OOS: Sharpe {def_oos["sharpe"]:+.3f} / '
          f'CAGR {def_oos["cagr"]*100:+.2f}% / DD {def_oos["max_dd"]*100:+.2f}%')
    print(f'  Aggressive_ap OOS: Sharpe {agg_oos["sharpe"]:+.3f} / '
          f'CAGR {agg_oos["cagr"]*100:+.2f}% / DD {agg_oos["max_dd"]*100:+.2f}%')

    print()
    print(f"wrote {OUT_ROOT / 'summary.csv'}")
    print(f"wrote {OUT_ROOT / 'lambdas.csv'}")
    print(f"wrote {OUT_ROOT / 'regime_by_window.csv'}")
    print(f"wrote {OUT_ROOT / 'high_vol_spread.csv'}")

    return summary


if __name__ == "__main__":
    run()
