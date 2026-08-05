"""
build_report.py
===============
生成 v6 two-layer 设计中文报告用的图表 + 汇总数据。

主要输出：
- ./figures/*.png
- ./_summary.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm

HERE = Path(__file__).resolve().parent
V6_ROOT = HERE.parent
DATA = V6_ROOT / "data"
FIG_DIR = HERE / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

# --- 中文字体 ---------------------------------------------------------
_CH_FONT_CANDIDATES = [
    "PingFang SC", "Heiti SC", "Songti SC", "STHeiti", "STSong",
    "Arial Unicode MS", "Hiragino Sans GB",
]
_available = {f.name for f in fm.fontManager.ttflist}
for _c in _CH_FONT_CANDIDATES:
    if _c in _available:
        mpl.rcParams["font.family"] = _c
        break
mpl.rcParams["axes.unicode_minus"] = False
mpl.rcParams["figure.dpi"] = 130
mpl.rcParams["savefig.bbox"] = "tight"

WPY = 52
IN_SAMPLE_END = pd.Timestamp("2023-12-31")
OOS_START = pd.Timestamp("2024-01-01")
OOS_END = pd.Timestamp("2025-07-31")
COST_BP = 10.0   # bp / side

# Layer-1 政策风险预算
POLICY_SHARES = {
    "equity":      0.55,
    "bond_rates":  0.20,
    "bond_credit": 0.10,
    "commodity":   0.15,
}
GROUP_ORDER = ["equity", "bond_rates", "bond_credit", "commodity"]
GROUP_ZH = {
    "equity":      "权益",
    "bond_rates":  "利率债",
    "bond_credit": "信用债",
    "commodity":   "商品",
}
GROUP_COLORS = {
    "equity":      "#c0392b",
    "bond_rates":  "#1f77b4",
    "bond_credit": "#3498db",
    "commodity":   "#f39c12",
}


# ============================================================
# 1. 数据加载
# ============================================================
BOOKS = {
    "two_layer_q20_e30": DATA / "block_two_layer_v6" / "q20_eps030" / "net_ret.csv",
    "two_layer_q10_e30": DATA / "block_two_layer_v6" / "q10_eps030" / "net_ret.csv",
    "two_layer_baseline": DATA / "block_two_layer_v6" / "baseline" / "net_ret.csv",
    "layer1_invvol_lw_erc":
        DATA / "block_risk_budget_v6_no_trend" / "invvol_lw_erc" / "net_ret.csv",
    "T2_bond_invvol": DATA / "bond_attribution_v6" / "T2_bond_invvol" / "net_ret.csv",
    "solo_defensive_final":
        DATA / "v6_static" / "oos_shot_ap" / "bar_solo_defensive.csv",
}

# gross_ret 文件（用于 gross Sharpe / cost drag）
GROSS = {
    "two_layer_q20_e30": DATA / "block_two_layer_v6" / "q20_eps030" / "gross_ret.csv",
    "two_layer_q10_e30": DATA / "block_two_layer_v6" / "q10_eps030" / "gross_ret.csv",
    "two_layer_baseline": DATA / "block_two_layer_v6" / "baseline" / "gross_ret.csv",
}

# turnover 从 summary.csv 里取
SUMMARY_FILES = {
    "two_layer_q20_e30": DATA / "block_two_layer_v6" / "q20_eps030" / "summary.csv",
    "two_layer_q10_e30": DATA / "block_two_layer_v6" / "q10_eps030" / "summary.csv",
    "two_layer_baseline": DATA / "block_two_layer_v6" / "baseline" / "summary.csv",
}

# 组权重 parquet
WGROUP_FILES = {
    "two_layer_q20_e30": DATA / "block_two_layer_v6" / "q20_eps030" / "w_group.parquet",
    "two_layer_q10_e30": DATA / "block_two_layer_v6" / "q10_eps030" / "w_group.parquet",
    "two_layer_baseline": DATA / "block_two_layer_v6" / "baseline" / "w_group.parquet",
}

# 实际风险贡献 parquet（仅 Layer-1 canonical 有保存）
RC_FILE = DATA / "block_risk_budget_v6_no_trend" / "invvol_lw_erc" / "realized_rc.parquet"

# ---------- 实验二（非-α 块代表集） -----------
EXP2_ROOT = DATA / "exp2_representative_sets_v6"
EXP2_BOOKS = {
    "exp2_hold_all":   EXP2_ROOT / "hold_all_net_ret.csv",
    "exp2_replicated": EXP2_ROOT / "replicated_net_ret.csv",
}
EXP2_GROSS = {
    "exp2_hold_all":   EXP2_ROOT / "hold_all_gross_ret.csv",
    "exp2_replicated": EXP2_ROOT / "replicated_gross_ret.csv",
}
EXP2_TURN = {
    "exp2_hold_all":   EXP2_ROOT / "hold_all_turnover.csv",
    "exp2_replicated": EXP2_ROOT / "replicated_turnover.csv",
}
EXP2_LABELS = {
    "exp2_hold_all":   "全持（hold-all，K均值=38.1）",
    "exp2_replicated": "代表集（adaptive K，K均值=24.1）",
}
EXP2_COLORS = {
    "exp2_hold_all":   "#7f8c8d",
    "exp2_replicated": "#c0392b",
}
EXP2_ATTR_FILE = EXP2_ROOT / "turnover_attribution.csv"
EXP2_K_BY_YEAR = EXP2_ROOT / "K_by_year.csv"
EXP2_BOOK_IMPACT = EXP2_ROOT / "book_impact.csv"

# ---------- 实验一（风险预算敏感性） -----------
EXP1_ROOT = DATA / "exp1_risk_budget_sensitivity_v6"
EXP1_CELLS = EXP1_ROOT / "cells.csv"
EXP1_SLOPE = EXP1_ROOT / "axis_slope.csv"

AXIS_ZH = {
    "equity":      "权益",
    "bond_rates":  "利率债",
    "bond_credit": "信用债",
    "commodity":   "商品",
}
AXIS_SHARE_KEY = {
    "equity":      "eq_share",
    "bond_rates":  "br_share",
    "bond_credit": "bc_share",
    "commodity":   "cm_share",
}
AXIS_COLORS = {
    "equity":      "#c0392b",
    "bond_rates":  "#1f77b4",
    "bond_credit": "#3498db",
    "commodity":   "#f39c12",
}


def load_net(path: Path, col: str = "net_ret") -> pd.Series:
    df = pd.read_csv(path, parse_dates=[0], index_col=0)
    if col not in df.columns:
        col = df.columns[0]
    s = df[col].astype(float).sort_index()
    s.index.name = None
    return s


def first_live_bar(s: pd.Series) -> pd.Timestamp:
    nz = (s.abs() > 0.0)
    if not bool(nz.any()):
        return s.index[0]
    return s.index[int(nz.values.argmax())]


# ============================================================
# 2. 指标计算
# ============================================================
def window_stats(net: pd.Series) -> dict:
    n = int(len(net))
    if n < 2:
        return dict(sharpe=np.nan, cagr=np.nan, dd=np.nan,
                    ann_vol=np.nan, ann_ret=np.nan, cumret=np.nan,
                    calmar=np.nan, n_bars=n)
    ann_vol = float(net.std(ddof=1)) * np.sqrt(WPY)
    ann_ret = float(net.mean()) * WPY
    sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
    cumret = float(net.sum())
    n_years = max(n / WPY, 1e-3)
    cagr = max(1.0 + cumret, 1e-9) ** (1.0 / n_years) - 1.0
    nav = 1.0 + net.cumsum()
    dd = float(((nav - nav.cummax()) / nav.cummax()).min())
    calmar = (cagr / abs(dd)) if abs(dd) > 1e-12 else np.nan
    return dict(sharpe=sharpe, cagr=cagr, dd=dd, ann_vol=ann_vol,
                ann_ret=ann_ret, cumret=cumret, calmar=calmar, n_bars=n)


def split_windows(s: pd.Series, start: pd.Timestamp) -> dict[str, pd.Series]:
    idx = s.index
    is_mask = (idx >= start) & (idx <= IN_SAMPLE_END)
    oos_mask = (idx >= OOS_START) & (idx <= OOS_END)
    return {
        "IS": s[is_mask],
        "OOS": s[oos_mask],
        "full": s[is_mask | oos_mask],
    }


def yearly_breakdown(net: pd.Series) -> pd.DataFrame:
    rows = []
    for year, s in net.groupby(net.index.year):
        if len(s) < 2:
            continue
        ann_vol = float(s.std(ddof=1)) * np.sqrt(WPY)
        ann_ret = float(s.mean()) * WPY
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
        cum = 1.0 + s.cumsum()
        dd = float(((cum - cum.cummax()) / cum.cummax()).min())
        year_ret = float(s.sum())
        rows.append({
            "year": int(year),
            "ret": year_ret,
            "sharpe": sharpe,
            "ann_vol": ann_vol,
            "max_dd": dd,
            "n_bars": int(len(s)),
        })
    return pd.DataFrame(rows).set_index("year")


# ============================================================
# 3. 绘图
# ============================================================
LABELS = {
    "two_layer_q20_e30":     "双层 q=0.20 ε=0.30 (plateau)",
    "two_layer_q10_e30":     "双层 q=0.10 ε=0.30 (raw IS 最高)",
    "two_layer_baseline":    "双层 α off (纯 Layer-1 参照)",
    "layer1_invvol_lw_erc":  "Layer-1 canonical (invvol·LW-ERC)",
    "T2_bond_invvol":        "T2 债券 inv-vol 被动本",
    "solo_defensive_final":  "旧版 finalist: solo defensive",
}
COLORS = {
    "two_layer_q20_e30":     "#c0392b",
    "two_layer_q10_e30":     "#e67e22",
    "two_layer_baseline":    "#7f8c8d",
    "layer1_invvol_lw_erc":  "#1f77b4",
    "T2_bond_invvol":        "#2ca02c",
    "solo_defensive_final":  "#8e44ad",
}


def plot_nav(nets: dict[str, pd.Series], order: list[str],
             title: str, out: Path,
             start: pd.Timestamp | None = None,
             end: pd.Timestamp | None = None) -> None:
    if end is None:
        end = OOS_END
    fig, ax = plt.subplots(figsize=(9.6, 4.6))
    for name in order:
        s = nets[name]
        if start is not None:
            s = s.loc[s.index >= start]
        s = s.loc[s.index <= end]
        nav = 1.0 + s.cumsum()
        ax.plot(nav.index, nav.values, color=COLORS[name], lw=1.5,
                label=LABELS[name])
    ax.axvline(IN_SAMPLE_END, color="grey", ls="--", lw=1.0)
    ymax = ax.get_ylim()[1]
    ax.text(IN_SAMPLE_END, ymax, " OOS 起点", va="top",
            fontsize=9, color="grey")
    ax.set_title(title)
    ax.set_ylabel("净值（起始 = 1，含成本）")
    ax.set_xlabel("周频调仓日 (W-FRI)")
    ax.grid(alpha=0.3)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_dd(nets: dict[str, pd.Series], order: list[str],
            title: str, out: Path,
            start: pd.Timestamp | None = None,
            end: pd.Timestamp | None = None) -> None:
    if end is None:
        end = OOS_END
    fig, ax = plt.subplots(figsize=(9.6, 4.6))
    for name in order:
        s = nets[name]
        if start is not None:
            s = s.loc[s.index >= start]
        s = s.loc[s.index <= end]
        nav = 1.0 + s.cumsum()
        dd = (nav - nav.cummax()) / nav.cummax()
        ax.fill_between(dd.index, dd.values, 0,
                        color=COLORS[name], alpha=0.18)
        ax.plot(dd.index, dd.values, color=COLORS[name], lw=1.1,
                label=LABELS[name])
    ax.axvline(IN_SAMPLE_END, color="grey", ls="--", lw=1.0)
    ax.set_title(title)
    ax.set_ylabel("回撤（相对历史高点）")
    ax.set_xlabel("周频调仓日 (W-FRI)")
    ax.grid(alpha=0.3)
    ax.legend(frameon=False, fontsize=9, loc="lower left")
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_sweep_heatmap(sweep: pd.DataFrame, out: Path) -> None:
    piv = sweep.pivot(index="epsilon", columns="q", values="sharpe_net")
    piv = piv.sort_index(ascending=False)
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    im = ax.imshow(piv.values, aspect="auto", cmap="RdYlGn",
                   vmin=1.30, vmax=1.50)
    ax.set_xticks(range(len(piv.columns)))
    ax.set_xticklabels([f"{v:.2f}" for v in piv.columns])
    ax.set_yticks(range(len(piv.index)))
    ax.set_yticklabels([f"{v:.2f}" for v in piv.index])
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            ax.text(j, i, f"{piv.values[i, j]:.3f}",
                    ha="center", va="center", fontsize=9, color="black")
    ax.set_xlabel("q（Top 分位）")
    ax.set_ylabel("ε（迟滞缓冲带）")
    ax.set_title("Layer-2 α 扫格：样本内净夏普（12 cells）")
    plt.colorbar(im, ax=ax, shrink=0.85, label="IS 净夏普")
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_metric_bars(stats: dict, order: list[str],
                     metric_key: str, win: str, ylabel: str,
                     title: str, out: Path,
                     as_pct: bool = False) -> None:
    fig, ax = plt.subplots(figsize=(9.6, 4.4))
    xs = np.arange(len(order))
    vals = [stats[n][win][metric_key] for n in order]
    if as_pct:
        vals = [v * 100 for v in vals]
    colors = [COLORS[n] for n in order]
    ax.bar(xs, vals, color=colors, edgecolor="white")
    for i, v in enumerate(vals):
        offset = max(abs(v) * 0.03, 0.03)
        ax.text(i, v + (offset if v >= 0 else -offset),
                (f"{v:.2f}%" if as_pct else f"{v:.3f}"),
                ha="center", va=("bottom" if v >= 0 else "top"),
                fontsize=9)
    ax.set_xticks(xs)
    ax.set_xticklabels([LABELS[n] for n in order], rotation=15,
                        ha="right", fontsize=9)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(alpha=0.25, axis="y")
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_sharpe_windows(stats: dict, order: list[str], out: Path) -> None:
    windows = ["IS", "OOS", "full"]
    win_zh = ["样本内", "样本外", "全窗"]
    xs = np.arange(len(order))
    w = 0.26
    fig, ax = plt.subplots(figsize=(11, 4.6))
    for j, (wk, wz) in enumerate(zip(windows, win_zh)):
        vals = [stats[n][wk]["sharpe"] for n in order]
        offs = (j - 1) * w
        col = ["#7f8c8d", "#c0392b", "#1f77b4"][j]
        bars = ax.bar(xs + offs, vals, width=w, color=col, label=wz)
        for x, v in zip(xs + offs, vals):
            ax.text(x, v + 0.05, f"{v:.2f}", ha="center", fontsize=8)
    ax.set_xticks(xs)
    ax.set_xticklabels([LABELS[n] for n in order], rotation=15,
                        ha="right", fontsize=9)
    ax.set_ylabel("净夏普")
    ax.set_title("六个方案的净夏普：样本内 / 样本外 / 全窗")
    ax.grid(alpha=0.25, axis="y")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_calmar_bars(stats: dict, order: list[str], out: Path) -> None:
    xs = np.arange(len(order))
    vals = [stats[n]["full"]["calmar"] for n in order]
    fig, ax = plt.subplots(figsize=(9.6, 4.4))
    colors = [COLORS[n] for n in order]
    ax.bar(xs, vals, color=colors, edgecolor="white")
    for i, v in enumerate(vals):
        ax.text(i, v + 0.05, f"{v:.2f}", ha="center", fontsize=9)
    ax.set_xticks(xs)
    ax.set_xticklabels([LABELS[n] for n in order], rotation=15,
                        ha="right", fontsize=9)
    ax.set_ylabel("Calmar 比率  = CAGR / |Max DD|")
    ax.set_title("全窗 Calmar 比率：Layer-2 α 层保住了 CAGR，Layer-1 结构压住了回撤")
    ax.grid(alpha=0.25, axis="y")
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_yearly_grouped(yearly: dict[str, pd.DataFrame], order: list[str],
                         out: Path) -> None:
    years = sorted({y for name in order for y in yearly[name].index})
    xs = np.arange(len(years))
    n = len(order)
    w = 0.8 / n
    fig, ax = plt.subplots(figsize=(11, 4.6))
    for i, name in enumerate(order):
        yb = yearly[name]
        vals = [float(yb.loc[y, "ret"] * 100) if y in yb.index else 0.0
                for y in years]
        offs = (i - (n - 1) / 2) * w
        ax.bar(xs + offs, vals, width=w, color=COLORS[name],
               label=LABELS[name])
    ax.axhline(0, color="black", lw=0.8)
    ax.axvline(xs[years.index(2024)] - 0.5, color="grey", ls="--", lw=1.0)
    ax.set_xticks(xs)
    ax.set_xticklabels([str(y) for y in years])
    ax.set_ylabel("全年净收益 (%)")
    ax.set_title("六个方案：分年度净收益 (灰色虚线右侧为 OOS)")
    ax.grid(alpha=0.25, axis="y")
    ax.legend(frameon=False, fontsize=8, ncol=3)
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_turnover_bars(order: list[str], turnovers: dict[str, float],
                       out: Path) -> None:
    have = [n for n in order if n in turnovers]
    xs = np.arange(len(have))
    vals = [turnovers[n] * 100 for n in have]
    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    ax.bar(xs, vals, color=[COLORS[n] for n in have], edgecolor="white")
    for i, v in enumerate(vals):
        ax.text(i, v + 0.1, f"{v:.2f}%", ha="center", fontsize=9)
    ax.set_xticks(xs)
    ax.set_xticklabels([LABELS[n] for n in have], rotation=15,
                        ha="right", fontsize=9)
    ax.set_ylabel("平均单边换手 (每周, %)")
    ax.set_title("每周单边换手：α 层在 hysteresis 下的成本代价")
    ax.grid(alpha=0.25, axis="y")
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def load_wgroup(path: Path) -> pd.DataFrame:
    w = pd.read_parquet(path)
    w = w.loc[w.index <= OOS_END, GROUP_ORDER]
    # 只保留有仓位的 bar
    return w[w.sum(axis=1) > 1e-3]


def yearly_group_weights(w: pd.DataFrame) -> pd.DataFrame:
    return w.groupby(w.index.year).mean() * 100.0


def plot_wgroup_area(w: pd.DataFrame, title: str, out: Path) -> None:
    """Stacked-area of capital weights over time; overlay policy-share reference."""
    # 用 rolling 平滑一下（4 周），避免视觉噪声太强
    w_smooth = w.rolling(window=4, min_periods=1).mean() * 100.0
    fig, ax = plt.subplots(figsize=(10, 4.6))
    xs = w_smooth.index
    bottom = np.zeros(len(w_smooth))
    for g in GROUP_ORDER:
        vals = w_smooth[g].values
        ax.fill_between(xs, bottom, bottom + vals,
                        color=GROUP_COLORS[g], alpha=0.85,
                        label=f"{GROUP_ZH[g]}（政策 {POLICY_SHARES[g]*100:.0f}% 风险）")
        bottom = bottom + vals
    ax.axvline(IN_SAMPLE_END, color="black", ls="--", lw=1.0)
    ax.set_ylim(0, 100)
    ax.set_ylabel("组间资本权重（%，4 周平滑）")
    ax.set_xlabel("周频调仓日")
    ax.set_title(title)
    ax.grid(alpha=0.25)
    ax.legend(loc="lower left", frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_policy_vs_capital(yearly_cap: pd.DataFrame, out: Path) -> None:
    """左：政策风险预算 55/20/10/15；右：realized 资本权重 IS/OOS 均值。"""
    IS = yearly_cap.loc[yearly_cap.index <= 2023].mean()
    OOS = yearly_cap.loc[yearly_cap.index >= 2024].mean()

    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    xs = np.arange(len(GROUP_ORDER))
    w = 0.28
    policy = [POLICY_SHARES[g] * 100 for g in GROUP_ORDER]
    is_vals = [IS[g] for g in GROUP_ORDER]
    oos_vals = [OOS[g] for g in GROUP_ORDER]
    ax.bar(xs - w, policy, width=w, color="#7f8c8d",
           label="政策风险贡献目标")
    ax.bar(xs, is_vals, width=w, color="#1f77b4",
           label="IS 平均资本权重")
    ax.bar(xs + w, oos_vals, width=w, color="#c0392b",
           label="OOS 平均资本权重")
    for i, (p, a, b) in enumerate(zip(policy, is_vals, oos_vals)):
        ax.text(i - w, p + 1, f"{p:.0f}%", ha="center", fontsize=9)
        ax.text(i,     a + 1, f"{a:.1f}%", ha="center", fontsize=9)
        ax.text(i + w, b + 1, f"{b:.1f}%", ha="center", fontsize=9)
    ax.set_xticks(xs)
    ax.set_xticklabels([GROUP_ZH[g] for g in GROUP_ORDER])
    ax.set_ylabel("百分比 (%)")
    ax.set_title("Layer-1 政策风险贡献目标 vs 实际资本权重（q=0.20 ε=0.30）")
    ax.grid(alpha=0.25, axis="y")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_rc_check(rc: pd.DataFrame, out: Path) -> None:
    """验证 realized RC 是否等于 policy target。"""
    rc = rc.dropna()
    rc = rc.loc[rc.index <= OOS_END, GROUP_ORDER]
    fig, ax = plt.subplots(figsize=(10, 4.4))
    for g in GROUP_ORDER:
        ax.plot(rc.index, rc[g].values * 100, color=GROUP_COLORS[g],
                lw=1.4, label=f"{GROUP_ZH[g]} (target {POLICY_SHARES[g]*100:.0f}%)")
        ax.axhline(POLICY_SHARES[g] * 100, color=GROUP_COLORS[g],
                   ls=":", lw=0.8, alpha=0.6)
    ax.axvline(IN_SAMPLE_END, color="black", ls="--", lw=1.0)
    ax.set_ylabel("实际风险贡献 RC%")
    ax.set_xlabel("周频调仓日")
    ax.set_title("Layer-1 校验：LW-ERC solver 的实际 RC% 严格命中政策目标")
    ax.grid(alpha=0.25)
    ax.legend(loc="center left", frameon=False, fontsize=9)
    ax.set_ylim(0, 65)
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def _load_turnover(path: Path) -> pd.Series:
    df = pd.read_csv(path, parse_dates=[0], index_col=0)
    s = df["turnover"].astype(float).sort_index()
    s.index.name = None
    return s


def _yearly_vol_ret(net: pd.Series) -> pd.DataFrame:
    rows = []
    for year, s in net.groupby(net.index.year):
        if len(s) < 2:
            continue
        rows.append({
            "year":    int(year),
            "ret":     float(s.sum()),
            "ann_vol": float(s.std(ddof=1)) * float(np.sqrt(WPY)),
            "n_bars":  int(len(s)),
        })
    return pd.DataFrame(rows).set_index("year")


def plot_exp2_nav(nets: dict[str, pd.Series], out: Path,
                  start: pd.Timestamp, title: str,
                  end: pd.Timestamp | None = None) -> None:
    if end is None:
        end = OOS_END
    fig, ax = plt.subplots(figsize=(9.6, 4.6))
    for name in ("exp2_hold_all", "exp2_replicated"):
        s = nets[name]
        s = s.loc[(s.index >= start) & (s.index <= end)]
        nav = 1.0 + s.cumsum()
        ax.plot(nav.index, nav.values, color=EXP2_COLORS[name], lw=1.6,
                label=EXP2_LABELS[name])
    ax.axvline(IN_SAMPLE_END, color="grey", ls="--", lw=1.0)
    ymax = ax.get_ylim()[1]
    ax.text(IN_SAMPLE_END, ymax, " OOS 起点", va="top",
            fontsize=9, color="grey")
    ax.set_title(title)
    ax.set_ylabel("净值（起始 = 1，含成本）")
    ax.set_xlabel("周频调仓日 (W-FRI)")
    ax.grid(alpha=0.3)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_exp2_dd(nets: dict[str, pd.Series], out: Path,
                 start: pd.Timestamp, title: str,
                 end: pd.Timestamp | None = None) -> None:
    if end is None:
        end = OOS_END
    fig, ax = plt.subplots(figsize=(9.6, 4.6))
    for name in ("exp2_hold_all", "exp2_replicated"):
        s = nets[name]
        s = s.loc[(s.index >= start) & (s.index <= end)]
        nav = 1.0 + s.cumsum()
        dd = (nav - nav.cummax()) / nav.cummax()
        ax.fill_between(dd.index, dd.values, 0,
                        color=EXP2_COLORS[name], alpha=0.20)
        ax.plot(dd.index, dd.values, color=EXP2_COLORS[name], lw=1.2,
                label=EXP2_LABELS[name])
    ax.axvline(IN_SAMPLE_END, color="grey", ls="--", lw=1.0)
    ax.set_title(title)
    ax.set_ylabel("回撤（相对历史高点）")
    ax.set_xlabel("周频调仓日 (W-FRI)")
    ax.grid(alpha=0.3)
    ax.legend(frameon=False, fontsize=9, loc="lower left")
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_exp2_yearly_vol_ret(yearly: dict[str, pd.DataFrame], out: Path,
                             start_year: int = 2019) -> None:
    """两联图：上图分年度净收益 (%)，下图分年度年化波动 (%)。"""
    years = sorted({int(y) for name in yearly for y in yearly[name].index
                    if int(y) >= start_year})
    xs = np.arange(len(years))
    w = 0.38
    fig, axes = plt.subplots(2, 1, figsize=(10.4, 6.6), sharex=True)
    for i, (metric, ylabel, title) in enumerate([
        ("ret",     "全年净收益 (%)", "分年度净收益（含成本）"),
        ("ann_vol", "年化波动 (%)",    "分年度年化波动（策略层面）"),
    ]):
        ax = axes[i]
        for j, name in enumerate(("exp2_hold_all", "exp2_replicated")):
            yb = yearly[name]
            vals = [float(yb.loc[y, metric] * 100) if y in yb.index else 0.0
                    for y in years]
            offs = (j - 0.5) * w
            ax.bar(xs + offs, vals, width=w, color=EXP2_COLORS[name],
                   edgecolor="white", label=EXP2_LABELS[name])
            for x, v in zip(xs + offs, vals):
                ax.text(x, v + max(abs(v) * 0.05, 0.03),
                        f"{v:.2f}%", ha="center", fontsize=8)
        if 2024 in years:
            ax.axvline(xs[years.index(2024)] - 0.5,
                       color="grey", ls="--", lw=1.0)
        ax.set_xticks(xs)
        ax.set_xticklabels([str(y) for y in years])
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(alpha=0.25, axis="y")
        if i == 0:
            ax.legend(frameon=False, fontsize=9)
    fig.suptitle("实验二：全持 vs 代表集 — 年化收益与年化波动分年对比",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_exp2_turnover_ts(turn: dict[str, pd.Series], out: Path,
                          refresh_dates: list[pd.Timestamp]) -> None:
    fig, ax = plt.subplots(figsize=(10.4, 4.4))
    for name in ("exp2_hold_all", "exp2_replicated"):
        s = turn[name].loc[turn[name].index <= OOS_END]
        ax.plot(s.index, s.values * 100.0, color=EXP2_COLORS[name],
                lw=1.1, label=EXP2_LABELS[name], alpha=0.9)
    for d in refresh_dates:
        ax.axvline(d, color="#95a5a6", ls=":", lw=0.7, alpha=0.55)
    ax.axvline(IN_SAMPLE_END, color="black", ls="--", lw=1.0)
    ax.set_ylabel("单边换手 (%)")
    ax.set_xlabel("周频调仓日")
    ax.set_title("实验二：单边换手时序（灰色虚线为 refresh week，每年首个 W-FRI）")
    ax.grid(alpha=0.25)
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_exp2_K_by_year(K_by_year: pd.DataFrame, out: Path) -> None:
    """六联图：K vs N over years per block."""
    blocks = sorted(K_by_year["block"].unique())
    fig, axes = plt.subplots(2, 3, figsize=(12.5, 6.6))
    palette = {b: c for b, c in zip(blocks,
        ["#1f77b4", "#3498db", "#c0392b", "#e67e22", "#9b59b6", "#16a085"])}
    for i, b in enumerate(blocks):
        ax = axes[i // 3, i % 3]
        sub = K_by_year[K_by_year["block"] == b].sort_values("year")
        years = sub["year"].astype(int).tolist()
        K = sub["K"].astype(int).tolist()
        N = sub["n"].astype(int).tolist()
        ax.plot(years, N, color="#7f8c8d", ls="--", marker="o", lw=1.4,
                label="N (入池数)")
        ax.plot(years, K, color=palette[b], marker="s", lw=1.8,
                label="K (代表数)")
        for x, k, n in zip(years, K, N):
            ax.annotate(f"{k}/{n}", (x, k),
                        textcoords="offset points", xytext=(0, 8),
                        ha="center", fontsize=8, color=palette[b])
        ymax = max(max(N), max(K)) + 3
        ax.set_ylim(0, ymax)
        ax.set_xticks(years)
        ax.set_xticklabels([str(y) for y in years], fontsize=8)
        ax.set_title(b, fontsize=10)
        ax.grid(alpha=0.25)
        if i == 0:
            ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.suptitle("实验二：adaptive-K 每年每块的 K vs N（残差波动阈 0.20）",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_exp1_axis_slope(slope: pd.DataFrame, cross_sigma: dict[str, float],
                          out: Path) -> None:
    """轴向 ±10pp 边际斜率柱状图（Δ IS / OOS Sharpe），叠加 cross-cell σ 噪声线。"""
    axes_ = ["equity", "bond_rates", "bond_credit", "commodity"]
    xs = np.arange(len(axes_))
    w = 0.2
    fig, ax = plt.subplots(figsize=(10.6, 4.8))
    pos_is = [float(slope[(slope["axis"] == a) &
                          (slope["direction"] == "+10pp")]["d_is_sharpe"].iloc[0])
              for a in axes_]
    neg_is = [float(slope[(slope["axis"] == a) &
                          (slope["direction"] == "-10pp")]["d_is_sharpe"].iloc[0])
              for a in axes_]
    pos_oos = [float(slope[(slope["axis"] == a) &
                           (slope["direction"] == "+10pp")]["d_oos_sharpe"].iloc[0])
               for a in axes_]
    neg_oos = [float(slope[(slope["axis"] == a) &
                           (slope["direction"] == "-10pp")]["d_oos_sharpe"].iloc[0])
               for a in axes_]
    ax.bar(xs - 1.5 * w, pos_is,  width=w, color="#1f77b4",
           label="Δ IS Sh · +10pp")
    ax.bar(xs - 0.5 * w, neg_is,  width=w, color="#3498db",
           label="Δ IS Sh · −10pp")
    ax.bar(xs + 0.5 * w, pos_oos, width=w, color="#c0392b",
           label="Δ OOS Sh · +10pp")
    ax.bar(xs + 1.5 * w, neg_oos, width=w, color="#e67e22",
           label="Δ OOS Sh · −10pp")
    for i, vals in enumerate(zip(pos_is, neg_is, pos_oos, neg_oos)):
        for j, v in enumerate(vals):
            offx = (j - 1.5) * w
            ax.text(xs[i] + offx, v + (0.02 if v >= 0 else -0.04),
                    f"{v:+.2f}", ha="center", fontsize=8,
                    color=("black" if abs(v) > 0.02 else "grey"))
    # 噪声横线
    is_sig = cross_sigma["IS_Sh"]
    oos_sig = cross_sigma["OOS_Sh"]
    ax.axhline(+is_sig,  color="#1f77b4", ls=":", lw=1.2,
               alpha=0.8, label=f"±1σ IS cross-cell = ±{is_sig:.2f}")
    ax.axhline(-is_sig,  color="#1f77b4", ls=":", lw=1.2, alpha=0.8)
    ax.axhline(+oos_sig, color="#c0392b", ls=":", lw=1.2,
               alpha=0.8, label=f"±1σ OOS cross-cell = ±{oos_sig:.2f}")
    ax.axhline(-oos_sig, color="#c0392b", ls=":", lw=1.2, alpha=0.8)
    ax.axhline(0, color="black", lw=0.6)
    ax.set_xticks(xs)
    ax.set_xticklabels([AXIS_ZH[a] for a in axes_])
    ax.set_ylabel("Δ 夏普（相对 base = 55/20/10/15）")
    ax.set_title("实验一：单轴 ±10pp 边际斜率 vs cross-cell σ 噪声带")
    ax.grid(alpha=0.25, axis="y")
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="lower left")
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_exp1_marginal_scatters(cells: pd.DataFrame,
                                base_row: pd.Series,
                                ew_row: pd.Series,
                                out: Path) -> None:
    """4 联散点：4 轴 share vs OOS Sharpe，附最小二乘拟合线。"""
    axes_ = ["equity", "bond_rates", "bond_credit", "commodity"]
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 7.2))
    for i, a in enumerate(axes_):
        ax = axes[i // 2, i % 2]
        col = AXIS_SHARE_KEY[a]
        x = cells[col].astype(float).values * 100
        y = cells["oos_sharpe"].astype(float).values
        ax.scatter(x, y, s=20, color=AXIS_COLORS[a], alpha=0.55,
                   edgecolor="white", label="80 grid cells")
        # OLS
        if len(x) >= 2 and float(np.std(x)) > 0:
            b1, b0 = np.polyfit(x, y, 1)
            xr = np.array([x.min(), x.max()])
            ax.plot(xr, b0 + b1 * xr, color=AXIS_COLORS[a], lw=1.3,
                    label=f"OLS 斜率 {b1:+.3f} /pp")
            r = float(np.corrcoef(x, y)[0, 1])
            ax.text(0.02, 0.02, f"corr(share, OOS Sh) = {r:+.2f}",
                    transform=ax.transAxes, fontsize=9,
                    color=AXIS_COLORS[a],
                    verticalalignment="bottom")
        # base / EW anchors
        ax.scatter(base_row[col] * 100, base_row["oos_sharpe"],
                   marker="s", s=90, color="black", label="base 55/20/10/15",
                   zorder=5)
        ax.scatter(ew_row[col] * 100, ew_row["oos_sharpe"],
                   marker="D", s=90, color="#16a085", label="EW 25/25/25/25",
                   zorder=5)
        ax.set_xlabel(f"{AXIS_ZH[a]} 政策风险贡献占比 (%)")
        ax.set_ylabel("OOS 净夏普")
        ax.set_title(f"{AXIS_ZH[a]} 轴")
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8, frameon=False, loc="upper right")
    fig.suptitle("实验一：4 个轴各自的 share vs OOS Sharpe 散点 —— "
                 "只有权益轴斜率明显（负相关），其他三轴散点近乎无结构",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_exp1_equity_dominance(cells: pd.DataFrame,
                               base_row: pd.Series,
                               ew_row: pd.Series,
                               out: Path) -> None:
    """左：equity share vs OOS Sharpe；右：equity share vs OOS DD & CAGR
    ——支持「equity ↑ → CAGR ↑ / DD 恶化 / Sh ↓」的三合一结论。"""
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.4))
    x = cells["eq_share"].values * 100
    for i, (col, ylabel, title, invert) in enumerate([
        ("oos_sharpe", "OOS 净夏普", "OOS 夏普 vs 权益占比", False),
        ("oos_cagr",   "OOS CAGR (%)", "OOS CAGR vs 权益占比", False),
        ("oos_max_dd", "OOS 最大回撤 (%)", "OOS 最大回撤 vs 权益占比", False),
    ]):
        ax = axes[i]
        y = cells[col].values * (100 if col != "oos_sharpe" else 1)
        ax.scatter(x, y, s=22, color="#c0392b", alpha=0.55,
                   edgecolor="white", label="80 grid cells")
        b1, b0 = np.polyfit(x, y, 1)
        xr = np.array([x.min(), x.max()])
        ax.plot(xr, b0 + b1 * xr, color="#c0392b", lw=1.3,
                label=f"OLS 斜率 {b1:+.4f} /pp")
        r = float(np.corrcoef(x, y)[0, 1])
        ax.text(0.02, 0.02, f"corr = {r:+.2f}",
                transform=ax.transAxes, fontsize=9, color="#c0392b",
                verticalalignment="bottom")
        # anchors
        by = base_row[col] * (100 if col != "oos_sharpe" else 1)
        ey = ew_row[col] * (100 if col != "oos_sharpe" else 1)
        ax.scatter(base_row["eq_share"] * 100, by,
                   marker="s", s=90, color="black", label="base")
        ax.scatter(ew_row["eq_share"] * 100, ey,
                   marker="D", s=90, color="#16a085", label="EW")
        ax.set_xlabel("权益政策风险贡献占比 (%)")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8, frameon=False, loc="upper right")
    fig.suptitle("实验一：权益轴的三个截面 —— equity ↑ 同时"
                 "推高 CAGR、恶化 DD、拉低 Sharpe（内部一致）",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_exp1_top_bottom(cells: pd.DataFrame, out: Path) -> None:
    """Top-5 vs Bottom-5 (按 OOS Sh) 的 4 轴 share 分布。"""
    top5 = cells.sort_values("oos_sharpe", ascending=False).head(5)
    bot5 = cells.sort_values("oos_sharpe", ascending=True).head(5)
    axes_ = ["equity", "bond_rates", "bond_credit", "commodity"]
    fig, ax = plt.subplots(figsize=(9.6, 4.4))
    xs = np.arange(len(axes_))
    w = 0.35
    top_vals = [top5[AXIS_SHARE_KEY[a]].mean() * 100 for a in axes_]
    bot_vals = [bot5[AXIS_SHARE_KEY[a]].mean() * 100 for a in axes_]
    ax.bar(xs - w / 2, top_vals, width=w, color="#27ae60",
           label="Top-5 (按 OOS Sh)")
    ax.bar(xs + w / 2, bot_vals, width=w, color="#c0392b",
           label="Bottom-5 (按 OOS Sh)")
    for i, (t, b) in enumerate(zip(top_vals, bot_vals)):
        ax.text(xs[i] - w / 2, t + 1, f"{t:.1f}%", ha="center", fontsize=9)
        ax.text(xs[i] + w / 2, b + 1, f"{b:.1f}%", ha="center", fontsize=9)
    ax.set_xticks(xs)
    ax.set_xticklabels([AXIS_ZH[a] for a in axes_])
    ax.set_ylabel("平均政策风险贡献占比 (%)")
    ax.set_title(f"实验一：Top-5 vs Bottom-5 (按 OOS Sh) 的 4 轴平均占比 —— "
                 f"唯一系统性差异在权益（Top-5 {top_vals[0]:.1f}% vs Bottom-5 {bot_vals[0]:.1f}%）")
    ax.grid(alpha=0.25, axis="y")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_layer1_only(nets: dict[str, pd.Series], out: Path) -> None:
    order = ["two_layer_baseline", "layer1_invvol_lw_erc"]
    fig, ax = plt.subplots(figsize=(9.6, 4.6))
    for name in order:
        s = nets[name].loc[nets[name].index <= OOS_END]
        nav = 1.0 + s.cumsum()
        ax.plot(nav.index, nav.values, color=COLORS[name], lw=1.5,
                label=LABELS[name])
    ax.axvline(IN_SAMPLE_END, color="grey", ls="--", lw=1.0)
    ax.set_title("双层结构 α off  ≡  Layer-1 canonical（净值曲线几乎重叠）")
    ax.set_ylabel("净值")
    ax.set_xlabel("周频调仓日")
    ax.grid(alpha=0.3); ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


# ============================================================
# 4. 主流程
# ============================================================
def main() -> None:
    print("[1/4] loading net_ret series...")
    nets: dict[str, pd.Series] = {}
    for name, path in BOOKS.items():
        col = "net_ret" if name != "solo_defensive_final" else "net_ret"
        nets[name] = load_net(path, col=col)
    gross_nets = {name: load_net(path, col="gross_ret")
                  for name, path in GROSS.items()}

    # ---- 公共起点 ----
    first_live = {n: first_live_bar(s) for n, s in nets.items()}
    common_start = max(first_live.values())
    print(f"    first-live per book:")
    for n, d in first_live.items():
        print(f"      {n:<24s} {d.date()}")
    print(f"    common start = {common_start.date()}")

    # ---- 每 book 三窗指标 ----
    stats: dict[str, dict[str, dict]] = {}
    for name, s in nets.items():
        wins = split_windows(s, common_start)
        stats[name] = {k: window_stats(v) for k, v in wins.items()}

    # ---- gross Sharpe（用于成本贡献） ----
    gross_stats: dict[str, dict[str, dict]] = {}
    for name, s in gross_nets.items():
        wins = split_windows(s, common_start)
        gross_stats[name] = {k: window_stats(v) for k, v in wins.items()}

    # ---- turnover / mean K ----
    turnovers: dict[str, float] = {}
    mean_K: dict[str, float] = {}
    for name, p in SUMMARY_FILES.items():
        df = pd.read_csv(p)
        turnovers[name] = float(df["avg_turnover"].iloc[0])
        mean_K[name] = float(df["mean_K"].iloc[0])

    # ---- yearly ----
    yearly: dict[str, pd.DataFrame] = {}
    for name, s in nets.items():
        # 只保留 common_start 之后
        y = yearly_breakdown(s.loc[s.index >= common_start])
        yearly[name] = y

    # ---- 扫格数据 ----
    sweep = pd.read_csv(DATA / "block_two_layer_v6" / "sweep_summary.csv")

    # =========================
    # 绘图
    # =========================
    print("[2/4] making figures...")
    order_full = [
        "two_layer_q20_e30",
        "two_layer_q10_e30",
        "two_layer_baseline",
        "layer1_invvol_lw_erc",
        "T2_bond_invvol",
        "solo_defensive_final",
    ]
    order_no_solo = [n for n in order_full if n != "solo_defensive_final"]

    # 1. 扫格热力图
    plot_sweep_heatmap(sweep, FIG_DIR / "fig01_sweep_heatmap.png")

    # 2. 双层 α off ≡ layer-1 canonical
    plot_layer1_only(nets, FIG_DIR / "fig02_alpha_off_identity.png")

    # 3. 六个方案全窗 NAV（从 common_start 起）
    plot_nav(nets, order_full,
             "六个方案的净值曲线（含成本，10 bp / 单边）",
             FIG_DIR / "fig03_nav_all.png", start=common_start)

    # 4. 六个方案回撤
    plot_dd(nets, order_full,
            "六个方案的回撤路径",
            FIG_DIR / "fig04_dd_all.png", start=common_start)

    # 5. OOS zoom
    plot_nav(nets, order_full,
             "样本外净值：2024-01-01 → 2025-07-31",
             FIG_DIR / "fig05_nav_oos.png", start=OOS_START)
    plot_dd(nets, order_full,
            "样本外回撤：2024-01-01 → 2025-07-31",
            FIG_DIR / "fig06_dd_oos.png", start=OOS_START)

    # 6. Sharpe 三窗对比（六方案）
    plot_sharpe_windows(stats, order_full, FIG_DIR / "fig07_sharpe_windows.png")

    # 7. Calmar 比率
    plot_calmar_bars(stats, order_full, FIG_DIR / "fig08_calmar.png")

    # 8. 最大回撤
    plot_metric_bars(stats, order_full, "dd", "full",
                     "最大回撤（%）", "全窗最大回撤对比",
                     FIG_DIR / "fig09_maxdd.png", as_pct=True)

    # 9. CAGR
    plot_metric_bars(stats, order_full, "cagr", "full",
                     "CAGR（%）", "全窗 CAGR 对比",
                     FIG_DIR / "fig10_cagr.png", as_pct=True)

    # 10. yearly grouped
    plot_yearly_grouped(yearly, order_full, FIG_DIR / "fig11_yearly.png")

    # 11. turnover
    plot_turnover_bars(order_no_solo, turnovers, FIG_DIR / "fig12_turnover.png")

    # =========================
    # 组间资本权重（holdings）
    # =========================
    print("    holdings figures...")
    wgroup: dict[str, pd.DataFrame] = {}
    yearly_cap: dict[str, pd.DataFrame] = {}
    for name, path in WGROUP_FILES.items():
        w = load_wgroup(path)
        wgroup[name] = w
        yearly_cap[name] = yearly_group_weights(w)

    plot_wgroup_area(wgroup["two_layer_q20_e30"],
                     "双层 q=0.20 ε=0.30：组间资本权重时序（stack area）",
                     FIG_DIR / "fig13_wgroup_area_q20.png")
    plot_wgroup_area(wgroup["two_layer_q10_e30"],
                     "双层 q=0.10 ε=0.30：组间资本权重时序（stack area）",
                     FIG_DIR / "fig14_wgroup_area_q10.png")
    plot_policy_vs_capital(yearly_cap["two_layer_q20_e30"],
                           FIG_DIR / "fig15_policy_vs_capital.png")

    # RC 校验图
    rc = pd.read_parquet(RC_FILE)
    plot_rc_check(rc, FIG_DIR / "fig16_rc_check.png")

    # =========================
    # 实验二：非-α 块代表集
    # =========================
    print("    exp2 (representative sets) figures...")
    exp2_nets: dict[str, pd.Series] = {
        name: load_net(path, col="net_ret") for name, path in EXP2_BOOKS.items()
    }
    exp2_gross: dict[str, pd.Series] = {
        name: load_net(path, col="gross_ret") for name, path in EXP2_GROSS.items()
    }
    exp2_turn: dict[str, pd.Series] = {
        name: _load_turnover(path) for name, path in EXP2_TURN.items()
    }
    exp2_first_live = max(first_live_bar(s) for s in exp2_nets.values())
    print(f"    exp2 common first-live = {exp2_first_live.date()}")

    # 三窗指标（warmup-trim 到共同 first-live）
    exp2_stats: dict[str, dict[str, dict]] = {}
    for name, s in exp2_nets.items():
        wins = split_windows(s, exp2_first_live)
        exp2_stats[name] = {k: window_stats(v) for k, v in wins.items()}
    exp2_gross_stats: dict[str, dict[str, dict]] = {}
    for name, s in exp2_gross.items():
        wins = split_windows(s, exp2_first_live)
        exp2_gross_stats[name] = {k: window_stats(v) for k, v in wins.items()}

    # 年度收益 + 年化波动
    exp2_yearly: dict[str, pd.DataFrame] = {}
    for name, s in exp2_nets.items():
        exp2_yearly[name] = _yearly_vol_ret(
            s.loc[s.index >= exp2_first_live])

    # 换手 attribution + refresh dates
    attr_df = pd.read_csv(EXP2_ATTR_FILE)
    exp2_turn_attr = {r["variant"]: dict(r) for _, r in attr_df.iterrows()}

    idx_full = exp2_nets["exp2_hold_all"].index
    y_start = int(idx_full[0].year)
    y_end = int(min(OOS_END.year, idx_full[-1].year))
    refresh_dates = []
    for y in range(y_start, y_end + 1):
        after = idx_full[idx_full >= pd.Timestamp(y, 1, 1)]
        if len(after):
            refresh_dates.append(after[0])

    # 图：NAV / DD 全窗 + OOS + 分年度收益 & 波动 + 换手时序 + K/N grid
    plot_exp2_nav(exp2_nets, FIG_DIR / "fig_exp2_01_nav_full.png",
                  exp2_first_live,
                  "实验二：hold-all vs 代表集 · 全窗净值")
    plot_exp2_dd(exp2_nets, FIG_DIR / "fig_exp2_02_dd_full.png",
                 exp2_first_live,
                 "实验二：hold-all vs 代表集 · 回撤路径")
    plot_exp2_nav(exp2_nets, FIG_DIR / "fig_exp2_03_nav_oos.png",
                  OOS_START,
                  "实验二：hold-all vs 代表集 · OOS 窗口净值")
    plot_exp2_dd(exp2_nets, FIG_DIR / "fig_exp2_04_dd_oos.png",
                 OOS_START,
                 "实验二：hold-all vs 代表集 · OOS 窗口回撤")
    plot_exp2_yearly_vol_ret(exp2_yearly,
                             FIG_DIR / "fig_exp2_05_yearly.png")
    plot_exp2_turnover_ts(exp2_turn,
                          FIG_DIR / "fig_exp2_06_turnover.png",
                          refresh_dates)
    K_by_year = pd.read_csv(EXP2_K_BY_YEAR)
    plot_exp2_K_by_year(K_by_year, FIG_DIR / "fig_exp2_07_k_by_year.png")

    # =========================
    # 实验一：风险预算敏感性
    # =========================
    print("    exp1 (risk-budget sensitivity) figures...")
    exp1_cells_all = pd.read_csv(EXP1_CELLS)
    exp1_grid = exp1_cells_all[exp1_cells_all["kind"] == "grid"].copy()
    exp1_slope = pd.read_csv(EXP1_SLOPE)
    exp1_base = exp1_cells_all[exp1_cells_all["tag"] == "base"].iloc[0]
    exp1_ew = exp1_cells_all[exp1_cells_all["tag"] == "EW"].iloc[0]

    cross_sigma = {
        "IS_Sh":   float(exp1_grid["is_sharpe"].std()),
        "OOS_Sh":  float(exp1_grid["oos_sharpe"].std()),
        "IS_CAGR": float(exp1_grid["is_cagr"].std()) * 100,
        "OOS_CAGR": float(exp1_grid["oos_cagr"].std()) * 100,
        "IS_DD":   float(exp1_grid["is_max_dd"].std()) * 100,
        "OOS_DD":  float(exp1_grid["oos_max_dd"].std()) * 100,
    }

    # Top / Bottom-5
    top5 = exp1_grid.sort_values("oos_sharpe", ascending=False).head(5)
    bot5 = exp1_grid.sort_values("oos_sharpe", ascending=True).head(5)

    # Marginal 轴相关系数 —— 用于文中「只有权益轴有明显斜率」的定量支撑
    axis_marginals: dict[str, dict] = {}
    for a, col in AXIS_SHARE_KEY.items():
        x = exp1_grid[col].values.astype(float)
        for w in ("is_sharpe", "oos_sharpe", "oos_cagr", "oos_max_dd"):
            y = exp1_grid[w].values.astype(float)
            if float(np.std(x)) > 0 and float(np.std(y)) > 0:
                r = float(np.corrcoef(x, y)[0, 1])
                slope_v = float(np.polyfit(x, y, 1)[0])
            else:
                r, slope_v = float("nan"), float("nan")
            axis_marginals.setdefault(a, {})[w] = {"corr": r, "slope_per_unit": slope_v}

    plot_exp1_axis_slope(exp1_slope, cross_sigma,
                         FIG_DIR / "fig_exp1_01_axis_slope.png")
    plot_exp1_marginal_scatters(exp1_grid, exp1_base, exp1_ew,
                                FIG_DIR / "fig_exp1_02_marginal_scatters.png")
    plot_exp1_equity_dominance(exp1_grid, exp1_base, exp1_ew,
                               FIG_DIR / "fig_exp1_03_equity_dominance.png")
    plot_exp1_top_bottom(exp1_grid,
                         FIG_DIR / "fig_exp1_04_top_bottom.png")

    # =========================
    # 汇总 JSON
    # =========================
    print("[3/4] writing _summary.json ...")
    out = {
        "common_start": str(common_start.date()),
        "first_live": {n: str(d.date()) for n, d in first_live.items()},
        "turnovers": turnovers,
        "mean_K": mean_K,
        "sweep": sweep.to_dict(orient="records"),
        "stats": {name: {win: stats[name][win] for win in ("IS", "OOS", "full")}
                  for name in order_full},
        "gross_stats": {name: {win: gross_stats[name][win] for win in ("IS", "OOS", "full")}
                        for name in gross_stats},
        "yearly": {name: yearly[name].reset_index().to_dict(orient="records")
                    for name in order_full},
        "labels": LABELS,
        "policy_shares": POLICY_SHARES,
        "yearly_capital": {
            name: {int(y): {g: float(yearly_cap[name].loc[y, g])
                            for g in GROUP_ORDER}
                   for y in yearly_cap[name].index}
            for name in yearly_cap
        },
        "window_capital": {
            name: {
                "IS": {g: float(yearly_cap[name].loc[
                                    yearly_cap[name].index <= 2023, g].mean())
                       for g in GROUP_ORDER},
                "OOS": {g: float(yearly_cap[name].loc[
                                     yearly_cap[name].index >= 2024, g].mean())
                        for g in GROUP_ORDER},
                "full": {g: float(yearly_cap[name][g].mean())
                         for g in GROUP_ORDER},
            }
            for name in yearly_cap
        },
        "exp2": {
            "common_first_live": str(exp2_first_live.date()),
            "stats": {name: {win: exp2_stats[name][win]
                             for win in ("IS", "OOS", "full")}
                      for name in exp2_nets},
            "gross_stats": {name: {win: exp2_gross_stats[name][win]
                                   for win in ("IS", "OOS", "full")}
                            for name in exp2_gross},
            "yearly": {name: exp2_yearly[name].reset_index().to_dict(
                orient="records") for name in exp2_yearly},
            "turnover_attribution": exp2_turn_attr,
            "K_by_year": K_by_year.to_dict(orient="records"),
        },
        "exp1": {
            "base":   exp1_base.to_dict(),
            "EW":     exp1_ew.to_dict(),
            "axis_slope": exp1_slope.to_dict(orient="records"),
            "cross_sigma": cross_sigma,
            "top5":  top5.to_dict(orient="records"),
            "bot5":  bot5.to_dict(orient="records"),
            "axis_marginals": axis_marginals,
        },
    }
    with open(HERE / "_summary.json", "w") as f:
        json.dump(out, f, indent=2, default=float)

    # 简洁打印
    print("[4/4] headline metrics:")
    for name in order_full:
        s = stats[name]
        print(f"  {name:<24s}  "
              f"IS Sh={s['IS']['sharpe']:+.3f} CAGR={s['IS']['cagr']*100:+.2f}%  "
              f"OOS Sh={s['OOS']['sharpe']:+.3f} CAGR={s['OOS']['cagr']*100:+.2f}%  "
              f"full Sh={s['full']['sharpe']:+.3f}  "
              f"Calmar={s['full']['calmar']:+.2f}  DD={s['full']['dd']*100:+.2f}%")


if __name__ == "__main__":
    main()
