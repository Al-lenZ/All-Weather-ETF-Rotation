"""
v6/scripts/oracle_blender_v6.py
===============================
Phase 11.2 — two-book oracle vs realistic blender test.

Design (per user spec)
----------------------
Two books, same selection + hysteresis, differ only in sizing kernel:

    aggressive : rank_prop  (Phase 11.1 treatment)
    defensive  : inv_vol    (Phase 9.2 baseline)

Blended per-bar: W = λ·W_agg + (1−λ)·W_def, with λ driven by the
equity-block risk score's expanding causal percentile rank via a
piecewise-linear schedule:

    pct < 0.3         →  λ = 1
    0.3 ≤ pct ≤ 0.9   →  λ = (0.9 − pct) / 0.6
    pct > 0.9         →  λ = 0

Score = equal-weight mean of σ across equity-block member ETFs
(broad_cn, sector_cn, smallcap_cn, cross_border_dm, cross_border_hk).
See ``two_book_blender_v6`` for the full construction.

Variants compared
-----------------
    solo_defensive        : W = W_def   (Phase 11.1 control — 1/σ alone)
    solo_aggressive       : W = W_agg   (Phase 11.1 treatment — rank_prop alone)
    blend_causal          : score from σ_causal_26w at bar t
                            (realistic — no forecast, uses 26w trailing σ)
    blend_fwd_1w_rv       : score from *actual weekly RV* at bar t+1
                            (proper 1-week oracle — this is what HAR
                            would target if HAR were perfect)
    blend_fwd_4w_rv       : score = mean actual weekly RV over [t+1..t+4]
                            (proper 4-week oracle — "next several weeks")
    blend_inv_causal      : inverted λ (aggressive in HIGH-vol regime,
                            defensive in LOW-vol). Added after the
                            first run surfaced regime-conditional
                            Sharpe that inverts the naive intuition.
    blend_inv_fwd_1w_rv   : same, proper 1-week RV oracle.
    blend_inv_fwd_4w_rv   : same, proper 4-week RV oracle.
    binary_{causal,fwd_1w_rv,fwd_4w_rv}
                          : HARD cutoff λ schedule (λ = 0 above pct 0.9,
                            λ = 1 below). Motivated by Phase 11.2's
                            observation that mid-regime spread on
                            forward-RV signals is still positive, so
                            the ramp's partial-defensive tilt in the
                            middle band is throwing away edge. Higher
                            switching cost; see the binary-transition
                            diagnostics for the tradeoff.
    best_fixed_lambda     : fixed λ across all bars, chosen by IS Sharpe
                            (counterfactual: does σ-conditioning add value
                            beyond a constant blend?)

Symmetric warmup
----------------
All blend variants use ``warmup_lambda = 0.5`` (neutral 50/50 blend
during the min_history bars before the percentile is trusted). This
is the same value for naive and inverted directions so their
headline metrics are apples-to-apples on the warmup slice.

Vol-source correction
---------------------
An earlier revision used ``sigma_causal_26w.shift(−1)`` and a mis-
oriented rolling window as its "oracle" sources — both are wrong.
The true oracle is *actual next-week RV* (what HAR predicts), not a
one-bar-shifted trailing σ. This revision drops those variants and
uses ``rv_panel.parquet`` for the oracles.

Pass rule for Phase 11.2
------------------------
The design passes if either oracle variant beats ``best_fixed_lambda``
on IS Sharpe by a meaningful margin (≥ ~0.05 as a rough gate). If not,
the pipeline itself doesn't leverage the σ signal even with a perfect
forecast → design fault, don't waste HAR work.

Sample discipline
-----------------
Per [[feedback-oos-discipline]], all metrics are IS-only
(bars ≤ 2023-12-31). OOS + hold-out numbers exist in the per-bar CSVs
for reproducibility but are neither printed nor persisted in the
narrative summary.

Outputs
-------
    data/v6_static/oracle_blender/summary.csv         — one row per variant
    data/v6_static/oracle_blender/bar_{variant}.csv   — per-bar (IS)
    data/v6_static/oracle_blender/lambdas.csv         — λ + score + pct
                                                        per blend variant
    data/v6_static/oracle_blender/block_alloc.csv     — mean block share (IS)
    data/v6_static/oracle_blender/fixed_lambda_sweep.csv — best-fixed-λ grid

Run
---
    python v6/scripts/oracle_blender_v6.py
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
import hysteresis_engine_v6 as H
import hysteresis_engine_v6_sizing as HS
import cost_attribution_v6 as CA
import two_book_blender_v6 as B
# Reuse pure helpers from the 1/√σ sweep (loaders + IS-only stats +
# concentration + block-alloc). Same convention as alpha_prop_sweep_v6.
import sizing_sweep_v6 as SS


# ---------------------------------------------------------------------- #
# Control point (frozen — mirror alpha_prop_sweep_v6 / sizing_sweep_v6)
# ---------------------------------------------------------------------- #
MODE    = "long"
Q       = 0.20
RULE    = "replace"
EPSILON = 0.20

COST_PER_TRADE = E.DEFAULT_COST_PER_TRADE
OUT_ROOT       = C.DATA_DIR / "v6_static" / "oracle_blender"

# Grid for the best-fixed-λ counterfactual. Coarse — the IS surface is
# smooth enough that a 0.05-step grid captures the optimum without
# overfit worry.
FIXED_LAMBDA_GRID = np.round(np.arange(0.0, 1.0 + 1e-9, 0.05), 2)

# Ramp blend variants — (label, vol_source, invert). Solo books handled separately.
BLEND_VARIANTS = (
    ("blend_causal",         "causal",    False),
    ("blend_fwd_1w_rv",      "fwd_1w_rv", False),
    ("blend_fwd_4w_rv",      "fwd_4w_rv", False),
    ("blend_inv_causal",     "causal",    True),
    ("blend_inv_fwd_1w_rv",  "fwd_1w_rv", True),
    ("blend_inv_fwd_4w_rv",  "fwd_4w_rv", True),
)

# Binary blend variants — (label, vol_source). No inverted binary
# because Phase 11.2's diagnostic showed the inverted direction on the
# forward-RV signals is a lagging-signal artifact; not worth retesting
# under a harder-shifting rule. λ = 0 above the upper gate, 1 otherwise.
BINARY_VARIANTS = (
    ("binary_causal",     "causal"),
    ("binary_fwd_1w_rv",  "fwd_1w_rv"),
    ("binary_fwd_4w_rv",  "fwd_4w_rv"),
)

# Warmup λ shared by every blend variant so naive vs inverted (and
# ramp vs binary) stay comparable on the min_history bars before the
# gate fires.
WARMUP_LAMBDA = 0.5


# ---------------------------------------------------------------------- #
# Book builders (weights only — backtest done in _score_book)
# ---------------------------------------------------------------------- #
def _build_solo_weights(alpha: pd.DataFrame, shared: dict, sizing: str
                        ) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    return HS.build_hysteresis_weights_sized(
        alpha, shared["sigma"], shared["membership"],
        q=Q, mode=MODE, epsilon=EPSILON, rule=RULE, sizing=sizing,
    )


def _score_book(W: pd.DataFrame, shared: dict,
                N_t: pd.Series, K_t: pd.Series) -> E.BookResult:
    return E.run_book(W, shared["fwd_1w"],
                      cost_per_trade=COST_PER_TRADE, N_t=N_t, K_t=K_t)


# ---------------------------------------------------------------------- #
# Summary row builder — same schema as sizing_sweep / alpha_prop_sweep
# ---------------------------------------------------------------------- #
def _summarize(res: E.BookResult, W: pd.DataFrame,
               block_tag: pd.Series, label: str,
               vol_source: str | None,
               fixed_lambda: float | None) -> tuple[dict, pd.Series]:
    """One summary row (IS-only stats + turnover + concentration).

    ``vol_source`` and ``fixed_lambda`` are book-keeping columns so the
    summary CSV records exactly which variant produced each row.
    """
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


def _write_bar_detail(res: E.BookResult, out_path: Path) -> None:
    is_idx = res.net_ret.index[res.net_ret.index <= C.IN_SAMPLE_END]
    bar_df = pd.DataFrame({
        "port_ret":  res.port_ret,
        "net_ret":   res.net_ret,
        "turnover":  res.turnover,
        "K":         res.K_t,
        "N":         res.N_t,
    }).reindex(is_idx)
    bar_df.to_csv(out_path)


def _print_row(row: dict) -> None:
    print(
        f"  {row['label']:>20s}  "
        f"IS net Sharpe = {row['net_sharpe_is']:+.3f}   "
        f"IS CAGR = {row['net_cagr_is']*100:+.2f}%   "
        f"IS max DD = {row['net_max_dd_is']*100:+.2f}%   "
        f"held = {row['held_mean']:.1f}   "
        f"eff N (1/HHI) = {row['conc_mean_eff_N']:.1f}"
    )


# ---------------------------------------------------------------------- #
# Best-fixed-λ counterfactual
# ---------------------------------------------------------------------- #
def _best_fixed_lambda(W_agg: pd.DataFrame, W_def: pd.DataFrame,
                       shared: dict, N_t: pd.Series, K_t: pd.Series
                       ) -> tuple[float, pd.DataFrame]:
    """Sweep λ over FIXED_LAMBDA_GRID, pick the one with max IS net
    Sharpe. Returns (best_lambda, full_grid_summary)."""
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
    best_lam = float(grid.loc[grid["net_sharpe_is"].idxmax(), "fixed_lambda"])
    return best_lam, grid


# ---------------------------------------------------------------------- #
# Top-level
# ---------------------------------------------------------------------- #
def run(data_dir: Path | None = None) -> pd.DataFrame:
    data_dir = Path(data_dir) if data_dir else C.DATA_DIR
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    shared    = SS._load_shared(data_dir)
    alpha     = SS._load_ensemble_alpha(data_dir, MODE, Q)
    block_tag = SS._load_block_tag(data_dir)
    # Realized weekly RV per ETF — source of the *actual* oracle σ
    # signal (what HAR predicts). Annualized weekly RV, 344 codes.
    rv_panel  = pd.read_parquet(data_dir / "vol_forecast_v6" / "rv_panel.parquet")

    print("Building solo book weights (aggressive + defensive)...")
    W_agg, N_t, K_t = _build_solo_weights(alpha, shared, sizing="rank_prop")
    W_def, N_ref, K_ref = _build_solo_weights(alpha, shared, sizing="inv_vol")

    # Sanity: both books share the same (N_t, K_t) — same selection.
    if not N_t.equals(N_ref) or not K_t.equals(K_ref):
        raise AssertionError("aggressive vs defensive N_t / K_t mismatch — "
                             "selection axis diverged unexpectedly")

    rows: list[dict] = []
    block_rows: dict[str, pd.Series] = {}

    # -------------------- solo variants --------------------
    print("\nSolo books:")
    for label, W in (("solo_defensive", W_def),
                     ("solo_aggressive", W_agg)):
        res = _score_book(W, shared, N_t, K_t)
        row, blk = _summarize(res, W, block_tag, label,
                              vol_source=None, fixed_lambda=None)
        rows.append(row)
        block_rows[label] = blk
        _write_bar_detail(res, OUT_ROOT / f"bar_{label}.csv")
        _print_row(row)

    # -------------------- blend variants --------------------
    print("\nOracle / realistic blend variants:")
    lambda_records: dict[str, pd.DataFrame] = {}
    for label, vol_source, invert in BLEND_VARIANTS:
        score_raw = B.equity_risk_score_raw(
            shared["sigma"], shared["membership"], block_tag,
            vol_source=vol_source, rv_panel=rv_panel)
        score_pct = B.score_to_percentile(score_raw, min_history=B.MIN_HISTORY)
        # Ffill pct through post-warmup NaN bars (holiday weeks where
        # RV panel has no entry). Warmup block stays NaN → warmup_lambda.
        score_pct = B.hold_through_transient_nan(score_pct)
        lam = B.lambda_schedule(score_pct, warmup_lambda=WARMUP_LAMBDA,
                                invert=invert)
        lambda_records[label] = pd.DataFrame({
            "score_raw":  score_raw,
            "score_pct":  score_pct,
            "lambda":     lam,
        })

        W_blend = B.blend_weights(W_agg, W_def, lam)
        res = _score_book(W_blend, shared, N_t, K_t)
        row, blk = _summarize(res, W_blend, block_tag, label,
                              vol_source=vol_source, fixed_lambda=None)
        rows.append(row)
        block_rows[label] = blk
        _write_bar_detail(res, OUT_ROOT / f"bar_{label}.csv")
        _print_row(row)

    # -------------------- binary variants (hard cutoff) --------------------
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
        row, blk = _summarize(res, W_blend, block_tag, label,
                              vol_source=vol_source, fixed_lambda=None)
        rows.append(row)
        block_rows[label] = blk
        _write_bar_detail(res, OUT_ROOT / f"bar_{label}.csv")
        _print_row(row)

    # -------------------- best-fixed-λ counterfactual --------------------
    print("\nBest-fixed-λ counterfactual:")
    best_lam, grid = _best_fixed_lambda(W_agg, W_def, shared, N_t, K_t)
    grid.to_csv(OUT_ROOT / "fixed_lambda_sweep.csv", index=False)
    print(f"  best fixed λ = {best_lam:.2f}  "
          f"(IS Sharpe = {grid['net_sharpe_is'].max():+.3f})")

    W_best = best_lam * W_agg + (1.0 - best_lam) * W_def
    res = _score_book(W_best, shared, N_t, K_t)
    row, blk = _summarize(res, W_best, block_tag, "best_fixed_lambda",
                          vol_source=None, fixed_lambda=best_lam)
    rows.append(row)
    block_rows["best_fixed_lambda"] = blk
    _write_bar_detail(res, OUT_ROOT / "bar_best_fixed_lambda.csv")
    _print_row(row)

    # -------------------- persist summary + block + λ side-tables ---------
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT_ROOT / "summary.csv", index=False)

    block_df = pd.DataFrame({k: v for k, v in block_rows.items()}).fillna(0.0)
    # Order columns semantically for readability.
    order = ["solo_defensive", "solo_aggressive",
             "blend_causal", "blend_fwd_1w_rv", "blend_fwd_4w_rv",
             "blend_inv_causal", "blend_inv_fwd_1w_rv", "blend_inv_fwd_4w_rv",
             "binary_causal", "binary_fwd_1w_rv", "binary_fwd_4w_rv",
             "best_fixed_lambda"]
    block_df = block_df[[c for c in order if c in block_df.columns]]
    block_df.to_csv(OUT_ROOT / "block_alloc.csv")

    # λ + score + pct time series, tall format.
    lam_df = pd.concat({k: v for k, v in lambda_records.items()},
                      names=["variant", "date"])
    lam_df.to_csv(OUT_ROOT / "lambdas.csv")

    print(f"\nwrote {OUT_ROOT / 'summary.csv'}  ({len(summary)} rows)")
    print(f"wrote {OUT_ROOT / 'block_alloc.csv'}")
    print(f"wrote {OUT_ROOT / 'lambdas.csv'}")
    print(f"wrote {OUT_ROOT / 'fixed_lambda_sweep.csv'}")
    return summary


if __name__ == "__main__":
    run()
