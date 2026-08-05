"""
v6/hold_out_backtest/scripts/run_hold_out_shot.py
=================================================
Final shot on the *extended* hold-out window 2025-08-01 → 2026-08-04
(last W-FRI bar 2026-07-31) for the v6 finalist.

Strategy (locked, matches production finalist):
    - Two-layer: layer-1 risk-budget (base 55/20/10/15) + layer-2 α rotation
      on broad_cn + sector_cn (q=0.20, ε=0.30 hysteresis, replace kernel).
    - Rep-set compression on the 6 non-α blocks (exp2 adaptive-K, threshold 0.20).
    - Whole-book vol-target leverage, weekly_ewma_52 estimator.
    - Cost split: 2 bp/side bond, 10 bp/side non-bond.
    - Funding + cash carry: DR007 (SHIBOR-1W proxy, +20-35 bp bias documented).

Two variants (only knobs that differ):
    - cap=2, σ*=3.2 %  (matches Round C `C_base_reps_lev_DR007`)
    - cap=5, σ*=6.4 %  (matches Round D `D_base_reps_lev_DR007`)

Windows reported per cell:
    - hold_out : 2025-08-01 → 2026-08-04   ← the shot
    - stress   : 2025-08-01 → 2026-07-17   ← for context (already consumed)
    - post_freeze : 2026-07-18 → 2026-08-04 ← truly-new bars only
    - is_oos_pool : 2019-05-31 → 2025-07-31 ← IS+OOS reference

Outputs → v6/data/hold_out_backtest/<cell_id>/
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve()
# Add v6/leverage and v6/common to sys.path
sys.path.insert(0, str(_HERE.parents[2] / "leverage"))
sys.path.insert(0, str(_HERE.parents[2] / "common"))
sys.path.insert(0, str(_HERE.parents[3]))                      # repo root

import _common_leverage as CL           # noqa: E402
import rb_variants as RV                # noqa: E402
import leverage_engine as LE            # noqa: E402
import funding_curves as FC             # noqa: E402
import metrics as M                     # noqa: E402
import block_composite_v6 as BC         # noqa: E402


HOLDOUT_START     = pd.Timestamp("2025-08-01")
HOLDOUT_END       = pd.Timestamp("2026-08-04")
STRESS_START      = CL.STRESS_START     # 2025-08-01
STRESS_END        = CL.STRESS_END       # 2026-07-17
POST_FREEZE_START = pd.Timestamp("2026-07-18")   # truly-new bars

OUT_ROOT = CL.DATA_DIR / "hold_out_backtest"

CELL_CONFIGS: dict[str, dict] = {
    "base_reps_lev_cap2_dr007": dict(
        rb="base", use_reps=True,
        funding_curve="dr007", cash_carry_curve="dr007",
        sigma_star=0.032, cap=2.0,
    ),
    "base_reps_lev_cap5_dr007": dict(
        rb="base", use_reps=True,
        funding_curve="dr007", cash_carry_curve="dr007",
        sigma_star=0.064, cap=5.0,
    ),
}


# -------------------------------------------------------------------- #
# Window bookkeeping (extends run_cell._window_slices)
# -------------------------------------------------------------------- #
def _first_nonzero(net_ret: pd.Series) -> pd.Timestamp:
    nz = net_ret[net_ret.ne(0.0)]
    return nz.index.min() if len(nz) else net_ret.index.min()


def _window_slices(net_ret: pd.Series) -> dict[str, pd.Series]:
    """IS/OOS + new hold_out flavors on top of run_cell semantics."""
    is_start = _first_nonzero(net_ret)
    idx = net_ret.index
    is_m  = (idx >= is_start) & (idx <= CL.IN_SAMPLE_END)
    oos_m = (idx >= CL.OOS_START) & (idx <= CL.OOS_END)
    hold_m   = (idx >= HOLDOUT_START) & (idx <= HOLDOUT_END)
    stress_m = (idx >= STRESS_START) & (idx <= STRESS_END)
    new_m    = (idx >= POST_FREEZE_START) & (idx <= HOLDOUT_END)
    return {
        "is":            net_ret[is_m],
        "oos":           net_ret[oos_m],
        "is_oos_pool":   net_ret[is_m | oos_m],
        "stress":        net_ret[stress_m],
        "post_freeze":   net_ret[new_m],
        "hold_out":      net_ret[hold_m],
        "_is_start":     is_start,
    }


# -------------------------------------------------------------------- #
# Summary row (subset of run_cell._summary_row — no gross-Sharpe or gc007
# excess columns since we only care about the levered DR007-funded cell)
# -------------------------------------------------------------------- #
def _summary_row(*, net_ret, L_t, sigma_est, sigma_real,
                 turn_bond, turn_nb, funding_cost, cash_carry,
                 fund_accrual, rf_ann,
                 window_label, window_bounds,
                 rb, funding_curve, sigma_star, cap,
                 fund_curve_daily) -> dict:
    if len(net_ret) < 2:
        return {"window": window_label, "n_bars": len(net_ret),
                "is_start": window_bounds[0].date() if window_bounds[0] is not None else None,
                "is_end":   window_bounds[1].date() if window_bounds[1] is not None else None,
                "rb": rb, "funding_curve_id": funding_curve,
                "sigma_star": sigma_star, "cap": cap}

    ws = M.window_stats(net_ret, rf_period=fund_accrual.reindex(net_ret.index))
    n = ws.n_bars
    row: dict = {
        "window":            window_label,
        "is_start":          window_bounds[0].date() if window_bounds[0] is not None else None,
        "is_end":            window_bounds[1].date() if window_bounds[1] is not None else None,
        "rb":                rb,
        "funding_curve_id":  funding_curve,
        "sigma_star":        sigma_star,
        "cap":               cap,
        "sharpe_net":         ws.sharpe,
        "excess_sharpe_net":  ws.excess_sharpe,
        "cagr_net":           ws.cagr,
        "excess_cagr_net":    ws.excess_cagr,
        "ann_excess_ret_net": ws.ann_excess_ret,
        "vol_realized":       ws.ann_vol,
        "avg_rf_ann":         float(rf_ann.reindex(net_ret.index).mean())
                              if len(net_ret) else np.nan,
        "max_dd":             ws.max_dd,
        "calmar":  (abs(ws.cagr / ws.max_dd) if ws.max_dd < 0 else np.nan),
        "turnover_ann_bond":    float(turn_bond.reindex(net_ret.index).mean()) * CL.WEEKS_PER_YEAR,
        "turnover_ann_nonbond": float(turn_nb.reindex(net_ret.index).mean())   * CL.WEEKS_PER_YEAR,
        "cost_drag_bp_yr":      float((turn_bond * CL.COST_BOND_BP +
                                       turn_nb   * CL.COST_NONBOND_BP)
                                       .reindex(net_ret.index).mean()) *
                                CL.WEEKS_PER_YEAR,
        "funding_drag_bp_yr":   float(funding_cost.reindex(net_ret.index).mean()) *
                                CL.WEEKS_PER_YEAR * 1e4,
        "cash_carry_bp_yr":     float(cash_carry.reindex(net_ret.index).mean()) *
                                CL.WEEKS_PER_YEAR * 1e4,
        "mean_L":       float(L_t.reindex(net_ret.index).mean()),
        "p95_L":        float(L_t.reindex(net_ret.index).quantile(0.95)),
        "pct_at_cap":   float((L_t.reindex(net_ret.index).round(6) >= cap).mean()),
        "pct_at_floor": float((L_t.reindex(net_ret.index).round(6) <= 1.0).mean()),
        "n_bars":       n,
    }
    ratio = (sigma_est / sigma_real).replace([np.inf, -np.inf], np.nan)
    row["sigma_est_vs_realized_ratio_mean"] = float(
        ratio.reindex(net_ret.index).mean()
    )
    # p90 conditional tail
    thr = fund_curve_daily.quantile(0.90)
    high_mask = rf_ann.reindex(net_ret.index) >= thr
    tail = net_ret[high_mask.fillna(False)]
    row["net_ret_p50_when_rf_p90"] = float(tail.quantile(0.50)) if len(tail) else np.nan
    row["net_ret_p05_when_rf_p90"] = float(tail.quantile(0.05)) if len(tail) else np.nan
    row["n_high_rf_bars"] = int(len(tail))
    return row


def _rf_period_ann(fund_accrual: pd.Series,
                   weekly_index: pd.DatetimeIndex) -> pd.Series:
    """Reconstruct per-bar annualized rate ≈ accrual × 365 / days_in_bar."""
    days = pd.Series(index=weekly_index, dtype=float)
    prev = None
    for t in weekly_index:
        days.loc[t] = float((t - prev).days) if prev is not None else np.nan
        prev = t
    return (fund_accrual * 365.0 / days).replace([np.inf, -np.inf], np.nan).rename("rf_ann")


# -------------------------------------------------------------------- #
# Cell runner
# -------------------------------------------------------------------- #
def run_cell(cell_id: str, shared: dict, out_root: Path = OUT_ROOT) -> dict:
    cfg = CELL_CONFIGS[cell_id]

    book = RV.build_book(shared, rb=cfg["rb"], use_reps=cfg["use_reps"])

    res = LE.apply_book_vol_target(
        book,
        sigma_star=cfg["sigma_star"],
        cap=cfg["cap"],
        funding_curve=cfg["funding_curve"],
        cash_carry_curve=cfg["cash_carry_curve"],
        apply_leverage=True,
        apply_cash_carry=True,
        L_mode="vol_target",
    )

    slices = _window_slices(res.net_ret)
    is_start = slices["_is_start"]
    windows = {
        "is":           (is_start,           CL.IN_SAMPLE_END),
        "oos":          (CL.OOS_START,       CL.OOS_END),
        "is_oos_pool":  (is_start,           CL.OOS_END),
        "stress":       (STRESS_START,       STRESS_END),
        "post_freeze":  (POST_FREEZE_START,  HOLDOUT_END),
        "hold_out":     (HOLDOUT_START,      HOLDOUT_END),
    }

    fund_daily = FC.load(cfg["funding_curve"])
    rf_ann     = _rf_period_ann(res.funding_accrual, res.funding_accrual.index)

    rows = [
        _summary_row(
            net_ret=slices[wl], L_t=res.L_t,
            sigma_est=res.sigma_est, sigma_real=res.sigma_realized,
            turn_bond=res.turn_bond, turn_nb=res.turn_nonbond,
            funding_cost=res.funding_cost, cash_carry=res.cash_carry,
            fund_accrual=res.funding_accrual, rf_ann=rf_ann,
            window_label=wl, window_bounds=(lo, hi),
            rb=cfg["rb"], funding_curve=cfg["funding_curve"],
            sigma_star=res.sigma_star, cap=res.cap,
            fund_curve_daily=fund_daily,
        )
        for wl, (lo, hi) in windows.items()
    ]
    summary = pd.DataFrame(rows)

    # Per-year rows (over hold_out only — the interesting window)
    per_yr_rows = []
    ho = slices["hold_out"]
    for yr, g in ho.groupby(ho.index.year):
        if len(g) < 2:
            continue
        ws = M.window_stats(g, rf_period=res.funding_accrual.reindex(g.index))
        turn_b_ann = float(res.turn_bond.reindex(g.index).mean()) * CL.WEEKS_PER_YEAR
        turn_n_ann = float(res.turn_nonbond.reindex(g.index).mean()) * CL.WEEKS_PER_YEAR
        per_yr_rows.append({
            "year": int(yr),
            "sharpe_net":         ws.sharpe,
            "excess_sharpe_net":  ws.excess_sharpe,
            "cagr_net":           ws.cagr,
            "excess_cagr_net":    ws.excess_cagr,
            "vol_realized":       ws.ann_vol,
            "max_dd":             ws.max_dd,
            "mean_L":             float(res.L_t.reindex(g.index).mean()),
            "cost_drag_bp_yr":    (turn_b_ann * CL.COST_BOND_BP +
                                   turn_n_ann * CL.COST_NONBOND_BP),
            "funding_drag_bp_yr": float(res.funding_cost.reindex(g.index).mean()) *
                                  CL.WEEKS_PER_YEAR * 1e4,
            "cash_carry_bp_yr":   float(res.cash_carry.reindex(g.index).mean()) *
                                  CL.WEEKS_PER_YEAR * 1e4,
            "n_bars": ws.n_bars,
        })
    per_year = pd.DataFrame(per_yr_rows)

    # Duration ledger on the levered W panel
    dur_led = RV.duration_ledger(res.W_lev, book["bond_group"], book["krd"])
    for wl in ("hold_out", "stress", "post_freeze", "is_oos_pool"):
        idx = slices[wl].index
        bd = dur_led["book_duration_yr"].reindex(idx).dropna()
        summary.loc[summary["window"] == wl, "book_duration_yr_mean"] = (
            float(bd.mean()) if len(bd) else np.nan)
        summary.loc[summary["window"] == wl, "book_duration_yr_p95"] = (
            float(bd.quantile(0.95)) if len(bd) else np.nan)

    # Persist
    d = out_root / cell_id
    d.mkdir(parents=True, exist_ok=True)
    summary.to_csv(d / "summary.csv", index=False)
    per_year.to_csv(d / "per_year.csv", index=False)
    dur_led.to_csv(d / "duration_ledger.csv")

    L_path = pd.DataFrame({
        "L_t":            res.L_t,
        "sigma_est":      res.sigma_est,
        "sigma_realized": res.sigma_realized,
        "sigma_star":     res.sigma_star,
        "rf_period":      res.funding_accrual,
        "rf_ann":         rf_ann,
        "cash_share":     res.cash_share,
    }).round(9)
    L_path.to_csv(d / "L_t_path.csv")

    ledger = pd.DataFrame({
        "nav":                  1.0,
        "L_t":                  res.L_t,
        "borrowed_notional":    (res.L_t - 1.0),
        "funding_accrual":      res.funding_accrual,
        "funding_cost_dollar":  res.funding_cost,
        "cash_nav":             res.cash_share,
        "cash_carry_accrual":   res.dr007_accrual,
        "cash_carry_dollar":    res.cash_carry,
        "net_funding_dollar":   res.cash_carry - res.funding_cost,
    }).round(9)
    ledger.to_csv(d / "funding_ledger.csv")

    res.net_ret.to_frame("net_ret").to_csv(d / "net_ret.csv")

    header = {
        "cell":                cell_id,
        "sigma_star":          res.sigma_star,
        "cap":                 res.cap,
        "rb":                  cfg["rb"],
        "use_reps":            cfg["use_reps"],
        "funding_curve":       cfg["funding_curve"],
        "cash_carry_curve":    cfg["cash_carry_curve"],
        "cost_bond_bp":        CL.COST_BOND_BP,
        "cost_nonbond_bp":     CL.COST_NONBOND_BP,
        "effective_is_start":  str(is_start.date()),
        "in_sample_end":       str(CL.IN_SAMPLE_END.date()),
        "oos_start":           str(CL.OOS_START.date()),
        "oos_end":             str(CL.OOS_END.date()),
        "stress_start":        str(STRESS_START.date()),
        "stress_end":          str(STRESS_END.date()),
        "hold_out_start":      str(HOLDOUT_START.date()),
        "hold_out_end":        str(HOLDOUT_END.date()),
        "post_freeze_start":   str(POST_FREEZE_START.date()),
        "n_bars_total":        int(len(res.net_ret)),
        "n_bars_hold_out":     int(len(slices["hold_out"])),
        "sigma_est_estimator": "weekly_ewma_52 (halflife 26w, min_periods 13)",
        "notes": [
            "Hold-out window 2025-08-01 → 2026-08-04 combines the frozen "
            "stress window (2025-08-01 → 2026-07-17, already consumed) with "
            "the newly-fetched post-freeze bars (2026-07-18 → 2026-08-04).",
            "DR007 curve is SHIBOR-1W proxy (+20-35 bp bias vs true DR007); "
            "real-DR007 execution would look slightly better.",
            "Cost split: 2 bp/side bond, 10 bp/side non-bond.",
            "Two-layer q=0.20 ε=0.30 finalist + exp2 rep-set on 6 non-α blocks.",
        ],
    }
    (d / "header.txt").write_text(json.dumps(header, indent=2, default=str) + "\n")

    return {"cell_id": cell_id, "cfg": cfg, "res": res, "book": book,
            "summary": summary, "per_year": per_year, "out_dir": d}


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    print(f"[hold_out] loading shared bundle ...")
    shared = BC.load_shared()
    print(f"[hold_out] shared loaded: fwd_1w {shared['fwd_1w'].shape}, "
          f"index {shared['fwd_1w'].index.min().date()} → "
          f"{shared['fwd_1w'].index.max().date()}")

    bundles = {}
    for cell_id in CELL_CONFIGS:
        print(f"\n=== running {cell_id} ===")
        b = run_cell(cell_id, shared)
        bundles[cell_id] = b
        s = b["summary"]
        cols = ["window", "n_bars", "sharpe_net", "excess_sharpe_net",
                "cagr_net", "max_dd", "mean_L", "pct_at_cap",
                "funding_drag_bp_yr", "cash_carry_bp_yr", "cost_drag_bp_yr"]
        print(s[cols].to_string(index=False,
                                float_format=lambda x: f"{x:+.4f}"))

    print(f"\n[hold_out] outputs → {OUT_ROOT}")
    return bundles


if __name__ == "__main__":
    main()
