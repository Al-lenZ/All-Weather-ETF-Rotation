"""
v6/scripts/block_xs_census_v6.py
================================
Phase 13.1 — N_{t,b} census on the v6 pool.

For every W-FRI bar × block, count admitted members from
``data/universe_v6/membership.parquet`` × ``catalogue_tagged.csv``.
Sets the ceiling on what a within-block IC screen can measure per block:
Spearman IC needs at least a handful of names to have any resolution,
and the ragged z-stat under Phase 5.2's convention needs enough bars ×
enough per-bar N to have a meaningful denominator.

The census does NOT itself filter what Phase 13.2 screens — a block
with a thin cross-section still gets its factors run; the report just
flags it so a passing zstat there is read as "directional only" instead
of "measured cleanly." Interpretation is downstream.

IS-only (bars ≤ ``C.IN_SAMPLE_END``). Feedback-oos-discipline.

Outputs
-------
    data/block_xs_census_v6/census.parquet         # W-FRI × block, int
    data/block_xs_census_v6/summary.csv            # per-block IS stats
    reports/block_xs_census_v6.md

Run
---
    python v6/scripts/block_xs_census_v6.py
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


OUT_DIR       = C.DATA_DIR / "block_xs_census_v6"
MIN_VALID_ROW = 5   # matches block_neutral_ic_v6's per-bar IC floor


# ---------------------------------------------------------------------- #
# Inputs
# ---------------------------------------------------------------------- #
def _load_membership_and_tags(data_dir: Path
                              ) -> tuple[pd.DataFrame, pd.Series]:
    mem = pd.read_parquet(data_dir / "universe_v6" / "membership.parquet")
    mem = mem.astype(bool)
    cat = pd.read_csv(data_dir / "universe_v6" / "catalogue_tagged.csv")
    block_tag = cat.set_index("code")["current_block"]
    return mem, block_tag


# ---------------------------------------------------------------------- #
# Census
# ---------------------------------------------------------------------- #
def build_census(membership: pd.DataFrame,
                 block_tag: pd.Series) -> pd.DataFrame:
    """Bar × block count of admitted members. UNTAGGED codes are kept
    as their own bucket so the totals reconcile against N_t.
    """
    tag = block_tag.reindex(membership.columns).fillna("UNTAGGED")
    # Stack membership True positions and group by block
    long = (membership.stack()
                     .rename("in")
                     .reset_index()
                     .rename(columns={"level_0": "date",
                                      "level_1": "code"}))
    long = long[long["in"]]
    long["block"] = long["code"].map(tag)
    census = (long.groupby(["date", "block"])
                  .size()
                  .unstack("block")
                  .fillna(0)
                  .astype(int)
                  .sort_index())
    census = census.reindex(membership.index).fillna(0).astype(int)
    return census


def is_summary(census: pd.DataFrame) -> pd.DataFrame:
    is_c = census.loc[census.index <= C.IN_SAMPLE_END]
    rows = []
    for b in is_c.columns:
        s = is_c[b]
        rows.append({
            "block":   b,
            "mean_N":  float(s.mean()),
            "median":  float(s.median()),
            "min":     int(s.min()),
            "p10":     float(s.quantile(0.10)),
            "p90":     float(s.quantile(0.90)),
            "max":     int(s.max()),
            "bars_ge_MIN": int((s >= MIN_VALID_ROW).sum()),
            "bars_total":  int(len(s)),
            "flag_thin":   bool(s.mean() < MIN_VALID_ROW),
        })
    out = pd.DataFrame(rows).sort_values("mean_N", ascending=False)
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------- #
# Report
# ---------------------------------------------------------------------- #
def _fmt(x, digits=1):
    return f"{x:.{digits}f}" if pd.notna(x) else "—"


def write_report(census: pd.DataFrame,
                 summary: pd.DataFrame,
                 report_path: Path) -> None:
    is_c = census.loc[census.index <= C.IN_SAMPLE_END]
    n_bars = int(len(is_c))
    tot_mean = float(is_c.sum(axis=1).mean())

    lines: list[str] = []
    lines.append("# v6 static — block cross-section census "
                 "(Phase 13.1, IS window)\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    lines.append(
        "Bar × block count of admitted members over the IS window "
        f"(bars ≤ {C.IN_SAMPLE_END.date()}, n_bars = {n_bars}). "
        f"Total-pool mean N_t = {tot_mean:.1f}. UNTAGGED codes kept as "
        "their own bucket so per-block counts sum back to N_t.\n\n"
        "Reads for the Phase 13.2 within-block IC screen: a block "
        f"whose mean N_b < MIN_VALID_ROW = {MIN_VALID_ROW} won't have "
        "a well-resolved per-bar IC — its z-stat is directional only. "
        "Such blocks are **not** dropped from the screen (per user); "
        "they're just flagged so the report reads them as qualitative.\n\n"
    )

    lines.append("## 1. IS block census (sorted by mean N_b)\n")
    lines.append("| block | mean N | median | min | p10 | p90 | max | "
                 "bars ≥ 5 / total | flag |")
    lines.append("|:---|---:|---:|---:|---:|---:|---:|---:|:---:|")
    for _, r in summary.iterrows():
        flag = "**thin**" if r["flag_thin"] else ""
        lines.append(
            f"| {r['block']} | {_fmt(r['mean_N'])} | {_fmt(r['median'])} | "
            f"{int(r['min'])} | {_fmt(r['p10'])} | {_fmt(r['p90'])} | "
            f"{int(r['max'])} | {int(r['bars_ge_MIN'])} / "
            f"{int(r['bars_total'])} | {flag} |"
        )
    lines.append("")

    lines.append("## 2. Per-year mean N_b by block\n")
    df = is_c.copy()
    df.index = pd.to_datetime(df.index)
    per_year = df.groupby(df.index.year).mean().round(1)
    cols = list(summary["block"])
    per_year = per_year[cols]
    lines.append("| year | " + " | ".join(cols) + " |")
    lines.append("|:---:|" + "|".join(["---:"] * len(cols)) + "|")
    for y, row in per_year.iterrows():
        cells = [f"{v:.1f}" for v in row.values]
        lines.append(f"| {int(y)} | " + " | ".join(cells) + " |")
    lines.append("")

    thin = summary.loc[summary["flag_thin"], "block"].tolist()
    fat  = summary.loc[~summary["flag_thin"], "block"].tolist()
    lines.append("## 3. Read for the 13.2 screen\n")
    lines.append(
        f"- **Well-resolved blocks (mean N ≥ {MIN_VALID_ROW}):** "
        + (", ".join(f"`{b}`" for b in fat) or "*none*")
        + ". Per-block zstat here is comparable to the pool-level zstat "
        "from `pv_sweep_xs_v6`.\n"
        f"- **Thin blocks (mean N < {MIN_VALID_ROW}):** "
        + (", ".join(f"`{b}`" for b in thin) or "*none*")
        + ". Screen still runs; treat zstat as directional. Consider "
        "quotient thresholds (top-1 / top-2 hit rate) as the actionable "
        "read here.\n\n"
        "The mini-bond diagnostic (13.3) is most relevant on the wider "
        "equity blocks where a naive 1/σ can still collapse to a fixed "
        "3-4 name portfolio — flagged separately in that report.\n"
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {report_path}")


# ---------------------------------------------------------------------- #
# Main
# ---------------------------------------------------------------------- #
def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mem, block_tag = _load_membership_and_tags(C.DATA_DIR)
    print(f"loaded membership: {mem.shape[0]} bars × {mem.shape[1]} codes  "
          f"({int(mem.any(axis=0).sum())} ever admitted)")
    print(f"block_tag: {block_tag.notna().sum()} tagged, "
          f"{block_tag.isna().sum()} untagged")

    census = build_census(mem, block_tag)
    census.to_parquet(OUT_DIR / "census.parquet")
    print(f"wrote {OUT_DIR / 'census.parquet'}")

    summary = is_summary(census)
    summary.to_csv(OUT_DIR / "summary.csv", index=False)
    print(f"wrote {OUT_DIR / 'summary.csv'}")

    print("\nIS per-block summary:")
    with pd.option_context("display.max_rows", None,
                           "display.width", 140):
        print(summary.to_string(index=False))

    write_report(census, summary, C.REPORTS_DIR / "block_xs_census_v6.md")


if __name__ == "__main__":
    main()
