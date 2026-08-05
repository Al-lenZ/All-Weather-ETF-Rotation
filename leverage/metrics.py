"""v6/leverage/metrics.py — Sharpe metrics for the leverage experiment.

Two Sharpe flavors, deliberately kept separate:

- ``raw_sharpe``   — bit-for-bit reproduction of ``xs_engine_v6._window_sharpe``
                     so `sharpe_net` on every summary.csv row can be verified
                     against the frozen v6 baseline within 1 bp. NOT the pass
                     metric (see PLAN §1, §8).
- ``excess_sharpe`` — time-series bar-by-bar excess Sharpe. rf accrues at the
                      cell's funding_curve, bar granularity. This is the PASS
                      metric under leverage (invariant absent estimator bias
                      and funding tracking cost — see PLAN §8A).

Additional helpers:

- ``window_stats``   — the same _WindowStats-like bundle xs_engine_v6 returns.
- ``per_year_stats`` — same computed inside each calendar-year slice.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

WEEKS_PER_YEAR = 52


@dataclass
class WindowStats:
    """Matches ``xs_engine_v6._WindowStats`` field-for-field, plus excess."""
    sharpe:         float = 0.0
    excess_sharpe:  float = 0.0
    ann_ret:        float = 0.0
    ann_excess_ret: float = 0.0           # mean(net_ret − rf_period) × 52
    ann_vol:        float = 0.0
    ann_rf:         float = 0.0           # window-mean rf (diagnostic only)
    cumret:         float = 0.0
    excess_cumret:  float = 0.0           # Σ (net_ret − rf_period)
    cagr:           float = 0.0
    excess_cagr:    float = 0.0           # (1 + excess_cumret)^(1/yrs) − 1
    max_dd:         float = 0.0
    n_bars:         int   = 0


# --------------------------------------------------------------------------- #
# Raw Sharpe (xs_engine_v6._window_sharpe backward-compatible)
# --------------------------------------------------------------------------- #
def raw_sharpe(net_ret: pd.Series) -> float:
    """Bit-for-bit ``xs_engine_v6._window_sharpe``: ann_ret / ann_vol,
    arithmetic-mean annualization at ``WEEKS_PER_YEAR``.

    Kept so leverage summary.csv rows can be cross-checked against the
    frozen v6 baseline within 1 bp.
    """
    n = int(len(net_ret))
    if n < 2:
        return 0.0
    ann_vol = float(net_ret.std(ddof=1)) * np.sqrt(WEEKS_PER_YEAR)
    if ann_vol <= 0:
        return 0.0
    ann_ret = float(net_ret.mean()) * WEEKS_PER_YEAR
    return ann_ret / ann_vol


# --------------------------------------------------------------------------- #
# Excess Sharpe (PLAN §1 pass metric)
# --------------------------------------------------------------------------- #
def excess_sharpe(net_ret: pd.Series,
                  rf_period: pd.Series) -> float:
    """Time-series excess Sharpe: `mean(net_ret − rf_period) × 52 /
    (std(net_ret) × √52)`. Both series are weekly, aligned. `rf_period`
    is the per-bar ACT/365 accrual (dimensionless — same units as
    `net_ret`), NOT an annualized rate.

    Invariance under leverage L (constant rf):
        net_ret_lev = L·r_base − (L−1)·rf_period
        excess_lev  = net_ret_lev − rf_period = L·(r_base − rf_period)
        mean and std scale by L → ratio unchanged.
    """
    net_ret, rf_period = net_ret.align(rf_period, join="inner")
    n = int(len(net_ret))
    if n < 2:
        return 0.0
    ann_vol = float(net_ret.std(ddof=1)) * np.sqrt(WEEKS_PER_YEAR)
    if ann_vol <= 0:
        return 0.0
    excess = net_ret - rf_period
    ann_excess = float(excess.mean()) * WEEKS_PER_YEAR
    return ann_excess / ann_vol


# --------------------------------------------------------------------------- #
# One-shot window bundle (mirrors xs_engine_v6._window_sharpe API)
# --------------------------------------------------------------------------- #
def window_stats(net_ret: pd.Series,
                 rf_period: pd.Series | None = None) -> WindowStats:
    """All PLAN §7 summary.csv metrics for a single window."""
    n = int(len(net_ret))
    if n < 2:
        return WindowStats(n_bars=n)
    ann_vol = float(net_ret.std(ddof=1)) * np.sqrt(WEEKS_PER_YEAR)
    ann_ret = float(net_ret.mean()) * WEEKS_PER_YEAR
    sharpe  = (ann_ret / ann_vol) if ann_vol > 0 else 0.0
    cumret  = float(net_ret.sum())
    n_years = max(n / WEEKS_PER_YEAR, 1e-3)
    cagr    = max(1.0 + cumret, 1e-9) ** (1.0 / n_years) - 1.0
    nav     = 1.0 + net_ret.cumsum()
    cummax  = nav.cummax()
    max_dd  = float(((nav - cummax) / cummax).min())

    if rf_period is not None:
        rf_al = rf_period.reindex(net_ret.index).fillna(0.0)
        ann_rf         = float(rf_al.mean()) * WEEKS_PER_YEAR
        excess_series  = net_ret - rf_al
        ann_excess_ret = float(excess_series.mean()) * WEEKS_PER_YEAR
        excess_cumret  = float(excess_series.sum())
        exc_sharpe     = (ann_excess_ret / ann_vol) if ann_vol > 0 else 0.0
        excess_cagr    = (max(1.0 + excess_cumret, 1e-9) ** (1.0 / n_years)) - 1.0
    else:
        ann_rf = ann_excess_ret = excess_cumret = 0.0
        excess_cagr = cagr
        exc_sharpe  = sharpe

    return WindowStats(sharpe=sharpe, excess_sharpe=exc_sharpe,
                       ann_ret=ann_ret, ann_excess_ret=ann_excess_ret,
                       ann_vol=ann_vol, ann_rf=ann_rf,
                       cumret=cumret, excess_cumret=excess_cumret,
                       cagr=cagr, excess_cagr=excess_cagr,
                       max_dd=max_dd, n_bars=n)


def per_year_stats(net_ret: pd.Series,
                   rf_period: pd.Series | None = None) -> pd.DataFrame:
    """Same stats bucketed by calendar year. Index = year int."""
    rows = []
    for yr, g in net_ret.groupby(net_ret.index.year):
        rfg = (rf_period.reindex(g.index).fillna(0.0)
                if rf_period is not None else None)
        s = window_stats(g, rfg)
        rows.append({"year": int(yr), "sharpe": s.sharpe,
                     "excess_sharpe": s.excess_sharpe,
                     "ann_ret": s.ann_ret, "ann_excess_ret": s.ann_excess_ret,
                     "ann_vol": s.ann_vol, "ann_rf": s.ann_rf,
                     "cumret": s.cumret, "excess_cumret": s.excess_cumret,
                     "cagr": s.cagr, "excess_cagr": s.excess_cagr,
                     "max_dd": s.max_dd, "n_bars": s.n_bars})
    return pd.DataFrame(rows).set_index("year")
