"""
v6/scripts/block_two_layer_v6.py
================================
Phase 12 × Phase 13 — two-layer book: block risk-budgeting (layer-1)
+ per-block α selection (layer-2) on broad_cn + sector_cn.

Design (2026-07-22, per user):

- **Layer-1** unchanged from `block_risk_budget_v6`: 4-group risk budget
  (equity 55 / bond_rates 20 / bond_credit 10 / commodity 15 %),
  LW-target-D shrinkage, log-barrier ERC solver.
  **Trend gate dropped** — the layer-1 ablation showed it as
  Sharpe-neutral (±0.04) after the naive/LW bug fix, and the user
  chose the simpler no-gate version.
- **Layer-2** replaces two of the 8 blocks' hold-all sub-books with
  α-hysteresis selection (production long_q20-replace kernel):
    - `broad_cn`  : K=5 finalist ensemble (locked in Phase 13.5)
    - `sector_cn` : K=8 finalist ensemble (locked in Phase 13.5)
  The other 6 blocks (bond_rates, bond_credit, cross_border_dm,
  cross_border_hk, metals, commodity_other) stay hold-all — no α,
  block-internal invvol.

Sub-block composition into groups. Each sub-book weight panel is
renormalized so Σ over its members = 1. Sub-block share within its
group = N_b / N_group (static ever-admitted counts). With α turned
off (q=1, ε=0 → hysteresis reduces to hold-all top-N), this reduces
exactly to layer-1 invvol × lw_erc, so Δ (layer-2 − baseline) is a
pure α effect with sub-block sizing held identical.

Baseline. `run_baseline(...)` = `run_variant(q=1.0, ε=0.0)`. Identical
non-α sub-blocks, identical solver, identical trend setting;
α sub-blocks fall back to invvol hold-all. Δ(Sharpe, CAGR, DD, turnover)
per cell is measured against this baseline.

Sweep. 3 q × 4 ε = 12 cells:

    q ∈ {0.10, 0.20, 0.30}
    ε ∈ {0.00, 0.10, 0.20, 0.30}

Uniform (q, ε) applied to both α blocks (broad_cn AND sector_cn use the
same q, same ε for this branch). Cell picked via plateau rule: within
Δ-Sharpe ≥ max Δ-Sharpe − PLATEAU_BAND (0.05), lowest turnover wins.

Cost attribution. Every cell runs twice — once with cost_per_trade =
DEFAULT_COST_PER_TRADE (10 bp/side) and once with 0. Report shows
gross Sharpe, net Sharpe, and their difference alongside turnover
so cost drag is separable from raw signal strength.

Outputs
-------
    data/block_two_layer_v6/
        baseline/{w_name.parquet, net_ret.csv, gross_ret.csv, summary.csv}
        q{qq}_eps{ee}/{same}
        sweep_summary.csv         — 12 rows + baseline
        plateau_pick.csv
    reports/block_two_layer_v6_report.md

Run
---
    python v6/scripts/block_two_layer_v6.py
    python v6/scripts/block_two_layer_v6.py --qs 0.20 --epsilons 0.20
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Iterable

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
import block_composite_v6 as BC
import block_risk_budget_v6 as BR
from within_block_ensemble_v6 import build_ensemble_score


# ---------------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------------- #
COST = E.DEFAULT_COST_PER_TRADE
BUDGET_METHOD = "lw_erc"                     # layer-1 canonical
USE_TREND     = False                        # dropped per user 2026-07-22

# α blocks + LOCKED finalist member lists (from
# project-layer-two-finalists / within_block_ensemble_v6 K=5 / K=8 runs).
# Hard-coded here as the frozen spec; do NOT retune before the OOS shot
# (feedback-oos-discipline). If the CSVs at
# data/within_block_ensemble_v6/{block}/members_{K}.csv are regenerated
# and disagree with these lists, that's a look-ahead breach — fix the
# regeneration, not this constant.
ALPHA_BLOCKS: tuple[str, ...] = ("broad_cn", "sector_cn")
ALPHA_MEMBERS: dict[str, list[tuple[str, str]]] = {
    "broad_cn": [
        ("alpha015",           "raw"),
        ("alpha_071",          "raw"),
        ("alpha_102",          "raw"),
        ("h_mom_decay_12_48",  "raw"),
        ("alpha006",           "rev"),
    ],
    "sector_cn": [
        ("var5_60",              "raw"),
        ("ma_disp",              "raw"),
        ("alpha_142",            "raw"),
        ("alpha_187",            "raw"),
        ("yj15_bias_mom_60_20",  "rev"),
        ("h_mom_decay_12_48",    "raw"),
        ("kurt_40",              "rev"),
        ("ret_skew_20",          "raw"),
    ],
}
ALPHA_SIZING    = "invvol"   # matches locked finalists
NONALPHA_SIZING = "invvol"   # matches α sub-blocks → clean Δ (pure α)
RULE            = "replace"  # production long_q20-replace kernel

# Sweep grid + plateau band
Q_GRID:   tuple[float, ...] = (0.10, 0.20, 0.30)
EPS_GRID: tuple[float, ...] = (0.00, 0.10, 0.20, 0.30)
PLATEAU_BAND = 0.05          # ΔSh within 0.05 of max counts as plateau

OUT_ROOT = C.DATA_DIR / "block_two_layer_v6"


# ---------------------------------------------------------------------- #
# α ensemble score cache
# ---------------------------------------------------------------------- #
def _members_frame(block: str) -> pd.DataFrame:
    return pd.DataFrame(ALPHA_MEMBERS[block], columns=["factor", "polarity"])


def build_alpha_scores(shared: dict) -> dict[str, pd.DataFrame]:
    """Precompute per-α-block ensemble scores. Reused across all sweep cells
    (only q, ε change downstream — the score panel is invariant).

    Loads factor caches lazily into shared['caches'] on first call — the
    `block_composite_v6.load_shared` shared bundle omits caches (only
    layer-1 needs them for α blocks)."""
    if "caches" not in shared:
        shared["caches"] = C.load_caches_v6("1d", shared["codes"])
    scores: dict[str, pd.DataFrame] = {}
    for b in ALPHA_BLOCKS:
        codes_b = pd.Index(
            [c for c in shared["codes"] if shared["block_tag"].get(c) == b]
        )
        if len(codes_b) == 0:
            scores[b] = pd.DataFrame(index=shared["fwd_1w"].index)
            continue
        scores[b] = build_ensemble_score(
            _members_frame(b), shared, codes_b,
        )
    return scores


# ---------------------------------------------------------------------- #
# Sub-block weight builders
# ---------------------------------------------------------------------- #
def _sub_block_codes(shared: dict, block: str) -> pd.Index:
    tag = shared["block_tag"]
    return pd.Index([c for c in shared["codes"] if tag.get(c) == block])


def build_holdall_subblock(shared: dict, block: str,
                           sizing: str) -> pd.DataFrame:
    """Eqw or invvol hold-all sub-book on block members, Σ = 1 per bar
    (when the block has eligible members). Thin wrapper on
    `block_composite_v6.build_group_weights` with the block as the sole
    constituent."""
    return BC.build_group_weights(
        shared["sigma"], shared["membership"], shared["block_tag"],
        (block,), sizing,
    )


def build_alpha_subblock(shared: dict, block: str,
                         score: pd.DataFrame,
                         q: float, epsilon: float,
                         sizing: str = ALPHA_SIZING) -> pd.DataFrame:
    """α-hysteresis sub-book (production long_q20-replace kernel):
    top-⌈q·N_b(t)⌉ picked by ensemble score, with ε-band hysteresis and
    the block-scoped σ_causal for invvol sizing (or a constant-σ panel
    for eqw). Σ = 1 per bar when invested."""
    codes_b = _sub_block_codes(shared, block)
    if len(codes_b) == 0:
        return pd.DataFrame(0.0, index=shared["fwd_1w"].index, columns=[])
    mem_b   = shared["membership"][codes_b]
    sigma_b = shared["sigma"][codes_b]
    if sizing == "eqw":
        sigma_use = (pd.DataFrame(1.0, index=sigma_b.index, columns=sigma_b.columns)
                       .where(mem_b, np.nan))
    else:
        sigma_use = sigma_b
    # score is already restricted to block codes by build_ensemble_score
    score_b = score.reindex(index=mem_b.index, columns=codes_b)
    W, _N, _K = H.build_hysteresis_weights(
        score_b, sigma_use, mem_b, q=q, mode="long",
        epsilon=epsilon, rule=RULE,
    )
    return W.fillna(0.0)


# ---------------------------------------------------------------------- #
# Group-level composition (sub-block share = N_b / N_g)
# ---------------------------------------------------------------------- #
def _static_member_counts(shared: dict) -> dict[str, int]:
    tag = shared["block_tag"]
    return {b: int((tag == b).sum()) for b in tag.unique() if isinstance(b, str)}


def build_group_weights_two_layer(shared: dict,
                                  q: float, epsilon: float,
                                  alpha_scores: dict[str, pd.DataFrame],
                                  ) -> tuple[dict[str, pd.DataFrame],
                                             dict[str, dict[str, pd.DataFrame]]]:
    """For each group, name-level sub-books stacked column-wise, weighted
    by N_b/N_g. Returns:

        group_weights_by_block : dict[group -> {block -> T×N_b sub-book × share}]
        group_weights          : dict[group -> T×N_g concatenated panel, Σ=1]

    The group-level composite return is Σ over members of the group's
    concatenated panel × fwd_1w. Weights inside the group **do not
    renormalize dynamically** when a sub-block is flat — its
    contribution just drops to 0 and the group total for that bar dips
    below 1. That matches the layer-1 hold-all convention (invested
    Σ = 1 when all sub-blocks are populated, else < 1 with the
    difference implicit cash inside the group).
    """
    N_counts = _static_member_counts(shared)

    per_group: dict[str, dict[str, pd.DataFrame]] = {}
    concat_group: dict[str, pd.DataFrame] = {}
    for grp, blocks in BC.BLOCK_GROUPS.items():
        N_g = sum(N_counts.get(b, 0) for b in blocks)
        per_block: dict[str, pd.DataFrame] = {}
        frames: list[pd.DataFrame] = []
        for b in blocks:
            N_b = N_counts.get(b, 0)
            if N_b == 0:
                continue
            if b in ALPHA_BLOCKS and q < 1.0:
                W_sub = build_alpha_subblock(
                    shared, b, alpha_scores[b], q, epsilon, sizing=ALPHA_SIZING,
                )
            else:
                W_sub = build_holdall_subblock(
                    shared, b,
                    sizing=(ALPHA_SIZING if b in ALPHA_BLOCKS
                                          else NONALPHA_SIZING),
                )
            share = N_b / N_g if N_g > 0 else 0.0
            W_scaled = W_sub * share
            per_block[b] = W_scaled
            frames.append(W_scaled)
        per_group[grp] = per_block
        concat_group[grp] = (pd.concat(frames, axis=1)
                             if frames else pd.DataFrame(index=shared["fwd_1w"].index))
    return concat_group, per_group


# ---------------------------------------------------------------------- #
# Composites: per-group weekly return series (for layer-1 cov / solve)
# ---------------------------------------------------------------------- #
def build_composites_two_layer(shared: dict,
                               q: float, epsilon: float,
                               alpha_scores: dict[str, pd.DataFrame]
                               ) -> dict:
    """Group-level returns + name-level weights + NAV for layer-1
    consumption. Returns the same structure `block_composite_v6` produces
    for a single sizing, plus a `per_block` mapping for aggregation."""
    concat_group, per_block = build_group_weights_two_layer(
        shared, q, epsilon, alpha_scores,
    )
    fwd = shared["fwd_1w"]
    rets = {}
    for grp, W_g in concat_group.items():
        if W_g.shape[1] == 0:
            rets[grp] = pd.Series(np.nan, index=fwd.index, name=grp)
            continue
        fwd_g = fwd.reindex(columns=W_g.columns).fillna(0.0)
        r_g = (W_g * fwd_g).sum(axis=1)
        invested = (W_g.abs().sum(axis=1) > 0.0)
        rets[grp] = r_g.where(invested).rename(grp)
    R = pd.concat([rets[g] for g in BC.GROUP_ORDER], axis=1)
    # NAV — carried NaN through flat bars, starts at 1 first invested bar
    nav = pd.DataFrame(index=R.index, columns=R.columns, dtype=float)
    for g in R.columns:
        active = R[g].notna()
        r0 = R[g].where(active, 0.0)
        nav[g] = (1.0 + r0).cumprod()
        nav.loc[~active, g] = np.nan
    return {"returns": R, "nav": nav, "weights_group": concat_group,
            "weights_per_block": per_block}


# ---------------------------------------------------------------------- #
# Variant runner
# ---------------------------------------------------------------------- #
def run_variant(shared: dict, q: float, epsilon: float,
                alpha_scores: dict[str, pd.DataFrame] | None = None,
                use_trend: bool = USE_TREND,
                budget_method: str = BUDGET_METHOD) -> dict:
    """Build layer-2 composites → layer-1 solve → aggregate → backtest
    (net AND gross). Returns everything needed for reporting."""
    if alpha_scores is None:
        alpha_scores = build_alpha_scores(shared)

    comp = build_composites_two_layer(shared, q, epsilon, alpha_scores)
    R   = comp["returns"][list(BC.GROUP_ORDER)]
    NAV = comp["nav"][list(BC.GROUP_ORDER)]

    if use_trend:
        trend = BR.compute_trend_gate(NAV)
    else:
        trend = pd.DataFrame(True, index=R.index, columns=R.columns)

    W_group, RC_pct, diag = BR.build_block_weights(
        R, trend, budget_method, BR.POLICY_SHARES,
    )

    # Aggregate to name-level: for each group, sub-block weights already
    # include the N_b/N_g share, so we just scale by W_group.
    frames = []
    for grp in BC.GROUP_ORDER:
        Wg = comp["weights_group"][grp]
        if Wg.shape[1] == 0:
            continue
        scale = W_group[grp].reindex(Wg.index).fillna(0.0)
        frames.append(Wg.mul(scale, axis=0))
    W_name = pd.concat(frames, axis=1) if frames else pd.DataFrame(index=R.index)

    fwd = shared["fwd_1w"].reindex(columns=W_name.columns).fillna(0.0)
    K_t = (W_name.abs() > 0).sum(axis=1).astype(int).rename("K_t")

    res_net   = E.run_book(W_name, fwd, cost_per_trade=COST,
                           N_t=K_t.rename("N_t"), K_t=K_t)
    res_gross = E.run_book(W_name, fwd, cost_per_trade=0.0,
                           N_t=K_t.rename("N_t"), K_t=K_t)
    summ_net   = E.summarize_book(res_net)
    summ_gross = E.summarize_book(res_gross)

    cash = (1.0 - W_group.sum(axis=1)).clip(lower=0.0)

    return {"q": q, "epsilon": epsilon,
            "composites": comp,
            "W_group": W_group, "RC_pct": RC_pct, "diag": diag,
            "W_name": W_name, "cash": cash,
            "res_net": res_net, "res_gross": res_gross,
            "summary_net": summ_net, "summary_gross": summ_gross}


def run_baseline(shared: dict, use_trend: bool = USE_TREND,
                 budget_method: str = BUDGET_METHOD) -> dict:
    """Layer-1 baseline for Δ measurement: α blocks fall back to invvol
    hold-all (q=1.0 makes hysteresis select all N_b eligible names; ε=0
    trivially inactive). Non-α blocks unchanged. Same solver / trend."""
    scores = build_alpha_scores(shared)      # cheap; score not used at q=1
    return run_variant(shared, q=1.0, epsilon=0.0,
                       alpha_scores=scores, use_trend=use_trend,
                       budget_method=budget_method)


# ---------------------------------------------------------------------- #
# Sweep + plateau selection
# ---------------------------------------------------------------------- #
def _cost_drag_ann_bp(turnover: float) -> float:
    """Annualized cost drag in basis points, based on turnover per bar
    at 10 bp / side and 52 bars / year."""
    return float(turnover) * COST * 2.0 * C.WEEKS_PER_YEAR * 10000.0


def sweep(shared: dict, qs: Iterable[float] = Q_GRID,
          epsilons: Iterable[float] = EPS_GRID,
          use_trend: bool = USE_TREND) -> tuple[pd.DataFrame, dict, dict]:
    """Run baseline + all (q, ε) cells. Return (sweep DataFrame,
    baseline bundle, per-cell bundles keyed by (q, ε))."""
    print("--- baseline (layer-1 hold-all, α off) ---")
    scores = build_alpha_scores(shared)
    baseline = run_variant(shared, q=1.0, epsilon=0.0,
                           alpha_scores=scores, use_trend=use_trend)
    bn = baseline["summary_net"]; bg = baseline["summary_gross"]
    print(f"  net   IS Sharpe={bn.is_sharpe:+.3f} CAGR={bn.is_cagr*100:+.2f}% "
          f"DD={bn.is_max_dd*100:+.2f}% turn={bn.avg_turnover:.4f}")
    print(f"  gross IS Sharpe={bg.is_sharpe:+.3f} CAGR={bg.is_cagr*100:+.2f}%\n")

    rows = []
    cells: dict[tuple[float, float], dict] = {}
    for q in qs:
        for eps in epsilons:
            print(f"--- cell q={q:.2f} ε={eps:.2f} ---")
            cell = run_variant(shared, q=q, epsilon=eps,
                               alpha_scores=scores, use_trend=use_trend)
            sn = cell["summary_net"]; sg = cell["summary_gross"]
            row = {
                "q":               q,
                "epsilon":         eps,
                "sharpe_net":      sn.is_sharpe,
                "sharpe_gross":    sg.is_sharpe,
                "cagr_net":        sn.is_cagr,
                "cagr_gross":      sg.is_cagr,
                "max_dd_net":      sn.is_max_dd,
                "ann_vol":         sn.annual_vol,
                "turnover":        sn.avg_turnover,
                "mean_K":          sn.mean_K,
                "d_sharpe_net":    sn.is_sharpe    - bn.is_sharpe,
                "d_cagr_net":      sn.is_cagr      - bn.is_cagr,
                "d_dd_net":        sn.is_max_dd    - bn.is_max_dd,
                "d_turnover":      sn.avg_turnover - bn.avg_turnover,
                "cost_drag_bp_yr": _cost_drag_ann_bp(sn.avg_turnover)
                                    - _cost_drag_ann_bp(bn.avg_turnover),
            }
            print(f"  net   Sharpe={sn.is_sharpe:+.3f} (Δ{row['d_sharpe_net']:+.3f})  "
                  f"CAGR={sn.is_cagr*100:+.2f}% (Δ{row['d_cagr_net']*100:+.2f}pp)  "
                  f"turn={sn.avg_turnover:.4f} (Δ{row['d_turnover']:+.4f})")
            rows.append(row)
            cells[(q, eps)] = cell

    return pd.DataFrame(rows), baseline, cells


def apply_plateau_rule(sweep_df: pd.DataFrame,
                       band: float = PLATEAU_BAND) -> tuple[pd.Series, pd.DataFrame]:
    """Plateau selection: within Δ-Sharpe ≥ (max − band), pick lowest
    turnover. Tie-break by lower ε (stickier), then lower q (more
    concentrated). Returns (picked row, plateau DataFrame)."""
    if sweep_df.empty:
        raise ValueError("empty sweep DataFrame")
    max_d = float(sweep_df["d_sharpe_net"].max())
    plateau = sweep_df[sweep_df["d_sharpe_net"] >= max_d - band].copy()
    plateau_sorted = plateau.sort_values(
        by=["turnover", "epsilon", "q"], ascending=[True, True, True]
    ).reset_index(drop=True)
    return plateau_sorted.iloc[0], plateau_sorted


# ---------------------------------------------------------------------- #
# Persistence
# ---------------------------------------------------------------------- #
def _persist_bundle(bundle: dict, out_dir: Path, tag: str) -> Path:
    d = out_dir / tag
    d.mkdir(parents=True, exist_ok=True)
    bundle["W_name"].to_parquet(d / "w_name.parquet")
    bundle["W_group"].to_parquet(d / "w_group.parquet")
    bundle["res_net"].net_ret.to_frame("net_ret").to_csv(d / "net_ret.csv")
    bundle["res_gross"].net_ret.to_frame("gross_ret").to_csv(d / "gross_ret.csv")
    sn = bundle["summary_net"]; sg = bundle["summary_gross"]
    pd.DataFrame([{
        "q": bundle["q"], "epsilon": bundle["epsilon"],
        "sharpe_net": sn.is_sharpe, "sharpe_gross": sg.is_sharpe,
        "cagr_net":  sn.is_cagr,   "cagr_gross": sg.is_cagr,
        "max_dd_net": sn.is_max_dd, "ann_vol": sn.annual_vol,
        "avg_turnover": sn.avg_turnover, "mean_K": sn.mean_K,
        "is_bars": sn.is_bars,
    }]).to_csv(d / "summary.csv", index=False)
    return d


# ---------------------------------------------------------------------- #
# Report
# ---------------------------------------------------------------------- #
def _fmt(x, d=3):  return f"{x:+.{d}f}" if pd.notna(x) else "   —"
def _fmt_pct(x, d=2): return f"{x*100:+.{d}f}%" if pd.notna(x) else "     —"


def _is_slice(s: pd.Series) -> pd.Series:
    return s[s.index <= C.IN_SAMPLE_END]


def _per_year(net: pd.Series) -> pd.DataFrame:
    s = _is_slice(net).copy()
    if s.empty:
        return pd.DataFrame(columns=["year", "ret"])
    df = s.to_frame("r"); df["year"] = df.index.year
    return (df.groupby("year")["r"].sum()
              .rename("ret").reset_index())


def write_report(sweep_df: pd.DataFrame,
                 baseline: dict,
                 cells: dict[tuple[float, float], dict],
                 picked: pd.Series,
                 plateau: pd.DataFrame,
                 report_path: Path) -> None:
    lines: list[str] = []
    lines.append("# Phase 12 × Phase 13 — two-layer book "
                 "(layer-1 risk budget + layer-2 α on broad_cn + sector_cn)\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    lines.append(
        "Layer-1: 4-group risk budget (equity 55 / bond_rates 20 / bond_credit 10 "
        "/ commodity 15 %), LW-target-D shrinkage, log-barrier ERC solver. "
        "**Trend gate off** (ablation showed it Sharpe-neutral post-fix; "
        "user chose the simpler no-gate spec).  "
        "Sub-block share within group = N_b / N_g (static ever-admitted count) "
        "so at α off (q=1, ε=0) the book collapses exactly to the layer-1 "
        f"all-{ALPHA_SIZING} baseline.\n\n"
        "Layer-2: production long_q20-`replace` α-hysteresis kernel on "
        "`broad_cn` (K=5 locked ensemble) and `sector_cn` (K=8 locked ensemble). "
        "Other 6 blocks (bond_rates, bond_credit, cross_border_dm, "
        "cross_border_hk, metals, commodity_other) stay hold-all with "
        f"{NONALPHA_SIZING} sizing. Members are frozen per Phase 13.5 finalists.\n\n"
        f"Cost {COST*10000:.0f} bp/side. IS = bars ≤ {C.IN_SAMPLE_END.date()}. "
        "**OOS sealed**. Sweep: q × ε = "
        f"({', '.join(f'{float(x):.2f}' for x in sorted(sweep_df['q'].unique()))}) × "
        f"({', '.join(f'{float(x):.2f}' for x in sorted(sweep_df['epsilon'].unique()))}) = "
        f"{len(sweep_df)} cells. Plateau rule: within Δ-Sharpe ≥ max − "
        f"{PLATEAU_BAND}, pick lowest turnover cell (tie-break lower ε, then lower q).\n\n"
    )

    # --- §0 baseline ---------------------------------------------------
    bn = baseline["summary_net"]; bg = baseline["summary_gross"]
    lines.append("## 0. Layer-1 baseline (α off; q=1, ε=0)\n")
    lines.append("| metric | net | gross |")
    lines.append("|:---|---:|---:|")
    lines.append(f"| IS Sharpe | {_fmt(bn.is_sharpe)} | {_fmt(bg.is_sharpe)} |")
    lines.append(f"| IS CAGR   | {_fmt_pct(bn.is_cagr)} | {_fmt_pct(bg.is_cagr)} |")
    lines.append(f"| IS max DD | {_fmt_pct(bn.is_max_dd)} | {_fmt_pct(bg.is_max_dd)} |")
    lines.append(f"| ann vol   | {_fmt_pct(bn.annual_vol)} | {_fmt_pct(bg.annual_vol)} |")
    lines.append(f"| turnover  | {bn.avg_turnover:.4f} | {bg.avg_turnover:.4f} |")
    lines.append(f"| mean K    | {bn.mean_K:.1f} | {bg.mean_K:.1f} |")
    lines.append("")

    # --- §1 sweep grid -------------------------------------------------
    lines.append(f"## 1. Sweep — {len(sweep_df)} cells (net metrics, Δ vs baseline)\n")
    lines.append("| q | ε | Sharpe net | Δ Sh | CAGR net | Δ CAGR pp | max DD | "
                 "turnover | Δ turn | cost drag bp/yr |")
    lines.append("|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in sweep_df.iterrows():
        star = " **★**" if (r["q"] == picked["q"] and r["epsilon"] == picked["epsilon"]) else ""
        lines.append(
            f"| {r['q']:.2f}{star} | {r['epsilon']:.2f} | "
            f"{_fmt(r['sharpe_net'])} | {_fmt(r['d_sharpe_net'])} | "
            f"{_fmt_pct(r['cagr_net'])} | "
            f"{r['d_cagr_net']*100:+.2f} | "
            f"{_fmt_pct(r['max_dd_net'])} | "
            f"{r['turnover']:.4f} | "
            f"{r['d_turnover']:+.4f} | "
            f"{r['cost_drag_bp_yr']:+.1f} |"
        )
    lines.append("")

    # --- §2 plateau + pick --------------------------------------------
    lines.append("## 2. Plateau selection\n")
    lines.append(
        f"Max Δ-Sharpe across sweep = "
        f"**{sweep_df['d_sharpe_net'].max():+.3f}**. "
        f"Plateau (Δ-Sharpe ≥ max − {PLATEAU_BAND}) contains "
        f"**{len(plateau)}** cell(s). Winner (lowest turnover within "
        "plateau, tie-break lower ε then lower q):\n\n"
        f"**q = {picked['q']:.2f}, ε = {picked['epsilon']:.2f}** — "
        f"Sharpe net {picked['sharpe_net']:+.3f} (Δ {picked['d_sharpe_net']:+.3f}), "
        f"CAGR net {picked['cagr_net']*100:+.2f}% "
        f"(Δ {picked['d_cagr_net']*100:+.2f} pp), "
        f"turnover {picked['turnover']:.4f}.\n\n"
    )
    if len(plateau) > 1:
        lines.append("Plateau members (sorted by turnover, then ε, then q):\n\n")
        lines.append("| q | ε | Sharpe net | Δ Sh | turnover |")
        lines.append("|:---:|:---:|---:|---:|---:|")
        for _, r in plateau.iterrows():
            lines.append(
                f"| {r['q']:.2f} | {r['epsilon']:.2f} | "
                f"{_fmt(r['sharpe_net'])} | {_fmt(r['d_sharpe_net'])} | "
                f"{r['turnover']:.4f} |"
            )
        lines.append("")

    # --- §3 recommended cell — detailed vs baseline --------------------
    key = (picked["q"], picked["epsilon"])
    pick_cell = cells[key]
    sn = pick_cell["summary_net"]; sg = pick_cell["summary_gross"]
    lines.append(f"## 3. Recommended cell (q = {picked['q']:.2f}, ε = {picked['epsilon']:.2f}) — detailed\n")
    lines.append("| metric | baseline | recommended | Δ |")
    lines.append("|:---|---:|---:|---:|")
    lines.append(f"| Sharpe net    | {_fmt(bn.is_sharpe)} | {_fmt(sn.is_sharpe)} | {_fmt(sn.is_sharpe - bn.is_sharpe)} |")
    lines.append(f"| Sharpe gross  | {_fmt(bg.is_sharpe)} | {_fmt(sg.is_sharpe)} | {_fmt(sg.is_sharpe - bg.is_sharpe)} |")
    lines.append(f"| CAGR net      | {_fmt_pct(bn.is_cagr)} | {_fmt_pct(sn.is_cagr)} | {(sn.is_cagr - bn.is_cagr)*100:+.2f} pp |")
    lines.append(f"| CAGR gross    | {_fmt_pct(bg.is_cagr)} | {_fmt_pct(sg.is_cagr)} | {(sg.is_cagr - bg.is_cagr)*100:+.2f} pp |")
    lines.append(f"| max DD        | {_fmt_pct(bn.is_max_dd)} | {_fmt_pct(sn.is_max_dd)} | {(sn.is_max_dd - bn.is_max_dd)*100:+.2f} pp |")
    lines.append(f"| ann vol       | {_fmt_pct(bn.annual_vol)} | {_fmt_pct(sn.annual_vol)} | {(sn.annual_vol - bn.annual_vol)*100:+.2f} pp |")
    lines.append(f"| turnover      | {bn.avg_turnover:.4f} | {sn.avg_turnover:.4f} | {sn.avg_turnover - bn.avg_turnover:+.4f} |")
    lines.append(f"| mean K names  | {bn.mean_K:.1f} | {sn.mean_K:.1f} | {sn.mean_K - bn.mean_K:+.1f} |")
    lines.append("")

    # --- §4 cost attribution across all cells --------------------------
    lines.append("## 4. Cost attribution (gross vs net, all cells + baseline)\n")
    lines.append("| q | ε | Sharpe gross | Sharpe net | Δ (cost drag) | CAGR gross | CAGR net | Δ pp |")
    lines.append("|:---:|:---:|---:|---:|---:|---:|---:|---:|")
    # baseline row first
    lines.append(f"| — | — | {_fmt(bg.is_sharpe)} | {_fmt(bn.is_sharpe)} | "
                 f"{_fmt(bn.is_sharpe - bg.is_sharpe)} | "
                 f"{_fmt_pct(bg.is_cagr)} | {_fmt_pct(bn.is_cagr)} | "
                 f"{(bn.is_cagr - bg.is_cagr)*100:+.2f} |")
    for _, r in sweep_df.iterrows():
        lines.append(
            f"| {r['q']:.2f} | {r['epsilon']:.2f} | "
            f"{_fmt(r['sharpe_gross'])} | {_fmt(r['sharpe_net'])} | "
            f"{_fmt(r['sharpe_net'] - r['sharpe_gross'])} | "
            f"{_fmt_pct(r['cagr_gross'])} | {_fmt_pct(r['cagr_net'])} | "
            f"{(r['cagr_net'] - r['cagr_gross'])*100:+.2f} |"
        )
    lines.append("")

    # --- §5 per-year --------------------------------------------------
    lines.append("## 5. Per-calendar-year IS return (sum of weekly net)\n")
    # Show baseline + recommended + top 2 by Sharpe (if not already shown)
    top_by_sh = sweep_df.sort_values("sharpe_net", ascending=False).head(3)
    extras = [(r["q"], r["epsilon"]) for _, r in top_by_sh.iterrows()
              if (r["q"], r["epsilon"]) != key][:2]
    year_cols = [("baseline", baseline["res_net"].net_ret),
                 (f"★ q={picked['q']:.2f} ε={picked['epsilon']:.2f}",
                  cells[key]["res_net"].net_ret)]
    for q, eps in extras:
        year_cols.append((f"q={q:.2f} ε={eps:.2f}",
                          cells[(q, eps)]["res_net"].net_ret))
    per_year_dfs = {name: _per_year(s) for name, s in year_cols}
    years = sorted({int(y) for df in per_year_dfs.values() for y in df["year"]})
    lines.append("| year | " + " | ".join(name for name, _ in year_cols) + " |")
    lines.append("|:---:|" + "|".join(["---:"] * len(year_cols)) + "|")
    for y in years:
        row = [f"| {y}"]
        for name, _ in year_cols:
            py = per_year_dfs[name]
            v = py.loc[py["year"] == y, "ret"]
            row.append(_fmt_pct(float(v.iloc[0])) if len(v) else "     —")
        lines.append(" | ".join(row) + " |")
    lines.append("")

    # --- §6 read ------------------------------------------------------
    lines.append("## 6. Read\n")
    dsh = picked["d_sharpe_net"]; dcg = picked["d_cagr_net"] * 100
    if dsh > 0:
        verdict = ("**layer-2 α helps** on this IS window at the "
                   f"chosen cell (+{dsh:.3f} Sharpe, {dcg:+.2f} pp CAGR "
                   "vs the layer-1-only baseline).")
    else:
        verdict = ("**layer-2 α does not help** on this IS window at "
                   f"the chosen cell ({dsh:+.3f} Sharpe, {dcg:+.2f} pp CAGR "
                   "vs the layer-1-only baseline).")
    lines.append(verdict + " Compare to prior anchors:\n"
        "- Layer-1 canonical (`invvol × lw_erc`, no trend): IS Sharpe +1.418 / "
        "CAGR +3.43% / DD −2.55%.\n"
        "- Layer-1 with trend on (`eqw × lw_erc`): IS Sharpe +1.429 / CAGR +3.40% "
        "/ DD −2.55%.\n"
        "- T2 bond_invvol: IS Sharpe +1.425 / CAGR +2.40% / DD −4.26%.\n"
        "- Solo defensive (Phase 11.2 finalist): IS Sharpe +1.002 / CAGR +3.48% "
        "/ DD −5.24%.\n\n"
        "**Plateau discipline.** The recommended cell was chosen by the "
        "plateau rule (Δ-Sharpe within " f"{PLATEAU_BAND}" " of max, "
        "lowest turnover). If the plateau contains only 1 cell the "
        "sweep is not that flat and the winner is a single-cell peak — "
        "watch out for OOS decay. If the plateau contains ≥ 3 cells "
        "spanning multiple q or ε, the recommended cell is robust to "
        "parameter perturbation.\n\n"
        "**Open follow-ups.** (a) Try α on cross_border_hk once its "
        "2024+ OOS opens and non-crashing regime data is available. "
        "(b) Per-block hysteresis knobs — this branch sweeps uniform "
        "(q, ε) across both α blocks; the frozen finalists actually "
        "had ε_broad_cn=0.20 vs ε_sector_cn=1.00 which the uniform "
        "sweep can't recover. (c) Combined intra-sizing sweep for the "
        "non-α blocks (eqw vs invvol) — currently held at "
        f"`{NONALPHA_SIZING}` for clean Δ.\n"
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {report_path}")


# ---------------------------------------------------------------------- #
# CLI + main
# ---------------------------------------------------------------------- #
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--qs", type=str, default=",".join(f"{x:.2f}" for x in Q_GRID),
                   help=f"comma-separated q values (default {Q_GRID})")
    p.add_argument("--epsilons", type=str, default=",".join(f"{x:.2f}" for x in EPS_GRID),
                   help=f"comma-separated ε values (default {EPS_GRID})")
    p.add_argument("--use-trend", action="store_true",
                   help="enable layer-1 trend gate (default OFF per user)")
    p.add_argument("--out-tag", type=str, default=None,
                   help="suffix on data + report paths")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    qs = tuple(float(x) for x in args.qs.split(","))
    epsilons = tuple(float(x) for x in args.epsilons.split(","))
    tag = f"_{args.out_tag}" if args.out_tag else ""
    out_root = C.DATA_DIR / f"block_two_layer_v6{tag}"
    report_p = C.REPORTS_DIR / f"block_two_layer_v6{tag}_report.md"
    out_root.mkdir(parents=True, exist_ok=True)

    shared = BC.load_shared()
    print(f"shared: {len(shared['codes'])} codes, "
          f"{len(shared['fwd_1w'])} bars\n")

    sweep_df, baseline, cells = sweep(shared, qs, epsilons,
                                      use_trend=args.use_trend)
    picked, plateau = apply_plateau_rule(sweep_df)

    # persist
    _persist_bundle(baseline, out_root, "baseline")
    for (q, eps), cell in cells.items():
        cell_tag = f"q{int(round(q*100)):02d}_eps{int(round(eps*100)):03d}"
        _persist_bundle(cell, out_root, cell_tag)
    sweep_df.to_csv(out_root / "sweep_summary.csv", index=False)
    plateau.to_csv(out_root / "plateau_pick.csv", index=False)
    print(f"\nplateau pick: q={picked['q']:.2f} ε={picked['epsilon']:.2f} "
          f"— Sharpe net {picked['sharpe_net']:+.3f} "
          f"(Δ {picked['d_sharpe_net']:+.3f}), "
          f"turn {picked['turnover']:.4f}")

    write_report(sweep_df, baseline, cells, picked, plateau, report_p)


if __name__ == "__main__":
    main()
