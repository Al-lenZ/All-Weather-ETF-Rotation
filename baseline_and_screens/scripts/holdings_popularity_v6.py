"""
v6/scripts/holdings_popularity_v6.py
====================================
Which names actually make it into the Phase 9.1 baseline books, and how
often? A quick-hit diagnostic complementing ``baseline_diagnostics_v6.py``
(which focused on flips and drawdowns rather than steady-state
composition).

For each of the four Phase 9.1 cells (long_q05, long_q10, long_q20,
ls_q20) we read the persisted ``ensemble_weights.parquet`` — restricted
to IS ∪ OOS bars, hold-out sealed — and compute per-name:

    presence_share  fraction of eligible bars in which the name held a
                    non-zero weight on this leg
    hit_bars        integer count of bars held
    mean_w          mean of |w| when held (0 when never held)
    weight_time     Σ_t |w_{i,t}| / T_eligible — "share of book-time"
                    (per-leg this integrates to 1 · presence_share_avg
                     × K̄, so we normalize by K̄ to a comparable 0..1)

For ``ls_q20`` we split each name into "long side" (w > 0) and "short
side" (w < 0) buckets so a name that only ever gets shorted doesn't
get confused with a name that flips sides.

Also aggregated by universe block (bond_rates, sector_cn, ...) to give
a "what kinds of ETFs does this cell like" picture.

Outputs
-------
    data/v6_static/holdings_popularity/{cell}_names.csv
        per-name (side, code, name_en, block, presence_share, hit_bars,
                  mean_w, weight_time_share)
    data/v6_static/holdings_popularity/{cell}_blocks.csv
        aggregated to block × side (n_names_ever_held, avg_weight_time,
        avg_presence_share)
    data/v6_static/holdings_popularity/coverage.csv
        one row per cell: total eligible bars, unique names ever held
        (per leg for LS), mean K, mean |held|
    reports/holdings_popularity_v6.md
        narrative + top-10 tables per cell

Run
---
    python v6/scripts/holdings_popularity_v6.py
"""
from __future__ import annotations

from pathlib import Path
import sys

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
from universe_v6 import load_persisted


CELLS: tuple[tuple[str, float], ...] = (
    ("long", 0.05),
    ("long", 0.10),
    ("long", 0.20),
    ("ls",   0.20),
)

OUT_ROOT = C.DATA_DIR / "v6_static" / "holdings_popularity"
TOP_N_NAMES_REPORT = 15


# ---------------------------------------------------------------------- #
# Loaders
# ---------------------------------------------------------------------- #
def _cell_tag(mode: str, q: float) -> str:
    return f"{mode}_q{int(round(q * 100)):02d}"


def _load_meta() -> tuple[dict, dict]:
    """Return (block_tag, name_en) for every persisted v6 code."""
    _mem, _codes, block_tag, _idx, name_en = load_persisted(
        C.DATA_DIR / "universe_v6"
    )
    return dict(block_tag), dict(name_en)


def _load_cell_weights(mode: str, q: float) -> pd.DataFrame:
    cell = _cell_tag(mode, q)
    W = pd.read_parquet(C.DATA_DIR / "v6_static" / cell /
                        "ensemble_weights.parquet")
    # Restrict to IS ∪ OOS; hold-out sealed
    idx = W.index
    keep = (idx <= C.IN_SAMPLE_END) | ((idx >= C.OOS_START) & (idx <= C.OOS_END))
    return W.loc[keep]


# ---------------------------------------------------------------------- #
# Per-name computation
# ---------------------------------------------------------------------- #
def _side_stats(W_side: pd.DataFrame, side_label: str,
                block_tag: dict, name_en: dict) -> pd.DataFrame:
    """One row per name that was ever held on this side.

    ``W_side`` must have magnitudes only (no sign) — for the short leg,
    caller passes |w| after masking on w < 0.
    """
    T = W_side.shape[0]
    if T == 0:
        return pd.DataFrame(columns=[
            "side", "code", "name_en", "block", "presence_share",
            "hit_bars", "mean_w_when_held", "weight_time_share"])

    held = (W_side > 0)
    hit_bars = held.sum(axis=0).astype(int)
    presence = hit_bars / T
    with np.errstate(invalid="ignore"):
        mean_when_held = W_side.where(held, np.nan).mean(axis=0)
    mean_when_held = mean_when_held.fillna(0.0)
    total_wt = W_side.sum(axis=0)        # Σ_t |w_{i,t}|
    weight_time_share = total_wt / total_wt.sum() if total_wt.sum() > 0 else total_wt

    df = pd.DataFrame({
        "code":               W_side.columns,
        "hit_bars":           hit_bars.values,
        "presence_share":     presence.values,
        "mean_w_when_held":   mean_when_held.values,
        "weight_time_share":  weight_time_share.values,
    })
    df = df[df["hit_bars"] > 0].copy()
    df.insert(0, "side", side_label)
    df.insert(2, "name_en", df["code"].map(name_en).fillna(""))
    df.insert(3, "block",   df["code"].map(block_tag).fillna(""))
    df = df.sort_values("weight_time_share", ascending=False).reset_index(drop=True)
    return df


def _cell_stats(mode: str, q: float,
                block_tag: dict, name_en: dict) -> dict:
    cell = _cell_tag(mode, q)
    W = _load_cell_weights(mode, q)
    T = W.shape[0]

    if mode == "long":
        names = _side_stats(W, "long", block_tag, name_en)
        held_now = (W != 0.0).sum(axis=1)
    else:  # ls
        W_long  = W.where(W > 0.0, 0.0)
        W_short = (-W).where(W < 0.0, 0.0)     # magnitudes on short side
        n_long  = _side_stats(W_long,  "long",  block_tag, name_en)
        n_short = _side_stats(W_short, "short", block_tag, name_en)
        names = pd.concat([n_long, n_short], ignore_index=True)
        held_now = (W != 0.0).sum(axis=1)

    coverage = {
        "cell":               cell,
        "mode":               mode,
        "q":                  q,
        "n_bars":             int(T),
        "unique_names_total": int(names["code"].nunique()),
        "mean_held_per_bar":  float(held_now.mean()),
        "max_held_per_bar":   int(held_now.max()),
    }
    if mode == "ls":
        coverage["unique_names_long"]  = int(names[names.side=="long"]["code"].nunique())
        coverage["unique_names_short"] = int(names[names.side=="short"]["code"].nunique())

    # Block-level aggregate (per-leg)
    def _block_agg(grp: pd.DataFrame) -> pd.Series:
        return pd.Series({
            "n_names_ever_held": grp["code"].nunique(),
            "sum_weight_time":   grp["weight_time_share"].sum(),
            "mean_presence":     grp["presence_share"].mean(),
        })

    blocks = (names.groupby(["side", "block"], as_index=False)
                    .apply(_block_agg, include_groups=False)
                    .reset_index(drop=True))
    if "block" not in blocks.columns:
        # groupby(as_index=False) + apply strips the group keys under
        # include_groups=False; recover them from the multi-index if
        # needed.
        blocks = (names.groupby(["side", "block"])
                        .apply(_block_agg, include_groups=False)
                        .reset_index())
    blocks = blocks.sort_values(["side", "sum_weight_time"], ascending=[True, False])

    return {"cell": cell, "names": names, "blocks": blocks, "coverage": coverage}


# ---------------------------------------------------------------------- #
# Report emission
# ---------------------------------------------------------------------- #
def _fmt_pct(x: float, digits: int = 1) -> str:
    return f"{x*100:.{digits}f}%"


def _fmt_wt(x: float) -> str:
    return f"{x*100:.2f}%"


def _write_report(results: list[dict], coverage_df: pd.DataFrame) -> str:
    lines: list[str] = []
    lines.append("# v6 static baseline — holdings popularity\n")
    lines.append(f"Generated: {pd.Timestamp.utcnow().date().isoformat()}\n")
    lines.append("")
    lines.append("Which names actually make it into each Phase 9.1 baseline "
                 "book, and how often. Restricted to IS ∪ OOS bars (hold-out "
                 "beyond 2025-07-31 sealed). Source: persisted "
                 "`ensemble_weights.parquet` per cell — same weight panels "
                 "used by `cost_attribution_v6.py` and "
                 "`baseline_diagnostics_v6.py`.")
    lines.append("")

    lines.append("## Metrics")
    lines.append("")
    lines.append("- **presence_share** — fraction of the cell's bars in "
                 "which the name held a non-zero weight (on the given leg).")
    lines.append("- **hit_bars** — integer count corresponding to "
                 "presence_share.")
    lines.append("- **mean_w** — average |w| in bars where the name is held. "
                 "For long books normalized to Σ = 1; for the LS book each "
                 "leg is normalized to 0.5.")
    lines.append("- **weight-time share** — `Σ_t |w_{i,t}| / Σ_t Σ_j |w_{j,t}|` "
                 "on this leg. Answers 'of all the dollar-weeks this leg "
                 "spent, what fraction went to this name'.")
    lines.append("")

    lines.append("## Coverage")
    lines.append("")
    show_cols = ["cell", "n_bars", "mean_held_per_bar", "max_held_per_bar",
                 "unique_names_total"]
    if "unique_names_long" in coverage_df.columns:
        show_cols += ["unique_names_long", "unique_names_short"]
    lines.append("| " + " | ".join(show_cols) + " |")
    lines.append("|" + "|".join([":---:"] * len(show_cols)) + "|")
    for _, r in coverage_df.iterrows():
        row = []
        for c in show_cols:
            v = r.get(c, "")
            if pd.isna(v):
                row.append("—")
            elif isinstance(v, float):
                row.append(f"{v:.2f}" if not float(v).is_integer() else str(int(v)))
            else:
                row.append(str(v))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # Per-cell tables
    for res in results:
        cell = res["cell"]
        names = res["names"]
        blocks = res["blocks"]
        lines.append(f"## {cell}")
        lines.append("")

        for side in sorted(names["side"].unique()):
            sub = names[names.side == side].head(TOP_N_NAMES_REPORT)
            leg_label = "long leg" if side == "long" else "short leg" \
                        if side == "short" else side
            lines.append(f"### Top {min(TOP_N_NAMES_REPORT, len(sub))} names — "
                         f"{leg_label} (by weight-time share)")
            lines.append("")
            lines.append("| rank | code | name_en | block | presence | "
                         "hit_bars | mean_w | wt-time share |")
            lines.append("|:---:|:---|:---|:---|---:|---:|---:|---:|")
            for i, r in sub.reset_index(drop=True).iterrows():
                lines.append(
                    f"| {i+1} | {r.code} | {r.name_en} | {r.block} | "
                    f"{_fmt_pct(r.presence_share)} | {int(r.hit_bars)} | "
                    f"{_fmt_wt(r.mean_w_when_held)} | "
                    f"{_fmt_pct(r.weight_time_share, 2)} |"
                )
            lines.append("")

        lines.append(f"### Block aggregate — {cell}")
        lines.append("")
        lines.append("| side | block | n names ever held | "
                     "Σ weight-time | mean presence |")
        lines.append("|:---:|:---|---:|---:|---:|")
        for _, r in blocks.iterrows():
            lines.append(
                f"| {r.side} | {r.block} | {int(r.n_names_ever_held)} | "
                f"{_fmt_pct(r.sum_weight_time, 1)} | "
                f"{_fmt_pct(r.mean_presence, 1)} |"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------- #
# Top-level driver
# ---------------------------------------------------------------------- #
def run() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    block_tag, name_en = _load_meta()

    results = []
    coverage_rows = []
    for mode, q in CELLS:
        res = _cell_stats(mode, q, block_tag, name_en)
        results.append(res)
        coverage_rows.append(res["coverage"])
        res["names"].to_csv(OUT_ROOT / f"{res['cell']}_names.csv", index=False)
        res["blocks"].to_csv(OUT_ROOT / f"{res['cell']}_blocks.csv", index=False)

        cov = res["coverage"]
        top3 = res["names"].head(3)
        top3_str = ", ".join(
            f"{r.code}({_fmt_pct(r.weight_time_share, 1)})"
            for _, r in top3.iterrows()
        )
        print(f"  {res['cell']:>8s}  T={cov['n_bars']}  "
              f"unique={cov['unique_names_total']:3d}  "
              f"mean|H|={cov['mean_held_per_bar']:5.2f}  "
              f"top-3 (weight-time): {top3_str}")

    coverage_df = pd.DataFrame(coverage_rows)
    coverage_df.to_csv(OUT_ROOT / "coverage.csv", index=False)

    report = _write_report(results, coverage_df)
    report_path = Path(__file__).resolve().parents[1] / "reports" / "holdings_popularity_v6.md"
    report_path.write_text(report)

    print(f"\nwrote {OUT_ROOT / 'coverage.csv'}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    run()
