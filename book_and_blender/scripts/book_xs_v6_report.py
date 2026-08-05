"""
v6/scripts/book_xs_v6_report.py
================================
Phase 9.1 — write the static-baseline report from the grid outputs.

Reads:
  data/v6_static/grid_summary.csv
  data/v6_static/{cell}/dedup.csv         # kept-set per cell
  data/v6_static/{cell}/ensemble_sharpe.csv

Writes:
  reports/book_xs_v6_report.md

The report deliberately shows OOS Sharpe for all six cells — this is a
2×3 coarse grid, not a bake-off with an OOS-held-out best-of-N winner.
Interpretation of which q to freeze belongs to the user in a downstream
Phase-9 step; this report just puts the numbers on paper.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

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
from xs_screen_v6 import (MODES, QS, MIN_IN_SHARPE, MIN_OUT_SHARPE, MIN_DECAY,
                          DEDUP_THRESHOLD, OUT_ROOT, _cell_dir, _cell_tag)


REPORT_PATH = C.REPORTS_DIR / "book_xs_v6_report.md"


def _fmt(x, w=6, sign=True, prec=3):
    if pd.isna(x):
        return f"{'n/a':>{w}s}"
    fmt = f"{{:{'+' if sign else ''}.{prec}f}}"
    return f"{fmt.format(x):>{w}s}"


def _sharpe_row(r: pd.Series) -> str:
    return (
        f"| {r['mode']:>4s} | {r['q']:.2f} | "
        f"{int(r['screened_n']):>4d} | {int(r['relaxed_n']):>3d} | "
        f"{int(r['kept_n']):>3d} | "
        f"{r['is_sharpe']:+.3f} | {r['oos_sharpe']:+.3f} | "
        f"{r['decay_ratio']:+.2f} | "
        f"{r['avg_turnover']:.3f} | "
        f"{r['mean_K']:>5.1f} | {r['mean_N']:>5.1f} |"
    )


def _pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def _returns_row(r: pd.Series) -> str:
    return (
        f"| {r['mode']:>4s} | {r['q']:.2f} | "
        f"{_pct(r['is_cumret']):>9s} | {_pct(r['is_cagr']):>8s} | "
        f"{_pct(r['is_max_dd']):>8s} | "
        f"{_pct(r['oos_cumret']):>9s} | {_pct(r['oos_cagr']):>8s} | "
        f"{_pct(r['oos_max_dd']):>8s} | "
        f"{_pct(r['full_cumret']):>9s} | {_pct(r['full_max_dd']):>8s} |"
    )


def _kept_table(mode: str, q: float, out_root: Path) -> str:
    """Kept-set table for one cell, sorted by full-Sharpe desc."""
    p = _cell_dir(mode, q, out_root) / "dedup.csv"
    if not p.exists() or p.stat().st_size == 0:
        return "_(no survivors)_"
    df = pd.read_csv(p)
    if df.empty:
        return "_(no survivors)_"
    df = df.sort_values("sharpe", ascending=False)
    lines = ["| factor | polarity | IS Sharpe | OOS Sharpe | decay | turnover |",
             "|---|:---:|---:|---:|---:|---:|"]
    for _, r in df.iterrows():
        lines.append(
            f"| {r['factor']} | {r['polarity']} | "
            f"{r['in_sharpe']:+.3f} | {r['out_sharpe']:+.3f} | "
            f"{r['decay_ratio']:+.2f} | {r['avg_turnover']:.3f} |"
        )
    return "\n".join(lines)


def _all_factors_headline(mode: str, q: float, out_root: Path,
                          n: int = 10) -> str:
    """Top-n by full Sharpe across all screened factors (pre-filter)."""
    p = _cell_dir(mode, q, out_root) / "all_factors.csv"
    if not p.exists():
        return ""
    df = pd.read_csv(p).sort_values("sharpe", ascending=False).head(n)
    lines = ["| factor | IS Sharpe | OOS Sharpe | full Sharpe | decay | turnover |",
             "|---|---:|---:|---:|---:|---:|"]
    for _, r in df.iterrows():
        lines.append(
            f"| {r['factor']} | {r['in_sharpe']:+.3f} | "
            f"{r['out_sharpe']:+.3f} | {r['sharpe']:+.3f} | "
            f"{r['decay_ratio']:+.2f} | {r['avg_turnover']:.3f} |"
        )
    return "\n".join(lines)


def _write(out_root: Path, report_path: Path) -> None:
    grid = pd.read_csv(out_root / "grid_summary.csv")

    lines: list[str] = []
    lines.append("# v6 static baseline — coarse (mode, q) grid\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")

    # --- setup block ---------------------------------------------------
    lines.append("\n## Setup\n")
    lines.append("**Universe:** v6, ragged W-FRI membership panel  "
                 f"(mean_N = {grid['mean_N'].max():.1f} in-panel, "
                 f"{int(grid['is_bars'].iloc[0])} IS bars + "
                 f"{int(grid['oos_bars'].iloc[0])} OOS bars).  ")
    lines.append(f"**IS window:** ≤ {C.IN_SAMPLE_END.date()} · "
                 f"**OOS window:** {C.OOS_START.date()} → {C.OOS_END.date()} · "
                 f"**Hold-out (sealed):** > {C.OOS_END.date()}  ")
    lines.append("**Engine:** weekly W-FRI rebal, vol-scaled inside "
                 "selection (w ∝ 1/σ_causal_26w), 10 bp/side turnover cost. "
                 "See `xs_engine_v6.py`.  ")
    lines.append(f"**Grid:** modes {list(MODES)} × q {list(QS)}  ")
    lines.append("**Screening thresholds** (reused from v4/v5): "
                 f"IS Sharpe ≥ {MIN_IN_SHARPE}, OOS Sharpe ≥ {MIN_OUT_SHARPE}, "
                 f"decay ≥ {MIN_DECAY}, dedup |ρ| > {DEDUP_THRESHOLD} on the "
                 "flattened stage-2 CS-Gaussian-rank panels.  ")
    lines.append("**Ensemble α** = mean of per-bar row-z-scored raw α of "
                 "kept factors (polarity-oriented). Matches the v4pool "
                 "convention (`build_combined_v5.ensemble_alpha`); see "
                 "`diagnose_ensemble_v6.py` for why the earlier CS-rank "
                 "combiner was replaced.  ")

    # --- headline Sharpe / risk-adjusted table -------------------------
    lines.append("\n## Grid results — Sharpe headline\n")
    lines.append("| mode | q | scr | rlx | kept | IS Sharpe | OOS Sharpe | "
                 "decay | avg turnover | mean_K | mean_N |")
    lines.append("|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in grid.iterrows():
        lines.append(_sharpe_row(r))

    # --- returns + drawdowns table -------------------------------------
    lines.append("\n## Grid results — cumulative return, CAGR, max drawdown\n")
    lines.append("Windows: **IS** ≤ "
                 f"{C.IN_SAMPLE_END.date()} · **OOS** "
                 f"{C.OOS_START.date()}→{C.OOS_END.date()} · **Full** "
                 "= IS ∪ OOS. Cumret is Convention-A additive "
                 "(Σ net_ret on constant notional). CAGR compounds the "
                 "same NAV path. Max DD is on the constant-notional NAV.\n")
    lines.append("| mode | q | IS cumret | IS CAGR | IS DD | "
                 "OOS cumret | OOS CAGR | OOS DD | full cumret | full DD |")
    lines.append("|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in grid.iterrows():
        lines.append(_returns_row(r))

    # --- Baseline selection deferred -----------------------------------
    lines.append("\n## Baseline selection\n")
    lines.append("**Deferred.** All three q values are retained so the "
                 "downstream model / combined-book sweeps can rerun the same "
                 "grid and compare like-for-like. Design §7's IS-Sharpe pick "
                 "rule is not applied here.\n")

    # --- per-cell kept sets --------------------------------------------
    lines.append("\n## Kept sets per cell (post-dedup)\n")
    for mode in MODES:
        for q in QS:
            lines.append(f"\n### {_cell_tag(mode, q)}\n")
            lines.append(_kept_table(mode, q, out_root))

    # --- diagnostic: top-10 raw per cell -------------------------------
    lines.append("\n## Diagnostic — top-10 by full Sharpe pre-filter\n")
    lines.append("Shows the strongest single-factor books at each cell "
                 "regardless of whether they cleared the (IS, OOS, decay) "
                 "gate. Useful for interpreting why some cells have empty "
                 "kept sets.\n")
    for mode in MODES:
        for q in QS:
            lines.append(f"\n### {_cell_tag(mode, q)}\n")
            hd = _all_factors_headline(mode, q, out_root)
            if hd:
                lines.append(hd)

    # --- files ---------------------------------------------------------
    lines.append("\n## Files\n")
    lines.append("- `data/v6_static/grid_summary.csv` — this table")
    lines.append("- `data/v6_static/{cell}/all_factors.csv` — every "
                 "(factor, polarity) row per cell")
    lines.append("- `data/v6_static/{cell}/relaxed.csv` — filter survivors")
    lines.append("- `data/v6_static/{cell}/dedup.csv` — kept set")
    lines.append("- `data/v6_static/{cell}/dropped.csv` — dedup dropouts")
    lines.append("- `data/v6_static/{cell}/ensemble_alpha.parquet` — the "
                 "T×N ensemble α panel")
    lines.append("- `data/v6_static/{cell}/ensemble_weights.parquet` — "
                 "book weights")
    lines.append("- `data/v6_static/{cell}/ensemble_net_ret.csv` — per-bar "
                 "net return")
    lines.append("- `data/v6_static/{cell}/ensemble_sharpe.csv` — one-row "
                 "summary")
    lines.append("- `data/v6_static/{cell}/ensemble_picks.csv` — per-bar "
                 "non-zero weights (long side + short side)")
    lines.append("")
    lines.append("**Raw data for downstream per-year / rolling-window "
                 "diagnostics.** Per-bar net returns of the ensemble book "
                 "live in `ensemble_net_ret.csv`; per-bar weights in "
                 "`ensemble_weights.parquet`. Any per-year Sharpe / max DD "
                 "/ CAGR breakdown can be reconstructed from those without "
                 "re-running the screen. Per-factor per-bar returns are not "
                 "persisted — rerun the screen (~70 s per cell) if you need "
                 "them.")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines))
    print(f"wrote {report_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", type=Path, default=OUT_ROOT)
    ap.add_argument("--report",   type=Path, default=REPORT_PATH)
    args = ap.parse_args()
    _write(args.out_root, args.report)


if __name__ == "__main__":
    main()
