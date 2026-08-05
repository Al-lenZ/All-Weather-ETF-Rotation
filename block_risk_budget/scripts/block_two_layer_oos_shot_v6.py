"""
v6/scripts/block_two_layer_oos_shot_v6.py
=========================================
OOS shot on the Phase 12 × 13 two-layer book — 2026-07-22.

**User-authorized OOS opening (2026-07-22).** Compares two two-layer
variants (both α on broad_cn + sector_cn) side by side against the
Phase 12 layer-1 canonical and the T2 bond_invvol passive book across
IS, OOS, and full windows.

Books
-----
1. **two_layer_q20_e30**  — plateau pick from `block_two_layer_v6`
                            (q=0.20, ε=0.30 hysteresis)
2. **two_layer_q10_e30**  — best-raw-IS cell (q=0.10, ε=0.30)
3. **layer1_invvol_lw_erc** — Phase 12 layer-1 canonical: invvol
                              intra-block × LW-target-D log-barrier ERC
                              solver, trend gate OFF
4. **T2_bond_invvol**     — bond blocks (rates + credit) held with
                            inv-vol, no α (bond_attribution_v6)

Additionally reports the **two-layer baseline** (α off, layer-1 hold-all
under the two-layer module's sub-block composition) so the α layer's
OOS contribution is directly readable as Δ.

All books already produced full-window net-return series in prior runs;
this script just loads them, aligns to the shared W-FRI grid, and
computes IS + OOS + full metrics per book.

Windows (from `_common_v6`):
    IS       : ≤ 2023-12-31
    OOS      : 2024-01-01 → 2025-07-31   (this is what we open here)
    hold-out : > 2025-07-31              (SEALED — do not touch)

Outputs
-------
    reports/block_two_layer_oos_shot_v6_report.md
    data/block_two_layer_oos_shot_v6/summary.csv
    data/block_two_layer_oos_shot_v6/per_year.csv
    data/block_two_layer_oos_shot_v6/correlations_{is,oos}.csv

Run
---
    python v6/scripts/block_two_layer_oos_shot_v6.py
"""
from __future__ import annotations

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


DATA_ROOT   = C.DATA_DIR
REPORTS_DIR = C.REPORTS_DIR
OUT_ROOT    = DATA_ROOT / "block_two_layer_oos_shot_v6"

# Book roster.  Each entry: (label, csv path relative to DATA_ROOT).
# Every csv is a two-column (date, net_ret) frame written by earlier runs.
BOOK_ROSTER: list[tuple[str, Path]] = [
    ("two_layer_q20_e30",
     Path("block_two_layer_v6") / "q20_eps030" / "net_ret.csv"),
    ("two_layer_q10_e30",
     Path("block_two_layer_v6") / "q10_eps030" / "net_ret.csv"),
    ("layer1_invvol_lw_erc",
     Path("block_risk_budget_v6_no_trend") / "invvol_lw_erc" / "net_ret.csv"),
    ("T2_bond_invvol",
     Path("bond_attribution_v6") / "T2_bond_invvol" / "net_ret.csv"),
    # baseline for Δ attribution (α off, same sub-block composition as the
    # two-layer variants)
    ("two_layer_baseline",
     Path("block_two_layer_v6") / "baseline" / "net_ret.csv"),
]

# Book against which the two-layer variants' α contribution is measured
# (matches the layer-2 report's baseline definition)
DELTA_BASELINE = "two_layer_baseline"


# ---------------------------------------------------------------------- #
# Metrics
# ---------------------------------------------------------------------- #
def _load_net_ret(path: Path) -> pd.Series:
    df = pd.read_csv(path, parse_dates=[0], index_col=0)
    s = df.iloc[:, 0].sort_index()
    s.name = "net_ret"
    return s


def _window_metrics(net: pd.Series, label: str) -> dict:
    n = int(len(net))
    if n < 2:
        return {"window": label, "n_bars": n,
                "sharpe": np.nan, "cagr": np.nan, "max_dd": np.nan,
                "ann_vol": np.nan, "cumret": np.nan}
    ann_vol = float(net.std(ddof=1)) * np.sqrt(C.WEEKS_PER_YEAR)
    ann_ret = float(net.mean()) * C.WEEKS_PER_YEAR
    sharpe  = (ann_ret / ann_vol) if ann_vol > 0 else np.nan
    cumret  = float(net.sum())
    n_yrs   = max(n / C.WEEKS_PER_YEAR, 1e-3)
    cagr    = max(1.0 + cumret, 1e-9) ** (1.0 / n_yrs) - 1.0
    nav     = 1.0 + net.cumsum()
    max_dd  = float(((nav - nav.cummax()) / nav.cummax()).min())
    return {"window": label, "n_bars": n,
            "sharpe": sharpe, "cagr": cagr, "max_dd": max_dd,
            "ann_vol": ann_vol, "cumret": cumret}


def _first_live_bar(s: pd.Series) -> pd.Timestamp:
    """First bar where |net_ret| > 0 — the point where the book stops
    being in warmup. For all books here the warmup is one of:

        - 26 W (σ_causal_26w) — bond_attribution T2/T3
        - 52 W (cov window)   — block_risk_budget layer-1
        - 52 W (cov + α ensemble expanding-z warmup) — two-layer

    Using the actual per-book zero-tail is more robust than hard-coding a
    bar count; different books hit their first live bar on different
    dates.
    """
    nz = (s.abs() > 0.0)
    if not bool(nz.any()):
        return s.index[0]
    return s.index[int(nz.values.argmax())]


def _common_start(books: dict[str, pd.Series]) -> pd.Timestamp:
    """Latest first-live bar across all books — the earliest date every
    book has actually started trading. Using max keeps IS metrics and the
    per-year table apples-to-apples across books with different warmup
    lengths (T2's 26 W σ warmup vs the two-layer's 52 W cov warmup)."""
    return max(_first_live_bar(s) for s in books.values())


def _split_windows(s: pd.Series,
                   start: pd.Timestamp) -> dict[str, pd.Series]:
    idx = s.index
    return {
        "IS":   s[(idx >= start) & (idx <= C.IN_SAMPLE_END)],
        "OOS":  s[(idx >= C.OOS_START) & (idx <= C.OOS_END)],
        "full": s[((idx >= start) & (idx <= C.IN_SAMPLE_END)) |
                  ((idx >= C.OOS_START) & (idx <= C.OOS_END))],
    }


def _book_row(name: str, s: pd.Series, start: pd.Timestamp) -> list[dict]:
    parts = _split_windows(s, start)
    return [dict(book=name, **_window_metrics(v, k)) for k, v in parts.items()]


# ---------------------------------------------------------------------- #
# Per-year
# ---------------------------------------------------------------------- #
def _per_year(name: str, s: pd.Series) -> pd.DataFrame:
    if s.empty:
        return pd.DataFrame(columns=["book", "year", "ret", "n_bars"])
    df = s.to_frame("r"); df["year"] = df.index.year
    rows = []
    for y, g in df.groupby("year"):
        rows.append({"book": name, "year": int(y),
                     "ret": float(g["r"].sum()), "n_bars": int(len(g))})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------- #
# Report
# ---------------------------------------------------------------------- #
def _fmt(x, d=3):   return f"{x:+.{d}f}" if pd.notna(x) else "   —"
def _fmt_pct(x, d=2): return f"{x*100:+.{d}f}%" if pd.notna(x) else "     —"


def _fmt_delta(x, d=3, ispct=False):
    if pd.isna(x): return "   —"
    if ispct: return f"{x*100:+.{d}f}%"
    return f"{x:+.{d}f}"


def write_report(books: dict[str, pd.Series],
                 summary_long: pd.DataFrame,
                 per_year_long: pd.DataFrame,
                 corr_is: pd.DataFrame,
                 corr_oos: pd.DataFrame,
                 common_start: pd.Timestamp,
                 per_book_start: dict[str, pd.Timestamp],
                 report_path: Path) -> None:
    lines: list[str] = []
    lines.append("# Two-layer OOS shot — 2026-07-22\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    lines.append(
        "**User-authorized OOS opening** on the Phase 12 × 13 two-layer "
        "book (see `block_two_layer_v6_report.md` for the IS-only sweep). "
        "Compares two two-layer variants (q=0.20 ε=0.30 plateau pick + "
        "q=0.10 ε=0.30 best-raw-IS cell) against the Phase 12 layer-1 "
        "canonical (invvol × lw_erc, no trend gate) and the T2 "
        "bond_invvol passive book. Two-layer baseline (α off) included "
        "so the α layer's OOS contribution is directly readable as Δ.\n\n"
        f"Windows: **IS = [{common_start.date()}, {C.IN_SAMPLE_END.date()}]** "
        f"(warmup stripped), OOS {C.OOS_START.date()} → {C.OOS_END.date()} "
        f"(hold-out > {C.OOS_END.date()} sealed). "
        f"Cost 10 bp/side. Weekly W-FRI grid.\n\n"
        f"**Warmup handling** (user 2026-07-22): each book's first-live bar "
        f"(first non-zero net-return) marks the end of its own warmup. The "
        f"common start = **{common_start.date()}** is the latest of those "
        f"across all 5 books, so all IS metrics + per-year table + "
        f"correlations are computed on the same window and are strictly "
        f"apples-to-apples. Per-book first-live bars: "
        + "; ".join(f"`{n}` {d.date()}" for n, d in per_book_start.items())
        + ". Warmup bars are excluded from Sharpe / CAGR / DD "
          "denominators, and the per-year table no longer shows the "
          "2018 (all-zero) row.\n\n"
    )

    # --- §1 headline three-window table -----------------------------------
    lines.append("## 1. Headline: IS / OOS / full per book\n")
    pivot_sh = summary_long.pivot(index="book", columns="window", values="sharpe")
    pivot_cg = summary_long.pivot(index="book", columns="window", values="cagr")
    pivot_dd = summary_long.pivot(index="book", columns="window", values="max_dd")
    pivot_v  = summary_long.pivot(index="book", columns="window", values="ann_vol")
    pivot_n  = summary_long.pivot(index="book", columns="window", values="n_bars")
    order = [n for n, _ in BOOK_ROSTER]
    lines.append("| book | IS Sharpe | OOS Sharpe | full Sharpe | decay | "
                 "IS CAGR | OOS CAGR | full CAGR | IS DD | OOS DD | "
                 "IS ann vol | OOS ann vol | OOS bars |")
    lines.append("|:---|" + "|".join(["---:"] * 12) + "|")
    for name in order:
        if name not in pivot_sh.index:
            continue
        is_sh = float(pivot_sh.loc[name, "IS"])
        oos_sh = float(pivot_sh.loc[name, "OOS"])
        full_sh = float(pivot_sh.loc[name, "full"])
        decay = (oos_sh / is_sh) if abs(is_sh) > 1e-12 else np.nan
        lines.append(
            f"| {name} | {_fmt(is_sh)} | {_fmt(oos_sh)} | {_fmt(full_sh)} | "
            f"{_fmt(decay)} | "
            f"{_fmt_pct(pivot_cg.loc[name, 'IS'])} | "
            f"{_fmt_pct(pivot_cg.loc[name, 'OOS'])} | "
            f"{_fmt_pct(pivot_cg.loc[name, 'full'])} | "
            f"{_fmt_pct(pivot_dd.loc[name, 'IS'])} | "
            f"{_fmt_pct(pivot_dd.loc[name, 'OOS'])} | "
            f"{_fmt_pct(pivot_v.loc[name, 'IS'])} | "
            f"{_fmt_pct(pivot_v.loc[name, 'OOS'])} | "
            f"{int(pivot_n.loc[name, 'OOS'])} |"
        )
    lines.append("")

    # --- §2 α contribution vs baseline ------------------------------------
    lines.append(f"## 2. α contribution: Δ vs `{DELTA_BASELINE}` (two-layer, α off)\n")
    if DELTA_BASELINE in pivot_sh.index:
        base_sh = pivot_sh.loc[DELTA_BASELINE]
        base_cg = pivot_cg.loc[DELTA_BASELINE]
        base_dd = pivot_dd.loc[DELTA_BASELINE]
        lines.append("| book | Δ Sharpe IS | Δ Sharpe OOS | Δ CAGR IS | Δ CAGR OOS | Δ DD OOS |")
        lines.append("|:---|---:|---:|---:|---:|---:|")
        for name in order:
            if name == DELTA_BASELINE or name not in pivot_sh.index:
                continue
            d_sh_is  = float(pivot_sh.loc[name, "IS"])  - float(base_sh["IS"])
            d_sh_oos = float(pivot_sh.loc[name, "OOS"]) - float(base_sh["OOS"])
            d_cg_is  = float(pivot_cg.loc[name, "IS"])  - float(base_cg["IS"])
            d_cg_oos = float(pivot_cg.loc[name, "OOS"]) - float(base_cg["OOS"])
            d_dd_oos = float(pivot_dd.loc[name, "OOS"]) - float(base_dd["OOS"])
            lines.append(
                f"| {name} | {_fmt(d_sh_is)} | {_fmt(d_sh_oos)} | "
                f"{d_cg_is*100:+.2f} pp | {d_cg_oos*100:+.2f} pp | "
                f"{d_dd_oos*100:+.2f} pp |"
            )
    lines.append("")

    # --- §3 per-year -------------------------------------------------------
    lines.append("## 3. Per-calendar-year net return (sum of weekly)\n")
    pivot_y = per_year_long.pivot(index="year", columns="book", values="ret")
    cols = [n for n in order if n in pivot_y.columns]
    lines.append("| year | " + " | ".join(cols) + " |")
    lines.append("|:---:|" + "|".join(["---:"] * len(cols)) + "|")
    for y in sorted(pivot_y.index):
        row = [f"| {int(y)}"]
        for c in cols:
            v = pivot_y.loc[y, c]
            row.append(_fmt_pct(v) if pd.notna(v) else "     —")
        lines.append(" | ".join(row) + " |")
    lines.append("")
    lines.append("Note: 2024–2025 rows are OOS bars.\n")

    # --- §4 correlations ---------------------------------------------------
    def _emit_corr(title: str, corr: pd.DataFrame) -> None:
        lines.append(f"### {title}\n")
        cols = [c for c in order if c in corr.columns]
        lines.append("| | " + " | ".join(cols) + " |")
        lines.append("|:---|" + "|".join(["---:"] * len(cols)) + "|")
        for i in cols:
            row = [f"| {i}"]
            for c in cols:
                row.append(f" {corr.loc[i, c]:+.3f} ")
            lines.append(" | ".join(row) + " |")
        lines.append("")

    lines.append("## 4. Weekly-return correlation\n")
    _emit_corr("IS", corr_is)
    _emit_corr("OOS", corr_oos)

    # --- §5 read ----------------------------------------------------------
    lines.append("## 5. Read\n")
    if DELTA_BASELINE in pivot_sh.index:
        b = float(pivot_sh.loc[DELTA_BASELINE, "OOS"])
        l1c = float(pivot_sh.loc["layer1_invvol_lw_erc", "OOS"]) \
                if "layer1_invvol_lw_erc" in pivot_sh.index else np.nan
        t2  = float(pivot_sh.loc["T2_bond_invvol", "OOS"]) \
                if "T2_bond_invvol" in pivot_sh.index else np.nan
        q20 = float(pivot_sh.loc["two_layer_q20_e30", "OOS"]) \
                if "two_layer_q20_e30" in pivot_sh.index else np.nan
        q10 = float(pivot_sh.loc["two_layer_q10_e30", "OOS"]) \
                if "two_layer_q10_e30" in pivot_sh.index else np.nan
        lines.append(
            f"- OOS Sharpe: two_layer q=0.20 ε=0.30 = **{q20:+.3f}**, "
            f"two_layer q=0.10 ε=0.30 = **{q10:+.3f}**, "
            f"layer-1 canonical = {l1c:+.3f}, "
            f"T2 = {t2:+.3f}, baseline (α off) = {b:+.3f}.\n"
            f"- α layer OOS Δ = q20: {q20 - b:+.3f} Sharpe, "
            f"q10: {q10 - b:+.3f} Sharpe.\n"
        )
    lines.append(
        "\nDecay ratio (OOS Sharpe / IS Sharpe) close to 1.0 means the "
        "IS edge survived; ratio < 0.5 means significant decay. "
        "Compare across the 5 books to isolate which layer (α, budget, "
        "or bond passive) held up OOS.\n"
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {report_path}")


# ---------------------------------------------------------------------- #
# Main
# ---------------------------------------------------------------------- #
def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    books: dict[str, pd.Series] = {}
    for label, rel in BOOK_ROSTER:
        p = DATA_ROOT / rel
        if not p.exists():
            print(f"MISSING: {label} at {p}")
            continue
        books[label] = _load_net_ret(p)
        n = int(len(books[label]))
        print(f"loaded {label:<28s}  n={n:>4d}  "
              f"first={books[label].index.min().date()}  "
              f"last={books[label].index.max().date()}")

    # Compute per-book first-live date + common start (drops warmup bars
    # from all metrics + per-year table + correlations).
    per_book_start = {n: _first_live_bar(s) for n, s in books.items()}
    common_start = _common_start(books)
    print("\nfirst-live bar per book:")
    for n, d in per_book_start.items():
        print(f"  {n:<28s}  {d.date()}")
    print(f"\ncommon start (max first-live, used for IS metrics + per-year): "
          f"{common_start.date()}")

    # Build long-form summary + per-year tables using common_start
    summary_rows = []
    per_year_frames = []
    for name, s in books.items():
        summary_rows.extend(_book_row(name, s, common_start))
        for k, v in _split_windows(s, common_start).items():
            if k in ("IS", "OOS"):
                py = _per_year(name, v)
                if not py.empty:
                    per_year_frames.append(py)
    summary_long = pd.DataFrame(summary_rows)
    per_year_long = pd.concat(per_year_frames, ignore_index=True) \
                        if per_year_frames else pd.DataFrame()
    summary_long.to_csv(OUT_ROOT / "summary.csv", index=False)
    per_year_long.to_csv(OUT_ROOT / "per_year.csv", index=False)

    # Correlation matrices (aligned, warmup stripped)
    def _corr_window(mask_key: str) -> pd.DataFrame:
        parts = {n: _split_windows(s, common_start)[mask_key]
                 for n, s in books.items()}
        df = pd.DataFrame(parts)
        return df.corr()
    corr_is  = _corr_window("IS")
    corr_oos = _corr_window("OOS")
    corr_is.to_csv(OUT_ROOT / "correlations_is.csv")
    corr_oos.to_csv(OUT_ROOT / "correlations_oos.csv")

    # Pretty-print headline to stdout
    print("\nHEADLINE (Sharpe · CAGR · DD, per window):")
    print(f"{'book':<28s}  {'IS':>26s}  {'OOS':>26s}")
    print("-" * 90)
    for name, _ in BOOK_ROSTER:
        if name not in books: continue
        rows = _book_row(name, books[name], common_start)
        is_r  = next(r for r in rows if r["window"] == "IS")
        oos_r = next(r for r in rows if r["window"] == "OOS")
        def _fmt_win(r):
            return (f"Sh={r['sharpe']:+.3f} CAGR={r['cagr']*100:+.2f}% "
                    f"DD={r['max_dd']*100:+.2f}%")
        print(f"{name:<28s}  {_fmt_win(is_r):>26s}  {_fmt_win(oos_r):>26s}")

    write_report(books, summary_long, per_year_long, corr_is, corr_oos,
                 common_start, per_book_start,
                 REPORTS_DIR / "block_two_layer_oos_shot_v6_report.md")


if __name__ == "__main__":
    main()
