"""v6/leverage/report_figures.py — PNG charts for the leverage Word report.

Produces four figures under ``v6/reports/figures/``:

    fig_nav.png          NAV curves (constant-notional NAV = 1 + Σ net_ret)
    fig_drawdown.png     drawdown curves (peak-to-trough on NAV path)
    fig_L_path.png       weekly L_t path for the levered variants
    fig_duration.png     book_duration_yr weekly time series

Cells shown: A_base_nolev (基准), A_base_lev (GC007), B_base_lev_DR007,
A_ew_nolev (对照), A_ew_lev (对照). EW variants are dashed to signal
"control group" status per the report brief.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import _common_leverage as CL

# --- Chinese fonts ------------------------------------------------------
plt.rcParams["font.sans-serif"] = [
    "Arial Unicode MS", "PingFang SC", "Heiti TC", "Hei", "SimHei",
]
plt.rcParams["axes.unicode_minus"] = False

FIG_DIR = Path("/Users/allenzhou/Downloads/YSJ Lab/etf_basket_strategy/v6/reports/figures")
FIG_DIR.mkdir(parents=True, exist_ok=True)


# --- cell display config ------------------------------------------------
CELLS = {
    "A_base_nolev":     dict(label="Base 无杠杆（基准）",     color="#1f77b4", ls="-",  lw=1.6),
    "A_base_lev":       dict(label="Base + 杠杆 · GC007",      color="#d62728", ls="-",  lw=1.8),
    "B_base_lev_DR007": dict(label="Base + 杠杆 · DR007代理",  color="#ff7f0e", ls="-",  lw=1.8),
    "A_ew_nolev":       dict(label="EW 无杠杆（对照）",        color="#1f77b4", ls="--", lw=1.2),
    "A_ew_lev":         dict(label="EW + 杠杆 · GC007（对照）",color="#d62728", ls="--", lw=1.2),
}


def _load_net(cell: str) -> pd.Series:
    p = CL.LEV_DIR / cell / "net_ret.csv"
    return pd.read_csv(p, index_col=0, parse_dates=True)["net_ret"]


def _load_lt(cell: str) -> pd.DataFrame:
    return pd.read_csv(CL.LEV_DIR / cell / "L_t_path.csv",
                       index_col=0, parse_dates=True)


def _load_dur(cell: str) -> pd.DataFrame:
    return pd.read_csv(CL.LEV_DIR / cell / "duration_ledger.csv",
                       index_col=0, parse_dates=True)


def _first_nonzero(s: pd.Series) -> pd.Timestamp:
    nz = s[s.ne(0.0)]
    return nz.index.min() if len(nz) else s.index.min()


def _clip(idx: pd.DatetimeIndex, t0: pd.Timestamp) -> slice:
    """Slice from first non-zero bar through OOS_END inclusive.
    Stress window (> OOS_END) is intentionally excluded from every chart
    per user directive (2026-07-30). Prior v6 reports use the same cutoff."""
    return (idx >= t0) & (idx <= CL.OOS_END)


# --- Figure 1: NAV ------------------------------------------------------
def draw_nav() -> None:
    fig, ax = plt.subplots(figsize=(11, 5.5))
    for cell, cfg in CELLS.items():
        s = _load_net(cell)
        t0 = _first_nonzero(s)
        mask = _clip(s.index, t0)
        s_post = s[mask]
        # NAV in constant-notional = 1 + cumsum(net_ret) — matches v6 convention.
        nav = 1.0 + s_post.cumsum()
        ax.plot(nav.index, nav.values, **{k: cfg[k] for k in ("color","ls","lw")},
                label=cfg["label"])

    ax.axvline(CL.IN_SAMPLE_END, color="gray", ls=":", lw=1)
    ax.text(CL.IN_SAMPLE_END, ax.get_ylim()[1]*0.98,
            "  IS 截止 2023-12-31", va="top", ha="left", color="gray", fontsize=9)
    ax.set_title("图1：净值曲线（常数名义 NAV = 1 + Σ 周度 net_ret，IS ∪ OOS ≤ 2025-07-31）",
                 fontsize=12)
    ax.set_ylabel("NAV")
    ax.set_xlabel("")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=9, ncol=1)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig_nav.png", dpi=160)
    plt.close(fig)


# --- Figure 2: Drawdown -------------------------------------------------
def draw_drawdown() -> None:
    fig, ax = plt.subplots(figsize=(11, 5.5))
    for cell, cfg in CELLS.items():
        s = _load_net(cell)
        t0 = _first_nonzero(s)
        mask = _clip(s.index, t0)
        s_post = s[mask]
        nav = 1.0 + s_post.cumsum()
        dd = (nav - nav.cummax()) / nav.cummax()
        ax.plot(dd.index, dd.values * 100,
                **{k: cfg[k] for k in ("color","ls","lw")},
                label=cfg["label"])
    ax.axvline(CL.IN_SAMPLE_END, color="gray", ls=":", lw=1)
    ax.axhline(0, color="k", lw=0.5)
    ax.set_title("图2：回撤曲线（NAV 相对历史峰值，%）", fontsize=12)
    ax.set_ylabel("回撤 (%)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower left", fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig_drawdown.png", dpi=160)
    plt.close(fig)


# --- Figure 3: L_t path -------------------------------------------------
def draw_L_path() -> None:
    fig, ax = plt.subplots(figsize=(11, 5.0))
    for cell in ("A_base_lev", "B_base_lev_DR007", "A_ew_lev"):
        cfg = CELLS[cell]
        df = _load_lt(cell)
        s_ret = _load_net(cell)
        t0 = _first_nonzero(s_ret)
        mask = _clip(df.index, t0)
        L = df["L_t"][mask]
        ax.plot(L.index, L.values,
                **{k: cfg[k] for k in ("color","ls","lw")},
                label=cfg["label"])
    ax.axhline(2.0, color="k", ls=":", lw=0.8, label="cap = 2.0")
    ax.axhline(1.0, color="k", ls=":", lw=0.8)
    ax.axvline(CL.IN_SAMPLE_END, color="gray", ls=":", lw=1)
    ax.set_title("图3：杠杆倍数 L_t 时间序列（σ*=3.2%，clip[1, 2]）", fontsize=12)
    ax.set_ylabel("L_t")
    ax.set_ylim(0.85, 2.15)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig_L_path.png", dpi=160)
    plt.close(fig)


# --- Figure 4: Duration -------------------------------------------------
def draw_duration() -> None:
    fig, ax = plt.subplots(figsize=(11, 5.0))
    for cell in ("A_base_nolev", "A_base_lev", "B_base_lev_DR007", "A_ew_lev"):
        cfg = CELLS[cell]
        df = _load_dur(cell)
        s_ret = _load_net(cell)
        t0 = _first_nonzero(s_ret)
        mask = _clip(df.index, t0)
        dur = df["book_duration_yr"][mask]
        ax.plot(dur.index, dur.values,
                **{k: cfg[k] for k in ("color","ls","lw")},
                label=cfg["label"])
    ax.axvline(CL.IN_SAMPLE_END, color="gray", ls=":", lw=1)
    ax.set_title("图4：整本久期（年数，L·W_name × KRD 加权）", fontsize=12)
    ax.set_ylabel("book_duration_yr（年）")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig_duration.png", dpi=160)
    plt.close(fig)


# --- Figure 5: rf curves ------------------------------------------------
def draw_rf() -> None:
    import funding_curves as FC
    fig, ax = plt.subplots(figsize=(11, 5.0))
    gc = FC.load("gc007")
    dr = FC.load("dr007")
    # Clip to <= OOS_END; stress window intentionally excluded from report.
    gc = gc[gc.index <= CL.OOS_END]
    dr = dr[dr.index <= CL.OOS_END]
    ax.plot(gc.index, gc.values * 100, color="#1f77b4",
            label="GC007 (204007.XSHG，交易所国债回购)", lw=1.2)
    ax.plot(dr.index, dr.values * 100, color="#d62728",
            label="DR007 代理（SHIBOR-1W）", lw=1.2)
    ax.axvline(CL.IN_SAMPLE_END, color="gray", ls=":", lw=1)
    ax.set_title("图5：资金利率曲线（年化 %）", fontsize=12)
    ax.set_ylabel("年化利率 (%)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right", fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig_rf.png", dpi=160)
    plt.close(fig)


def main() -> None:
    draw_nav()
    draw_drawdown()
    draw_L_path()
    draw_duration()
    draw_rf()
    print(f"wrote figures to {FIG_DIR}")


if __name__ == "__main__":
    main()
