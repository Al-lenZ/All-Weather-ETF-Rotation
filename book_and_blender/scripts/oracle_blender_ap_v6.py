"""
v6/scripts/oracle_blender_ap_v6.py
==================================
Phase 11.2 — last-round blender test using the **v4pool/v5 α-proportional
sizing** for the aggressive book instead of rank_prop.

Motivation
----------
Every prior blender test used ``rank_prop`` for the aggressive book —
weights proportional to local α rank. That kernel is sign-safe under
row-z α but ignores the *magnitude* of α, which is potentially the
most informative axis when α actually distinguishes names cleanly.

``alpha_prop`` (formula from ``v5/static/xs_engine_v5.weights_topk_alphaprop_long``
and ``v4pool/xs_ic_pipeline/scripts/book_xs.py``) uses α levels:

    H     = |held|
    rng   = max(α_held) − min(α_held)
    ε     = max(rng / H, 1e-12)
    p_i   = α_i − min(α_held) + ε
    w_i   = p_i / Σp

Effect: when α has meaningful spread, top-α held names get
disproportionately more weight than the rank_prop's linear ramp gives
them. Expected direction: even higher CAGR, even higher DD, Sharpe
depending on whether the added tilt tracks realized returns.

Variants (per user spec)
------------------------
No inverted variants, no causal-source blend variants. Only:

    solo_defensive       : W = W_def (1/σ, unchanged)
    solo_aggressive_ap   : W = W_agg (alpha_prop, this run's aggressive)
    blend_fwd_1w_rv      : ramp, 1-week RV oracle
    blend_fwd_4w_rv      : ramp, 4-week RV oracle
    binary_fwd_1w_rv     : binary, 1-week RV oracle
    binary_fwd_4w_rv     : binary, 4-week RV oracle
    best_fixed_lambda    : counterfactual (fixed λ chosen by IS Sharpe)

Sample discipline
-----------------
Per [[feedback-oos-discipline]], IS-only (bars ≤ 2023-12-31). Every
headline net of 10 bp/side per [[feedback-backtests-cost-on]].

Outputs
-------
    data/v6_static/oracle_blender_ap/summary.csv        — 7 rows
    data/v6_static/oracle_blender_ap/bar_{variant}.csv  — per-bar IS
    data/v6_static/oracle_blender_ap/lambdas.csv        — λ + score + pct
    data/v6_static/oracle_blender_ap/fixed_lambda_sweep.csv
    data/v6_static/oracle_blender_ap/block_alloc.csv
    data/v6_static/oracle_blender_ap/diag_transitions.csv  — switching
                                                             cost + high-
                                                             vol def-agg
Also compares vs the rank_prop run in stdout:
    - solo aggressive: alpha_prop vs rank_prop
    - top blender variant: alpha_prop vs rank_prop

Run
---
    python v6/scripts/oracle_blender_ap_v6.py
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
# Fixed knobs (matches oracle_blender_v6 so results are directly comparable)
# ---------------------------------------------------------------------- #
MODE     = "long"
Q        = 0.20
RULE     = "replace"
EPSILON  = 0.20

# Aggressive kernel — the axis being tested this round.
AGG_SIZING = "alpha_prop"
DEF_SIZING = "inv_vol"

COST_PER_TRADE = E.DEFAULT_COST_PER_TRADE
WARMUP_LAMBDA  = 0.5

OUT_ROOT = C.DATA_DIR / "v6_static" / "oracle_blender_ap"

# Ramp + binary variants — no inverted, no causal (user spec).
RAMP_VARIANTS = (
    ("blend_fwd_1w_rv", "fwd_1w_rv"),
    ("blend_fwd_4w_rv", "fwd_4w_rv"),
)
BINARY_VARIANTS = (
    ("binary_fwd_1w_rv", "fwd_1w_rv"),
    ("binary_fwd_4w_rv", "fwd_4w_rv"),
)

FIXED_LAMBDA_GRID = np.round(np.arange(0.0, 1.0 + 1e-9, 0.05), 2)


# ---------------------------------------------------------------------- #
# Small helpers — copied minimally from oracle_blender_v6 so this driver
# is self-sufficient when a comparison run is being made.
# ---------------------------------------------------------------------- #
def _build_solo_weights(alpha, shared, sizing):
    return HS.build_hysteresis_weights_sized(
        alpha, shared["sigma"], shared["membership"],
        q=Q, mode=MODE, epsilon=EPSILON, rule=RULE, sizing=sizing,
    )


def _score_book(W, shared, N_t, K_t):
    return E.run_book(W, shared["fwd_1w"],
                      cost_per_trade=COST_PER_TRADE, N_t=N_t, K_t=K_t)


def _summarize(res, W, block_tag, label, vol_source, fixed_lambda):
    attrib = CA.decompose_turnover(res.weights)
    cost = attrib.total * COST_PER_TRADE

    net_stats   = SS._is_stats(res.net_ret)
    gross_stats = SS._is_stats(res.port_ret)

    is_idx   = res.net_ret.index[res.net_ret.index <= C.IN_SAMPLE_END]
    is_total = attrib.total.reindex(is_idx)
    is_sel   = attrib.selection.reindex(is_idx)
    is_size  = attrib.sizing.reindex(is_idx)
    is_cost  = cost.reindex(is_idx)

    conc = SS._weight_concentration(W)
    block_alloc = SS._block_allocation(W, block_tag)

    denom = float(is_total.mean()) if float(is_total.mean()) > 0 else np.nan
    row = {
        "label":       label,
        "vol_source":  vol_source if vol_source else "",
        "fixed_lambda": fixed_lambda if fixed_lambda is not None else np.nan,
        "cell":        SS._cell_tag(MODE, Q),
        "rule":        RULE,
        "epsilon":     EPSILON,
        "n_bars_is":   int(net_stats["n_bars"]),
        "net_sharpe_is":     net_stats["sharpe"],
        "gross_sharpe_is":   gross_stats["sharpe"],
        "net_ann_ret_is":    net_stats["ann_ret"],
        "gross_ann_ret_is":  gross_stats["ann_ret"],
        "net_cagr_is":       net_stats["cagr"],
        "gross_cagr_is":     gross_stats["cagr"],
        "net_cumret_is":     net_stats["cumret"],
        "net_max_dd_is":     net_stats["max_dd"],
        "gross_max_dd_is":   gross_stats["max_dd"],
        "annual_vol_is":     net_stats["ann_vol"],
        "cost_bps_yr_is":    float(is_cost.mean() * C.WEEKS_PER_YEAR * 1e4),
        "turnover_total":    float(is_total.mean()),
        "turnover_selection": float(is_sel.mean()),
        "turnover_sizing":    float(is_size.mean()),
        "sizing_share":      float(is_size.mean() / denom) if denom else 0.0,
        "selection_share":   float(is_sel.mean()  / denom) if denom else 0.0,
        **{f"conc_{k}": v for k, v in conc.items()},
        "held_mean":         float((W.loc[is_idx] != 0).sum(axis=1).mean()),
    }
    return row, block_alloc


def _write_bar_detail(res, out_path):
    is_idx = res.net_ret.index[res.net_ret.index <= C.IN_SAMPLE_END]
    pd.DataFrame({
        "port_ret":  res.port_ret,
        "net_ret":   res.net_ret,
        "turnover":  res.turnover,
        "K":         res.K_t,
        "N":         res.N_t,
    }).reindex(is_idx).to_csv(out_path)


def _print_row(row):
    print(
        f"  {row['label']:>22s}  "
        f"IS net Sharpe = {row['net_sharpe_is']:+.3f}   "
        f"IS CAGR = {row['net_cagr_is']*100:+.2f}%   "
        f"IS max DD = {row['net_max_dd_is']*100:+.2f}%   "
        f"ann vol = {row['annual_vol_is']*100:.2f}%   "
        f"eff N = {row['conc_mean_eff_N']:.1f}"
    )


def _best_fixed_lambda(W_agg, W_def, shared, N_t, K_t):
    rows = []
    for lam in FIXED_LAMBDA_GRID:
        W_mix = lam * W_agg + (1.0 - lam) * W_def
        res = _score_book(W_mix, shared, N_t, K_t)
        stats = SS._is_stats(res.net_ret)
        rows.append({
            "fixed_lambda":    float(lam),
            "net_sharpe_is":   stats["sharpe"],
            "net_cagr_is":     stats["cagr"],
            "net_max_dd_is":   stats["max_dd"],
            "annual_vol_is":   stats["ann_vol"],
        })
    grid = pd.DataFrame(rows)
    best = float(grid.loc[grid["net_sharpe_is"].idxmax(), "fixed_lambda"])
    return best, grid


# ---------------------------------------------------------------------- #
# Inline transition + high-vol def-agg diagnostic
# ---------------------------------------------------------------------- #
def _transition_diag(variant, lam_series, bar_df, spread, is_years,
                     cost_per_trade):
    lam_is = lam_series.reindex(spread.index).astype(float)
    prev   = lam_is.shift(1)
    trans_mask = (lam_is != prev) & lam_is.notna() & prev.notna()
    def_now  = lam_is == 0.0
    def_prev = prev   == 0.0
    enter = def_now & (~def_prev) & prev.notna()
    exit_ = (~def_now) & def_prev & lam_is.notna()

    def_change = def_now != def_now.shift(1, fill_value=False)
    run_id = def_change.cumsum()
    run_lens = def_now.groupby(run_id).sum()
    def_runs = run_lens[run_lens > 0]
    dwell_mean = float(def_runs.mean()) if len(def_runs) else 0.0
    dwell_max  = int(def_runs.max()) if len(def_runs) else 0

    turn = bar_df["turnover"].reindex(spread.index)
    turn_trans = float(turn[trans_mask].mean()) if trans_mask.any() else float("nan")
    turn_other = float(turn[~trans_mask & turn.notna()].mean())
    cost_trans = float(turn[trans_mask].sum() * cost_per_trade)
    cost_trans_bps_yr = cost_trans / is_years * 1e4

    return {
        "variant":          variant,
        "enter_per_yr":     float(enter.sum()) / is_years,
        "exit_per_yr":      float(exit_.sum()) / is_years,
        "switches_per_yr":  float(trans_mask.sum()) / is_years,
        "defensive_frac":   float(def_now.mean()),
        "dwell_mean":       dwell_mean,
        "dwell_max":        dwell_max,
        "turn_trans_bar":   turn_trans,
        "turn_other_bar":   turn_other,
        "cost_trans_bps_per_yr": cost_trans_bps_yr,
    }


def _high_vol_def_minus_agg(spread, score_pct_by_signal):
    """def-agg = − spread. Grouped by 'high' regime (pct > 0.9) per signal."""
    rows = []
    def_minus_agg = -spread
    for signal, pct in score_pct_by_signal.items():
        m = (pct.reindex(spread.index) > 0.90) & spread.notna()
        n = int(m.sum())
        mean_pct_wk = (def_minus_agg[m].mean() * 100) if n else float("nan")
        rows.append({
            "signal":     signal,
            "n_high_bars": n,
            "mean_def_minus_agg_pct_wk": mean_pct_wk,
            "annualized_pct": mean_pct_wk * C.WEEKS_PER_YEAR,
            "share_of_IS": n / len(spread) if len(spread) else 0.0,
        })
    return rows


# ---------------------------------------------------------------------- #
# Top-level
# ---------------------------------------------------------------------- #
def run(data_dir: Path | None = None) -> pd.DataFrame:
    data_dir = Path(data_dir) if data_dir else C.DATA_DIR
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    shared    = SS._load_shared(data_dir)
    alpha     = SS._load_ensemble_alpha(data_dir, MODE, Q)
    block_tag = SS._load_block_tag(data_dir)
    rv_panel  = pd.read_parquet(data_dir / "vol_forecast_v6" / "rv_panel.parquet")

    print("Building solo book weights…")
    print(f"  aggressive = {AGG_SIZING},  defensive = {DEF_SIZING}")
    W_agg, N_t, K_t = _build_solo_weights(alpha, shared, sizing=AGG_SIZING)
    W_def, N_ref, K_ref = _build_solo_weights(alpha, shared, sizing=DEF_SIZING)
    if not N_t.equals(N_ref) or not K_t.equals(K_ref):
        raise AssertionError("aggressive vs defensive selection diverged")

    rows: list[dict] = []
    block_rows: dict[str, pd.Series] = {}
    lambda_records: dict[str, pd.DataFrame] = {}

    print("\nSolo books:")
    for label, W in (("solo_defensive", W_def),
                     ("solo_aggressive_ap", W_agg)):
        res = _score_book(W, shared, N_t, K_t)
        row, blk = _summarize(res, W, block_tag, label, None, None)
        rows.append(row)
        block_rows[label] = blk
        _write_bar_detail(res, OUT_ROOT / f"bar_{label}.csv")
        _print_row(row)

    # -------------------- ramp blend variants ---------------------
    print("\nRamp blend variants:")
    for label, vol_source in RAMP_VARIANTS:
        score_raw = B.equity_risk_score_raw(
            shared["sigma"], shared["membership"], block_tag,
            vol_source=vol_source, rv_panel=rv_panel)
        score_pct = B.score_to_percentile(score_raw, min_history=B.MIN_HISTORY)
        score_pct = B.hold_through_transient_nan(score_pct)
        lam = B.lambda_schedule(score_pct, warmup_lambda=WARMUP_LAMBDA)
        lambda_records[label] = pd.DataFrame({
            "score_raw":  score_raw,
            "score_pct":  score_pct,
            "lambda":     lam,
        })

        W_blend = B.blend_weights(W_agg, W_def, lam)
        res = _score_book(W_blend, shared, N_t, K_t)
        row, blk = _summarize(res, W_blend, block_tag, label, vol_source, None)
        rows.append(row)
        block_rows[label] = blk
        _write_bar_detail(res, OUT_ROOT / f"bar_{label}.csv")
        _print_row(row)

    # -------------------- binary blend variants -------------------
    print("\nBinary blend variants (hard cutoff at pct = 0.9):")
    for label, vol_source in BINARY_VARIANTS:
        score_raw = B.equity_risk_score_raw(
            shared["sigma"], shared["membership"], block_tag,
            vol_source=vol_source, rv_panel=rv_panel)
        score_pct = B.score_to_percentile(score_raw, min_history=B.MIN_HISTORY)
        score_pct = B.hold_through_transient_nan(score_pct)
        lam = B.binary_lambda_schedule(
            score_pct, upper_gate=B.UPPER_GATE, warmup_lambda=WARMUP_LAMBDA)
        lambda_records[label] = pd.DataFrame({
            "score_raw":  score_raw,
            "score_pct":  score_pct,
            "lambda":     lam,
        })

        W_blend = B.blend_weights(W_agg, W_def, lam)
        res = _score_book(W_blend, shared, N_t, K_t)
        row, blk = _summarize(res, W_blend, block_tag, label, vol_source, None)
        rows.append(row)
        block_rows[label] = blk
        _write_bar_detail(res, OUT_ROOT / f"bar_{label}.csv")
        _print_row(row)

    # -------------------- best-fixed-λ counterfactual -------------
    print("\nBest-fixed-λ counterfactual:")
    best_lam, grid = _best_fixed_lambda(W_agg, W_def, shared, N_t, K_t)
    grid.to_csv(OUT_ROOT / "fixed_lambda_sweep.csv", index=False)
    print(f"  best fixed λ = {best_lam:.2f}   IS Sharpe = "
          f"{grid['net_sharpe_is'].max():+.3f}")
    W_best = best_lam * W_agg + (1.0 - best_lam) * W_def
    res = _score_book(W_best, shared, N_t, K_t)
    row, blk = _summarize(res, W_best, block_tag, "best_fixed_lambda",
                          None, best_lam)
    rows.append(row)
    block_rows["best_fixed_lambda"] = blk
    _write_bar_detail(res, OUT_ROOT / "bar_best_fixed_lambda.csv")
    _print_row(row)

    # -------------------- persist summary + block + λ side-tables -
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT_ROOT / "summary.csv", index=False)

    block_df = pd.DataFrame({k: v for k, v in block_rows.items()}).fillna(0.0)
    order = ["solo_defensive", "solo_aggressive_ap",
             "blend_fwd_1w_rv", "blend_fwd_4w_rv",
             "binary_fwd_1w_rv", "binary_fwd_4w_rv",
             "best_fixed_lambda"]
    block_df = block_df[[c for c in order if c in block_df.columns]]
    block_df.to_csv(OUT_ROOT / "block_alloc.csv")

    lam_df = pd.concat({k: v for k, v in lambda_records.items()},
                      names=["variant", "date"])
    lam_df.to_csv(OUT_ROOT / "lambdas.csv")

    # -------------------- inline transition + high-vol diagnostic --
    print()
    print("=" * 100)
    print("Switching-cost diagnostic (blend variants only)")
    print("=" * 100)

    solo_def_ret = pd.read_csv(OUT_ROOT / "bar_solo_defensive.csv",
                               index_col=0, parse_dates=True)["net_ret"]
    solo_agg_ret = pd.read_csv(OUT_ROOT / "bar_solo_aggressive_ap.csv",
                               index_col=0, parse_dates=True)["net_ret"]
    spread = (solo_agg_ret - solo_def_ret).rename("spread")
    is_mask = spread.index <= C.IN_SAMPLE_END
    spread = spread[is_mask]
    is_years = len(spread) / C.WEEKS_PER_YEAR
    print(f"IS bars: {len(spread)}   IS years: {is_years:.2f}")
    print(f"mean spread (agg_ap − def) = {spread.mean()*100:+.4f}%/wk  "
          f"= {spread.mean()*100*C.WEEKS_PER_YEAR:+.2f}%/yr")

    diag_rows = []
    hdr = (f'{"variant":>22s}  {"ent/yr":>7s}  {"exit/yr":>7s}  '
           f'{"switch/yr":>10s}  {"def_frac":>9s}  '
           f'{"dwell_mean":>11s}  {"dwell_max":>10s}  '
           f'{"turn_trans":>11s}  {"turn_other":>11s}  {"cost_trans_bps/yr":>18s}')
    print()
    print(hdr)
    print("-" * len(hdr))
    for variant, lam_rec in lambda_records.items():
        bar_df = pd.read_csv(OUT_ROOT / f"bar_{variant}.csv",
                             index_col=0, parse_dates=True)
        row = _transition_diag(variant, lam_rec["lambda"], bar_df,
                               spread, is_years, COST_PER_TRADE)
        diag_rows.append(row)
        print(f'{row["variant"]:>22s}  '
              f'{row["enter_per_yr"]:>7.2f}  '
              f'{row["exit_per_yr"]:>7.2f}  '
              f'{row["switches_per_yr"]:>10.2f}  '
              f'{row["defensive_frac"]:>9.1%}  '
              f'{row["dwell_mean"]:>11.2f}  '
              f'{row["dwell_max"]:>10d}  '
              f'{row["turn_trans_bar"]:>11.4f}  '
              f'{row["turn_other_bar"]:>11.4f}  '
              f'{row["cost_trans_bps_per_yr"]:>18.1f}')

    # High-vol def-agg spread (annualized over high-vol bars only)
    print()
    print("Defensive − aggressive_ap return in high-vol weeks (pct > 0.9)")
    hv_rows = _high_vol_def_minus_agg(
        spread,
        {vs: lambda_records[label]["score_pct"]
         for label, vs in list(RAMP_VARIANTS) + list(BINARY_VARIANTS)
         if label in lambda_records}
    )
    # Dedup — 1w_rv appears in both ramp and binary lists with same pct.
    seen = set()
    for r in hv_rows:
        if r["signal"] in seen:
            continue
        seen.add(r["signal"])
        print(f'  {r["signal"]:>10s}  n_high = {r["n_high_bars"]:>3d}  '
              f'mean(def−agg) = {r["mean_def_minus_agg_pct_wk"]:+.4f}%/wk  '
              f'annualized (on high-vol subset) = {r["annualized_pct"]:+.2f}%   '
              f'share of IS = {r["share_of_IS"]:.1%}')

    # Persist the diagnostic tables.
    diag_df = pd.DataFrame(diag_rows)
    hv_df   = pd.DataFrame([r for r in hv_rows if r["signal"] not in {"causal"}])
    diag_df["section"] = "transitions"
    hv_df["section"]   = "high_vol_def_minus_agg"
    combined = pd.concat([
        diag_df.reindex(columns=["section"] + [c for c in diag_df.columns if c != "section"]),
        hv_df.reindex(columns=["section"] + [c for c in hv_df.columns if c != "section"]),
    ], ignore_index=True)
    combined.to_csv(OUT_ROOT / "diag_transitions.csv", index=False)

    print()
    print(f"wrote {OUT_ROOT / 'summary.csv'}  ({len(summary)} rows)")
    print(f"wrote {OUT_ROOT / 'diag_transitions.csv'}")
    return summary


if __name__ == "__main__":
    run()
