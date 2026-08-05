"""
v6/scripts/vol_har_block_v6.py
==============================
Phase 10.2 — block-pooled HAR-RV forecaster.

Three separate HAR fits — one per block (equity / bond / alt) — on the
v6 ragged RV panel. Within each block:

  - Shared β_1w, β_4w, β_13w across the block's ETFs (Corsi weekly HAR).
  - Per-ETF fixed effect (one intercept per ETF in the block).
  - Walk-forward expanding fit, min_train = 52 weeks, refit every 4w.
  - **Weighted OLS** so each ETF contributes equal total sample weight
    within its block regardless of history length. Per-obs weight for
    ETF i at refit r is::

        w_{i, r} = 1 / (n_etfs_in_block × T_{i, r}^{train})

    so that Σ_rows w = 1 per block (assumed by [[project-har-blockbalanced]]:
    "Equity total = Bond total = Alt total = 1").

Because blocks are fit independently, the constant "1 per block" doesn't
affect the OLS solution within a block — it makes the *relative* ETF
weighting equal, which does matter when history length differs
substantially between ETFs (e.g. an equity ETF with 300 bars vs a
newer one with 70 bars).

Pure functions
--------------
- `gaussian_rank_transform` / `gaussian_rank_invert`: causal 52w
  rank-Gaussian normalization on a single log-σ series. Copied into
  v6 (not imported from v4/vol_forecast_global/preprocess.py) so v6
  stays hermetic; kernels are identical.
- `har_features_from_norm`, `build_panel`: long-format HAR feature
  builder — one row per (etf, week) with lag_1w / lag_4w / lag_13w and
  target y = norm[t+1].
- `walk_forward_pooled_wls`: pooled OLS with per-ETF FE + shared β,
  optional per-obs weights. Falls back to plain OLS when
  `sample_weight_fn` is None.
- `denormalize`: map normalized-space forecast at feature-date t back
  to a σ level at target-date t+1 via the trailing 52w empirical CDF.

The block driver — how the three block HARs are chained into a single
wide σ̂ panel — lives in `vol_forecast_v6.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd
from scipy.stats import norm


CLIP_LOWER   = 1e-6
WINDOW       = 52         # causal rolling-window for Gaussian rank + inversion
LAGS         = (1, 4, 13)
LAG_UNIT     = "w"
MIN_TRAIN    = 52
REFIT_EVERY  = 4


# ---------------------------------------------------------------------- #
# Gaussian rank normalization (causal, 52w window)
# ---------------------------------------------------------------------- #
def gaussian_rank_transform(log_rv: pd.Series, window: int = WINDOW) -> pd.Series:
    """Causal Gaussian rank of log σ over trailing `window` obs.

    At position t: rank log_rv[t] among log_rv[t-window : t] (exclusive
    of t itself), apply midrank + continuity correction, then Φ⁻¹.
    Numerically identical to v4/vol_forecast_global/preprocess.gaussian_rank_transform.
    """
    x = log_rv.values.astype(float)
    n = len(x)
    g = np.full(n, np.nan)

    for t in range(window, n):
        curr = x[t]
        H = x[t - window : t]
        if not np.isfinite(curr) or not np.all(np.isfinite(H)):
            continue
        n_less = float(np.sum(H < curr))
        n_eq   = float(np.sum(H == curr))
        rank_c = n_less + 0.5 * n_eq
        r = (rank_c + 0.5) / (window + 1)
        g[t] = norm.ppf(r)

    return pd.Series(g, index=log_rv.index)


def gaussian_rank_invert(g_hat: float, history: np.ndarray) -> float:
    """Map ĝ back to σ level via the empirical quantile of `history`
    (the log σ window used to build day-t's rank map). Clip to
    (1/(W+1), W/(W+1)) so we never fall off the empirical support."""
    if not np.isfinite(g_hat) or history.size == 0:
        return np.nan
    H = history[np.isfinite(history)]
    if H.size == 0:
        return np.nan
    r_hat = float(norm.cdf(g_hat))
    lo = 1.0 / (H.size + 1)
    hi = H.size / (H.size + 1)
    r_hat = float(np.clip(r_hat, lo, hi))
    log_sigma_hat = float(np.quantile(H, r_hat))
    return float(np.exp(log_sigma_hat))


def build_normalized_panel(rv: pd.DataFrame,
                           window: int = WINDOW) -> pd.DataFrame:
    """Column-wise causal Gaussian rank of log σ. Ragged-safe: each ETF's
    output series is NaN'd on any bar whose trailing 52w window itself
    has NaNs (matching v4/v5 behavior)."""
    log_rv = np.log(rv.clip(lower=CLIP_LOWER))
    out = pd.DataFrame(index=rv.index, columns=rv.columns, dtype=float)
    for c in rv.columns:
        out[c] = gaussian_rank_transform(log_rv[c], window)
    return out


def leakage_test(log_rv_col: pd.Series, window: int = WINDOW) -> None:
    """Assert that normalized value at t does not depend on log_rv at
    positions ≥ t. Perturb the last obs and confirm every earlier
    normalized value is unchanged."""
    original = log_rv_col.copy()
    perturbed = original.copy()
    tail = len(perturbed) - 1
    perturbed.iloc[tail] = original.iloc[tail] + 100.0

    orig = gaussian_rank_transform(original, window)
    pert = gaussian_rank_transform(perturbed, window)
    common = orig.iloc[:tail].dropna().index.intersection(
        pert.iloc[:tail].dropna().index
    )
    diff = (orig.loc[common] - pert.loc[common]).abs().max()
    if not (np.isnan(diff) or diff < 1e-10):
        raise AssertionError(
            f"LEAKAGE: perturbing log_rv at position {tail} changed "
            f"earlier normalized values by up to {diff}"
        )


# ---------------------------------------------------------------------- #
# HAR features + long-panel builder
# ---------------------------------------------------------------------- #
def _lag_cols(lags: tuple[int, ...] = LAGS, unit: str = LAG_UNIT) -> list[str]:
    return [f"lag_{L}{unit}" for L in lags]


def har_features_from_norm(norm_s: pd.Series,
                           lags: tuple[int, ...] = LAGS,
                           unit: str = LAG_UNIT) -> pd.DataFrame:
    """HAR feature matrix on a normalized log-σ series.

    Row t: lag_1 = norm[t]; lag_L (L>1) = mean of trailing L observations.
    Target y (built separately) = norm.shift(-1) — the *next* week's
    normalized log σ. All strictly causal.
    """
    cols = {}
    for L in lags:
        name = f"lag_{L}{unit}"
        cols[name] = norm_s if L == 1 else norm_s.rolling(L, min_periods=L).mean()
    return pd.DataFrame(cols, index=norm_s.index)


def build_panel(norm_panel: pd.DataFrame,
                lags: tuple[int, ...] = LAGS,
                unit: str = LAG_UNIT) -> pd.DataFrame:
    """Long-format panel: one row per (etf, date) with HAR features and
    the next-week target y. NaN rows are dropped (an ETF starts
    contributing only once all its lag features + target exist)."""
    lag_names = _lag_cols(lags, unit)
    rows = []
    for c in norm_panel.columns:
        s = norm_panel[c].dropna()
        if s.empty:
            continue
        feat = har_features_from_norm(s, lags, unit)
        target = s.shift(-1).rename("y")
        aligned = pd.concat([feat, target], axis=1).dropna()
        aligned["etf"] = c
        aligned["date"] = aligned.index
        rows.append(aligned.reset_index(drop=True))
    if not rows:
        return pd.DataFrame(columns=["etf", "date", *lag_names, "y"])
    return pd.concat(rows, ignore_index=True)[["etf", "date", *lag_names, "y"]]


# ---------------------------------------------------------------------- #
# Weighted pooled OLS with per-ETF FE
# ---------------------------------------------------------------------- #
def _design_matrix(df_slice: pd.DataFrame,
                   etf_order: list[str],
                   lag_cols: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """[FE per etf] + lag columns. y is the target column."""
    n = len(df_slice)
    n_etf = len(etf_order)
    fe = np.zeros((n, n_etf))
    idx_of = {c: i for i, c in enumerate(etf_order)}
    fe[np.arange(n), df_slice["etf"].map(idx_of).values] = 1.0
    X = np.hstack([fe, df_slice[lag_cols].values])
    y = df_slice["y"].values
    return X, y


def _fit_ols(X: np.ndarray, y: np.ndarray,
             sample_weight: np.ndarray | None = None) -> np.ndarray:
    """(Weighted) least squares via lstsq. sqrt(w) rescaling for WLS."""
    if sample_weight is None:
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        return coef
    w = np.sqrt(np.asarray(sample_weight, dtype=float))
    coef, *_ = np.linalg.lstsq(X * w[:, None], y * w, rcond=None)
    return coef


# ---------------------------------------------------------------------- #
# Sample-weight builders
# ---------------------------------------------------------------------- #
def equal_etf_weights(train_df: pd.DataFrame,
                      etf_order: list[str]) -> np.ndarray:
    """Per-obs weight so each ETF in the block contributes total weight
    1/n_etfs — i.e., all ETFs are on equal footing regardless of how
    many training rows they have.  Sum of weights over the full training
    slice = 1.

    Formula::
        w_{i, r}(t) = 1 / (n_etfs × T_{i, r}^{train})

    where T_{i, r}^{train} is the count of training rows contributed by
    ETF i at refit r. ETFs with T_i = 0 don't appear in the training
    slice by construction.
    """
    counts = train_df["etf"].value_counts()
    n_etfs = len(etf_order)
    per_etf_row_weight = counts.rdiv(1.0).div(n_etfs)   # 1 / (n_etfs × T_i)
    return train_df["etf"].map(per_etf_row_weight).to_numpy(dtype=float)


# ---------------------------------------------------------------------- #
# Walk-forward driver
# ---------------------------------------------------------------------- #
@dataclass
class WalkForwardResult:
    predictions: pd.DataFrame     # columns: etf, feature_date, y_hat_norm
    coefs: pd.DataFrame           # index: refit_date, columns: FE_* / β_*w
    n_refits: int


def walk_forward_pooled_wls(panel: pd.DataFrame,
                            etf_order: list[str],
                            lag_cols: list[str] | None = None,
                            min_train_steps: int = MIN_TRAIN,
                            refit_every: int = REFIT_EVERY,
                            sample_weight_fn: Callable[
                                [pd.DataFrame, list[str]], np.ndarray] | None = None,
                            ) -> WalkForwardResult:
    """Walk forward over unique dates; refit every N steps.

    Same mechanics as v4/vol_forecast_global/har_pooled.walk_forward_pooled,
    but the fit is (optionally) weighted via ``sample_weight_fn``. Pass
    ``sample_weight_fn=None`` for plain OLS (v4/v5 bit-for-bit path).
    Pass ``equal_etf_weights`` for the block-balanced fit.
    """
    if lag_cols is None:
        lag_cols = _lag_cols()

    panel = panel.sort_values(["date", "etf"]).reset_index(drop=True)
    all_dates = np.array(sorted(panel["date"].unique()))
    date_pos = {d: i for i, d in enumerate(all_dates)}
    panel["date_pos"] = panel["date"].map(date_pos)

    n_etf = len(etf_order)
    fe_labels   = [f"fe_{c}" for c in etf_order]
    beta_labels = [f"β_{c.split('_')[1]}" for c in lag_cols]

    preds_rows: list[dict] = []
    coef_rows:  list[dict] = []
    coef = None
    last_refit = -10 ** 9

    for i, d in enumerate(all_dates):
        if i < min_train_steps:
            continue

        if (i - last_refit) >= refit_every or coef is None:
            train = panel[panel["date_pos"] < i]
            if len(train) < n_etf + len(lag_cols) + 10:
                continue
            X_tr, y_tr = _design_matrix(train, etf_order, lag_cols)
            w_tr = (sample_weight_fn(train, etf_order)
                    if sample_weight_fn is not None else None)
            coef = _fit_ols(X_tr, y_tr, sample_weight=w_tr)
            last_refit = i
            coef_rows.append({
                "refit_date": d,
                **{lab: coef[k]         for k, lab in enumerate(fe_labels)},
                **{lab: coef[n_etf + k] for k, lab in enumerate(beta_labels)},
            })

        curr = panel[panel["date_pos"] == i]
        if curr.empty:
            continue
        X_cur, _ = _design_matrix(curr, etf_order, lag_cols)
        y_hat = X_cur @ coef
        for row_i, (_, row) in enumerate(curr.iterrows()):
            preds_rows.append({
                "etf":          row["etf"],
                "feature_date": row["date"],
                "y_hat_norm":   float(y_hat[row_i]),
            })

    preds = pd.DataFrame(preds_rows)
    coefs = (pd.DataFrame(coef_rows).set_index("refit_date")
             if coef_rows else pd.DataFrame())
    return WalkForwardResult(predictions=preds,
                             coefs=coefs,
                             n_refits=len(coef_rows))


# ---------------------------------------------------------------------- #
# Wide-panel target-date pivot of the raw normalized forecast
# ---------------------------------------------------------------------- #
def preds_to_wide_target_norm(preds: pd.DataFrame,
                              rv: pd.DataFrame) -> pd.DataFrame:
    """Pivot ``(etf, feature_date, y_hat_norm)`` predictions into a wide
    T×N panel keyed by **target date** (the next observation in each
    ETF's own calendar), with values = ``y_hat_norm`` — i.e., HAR's
    forecast in the Gaussian-rank space it was trained in.

    Useful for percentile-space recalibration / evaluation without
    losing tail information to the empirical-quantile clip in
    ``denormalize``.
    """
    out = pd.DataFrame(index=rv.index, columns=rv.columns, dtype=float)
    per_etf_idx = {c: rv[c].dropna().index for c in rv.columns}
    for etf, sub in preds.groupby("etf"):
        idx = per_etf_idx.get(etf, pd.Index([]))
        if len(idx) == 0:
            continue
        idx_pos = {d: k for k, d in enumerate(idx)}
        for _, r in sub.iterrows():
            fd = r["feature_date"]
            if fd not in idx_pos:
                continue
            k = idx_pos[fd]
            if k + 1 >= len(idx):
                continue
            y_hat = r["y_hat_norm"]
            if not np.isfinite(y_hat):
                continue
            out.at[idx[k + 1], etf] = float(y_hat)
    return out


# ---------------------------------------------------------------------- #
# Denormalization: normalized forecast at feature-date t → σ at t+1
# ---------------------------------------------------------------------- #
def denormalize(preds: pd.DataFrame,
                rv: pd.DataFrame,
                window: int = WINDOW) -> pd.DataFrame:
    """(etf, feature_date, y_hat_norm) → per-ETF σ̂ indexed by target
    date (= next observation in that ETF's own calendar).

    Uses the trailing `window` log σ values (up to and including target
    date) as the inversion history — matches v4/v5 gaussian_rank_invert
    convention.
    """
    log_rv = np.log(rv.clip(lower=CLIP_LOWER))
    out = pd.DataFrame(index=rv.index, columns=rv.columns, dtype=float)
    per_etf_idx = {c: rv[c].dropna().index for c in rv.columns}

    for etf, sub in preds.groupby("etf"):
        idx = per_etf_idx.get(etf, pd.Index([]))
        if len(idx) == 0:
            continue
        idx_pos = {d: k for k, d in enumerate(idx)}
        for _, r in sub.iterrows():
            fd = r["feature_date"]
            if fd not in idx_pos:
                continue
            k = idx_pos[fd]
            if k + 1 >= len(idx):
                continue
            target_date = idx[k + 1]
            y_hat = r["y_hat_norm"]
            if not np.isfinite(y_hat) or k + 1 - window < 0:
                continue
            H = log_rv[etf].iloc[k + 1 - window : k + 1].values
            sigma_hat = gaussian_rank_invert(y_hat, H)
            out.at[target_date, etf] = sigma_hat
    return out
