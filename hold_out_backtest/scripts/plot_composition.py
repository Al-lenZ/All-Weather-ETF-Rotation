"""
v6/hold_out_backtest/scripts/plot_composition.py
================================================
Stacked-area plot of actual portfolio composition (dollar weights, not
risk contributions) over the hold-out window 2025-08-01 → 2026-08-04.

Three vertically stacked panels:
  1. Pre-leverage weights  (% of invested notional; Σ ≤ 1, remainder = cash)
  2. Post-leverage weights, cap=2 cell  (% of NAV; stack may exceed 100 %)
  3. Post-leverage weights, cap=5 cell  (% of NAV)

Groups follow BLOCK_GROUPS from block_composite_v6:
    equity      = broad_cn + sector_cn + cross_border_dm + cross_border_hk
    bond_rates
    bond_credit
    commodity   = metals + commodity_other

Also writes a CSV of the per-bar shares for each panel.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[2] / "leverage"))
sys.path.insert(0, str(_HERE.parents[2] / "common"))
sys.path.insert(0, str(_HERE.parents[3]))

import block_composite_v6 as BC        # noqa: E402
import leverage_engine as LE           # noqa: E402
import rb_variants as RV               # noqa: E402


HOLDOUT_START = pd.Timestamp("2025-08-01")
HOLDOUT_END   = pd.Timestamp("2026-08-04")
STRESS_END    = pd.Timestamp("2026-07-17")

REPORTS_DIR = _HERE.parents[1] / "reports"
FIG_PATH    = REPORTS_DIR / "figures" / "composition_hold_out.png"
CSV_PATH    = REPORTS_DIR / "hold_out_composition.csv"

GROUP_ORDER = ("equity", "bond_rates", "bond_credit", "commodity")
GROUP_COLOR = {
    "equity":      "#1f77b4",
    "bond_rates":  "#2ca02c",
    "bond_credit": "#8c564b",
    "commodity":   "#ff7f0e",
}
CASH_COLOR = "#7f7f7f"

CELL_CONFIGS = {
    "cap2": dict(sigma_star=0.032, cap=2.0),
    "cap5": dict(sigma_star=0.064, cap=5.0),
}


def _ticker_to_group(block_tag: pd.Series) -> dict[str, str]:
    """Map each ticker → asset-class group per BLOCK_GROUPS."""
    out: dict[str, str] = {}
    for grp, blocks in BC.BLOCK_GROUPS.items():
        for tkr, tag in block_tag.items():
            if tag in blocks:
                out[tkr] = grp
    return out


def _group_shares(W: pd.DataFrame, tkr_group: dict[str, str]) -> pd.DataFrame:
    """Aggregate name-level weights into GROUP_ORDER columns."""
    cols = {g: [c for c in W.columns if tkr_group.get(c) == g] for g in GROUP_ORDER}
    return pd.concat(
        {g: (W[cols[g]].sum(axis=1) if cols[g] else pd.Series(0.0, index=W.index))
         for g in GROUP_ORDER},
        axis=1,
    )


def _stack_panel(ax, shares: pd.DataFrame, cash: pd.Series, title: str,
                 y_is_pct_of_nav: bool) -> None:
    """One stacked-area subplot with a cash overlay."""
    xs = shares.index
    stacks = [shares[g].values * 100.0 for g in GROUP_ORDER]
    ax.stackplot(xs, *stacks,
                 labels=list(GROUP_ORDER),
                 colors=[GROUP_COLOR[g] for g in GROUP_ORDER],
                 alpha=0.90)

    cash_pct = cash.reindex(xs).values * 100.0
    ax.plot(xs, cash_pct, color=CASH_COLOR, linewidth=1.5,
            linestyle="--", label="cash (net)")

    if y_is_pct_of_nav:
        ax.axhline(100.0, color="black", linewidth=0.7, alpha=0.5)
    ax.axhline(0.0, color="black", linewidth=0.7, alpha=0.5)
    ax.axvline(STRESS_END, color="grey", linestyle=":", linewidth=1)

    ax.set_title(title, fontsize=10)
    ax.set_ylabel("% of " + ("NAV" if y_is_pct_of_nav else "invested"))
    ax.grid(alpha=0.3)


def _build() -> dict:
    """Load shared bundle, build finalist book, run both leverage cells."""
    print("[composition] loading shared bundle ...")
    shared = BC.load_shared()
    book = RV.build_book(shared, rb="base", use_reps=True)
    tkr_group = _ticker_to_group(shared["block_tag"])

    results = {}
    for cid, cfg in CELL_CONFIGS.items():
        print(f"[composition] running leverage cell {cid} ...")
        r = LE.apply_book_vol_target(
            book,
            sigma_star=cfg["sigma_star"], cap=cfg["cap"],
            funding_curve="dr007", cash_carry_curve="dr007",
            apply_leverage=True, apply_cash_carry=True,
            L_mode="vol_target",
        )
        results[cid] = r

    return {"shared": shared, "book": book, "tkr_group": tkr_group,
            "results": results}


def main() -> None:
    ctx = _build()
    tkr_group = ctx["tkr_group"]
    book = ctx["book"]

    # ---- pre-leverage (Σ ≤ 1, remainder = cash) ------------------------ #
    W_name = book["W_name"]
    W_name_ho = W_name[(W_name.index >= HOLDOUT_START) & (W_name.index <= HOLDOUT_END)]
    pre_shares = _group_shares(W_name_ho, tkr_group)
    pre_cash   = (1.0 - W_name_ho.sum(axis=1)).clip(lower=0.0)

    # ---- post-leverage per cell --------------------------------------- #
    post = {}
    for cid, r in ctx["results"].items():
        W_lev = r.W_lev
        W_ho  = W_lev[(W_lev.index >= HOLDOUT_START) & (W_lev.index <= HOLDOUT_END)]
        shares = _group_shares(W_ho, tkr_group)
        L_ho   = r.L_t.reindex(W_ho.index)
        # Net cash (may go negative under leverage). We define
        #   net_cash = 1 - Σ W_lev  (i.e. cash share of NAV, negative when
        #   the book is a net borrower).
        net_cash = 1.0 - W_ho.sum(axis=1)
        post[cid] = {"shares": shares, "cash": net_cash, "L": L_ho}

    # ---- plot ---------------------------------------------------------- #
    FIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(3, 1, figsize=(11, 10.5), sharex=True,
                             gridspec_kw={"hspace": 0.18})

    _stack_panel(axes[0], pre_shares, pre_cash,
                 "Pre-leverage composition — invested notional shares (base RB + reps)",
                 y_is_pct_of_nav=False)
    axes[0].legend(loc="upper left", ncol=5, fontsize=8, framealpha=0.85)

    for ax_i, cid in enumerate(("cap2", "cap5"), start=1):
        cfg = CELL_CONFIGS[cid]
        mL = float(post[cid]["L"].mean())
        pL = float(post[cid]["L"].quantile(0.95))
        _stack_panel(
            axes[ax_i], post[cid]["shares"], post[cid]["cash"],
            f"Post-leverage — {cid} (σ*={cfg['sigma_star']*100:.1f} %, cap={cfg['cap']:.0f})"
            f"   mean L={mL:.2f}, p95 L={pL:.2f}",
            y_is_pct_of_nav=True,
        )
        if ax_i == 1:
            axes[ax_i].legend(loc="upper left", ncol=5, fontsize=8, framealpha=0.85)

    axes[-1].set_xlabel("date (weekly W-FRI bars)")
    axes[-1].xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    for lbl in axes[-1].get_xticklabels():
        lbl.set_rotation(30); lbl.set_ha("right")

    axes[0].text(STRESS_END, axes[0].get_ylim()[1], "  post-freeze →",
                 color="grey", fontsize=8, va="top")

    fig.suptitle(
        "v6 finalist — actual holdings composition over hold-out "
        f"({HOLDOUT_START.date()} → {HOLDOUT_END.date()})",
        fontsize=12, y=0.995,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.985))
    fig.savefig(FIG_PATH, dpi=140, bbox_inches="tight")
    print(f"wrote {FIG_PATH}")

    # ---- CSV dump ------------------------------------------------------ #
    out = pd.DataFrame({"week_end": pre_shares.index.strftime("%Y-%m-%d")})
    for g in GROUP_ORDER:
        out[f"pre_{g}_pct"] = (pre_shares[g].values * 100).round(3)
    out["pre_cash_pct"] = (pre_cash.values * 100).round(3)
    for cid in ("cap2", "cap5"):
        for g in GROUP_ORDER:
            out[f"{cid}_{g}_pct"] = (post[cid]["shares"][g].values * 100).round(3)
        out[f"{cid}_cash_pct"] = (post[cid]["cash"].values * 100).round(3)
        out[f"{cid}_L"] = post[cid]["L"].values.round(4)
    out.to_csv(CSV_PATH, index=False)
    print(f"wrote {CSV_PATH}  rows={len(out)}")


if __name__ == "__main__":
    main()
