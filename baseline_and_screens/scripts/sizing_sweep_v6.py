"""
v6/scripts/sizing_sweep_v6.py
=============================
Sizing-scheme experiment on the long_q20 replace-ε=0.2 control point.

Motivation
----------
The Phase 9.2 hysteresis picks concentrate the book in the lowest-vol
names — mostly bonds — via the 1/σ_causal_26w kernel. Risk-management
is fine, but headline CAGR on `long_q20` sits ~3% (net, IS) which is
bond-like. Softening the sizing kernel from 1/σ to 1/√σ should flatten
the weight distribution: bond names still over-weight but higher-vol
equity names get more mass. Expected: Sharpe roughly flat, CAGR up,
max DD up.

Design
------
- **Control**   : long_q20, rule=replace, ε=0.20, sizing=inv_vol
                 (matches the Phase 9.2 `long_q20 replace ε=0.20` cell
                 in `hysteresis_sweep/summary.csv` bit-for-bit).
- **Treatment** : long_q20, rule=replace, ε=0.20, sizing=inv_sqrt_vol
                 (this branch's experiment).

Selection and cost model are identical — the only axis moving is the
per-name sizing kernel applied to the held set at each bar.

Sample discipline
-----------------
Per [[project_oos_discipline]]: this experiment reports **IS metrics
only**. Bars ≤ 2023-12-31. OOS + hold-out are computed for the
reproduction assert but are neither printed nor persisted in the
narrative summary (the raw per-bar CSV keeps them so the driver stays
recoverable; the report table does not surface them).

Outputs
-------
    data/v6_static/sizing_sweep/summary.csv         — control + treatment row
    data/v6_static/sizing_sweep/bar_control.csv     — per-bar (IS) detail
    data/v6_static/sizing_sweep/bar_treatment.csv   — per-bar (IS) detail
    data/v6_static/sizing_sweep/block_alloc.csv     — mean block share (IS)

Run
---
    python v6/scripts/sizing_sweep_v6.py
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


# ---------------------------------------------------------------------- #
# Control point (frozen)
# ---------------------------------------------------------------------- #
MODE    = "long"
Q       = 0.20
RULE    = "replace"
EPSILON = 0.20

SIZINGS = ("inv_vol", "inv_sqrt_vol")     # control, then treatment
LABELS  = {"inv_vol": "control", "inv_sqrt_vol": "treatment"}

COST_PER_TRADE = E.DEFAULT_COST_PER_TRADE
OUT_ROOT       = C.DATA_DIR / "v6_static" / "sizing_sweep"


# ---------------------------------------------------------------------- #
# Loaders — mirror hysteresis_sweep_v6 shape
# ---------------------------------------------------------------------- #
def _cell_tag(mode: str, q: float) -> str:
    return f"{mode}_q{int(round(q * 100)):02d}"


def _load_shared(data_dir: Path) -> dict:
    mem = pd.read_parquet(data_dir / "universe_v6" / "membership.parquet")
    codes = list(mem.columns[mem.any(axis=0)])
    mem = mem[codes].astype(bool)
    fwd   = pd.read_parquet(data_dir / "panels_v6" / "fwd_1w.parquet")[codes]
    sigma = pd.read_parquet(data_dir / "panels_v6" / "sigma_causal_26w.parquet")[codes]
    return {"membership": mem, "codes": codes, "fwd_1w": fwd, "sigma": sigma}


def _load_ensemble_alpha(data_dir: Path, mode: str, q: float) -> pd.DataFrame:
    cell = _cell_tag(mode, q)
    return pd.read_parquet(data_dir / "v6_static" / cell / "ensemble_alpha.parquet")


def _load_block_tag(data_dir: Path) -> pd.Series:
    """code → block mapping (Phase 3 tags)."""
    cat = pd.read_csv(data_dir / "universe_v6" / "catalogue_tagged.csv")
    return cat.set_index("code")["current_block"]


# ---------------------------------------------------------------------- #
# IS-only stats
# ---------------------------------------------------------------------- #
def _is_mask(idx: pd.DatetimeIndex) -> np.ndarray:
    return (idx <= C.IN_SAMPLE_END).to_numpy()


def _is_stats(net: pd.Series) -> dict:
    """Sharpe / CAGR / max_dd / ann_vol on the IS window only."""
    is_net = net[net.index <= C.IN_SAMPLE_END]
    n = int(len(is_net))
    if n < 2:
        return {"sharpe": 0.0, "cumret": 0.0, "cagr": 0.0,
                "max_dd": 0.0, "ann_vol": 0.0, "ann_ret": 0.0, "n_bars": n}
    ann_vol = float(is_net.std(ddof=1)) * np.sqrt(C.WEEKS_PER_YEAR)
    ann_ret = float(is_net.mean()) * C.WEEKS_PER_YEAR
    sharpe  = (ann_ret / ann_vol) if ann_vol > 0 else 0.0
    cumret  = float(is_net.sum())
    n_years = max(n / C.WEEKS_PER_YEAR, 1e-3)
    cagr    = max(1.0 + cumret, 1e-9) ** (1.0 / n_years) - 1.0
    nav     = 1.0 + is_net.cumsum()
    cummax  = nav.cummax()
    max_dd  = float(((nav - cummax) / cummax).min())
    return {"sharpe": sharpe, "cumret": cumret, "cagr": cagr,
            "max_dd": max_dd, "ann_vol": ann_vol, "ann_ret": ann_ret,
            "n_bars": n}


def _weight_concentration(W: pd.DataFrame) -> dict:
    """IS-window mean concentration diagnostics on the held-set of each bar.

    - HHI = Σ_i w_i²  (per-bar; sensitive to a small number of large
      weights)
    - eff_N = 1 / HHI  (effective number of names)
    - top1_w = max single-name weight (per bar)
    - top3_sum, top5_sum = sum of largest 3 / 5 weights (per bar)

    Averaged across IS bars where HHI > 0 (i.e., not flat).
    """
    is_W = W.loc[W.index <= C.IN_SAMPLE_END]
    Wm = is_W.to_numpy()
    hhi = (Wm * Wm).sum(axis=1)

    valid = hhi > 0
    if not valid.any():
        return {"mean_hhi": np.nan, "mean_eff_N": np.nan,
                "mean_top1": np.nan, "mean_top3": np.nan,
                "mean_top5": np.nan}
    eff_N = np.where(valid, 1.0 / np.where(valid, hhi, 1.0), np.nan)

    # Sort each row descending for top-k sums (abs to keep LS-safe though
    # we're long-only here).
    abs_W = np.sort(np.abs(Wm), axis=1)[:, ::-1]
    top1 = abs_W[:, 0]
    top3 = abs_W[:, :3].sum(axis=1)
    top5 = abs_W[:, :5].sum(axis=1)

    return {
        "mean_hhi":    float(np.nanmean(hhi[valid])),
        "mean_eff_N":  float(np.nanmean(eff_N[valid])),
        "mean_top1":   float(np.nanmean(top1[valid])),
        "mean_top3":   float(np.nanmean(top3[valid])),
        "mean_top5":   float(np.nanmean(top5[valid])),
    }


def _block_allocation(W: pd.DataFrame,
                      block_tag: pd.Series) -> pd.Series:
    """IS-mean share of book weight per block (sum-abs then per-bar
    normalized). Returns a Series indexed by block name, summing to 1.0
    across defined blocks (up to floating slop)."""
    is_W = W.loc[W.index <= C.IN_SAMPLE_END]
    abs_W = is_W.abs()
    row_sum = abs_W.sum(axis=1).replace(0.0, np.nan)
    share = abs_W.div(row_sum, axis=0)
    # Group columns by block, sum, then average across bars.
    tag = block_tag.reindex(share.columns).fillna("unknown")
    by_block = share.T.groupby(tag).sum().T
    return by_block.mean(axis=0)


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
    """One summary row (IS-only stats + turnover + concentration)."""
    attrib = CA.decompose_turnover(res.weights)
    cost = attrib.total * COST_PER_TRADE

    net_stats   = _is_stats(res.net_ret)
    gross_stats = _is_stats(res.port_ret)

    # IS-restricted turnover / cost / K
    is_idx = res.net_ret.index[res.net_ret.index <= C.IN_SAMPLE_END]
    is_total = attrib.total.reindex(is_idx)
    is_sel   = attrib.selection.reindex(is_idx)
    is_size  = attrib.sizing.reindex(is_idx)
    is_cost  = cost.reindex(is_idx)

    conc = _weight_concentration(W)
    block_alloc = _block_allocation(W, block_tag)

    denom = float(is_total.mean()) if float(is_total.mean()) > 0 else np.nan
    row = {
        "sizing":   sizing,
        "label":    LABELS[sizing],
        "cell":     _cell_tag(MODE, Q),
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
    long_q20)."""
    W_ref, N_ref, K_ref = H.build_hysteresis_weights(
        alpha, shared["sigma"], shared["membership"],
        q=Q, mode=MODE, epsilon=EPSILON, rule=RULE,
    )
    res_ref = E.run_book(W_ref, shared["fwd_1w"],
                         cost_per_trade=COST_PER_TRADE, N_t=N_ref, K_t=K_ref)

    # Weight-level check
    dW = (res_control.weights - W_ref).abs().to_numpy().max()
    if dW > 1e-12:
        raise AssertionError(
            f"inv_vol control weights diverge from hysteresis_engine_v6: "
            f"max |ΔW| = {dW:.3g}"
        )
    # Net-return level check (redundant given weights match, but keeps
    # the guard interpretable in a future rerun log)
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

    shared    = _load_shared(data_dir)
    alpha     = _load_ensemble_alpha(data_dir, MODE, Q)
    block_tag = _load_block_tag(data_dir)

    rows: list[dict] = []
    block_rows: dict[str, pd.Series] = {}

    for sizing in SIZINGS:
        res, W = _run_one(alpha, shared, sizing)
        if sizing == "inv_vol":
            _assert_control_matches_hysteresis(res, alpha, shared)

        row, blk = _summarize(res, W, block_tag, sizing)
        rows.append(row)
        block_rows[sizing] = blk

        # Per-bar IS detail (net_ret / turnover / K)
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

    # Block-allocation side table (rows = block, cols = control / treatment)
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
