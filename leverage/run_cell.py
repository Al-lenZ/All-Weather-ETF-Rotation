"""v6/leverage/run_cell.py — one leverage / no-lev cell → data/leverage/<id>/.

Round A cells (PLAN §6):

    A_base_nolev   base RB 55/20/10/15, L≡1, DR007 carry on residual cash.
    A_ew_nolev     EW   RB 25/25/25/25, L≡1, DR007 carry on residual cash.
    A_base_lev     base RB, book-lev σ*=3.2%, cap=2.0, GC007 borrow / DR007 carry.
    A_ew_lev       EW   RB, book-lev σ*=3.2%, cap=2.0, GC007 borrow / DR007 carry.

Extra utility cell (M3 sanity checkpoint — NOT part of Round A matrix):

    A_base_nolev_raw   base RB, L≡1, cash carry OFF. Should reproduce
                       ``data/block_two_layer_v6/q20_eps030/`` on raw
                       Sharpe within 1 bp.

Deliverables written per cell (PLAN §7):

    summary.csv          IS / OOS / IS+OOS rows with raw + excess Sharpe,
                         CAGR, DD, split turnover, funding & cash-carry
                         drag, L stats, σ_est/realized ratio, and the
                         conditional tail diagnostic.
    per_year.csv         same metrics bucketed by calendar year.
    L_t_path.csv         weekly L_t, σ_est, σ_realized, cash_share, rf.
    funding_ledger.csv   weekly borrow / cash-carry accruals in the fraction-
                         of-NAV convention (NAV_t ≡ 1 constant-notional).
    net_ret.csv          weekly net_ret series.
    header.txt           config echo + effective IS start.

CLI
---
    python -m leverage.run_cell --cell A_base_nolev
    python -m leverage.run_cell --cell A_base_lev
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import _common_leverage as CL
import rb_variants as RV
import leverage_engine as LE
import metrics as M
# --- v6/common sys.path bootstrap ---
import sys as _v6_sys
from pathlib import Path as _V6Path
_v6_p = _V6Path(__file__).resolve().parent
while _v6_p.name != "v6" and _v6_p.parent != _v6_p:
    _v6_p = _v6_p.parent
_v6_sys.path.insert(0, str(_v6_p / "common"))
del _v6_p
# --------------------------------------
import block_composite_v6 as BC       # noqa: E402


# ----------------------------------------------------------------------
# Cell config table (Round A + M3 sanity)
# ----------------------------------------------------------------------
CELL_CONFIGS: dict[str, dict] = {
    # --- Round A ------------------------------------------------------
    "A_base_nolev": dict(
        engine="whole_book", rb="base",
        apply_leverage=False, apply_cash_carry=True,
        funding_curve="gc007", cash_carry_curve="dr007",
    ),
    "A_ew_nolev":   dict(
        engine="whole_book", rb="EW",
        apply_leverage=False, apply_cash_carry=True,
        funding_curve="gc007", cash_carry_curve="dr007",
    ),
    "A_base_lev":   dict(
        engine="whole_book", rb="base",
        apply_leverage=True, apply_cash_carry=True,
        L_mode="vol_target",
        funding_curve="gc007", cash_carry_curve="dr007",
    ),
    "A_ew_lev":     dict(
        engine="whole_book", rb="EW",
        apply_leverage=True, apply_cash_carry=True,
        L_mode="vol_target",
        funding_curve="gc007", cash_carry_curve="dr007",
    ),
    # M3 sanity checkpoint — cash carry OFF so raw Sharpe matches finalist.
    "A_base_nolev_raw": dict(
        engine="whole_book", rb="base",
        apply_leverage=False, apply_cash_carry=False,
        funding_curve="gc007", cash_carry_curve="dr007",
    ),
    # --- Round B — funding-channel swap (DR007 instead of GC007) --------
    "B_base_lev_DR007": dict(
        engine="whole_book", rb="base",
        apply_leverage=True, apply_cash_carry=True,
        L_mode="vol_target",
        funding_curve="dr007", cash_carry_curve="dr007",
    ),
    "B_ew_lev_DR007": dict(
        engine="whole_book", rb="EW",
        apply_leverage=True, apply_cash_carry=True,
        L_mode="vol_target",
        funding_curve="dr007", cash_carry_curve="dr007",
    ),
    # --- Round B — static L ≡ cap (sanity vs the vol-targeter) ---------
    "B_base_lev_static": dict(
        engine="whole_book", rb="base",
        apply_leverage=True, apply_cash_carry=True,
        L_mode="static",
        funding_curve="gc007", cash_carry_curve="dr007",
    ),
    "B_ew_lev_static": dict(
        engine="whole_book", rb="EW",
        apply_leverage=True, apply_cash_carry=True,
        L_mode="static",
        funding_curve="gc007", cash_carry_curve="dr007",
    ),
    # --- Round B — bond-leg-only lev (leg-vs-whole sanity, §5B) --------
    "B_base_bondleg_lev": dict(
        engine="bond_leg", rb="base",
        apply_leverage=True, apply_cash_carry=True,
        funding_curve="gc007", cash_carry_curve="dr007",
        leg_sigma_star=CL.SIGMA_STAR_BONDLEG,
    ),
    "B_ew_bondleg_lev": dict(
        engine="bond_leg", rb="EW",
        apply_leverage=True, apply_cash_carry=True,
        funding_curve="gc007", cash_carry_curve="dr007",
        leg_sigma_star=CL.SIGMA_STAR_BONDLEG,
    ),
    # --- Round C — non-α blocks compressed to rep-sets (post-hoc) ------
    # PLAN §11 log 2026-07-31: replace 6 non-α blocks with the exp2
    # adaptive-K representative-set replicated invvol composite (frozen
    # CSVs under data/exp2_representative_sets_v6/). α blocks unchanged.
    # 6 cells: {base, EW} × {no-lev, lev @ GC007, lev @ DR007}.
    "C_base_reps_nolev": dict(
        engine="whole_book", rb="base",
        apply_leverage=False, apply_cash_carry=True,
        funding_curve="gc007", cash_carry_curve="dr007",
        use_reps=True,
    ),
    "C_ew_reps_nolev": dict(
        engine="whole_book", rb="EW",
        apply_leverage=False, apply_cash_carry=True,
        funding_curve="gc007", cash_carry_curve="dr007",
        use_reps=True,
    ),
    "C_base_reps_lev": dict(
        engine="whole_book", rb="base",
        apply_leverage=True, apply_cash_carry=True,
        L_mode="vol_target",
        funding_curve="gc007", cash_carry_curve="dr007",
        use_reps=True,
    ),
    "C_ew_reps_lev": dict(
        engine="whole_book", rb="EW",
        apply_leverage=True, apply_cash_carry=True,
        L_mode="vol_target",
        funding_curve="gc007", cash_carry_curve="dr007",
        use_reps=True,
    ),
    "C_base_reps_lev_DR007": dict(
        engine="whole_book", rb="base",
        apply_leverage=True, apply_cash_carry=True,
        L_mode="vol_target",
        funding_curve="dr007", cash_carry_curve="dr007",
        use_reps=True,
    ),
    "C_ew_reps_lev_DR007": dict(
        engine="whole_book", rb="EW",
        apply_leverage=True, apply_cash_carry=True,
        L_mode="vol_target",
        funding_curve="dr007", cash_carry_curve="dr007",
        use_reps=True,
    ),
    # --- Round D — higher-cap experiment (post-hoc, boss ask) ----------
    # σ* doubled to 6.4 % (targets ~2× current normal-case leverage);
    # cap raised to 5.0 (boss OK'd 5x, said 10x is theoretical ceiling
    # but stay at 5 first). Rep-set retained from Round C. 4 cells:
    # {base, EW} × {GC007, DR007}. PLAN §11 log 2026-07-31.
    "D_base_reps_lev": dict(
        engine="whole_book", rb="base",
        apply_leverage=True, apply_cash_carry=True,
        L_mode="vol_target",
        funding_curve="gc007", cash_carry_curve="dr007",
        use_reps=True,
        sigma_star=0.064, cap=5.0,
    ),
    "D_ew_reps_lev": dict(
        engine="whole_book", rb="EW",
        apply_leverage=True, apply_cash_carry=True,
        L_mode="vol_target",
        funding_curve="gc007", cash_carry_curve="dr007",
        use_reps=True,
        sigma_star=0.064, cap=5.0,
    ),
    "D_base_reps_lev_DR007": dict(
        engine="whole_book", rb="base",
        apply_leverage=True, apply_cash_carry=True,
        L_mode="vol_target",
        funding_curve="dr007", cash_carry_curve="dr007",
        use_reps=True,
        sigma_star=0.064, cap=5.0,
    ),
    "D_ew_reps_lev_DR007": dict(
        engine="whole_book", rb="EW",
        apply_leverage=True, apply_cash_carry=True,
        L_mode="vol_target",
        funding_curve="dr007", cash_carry_curve="dr007",
        use_reps=True,
        sigma_star=0.064, cap=5.0,
    ),
}


# ----------------------------------------------------------------------
# Window bookkeeping
# ----------------------------------------------------------------------
def _window_slices(net_ret: pd.Series) -> dict[str, pd.Series]:
    """Split into IS / OOS / IS+OOS. Effective IS start = first non-zero
    bar (matches PLAN §1 warmup-strip convention)."""
    nz = net_ret[net_ret.ne(0.0)]
    is_start = nz.index.min() if len(nz) else net_ret.index.min()
    idx = net_ret.index
    is_mask  = (idx >= is_start) & (idx <= CL.IN_SAMPLE_END)
    oos_mask = (idx >= CL.OOS_START) & (idx <= CL.OOS_END)
    return {
        "is":     net_ret[is_mask],
        "oos":    net_ret[oos_mask],
        "is+oos": net_ret[is_mask | oos_mask],
        "_is_start": is_start,
    }


def _funding_curve_p90(cell_cfg: dict) -> pd.Series:
    """90th-percentile threshold on the cell's funding curve, computed on
    the historical daily series available. Used for the conditional-tail
    diagnostic in ``_summary_row``."""
    import funding_curves as FC
    return FC.load(cell_cfg["funding_curve"])


def _summary_row(net_ret: pd.Series,
                 L_t: pd.Series,
                 sigma_est: pd.Series,
                 sigma_real: pd.Series,
                 turn_bond: pd.Series,
                 turn_nb:   pd.Series,
                 funding_cost: pd.Series,
                 cash_carry:   pd.Series,
                 fund_accrual: pd.Series,
                 dr007_accrual: pd.Series,
                 rf_period_ann: pd.Series,   # ann-form of fund_accrual (for avg_rf_ann)
                 gc007_accrual: pd.Series,   # common rf reference for cross-cell comp
                 window_label: str,
                 window_bounds: tuple[pd.Timestamp, pd.Timestamp],
                 rb: str, funding_curve: str,
                 sigma_star: float, cap: float,
                 fund_curve_daily: pd.Series) -> dict:
    """One row of summary.csv per PLAN §7 schema."""
    ws = M.window_stats(net_ret, rf_period=fund_accrual.reindex(net_ret.index))
    n = ws.n_bars
    row: dict = {
        "window":  window_label,
        "is_start": window_bounds[0].date() if window_bounds[0] is not None else None,
        "is_end":   window_bounds[1].date() if window_bounds[1] is not None else None,
        "rb":       rb,
        "funding_curve_id": funding_curve,
        "sigma_star": sigma_star,
        "cap":        cap,
        "sharpe_net":          ws.sharpe,
        "sharpe_gross":        np.nan,   # populated separately
        "excess_sharpe_net":   ws.excess_sharpe,
        "excess_sharpe_gross": np.nan,
        "cagr_net":            ws.cagr,
        "cagr_gross":          np.nan,
        "excess_cagr_net":     ws.excess_cagr,      # compounded, vs cell's own rf
        "ann_excess_ret_net":  ws.ann_excess_ret,   # arithmetic, vs cell's own rf
        "vol_realized":        ws.ann_vol,
        "avg_rf_ann":          float(rf_period_ann.reindex(net_ret.index).mean())
                                if len(net_ret) else np.nan,
        "max_dd":              ws.max_dd,
        "calmar":       (abs(ws.cagr / ws.max_dd) if ws.max_dd < 0 else np.nan),
        "turnover_ann_bond":    float(turn_bond.reindex(net_ret.index).mean()) * CL.WEEKS_PER_YEAR,
        "turnover_ann_nonbond": float(turn_nb.reindex(net_ret.index).mean())   * CL.WEEKS_PER_YEAR,
        "cost_drag_bp_yr":      float((turn_bond * CL.COST_BOND_BP +
                                       turn_nb   * CL.COST_NONBOND_BP)
                                       .reindex(net_ret.index).mean()) *
                                CL.WEEKS_PER_YEAR,           # already bp
        "funding_drag_bp_yr":   float(funding_cost.reindex(net_ret.index).mean()) *
                                CL.WEEKS_PER_YEAR * 1e4,
        "cash_carry_bp_yr":     float(cash_carry.reindex(net_ret.index).mean()) *
                                CL.WEEKS_PER_YEAR * 1e4,
        "mean_L":       float(L_t.reindex(net_ret.index).mean()),
        "p95_L":        float(L_t.reindex(net_ret.index).quantile(0.95)) if n else np.nan,
        "pct_at_cap":   float((L_t.reindex(net_ret.index).round(6) >= cap).mean()) if n else np.nan,
        "pct_at_floor": float((L_t.reindex(net_ret.index).round(6) <= 1.0).mean()) if n else np.nan,
        "n_bars":       n,
    }
    # Cross-cell excess vs GC007 (common benchmark, cash-carry-rate-equivalent).
    # cell's-own-rf excess (above) preserves the invariance identity for §8B;
    # this GC007 version is the like-for-like cross-cell number for reports.
    if len(net_ret) >= 2:
        ws_gc = M.window_stats(net_ret, rf_period=gc007_accrual.reindex(net_ret.index))
        row["excess_cagr_vs_gc007"]    = ws_gc.excess_cagr
        row["ann_excess_ret_vs_gc007"] = ws_gc.ann_excess_ret
        row["excess_sharpe_vs_gc007"]  = ws_gc.excess_sharpe
    else:
        row["excess_cagr_vs_gc007"]    = np.nan
        row["ann_excess_ret_vs_gc007"] = np.nan
        row["excess_sharpe_vs_gc007"]  = np.nan

    # σ ratio — two forms
    # (a) per-bar mean of (σ_est / σ_real_fwd4). Right-skewed (some bars catch
    #     ultra-calm 4w windows, blowing up the ratio) — matches WINNER.md
    #     ``fwd4_mean`` diagnostic column.
    # (b) M0-B "aggregate" ratio: mean(σ_est) over window ÷ realized_ann,
    #     where realized_ann = std(weekly_book_ret) × √52 on that same window.
    #     This is the number in WINNER.md's ``is_agg_ratio`` column and is
    #     what the memory ``project-leverage-experiment-v6`` cites (0.917).
    ratio = (sigma_est / sigma_real).replace([np.inf, -np.inf], np.nan)
    row["sigma_est_vs_realized_ratio_mean"] = float(
        ratio.reindex(net_ret.index).mean()
    )
    se_w = sigma_est.reindex(net_ret.index).dropna()
    if len(net_ret) >= 2 and len(se_w) > 0 and float(net_ret.std(ddof=1)) > 0:
        realized_agg = float(net_ret.std(ddof=1)) * np.sqrt(CL.WEEKS_PER_YEAR)
        row["sigma_est_vs_realized_agg"] = float(se_w.mean() / realized_agg)
    else:
        row["sigma_est_vs_realized_agg"] = np.nan

    # conditional tail: p50 / p05 of net_ret on weeks where funding curve
    # (annualized) is in its own 90th-pctile. Uses the cell's funding curve.
    fc_ann_wkly = fund_accrual.reindex(net_ret.index) * (CL.WEEKS_PER_YEAR)  # decimal ann-approx
    # more principled: annualize by dividing by (bar's day fraction) — but
    # since weekly bar accrual ≈ ann_rate × 7/365 and 7/365 × 52 ≈ 0.997,
    # multiplying by 52 gives the same order. Use the daily curve directly
    # for the threshold instead.
    thr = fund_curve_daily.quantile(0.90)
    # Weekly rf_ann (avg of daily curve within the bar) — use rf_period_ann.
    high_mask = rf_period_ann.reindex(net_ret.index) >= thr
    tail = net_ret[high_mask.fillna(False)]
    row["net_ret_p50_when_rf_p90"] = float(tail.quantile(0.50)) if len(tail) else np.nan
    row["net_ret_p05_when_rf_p90"] = float(tail.quantile(0.05)) if len(tail) else np.nan
    row["n_high_rf_bars"] = int(len(tail))
    return row


def _rf_period_ann(fund_accrual: pd.Series,
                   weekly_index: pd.DatetimeIndex,
                   fund_daily: pd.Series) -> pd.Series:
    """Reconstruct per-bar annualized rate ≈ accrual × 365 / days_in_bar.
    For diagnostic columns only (`avg_rf_ann`, threshold on 90th-pctile)."""
    days = pd.Series(index=weekly_index, dtype=float)
    prev = None
    for t in weekly_index:
        if prev is None:
            days.loc[t] = np.nan
        else:
            days.loc[t] = float((t - prev).days)
        prev = t
    ann = (fund_accrual * 365.0 / days).replace([np.inf, -np.inf], np.nan)
    return ann.rename("rf_ann")


# ----------------------------------------------------------------------
# Full-cell runner
# ----------------------------------------------------------------------
def run_cell(cell_id: str,
             shared: dict | None = None,
             out_root: Path = CL.LEV_DIR) -> dict:
    if cell_id not in CELL_CONFIGS:
        raise KeyError(f"unknown cell: {cell_id}. Known: {list(CELL_CONFIGS)}")
    cfg = CELL_CONFIGS[cell_id]

    if shared is None:
        shared = BC.load_shared()

    # 1. book
    book = RV.build_book(shared, rb=cfg["rb"],
                         use_reps=cfg.get("use_reps", False))

    # 2. net cell (leverage + carry per config)
    engine = cfg.get("engine", "whole_book")
    cell_sigma_star = cfg.get("sigma_star", CL.SIGMA_STAR)
    cell_cap        = cfg.get("cap",        CL.CAP)
    if engine == "whole_book":
        res = LE.apply_book_vol_target(
            book,
            sigma_star=cell_sigma_star,
            cap=cell_cap,
            funding_curve=cfg["funding_curve"],
            cash_carry_curve=cfg["cash_carry_curve"],
            apply_leverage=cfg["apply_leverage"],
            apply_cash_carry=cfg["apply_cash_carry"],
            L_mode=cfg.get("L_mode", "vol_target"),
        )
    elif engine == "bond_leg":
        res = LE.apply_bondleg_vol_target(
            book,
            sigma_star_bondleg=cfg.get("leg_sigma_star", CL.SIGMA_STAR_BONDLEG),
            cap=cell_cap,
            funding_curve=cfg["funding_curve"],
            cash_carry_curve=cfg["cash_carry_curve"],
            apply_cash_carry=cfg["apply_cash_carry"],
        )
    else:
        raise ValueError(f"unknown engine: {engine!r}")

    # 3. gross cell (zero cost, no carry) — for sharpe_gross / cagr_gross column
    #    Re-uses the same L_t path so the ratio isolates cost impact only.
    gross_net = (res.r_book_lev.copy()
                 + (res.cash_carry if cfg["apply_cash_carry"] else 0.0)
                 - res.funding_cost)
    # (no − cost subtracted)

    # 4. windowize + summary rows
    slices = _window_slices(res.net_ret)
    is_start = slices["_is_start"]
    windows = {
        "is":     (is_start,           CL.IN_SAMPLE_END),
        "oos":    (CL.OOS_START,       CL.OOS_END),
        "is+oos": (is_start,           CL.OOS_END),
    }

    # rf helpers (per PLAN §7): rf_period is fund_accrual;
    # avg_rf_ann diagnostic uses the ann-form. gc007_accrual is the common
    # cross-cell rf reference used for ``excess_*_vs_gc007`` columns.
    import funding_curves as FC
    fund_daily     = _funding_curve_p90(cfg)
    gc007_daily    = FC.load("gc007")
    rf_ann         = _rf_period_ann(res.funding_accrual, res.funding_accrual.index, fund_daily)
    gc007_accrual  = FC.weekly_accrual(
        gc007_daily, res.funding_accrual.index
    ).reindex(res.funding_accrual.index).fillna(0.0)
    gc007_accrual  = gc007_accrual.where(res.invested, 0.0)

    rows = []
    for wlabel, (lo, hi) in windows.items():
        sl = slices[wlabel]
        # gross slice metrics
        ws_g = M.window_stats(gross_net.reindex(sl.index),
                              rf_period=res.funding_accrual.reindex(sl.index))
        row = _summary_row(
            net_ret=sl,
            L_t=res.L_t, sigma_est=res.sigma_est, sigma_real=res.sigma_realized,
            turn_bond=res.turn_bond, turn_nb=res.turn_nonbond,
            funding_cost=res.funding_cost, cash_carry=res.cash_carry,
            fund_accrual=res.funding_accrual, dr007_accrual=res.dr007_accrual,
            rf_period_ann=rf_ann, gc007_accrual=gc007_accrual,
            window_label=wlabel, window_bounds=(lo, hi),
            rb=cfg["rb"], funding_curve=cfg["funding_curve"],
            sigma_star=res.sigma_star, cap=res.cap,
            fund_curve_daily=fund_daily,
        )
        row["sharpe_gross"]        = ws_g.sharpe
        row["excess_sharpe_gross"] = ws_g.excess_sharpe
        row["cagr_gross"]          = ws_g.cagr
        rows.append(row)
    summary = pd.DataFrame(rows)

    # 5. per-year (over IS+OOS)
    per_yr_rows = []
    idx = slices["is+oos"].index
    for yr, g in slices["is+oos"].groupby(idx.year):
        gross_g = gross_net.reindex(g.index)
        ws_n = M.window_stats(g, rf_period=res.funding_accrual.reindex(g.index))
        ws_g = M.window_stats(gross_g, rf_period=res.funding_accrual.reindex(g.index))
        turn_b_ann = float(res.turn_bond.reindex(g.index).mean()) * CL.WEEKS_PER_YEAR
        turn_n_ann = float(res.turn_nonbond.reindex(g.index).mean()) * CL.WEEKS_PER_YEAR
        per_yr_rows.append({
            "year": int(yr),
            "sharpe_net": ws_n.sharpe, "sharpe_gross": ws_g.sharpe,
            "excess_sharpe_net": ws_n.excess_sharpe,
            "cagr_net": ws_n.cagr, "cagr_gross": ws_g.cagr,
            "vol_realized": ws_n.ann_vol,
            "max_dd": ws_n.max_dd,
            "mean_L": float(res.L_t.reindex(g.index).mean()),
            "cost_drag_bp_yr": (turn_b_ann * CL.COST_BOND_BP +
                                turn_n_ann * CL.COST_NONBOND_BP),
            "funding_drag_bp_yr": float(res.funding_cost.reindex(g.index).mean()) *
                                  CL.WEEKS_PER_YEAR * 1e4,
            "cash_carry_bp_yr":   float(res.cash_carry.reindex(g.index).mean()) *
                                  CL.WEEKS_PER_YEAR * 1e4,
            "n_bars": ws_n.n_bars,
        })
    per_year = pd.DataFrame(per_yr_rows)

    # 6. duration ledger — book_duration on the LEVERED W panel
    dur_led = RV.duration_ledger(res.W_lev, book["bond_group"], book["krd"])
    # inject book_duration mean / p95 into every summary row for the row's window
    idx_by_win = {"is": slices["is"].index, "oos": slices["oos"].index,
                  "is+oos": slices["is+oos"].index}
    for i, wl in enumerate(("is", "oos", "is+oos")):
        bdi = dur_led["book_duration_yr"].reindex(idx_by_win[wl]).dropna()
        summary.loc[summary["window"] == wl, "book_duration_yr_mean"] = (
            float(bdi.mean()) if len(bdi) else np.nan
        )
        summary.loc[summary["window"] == wl, "book_duration_yr_p95"] = (
            float(bdi.quantile(0.95)) if len(bdi) else np.nan
        )

    # 7. persist
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
        "nav":                  1.0,            # constant-notional
        "L_t":                  res.L_t,
        "borrowed_notional":    (res.L_t - 1.0),
        "funding_accrual":      res.funding_accrual,
        "funding_cost_dollar":  res.funding_cost,        # frac-of-NAV (NAV=1)
        "cash_nav":             res.cash_share,
        "cash_carry_accrual":   res.dr007_accrual,
        "cash_carry_dollar":    res.cash_carry,
        "net_funding_dollar":   res.cash_carry - res.funding_cost,
    }).round(9)
    ledger.to_csv(d / "funding_ledger.csv")

    res.net_ret.to_frame("net_ret").to_csv(d / "net_ret.csv")

    header = {
        "cell": cell_id, **cfg,
        "engine": engine,
        "sigma_star": res.sigma_star, "cap": res.cap,
        "cost_bond_bp":    CL.COST_BOND_BP,
        "cost_nonbond_bp": CL.COST_NONBOND_BP,
        "effective_is_start": str(is_start.date()),
        "in_sample_end":      str(CL.IN_SAMPLE_END.date()),
        "oos_start":          str(CL.OOS_START.date()),
        "oos_end":            str(CL.OOS_END.date()),
        "n_bars_total":       int(len(res.net_ret)),
        "sigma_est_estimator": "weekly_ewma_52 (halflife 26w, min_periods 13)",
        "book_duration_yr_mean_is+oos":
            (None if pd.isna(summary.loc[summary["window"]=="is+oos","book_duration_yr_mean"].iloc[0])
             else float(summary.loc[summary["window"]=="is+oos","book_duration_yr_mean"].iloc[0])),
        "book_duration_yr_p95_is+oos":
            (None if pd.isna(summary.loc[summary["window"]=="is+oos","book_duration_yr_p95"].iloc[0])
             else float(summary.loc[summary["window"]=="is+oos","book_duration_yr_p95"].iloc[0])),
        "plan_hash":          "revised 2026-07-30 (Round A wrap: C5 → per-window diagnostic; §8C prior rewritten; KRD table wired)",
        "notes":              [
            "L_t clip [1.0, cap]; no de-lever below 1x (PLAN §9 open item).",
            "Cash carry uses SHIBOR 1W proxy for DR007 (see funding _funding/PROVENANCE.md).",
            "Cost split: 2 bp/side bond, 10 bp/side non-bond (PLAN §四.D4).",
            "book_duration_yr uses static KRD table in _common_leverage.py; ±0.5y accuracy.",
        ],
    }
    (d / "header.txt").write_text(json.dumps(header, indent=2, default=str) + "\n")

    return {
        "cell_id": cell_id,
        "cfg": cfg,
        "book": book,
        "res":  res,
        "summary": summary,
        "per_year": per_year,
        "out_dir": d,
    }


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run one leverage cell.")
    p.add_argument("--cell", required=True, choices=sorted(CELL_CONFIGS),
                   help="cell id to run")
    p.add_argument("--out-root", type=str, default=None,
                   help="override output root (default data/leverage/)")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    out_root = Path(args.out_root) if args.out_root else CL.LEV_DIR
    bundle = run_cell(args.cell, out_root=out_root)
    print(f"\n=== {bundle['cell_id']} → {bundle['out_dir']} ===")
    s = bundle["summary"]
    if not s.empty:
        cols = ["window", "sharpe_net", "excess_sharpe_net",
                "cagr_net", "max_dd", "mean_L", "pct_at_cap", "pct_at_floor",
                "funding_drag_bp_yr", "cash_carry_bp_yr", "cost_drag_bp_yr",
                "n_bars"]
        print(s[cols].to_string(index=False, float_format=lambda x: f"{x:+.4f}"))


if __name__ == "__main__":
    main()
