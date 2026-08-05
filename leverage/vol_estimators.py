"""v6/leverage/vol_estimators.py — σ estimators for the M0-B diagnostic.

Four estimators, one truth proxy. On the leverage path (leverage_engine.py)
only the M0-B winner is used; this file exists so the diagnostic can put all
four on the same axes.

- ``daily_ewma_252``    old M1 — EWMA on daily returns × √252 (baseline for
                        the §四.D2 frequency-mismatch bias).
- ``weekly_ewma_52``    new M1 — EWMA on weekly returns × √52.
- ``daily_60d_252``     simple 60D rolling std × √252 (M2a vol_window echo).
- ``weekly_newey_west`` HAC-adjusted weekly σ × √52; quantifies the bias.

- ``realized_forward_ann`` truth proxy at bar t: std of weekly_ret over
                           ``(t, t+H]`` × √52.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

WEEKS_PER_YEAR = 52
DAYS_PER_YEAR  = 252


def daily_ewma_252(daily_ret: pd.Series,
                   halflife_days: int = 30,
                   min_periods: int = 30) -> pd.Series:
    """EWMA on daily returns × √252. §四.D2 baseline (biased for
    serially-correlated bond returns)."""
    var = (daily_ret ** 2).ewm(halflife=halflife_days,
                               min_periods=min_periods).mean()
    return np.sqrt(var * DAYS_PER_YEAR)


def weekly_ewma_52(weekly_ret: pd.Series,
                   halflife_weeks: int = 26,
                   min_periods: int = 13) -> pd.Series:
    """EWMA on weekly returns × √52. New M1."""
    var = (weekly_ret ** 2).ewm(halflife=halflife_weeks,
                                min_periods=min_periods).mean()
    return np.sqrt(var * WEEKS_PER_YEAR)


def daily_60d_252(daily_ret: pd.Series,
                  window: int = 60,
                  min_periods: int = 30) -> pd.Series:
    """Simple 60D rolling std × √252 (mirrors M2a's vol_window default)."""
    return (daily_ret.rolling(window, min_periods=min_periods).std()
            * np.sqrt(DAYS_PER_YEAR))


def weekly_newey_west(weekly_ret: pd.Series,
                      window: int = 52,
                      lags: int = 4,
                      min_periods: int = 26) -> pd.Series:
    """HAC-adjusted weekly σ × √52. Bartlett kernel over ``lags`` lags on
    a rolling ``window``-bar window."""
    def _nw_var(x: np.ndarray) -> float:
        x = x[~np.isnan(x)]
        n = len(x)
        if n <= lags:
            return np.nan
        x = x - x.mean()
        g0 = (x * x).mean()
        s = g0
        for l in range(1, lags + 1):
            w = 1.0 - l / (lags + 1)
            gl = (x[l:] * x[:-l]).mean()
            s += 2.0 * w * gl
        return float(s)

    var = weekly_ret.rolling(window, min_periods=min_periods).apply(
        _nw_var, raw=True
    ).clip(lower=0.0)
    return np.sqrt(var * WEEKS_PER_YEAR)


def realized_forward_ann(weekly_ret: pd.Series,
                         horizon_weeks: int = 4) -> pd.Series:
    """Truth proxy: at bar t, std of ``weekly_ret[t+1 : t+H+1]`` × √52.

    Implementation: rolling(H).std() at position t = std over (t-H+1, ..., t];
    shifting by -H makes position t hold the value from position t+H = std
    over (t+1, ..., t+H). Exactly the forward window we want.
    """
    fwd = (weekly_ret.rolling(horizon_weeks, min_periods=horizon_weeks)
                     .std()
                     .shift(-horizon_weeks))
    return fwd * np.sqrt(WEEKS_PER_YEAR)


ESTIMATORS = {
    "daily_ewma_252":    ("daily",  daily_ewma_252),
    "weekly_ewma_52":    ("weekly", weekly_ewma_52),
    "daily_60d_252":     ("daily",  daily_60d_252),
    "weekly_newey_west": ("weekly", weekly_newey_west),
}
