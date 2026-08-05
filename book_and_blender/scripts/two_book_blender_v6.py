"""
v6/scripts/two_book_blender_v6.py
=================================
Two-book blender for Phase 11.2. Combines an aggressive-book weight
panel (rank_prop sizing) and a defensive-book weight panel (1/σ
sizing) via a per-bar scalar λ ∈ [0, 1]:

    W_blend[t] = λ[t] · W_aggressive[t] + (1 − λ[t]) · W_defensive[t]

λ is driven by an **equity-block risk score** — the equal-weight mean
of σ across all equity-block member ETFs at bar t (equity blocks =
`broad_cn`, `sector_cn`, `smallcap_cn`, `cross_border_dm`,
`cross_border_hk`; bonds / metals / commodities are excluded per
[[project-phase-8-state]] §11.2 spec).

The score is normalized to an **expanding causal percentile rank**
(range [0, 1]) so 0.3 / 0.9 are meaningful gate thresholds regardless
of the underlying σ units. Raw σ mean is ~0.03 (weekly) — see the
Phase 11 report kickoff diagnostic.

λ schedule (continuous piecewise, per user spec)
------------------------------------------------
    score < 0.3               →  λ = 1                (full aggressive)
    0.3 ≤ score ≤ 0.9         →  λ = (0.9 − score) / 0.6
    score > 0.9               →  λ = 0                (full defensive)

Vol-source variants (drives the "oracle vs realistic" comparison)
-----------------------------------------------------------------
- ``causal``       : σ = σ_causal_26w at bar t (realistic — the sizing
                     kernel's own 26w trailing estimator; no forecast).
- ``fwd_1w_rv``    : σ = actual weekly realized RV at bar t+1 (proper
                     oracle — this is what HAR would target if HAR
                     were perfect. Source: `vol_forecast_v6/rv_panel.parquet`,
                     which stores annualized weekly RV per ETF).
- ``fwd_4w_rv``    : σ = mean of realized weekly RV over bars t+1..t+4
                     (4-week oracle — the "next several weeks" version
                     called out at kickoff, computed on actual RV not
                     shifted trailing σ).

The shifted-trailing-σ variants (``fwd_1w`` / ``fwd_4w``) from an
earlier revision were wrong for two reasons: (a) they used a slow-
moving 26w window instead of the actual weekly RV that HAR predicts;
(b) the fwd_4w rolling window was accidentally backward-looking due
to a shift ordering bug. They were removed.

Membership consistency
----------------------
Membership is applied *before* the σ shift, so at bar t under a
forward-looking vol_source we mask by membership at t+1 (or t+1..t+4).
This is intentional — the oracle "knows next week's σ" AND "knows
which ETFs will be members next week." For the causal source both are
at bar t.

Shared-book construction
------------------------
Both books use the **same selection + hysteresis** (from
`hysteresis_engine_v6_sizing.build_hysteresis_weights_sized`; see the
Phase 11.1 report's "structural questions" — sharing the held set
means selection cost is paid once, and the blend's `Δw` netting
handles the "same cadence" question naturally).

Since W_agg and W_def both sum to 1 per bar, the convex combination
sums to 1 per bar as well — the blend is always long-only, gross 1.
Turnover is computed on the blended weight panel, so shared-name Δw
naturally nets across the two legs.
"""
from __future__ import annotations

import warnings
from typing import Literal

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
import _common_v6 as C  # noqa: F401


EQUITY_BLOCKS = (
    "broad_cn",
    "sector_cn",
    "smallcap_cn",
    "cross_border_dm",
    "cross_border_hk",
)

# vol_source ∈ VOL_SOURCES. See module docstring.
VOL_SOURCES = ("causal", "fwd_1w_rv", "fwd_4w_rv")
_ORACLE_SOURCES = ("fwd_1w_rv", "fwd_4w_rv")   # need rv_panel

LOWER_GATE = 0.30      # score < → λ = 1 (full aggressive, non-inverted)
UPPER_GATE = 0.90      # score > → λ = 0 (full defensive, non-inverted)
MIN_HISTORY = 26       # bars of history before the percentile is trusted
WARMUP_LAMBDA = 0.5    # neutral warmup — same value for both directions
                       # so naive vs inverted are apples-to-apples during
                       # the min_history bars before the gate fires.


# ---------------------------------------------------------------------- #
# Risk score
# ---------------------------------------------------------------------- #
def equity_risk_score_raw(sigma: pd.DataFrame,
                          membership: pd.DataFrame,
                          block_tag: pd.Series,
                          vol_source: str = "causal",
                          rv_panel: pd.DataFrame | None = None) -> pd.Series:
    """Per-bar equal-weight mean σ across equity-block member ETFs.

    Parameters
    ----------
    sigma        : T × N σ panel — the causal trailing estimator
                   (v6 uses ``sigma_causal_26w``; weekly σ units,
                   ~0.03 typical for equity ETFs). Drives the ``causal``
                   source and provides the T×N index/columns skeleton
                   the other sources reindex against.
    membership   : T × N bool mask.
    block_tag    : Series (code → block name).
    vol_source   : one of ``VOL_SOURCES``. Oracle sources need rv_panel.
    rv_panel     : T × N annualized weekly realized RV panel — required
                   for ``fwd_1w_rv`` / ``fwd_4w_rv``. Source:
                   ``vol_forecast_v6/rv_panel.parquet``.

    Returns
    -------
    Series indexed by the σ panel's date index. NaN on bars where no
    equity-block member is eligible or the required RV lookahead is
    beyond the RV panel's coverage.

    Membership consistency: the equity mask is applied *before* any
    shift/rolling, so under an oracle source at bar t we get σ or RV
    at t+k masked by membership at t+k. That is intentional and
    documented in the module header.
    """
    if vol_source not in VOL_SOURCES:
        raise ValueError(f"vol_source must be one of {VOL_SOURCES}, got {vol_source!r}")
    if vol_source in _ORACLE_SOURCES and rv_panel is None:
        raise ValueError(f"vol_source={vol_source!r} requires rv_panel argument")

    idx  = sigma.index
    cols = sigma.columns
    M = (membership.reindex(index=idx, columns=cols)
                   .astype("boolean").fillna(False).astype(bool))

    equity_codes = [c for c in cols if block_tag.get(c, "") in EQUITY_BLOCKS]
    if not equity_codes:
        raise ValueError("no equity-block codes found in sigma columns")

    if vol_source == "causal":
        S_eq = sigma[equity_codes].where(M[equity_codes])
        S_used = S_eq
    else:
        # Oracle sources — pull equity RV, align to sigma's grid, then
        # mask by (forward-shifted) membership. reindex fills missing
        # RV bars with NaN, which propagate through the mean and cause
        # the blender to fall back to WARMUP_LAMBDA on those bars.
        rv_eq = rv_panel.reindex(index=idx, columns=equity_codes)
        rv_eq = rv_eq.where(M[equity_codes])

        if vol_source == "fwd_1w_rv":
            # At bar t: mean over i of RV[t+1, i], masked by M[t+1, i].
            S_used = rv_eq.shift(-1)
        elif vol_source == "fwd_4w_rv":
            # At bar t: mean over i of mean(RV[t+1..t+4, i]).
            # Approach: for each k in {1..4}, shift RV by −k so row t
            # holds RV[t+k]; then average the four shifted panels.
            shifted = [rv_eq.shift(-k) for k in (1, 2, 3, 4)]
            arr = np.stack([s.to_numpy() for s in shifted], axis=0)  # (4, T, N)
            # Last 4 rows have all-NaN shifts → NaN score. That's the
            # desired behavior; suppress np.nanmean's warning about it.
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore",
                                        message="Mean of empty slice",
                                        category=RuntimeWarning)
                mean_arr = np.nanmean(arr, axis=0)                   # (T, N)
            S_used = pd.DataFrame(mean_arr, index=idx, columns=equity_codes)
        else:
            raise AssertionError("unreachable")

    return S_used.mean(axis=1).rename(f"equity_score_{vol_source}")


def hold_through_transient_nan(pct: pd.Series) -> pd.Series:
    """Forward-fill a percentile series through NaN bars that occur
    *after* the first valid value. The initial NaN block (warmup) is
    preserved so ``lambda_schedule`` still assigns ``warmup_lambda``
    there.

    Why: transient NaN scores appear when the σ or RV panel has a
    holiday week that the trading calendar doesn't observe (e.g.,
    Chinese New Year weeks in the sigma index don't have RV entries).
    Without ffill, λ oscillates to ``warmup_lambda`` on those bars and
    back to a real gate value on the next bar — that produces
    spurious weight churn in the blended book and inflates cost.
    Holding the last known gate state through the transient NaN is
    the operationally realistic behavior (any real system would keep
    the latest forecast active while awaiting the next one).
    """
    first_valid = pct.first_valid_index()
    if first_valid is None:
        return pct.copy()
    out = pct.copy()
    tail = out.loc[first_valid:].ffill()
    out.loc[first_valid:] = tail
    return out


def score_to_percentile(score: pd.Series,
                        min_history: int = MIN_HISTORY) -> pd.Series:
    """Expanding causal percentile rank of a scalar series → [0, 1].

    At bar t, rank(score[t]) among {score[0], ..., score[t]}, divided
    by count. Returns NaN for the first ``min_history`` observations
    so the blender doesn't gate on a barely-populated distribution.

    Ties → average rank (pandas default). Rank / count instead of
    rank / (count-1) so the score maps to (0, 1] rather than [0, 1] —
    the largest-ever value at bar t always gets 1.0, which is the
    "full defensive" corner.
    """
    x = score.astype(float)
    n = len(x)
    pct = np.full(n, np.nan)
    for t in range(n):
        if pd.isna(x.iloc[t]):
            continue
        window = x.iloc[:t + 1].dropna()
        if len(window) < min_history:
            continue
        # rank of x[t] among window (largest → highest rank).
        rank_of_t = float((window <= x.iloc[t]).sum())
        pct[t] = rank_of_t / len(window)
    return pd.Series(pct, index=score.index, name=score.name.replace("score", "pct")
                     if score.name else "pct")


# ---------------------------------------------------------------------- #
# λ schedule
# ---------------------------------------------------------------------- #
def lambda_schedule(pct: pd.Series,
                    lower_gate: float = LOWER_GATE,
                    upper_gate: float = UPPER_GATE,
                    warmup_lambda: float = WARMUP_LAMBDA,
                    invert: bool = False) -> pd.Series:
    """Piecewise-linear λ(percentile). Continuous at both boundaries.

    Non-inverted (default — matches Phase 11.2 user spec)
    -----------------------------------------------------
    - pct < lower_gate       →  λ = 1                (full aggressive)
    - lower ≤ pct ≤ upper    →  λ = (upper − pct) / (upper − lower)
    - pct > upper_gate       →  λ = 0                (full defensive)
    - pct NaN                →  λ = warmup_lambda

    Inverted (``invert=True``)
    --------------------------
    Same schedule, mirrored: aggressive in HIGH vol, defensive in LOW
    vol. Introduced after the first run of ``oracle_blender_v6.py``
    surfaced regime-conditional Sharpe that inverts the naive intuition
    — see reports/oracle_blender_v6_report.md §"Regime diagnostic".

    Warmup semantics (symmetric across directions)
    -----------------------------------------------
    ``warmup_lambda`` is applied literally on NaN bars regardless of
    ``invert``. So naive vs inverted use the *same* λ during the
    first ``min_history`` bars, which makes their headline metrics
    apples-to-apples. Default is 0.5 (neutral). Was previously
    asymmetric — the inverted branch used ``1 − warmup_lambda``, which
    gave the two directions different warmup exposures and biased the
    comparison.
    """
    if not (0.0 <= lower_gate < upper_gate <= 1.0):
        raise ValueError(f"need 0 ≤ lower < upper ≤ 1, got {lower_gate}, {upper_gate}")
    if not (0.0 <= warmup_lambda <= 1.0):
        raise ValueError(f"warmup_lambda must be in [0, 1], got {warmup_lambda}")

    p = pct.to_numpy(dtype=float)
    span = upper_gate - lower_gate

    is_nan  = np.isnan(p)
    below   = (~is_nan) & (p < lower_gate)
    above   = (~is_nan) & (p > upper_gate)
    middle  = (~is_nan) & (~below) & (~above)

    # Symmetric warmup: same λ during NaN bars regardless of direction.
    lam = np.full_like(p, warmup_lambda)

    if not invert:
        lam[below]  = 1.0
        lam[above]  = 0.0
        lam[middle] = (upper_gate - p[middle]) / span
    else:
        lam[below]  = 0.0
        lam[above]  = 1.0
        lam[middle] = (p[middle] - lower_gate) / span

    return pd.Series(lam, index=pct.index, name="lambda")


def binary_lambda_schedule(pct: pd.Series,
                           upper_gate: float = UPPER_GATE,
                           warmup_lambda: float = WARMUP_LAMBDA) -> pd.Series:
    """Binary λ — pure aggressive OR pure defensive, no ramp.

    - pct > upper_gate  →  λ = 0   (full defensive)
    - pct ≤ upper_gate  →  λ = 1   (full aggressive)
    - pct NaN           →  λ = warmup_lambda

    Motivated by the Phase 11.2 diagnostic (see report §Regime × future-
    return): the mid-regime spread on the forward-RV signals is still
    positive (+0.09%/wk at fwd_1w_rv, +0.04% at fwd_4w_rv), so the
    ramp's partial-defensive tilt in the middle band is throwing away
    positive expected spread. A hard cutoff at pct = 0.9 keeps the book
    aggressive whenever the forward oracle isn't signaling actual high
    RV, and only steps out for the top-decile weeks where aggressive
    genuinely loses.

    The cost of the hard shift is diagnosed separately in
    ``blender_diagnostics_v6.py`` — at every transition the whole book
    flips from W_agg to W_def (or back), which is ~1 unit of turnover
    at 10 bp / side.
    """
    if not (0.0 <= upper_gate <= 1.0):
        raise ValueError(f"upper_gate must be in [0, 1], got {upper_gate}")
    if not (0.0 <= warmup_lambda <= 1.0):
        raise ValueError(f"warmup_lambda must be in [0, 1], got {warmup_lambda}")

    p = pct.to_numpy(dtype=float)
    lam = np.full_like(p, warmup_lambda)
    is_nan = np.isnan(p)
    above  = (~is_nan) & (p > upper_gate)
    at_or_below = (~is_nan) & (~above)
    lam[at_or_below] = 1.0
    lam[above]       = 0.0
    return pd.Series(lam, index=pct.index, name="lambda")


# ---------------------------------------------------------------------- #
# Blend
# ---------------------------------------------------------------------- #
def blend_weights(W_aggressive: pd.DataFrame,
                  W_defensive: pd.DataFrame,
                  lambdas: pd.Series) -> pd.DataFrame:
    """W_blend[t] = λ[t] · W_agg[t] + (1 − λ[t]) · W_def[t].

    Both W panels must share the same index and columns. λ is
    reindexed against the W panels; missing λ → treated as 1.0
    (full aggressive) per ``lambda_schedule`` convention.
    """
    if not W_aggressive.index.equals(W_defensive.index):
        raise ValueError("W_aggressive and W_defensive must share an index")
    if not W_aggressive.columns.equals(W_defensive.columns):
        raise ValueError("W_aggressive and W_defensive must share columns")

    lam = lambdas.reindex(W_aggressive.index).fillna(1.0)
    lam_arr = lam.to_numpy()[:, None]   # T × 1 broadcast
    W_blend = lam_arr * W_aggressive.to_numpy() + (1.0 - lam_arr) * W_defensive.to_numpy()
    return pd.DataFrame(W_blend, index=W_aggressive.index, columns=W_aggressive.columns)
