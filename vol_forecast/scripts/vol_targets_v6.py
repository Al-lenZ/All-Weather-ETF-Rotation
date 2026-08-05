"""
v6/scripts/vol_targets_v6.py
============================
Phase 10.2 — weekly realized-volatility panel on the v6 ragged pool.

Per-ETF weekly RV (annualized, Corsi weekly convention). Same estimator
as v4/vol_forecast/targets.py:

    RV_t = sqrt( Σ_d r_d² / N_d ) * sqrt(252)

- Daily log returns per ETF from ``data/px_daily/{code}_XSHG.parquet``.
- Aggregate to W-FRI: sum-of-squares over daily returns falling in
  each week ending Friday, divided by that week's non-NaN day count,
  then multiplied by √252 to annualize.
- Drop weeks with < 3 trading days (holidays / listing gaps).
- Panel is **ragged**: each ETF's series starts at its own listing +
  first observable weekly RV bar. Non-defined cells stay NaN.

Downstream filter
-----------------
Only ETFs whose lifetime RV coverage ≥ 52 weekly bars are marked as
eligible for HAR training. `data/vol_forecast_v6/rv_coverage.csv` lists
the per-code coverage and eligibility flag.

Outputs
-------
    data/vol_forecast_v6/rv_panel.parquet   — ragged weekly RV
    data/vol_forecast_v6/rv_coverage.csv    — per-code lifetime coverage
                                              (n_weeks, first, last, ≥ 52w)

Run
---
    python v6/scripts/vol_targets_v6.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

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


OUT_DIR    = C.DATA_DIR / "vol_forecast_v6"
RV_PARQUET = OUT_DIR / "rv_panel.parquet"
COV_CSV    = OUT_DIR / "rv_coverage.csv"

TRADING_DAYS_PER_YEAR = 252
MIN_DAYS_PER_WEEK     = 3
MIN_HISTORY_WEEKS     = 52   # ETFs with < this many defined RV bars are
                              # ineligible for HAR training


def _load_daily_close(codes: list[str]) -> pd.DataFrame:
    """Ragged wide close panel across ``codes``. Reuses _common_v6's
    per-code loader so we inherit the same file layout convention."""
    return C.load_price_panel_v6_ragged(codes, price_col="close")


def build_rv_panel(codes: list[str]) -> pd.DataFrame:
    """Ragged weekly RV panel over ``codes``.

    Each column is a code, index is W-FRI Fridays with at least one
    ETF's RV defined. Cells are NaN where a code has < 3 trading days
    that week (or wasn't listed yet).
    """
    daily = _load_daily_close(codes)
    if daily.empty:
        raise RuntimeError(f"no daily close prices for any of {len(codes)} codes")

    log_ret = np.log(daily / daily.shift(1))
    grouper = log_ret.index.to_period("W-FRI")

    sum_sq = log_ret.pow(2).groupby(grouper).sum(min_count=1)
    n_days = log_ret.notna().groupby(grouper).sum()

    rv = np.sqrt(sum_sq / n_days) * np.sqrt(TRADING_DAYS_PER_YEAR)
    rv = rv.where(n_days >= MIN_DAYS_PER_WEEK)
    rv.index = rv.index.to_timestamp(how="end").normalize()
    rv = rv.dropna(how="all")
    return rv


def coverage_summary(rv: pd.DataFrame) -> pd.DataFrame:
    """Per-code lifetime coverage + eligibility flag.

    A code is HAR-eligible when its lifetime RV coverage ≥ 52 weekly
    bars (the user-stated ≥ 52w-history rule).
    """
    rows = []
    for c in rv.columns:
        s = rv[c].dropna()
        first = s.index.min() if len(s) else pd.NaT
        last  = s.index.max() if len(s) else pd.NaT
        rows.append({
            "code":     c,
            "n_weeks":  int(len(s)),
            "first":    first,
            "last":     last,
            "eligible": bool(len(s) >= MIN_HISTORY_WEEKS),
        })
    return pd.DataFrame(rows).sort_values("n_weeks", ascending=False)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 74)
    print("v6 WEEKLY REALIZED-VOL PANEL (ragged)")
    print("=" * 74)

    # Universe = every code ever a member (matches downstream book pool).
    mem = pd.read_parquet(C.DATA_DIR / "universe_v6" / "membership.parquet")
    codes = list(mem.columns[mem.any(axis=0)])
    print(f"  admitted codes: {len(codes)}")

    rv = build_rv_panel(codes)
    rv = rv.reindex(columns=codes)      # keep column order stable
    rv.to_parquet(RV_PARQUET)
    print(f"  wrote {RV_PARQUET.name}   shape={rv.shape}  "
          f"({rv.index.min().date()} → {rv.index.max().date()})")

    cov = coverage_summary(rv)
    cov.to_csv(COV_CSV, index=False)
    n_elig = int(cov["eligible"].sum())
    print(f"  wrote {COV_CSV.name}      "
          f"eligible (≥ {MIN_HISTORY_WEEKS}w): {n_elig}/{len(cov)}")

    print()
    print("  coverage distribution (weeks defined per code):")
    print(cov["n_weeks"].describe().apply(lambda x: f"    {x:.1f}").to_string())


if __name__ == "__main__":
    main()
