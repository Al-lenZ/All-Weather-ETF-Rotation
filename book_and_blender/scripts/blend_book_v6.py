"""
v6/scripts/blend_book_v6.py
===========================
Blend book — combines the Phase 9.1 per-cell static α with the Phase 8.2
equal-weight ensemble α in rank space.

v4pool convention (design §7, `book_xs.py`):

    blend_alpha[t, i] = 0.5 · cs_rank(static)[t, i]
                      + 0.5 · cs_rank(model)[t, i]

The rationale: static and model are (assumed to be) optimizing orthogonal
signals, so a rank-space equal-weight combination should generalize
better than either leg alone. v4pool used ridge output as the model leg;
v6 does not have a ridge yet (Phase 8.3 deferred), so we sub the EQW
baseline in that slot to test whether the blending idea itself lifts
performance.

Legs
----
    static — Phase 9.1 per-cell ensemble α from
             `data/v6_static/{mode}_q{qq}/ensemble_alpha.parquet`.
             Different α per (mode, q) cell — selection was tuned there.
    eqw    — Phase 8.2 ensemble α from
             `data/eqw_baseline_v6/{variant}/ensemble_alpha.parquet`.
             SAME α across all (mode, q); only the book engine varies.
             Two variants: dedup_v6 (28 factors), stability_v6 (5).

Per-cell blend recipe: rebuild both legs on the W-FRI grid, apply
membership mask, per-bar CS Gaussian rank each, then equal-weight
average. Run the blended α through `xs_engine_v6` at the same (mode, q)
that defined the static leg. Cost stays on (10 bp/side per
`feedback_backtests_cost_on`).

Skipped cells
-------------
`ls_q05` and `ls_q10`: Phase 9.1's static α is entirely NaN there (no
factor passed the book-Sharpe screen at those q's). Blend is undefined
in the strict sense — do NOT fall back to EQW-alone (would silently
inflate the blend column). Reported as "no static leg" in the grid.

Outputs
-------
    data/blend_book_v6/{variant}/{cell}/blend_alpha.parquet
    data/blend_book_v6/{variant}/{cell}/blend_weights.parquet
    data/blend_book_v6/{variant}/{cell}/blend_net_ret.csv
    data/blend_book_v6/{variant}/blend_grid.csv
    reports/blend_book_v6_report.md

Run
---
    python v6/scripts/blend_book_v6.py
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
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


BOOK_GRID = tuple(("long", q) for q in (0.05, 0.10, 0.20)) + \
            tuple(("ls",   q) for q in (0.05, 0.10, 0.20))
EQW_VARIANTS = ("dedup_v6", "stability_v6")

OUT_ROOT = C.DATA_DIR / "blend_book_v6"


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #
def _cell_tag(mode: str, q: float) -> str:
    return f"{mode}_q{int(round(q * 100)):02d}"


def _has_finite(df: pd.DataFrame) -> bool:
    return bool(np.isfinite(df.values).any())


def _load_common_inputs(data_dir: Path) -> dict:
    mem = pd.read_parquet(data_dir / "universe_v6" / "membership.parquet")
    codes = list(mem.columns[mem.any(axis=0)])
    mem = mem[codes].astype(bool)
    fwd   = pd.read_parquet(data_dir / "panels_v6" / "fwd_1w.parquet")[codes]
    sigma = pd.read_parquet(data_dir / "panels_v6" / "sigma_causal_26w.parquet")[codes]
    return {"membership": mem, "codes": codes, "fwd_1w": fwd, "sigma": sigma}


def _load_static_alpha(data_dir: Path, mode: str, q: float,
                       codes: list[str]) -> pd.DataFrame | None:
    """Return None if the Phase 9.1 α at this cell is entirely NaN."""
    p = data_dir / "v6_static" / _cell_tag(mode, q) / "ensemble_alpha.parquet"
    if not p.exists():
        return None
    a = pd.read_parquet(p).reindex(columns=codes)
    return a if _has_finite(a) else None


def _load_eqw_alpha(data_dir: Path, variant: str,
                    codes: list[str]) -> pd.DataFrame:
    p = data_dir / "eqw_baseline_v6" / variant / "ensemble_alpha.parquet"
    if not p.exists():
        raise SystemExit(f"missing {p} — run eqw_baseline_v6.py first")
    return pd.read_parquet(p).reindex(columns=codes)


# ---------------------------------------------------------------------- #
# Rank-space blend
# ---------------------------------------------------------------------- #
def blend_alpha(static: pd.DataFrame, eqw: pd.DataFrame,
                membership: pd.DataFrame,
                w_static: float = 0.5,
                w_eqw:    float = 0.5) -> pd.DataFrame:
    """Per-bar CS Gaussian rank each leg, then weighted average.

    Membership mask applied before ranking so per-bar ranks are over
    the in-panel set only. NaN inputs remain NaN in the ranked leg;
    the mean uses skip-NaN so a cell with only one defined leg still
    gets a value equal to that leg's rank (times its weight fraction).
    """
    idx  = static.index.union(eqw.index).sort_values()
    cols = static.columns.union(eqw.columns)

    S = C.apply_membership(static.reindex(index=idx, columns=cols), membership)
    Q = C.apply_membership(eqw.reindex(index=idx, columns=cols), membership)

    S_r = C.cs_gaussian_rank(S)
    Q_r = C.cs_gaussian_rank(Q)

    stack = np.stack([w_static * S_r.values, w_eqw * Q_r.values], axis=0)
    with np.errstate(invalid="ignore"):
        m = np.nanmean(stack, axis=0)
    return pd.DataFrame(m, index=idx, columns=cols)


# ---------------------------------------------------------------------- #
# Cell driver
# ---------------------------------------------------------------------- #
def run_cell(mode: str, q: float, variant: str,
             data: dict, static_alpha: pd.DataFrame,
             eqw_alpha: pd.DataFrame,
             out_root: Path,
             cost_per_trade: float = E.DEFAULT_COST_PER_TRADE) -> dict:
    cell = _cell_tag(mode, q)
    out_dir = out_root / variant / cell
    out_dir.mkdir(parents=True, exist_ok=True)

    blend = blend_alpha(static_alpha, eqw_alpha, data["membership"])
    res, summ = E.backtest_alpha(
        blend, data["sigma"], data["fwd_1w"], data["membership"],
        q, mode, cost_per_trade=cost_per_trade,
    )
    blend.to_parquet(out_dir / "blend_alpha.parquet")
    res.weights.to_parquet(out_dir / "blend_weights.parquet")
    res.net_ret.to_frame("net_ret").to_csv(out_dir / "blend_net_ret.csv")

    return {"variant": variant, "mode": mode, "q": q, "cell": cell,
            **asdict(summ)}


# ---------------------------------------------------------------------- #
# Comparison table (blend vs static-alone vs EQW-alone)
# ---------------------------------------------------------------------- #
def _load_static_grid(data_dir: Path) -> pd.DataFrame:
    return pd.read_csv(data_dir / "v6_static" / "grid_summary.csv")


def _load_eqw_grid(data_dir: Path, variant: str) -> pd.DataFrame:
    return pd.read_csv(data_dir / "eqw_baseline_v6" / variant / "book_grid.csv")


def build_comparison(blend_grid: pd.DataFrame,
                     static_grid: pd.DataFrame,
                     eqw_grid: pd.DataFrame) -> pd.DataFrame:
    """One row per (mode, q) with full/OOS Sharpe for each of the three
    variants, plus deltas of blend vs the two references."""
    key_cols = ["mode", "q"]
    b = blend_grid[key_cols + ["full_sharpe", "oos_sharpe",
                               "avg_turnover"]].rename(
        columns={"full_sharpe":   "blend_full",
                 "oos_sharpe":    "blend_oos",
                 "avg_turnover":  "blend_turn"})
    s = static_grid[key_cols + ["full_sharpe", "oos_sharpe",
                                "avg_turnover"]].rename(
        columns={"full_sharpe":   "static_full",
                 "oos_sharpe":    "static_oos",
                 "avg_turnover":  "static_turn"})
    e = eqw_grid[key_cols + ["full_sharpe", "oos_sharpe",
                             "avg_turnover"]].rename(
        columns={"full_sharpe":   "eqw_full",
                 "oos_sharpe":    "eqw_oos",
                 "avg_turnover":  "eqw_turn"})
    out = b.merge(s, on=key_cols, how="left").merge(e, on=key_cols, how="left")
    out["d_full_vs_static"] = out["blend_full"] - out["static_full"]
    out["d_full_vs_eqw"]    = out["blend_full"] - out["eqw_full"]
    out["d_oos_vs_static"]  = out["blend_oos"]  - out["static_oos"]
    out["d_oos_vs_eqw"]     = out["blend_oos"]  - out["eqw_oos"]
    return out


# ---------------------------------------------------------------------- #
# Report
# ---------------------------------------------------------------------- #
def _fmt(v: float, spec: str) -> str:
    return "n/a" if not np.isfinite(v) else format(v, spec)


def _write_report(blend_grids: dict[str, pd.DataFrame],
                  comparison: dict[str, pd.DataFrame],
                  skipped_cells: list[str],
                  reports_dir: Path,
                  cost_per_trade: float) -> str:
    lines: list[str] = []
    lines.append("# Blend book (static + EQW) — v6\n")
    lines.append(
        "Rank-space equal-weight blend of the Phase 9.1 static α (per-cell "
        "book-screened) and the Phase 8.2 equal-weight α (IC-shortlisted). "
        "Recipe (v4pool convention, design §7):\n"
    )
    lines.append(
        "```\n"
        "blend[t, i] = 0.5 · cs_rank(static)[t, i] + 0.5 · cs_rank(eqw)[t, i]\n"
        "```\n"
    )
    lines.append(
        "Membership mask applied before ranking. Blend α → `xs_engine_v6` "
        f"at the same (mode, q) with {cost_per_trade*1e4:.0f} bp/side cost. "
        "v4pool used ridge for the second leg; v6 subs EQW while the ridge "
        "is deferred, so this test isolates the *blending idea* (rank-space "
        "combination of orthogonal selections) from the model quality itself.\n"
    )
    if skipped_cells:
        lines.append(
            f"\n**Skipped cells** ({len(skipped_cells)}): "
            f"{', '.join(skipped_cells)}. Phase 9.1 had no static leg here "
            "(no factor cleared the book-Sharpe screen at those q's), so "
            "blend is undefined. Fallback to EQW-alone would silently "
            "inflate the blend column — omitted instead.\n"
        )

    for variant in EQW_VARIANTS:
        lines.append(f"\n## {variant}\n")
        if variant not in blend_grids or blend_grids[variant].empty:
            lines.append("_(no blend cells for this variant)_\n")
            continue

        # Blend grid table
        lines.append("### Blend book — grid (net of cost)\n")
        lines.append("| mode | q | IS Sharpe | OOS Sharpe | full Sharpe | decay | "
                     "IS cumret | OOS cumret | full cumret | full DD | "
                     "avg turnover | mean_K |")
        lines.append("|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for _, r in blend_grids[variant].iterrows():
            lines.append(
                f"| {r['mode']} | {r['q']:.2f} | "
                f"{r['is_sharpe']:+.3f} | {r['oos_sharpe']:+.3f} | "
                f"{r['full_sharpe']:+.3f} | {r['decay_ratio']:+.2f} | "
                f"{r['is_cumret']*100:+.2f}% | {r['oos_cumret']*100:+.2f}% | "
                f"{r['full_cumret']*100:+.2f}% | {r['full_max_dd']*100:+.2f}% | "
                f"{r['avg_turnover']:.3f} | {r['mean_K']:.1f} |"
            )

        # 3-way comparison table
        if variant in comparison and not comparison[variant].empty:
            lines.append("\n### Side-by-side vs static-alone (9.1) vs EQW-alone (8.2)\n")
            lines.append("Full Sharpe and OOS Sharpe for each of the three "
                         "variants at the same (mode, q). Positive Δ = blend "
                         "beats the reference leg.\n")
            lines.append("| mode | q | static full | eqw full | **blend full** | "
                         "Δ vs static | Δ vs eqw | static OOS | eqw OOS | "
                         "**blend OOS** | Δ vs static | Δ vs eqw |")
            lines.append("|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
            for _, r in comparison[variant].iterrows():
                lines.append(
                    f"| {r['mode']} | {r['q']:.2f} | "
                    f"{_fmt(r['static_full'], '+.3f')} | "
                    f"{_fmt(r['eqw_full'],   '+.3f')} | "
                    f"**{_fmt(r['blend_full'],'+.3f')}** | "
                    f"{_fmt(r['d_full_vs_static'], '+.3f')} | "
                    f"{_fmt(r['d_full_vs_eqw'],    '+.3f')} | "
                    f"{_fmt(r['static_oos'],  '+.3f')} | "
                    f"{_fmt(r['eqw_oos'],     '+.3f')} | "
                    f"**{_fmt(r['blend_oos'], '+.3f')}** | "
                    f"{_fmt(r['d_oos_vs_static'], '+.3f')} | "
                    f"{_fmt(r['d_oos_vs_eqw'],    '+.3f')} |"
                )

    lines.append("\n## Files\n")
    lines.append("- per-cell blend α       : `data/blend_book_v6/{variant}/{cell}/blend_alpha.parquet`")
    lines.append("- per-cell blend weights : `data/blend_book_v6/{variant}/{cell}/blend_weights.parquet`")
    lines.append("- per-cell net returns   : `data/blend_book_v6/{variant}/{cell}/blend_net_ret.csv`")
    lines.append("- per-variant grid       : `data/blend_book_v6/{variant}/blend_grid.csv`")

    reports_dir.mkdir(parents=True, exist_ok=True)
    p = reports_dir / "blend_book_v6_report.md"
    p.write_text("\n".join(lines))
    return str(p)


# ---------------------------------------------------------------------- #
# Driver
# ---------------------------------------------------------------------- #
def run(data_dir: Path | None = None,
        reports_dir: Path | None = None,
        cost_per_trade: float = E.DEFAULT_COST_PER_TRADE) -> None:
    data_dir    = Path(data_dir)    if data_dir    else C.DATA_DIR
    reports_dir = Path(reports_dir) if reports_dir else C.REPORTS_DIR

    data = _load_common_inputs(data_dir)

    static_grid = _load_static_grid(data_dir)

    print("=" * 78)
    print(f"Blend book v6 — cost = {cost_per_trade*1e4:.0f} bp/side")
    print("=" * 78)

    blend_grids: dict[str, pd.DataFrame] = {}
    comparison: dict[str, pd.DataFrame] = {}
    skipped_cells: set[str] = set()

    for variant in EQW_VARIANTS:
        print(f"\n[{variant}]")
        eqw_alpha = _load_eqw_alpha(data_dir, variant, data["codes"])
        rows: list[dict] = []
        for mode, q in BOOK_GRID:
            cell = _cell_tag(mode, q)
            static_alpha = _load_static_alpha(data_dir, mode, q, data["codes"])
            if static_alpha is None:
                print(f"  {cell}: SKIP (no static leg)")
                skipped_cells.add(cell)
                continue
            row = run_cell(mode, q, variant, data, static_alpha, eqw_alpha,
                           OUT_ROOT, cost_per_trade=cost_per_trade)
            rows.append(row)
            print(f"  {cell}: IS={row['is_sharpe']:+.3f}  "
                  f"OOS={row['oos_sharpe']:+.3f}  "
                  f"full={row['full_sharpe']:+.3f}  "
                  f"turn={row['avg_turnover']:.3f}")

        if not rows:
            continue
        grid = pd.DataFrame(rows)
        (OUT_ROOT / variant).mkdir(parents=True, exist_ok=True)
        grid.to_csv(OUT_ROOT / variant / "blend_grid.csv", index=False)
        blend_grids[variant] = grid

        eqw_grid = _load_eqw_grid(data_dir, variant)
        comparison[variant] = build_comparison(grid, static_grid, eqw_grid)

    report_p = _write_report(blend_grids, comparison, sorted(skipped_cells),
                             reports_dir, cost_per_trade)
    print(f"\nwrote {report_p}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir",    type=Path, default=None)
    ap.add_argument("--reports-dir", type=Path, default=None)
    args = ap.parse_args()
    run(args.data_dir, args.reports_dir)


if __name__ == "__main__":
    main()
