"""
run_stress_test.py
==================
执行 STRESS_TEST_PREREG.md 中约定的 v6 hold-out 压力测试。

严格按 pre-reg 约束：
- §2 只跑 finalist + 3 anchor（不跑 q=0.10 或其他扫格）
- §3 只算 9 个 metric
- §5 只出 5 张图/表
- §4 阈值判定
- §5 明确不看：逐块 pnl、逐名字、分周回撤路径、α 名字、逐周组权重

输出：
  ./stress/_stress_summary.json
  ./stress/verdict.txt
  ./figures/fig_stress_*.png
"""
from __future__ import annotations

import json
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
STRESS_DIR = HERE / "stress"
STRESS_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)

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
OOS_START = pd.Timestamp("2024-01-01")
OOS_END = pd.Timestamp("2025-07-31")
STRESS_START = pd.Timestamp("2025-08-01")

# 之前 OOS shot 报告里的 apples-to-apples IS Sharpe（作为 decay 参照）
IS_SHARPE_ANCHOR = {
    "two_layer_q20_e30":     1.577,
    "layer1_invvol_lw_erc":  1.570,
    "T2_bond_invvol":        1.462,
    "two_layer_baseline":    1.511,
}

BOOKS = {
    "two_layer_q20_e30":
        DATA / "block_two_layer_v6" / "q20_eps030" / "net_ret.csv",
    "layer1_invvol_lw_erc":
        DATA / "block_risk_budget_v6_no_trend" / "invvol_lw_erc" / "net_ret.csv",
    "T2_bond_invvol":
        DATA / "bond_attribution_v6" / "T2_bond_invvol" / "net_ret.csv",
    "two_layer_baseline":
        DATA / "block_two_layer_v6" / "baseline" / "net_ret.csv",
}

LABEL_ZH = {
    "two_layer_q20_e30":     "双层 q=0.20 ε=0.30 (finalist)",
    "layer1_invvol_lw_erc":  "Layer-1 canonical",
    "T2_bond_invvol":        "T2 债券 inv-vol",
    "two_layer_baseline":    "双层 α off",
}
COLORS = {
    "two_layer_q20_e30":     "#c0392b",
    "layer1_invvol_lw_erc":  "#1f77b4",
    "T2_bond_invvol":        "#2ca02c",
    "two_layer_baseline":    "#7f8c8d",
}

# w_group 用于组权重（组权重是允许查看的"窗口平均"，见 pre-reg §5）
WGROUP = DATA / "block_two_layer_v6" / "q20_eps030" / "w_group.parquet"
GROUP_ORDER = ["equity", "bond_rates", "bond_credit", "commodity"]
GROUP_ZH = {"equity": "权益", "bond_rates": "利率债",
             "bond_credit": "信用债", "commodity": "商品"}
GROUP_COLORS = {"equity": "#c0392b", "bond_rates": "#1f77b4",
                 "bond_credit": "#3498db", "commodity": "#f39c12"}
POLICY = {"equity": 0.55, "bond_rates": 0.20,
          "bond_credit": 0.10, "commodity": 0.15}

# pre-reg §4 阈值
THRESH = {
    "sharpe":   {"pass": 0.50,  "edge_lo": 0.00,  "fail": 0.00},
    "cagr":     {"pass": 0.00,  "edge_lo": -0.02, "fail": -0.02},
    "max_dd":   {"pass": -0.04, "edge_lo": -0.06, "fail": -0.06},
    "calmar":   {"pass": 0.30,  "edge_lo": 0.00,  "fail": 0.00},
    "decay":    {"pass": 0.30,  "edge_lo": 0.10,  "fail": 0.10},
}


# ---------------------------- metrics ---------------------------------- #
def load_net(path: Path) -> pd.Series:
    df = pd.read_csv(path, parse_dates=[0], index_col=0)
    return df.iloc[:, 0].astype(float).sort_index()


def window_stats(net: pd.Series) -> dict:
    n = int(len(net))
    if n < 2:
        return {"sharpe": None, "cagr": None, "dd": None, "ann_vol": None,
                "ann_ret": None, "cumret": None, "calmar": None, "n_bars": n}
    ann_vol = float(net.std(ddof=1)) * np.sqrt(WPY)
    ann_ret = float(net.mean()) * WPY
    sharpe = ann_ret / ann_vol if ann_vol > 0 else None
    cumret = float(net.sum())
    n_years = max(n / WPY, 1e-3)
    cagr = max(1.0 + cumret, 1e-9) ** (1.0 / n_years) - 1.0
    nav = 1.0 + net.cumsum()
    dd = float(((nav - nav.cummax()) / nav.cummax()).min())
    calmar = (cagr / abs(dd)) if abs(dd) > 1e-12 else None
    return {"sharpe": sharpe, "cagr": cagr, "dd": dd, "ann_vol": ann_vol,
            "ann_ret": ann_ret, "cumret": cumret, "calmar": calmar,
            "n_bars": n}


# ---------------------------- pass/fail -------------------------------- #
def classify(value, key) -> str:
    """Return 'pass' / 'edge' / 'fail' for a metric value per pre-reg §4."""
    if value is None:
        return "fail"
    th = THRESH[key]
    if key in ("sharpe", "cagr", "calmar", "decay"):
        # bigger is better
        if value >= th["pass"]:
            return "pass"
        if value >= th["edge_lo"]:
            return "edge"
        return "fail"
    if key == "max_dd":
        # closer to 0 is better; th values are negative
        if value >= th["pass"]:
            return "pass"
        if value >= th["edge_lo"]:
            return "edge"
        return "fail"
    return "fail"


def overall_verdict(m_dict: dict[str, str]) -> str:
    if any(v == "fail" for v in m_dict.values()):
        return "FAIL"
    if any(v == "edge" for v in m_dict.values()):
        return "EDGE"
    return "PASS"


# ---------------------------- figures ---------------------------------- #
def plot_stress_nav(nets: dict[str, pd.Series], stress_start: pd.Timestamp,
                     last_bar: pd.Timestamp, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(9.6, 4.4))
    for name, s in nets.items():
        s = s.loc[(s.index >= stress_start) & (s.index <= last_bar)]
        nav = 1.0 + s.cumsum()  # rebase from stress-window start
        ax.plot(nav.index, nav.values, color=COLORS[name], lw=1.6,
                label=LABEL_ZH[name])
    ax.axhline(1.0, color="black", lw=0.6, alpha=0.5)
    ax.set_ylabel("窗口内累计净值（起点 = 1）")
    ax.set_xlabel("周频调仓日")
    ax.set_title(f"压力窗口 NAV：{stress_start.date()} → {last_bar.date()}")
    ax.grid(alpha=0.3)
    ax.legend(frameon=False, fontsize=9, loc="lower left")
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_stress_dd(nets: dict[str, pd.Series], stress_start: pd.Timestamp,
                    last_bar: pd.Timestamp, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(9.6, 4.4))
    for name, s in nets.items():
        s = s.loc[(s.index >= stress_start) & (s.index <= last_bar)]
        nav = 1.0 + s.cumsum()
        dd = (nav - nav.cummax()) / nav.cummax()
        ax.fill_between(dd.index, dd.values, 0,
                        color=COLORS[name], alpha=0.18)
        ax.plot(dd.index, dd.values, color=COLORS[name], lw=1.1,
                label=LABEL_ZH[name])
    ax.set_ylabel("窗口内回撤")
    ax.set_xlabel("周频调仓日")
    ax.set_title(f"压力窗口回撤：{stress_start.date()} → {last_bar.date()}")
    ax.grid(alpha=0.3)
    ax.legend(frameon=False, fontsize=9, loc="lower left")
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_stress_wgroup(w: pd.DataFrame, stress_start: pd.Timestamp,
                        last_bar: pd.Timestamp, out: Path) -> None:
    """允许：窗口平均组权重条形图（pre-reg §5.4）。"""
    w_stress = w.loc[(w.index >= stress_start) & (w.index <= last_bar)]
    w_stress = w_stress[w_stress.sum(axis=1) > 1e-3]
    means_stress = w_stress.mean() * 100
    w_oos = w.loc[(w.index >= OOS_START) & (w.index <= OOS_END)]
    w_oos = w_oos[w_oos.sum(axis=1) > 1e-3]
    means_oos = w_oos.mean() * 100
    policy = pd.Series({g: POLICY[g] * 100 for g in GROUP_ORDER})

    xs = np.arange(len(GROUP_ORDER))
    w_bar = 0.28
    fig, ax = plt.subplots(figsize=(9.5, 4.5))
    ax.bar(xs - w_bar, [policy[g] for g in GROUP_ORDER],
           width=w_bar, color="#7f8c8d", label="政策风险贡献目标")
    ax.bar(xs, [means_oos[g] for g in GROUP_ORDER],
           width=w_bar, color="#1f77b4", label="OOS 平均资本权重")
    ax.bar(xs + w_bar, [means_stress[g] for g in GROUP_ORDER],
           width=w_bar, color="#c0392b", label="Stress 平均资本权重")
    for i, g in enumerate(GROUP_ORDER):
        ax.text(i - w_bar, policy[g] + 1, f"{policy[g]:.0f}%",
                ha="center", fontsize=9)
        ax.text(i, means_oos[g] + 1, f"{means_oos[g]:.1f}%",
                ha="center", fontsize=9)
        ax.text(i + w_bar, means_stress[g] + 1, f"{means_stress[g]:.1f}%",
                ha="center", fontsize=9)
    ax.set_xticks(xs)
    ax.set_xticklabels([GROUP_ZH[g] for g in GROUP_ORDER])
    ax.set_ylabel("百分比 (%)")
    ax.set_title("Stress 窗口平均组权重 vs OOS vs 政策目标（q=0.20 ε=0.30）")
    ax.grid(alpha=0.25, axis="y")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


def plot_decay_bars(decays: dict[str, float], out: Path) -> None:
    xs = np.arange(len(decays))
    fig, ax = plt.subplots(figsize=(9.0, 4.2))
    vals = [decays[n] for n in decays]
    names = list(decays.keys())
    colors = [COLORS[n] for n in names]
    ax.bar(xs, vals, color=colors, edgecolor="white")
    for i, v in enumerate(vals):
        ax.text(i, v + 0.03 * max(abs(v), 0.1), f"{v:+.2f}",
                ha="center", fontsize=9)
    ax.axhline(0.30, color="green", ls="--", lw=1.0, label="通过阈值 0.30")
    ax.axhline(0.10, color="orange", ls="--", lw=1.0, label="边缘阈值 0.10")
    ax.axhline(0.0, color="black", lw=0.6, alpha=0.4)
    ax.set_xticks(xs)
    ax.set_xticklabels([LABEL_ZH[n] for n in names], rotation=15,
                        ha="right", fontsize=9)
    ax.set_ylabel("Sharpe decay = Sharpe_stress / Sharpe_IS")
    ax.set_title("Sharpe 保留率：Stress 窗口 vs IS anchor")
    ax.grid(alpha=0.25, axis="y")
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    fig.tight_layout()
    fig.savefig(out); plt.close(fig)


# ---------------------------- main ------------------------------------- #
def main() -> None:
    print("[1/4] loading nets...")
    nets = {name: load_net(p) for name, p in BOOKS.items()}
    last_bar = min(s.index.max() for s in nets.values())
    print(f"    stress window = [{STRESS_START.date()}, {last_bar.date()}]")

    # ---- window metrics ----
    print("[2/4] computing metrics...")
    results = {}
    for name, s in nets.items():
        oos = s.loc[(s.index >= OOS_START) & (s.index <= OOS_END)]
        stress = s.loc[(s.index >= STRESS_START) & (s.index <= last_bar)]
        oos_m = window_stats(oos)
        st_m = window_stats(stress)
        is_anchor = IS_SHARPE_ANCHOR[name]
        decay = (st_m["sharpe"] / is_anchor) if (st_m["sharpe"] is not None
                                                  and abs(is_anchor) > 1e-9) else None
        st_m["decay"] = decay
        results[name] = {"OOS": oos_m, "stress": st_m,
                          "is_sharpe_anchor": is_anchor}

    # ---- verdict (只对 finalist 判定) ----
    print("[3/4] applying thresholds...")
    fin = results["two_layer_q20_e30"]["stress"]
    per_metric = {
        "sharpe": classify(fin["sharpe"], "sharpe"),
        "cagr":   classify(fin["cagr"],   "cagr"),
        "max_dd": classify(fin["dd"],     "max_dd"),
        "calmar": classify(fin["calmar"], "calmar"),
        "decay":  classify(fin["decay"],  "decay"),
    }
    verdict = overall_verdict(per_metric)
    print(f"    per-metric: {per_metric}")
    print(f"    OVERALL VERDICT: {verdict}")

    # ---- 允许的 5 张图/表 ----
    print("[4/4] making figures...")
    plot_stress_nav(nets, STRESS_START, last_bar,
                     FIG_DIR / "fig_stress01_nav.png")
    plot_stress_dd(nets, STRESS_START, last_bar,
                    FIG_DIR / "fig_stress02_dd.png")
    w = pd.read_parquet(WGROUP)
    plot_stress_wgroup(w, STRESS_START, last_bar,
                        FIG_DIR / "fig_stress03_wgroup.png")
    decays = {name: results[name]["stress"]["decay"] for name in BOOKS}
    plot_decay_bars(decays, FIG_DIR / "fig_stress04_decay.png")

    # ---- persist ----
    summary = {
        "stress_window": {
            "start": str(STRESS_START.date()),
            "end":   str(last_bar.date()),
            "n_bars": int(len(nets["two_layer_q20_e30"].loc[
                (nets["two_layer_q20_e30"].index >= STRESS_START)
                & (nets["two_layer_q20_e30"].index <= last_bar)])),
        },
        "is_sharpe_anchors": IS_SHARPE_ANCHOR,
        "results": results,
        "per_metric_verdict": per_metric,
        "overall_verdict": verdict,
        "labels": LABEL_ZH,
    }
    (STRESS_DIR / "_stress_summary.json").write_text(
        json.dumps(summary, indent=2, default=float))
    (STRESS_DIR / "verdict.txt").write_text(
        f"OVERALL: {verdict}\n\n" +
        "per metric:\n" +
        "\n".join(f"  {k}: {v}" for k, v in per_metric.items()) + "\n" +
        f"\nsharpe = {fin['sharpe']:+.3f}\n"
        f"cagr   = {fin['cagr']*100:+.2f}%\n"
        f"max_dd = {fin['dd']*100:+.2f}%\n"
        f"calmar = {fin['calmar']:+.2f}\n"
        f"decay  = {fin['decay']:+.2f}\n"
    )
    print("\n=== SUMMARY (two_layer_q20_e30 stress window) ===")
    print(f"  Sharpe = {fin['sharpe']:+.3f}   ({per_metric['sharpe']})")
    print(f"  CAGR   = {fin['cagr']*100:+.2f}%  ({per_metric['cagr']})")
    print(f"  MaxDD  = {fin['dd']*100:+.2f}%  ({per_metric['max_dd']})")
    print(f"  Calmar = {fin['calmar']:+.2f}   ({per_metric['calmar']})")
    print(f"  Decay  = {fin['decay']:+.2f}   ({per_metric['decay']})")
    print(f"\n>>> OVERALL VERDICT: {verdict} <<<")


if __name__ == "__main__":
    main()
