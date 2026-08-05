"""
v6/scripts/alpha_prop_sweep_v6.py
=================================
Aggressive-book validation on the Phase 9.2 `long_q20 replace ε=0.20`
control point.

Motivation
----------
Phase 11 introduces a two-book design (aggressive + defensive) whose
cash split will eventually be steered by a vol forecast. The defensive
leg is the current `1/σ` book. The aggressive leg is an α-responsive
sizing kernel that up-weights the top-α held names.

Before wiring the blender, isolate whether the aggressive kernel
behaves as expected in isolation vs the defensive baseline:

- Net CAGR: **higher** (rotates mass out of low-vol / low-α names)
- Net max DD: **worse** (less risk-parity concentration in bonds)
- Net Sharpe: **flat or slightly lower** (higher return + higher vol)

If those three all point the right way, the sizing axis is real and
worth combining with the defensive book in a later oracle test
(Phase 11.2).

Design
------
- **Control**   : long_q20, rule=replace, ε=0.20, sizing=inv_vol
                 (matches the Phase 9.2 `long_q20 replace ε=0.20` cell
                 in `hysteresis_sweep/summary.csv` bit-for-bit).
- **Treatment** : long_q20, rule=replace, ε=0.20, sizing=rank_prop
                 (aggressive book — rank-proportional weight on the
                 held set, w_i ∝ H − r_i + 1 with local α-rank).

Selection and cost model are identical — the only axis moving is the
per-name sizing kernel applied to the held set at each bar.

Sample discipline
-----------------
Per [[feedback-oos-discipline]]: this experiment reports **IS metrics
only**. Bars ≤ 2023-12-31. OOS + hold-out numbers are computed for the
reproduction assert but are neither printed nor persisted in the
narrative summary (the raw per-bar CSV keeps them so the driver stays
recoverable; the report table does not surface them).

Outputs
-------
    data/v6_static/alpha_prop_sweep/summary.csv       — control + treatment
    data/v6_static/alpha_prop_sweep/bar_control.csv   — per-bar (IS)
    data/v6_static/alpha_prop_sweep/bar_treatment.csv — per-bar (IS)
    data/v6_static/alpha_prop_sweep/block_alloc.csv   — mean block share (IS)

Run
---
    python v6/scripts/alpha_prop_sweep_v6.py
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
# Reuse pure helpers from the 1/√σ sweep — same shared loaders / IS-only
# stats / concentration / block helpers. Importing keeps this driver
# consistent with the sizing_sweep_v6 conventions without an edit-in-place.
import sizing_sweep_v6 as SS


# ---------------------------------------------------------------------- #
# Control point (frozen — mirror sizing_sweep_v6)
# ---------------------------------------------------------------------- #
MODE    = "long"
Q       = 0.20
RULE    = "replace"
EPSILON = 0.20

SIZINGS = ("inv_vol", "rank_prop")           # control, then treatment
LABELS  = {"inv_vol": "control", "rank_prop": "treatment"}

COST_PER_TRADE = E.DEFAULT_COST_PER_TRADE
OUT_ROOT       = C.DATA_DIR / "v6_static" / "alpha_prop_sweep"


# ---------------------------------------------------------------------- #
# Per-run driver
# ---------------------------------------------------------------------- #
def _run_one(alpha: pd.DataFrame, shared: dict, sizing: str
             ) -> tuple[E.BookResult, pd.DataFrame]:
    W, N_t, K_t = HS.build_hysteresis_weights_sized(
        alpha, shared["sigma"], shared["membership"],
        q=Q, mode=MODE, epsilon=EPSILON, rule=RULE, sizing=sizing,
    )
    res = E.run_book(W, shared["fwd_1w"],
                     cost_per_trade=COST_PER_TRADE, N_t=N_t, K_t=K_t)
    return res, W


def _summarize(res: E.BookResult, W: pd.DataFrame,
               block_tag: pd.Series, sizing: str) -> tuple[dict, pd.Series]:
    """One summary row (IS-only stats + turnover + concentration).

    Structure mirrors ``sizing_sweep_v6._summarize`` — same columns so
    downstream diffing between the two sweep artifacts stays trivial."""
    attrib = CA.decompose_turnover(res.weights)
    cost = attrib.total * COST_PER_TRADE

    net_stats   = SS._is_stats(res.net_ret)
    gross_stats = SS._is_stats(res.port_ret)

    is_idx  = res.net_ret.index[res.net_ret.index <= C.IN_SAMPLE_END]
    is_total = attrib.total.reindex(is_idx)
    is_sel   = attrib.selection.reindex(is_idx)
    is_size  = attrib.sizing.reindex(is_idx)
    is_cost  = cost.reindex(is_idx)

    conc = SS._weight_concentration(W)
    block_alloc = SS._block_allocation(W, block_tag)

    denom = float(is_total.mean()) if float(is_total.mean()) > 0 else np.nan
    row = {
        "sizing":   sizing,
        "label":    LABELS[sizing],
        "cell":     SS._cell_tag(MODE, Q),
        "rule":     RULE,
        "epsilon":  EPSILON,
        "n_bars_is": int(net_stats["n_bars"]),
        # IS Sharpe (net + gross)
        "net_sharpe_is":     net_stats["sharpe"],
        "gross_sharpe_is":   gross_stats["sharpe"],
        # IS return metrics
        "net_ann_ret_is":    net_stats["ann_ret"],
        "gross_ann_ret_is":  gross_stats["ann_ret"],
        "net_cagr_is":       net_stats["cagr"],
        "gross_cagr_is":     gross_stats["cagr"],
        "net_cumret_is":     net_stats["cumret"],
        # Risk metrics
        "net_max_dd_is":     net_stats["max_dd"],
        "gross_max_dd_is":   gross_stats["max_dd"],
        "annual_vol_is":     net_stats["ann_vol"],
        # Turnover / cost (IS)
        "cost_bps_yr_is":    float(is_cost.mean() * C.WEEKS_PER_YEAR * 1e4),
        "turnover_total":    float(is_total.mean()),
        "turnover_selection": float(is_sel.mean()),
        "turnover_sizing":    float(is_size.mean()),
        "sizing_share":      float(is_size.mean() / denom) if denom else 0.0,
        "selection_share":   float(is_sel.mean()  / denom) if denom else 0.0,
        # Weight-distribution diagnostics (IS mean per-bar)
        **{f"conc_{k}": v for k, v in conc.items()},
        "held_mean":         float((W.loc[is_idx] != 0).sum(axis=1).mean()),
    }
    return row, block_alloc


# ---------------------------------------------------------------------- #
# Reproduction guard — inv_vol branch must match the Phase 9.2 point
# ---------------------------------------------------------------------- #
def _assert_control_matches_hysteresis(res_control: E.BookResult,
                                       alpha: pd.DataFrame,
                                       shared: dict) -> None:
    """The parameterized engine's inv_vol branch must reproduce the
    production hysteresis engine bit-for-bit at (ε=0.2, replace,
    long_q20). Same guard sizing_sweep_v6 runs — kept independently
    here so `alpha_prop_sweep_v6.py` is self-sufficient."""
    W_ref, N_ref, K_ref = H.build_hysteresis_weights(
        alpha, shared["sigma"], shared["membership"],
        q=Q, mode=MODE, epsilon=EPSILON, rule=RULE,
    )
    res_ref = E.run_book(W_ref, shared["fwd_1w"],
                         cost_per_trade=COST_PER_TRADE, N_t=N_ref, K_t=K_ref)

    dW = (res_control.weights - W_ref).abs().to_numpy().max()
    if dW > 1e-12:
        raise AssertionError(
            f"inv_vol control weights diverge from hysteresis_engine_v6: "
            f"max |ΔW| = {dW:.3g}"
        )
    dret = (res_control.net_ret - res_ref.net_ret).abs().max()
    if dret > 1e-12:
        raise AssertionError(
            f"inv_vol control net_ret diverges from hysteresis_engine_v6: "
            f"max |Δ net_ret| = {dret:.3g}"
        )


# ---------------------------------------------------------------------- #
# Top-level
# ---------------------------------------------------------------------- #
def run(data_dir: Path | None = None) -> pd.DataFrame:
    data_dir = Path(data_dir) if data_dir else C.DATA_DIR
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    shared    = SS._load_shared(data_dir)
    alpha     = SS._load_ensemble_alpha(data_dir, MODE, Q)
    block_tag = SS._load_block_tag(data_dir)

    rows: list[dict] = []
    block_rows: dict[str, pd.Series] = {}

    for sizing in SIZINGS:
        res, W = _run_one(alpha, shared, sizing)
        if sizing == "inv_vol":
            _assert_control_matches_hysteresis(res, alpha, shared)

        row, blk = _summarize(res, W, block_tag, sizing)
        rows.append(row)
        block_rows[sizing] = blk

        is_idx = res.net_ret.index[res.net_ret.index <= C.IN_SAMPLE_END]
        bar_df = pd.DataFrame({
            "port_ret":  res.port_ret,
            "net_ret":   res.net_ret,
            "turnover":  res.turnover,
            "K":         res.K_t,
            "N":         res.N_t,
        }).reindex(is_idx)
        bar_df.to_csv(OUT_ROOT / f"bar_{LABELS[sizing]}.csv")

        print(
            f"  {sizing:>14s} ({LABELS[sizing]:>9s})  "
            f"IS net Sharpe = {row['net_sharpe_is']:+.3f}   "
            f"IS CAGR = {row['net_cagr_is']*100:+.2f}%   "
            f"IS max DD = {row['net_max_dd_is']*100:+.2f}%   "
            f"eff N = {row['conc_mean_eff_N']:.1f}"
        )

    summary = pd.DataFrame(rows)
    summary.to_csv(OUT_ROOT / "summary.csv", index=False)

    block_df = pd.DataFrame({LABELS[k]: v for k, v in block_rows.items()})
    block_df = block_df.fillna(0.0)
    block_df["delta"] = block_df["treatment"] - block_df["control"]
    block_df = block_df.sort_values("control", ascending=False)
    block_df.to_csv(OUT_ROOT / "block_alloc.csv")

    print(f"\nwrote {OUT_ROOT / 'summary.csv'}  ({len(summary)} rows)")
    print(f"wrote {OUT_ROOT / 'block_alloc.csv'}")
    return summary


if __name__ == "__main__":
    run()
