"""
build_report.py
===============
生成 v6 项目中文汇总报告（含 Word 文档 + 全部图表）。

- 复用现有的 alpha 集成面板 + 池子/成分数据，运行 hysteresis 引擎，
  为三个纯多头 baseline (long_q05, long_q10, long_q20) 生成
  "加入 hysteresis 前 / 后" 两条净值序列。
- 全部图表输出到 ./figures/。
- Word 报告输出到 ./v6_strategy_report_cn.docx。
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
V6_ROOT = HERE.parent
SCRIPTS = V6_ROOT / "scripts"
DATA = V6_ROOT / "data"
REPORTS = V6_ROOT / "reports"
FIG_DIR = HERE / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(SCRIPTS))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib import font_manager as fm

# --- 中文字体（macOS 常见字体优先） ---------------------------------
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
import hysteresis_engine_v6 as H

IN_END = C.IN_SAMPLE_END
OOS_START = C.OOS_START
OOS_END = C.OOS_END
WPY = C.WEEKS_PER_YEAR
COST = E.DEFAULT_COST_PER_TRADE


# ============================================================
# 1. 池子相关：读取 universe 面板并绘图
# ============================================================
def load_universe_panels():
    mem = pd.read_parquet(DATA / "universe_v6" / "membership.parquet")
    changes = pd.read_csv(DATA / "universe_v6" / "membership_changes.csv")
    catalogue = pd.read_csv(DATA / "universe_v6" / "catalogue.csv", low_memory=False)
    return mem, changes, catalogue


def plot_N_curve(mem: pd.DataFrame, out: Path):
    N_t = mem.sum(axis=1)
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.plot(N_t.index, N_t.values, color="#1f4e79", lw=1.4)
    ax.axvline(pd.Timestamp("2023-12-31"), color="crimson", ls="--", lw=1.0,
               label="样本内截止 2023-12-31")
    ax.axvline(pd.Timestamp(OOS_END), color="darkorange", ls="--", lw=1.0,
               label="样本外截止 2025-07-31")
    ax.set_title("v6 池子规模随时间演化 N(t)")
    ax.set_ylabel("池子内 ETF 数量")
    ax.set_xlabel("周频调仓日 (W-FRI)")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", frameon=False)
    fig.savefig(out)
    plt.close(fig)


def plot_admissions_exits(changes: pd.DataFrame, mem: pd.DataFrame, out: Path):
    changes = changes.copy()
    changes["date"] = pd.to_datetime(changes["date"])
    changes["year"] = changes["date"].dt.year
    counts = changes.pivot_table(
        index="year", columns="event", values="code",
        aggfunc="count", fill_value=0,
    )
    # 保证事件列存在
    for col in ["enter", "exit_pctl", "exit_floor", "repr_switch"]:
        if col not in counts.columns:
            counts[col] = 0
    counts = counts[["enter", "exit_pctl", "exit_floor", "repr_switch"]]
    counts["exit_total"] = counts["exit_pctl"] + counts["exit_floor"]
    # 年末 N
    N_t = mem.sum(axis=1)
    year_end_N = N_t.groupby(N_t.index.year).last()

    fig, ax = plt.subplots(figsize=(9, 4.5))
    years = counts.index.astype(int)
    ax.bar(years - 0.15, counts["enter"], width=0.3, label="新增纳入", color="#2ca02c")
    ax.bar(years + 0.15, counts["exit_total"], width=0.3, label="退出（合计）", color="#c0392b")
    ax.bar(years + 0.15, counts["repr_switch"], width=0.3,
           bottom=counts["exit_total"], label="代表 ETF 切换", color="#f39c12")

    ax2 = ax.twinx()
    ax2.plot(year_end_N.index, year_end_N.values, marker="o",
             color="#1f4e79", lw=1.6, label="年末 N")
    ax2.set_ylabel("年末池子规模 N")

    ax.set_title("每年入池 / 退出 / 代表切换事件数")
    ax.set_xlabel("年份")
    ax.set_ylabel("事件数")
    ax.grid(alpha=0.25, axis="y")

    # 合并图例
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc="upper left", frameon=False)
    fig.savefig(out)
    plt.close(fig)


def plot_fund_type_pie(catalogue: pd.DataFrame, mem: pd.DataFrame, out: Path):
    admitted_codes = set(mem.columns[mem.any(axis=0)])
    cat = catalogue.copy()
    code_col = "code" if "code" in cat.columns else "order_book_id"
    cat["admitted"] = cat[code_col].isin(admitted_codes)
    # 找 fund_type 字段名
    ft_col = None
    for c in ["fund_type", "instrument_type", "fund_category"]:
        if c in cat.columns:
            ft_col = c
            break
    if ft_col is None:
        # 只画一个入池比例
        n_ever = cat["admitted"].sum() if "admitted" in cat.columns else 0
        n_all = len(cat)
        fig, ax = plt.subplots(figsize=(5, 4))
        ax.pie([n_ever, n_all - n_ever],
               labels=[f"入池 {n_ever}", f"未入池 {n_all - n_ever}"],
               autopct="%1.1f%%", colors=["#2ca02c", "#bdbdbd"])
        ax.set_title(f"目录 ETF 入池比例（共 {n_all}）")
        fig.savefig(out); plt.close(fig)
        return
    ft_counts = cat.groupby(ft_col).agg(
        cat_n=("admitted", "size"), admit_n=("admitted", "sum")
    ).sort_values("cat_n", ascending=False)
    ft_counts["admit_rate"] = ft_counts["admit_n"] / ft_counts["cat_n"].replace(0, np.nan)

    top5 = ft_counts.head(5)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6))
    axes[0].pie(top5["cat_n"], labels=top5.index, autopct="%1.1f%%",
                colors=["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"],
                startangle=90, pctdistance=0.75, labeldistance=1.05,
                textprops={"fontsize": 10})
    axes[0].set_title("原始目录中各类型 ETF 占比 (Top 5)")

    axes[1].bar(top5.index, top5["admit_rate"] * 100, color="#1f4e79")
    max_h = float((top5["admit_rate"] * 100).max())
    axes[1].set_ylim(0, max(max_h * 1.2, 5))
    for i, v in enumerate(top5["admit_rate"] * 100):
        axes[1].text(i, v + max_h * 0.02, f"{v:.1f}%",
                     ha="center", fontsize=10)
    axes[1].set_ylabel("累计入池比例（%）")
    axes[1].set_title("各类型 ETF 的累计入池率")
    axes[1].tick_params(axis="x", rotation=15)
    axes[1].grid(alpha=0.25, axis="y")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return ft_counts


# ============================================================
# 2. 因子筛选：从 pv_sweep 汇总 CSV 抓取相关数据
# ============================================================
def load_pv_sweep():
    df = pd.read_csv(DATA / "pv_sweep_xs_v6.csv")
    dedup = pd.read_csv(DATA / "pv_sweep_xs_v6_dedup.csv")
    return df, dedup


def plot_alpha_funnel(pv: pd.DataFrame, dedup: pd.DataFrame, out: Path):
    n_all = len(pv)
    n_gate = int(((pv["zstat"].abs() >= 2.0) & (pv["n_bars"] >= 100)).sum())
    n_dedup = len(dedup)
    stages = ["PV 因子池", "|zstat|≥2 & n≥100", "去相关（|ρ|≤0.5）后"]
    counts = [n_all, n_gate, n_dedup]

    fig, ax = plt.subplots(figsize=(7.5, 4))
    bars = ax.barh(stages, counts, color=["#7f8c8d", "#1f77b4", "#2ca02c"])
    for i, c in enumerate(counts):
        ax.text(c + 5, i, f"{c}", va="center", fontsize=11)
    ax.set_xlabel("因子数量")
    ax.set_title("Alpha 因子筛选漏斗")
    ax.invert_yaxis()
    ax.grid(alpha=0.25, axis="x")
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)
    return n_all, n_gate, n_dedup


def plot_top_alphas(pv: pd.DataFrame, out: Path):
    top = pv.reindex(pv["zstat"].abs().sort_values(ascending=False).index).head(15)
    fig, ax = plt.subplots(figsize=(9, 5))
    colors = ["#2ca02c" if z > 0 else "#c0392b" for z in top["zstat"]]
    ax.barh(top["factor"], top["zstat"], color=colors)
    ax.axvline(2.0, color="grey", ls="--", lw=0.8)
    ax.axvline(-2.0, color="grey", ls="--", lw=0.8)
    ax.set_xlabel("zstat (方向即因子极性)")
    ax.set_title("Top 15 单因子 IC 强度（按 |zstat| 排序）")
    ax.invert_yaxis()
    ax.grid(alpha=0.25, axis="x")
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


# ============================================================
# 3. Baseline 回测数据 + hysteresis 引擎重算
# ============================================================
CELLS = [("long", 0.05, "long_q05"),
         ("long", 0.10, "long_q10"),
         ("long", 0.20, "long_q20")]
BEST_EPS = {"long_q05": 0.30, "long_q10": 0.50, "long_q20": 0.20}  # 由 sweep 报告选出的 replace 最优


def load_shared():
    mem = pd.read_parquet(DATA / "universe_v6" / "membership.parquet")
    codes = list(mem.columns[mem.any(axis=0)])
    mem = mem[codes].astype(bool)
    fwd = pd.read_parquet(DATA / "panels_v6" / "fwd_1w.parquet")[codes]
    sigma = pd.read_parquet(DATA / "panels_v6" / "sigma_causal_26w.parquet")[codes]
    return dict(mem=mem, fwd=fwd, sigma=sigma, codes=codes)


def run_hysteresis_series(mode: str, q: float, epsilon: float,
                          shared: dict, cell: str) -> pd.Series:
    alpha = pd.read_parquet(DATA / "v6_static" / cell / "ensemble_alpha.parquet")
    W, N_t, K_t = H.build_hysteresis_weights(
        alpha, shared["sigma"], shared["mem"],
        q=q, mode=mode, epsilon=epsilon, rule="replace")
    res = E.run_book(W, shared["fwd"], cost_per_trade=COST, N_t=N_t, K_t=K_t)
    return res  # BookResult


def window_stats(net: pd.Series) -> dict:
    """样本内 / 样本外 / 全窗 各项指标。"""
    idx = net.index
    is_mask = idx <= IN_END
    oos_mask = (idx >= OOS_START) & (idx <= OOS_END)
    full_mask = idx <= OOS_END
    out = {}
    for name, mask in [("is", is_mask), ("oos", oos_mask), ("full", full_mask)]:
        s = net[mask]
        if len(s) < 2:
            out[name] = dict(sharpe=0, cagr=0, dd=0, ann_ret=0, ann_vol=0, n=len(s))
            continue
        ann_vol = float(s.std(ddof=1)) * np.sqrt(WPY)
        ann_ret = float(s.mean()) * WPY
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
        cum = 1.0 + s.cumsum()
        cummax = cum.cummax()
        dd = float(((cum - cummax) / cummax).min())
        n_years = max(len(s) / WPY, 1e-3)
        cagr = max(1.0 + float(s.sum()), 1e-9) ** (1.0 / n_years) - 1.0
        out[name] = dict(sharpe=sharpe, cagr=cagr, dd=dd, ann_ret=ann_ret,
                         ann_vol=ann_vol, n=len(s))
    return out


def load_baseline_bar(cell: str) -> pd.DataFrame:
    return pd.read_csv(DATA / "v6_static" / "cost_attribution" / f"{cell}_bar.csv",
                       index_col=0, parse_dates=[0])


def collect_book_data(shared: dict):
    """返回每个 cell 的 baseline+hysteresis 数据字典。"""
    results = {}
    for mode, q, cell in CELLS:
        bar = load_baseline_bar(cell)
        base_net = bar["net_ret"].astype(float)
        base_port = bar["port_ret"].astype(float)
        base_turn = bar["turnover"].astype(float)
        base_sel = bar["turn_selection"].astype(float)
        base_size = bar["turn_sizing"].astype(float)

        # 只保留 IS+OOS 窗口（<=OOS_END）
        mask = base_net.index <= OOS_END
        base_net = base_net[mask]
        base_port = base_port[mask]
        base_turn = base_turn[mask]
        base_sel = base_sel[mask]
        base_size = base_size[mask]

        # 加入 hysteresis 的再算
        eps = BEST_EPS[cell]
        res = run_hysteresis_series(mode, q, eps, shared, cell)
        h_net = res.net_ret.reindex(base_net.index).fillna(0.0)
        h_port = res.port_ret.reindex(base_net.index).fillna(0.0)
        h_turn = res.turnover.reindex(base_net.index).fillna(0.0)

        # selection / sizing 分解
        W = res.weights
        prev = W.shift(1).fillna(0.0)
        both = (W != 0.0) & (prev != 0.0)
        sel_mask = ~both
        dW = (W - prev).abs()
        h_sel = dW.where(sel_mask, 0.0).sum(axis=1).reindex(base_net.index).fillna(0.0)
        h_size = dW.where(both, 0.0).sum(axis=1).reindex(base_net.index).fillna(0.0)

        results[cell] = dict(
            base_net=base_net, base_port=base_port,
            base_turn=base_turn, base_sel=base_sel, base_size=base_size,
            h_net=h_net, h_port=h_port,
            h_turn=h_turn, h_sel=h_sel, h_size=h_size,
            eps=eps, mode=mode, q=q,
        )
    return results


# ============================================================
# 3.b v4pool baseline 参考对比
# ============================================================
V4POOL_SHARPE_CSV = (
    V6_ROOT.parent / "v4pool" / "xs_ic_pipeline" / "data" / "book_sharpe.csv"
)


def load_v4pool_static() -> dict:
    """从 v4pool xs_ic_pipeline 的 book_sharpe.csv 提取 static book 指标。
    v4pool 池子固定 15 只 ETF，K = 5，权重方案为 α-proportional，
    与 v6 baseline 不同的地方在于（1）池子只有 15 只，（2）权重不做 1/σ 反比。
    """
    df = pd.read_csv(V4POOL_SHARPE_CSV)
    row = df[df["book"] == "static"].iloc[0].to_dict()
    return {
        "full_sharpe": float(row["sharpe"]),
        "is_sharpe": float(row["in_sharpe"]),
        "oos_sharpe": float(row["out_sharpe"]),
        "max_dd": float(row["max_drawdown"]),
        "annual_vol": float(row["annual_vol"]),
        "avg_turnover": float(row["avg_turnover"]),
        "cost_burn": float(row["cost_burn"]),
    }


def plot_v4_vs_v6(v4: dict, stats: dict, out: Path):
    """按 IS/OOS/全窗 三窗对比 v4pool baseline 与 v6 三个 baseline 的净夏普。"""
    windows = ["is", "oos", "full"]
    win_zh = ["样本内", "样本外", "全窗"]
    labels = ["v4 池（15 只，K=5）", "v6 Top 5%", "v6 Top 10%", "v6 Top 20%"]

    def series(win_key: str) -> list[float]:
        return [
            {"is": v4["is_sharpe"], "oos": v4["oos_sharpe"],
             "full": v4["full_sharpe"]}[win_key],
            stats["long_q05"]["base"][win_key]["sharpe"],
            stats["long_q10"]["base"][win_key]["sharpe"],
            stats["long_q20"]["base"][win_key]["sharpe"],
        ]

    x = np.arange(len(labels))
    w = 0.25
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    colors = ["#7f8c8d", "#1f77b4", "#2ca02c"]
    for j, (wk, wz, col) in enumerate(zip(windows, win_zh, colors)):
        vals = series(wk)
        bars = ax.bar(x + (j - 1) * w, vals, width=w, color=col, label=wz)
        for xi, v in zip(x + (j - 1) * w, vals):
            ax.text(xi, v + 0.03, f"{v:.2f}", ha="center", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("净夏普")
    ax.set_title("池子扩容效应：v4 池 baseline vs v6 三个 baseline")
    ax.grid(alpha=0.25, axis="y")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


# ============================================================
# 3.c 按年 breakdown（用于 hysteresis 三 variant）
# ============================================================
def yearly_breakdown(net: pd.Series, turn: pd.Series | None = None) -> pd.DataFrame:
    """按自然年输出 收益 / Sharpe / 最大回撤 / 平均换手 / 有效周数。"""
    rows = []
    net = net.sort_index()
    for year, s in net.groupby(net.index.year):
        if len(s) < 2:
            continue
        ann_vol = float(s.std(ddof=1)) * np.sqrt(WPY)
        ann_ret = float(s.mean()) * WPY
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
        cum = 1.0 + s.cumsum()
        cummax = cum.cummax()
        dd = float(((cum - cummax) / cummax).min())
        year_ret = float(s.sum())
        turn_mean = float(turn.reindex(s.index).mean()) if turn is not None else np.nan
        rows.append({
            "year": int(year),
            "ret": year_ret,
            "ann_ret": ann_ret,
            "sharpe": sharpe,
            "ann_vol": ann_vol,
            "max_dd": dd,
            "turnover": turn_mean,
            "n_bars": int(len(s)),
        })
    return pd.DataFrame(rows).set_index("year")


# ============================================================
# 4. 绘图：净值 / 回撤 / 换手 / 指标对比
# ============================================================
def plot_nav_curves(data: dict, key: str, title: str, out: Path):
    fig, ax = plt.subplots(figsize=(9, 4.5))
    colors_base = {"long_q05": "#1f77b4", "long_q10": "#2ca02c", "long_q20": "#c0392b"}
    labels = {"long_q05": "Top 5%", "long_q10": "Top 10%", "long_q20": "Top 20%"}
    for cell in ["long_q05", "long_q10", "long_q20"]:
        s = data[cell][key]
        nav = 1.0 + s.cumsum()
        ax.plot(nav.index, nav.values, color=colors_base[cell], lw=1.4,
                label=labels[cell])
    ax.axvline(pd.Timestamp("2023-12-31"), color="grey", ls="--", lw=1.0)
    ax.text(pd.Timestamp("2023-12-31"), ax.get_ylim()[1], " OOS 起点",
            va="top", fontsize=9, color="grey")
    ax.set_title(title)
    ax.set_ylabel("净值（起始 = 1，含成本）")
    ax.set_xlabel("周频调仓日")
    ax.grid(alpha=0.3)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_dd_curves(data: dict, key: str, title: str, out: Path):
    fig, ax = plt.subplots(figsize=(9, 4.5))
    colors_base = {"long_q05": "#1f77b4", "long_q10": "#2ca02c", "long_q20": "#c0392b"}
    labels = {"long_q05": "Top 5%", "long_q10": "Top 10%", "long_q20": "Top 20%"}
    for cell in ["long_q05", "long_q10", "long_q20"]:
        s = data[cell][key]
        nav = 1.0 + s.cumsum()
        cummax = nav.cummax()
        dd = (nav - cummax) / cummax
        ax.fill_between(dd.index, dd.values, 0, color=colors_base[cell],
                        alpha=0.25)
        ax.plot(dd.index, dd.values, color=colors_base[cell], lw=1.0,
                label=labels[cell])
    ax.axvline(pd.Timestamp("2023-12-31"), color="grey", ls="--", lw=1.0)
    ax.set_title(title)
    ax.set_ylabel("回撤（相对历史高点）")
    ax.set_xlabel("周频调仓日")
    ax.grid(alpha=0.3)
    ax.legend(frameon=False, loc="lower left")
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_nav_compare(data: dict, cell: str, out: Path):
    d = data[cell]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    nav_b = 1.0 + d["base_net"].cumsum()
    nav_h = 1.0 + d["h_net"].cumsum()
    ax.plot(nav_b.index, nav_b.values, color="#7f8c8d", lw=1.4,
            label="baseline（每周重排）")
    ax.plot(nav_h.index, nav_h.values, color="#c0392b", lw=1.6,
            label=f"加入 hysteresis (ε={d['eps']:.2f})")
    ax.axvline(pd.Timestamp("2023-12-31"), color="grey", ls="--", lw=1.0)
    ax.text(pd.Timestamp("2023-12-31"), ax.get_ylim()[1], " OOS 起点",
            va="top", fontsize=9, color="grey")
    label_q = {"long_q05": "Top 5%", "long_q10": "Top 10%", "long_q20": "Top 20%"}[cell]
    ax.set_title(f"{label_q} 纯多头：加入 hysteresis 前后净值对比")
    ax.set_ylabel("净值（起始 = 1，含成本）")
    ax.set_xlabel("周频调仓日")
    ax.grid(alpha=0.3)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_dd_compare(data: dict, cell: str, out: Path):
    d = data[cell]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for net, color, label in [
        (d["base_net"], "#7f8c8d", "baseline"),
        (d["h_net"], "#c0392b", f"加入 hysteresis (ε={d['eps']:.2f})"),
    ]:
        nav = 1.0 + net.cumsum()
        cm = nav.cummax()
        dd = (nav - cm) / cm
        ax.fill_between(dd.index, dd.values, 0, color=color, alpha=0.18)
        ax.plot(dd.index, dd.values, color=color, lw=1.1, label=label)
    ax.axvline(pd.Timestamp("2023-12-31"), color="grey", ls="--", lw=1.0)
    label_q = {"long_q05": "Top 5%", "long_q10": "Top 10%", "long_q20": "Top 20%"}[cell]
    ax.set_title(f"{label_q} 纯多头：加入 hysteresis 前后回撤对比")
    ax.set_ylabel("回撤")
    ax.set_xlabel("周频调仓日")
    ax.grid(alpha=0.3)
    ax.legend(frameon=False, loc="lower left")
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_turnover_bar(data: dict, out: Path):
    cells = ["long_q05", "long_q10", "long_q20"]
    label_q = ["Top 5%", "Top 10%", "Top 20%"]
    base_sel = [data[c]["base_sel"].mean() for c in cells]
    h_sel = [data[c]["h_sel"].mean() for c in cells]
    base_size = [data[c]["base_size"].mean() for c in cells]
    h_size = [data[c]["h_size"].mean() for c in cells]

    x = np.arange(len(cells))
    fig, ax = plt.subplots(figsize=(8, 4.6))
    w = 0.35
    ax.bar(x - w/2, base_sel, width=w, color="#7f8c8d", label="baseline · 选股换手")
    ax.bar(x - w/2, base_size, width=w, bottom=base_sel, color="#bdc3c7",
           label="baseline · 权重调整")
    ax.bar(x + w/2, h_sel, width=w, color="#c0392b", label="hysteresis · 选股换手")
    ax.bar(x + w/2, h_size, width=w, bottom=h_sel, color="#e74c3c", alpha=0.6,
           label="hysteresis · 权重调整")
    ax.set_xticks(x); ax.set_xticklabels(label_q)
    ax.set_ylabel("平均每周单边换手")
    ax.set_title("加入 hysteresis 前后：每周换手结构对比")
    ax.grid(alpha=0.25, axis="y")
    ax.legend(frameon=False, fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_hyst_overview(data: dict, out: Path):
    """三个 hysteresis variant 的 NAV + 回撤放到一张图 (双子图)。"""
    fig, (ax_nav, ax_dd) = plt.subplots(
        2, 1, figsize=(9.5, 6.4), sharex=True,
        gridspec_kw={"height_ratios": [1.5, 1.0]},
    )
    colors = {"long_q05": "#1f77b4", "long_q10": "#2ca02c", "long_q20": "#c0392b"}
    labels = {
        "long_q05": f"Top 5%  (ε={data['long_q05']['eps']:.2f})",
        "long_q10": f"Top 10% (ε={data['long_q10']['eps']:.2f})",
        "long_q20": f"Top 20% (ε={data['long_q20']['eps']:.2f})",
    }
    for cell in ["long_q05", "long_q10", "long_q20"]:
        s = data[cell]["h_net"]
        nav = 1.0 + s.cumsum()
        cm = nav.cummax()
        dd = (nav - cm) / cm
        ax_nav.plot(nav.index, nav.values, color=colors[cell], lw=1.5,
                    label=labels[cell])
        ax_dd.fill_between(dd.index, dd.values, 0, color=colors[cell],
                           alpha=0.20)
        ax_dd.plot(dd.index, dd.values, color=colors[cell], lw=1.0)

    for ax in (ax_nav, ax_dd):
        ax.axvline(pd.Timestamp("2023-12-31"), color="grey", ls="--", lw=1.0)
        ax.grid(alpha=0.3)
    ax_nav.set_ylabel("净值（起始 = 1，含成本）")
    ax_nav.set_title("加入 hysteresis 的三个方案：净值与回撤汇总对比")
    ax_nav.legend(frameon=False, loc="upper left")
    ax_dd.set_ylabel("回撤")
    ax_dd.set_xlabel("周频调仓日")
    # OOS 起点标注
    ax_nav.text(pd.Timestamp("2023-12-31"), ax_nav.get_ylim()[1],
                " OOS 起点", va="top", fontsize=9, color="grey")
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_metrics_compare(stats: dict, out: Path):
    cells = ["long_q05", "long_q10", "long_q20"]
    label_q = ["Top 5%", "Top 10%", "Top 20%"]

    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2))

    # Sharpe (full)
    b = [stats[c]["base"]["full"]["sharpe"] for c in cells]
    h = [stats[c]["hyst"]["full"]["sharpe"] for c in cells]
    x = np.arange(len(cells)); w = 0.35
    axes[0].bar(x - w/2, b, width=w, color="#7f8c8d", label="baseline")
    axes[0].bar(x + w/2, h, width=w, color="#c0392b", label="hysteresis")
    axes[0].set_title("全窗净夏普")
    axes[0].set_xticks(x); axes[0].set_xticklabels(label_q)
    axes[0].grid(alpha=0.25, axis="y")
    axes[0].legend(frameon=False)
    for i, (bb, hh) in enumerate(zip(b, h)):
        axes[0].text(i - w/2, bb + 0.02, f"{bb:.2f}", ha="center", fontsize=9)
        axes[0].text(i + w/2, hh + 0.02, f"{hh:.2f}", ha="center", fontsize=9)

    # CAGR (full, %)
    b = [stats[c]["base"]["full"]["cagr"] * 100 for c in cells]
    h = [stats[c]["hyst"]["full"]["cagr"] * 100 for c in cells]
    axes[1].bar(x - w/2, b, width=w, color="#7f8c8d")
    axes[1].bar(x + w/2, h, width=w, color="#c0392b")
    axes[1].set_title("全窗 CAGR (%)")
    axes[1].set_xticks(x); axes[1].set_xticklabels(label_q)
    axes[1].grid(alpha=0.25, axis="y")
    for i, (bb, hh) in enumerate(zip(b, h)):
        axes[1].text(i - w/2, bb + 0.05, f"{bb:.2f}%", ha="center", fontsize=9)
        axes[1].text(i + w/2, hh + 0.05, f"{hh:.2f}%", ha="center", fontsize=9)

    # max DD (full, %)
    b = [stats[c]["base"]["full"]["dd"] * 100 for c in cells]
    h = [stats[c]["hyst"]["full"]["dd"] * 100 for c in cells]
    axes[2].bar(x - w/2, b, width=w, color="#7f8c8d")
    axes[2].bar(x + w/2, h, width=w, color="#c0392b")
    axes[2].set_title("全窗最大回撤 (%)")
    axes[2].set_xticks(x); axes[2].set_xticklabels(label_q)
    axes[2].grid(alpha=0.25, axis="y")
    for i, (bb, hh) in enumerate(zip(b, h)):
        axes[2].text(i - w/2, bb - 0.15, f"{bb:.2f}%", ha="center", fontsize=9)
        axes[2].text(i + w/2, hh - 0.15, f"{hh:.2f}%", ha="center", fontsize=9)

    fig.suptitle("三个 Top-q 纯多头 baseline：加入 hysteresis 前后关键指标对比", y=1.03)
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_cost_share(data: dict, stats: dict, out: Path):
    cells = ["long_q05", "long_q10", "long_q20"]
    label_q = ["Top 5%", "Top 10%", "Top 20%"]
    base_cost = []
    h_cost = []
    for c in cells:
        base_cost.append(float(data[c]["base_turn"].mean()) * COST * WPY * 1e4)
        h_cost.append(float(data[c]["h_turn"].mean()) * COST * WPY * 1e4)
    fig, ax = plt.subplots(figsize=(8, 4.4))
    x = np.arange(len(cells)); w = 0.35
    ax.bar(x - w/2, base_cost, width=w, color="#7f8c8d", label="baseline")
    ax.bar(x + w/2, h_cost, width=w, color="#c0392b", label="hysteresis")
    for i, (b, h) in enumerate(zip(base_cost, h_cost)):
        ax.text(i - w/2, b + 2, f"{b:.0f}", ha="center", fontsize=9)
        ax.text(i + w/2, h + 2, f"{h:.0f}", ha="center", fontsize=9)
    ax.set_xticks(x); ax.set_xticklabels(label_q)
    ax.set_ylabel("交易成本（bps/年）")
    ax.set_title("成本消耗对比：hysteresis 大幅压低成本")
    ax.grid(alpha=0.25, axis="y")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


# ============================================================
# 5. 主流程
# ============================================================
def main():
    print("[1/4] loading universe...")
    mem, changes, catalogue = load_universe_panels()
    plot_N_curve(mem, FIG_DIR / "fig01_universe_N.png")
    plot_admissions_exits(changes, mem, FIG_DIR / "fig02_admissions.png")
    ft_counts = plot_fund_type_pie(catalogue, mem, FIG_DIR / "fig03_fundtype.png")
    print("    universe figures written.")

    print("[2/4] loading factor sweep...")
    pv, dedup = load_pv_sweep()
    n_all, n_gate, n_dedup = plot_alpha_funnel(pv, dedup, FIG_DIR / "fig04_funnel.png")
    plot_top_alphas(pv, FIG_DIR / "fig05_topalpha.png")
    print(f"    factor funnel: {n_all} → {n_gate} → {n_dedup}")

    print("[3/4] rerunning hysteresis engine...")
    shared = load_shared()
    data = collect_book_data(shared)

    stats = {}
    for cell in ["long_q05", "long_q10", "long_q20"]:
        stats[cell] = {
            "base": window_stats(data[cell]["base_net"]),
            "hyst": window_stats(data[cell]["h_net"]),
        }

    # 三个 baseline 的 NAV / 回撤（无 hysteresis）
    plot_nav_curves(data, "base_net",
                    "无 hysteresis：三个 Top-q 纯多头 baseline 净值",
                    FIG_DIR / "fig06_nav_baseline.png")
    plot_dd_curves(data, "base_net",
                   "无 hysteresis：三个 Top-q 纯多头 baseline 回撤",
                   FIG_DIR / "fig07_dd_baseline.png")

    # 每个 cell 的对比
    plot_nav_compare(data, "long_q05", FIG_DIR / "fig08_nav_q05.png")
    plot_nav_compare(data, "long_q10", FIG_DIR / "fig09_nav_q10.png")
    plot_nav_compare(data, "long_q20", FIG_DIR / "fig10_nav_q20.png")
    plot_dd_compare(data, "long_q05", FIG_DIR / "fig11_dd_q05.png")
    plot_dd_compare(data, "long_q10", FIG_DIR / "fig12_dd_q10.png")
    plot_dd_compare(data, "long_q20", FIG_DIR / "fig13_dd_q20.png")

    # 换手 / 成本 / 指标
    plot_turnover_bar(data, FIG_DIR / "fig14_turnover.png")
    plot_cost_share(data, stats, FIG_DIR / "fig15_cost.png")
    plot_metrics_compare(stats, FIG_DIR / "fig16_metrics.png")

    # v4 池对比 & hysteresis 三 variant 汇总
    v4 = load_v4pool_static()
    plot_v4_vs_v6(v4, stats, FIG_DIR / "fig17_v4_vs_v6.png")
    plot_hyst_overview(data, FIG_DIR / "fig18_hyst_overview.png")
    print("    all backtest figures written.")

    # 保存指标 JSON 供 build_doc 使用
    import json
    summary = {
        "n_all": int(n_all), "n_gate": int(n_gate), "n_dedup": int(n_dedup),
        "v4pool": v4,
        "cells": {},
    }
    for cell in ["long_q05", "long_q10", "long_q20"]:
        d = data[cell]
        # 按年 breakdown（hysteresis 版本）
        yb_h = yearly_breakdown(d["h_net"], d["h_turn"])
        yb_b = yearly_breakdown(d["base_net"], d["base_turn"])
        summary["cells"][cell] = {
            "eps": d["eps"],
            "base": {
                "is": stats[cell]["base"]["is"],
                "oos": stats[cell]["base"]["oos"],
                "full": stats[cell]["base"]["full"],
                "cost_bps_yr": float(d["base_turn"].mean() * COST * WPY * 1e4),
                "turnover": float(d["base_turn"].mean()),
                "sel_turn": float(d["base_sel"].mean()),
                "size_turn": float(d["base_size"].mean()),
                "yearly": yb_b.reset_index().to_dict(orient="records"),
            },
            "hyst": {
                "is": stats[cell]["hyst"]["is"],
                "oos": stats[cell]["hyst"]["oos"],
                "full": stats[cell]["hyst"]["full"],
                "cost_bps_yr": float(d["h_turn"].mean() * COST * WPY * 1e4),
                "turnover": float(d["h_turn"].mean()),
                "sel_turn": float(d["h_sel"].mean()),
                "size_turn": float(d["h_size"].mean()),
                "yearly": yb_h.reset_index().to_dict(orient="records"),
            },
        }
    with open(HERE / "_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=float)
    print("[4/4] wrote _summary.json")


if __name__ == "__main__":
    main()
