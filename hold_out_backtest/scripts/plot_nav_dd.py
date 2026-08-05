"""
v6/hold_out_backtest/scripts/plot_nav_dd.py
===========================================
Two-subplot figure: NAV (rebased to 100) and drawdown (%) over the
hold-out window 2025-08-01 → 2026-08-04. cap=2 and cap=5 cells overlaid.

Reads:
    v6/data/hold_out_backtest/<cell>/net_ret.csv

Writes:
    v6/hold_out_backtest/reports/figures/nav_dd_hold_out.png
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

_HERE = Path(__file__).resolve()
DATA_ROOT = _HERE.parents[2] / "data" / "hold_out_backtest"
FIG_PATH  = _HERE.parents[1] / "reports" / "figures" / "nav_dd_hold_out.png"

HOLDOUT_START = pd.Timestamp("2025-08-01")
HOLDOUT_END   = pd.Timestamp("2026-08-04")
STRESS_END    = pd.Timestamp("2026-07-17")

CELLS = [
    ("base_reps_lev_cap2_dr007", "cap=2 (σ*=3.2 %)", "#1f77b4"),
    ("base_reps_lev_cap5_dr007", "cap=5 (σ*=6.4 %)", "#d62728"),
]


def _load(cell: str) -> pd.Series:
    df = pd.read_csv(DATA_ROOT / cell / "net_ret.csv",
                     index_col=0, parse_dates=True)
    s = df.iloc[:, 0]
    s = s[(s.index >= HOLDOUT_START) & (s.index <= HOLDOUT_END)]
    return s


def _nav_and_dd(net_ret: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Compounded NAV rebased to 100; drawdown in %."""
    nav = 100.0 * (1.0 + net_ret).cumprod()
    # Prepend a start point at 100 for a clean starting anchor
    start = pd.Series([100.0], index=[net_ret.index[0] - pd.Timedelta(days=1)])
    nav = pd.concat([start, nav])
    cummax = nav.cummax()
    dd = (nav / cummax - 1.0) * 100.0
    return nav, dd


def main() -> None:
    FIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    fig, (ax_nav, ax_dd) = plt.subplots(
        2, 1, figsize=(11, 7), sharex=True,
        gridspec_kw={"height_ratios": [2, 1], "hspace": 0.08},
    )

    for cell, label, color in CELLS:
        r = _load(cell)
        nav, dd = _nav_and_dd(r)
        end_nav = nav.iloc[-1]
        min_dd  = dd.min()
        ax_nav.plot(nav.index, nav.values, label=f"{label} — end NAV {end_nav:.2f}",
                    color=color, linewidth=1.8)
        ax_dd.plot(dd.index, dd.values,
                   label=f"{label} — max DD {min_dd:.2f}%",
                   color=color, linewidth=1.4)
        ax_dd.fill_between(dd.index, dd.values, 0.0, color=color, alpha=0.10)

    # Boundary between pre-registered stress window and post-freeze new bars
    for ax in (ax_nav, ax_dd):
        ax.axvline(STRESS_END, color="grey", linestyle=":", linewidth=1)
    ax_nav.text(STRESS_END, ax_nav.get_ylim()[1], "  post-freeze →",
                color="grey", fontsize=8, va="top")

    ax_nav.axhline(100.0, color="black", linewidth=0.7, alpha=0.5)
    ax_nav.set_ylabel("NAV (rebased to 100 at hold-out start)")
    ax_nav.set_title("v6 finalist — hold-out (2025-08-01 → 2026-08-04): "
                     "NAV & drawdown, base RB + reps, DR007 funding")
    ax_nav.grid(alpha=0.3)
    ax_nav.legend(loc="upper left", fontsize=9)

    ax_dd.axhline(0.0, color="black", linewidth=0.7, alpha=0.5)
    ax_dd.set_ylabel("Drawdown (%)")
    ax_dd.set_xlabel("date (weekly W-FRI bars)")
    ax_dd.grid(alpha=0.3)
    ax_dd.legend(loc="lower left", fontsize=9)

    # Nicer x-ticks: monthly majors
    ax_dd.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax_dd.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    for lbl in ax_dd.get_xticklabels():
        lbl.set_rotation(30); lbl.set_ha("right")

    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=140, bbox_inches="tight")
    print(f"wrote {FIG_PATH}")


if __name__ == "__main__":
    main()
