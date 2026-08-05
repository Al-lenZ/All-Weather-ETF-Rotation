"""
v6/scripts/ridge_static_blend_v6.py
===================================
Phase 8.6 — v4pool production blend: ridge OOF score + Phase 9.1 static α,
rank-space equal-weight combination.

    blend[t, i] = 0.5 · cs_rank(static)[t, i] + 0.5 · cs_rank(ridge)[t, i]

Recipe is identical to `blend_book_v6.py` (design §7 / v4pool `book_xs.py`);
only the second-leg source changes. The reasoning — that ridge and static
are optimizing orthogonal signals so a rank-space blend should generalize
better than either alone — applies more strongly here than in the
eqw+static blend (the eqw leg is a coarser second leg by construction).

Legs
----
    static — Phase 9.1 per-cell ensemble α from
             `data/v6_static/{mode}_q{qq}/ensemble_alpha.parquet`.
    ridge  — Phase 8.3 OOF `s_hat` panel from
             `data/fit_ridge_xs_v6/{variant}/ridge_score.parquet`.
             Two variants: dedup_v6 (28-feature ridge), stability_v6 (5).

Ridge OOF bars < first test bar are NaN; the blend naturally uses only
the static leg where the ridge leg is missing (bounded by NaN-mean).
That's a warm-up window, not a data-leak concern.

Cost stays on (10 bp/side).

Outputs
-------
    data/ridge_static_blend_v6/{variant}/{cell}/blend_alpha.parquet
    data/ridge_static_blend_v6/{variant}/{cell}/blend_weights.parquet
    data/ridge_static_blend_v6/{variant}/{cell}/blend_net_ret.csv
    data/ridge_static_blend_v6/{variant}/blend_grid.csv
    reports/ridge_static_blend_v6_report.md
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
from blend_book_v6 import (
    BOOK_GRID,
    blend_alpha,
    _cell_tag,
    _has_finite,
    _load_common_inputs,
    _load_static_alpha,
    _load_static_grid,
    _load_eqw_grid,
)


VARIANTS = ("dedup_v6", "stability_v6")
OUT_ROOT = C.DATA_DIR / "ridge_static_blend_v6"


# ---------------------------------------------------------------------- #
# Ridge score loader
# ---------------------------------------------------------------------- #
def _load_ridge_score(data_dir: Path, variant: str,
                      codes: list[str]) -> pd.DataFrame:
    p = data_dir / "fit_ridge_xs_v6" / variant / "ridge_score.parquet"
    if not p.exists():
        raise SystemExit(f"missing {p} — run fit_ridge_xs_v6.py first")
    return pd.read_parquet(p).reindex(columns=codes)


def _load_ridge_grid(data_dir: Path, variant: str) -> pd.DataFrame:
    return pd.read_csv(data_dir / "fit_ridge_xs_v6" / variant / "book_grid.csv")


def _load_eqw_blend_grid(data_dir: Path, variant: str) -> pd.DataFrame | None:
    p = data_dir / "blend_book_v6" / variant / "blend_grid.csv"
    if not p.exists():
        return None
    return pd.read_csv(p)


# ---------------------------------------------------------------------- #
# Cell driver
# ---------------------------------------------------------------------- #
def run_cell(mode: str, q: float, variant: str,
             data: dict, static_alpha: pd.DataFrame,
             ridge_alpha: pd.DataFrame,
             out_root: Path,
             cost_per_trade: float = E.DEFAULT_COST_PER_TRADE) -> dict:
    cell = _cell_tag(mode, q)
    out_dir = out_root / variant / cell
    out_dir.mkdir(parents=True, exist_ok=True)

    blend = blend_alpha(static_alpha, ridge_alpha, data["membership"])
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
# Report
# ---------------------------------------------------------------------- #
def _fmt(v: float, spec: str) -> str:
    return "n/a" if not np.isfinite(v) else format(v, spec)


def _write_report(blend_grids: dict[str, pd.DataFrame],
                  skipped_cells: list[str],
                  data_dir: Path,
                  reports_dir: Path,
                  cost_per_trade: float) -> str:
    lines: list[str] = []
    lines.append("# Phase 8.6 — ridge + static blend (v6)\n")
    lines.append(
        "v4pool production book recipe: rank-space equal-weight blend of the "
        "Phase 9.1 per-cell static α and the Phase 8.3 ridge OOF s_hat.\n"
    )
    lines.append(
        "```\n"
        "blend[t, i] = 0.5 · cs_rank(static)[t, i] + 0.5 · cs_rank(ridge)[t, i]\n"
        "```\n"
    )
    lines.append(
        f"Ridge OOF s_hat is NaN before the first test fold (warm-up); the "
        "rank-space blend degrades to static-alone in that window. Membership "
        "mask applied before ranking. Blend α → `xs_engine_v6` at the same "
        f"(mode, q) with {cost_per_trade*1e4:.0f} bp/side cost.\n"
    )
    if skipped_cells:
        lines.append(
            f"\n**Skipped cells** ({len(skipped_cells)}): "
            f"{', '.join(skipped_cells)}. Phase 9.1 had no static leg here "
            "so blend is undefined (see `blend_book_v6_report.md`).\n"
        )

    static_grid = _load_static_grid(data_dir)

    for variant in VARIANTS:
        if variant not in blend_grids or blend_grids[variant].empty:
            lines.append(f"\n## {variant}\n_(no blend cells for this variant)_\n")
            continue

        eqw_grid       = _load_eqw_grid(data_dir, variant)
        ridge_grid     = _load_ridge_grid(data_dir, variant)
        eqw_blend_grid = _load_eqw_blend_grid(data_dir, variant)

        lines.append(f"\n## {variant}\n")

        # Ridge+static blend grid
        lines.append("### Ridge+static blend — grid (net of cost)\n")
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

        # 5-way comparison per cell (full + OOS)
        for label, col in [("Full Sharpe", "full_sharpe"),
                           ("OOS Sharpe",  "oos_sharpe")]:
            lines.append(f"\n### 5-way {label} — static / eqw / eqw+static "
                         f"blend / ridge / **ridge+static blend**\n")
            lines.append("| mode | q | static | eqw | eqw⊕static | ridge | "
                         "**ridge⊕static** | Δ vs static | Δ vs eqw⊕static |")
            lines.append("|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|")
            for _, br in blend_grids[variant].iterrows():
                m, q = br["mode"], br["q"]
                def _get(g):
                    if g is None:
                        return np.nan
                    sub = g[(g["mode"] == m) & (np.isclose(g["q"], q))]
                    return float(sub[col].iloc[0]) if len(sub) else np.nan
                s_v = _get(static_grid)
                e_v = _get(eqw_grid)
                b_v = _get(eqw_blend_grid)
                r_v = _get(ridge_grid)
                rs_v = float(br[col])
                d_static = rs_v - s_v if np.isfinite(s_v) else np.nan
                d_blend  = rs_v - b_v if np.isfinite(b_v) else np.nan
                lines.append(
                    f"| {m} | {q:.2f} | "
                    f"{_fmt(s_v, '+.3f')} | {_fmt(e_v, '+.3f')} | "
                    f"{_fmt(b_v, '+.3f')} | {_fmt(r_v, '+.3f')} | "
                    f"**{_fmt(rs_v, '+.3f')}** | "
                    f"{_fmt(d_static, '+.3f')} | {_fmt(d_blend, '+.3f')} |"
                )

    lines.append("\n## Files\n")
    lines.append("- per-cell blend α       : `data/ridge_static_blend_v6/{variant}/{cell}/blend_alpha.parquet`")
    lines.append("- per-cell blend weights : `data/ridge_static_blend_v6/{variant}/{cell}/blend_weights.parquet`")
    lines.append("- per-cell net returns   : `data/ridge_static_blend_v6/{variant}/{cell}/blend_net_ret.csv`")
    lines.append("- per-variant grid       : `data/ridge_static_blend_v6/{variant}/blend_grid.csv`")

    reports_dir.mkdir(parents=True, exist_ok=True)
    p = reports_dir / "ridge_static_blend_v6_report.md"
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

    print("=" * 78)
    print(f"Ridge + static blend v6 — cost = {cost_per_trade*1e4:.0f} bp/side")
    print("=" * 78)

    blend_grids: dict[str, pd.DataFrame] = {}
    skipped_cells: set[str] = set()
    for variant in VARIANTS:
        print(f"\n[{variant}]")
        ridge_alpha = _load_ridge_score(data_dir, variant, data["codes"])
        rows: list[dict] = []
        for mode, q in BOOK_GRID:
            cell = _cell_tag(mode, q)
            static_alpha = _load_static_alpha(data_dir, mode, q, data["codes"])
            if static_alpha is None:
                print(f"  {cell}: SKIP (no static leg)")
                skipped_cells.add(cell)
                continue
            row = run_cell(mode, q, variant, data, static_alpha, ridge_alpha,
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

    report_p = _write_report(blend_grids, sorted(skipped_cells),
                             data_dir, reports_dir, cost_per_trade)
    print(f"\nwrote {report_p}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir",    type=Path, default=None)
    ap.add_argument("--reports-dir", type=Path, default=None)
    args = ap.parse_args()
    run(args.data_dir, args.reports_dir)


if __name__ == "__main__":
    main()
