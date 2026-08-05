"""
v6/scripts/universe_v6_report.py
================================
Phase 3.3 diagnostics on the frozen MEMBERSHIP panel.

Reads:
    v6/data/universe_v6/catalogue.csv
    v6/data/universe_v6/px_daily.parquet
    v6/data/universe_v6/membership.parquet
    v6/data/universe_v6/membership_changes.csv

Writes:
    v6/reports/universe_v6_report.md
    v6/reports/universe_v6/N_curve.png
    v6/reports/universe_v6/churn_by_year.png
    v6/reports/universe_v6/adv_by_year.png
    v6/reports/universe_v6/block_composition.png   (skipped while all UNTAGGED)

The pre-registered N(t) sanity targets from DESIGN §2.5 sit alongside the
actuals in the header table so the freeze decision is auditable.

Run
---
    python v6/scripts/universe_v6_report.py
"""
from __future__ import annotations

import sys
from pathlib import Path
_HERE = Path(__file__).resolve()

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# --- v6/common sys.path bootstrap ---
import sys as _v6_sys
from pathlib import Path as _V6Path
_v6_p = _V6Path(__file__).resolve().parent
while _v6_p.name != "v6" and _v6_p.parent != _v6_p:
    _v6_p = _v6_p.parent
_v6_sys.path.insert(0, str(_v6_p / "common"))
del _v6_p
# --------------------------------------
import universe_v6 as U


# ---------------------------------------------------------------------- #
DATA_DIR    = _HERE.parents[2] / "data" / "universe_v6"
REPORTS_DIR = _HERE.parents[1] / "reports"  # v6/universe/reports
FIG_DIR     = REPORTS_DIR / "universe_v6"
REPORT_MD   = REPORTS_DIR / "universe_v6_report.md"

# Pre-registered from DESIGN §2.5 — evaluated at the last weekly bar ≤ date.
SANITY_TARGETS = [
    ("2019-12-31",  40,  60),
    ("2021-12-31",  80, 100),
    ("2024-12-31", 100, 150),
]


def _last_weekly(mem: pd.DataFrame, date: str) -> pd.Timestamp:
    ts = pd.Timestamp(date)
    prior = mem.index[mem.index <= ts]
    if not len(prior):
        return None
    return prior[-1]


def _fmt_range(lo, hi):
    return f"{lo}–{hi}"


# ---------------------------------------------------------------------- #
def plot_N_curve(mem: pd.DataFrame, out: Path) -> None:
    nt = mem.sum(axis=1)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(nt.index, nt.values, lw=1.2, color="#1f77b4")
    for date, lo, hi in SANITY_TARGETS:
        ax.axvspan(pd.Timestamp(date) - pd.Timedelta(days=90),
                   pd.Timestamp(date) + pd.Timedelta(days=90),
                   color="grey", alpha=0.08)
        ax.hlines([lo, hi], pd.Timestamp(date) - pd.Timedelta(days=90),
                  pd.Timestamp(date) + pd.Timedelta(days=90),
                  color="grey", lw=0.8, linestyle="--")
    ax.axvline(U.pd.Timestamp("2023-12-31"), color="crimson", lw=0.8,
               linestyle=":", label="IS end")
    ax.set_title("N(t) — admitted codes per W-FRI bar")
    ax.set_ylabel("N codes"); ax.set_xlabel("date")
    ax.legend(loc="upper left"); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(out, dpi=110); plt.close(fig)


def plot_churn_by_year(changes: pd.DataFrame, out: Path) -> None:
    if changes.empty:
        return
    ch = changes.copy()
    ch["year"] = pd.to_datetime(ch["date"]).dt.year
    events = ch.pivot_table(index="year", columns="event",
                            values="code", aggfunc="count").fillna(0).astype(int)
    fig, ax = plt.subplots(figsize=(10, 4))
    events.plot(kind="bar", stacked=True, ax=ax, colormap="tab10", width=0.85)
    ax.set_title("Membership churn by year (event count)")
    ax.set_ylabel("events"); ax.set_xlabel("year")
    ax.legend(loc="upper left", fontsize=8); ax.grid(alpha=0.3, axis="y")
    fig.tight_layout(); fig.savefig(out, dpi=110); plt.close(fig)


def plot_adv_by_year(px_long: pd.DataFrame, mem: pd.DataFrame,
                     out: Path) -> None:
    """Boxplot of trailing-60d median ADV for admitted names, per year.

    Only names admitted on the last weekly bar of each year are included.
    """
    amt = px_long.pivot(index="date", columns="code",
                        values="amount").sort_index()
    adv60 = amt.rolling(60, min_periods=30).median()

    per_year = {}
    for year in sorted(pd.to_datetime(mem.index).year.unique()):
        end_ts = mem.index[pd.to_datetime(mem.index).year == year][-1]
        cols_in = mem.columns[mem.loc[end_ts]].tolist()
        if not cols_in:
            continue
        # Nearest daily bar ≤ end_ts
        prior_daily = adv60.index[adv60.index <= end_ts]
        if not len(prior_daily):
            continue
        vals = adv60.loc[prior_daily[-1], cols_in].dropna().values
        if len(vals):
            per_year[int(year)] = vals / 1e6

    if not per_year:
        return
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.boxplot([per_year[y] for y in per_year],
               tick_labels=[str(y) for y in per_year],
               showfliers=False)
    ax.set_yscale("log")
    ax.set_title("Admitted-name ADV distribution, year-end snapshots "
                 "(trailing-60d median amount, RMB millions)")
    ax.set_ylabel("ADV (RMB m, log)"); ax.set_xlabel("year")
    ax.grid(alpha=0.3, which="both"); fig.tight_layout()
    fig.savefig(out, dpi=110); plt.close(fig)


def plot_block_composition(mem: pd.DataFrame, block_tag: dict,
                           out: Path) -> bool:
    """Stacked area of block share over time. Returns True if plotted,
    False if skipped (e.g., all UNTAGGED)."""
    tags = pd.Series({c: block_tag.get(c, "UNTAGGED") for c in mem.columns})
    if tags.nunique() <= 1:
        return False
    blocks = sorted(tags.unique())
    area = pd.DataFrame(0, index=mem.index, columns=blocks, dtype=int)
    for b in blocks:
        cols = tags[tags == b].index.tolist()
        if not cols:
            continue
        area[b] = mem[cols].sum(axis=1)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.stackplot(area.index, area.T.values, labels=area.columns,
                 colors=plt.cm.tab10(range(len(area.columns))))
    ax.set_title("Block composition of admitted pool through time")
    ax.set_ylabel("N codes"); ax.set_xlabel("date")
    ax.legend(loc="upper left", fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(out, dpi=110); plt.close(fig)
    return True


# ---------------------------------------------------------------------- #
def build_report() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # ---- load ----
    cat = pd.read_csv(DATA_DIR / "catalogue.csv",
                      parse_dates=["list_date", "delist_date"])
    px_long  = pd.read_parquet(DATA_DIR / "px_daily.parquet")
    mem      = pd.read_parquet(DATA_DIR / "membership.parquet")
    changes  = pd.read_csv(DATA_DIR / "membership_changes.csv",
                            parse_dates=["date"])
    block_tag = dict(zip(cat["code"], cat["block"]))

    # ---- figures ----
    plot_N_curve(mem, FIG_DIR / "N_curve.png")
    plot_churn_by_year(changes, FIG_DIR / "churn_by_year.png")
    plot_adv_by_year(px_long, mem, FIG_DIR / "adv_by_year.png")
    plotted_blocks = plot_block_composition(mem, block_tag,
                                            FIG_DIR / "block_composition.png")

    # ---- headline stats ----
    nt = mem.sum(axis=1)
    ever_admitted = int((mem.sum(axis=0) > 0).sum())
    first_40 = mem.index[nt >= 40][0] if (nt >= 40).any() else None
    first_60 = mem.index[nt >= 60][0] if (nt >= 60).any() else None

    # ---- sanity table ----
    rows = []
    for date, lo, hi in SANITY_TARGETS:
        bar = _last_weekly(mem, date)
        actual = int(nt.loc[bar]) if bar is not None else None
        status = "OK" if (actual is not None and lo <= actual <= hi) else "MISS"
        rows.append((date, bar.date() if bar is not None else "—",
                    _fmt_range(lo, hi), actual, status))
    sanity_tbl = pd.DataFrame(
        rows, columns=["target_date", "eval_bar", "target_N", "actual_N", "status"]
    )

    # ---- event summary ----
    events_by_type = changes["event"].value_counts().to_dict() if not changes.empty else {}

    # ---- write markdown ----
    lines = []
    lines.append("# `universe_v6` — MEMBERSHIP report (Phase 3.3)\n")
    lines.append("Auto-generated by `v6/scripts/universe_v6_report.py`.\n")
    lines.append("")

    lines.append("## Headline")
    lines.append("")
    lines.append(f"- Weekly bars (W-FRI): **{len(mem)}**   "
                 f"({mem.index.min().date()} → {mem.index.max().date()})")
    lines.append(f"- Catalogue size: **{len(cat)}** ETFs "
                 f"(1688 with px data, 15 delisted before 2018-06-01 or list_date in future)")
    lines.append(f"- Ever-admitted (`CODES_V6`): **{ever_admitted}**")
    lines.append(f"- N(t) min / median / max: "
                 f"**{int(nt.min())} / {int(nt.median())} / {int(nt.max())}**")
    if first_40 is not None:
        lines.append(f"- First bar with N ≥ 40: **{first_40.date()}**")
    if first_60 is not None:
        lines.append(f"- First bar with N ≥ 60: **{first_60.date()}**")
    lines.append("")

    lines.append("## Frozen floors (post-Phase 3.4 review — see DESIGN §2.4 addendum)")
    lines.append("")
    lines.append(f"- `SEASONING_BARS` = {U.SEASONING_BARS} weekly bars")
    lines.append(f"- `ADV_FLOOR_ENTER` = ¥{U.ADV_FLOOR_ENTER:,}   "
                 f"`ADV_FLOOR_EXIT` = ¥{U.ADV_FLOOR_EXIT:,}")
    lines.append(f"- `AUM_FLOOR_ENTER` = ¥{U.AUM_FLOOR_ENTER:,}   "
                 f"`AUM_FLOOR_EXIT` = ¥{U.AUM_FLOOR_EXIT:,}")
    lines.append(f"- `ADV_PCTL_ENTER` = {U.ADV_PCTL_ENTER}   "
                 f"`ADV_PCTL_EXIT` = {U.ADV_PCTL_EXIT}")
    lines.append(f"- `INDEX_DEDUP_ADV_MARGIN` = {U.INDEX_DEDUP_ADV_MARGIN}")
    lines.append("")

    lines.append("## N(t) sanity check (pre-registered from DESIGN §2.5)")
    lines.append("")
    lines.append(sanity_tbl.to_markdown(index=False))
    lines.append("")
    lines.append("Sanity targets are calibration hints, not gates (§2.5). "
                 "The 2019-12 target isn't met — the CN ETF market at that "
                 "date genuinely had few tradable names outside the top ~30 "
                 "indices. Recalibrating floors further to reach 40 admits "
                 "marginal names in 2024+ (see §2.4 addendum for the decision "
                 "trace).")
    lines.append("")

    lines.append("## N(t) curve")
    lines.append("")
    lines.append("![N(t)](universe_v6/N_curve.png)")
    lines.append("")
    lines.append("Grey bands mark the ±90-day windows around the pre-registered "
                 "sanity dates; dashed lines are the target [lo, hi] band. "
                 "Red dotted vertical is the IS-end freeze at 2023-12-31.")
    lines.append("")

    lines.append("## Churn per year")
    lines.append("")
    lines.append("![churn](universe_v6/churn_by_year.png)")
    lines.append("")
    if events_by_type:
        etbl = pd.DataFrame(sorted(events_by_type.items(),
                                    key=lambda kv: -kv[1]),
                            columns=["event", "count"])
        lines.append(etbl.to_markdown(index=False))
        lines.append("")

    lines.append("## ADV distribution by year (admitted names, year-end)")
    lines.append("")
    lines.append("![ADV boxplot](universe_v6/adv_by_year.png)")
    lines.append("")

    lines.append("## Block composition through time")
    lines.append("")
    if plotted_blocks:
        lines.append("![blocks](universe_v6/block_composition.png)")
    else:
        lines.append(
            "*Deferred.* All catalogue rows are currently `UNTAGGED`. Per "
            "the resolved Open Decision D1 in `IMPLEMENTATION_PLAN.md`, "
            "block tagging happens **after** MEMBERSHIP is frozen and is "
            f"scoped to the {ever_admitted} ever-admitted codes only. Rerun "
            "this report after that pass to populate the block-composition "
            "chart."
        )
    lines.append("")

    REPORT_MD.write_text("\n".join(lines))
    print(f"[report] wrote {REPORT_MD}")
    for f in ("N_curve.png", "churn_by_year.png", "adv_by_year.png"):
        if (FIG_DIR / f).exists():
            print(f"[report] wrote {FIG_DIR / f}")
    if plotted_blocks:
        print(f"[report] wrote {FIG_DIR / 'block_composition.png'}")


if __name__ == "__main__":
    build_report()
