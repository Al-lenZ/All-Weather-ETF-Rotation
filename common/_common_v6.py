"""
v6/common/_common_v6.py
=======================
Shared utilities for the v6 XS-IC pipeline.

Ported from v4pool/xs_ic_pipeline/scripts/_common.py at Phase 0, extended
in Phase 5 for ragged-panel aggregation. Backward-compatible callers
(``ic_summary(series)`` with no ``n_per_bar``, ``precision_at_k``,
``load_universe()`` with no ``version``) reproduce v4 semantics bit-for-bit;
Phase 5.5 pins that with a regression test.

Phase 5 additions (design §5):
- ``apply_membership(panel, membership)`` — mask non-member cells (§5.1).
- ``ic_summary(series, n_per_bar=...)`` — adds ragged zstat / mean_ic_w /
  mean_N and auxiliary rolling-52w summaries when ``n_per_bar`` is supplied
  (§5.2).
- ``precision_at_q(alpha, target, q, ...)`` — quantile-K precision, replaces
  fixed-K in v6 sweeps; ``precision_at_k`` stays as a shim (§5.3).
- ``load_universe(version="v4"|"v6")`` — v4 signature default, v6 loads
  the persisted MEMBERSHIP + block tags (§5.4).

Design references
-----------------
- Stage-1 per-name normalization: expanding-z, min_periods=26.
- Stage-2 per-bar CS Gaussian rank: (rank - 0.5) / n_valid, then norm.ppf.
- Vol proxy for the label: causal 26-week trailing std of weekly log returns.
- Label ỹ: per-bar CS Gaussian rank of (fwd_1w / σ_causal).
"""
from __future__ import annotations

# --- path preamble -------------------------------------------------------
# File lives at .../etf_basket_strategy/v6/common/_common_v6.py
#   parents[0] = v6/common
#   parents[1] = v6
#   parents[2] = repo root (etf_basket_strategy)
import sys
from pathlib import Path
_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[2]
sys.path.insert(0, str(_REPO / "v5" / "static"))         # xs_engine_v5 lives here
sys.path.insert(0, str(_REPO / "v5" / "return_model"))
sys.path.insert(0, str(_REPO / "v5"))
sys.path.insert(0, str(_REPO / "v4"))                    # universe_v4 (v4 path in load_universe)
sys.path.insert(0, str(_HERE.parent))                    # v6/common — shared v6 modules
# All experiment scripts/ folders — enables cross-experiment sibling imports
# (e.g. block_two_layer_v6 → within_block_ensemble_v6, exp2 → block_two_layer_v6).
for _exp_scripts in sorted((_HERE.parents[1]).glob("*/scripts")):
    sys.path.insert(0, str(_exp_scripts))
sys.path.insert(0, str(_REPO))                           # repo root: etf_io, factors, _bootstrap
# -------------------------------------------------------------------------

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, norm, rankdata

# Fixed defaults, mirror the design doc §2-§3, §6.
IN_SAMPLE_END = pd.Timestamp("2023-12-31")
# OOS covers 2024-01-01 → OOS_END; the untouched hold-out sealed from any
# tuning starts the day after OOS_END. Do not extend OOS_END without
# explicit sign-off — every look at post-OOS_END data burns statistical
# power that later confirmatory runs will need.
OOS_START     = pd.Timestamp("2024-01-01")
OOS_END       = pd.Timestamp("2025-07-31")
HOLDOUT_START = pd.Timestamp("2025-08-01")
REBAL_FREQ    = "W-FRI"
DATA_FREQ     = "1d"
Z_MIN_PERIODS = 26     # stage-1 expanding-z warmup
VOL_WINDOW    = 26     # weekly bars for causal trailing σ
K_TOP         = 5      # legacy default (Phase 5 replaces with quantile Q)
WEEKS_PER_YEAR = 52    # annualization factor for W-FRI Sharpe

PIPELINE_ROOT = _HERE.parents[1]                # v6/
DATA_DIR      = PIPELINE_ROOT / "data"
REPORTS_DIR   = PIPELINE_ROOT / "reports"


# ---------------------------------------------------------------------- #
# Stage 1 — per-name causal expanding z
# ---------------------------------------------------------------------- #
def expanding_z(df: pd.DataFrame, min_periods: int = Z_MIN_PERIODS
                ) -> pd.DataFrame:
    """Column-wise expanding causal z-score."""
    def _z(s: pd.Series) -> pd.Series:
        mu = s.expanding(min_periods=min_periods).mean()
        sd = s.expanding(min_periods=min_periods).std()
        return (s - mu) / sd
    return df.apply(_z, axis=0)


# ---------------------------------------------------------------------- #
# Stage 2 — per-bar cross-sectional Gaussian rank
# ---------------------------------------------------------------------- #
def cs_gaussian_rank(df: pd.DataFrame, min_valid: int = 3) -> pd.DataFrame:
    """For each row, rank finite entries (average-ties), compute
    (rank - 0.5) / n_valid, apply norm.ppf. NaN rows or rows with < min_valid
    finite entries produce all-NaN output for that row.

    Output is approximately N(0, 1) per bar, mean-zero within-bar.
    """
    vals = df.to_numpy(dtype=float, copy=True)
    T, N = vals.shape
    out = np.full((T, N), np.nan, dtype=float)
    for t in range(T):
        row = vals[t]
        finite = np.isfinite(row)
        n = int(finite.sum())
        if n < min_valid:
            continue
        r = rankdata(row[finite], method="average")   # 1..n_valid
        u = (r - 0.5) / n
        out[t, finite] = norm.ppf(u)
    return pd.DataFrame(out, index=df.index, columns=df.columns)


# ---------------------------------------------------------------------- #
# Membership masking  (Phase 5.1 — ragged-panel enforcement)
# ---------------------------------------------------------------------- #
def apply_membership(panel: pd.DataFrame,
                     membership: pd.DataFrame) -> pd.DataFrame:
    """Return `panel` with entries NaN'd out where membership is False.

    Membership is aligned to `panel`'s (index, columns); unaligned entries
    default to False (fully excluded). Downstream stage-2 builders and IC
    computations must run on a membership-masked panel so ragged N_t is
    honored per bar (design §5).
    """
    m = (membership.reindex(index=panel.index, columns=panel.columns)
                   .astype("boolean")
                   .fillna(False)
                   .to_numpy(dtype=bool, na_value=False))
    return panel.where(m)


# ---------------------------------------------------------------------- #
# Forward return + causal vol proxy + ranked risk-adj label ỹ
# ---------------------------------------------------------------------- #
def forward_1w(price_daily: pd.DataFrame,
               rebal_idx: pd.DatetimeIndex) -> pd.DataFrame:
    """`fwd_1w_{i,t} = close_{i,t+1} / close_{i,t} - 1` on the W-FRI grid."""
    w = price_daily.reindex(rebal_idx)
    return w.pct_change(1).shift(-1)


def realized_vol_trailing(price_daily: pd.DataFrame,
                          rebal_idx: pd.DatetimeIndex,
                          window: int = VOL_WINDOW) -> pd.DataFrame:
    """Causal 26-week trailing std of weekly log returns, per ETF.

    σ_{i,t} uses log returns up to and including bar t. min_periods = window,
    so σ is only defined once `window` prior weekly bars exist.
    """
    w = price_daily.reindex(rebal_idx)
    logret = np.log(w / w.shift(1))
    return logret.rolling(window=window, min_periods=window).std()


def ranked_risk_adj_label(fwd_1w: pd.DataFrame,
                          sigma: pd.DataFrame,
                          eps: float = 1e-12) -> pd.DataFrame:
    """ỹ = per-bar CS Gaussian rank of (fwd_1w / σ_causal).

    σ = 0 or NaN → NaN in the ratio → dropped from the row's rank.

    v1 label — re-adopted in v6 (design §3).
    """
    sig = sigma.where(sigma > eps)
    ratio = fwd_1w / sig
    return cs_gaussian_rank(ratio)


def ranked_raw_label(fwd_1w: pd.DataFrame) -> pd.DataFrame:
    """ỹ = per-bar CS Gaussian rank of raw fwd_1w.

    v2 label — retained for the v2 diff-check only; v6 uses
    ``ranked_risk_adj_label``.
    """
    return cs_gaussian_rank(fwd_1w)


# ---------------------------------------------------------------------- #
# Rolling causal OLS beta (external-projection §3.1)
# ---------------------------------------------------------------------- #
def rolling_beta(returns: pd.DataFrame,
                 driver: pd.Series,
                 window: int) -> pd.DataFrame:
    """Rolling OLS slope β̂_{i,t} of each column of `returns` on `driver`.

    Strictly causal: β̂_{i,t} uses observations at τ ∈ [t-window, t-1] only.
    """
    idx = returns.index
    x = driver.reindex(idx).astype(float)
    x_lag = x.shift(1)

    n_scalar     = x_lag.notna().astype(float).rolling(window, min_periods=window).sum()
    sum_x        = x_lag.rolling(window, min_periods=window).sum()
    sum_x2       = (x_lag ** 2).rolling(window, min_periods=window).sum()
    denom_scalar = sum_x2 - (sum_x ** 2) / n_scalar
    denom_scalar = denom_scalar.where(denom_scalar > 0)

    sum_y  = returns.rolling(window, min_periods=window).sum()
    xy     = returns.mul(x_lag, axis=0)
    sum_xy = xy.rolling(window, min_periods=window).sum()

    num  = sum_xy.sub(sum_y.mul(sum_x, axis=0).div(n_scalar, axis=0))
    beta = num.div(denom_scalar, axis=0)
    return beta


# ---------------------------------------------------------------------- #
# Per-bar diagnostics — Spearman IC, precision@k
# ---------------------------------------------------------------------- #
def per_bar_spearman(alpha: pd.DataFrame,
                     target: pd.DataFrame,
                     min_valid: int = 5) -> pd.Series:
    """Per-bar Spearman(alpha[t,:], target[t,:]) across the cross-section."""
    idx = alpha.index.intersection(target.index)
    cols = alpha.columns.intersection(target.columns)
    A = alpha.loc[idx, cols].to_numpy(dtype=float)
    B = target.loc[idx, cols].to_numpy(dtype=float)
    out = np.full(len(idx), np.nan, dtype=float)
    for i in range(len(idx)):
        a, b = A[i], B[i]
        m = np.isfinite(a) & np.isfinite(b)
        if int(m.sum()) < min_valid:
            continue
        aa, bb = a[m], b[m]
        if np.nanstd(aa) == 0.0 or np.nanstd(bb) == 0.0:
            continue
        rho, _ = spearmanr(aa, bb)
        out[i] = float(rho)
    return pd.Series(out, index=idx, name="ic")


def precision_at_q(alpha: pd.DataFrame,
                   target: pd.DataFrame,
                   q: float,
                   side: str = "top",
                   membership: pd.DataFrame | None = None,
                   min_valid_q: float = 0.5) -> pd.Series:
    """Per-bar quantile precision: |top-⌈q·N_t⌉ predicted ∩ top-⌈q·N_t⌉ true|
    / ⌈q·N_t⌉, or bottom-⌈q·N_t⌉ variant.

    ``N_t`` counts names with both alpha and target defined at bar t after the
    optional membership mask. Bars with ``N_t < max(2, ⌈min_valid_q / q⌉)``
    are skipped — that keeps ⌈q·N_t⌉ ≥ 1 and demands at least one full
    "slot's worth" of names.  E.g. q=0.20, min_valid_q=0.5 → skip bars with
    N_t < 3.

    Phase 5.3 replaces the fixed-K ``precision_at_k`` for v6 downstream code
    (design §7). The old function stays as a shim over the k-based
    implementation for v4pool call sites.
    """
    if side not in ("top", "bottom"):
        raise ValueError("side must be 'top' or 'bottom'")
    if not (0.0 < q <= 1.0):
        raise ValueError("q must be in (0, 1]")
    idx  = alpha.index.intersection(target.index)
    cols = alpha.columns.intersection(target.columns)
    A = alpha.loc[idx, cols]
    B = target.loc[idx, cols]
    if membership is not None:
        M = (membership.reindex(index=idx, columns=cols)
                       .astype("boolean").fillna(False))
        A = A.where(M); B = B.where(M)
    min_N = max(2, int(np.ceil(min_valid_q / q)))
    out = np.full(len(idx), np.nan, dtype=float)
    for i, t in enumerate(idx):
        a = A.iloc[i]; b = B.iloc[i]
        both = a.notna() & b.notna()
        n = int(both.sum())
        if n < min_N:
            continue
        k = int(np.ceil(q * n))
        aa = a[both]; bb = b[both]
        if side == "top":
            pa = set(aa.nlargest(k).index)
            pb = set(bb.nlargest(k).index)
        else:
            pa = set(aa.nsmallest(k).index)
            pb = set(bb.nsmallest(k).index)
        out[i] = len(pa & pb) / k
    return pd.Series(out, index=idx, name=f"prec_{side}_q{int(round(q*100)):02d}")


def precision_at_k(alpha: pd.DataFrame,
                   target: pd.DataFrame,
                   k: int = K_TOP,
                   side: str = "top",
                   min_valid: int = 10) -> pd.Series:
    """Per-bar |top-k predicted ∩ top-k true| / k, or bottom-k variant.

    Legacy v4 shape — v6 sweeps use ``precision_at_q``. Kept unchanged (not
    delegated to ``precision_at_q``) so v4pool reruns reproduce the original
    CSVs bit-for-bit."""
    if side not in ("top", "bottom"):
        raise ValueError("side must be 'top' or 'bottom'")
    idx  = alpha.index.intersection(target.index)
    cols = alpha.columns.intersection(target.columns)
    A = alpha.loc[idx, cols]
    B = target.loc[idx, cols]
    out = np.full(len(idx), np.nan, dtype=float)
    for i, t in enumerate(idx):
        a = A.iloc[i]
        b = B.iloc[i]
        both = a.notna() & b.notna()
        n = int(both.sum())
        if n < min_valid:
            continue
        aa = a[both]
        bb = b[both]
        if side == "top":
            pa = set(aa.nlargest(k).index)
            pb = set(bb.nlargest(k).index)
        else:
            pa = set(aa.nsmallest(k).index)
            pb = set(bb.nsmallest(k).index)
        out[i] = len(pa & pb) / k
    return pd.Series(out, index=idx, name=f"prec_{side}{k}")


# ---------------------------------------------------------------------- #
# IC series summary
# ---------------------------------------------------------------------- #
ROLLING_IC_WINDOW = 52    # weekly bars; ~1y auxiliary rank-IC window (§5.2)
ROLLING_IC_MIN_COVERAGE = 0.75   # ≥ this fraction of the window must be defined

def rolling_ic(series: pd.Series,
               window: int = ROLLING_IC_WINDOW,
               min_periods: int | None = None) -> pd.Series:
    """Trailing-`window` mean of the per-bar IC series.

    ``min_periods`` defaults to ``ceil(ROLLING_IC_MIN_COVERAGE * window)``
    (75% coverage → 39 of 52 defined bars). Requiring 100% coverage
    (``min_periods = window``) is the v4 convention but produces all-NaN
    rolling series on v6's ragged panel, where early-year small-N bars leave
    scattered NaNs in the IC series. A coverage threshold keeps the
    calendar-time semantic without silently dropping every window.

    Auxiliary metric — the primary z-stat gate lives in ``ic_summary``.
    """
    if min_periods is None:
        min_periods = max(1, int(np.ceil(ROLLING_IC_MIN_COVERAGE * window)))
    return series.sort_index().rolling(window, min_periods=min_periods).mean()


def ic_summary(series: pd.Series,
               n_per_bar: pd.Series | None = None,
               roll_window: int = ROLLING_IC_WINDOW) -> dict:
    """IC series summary.

    Legacy path (``n_per_bar=None``) returns the v4 dict and is byte-for-byte
    identical to the original ``_common.ic_summary``. Passing ``n_per_bar``
    activates the Phase 5.2 ragged-panel additions:

      z_t   = ic_t · sqrt(N_t − 1)                # ≈ N(0,1) under null
      Z     = mean(z_t) · sqrt(T)                 # panel z-score
      ic_w  = Σ w_t ic_t / Σ w_t,  w_t = N_t − 1  # effective mean IC

    plus auxiliary rolling-window summaries of the per-bar IC series (default
    52w ≈ 1y):

      mean_ic_52w  = mean over defined windows
      min_ic_52w   = min
      max_ic_52w   = max
      pct_pos_52w  = fraction of defined windows with mean IC > 0

    Rolling metrics answer the "does the factor stay positive across a year
    of bars, or is it a boom-then-fade signal" question without changing the
    primary screening bar.
    """
    s = series.dropna()
    n = int(len(s))
    legacy_empty = {"n_bars": 0, "mean": np.nan, "std": np.nan,
                    "tstat": np.nan, "pct_pos": np.nan}
    if n == 0:
        if n_per_bar is None:
            return legacy_empty
        return {**legacy_empty,
                "zstat": np.nan, "mean_ic_w": np.nan, "mean_N": np.nan,
                "mean_ic_52w": np.nan, "min_ic_52w": np.nan,
                "max_ic_52w": np.nan, "pct_pos_52w": np.nan}
    mean = float(s.mean())
    std  = float(s.std(ddof=1)) if n > 1 else np.nan
    tstat = (mean / (std / np.sqrt(n))) if (std and std > 0) else np.nan
    base = {"n_bars": n, "mean": mean, "std": std,
            "tstat": tstat, "pct_pos": float((s > 0).mean())}
    if n_per_bar is None:
        return base

    # Ragged-panel aggregation on bars where both ic and N_t are defined
    # and N_t > 1 (below that the z_t normalization is degenerate).
    N_t = n_per_bar.reindex(s.index).astype(float)
    valid = N_t.notna() & (N_t > 1.0)
    ic_v = s[valid]
    N_v  = N_t[valid]
    if len(ic_v) == 0:
        z_ext = {"zstat": np.nan, "mean_ic_w": np.nan, "mean_N": np.nan}
    else:
        z_t = ic_v * np.sqrt(N_v - 1.0)
        T = float(len(z_t))
        w = (N_v - 1.0)
        zstat = float(z_t.mean() * np.sqrt(T))
        mean_ic_w = float((w * ic_v).sum() / w.sum()) if float(w.sum()) > 0 else np.nan
        mean_N = float(N_v.mean())
        z_ext = {"zstat": zstat, "mean_ic_w": mean_ic_w, "mean_N": mean_N}

    roll = rolling_ic(series, window=roll_window).dropna()
    if len(roll) == 0:
        aux = {"mean_ic_52w": np.nan, "min_ic_52w": np.nan,
               "max_ic_52w": np.nan, "pct_pos_52w": np.nan}
    else:
        aux = {"mean_ic_52w": float(roll.mean()),
               "min_ic_52w":  float(roll.min()),
               "max_ic_52w":  float(roll.max()),
               "pct_pos_52w": float((roll > 0).mean())}
    return {**base, **z_ext, **aux}


def per_bar_n_valid(alpha: pd.DataFrame,
                    target: pd.DataFrame,
                    membership: pd.DataFrame | None = None) -> pd.Series:
    """Per-bar N_t := number of names with both alpha and target defined
    (post-membership mask if supplied). Companion to ``per_bar_spearman`` for
    Phase 5.2 z-stat aggregation."""
    idx  = alpha.index.intersection(target.index)
    cols = alpha.columns.intersection(target.columns)
    A = alpha.loc[idx, cols]
    B = target.loc[idx, cols]
    if membership is not None:
        M = (membership.reindex(index=idx, columns=cols)
                       .astype("boolean").fillna(False))
        A = A.where(M); B = B.where(M)
    n = (A.notna() & B.notna()).sum(axis=1).astype(int)
    n.name = "n_valid"
    return n


# ---------------------------------------------------------------------- #
# Universe helper — v4 default, v6 loads persisted MEMBERSHIP  (Phase 5.4)
# ---------------------------------------------------------------------- #
def load_universe(version: str = "v4"):
    """Universe loader with version dispatch.

    ``version="v4"`` (default):
        Returns ``(CODES, MARKET_TAG)`` — bit-for-bit compatible with the
        v4pool ``_common.load_universe()`` signature. Every v4pool caller is
        ``codes, blocks = C.load_universe()``, so keeping v4 as default
        preserves the regression path (§5.5).

    ``version="v6"``:
        Returns ``(CODES, BLOCK_TAG, MEMBERSHIP)``. Loads the persisted
        Phase-3 artifacts from ``DATA_DIR / "universe_v6"``. ``MEMBERSHIP``
        is a ``W-FRI × code`` bool DataFrame; ``CODES`` is the union of
        names ever admitted; ``BLOCK_TAG`` maps ``code → block``.
    """
    if version == "v4":
        from universe_v4 import CODES, MARKET_TAG  # type: ignore
        return list(CODES), dict(MARKET_TAG)
    if version == "v6":
        from universe_v6 import load_persisted  # type: ignore
        membership, codes, block_tag, _index_of, _name_en = load_persisted(
            DATA_DIR / "universe_v6"
        )
        return list(codes), dict(block_tag), membership
    raise ValueError(f"load_universe: unknown version {version!r}")


# ---------------------------------------------------------------------- #
# v6 factor-cache loaders  (Phase 4.4)
# ---------------------------------------------------------------------- #
# Mirror etf_io.load_caches / common_factors / build_alpha_panel, but point
# at v6/data/factor_cache/ instead of the global data/factors_cache/. Keeps
# v4pool's cache untouched and makes the v6 sweeps hermetic.
V6_PX_DIR    = DATA_DIR / "px_daily"
V6_CACHE_DIR = DATA_DIR / "factor_cache"


def _v6_code_to_stub(code: str) -> str:
    """`159007.XSHE` → `159007_XSHE` (matches split_px_v6 / compute_factors_v6)."""
    return code.replace(".", "_")


def _v6_cache_path(code: str, freq: str):
    return V6_CACHE_DIR / f"{_v6_code_to_stub(code)}_{freq}.parquet"


def _v6_price_path(code: str):
    return V6_PX_DIR / f"{_v6_code_to_stub(code)}.parquet"


def load_caches_v6(freq: str, codes):
    """code -> wide factor matrix (index=time, cols=factor names).

    Parquets missing on disk are silently skipped so a partially-built cache
    (e.g., an in-flight Phase 4 run) still returns whatever's ready.
    """
    caches = {}
    for c in codes:
        p = _v6_cache_path(c, freq)
        if p.exists():
            caches[c] = pd.read_parquet(p)
    return caches


def load_price_panel_v6(codes, price_col: str = "close"):
    """Wide close-price panel, columns = codes, index = intersection of bars
    where every requested code has data. Matches ``etf_io.load_price_panel``
    intersection semantics."""
    cols = {}
    for c in codes:
        p = _v6_price_path(c)
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        if price_col in df.columns and not df[price_col].dropna().empty:
            cols[c] = df[price_col]
    if not cols:
        return pd.DataFrame()
    panel = pd.DataFrame(cols).sort_index()
    return panel.dropna(how="any")


def load_price_panel_v6_ragged(codes, price_col: str = "close"):
    """Wide price panel, columns = codes, index = union of bars where any
    requested code has data. Ragged — missing (bar, code) entries stay NaN.

    Use this for v6 ragged-universe pipelines (Phase 6+); intersection
    semantics (``load_price_panel_v6``) would drop almost every bar for a
    344-code pool with staggered list dates.
    """
    cols = {}
    for c in codes:
        p = _v6_price_path(c)
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        if price_col in df.columns and not df[price_col].dropna().empty:
            cols[c] = df[price_col]
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).sort_index()


def common_factors_v6(caches):
    """Factor names present in EVERY code's cache. Verbatim ``etf_io.common_factors``.
    Provided here so v6 consumers only import from ``_common_v6``."""
    if not caches:
        return []
    sets = [set(df.columns) for df in caches.values()]
    return sorted(set.intersection(*sets))


def build_alpha_panel_v6(caches, factor: str, index):
    """One factor's value across the pool → T×N panel on ``index``.
    Verbatim ``etf_io.build_alpha_panel``."""
    cols = {}
    for c, df in caches.items():
        if factor in df.columns:
            cols[c] = df[factor].reindex(index)
    return pd.DataFrame(cols, index=index)
