"""v6/leverage/report_figures_round_d.py — PNG charts for the higher-cap
Word report.

Compares Round D (cap=5.0, σ*=6.4 %) vs Round C (cap=2.0, σ*=3.2 %),
both on the rep-set book, across {base, EW} × {GC007, DR007-proxy}.

Figures under ``v6/reports/figures_round_d/``:

    fig_d_nav.png        NAV curves (cap 2 vs cap 5)
    fig_d_drawdown.png   drawdown curves
    fig_d_L_path.png     weekly L_t path

Line convention:
- cap=5 = solid, thicker line (primary)
- cap=2 = dotted, thinner (control)
- base RB = full opacity
- EW RB   = dashed / lighter (secondary)
- GC007 = red family, DR007 = blue family
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import _common_leverage as CL


plt.rcParams["font.sans-serif"] = [
    "Arial Unicode MS", "PingFang SC", "Heiti TC", "Hei", "SimHei",
]
plt.rcParams["axes.unicode_minus"] = False

FIG_DIR = Path("/Users/allenzhou/Downloads/YSJ Lab/etf_basket_strategy/v6/reports/figures_round_d")
FIG_DIR.mkdir(parents=True, exist_ok=True)


# --- cell display config -----------------------------------------------
# Solid vs dotted encodes cap; color encodes funding curve; alpha/width
# encodes RB (base = full, EW = lighter dashed).
CELLS = {
    # base × cap=2 (control)
    "C_base_reps_lev":       dict(label="Base · cap=2 · GC007（对照）",
                                   color="#d62728", ls=":",  lw=1.4, alpha=0.85),
    "C_base_reps_lev_DR007": dict(label="Base · cap=2 · DR007代理（对照）",
                                   color="#1f77b4", ls=":",  lw=1.4, alpha=0.85),
    # base × cap=5 (primary)
    "D_base_reps_lev":       dict(label="Base · cap=5 · GC007",
                                   color="#d62728", ls="-",  lw=2.0, alpha=1.00),
    "D_base_reps_lev_DR007": dict(label="Base · cap=5 · DR007代理",
                                   color="#1f77b4", ls="-",  lw=2.0, alpha=1.00),
    # EW × cap=2 / cap=5 (secondary control)
    "C_ew_reps_lev":         dict(label="EW · cap=2 · GC007（对照）",
                                   color="#d62728", ls=":",  lw=1.0, alpha=0.55),
    "D_ew_reps_lev":         dict(label="EW · cap=5 · GC007",
                                   color="#d62728", ls="--", lw=1.4, alpha=0.75),
    "C_ew_reps_lev_DR007":   dict(label="EW · cap=2 · DR007代理（对照）",
                                   color="#1f77b4", ls=":",  lw=1.0, alpha=0.55),
    "D_ew_reps_lev_DR007":   dict(label="EW · cap=5 · DR007代理",
                                   color="#1f77b4", ls="--", lw=1.4, alpha=0.75),
}
CELL_ORDER = list(CELLS.keys())


def _load_net(cell: str) -> pd.Series:
    return pd.read_csv(CL.LEV_DIR / cell / "net_ret.csv",
                       index_col=0, parse_dates=True)["net_ret"]


def _load_lt(cell: str) -> pd.DataFrame:
    return pd.read_csv(CL.LEV_DIR / cell / "L_t_path.csv",
                       index_col=0, parse_dates=True)


def _first_nonzero(s: pd.Series) -> pd.Timestamp:
    nz = s[s.ne(0.0)]
    return nz.index.min() if len(nz) else s.index.min()


def _clip(idx, t0):
    return (idx >= t0) & (idx <= CL.OOS_END)


def _plot_kwargs(cfg):
    return {k: cfg[k] for k in ("color", "ls", "lw", "alpha")}


def draw_nav() -> None:
    fig, ax = plt.subplots(figsize=(11, 6.0))
    for cell in CELL_ORDER:
        cfg = CELLS[cell]
        s = _load_net(cell)
        t0 = _first_nonzero(s)
        mask = _clip(s.index, t0)
        s_post = s[mask]
        nav = 1.0 + s_post.cumsum()
        ax.plot(nav.index, nav.values, label=cfg["label"], **_plot_kwargs(cfg))

    ax.axvline(CL.IN_SAMPLE_END, color="gray", ls=":", lw=1)
    ax.text(CL.IN_SAMPLE_END, ax.get_ylim()[1]*0.98,
            "  IS 截止 2023-12-31", va="top", ha="left", color="gray", fontsize=9)
    ax.set_title("图1：净值曲线（常数名义 NAV = 1 + Σ 周度 net_ret，2019-05-31 至 2025-07-31）",
                 fontsize=12)
    ax.set_ylabel("NAV")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08),
              fontsize=9, ncol=4, frameon=False)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig_d_nav.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def draw_drawdown() -> None:
    fig, ax = plt.subplots(figsize=(11, 5.5))
    for cell in CELL_ORDER:
        cfg = CELLS[cell]
        s = _load_net(cell)
        t0 = _first_nonzero(s)
        mask = _clip(s.index, t0)
        s_post = s[mask]
        nav = 1.0 + s_post.cumsum()
        dd = (nav - nav.cummax()) / nav.cummax()
        ax.plot(dd.index, dd.values * 100, label=cfg["label"], **_plot_kwargs(cfg))

    ax.axvline(CL.IN_SAMPLE_END, color="gray", ls=":", lw=1)
    ax.axhline(0, color="k", lw=0.5)
    ax.set_title("图2：回撤曲线（NAV 相对历史峰值，%）", fontsize=12)
    ax.set_ylabel("回撤 (%)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08),
              fontsize=9, ncol=4, frameon=False)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig_d_drawdown.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def draw_L_path() -> None:
    """L_t doesn't depend on funding curve, so plot 4 lines only:
    {base, EW} × {cap=2, cap=5}, both under GC007."""
    fig, ax = plt.subplots(figsize=(11, 5.5))
    lt_cells = [
        ("C_base_reps_lev", "Base · cap=2 · σ*=3.2%（对照）",
             "#d62728", ":",  1.4, 0.85),
        ("D_base_reps_lev", "Base · cap=5 · σ*=6.4%",
             "#d62728", "-",  2.0, 1.00),
        ("C_ew_reps_lev",   "EW · cap=2 · σ*=3.2%（对照）",
             "#1f77b4", ":",  1.0, 0.55),
        ("D_ew_reps_lev",   "EW · cap=5 · σ*=6.4%",
             "#1f77b4", "--", 1.4, 0.85),
    ]
    for cell, label, color, ls, lw, alpha in lt_cells:
        df = _load_lt(cell)
        s_ret = _load_net(cell)
        t0 = _first_nonzero(s_ret)
        mask = _clip(df.index, t0)
        L = df["L_t"][mask]
        ax.plot(L.index, L.values, label=label,
                color=color, ls=ls, lw=lw, alpha=alpha)

    ax.axhline(5.0, color="k", ls=":", lw=0.8)
    ax.text(pd.Timestamp("2019-06-01"), 5.05, "cap = 5.0", fontsize=8.5, color="gray")
    ax.axhline(2.0, color="k", ls=":", lw=0.8)
    ax.text(pd.Timestamp("2019-06-01"), 2.05, "cap = 2.0（对照）", fontsize=8.5, color="gray")
    ax.axhline(1.0, color="k", ls=":", lw=0.6)
    ax.axvline(CL.IN_SAMPLE_END, color="gray", ls=":", lw=1)
    ax.set_title("图3：杠杆倍数 L_t 时间序列（对比 cap=2 σ*=3.2% 与 cap=5 σ*=6.4%）",
                 fontsize=12)
    ax.set_ylabel("L_t")
    ax.set_ylim(0.85, 5.3)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08),
              fontsize=9, ncol=4, frameon=False)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig_d_L_path.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    draw_nav()
    draw_drawdown()
    draw_L_path()
    print(f"wrote figures to {FIG_DIR}")


if __name__ == "__main__":
    main()
