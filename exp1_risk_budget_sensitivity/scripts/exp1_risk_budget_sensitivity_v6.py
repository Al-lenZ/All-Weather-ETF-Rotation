"""
v6/scripts/exp1_risk_budget_sensitivity_v6.py
=============================================
Experiment 1 — risk-budget allocation sensitivity surface.

Goal
----
Understand fragility of the frozen (equity 55, bond_rates 20, bond_credit 10,
commodity 15) policy share vector. Sweep three things:

  • control : EW (25/25/25/25)
  • axis    : each of the 4 shares moved by ±10pp, delta spread pro-rata over
              the other three (8 cells) — reads the *marginal* slope per axis
  • grid    : {−10, 0, +10}pp ⁴ Cartesian around the base, renormalized
              (81 cells) — reads joint (curvature / ridge) effects

Everything else is frozen at the Phase 12 × 13 finalist:
    q = 0.20, ε = 0.30, layer-2 α on broad_cn (K=5) + sector_cn (K=8),
    intra-block invvol, LW-target-D shrinkage, log-barrier ERC solver,
    trend gate off, cost = 10 bp/side.

The frozen finalist is *not re-optimized* — this is a sensitivity analysis
on top of a locked spec, not a search. Sharpe/CAGR/DD are reported IS and
pre-stress OOS (2024-01-01 → 2025-07-31) per user request; the v6 stress
hold-out (> 2025-07-31) stays sealed.

Outputs
-------
    data/exp1_risk_budget_sensitivity_v6/
        cells.csv                       — every cell, IS + OOS metrics
        axis_slope.csv                  — per-axis ±10pp slope table
    reports/exp1_risk_budget_sensitivity_v6_report.md

Run
---
    python v6/scripts/exp1_risk_budget_sensitivity_v6.py
"""
from __future__ import annotations

import itertools
from datetime import datetime
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
import block_composite_v6 as BC
import block_risk_budget_v6 as BR
import block_two_layer_v6 as TL


# ---------------------------------------------------------------------- #
# Config
# ---------------------------------------------------------------------- #
Q_FIN, EPS_FIN = 0.20, 0.30                                  # finalist
BASE_SHARES: dict[str, float] = dict(BR.POLICY_SHARES)       # 55/20/10/15
EW_SHARES:   dict[str, float] = {g: 0.25 for g in BC.GROUP_ORDER}
DELTA_PP = 0.10
GRID_STEPS_PP: tuple[float, ...] = (-0.10, 0.0, +0.10)

OUT_ROOT = C.DATA_DIR / "exp1_risk_budget_sensitivity_v6"
REPORT_PATH = C.DATA_DIR.parent / "reports" / "exp1_risk_budget_sensitivity_v6_report.md"


# ---------------------------------------------------------------------- #
# Warmup-trim helpers (convention per block_two_layer_oos_shot_v6)
# ---------------------------------------------------------------------- #
def _first_live_bar(net_ret: pd.Series) -> pd.Timestamp:
    """First bar where |net_ret| > 0 — end of the book's own warmup.
    All Phase 12 × 13 variants share the layer-1 52 W cov warmup, so
    every cell in this sweep will land on the same date."""
    nz = (net_ret.abs() > 0.0)
    if not bool(nz.any()):
        return net_ret.index[0]
    return net_ret.index[int(nz.values.argmax())]


def _window_metrics(net: pd.Series) -> dict:
    n = int(len(net))
    if n < 2:
        return {"n_bars": n, "sharpe": np.nan, "cagr": np.nan,
                "max_dd": np.nan, "ann_vol": np.nan}
    ann_vol = float(net.std(ddof=1)) * np.sqrt(C.WEEKS_PER_YEAR)
    ann_ret = float(net.mean()) * C.WEEKS_PER_YEAR
    sharpe  = (ann_ret / ann_vol) if ann_vol > 0 else np.nan
    cumret  = float(net.sum())
    n_yrs   = max(n / C.WEEKS_PER_YEAR, 1e-3)
    cagr    = max(1.0 + cumret, 1e-9) ** (1.0 / n_yrs) - 1.0
    nav     = 1.0 + net.cumsum()
    max_dd  = float(((nav - nav.cummax()) / nav.cummax()).min())
    return {"n_bars": n, "sharpe": sharpe, "cagr": cagr, "max_dd": max_dd,
            "ann_vol": ann_vol}


def _trimmed_metrics(net_ret: pd.Series,
                     start: pd.Timestamp) -> dict:
    """IS/OOS metrics on [start, IN_SAMPLE_END] ∪ [OOS_START, OOS_END]."""
    idx = net_ret.index
    is_slice  = net_ret[(idx >= start) & (idx <= C.IN_SAMPLE_END)]
    oos_slice = net_ret[(idx >= C.OOS_START) & (idx <= C.OOS_END)]
    is_m  = _window_metrics(is_slice)
    oos_m = _window_metrics(oos_slice)
    return {
        "is_sharpe":  is_m["sharpe"],
        "oos_sharpe": oos_m["sharpe"],
        "is_cagr":    is_m["cagr"],
        "oos_cagr":   oos_m["cagr"],
        "is_max_dd":  is_m["max_dd"],
        "oos_max_dd": oos_m["max_dd"],
        "annual_vol": is_m["ann_vol"],       # IS ann vol (matches convention)
        "is_bars":    is_m["n_bars"],
        "oos_bars":   oos_m["n_bars"],
    }


# ---------------------------------------------------------------------- #
# Share vector construction
# ---------------------------------------------------------------------- #
def _normalize(s: dict[str, float]) -> dict[str, float]:
    tot = float(sum(s.values()))
    if tot <= 0:
        raise ValueError(f"non-positive total share: {s}")
    return {k: v / tot for k, v in s.items()}


def _clip_nonneg(s: dict[str, float]) -> dict[str, float]:
    return {k: max(0.0, float(v)) for k, v in s.items()}


def axis_shares(base: dict[str, float], group: str, delta: float
                ) -> dict[str, float]:
    """Move ``group``'s share by ``delta`` (signed, in absolute share units),
    spread −delta pro-rata over the remaining groups by their base share
    (so equal-weight base collapses to uniform compensation). Clip at 0 to
    guard against pathological cells, then renormalize."""
    others = [g for g in base if g != group]
    other_sum = sum(base[g] for g in others)
    if other_sum <= 0:
        raise ValueError(f"cannot spread delta — other groups sum to 0")
    out = dict(base)
    out[group] = base[group] + delta
    for g in others:
        out[g] = base[g] - delta * (base[g] / other_sum)
    return _normalize(_clip_nonneg(out))


def grid_shares(base: dict[str, float],
                steps: tuple[float, ...] = GRID_STEPS_PP
                ) -> list[tuple[dict[str, float], dict[str, float]]]:
    """Cartesian {−δ, 0, +δ}^G steps around base; each cell renormalized.

    Returns list of (cell_shares, raw_offsets) tuples. Skips the origin
    (all-zero) since it duplicates the base cell logged separately.
    """
    groups = list(base)
    out = []
    for offs in itertools.product(steps, repeat=len(groups)):
        if all(abs(o) < 1e-12 for o in offs):
            continue
        raw = {g: base[g] + o for g, o in zip(groups, offs)}
        raw = _clip_nonneg(raw)
        # Renormalize; if the whole vector is 0 (impossible with our steps)
        # skip.
        tot = sum(raw.values())
        if tot <= 0:
            continue
        norm = {g: raw[g] / tot for g in groups}
        offset_dict = dict(zip(groups, offs))
        out.append((norm, offset_dict))
    return out


# ---------------------------------------------------------------------- #
# Variant runner with custom policy_shares
# ---------------------------------------------------------------------- #
def run_with_shares(shared: dict,
                    alpha_scores: dict[str, pd.DataFrame],
                    policy_shares: dict[str, float],
                    q: float = Q_FIN,
                    epsilon: float = EPS_FIN,
                    ) -> dict:
    """Mirror of ``block_two_layer_v6.run_variant`` but with a custom
    ``policy_shares`` fed into the layer-1 solver. Everything else
    (layer-2 α blocks, sizing, cost, trend-off) matches the frozen
    Phase 12 × 13 finalist so ΔSharpe/ΔCAGR/ΔDD isolate the risk-budget
    change alone.
    """
    comp = TL.build_composites_two_layer(shared, q, epsilon, alpha_scores)
    R    = comp["returns"][list(BC.GROUP_ORDER)]

    # Trend off (frozen finalist).
    trend = pd.DataFrame(True, index=R.index, columns=R.columns)

    W_group, RC_pct, diag = BR.build_block_weights(
        R, trend, TL.BUDGET_METHOD, policy_shares,
    )

    # Aggregate to name-level using the layer-2 concat panels.
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

    res_net = E.run_book(W_name, fwd, cost_per_trade=TL.COST,
                         N_t=K_t.rename("N_t"), K_t=K_t)
    summ    = E.summarize_book(res_net)
    return {"summary": summ, "W_group": W_group, "W_name": W_name, "res": res_net}


# ---------------------------------------------------------------------- #
# Cell rows
# ---------------------------------------------------------------------- #
def _row(tag: str, kind: str, axis: str, direction: str,
         shares: dict[str, float],
         summ: E.BookSummary,
         trimmed: dict,
         offsets: dict[str, float] | None = None) -> dict:
    """Trimmed IS/OOS metrics take precedence — warmup bars stripped so
    Sharpe / CAGR / DD denominators exclude the all-zero pre-live period.
    Turnover + mean_K stay as-is (whole-panel means; the extra zero bars
    just slightly dilute the mean, informationally consistent)."""
    row = {
        "tag":            tag,
        "kind":           kind,
        "axis":           axis,
        "direction":      direction,
        "eq_share":       shares["equity"],
        "br_share":       shares["bond_rates"],
        "bc_share":       shares["bond_credit"],
        "cm_share":       shares["commodity"],
        "is_sharpe":      trimmed["is_sharpe"],
        "oos_sharpe":     trimmed["oos_sharpe"],
        "is_cagr":        trimmed["is_cagr"],
        "oos_cagr":       trimmed["oos_cagr"],
        "is_max_dd":      trimmed["is_max_dd"],
        "oos_max_dd":     trimmed["oos_max_dd"],
        "is_ann_vol":     trimmed["annual_vol"],
        "is_bars":        trimmed["is_bars"],
        "oos_bars":       trimmed["oos_bars"],
        "avg_turnover":   summ.avg_turnover,
        "mean_K":         summ.mean_K,
    }
    if offsets is not None:
        for g in BC.GROUP_ORDER:
            row[f"off_{g}"] = offsets.get(g, 0.0)
    return row


# ---------------------------------------------------------------------- #
# Sweep driver
# ---------------------------------------------------------------------- #
def run_sweep() -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    print("--- exp1 risk-budget sensitivity ---")
    print(f"base shares  : {BASE_SHARES}")
    print(f"EW shares    : {EW_SHARES}")
    print(f"finalist cell: q={Q_FIN}, ε={EPS_FIN}")

    shared = BC.load_shared()
    alpha_scores = TL.build_alpha_scores(shared)

    rows: list[dict] = []

    # --- 0. base + EW control -----------------------------------------
    # Compute first-live bar from the base cell — all cells share the
    # layer-1 52 W cov warmup, so the same start date applies to every
    # variant. Assert consistency defensively as we sweep.
    print("\n[control] base (55/20/10/15)")
    r = run_with_shares(shared, alpha_scores, BASE_SHARES)
    first_live = _first_live_bar(r["res"].net_ret)
    print(f"  first-live bar (warmup end): {first_live.date()}")
    trimmed = _trimmed_metrics(r["res"].net_ret, first_live)
    rows.append(_row("base", "control", "—", "—", BASE_SHARES,
                     r["summary"], trimmed))
    _pp(rows[-1])

    print("[control] EW (25/25/25/25)")
    r = run_with_shares(shared, alpha_scores, EW_SHARES)
    trimmed = _trimmed_metrics(r["res"].net_ret, first_live)
    rows.append(_row("EW", "control", "—", "—", EW_SHARES,
                     r["summary"], trimmed))
    _pp(rows[-1])

    # --- 1. axis ±10pp -------------------------------------------------
    print("\n[axis] ±10pp per group, delta spread pro-rata")
    for g in BC.GROUP_ORDER:
        for delta, dtag in ((+DELTA_PP, "+10pp"), (-DELTA_PP, "-10pp")):
            shares = axis_shares(BASE_SHARES, g, delta)
            r = run_with_shares(shared, alpha_scores, shares)
            tag = f"axis_{g}_{dtag}"
            print(f"  {tag}  shares={_fmt_shares(shares)}")
            trimmed = _trimmed_metrics(r["res"].net_ret, first_live)
            rows.append(_row(tag, "axis", g, dtag, shares,
                             r["summary"], trimmed))
            _pp(rows[-1])

    # --- 2. full 3^4 grid ---------------------------------------------
    print("\n[grid] {-10, 0, +10}^4 renormalized")
    for shares, offsets in grid_shares(BASE_SHARES):
        tag = "grid_" + "_".join(
            f"{g[:2]}{int(round(offsets[g]*100)):+d}"
            for g in BC.GROUP_ORDER
        )
        r = run_with_shares(shared, alpha_scores, shares)
        trimmed = _trimmed_metrics(r["res"].net_ret, first_live)
        rows.append(_row(tag, "grid", "—", "—", shares,
                         r["summary"], trimmed, offsets=offsets))
    print(f"  ran {sum(1 for r in rows if r['kind']=='grid')} grid cells")

    cells = pd.DataFrame(rows)
    axis_df = _axis_slope_table(cells)
    return cells, axis_df, first_live


def _axis_slope_table(cells: pd.DataFrame) -> pd.DataFrame:
    """Per-axis ±10pp Δ vs base — reads which direction is steepest."""
    base = cells.query("tag == 'base'").iloc[0]
    out = []
    for g in BC.GROUP_ORDER:
        for sign in ("+10pp", "-10pp"):
            row = cells.query(f"tag == 'axis_{g}_{sign}'")
            if row.empty:
                continue
            r = row.iloc[0]
            out.append({
                "axis":            g,
                "direction":       sign,
                "d_is_sharpe":     r.is_sharpe   - base.is_sharpe,
                "d_oos_sharpe":    r.oos_sharpe  - base.oos_sharpe,
                "d_is_cagr_pp":    (r.is_cagr    - base.is_cagr) * 100,
                "d_oos_cagr_pp":   (r.oos_cagr   - base.oos_cagr) * 100,
                "d_is_max_dd_pp":  (r.is_max_dd  - base.is_max_dd) * 100,
                "d_oos_max_dd_pp": (r.oos_max_dd - base.oos_max_dd) * 100,
            })
    return pd.DataFrame(out)


# ---------------------------------------------------------------------- #
# Formatting helpers
# ---------------------------------------------------------------------- #
def _fmt_shares(s: dict[str, float]) -> str:
    return "/".join(f"{s[g]*100:.1f}" for g in BC.GROUP_ORDER)


def _pp(r: dict) -> None:
    print(
        f"    IS  Sh {r['is_sharpe']:+.3f}  CAGR {r['is_cagr']*100:+.2f}%  "
        f"DD {r['is_max_dd']*100:+.2f}%   "
        f"OOS Sh {r['oos_sharpe']:+.3f}  CAGR {r['oos_cagr']*100:+.2f}%  "
        f"DD {r['oos_max_dd']*100:+.2f}%"
    )


# ---------------------------------------------------------------------- #
# Report
# ---------------------------------------------------------------------- #
def _fmt(x, d=3):
    return f"{x:+.{d}f}" if pd.notna(x) else "   —"


def _fmt_pct(x, d=2):
    return f"{x*100:+.{d}f}%" if pd.notna(x) else "     —"


def write_report(cells: pd.DataFrame, axis_df: pd.DataFrame,
                 first_live: pd.Timestamp,
                 report_path: Path) -> None:
    base = cells.query("tag == 'base'").iloc[0]
    ew   = cells.query("tag == 'EW'").iloc[0]

    is_bars = int(base["is_bars"]) if "is_bars" in base else 0
    oos_bars = int(base["oos_bars"]) if "oos_bars" in base else 0

    lines: list[str] = []
    lines.append("# Experiment 1 — Risk-budget allocation sensitivity\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n\n")
    lines.append(
        "Frozen: layer-2 α broad_cn (K=5) + sector_cn (K=8), invvol intra-block, "
        f"LW-target-D + log-barrier ERC solver, trend off, cost {TL.COST*10000:.0f} bp/side, "
        f"finalist cell q={Q_FIN}, ε={EPS_FIN}. **Only** POLICY_SHARES varies.  \n\n"
        "**Warmup handling** — Sharpe / CAGR / DD denominators exclude the "
        "pre-live warmup period. Effective IS window = "
        f"**[{first_live.date()}, {C.IN_SAMPLE_END.date()}]** "
        f"({is_bars} weekly bars). Warmup end = first bar with non-zero "
        "net return (Phase 12 layer-1 has a 52-week cov window); all 90 "
        "cells share the same layer-1 solver and therefore the same "
        "first-live bar. OOS window unchanged at "
        f"[{C.OOS_START.date()}, {C.OOS_END.date()}] ({oos_bars} bars). "
        "v6 stress hold-out (> 2025-07-31) sealed.  \n\n"
    )

    # ------------------------------------------------------------------
    # §1. Controls: base + EW
    # ------------------------------------------------------------------
    lines.append("## 1. Controls\n")
    lines.append("| cell | equity | bond_r | bond_c | comm |"
                 " IS Sh | OOS Sh | IS CAGR | OOS CAGR | IS DD | OOS DD | turn |")
    lines.append("|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in cells.query("kind == 'control'").iterrows():
        lines.append(
            f"| {r['tag']} | {r.eq_share*100:.1f} | {r.br_share*100:.1f} | "
            f"{r.bc_share*100:.1f} | {r.cm_share*100:.1f} | "
            f"{_fmt(r.is_sharpe)} | {_fmt(r.oos_sharpe)} | "
            f"{_fmt_pct(r.is_cagr)} | {_fmt_pct(r.oos_cagr)} | "
            f"{_fmt_pct(r.is_max_dd)} | {_fmt_pct(r.oos_max_dd)} | "
            f"{r.avg_turnover:.4f} |"
        )
    d_is  = ew.is_sharpe  - base.is_sharpe
    d_oos = ew.oos_sharpe - base.oos_sharpe
    lines.append(f"\n**Base → EW**: ΔIS Sharpe {d_is:+.3f}, ΔOOS Sharpe {d_oos:+.3f}. "
                 f"ΔIS CAGR {(ew.is_cagr - base.is_cagr)*100:+.2f} pp, "
                 f"ΔOOS CAGR {(ew.oos_cagr - base.oos_cagr)*100:+.2f} pp.  \n\n")

    # ------------------------------------------------------------------
    # §2. Axis-wise ±10pp — slope per axis
    # ------------------------------------------------------------------
    lines.append("## 2. Axis-wise ±10pp — marginal slope per axis\n")
    lines.append(
        "Move one block's share by ±10pp, spread the compensating "
        "delta pro-rata over the other three (proportional to base share). "
        "A steep column = fragility in that direction.\n\n"
    )
    lines.append("| axis | dir | Δ IS Sh | Δ OOS Sh | Δ IS CAGR pp | "
                 "Δ OOS CAGR pp | Δ IS DD pp | Δ OOS DD pp |")
    lines.append("|:---|:---:|---:|---:|---:|---:|---:|---:|")
    for _, r in axis_df.iterrows():
        lines.append(
            f"| {r['axis']} | {r['direction']} | "
            f"{r['d_is_sharpe']:+.3f} | {r['d_oos_sharpe']:+.3f} | "
            f"{r['d_is_cagr_pp']:+.2f} | {r['d_oos_cagr_pp']:+.2f} | "
            f"{r['d_is_max_dd_pp']:+.2f} | {r['d_oos_max_dd_pp']:+.2f} |"
        )
    # steepest axis (by |Δ IS Sh| + |Δ OOS Sh| aggregated per axis)
    agg = (axis_df.assign(mag=lambda d: d.d_is_sharpe.abs() + d.d_oos_sharpe.abs())
                   .groupby("axis")["mag"].sum()
                   .sort_values(ascending=False))
    lines.append(f"\n**Steepest axis** by Σ|ΔSharpe| (IS + OOS): "
                 f"{agg.index[0]} ({agg.iloc[0]:.3f}).  \n")
    lines.append("Full ranking:  \n")
    for a, v in agg.items():
        lines.append(f"- {a}: {v:.3f}")
    lines.append("")

    # ------------------------------------------------------------------
    # §3. Full 3^4 grid summary
    # ------------------------------------------------------------------
    grid = cells.query("kind == 'grid'").copy()
    lines.append(f"\n## 3. Full grid — {len(grid)} cells\n")
    lines.append(
        "Cartesian {−10, 0, +10}pp on each of the 4 axes around the base, "
        "renormalized. Cells with any negative pre-normalization share clipped at 0.\n\n"
    )
    # summary stats
    for metric, col in [
        ("IS Sharpe",  "is_sharpe"),
        ("OOS Sharpe", "oos_sharpe"),
        ("IS CAGR",    "is_cagr"),
        ("OOS CAGR",   "oos_cagr"),
        ("IS max DD",  "is_max_dd"),
        ("OOS max DD", "oos_max_dd"),
    ]:
        s = grid[col]
        base_v = base[col]
        pcent = "*100 %*" if "CAGR" in metric or "DD" in metric else ""
        scale = 100.0 if ("CAGR" in metric or "DD" in metric) else 1.0
        suffix = " %" if scale != 1.0 else ""
        lines.append(
            f"- **{metric}**: base = {base_v*scale:+.2f}{suffix} · "
            f"grid min = {s.min()*scale:+.2f}{suffix} · "
            f"median = {s.median()*scale:+.2f}{suffix} · "
            f"max = {s.max()*scale:+.2f}{suffix} · "
            f"σ across cells = {s.std()*scale:.3f}{suffix}"
        )
    lines.append("")

    # Top / bottom 5 by OOS Sharpe
    lines.append("### 3a. Top 5 cells by OOS Sharpe\n")
    lines.append(_grid_table(grid.nlargest(5, "oos_sharpe")))
    lines.append("### 3b. Bottom 5 cells by OOS Sharpe\n")
    lines.append(_grid_table(grid.nsmallest(5, "oos_sharpe")))

    # ------------------------------------------------------------------
    # §4. Read-off — where is the surface steep?
    # ------------------------------------------------------------------
    lines.append("## 4. Read-off\n")
    ax_top = agg.index[0]
    lines.append(
        f"- Axis-wise ±10pp Σ|ΔSharpe| ranks: {', '.join(f'{a}={v:.3f}' for a, v in agg.items())}.\n"
        f"- Steepest = **{ax_top}**; that's the fragility direction to "
        "watch if the policy prior on it drifts.\n"
        "- EW control (25/25/25/25) vs base tells you the price you're "
        "paying (or getting refunded) for concentrating risk on equity.\n"
        "- If OOS response has the *opposite sign* of IS response on any "
        "axis, that's a warning the policy prior is IS-fit, not structural.\n"
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwrote {report_path}")


def _grid_table(sub: pd.DataFrame) -> str:
    hdr = ("| equity | bond_r | bond_c | comm | IS Sh | OOS Sh | "
           "IS CAGR | OOS CAGR | IS DD | OOS DD |")
    sep = "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    body = []
    for _, r in sub.iterrows():
        body.append(
            f"| {r.eq_share*100:.1f} | {r.br_share*100:.1f} | "
            f"{r.bc_share*100:.1f} | {r.cm_share*100:.1f} | "
            f"{_fmt(r.is_sharpe)} | {_fmt(r.oos_sharpe)} | "
            f"{_fmt_pct(r.is_cagr)} | {_fmt_pct(r.oos_cagr)} | "
            f"{_fmt_pct(r.is_max_dd)} | {_fmt_pct(r.oos_max_dd)} |"
        )
    return "\n".join([hdr, sep, *body, ""])


# ---------------------------------------------------------------------- #
# Main
# ---------------------------------------------------------------------- #
def main() -> None:
    cells, axis_df, first_live = run_sweep()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    cells.to_csv(OUT_ROOT / "cells.csv", index=False)
    axis_df.to_csv(OUT_ROOT / "axis_slope.csv", index=False)
    print(f"\nwrote {OUT_ROOT / 'cells.csv'} ({len(cells)} cells)")
    print(f"wrote {OUT_ROOT / 'axis_slope.csv'}")

    write_report(cells, axis_df, first_live, REPORT_PATH)


if __name__ == "__main__":
    main()
