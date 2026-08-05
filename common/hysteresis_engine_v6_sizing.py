"""
v6/scripts/hysteresis_engine_v6_sizing.py
=========================================
Sizing-scheme sandbox for the v6 static book.

Same rank-hysteresis selection as ``hysteresis_engine_v6``; the only
difference is the sizing kernel applied to the held set. The point of
this file is to isolate one axis (weighting scheme) so the selection
side of Phase 9.2 stays frozen while we explore alternatives to the
1/σ default.

Motivation
----------
The Phase 9.2 hysteresis sweep is Sharpe-optimal but concentration-
heavy: on `long_q20` the 1/σ_causal_26w kernel pours most of the mass
into the lowest-vol names (mostly bonds). CAGR sits ~3% net in-sample,
which is bond-like. Two axes to explore:

- Soften the vol kernel (``inv_sqrt_vol`` — rejected in the 1/√σ
  sweep, see reports/sizing_sweep_v6_report.md).
- Move to an α-responsive kernel (``rank_prop`` — this file's second
  extension, drives the "aggressive book" leg of the Phase 11 two-book
  design).

Sizing schemes
--------------
    "inv_vol"       w_i ∝ 1 / σ_i               (defensive baseline —
                                                 reproduces Phase 9.1 /
                                                 9.2 weights bit-for-bit)
    "inv_sqrt_vol"  w_i ∝ 1 / √σ_i              (rejected 1/√σ branch)
    "rank_prop"     w_i ∝ (H − r_i + 1)         (aggressive book — r_i
                                                 is the α-rank *within
                                                 the held set*, H =
                                                 |held|; 1 = best α)
    "alpha_prop"    w_i ∝ α_i − min(α_held)     (v4pool/v5 α-proportional
                     + rng_held / H              formula — uses α *levels*
                                                 not just ranks; more
                                                 concentrated tilt toward
                                                 top-α held names when α
                                                 has spread)
    "inv_vol_pctl"  w_i ∝ (1/σ_i) ·             (per-ETF vol-regime
                     exp(β(0.5 − p_i))            adjustment on top of
                                                 1/σ — p_i is the trailing
                                                 26w percentile of σ_i,t
                                                 against its own history,
                                                 β = ln(2). Rewards ETFs
                                                 in their own low-vol
                                                 regime, penalizes those
                                                 in their own high-vol
                                                 regime. p=0.5 → no
                                                 adjustment; p=0 → ×√2;
                                                 p=1 → ÷√2.)

All are renormalized so Σw = 1 (long) or ±0.5 per side (LS).

Sample discipline
-----------------
This module does NOT enforce IS/OOS windowing — that's the driver's job
(see sizing_sweep_v6.py and alpha_prop_sweep_v6.py, both of which only
report IS metrics for this experiment branch per
[[feedback-oos-discipline]]).

Compatibility
-------------
- Return signature identical to ``hysteresis_engine_v6.build_hysteresis_weights``
  and ``xs_engine_v6.build_static_weights``. Feed the (W, N_t, K_t)
  triple into ``xs_engine_v6.run_book`` unchanged.
- No edits to existing files. Deleting this file reverts the pipeline
  to the Phase 9.2 state.
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

import _common_v6 as C  # noqa: F401
import xs_engine_v6 as E
import hysteresis_engine_v6 as H


SIZINGS = ("inv_vol", "inv_sqrt_vol", "rank_prop", "alpha_prop", "inv_vol_pctl")

# Sizings that consume the σ-derived per-cell kernel (precomputed once
# per run). Everything else must dispatch through _leg_from_sizing.
# `inv_vol_pctl` is σ-only but needs the σ *history*, not just the
# current σ, to compute the per-ETF trailing-percentile multiplier.
_SIGMA_SIZINGS = ("inv_vol", "inv_sqrt_vol", "inv_vol_pctl")
_ALPHA_SIZINGS = ("rank_prop", "alpha_prop")

# inv_vol_pctl knobs (per user spec, mild adjustment)
INV_VOL_PCTL_WINDOW = 26              # trailing bars for per-ETF percentile
INV_VOL_PCTL_BETA   = float(np.log(2.0))  # → mult in [1/√2, √2]


def _sigma_trailing_percentile(sigma: pd.DataFrame,
                               window: int = INV_VOL_PCTL_WINDOW
                               ) -> pd.DataFrame:
    """Per-ETF trailing-``window`` percentile rank of the current σ_i,t
    against its own history σ_i,τ for τ ∈ [t − window + 1, t].

    Returns a T × N panel in [0, 1] with NaN before ``window`` valid
    observations per column (or when a valid current value is NaN).

    Definition (matches the user spec):
        p_i,t = # {τ ∈ [t−W+1, t] : σ_i,τ ≤ σ_i,t}  /  W

    Implementation: vectorized numpy sliding-window comparison. On the
    v6 grid (~425 bars × ~344 codes × 26w window) this runs in <0.5s.
    """
    if window < 2:
        raise ValueError(f"window must be ≥ 2, got {window}")
    arr = sigma.to_numpy(dtype=float)
    T, N = arr.shape
    out = np.full_like(arr, np.nan)
    # Rolling comparison: for each bar t ≥ window − 1, compare current
    # row against the prior window rows (inclusive of current), then
    # divide by count of *defined* values in the window.
    for t in range(window - 1, T):
        w_arr = arr[t - window + 1 : t + 1, :]     # (window, N)
        cur   = arr[t, :]                          # (N,)
        # (w ≤ cur) is True on defined values only; NaN comparisons → False.
        le = (w_arr <= cur[None, :])
        n_defined = (~np.isnan(w_arr)).sum(axis=0).astype(float)
        with np.errstate(invalid="ignore", divide="ignore"):
            pct = le.sum(axis=0) / n_defined
        # Require the full window of defined obs (per user spec: 26w) —
        # partial-window percentiles are noisy and would leak into
        # early-life bars of newly admitted names.
        pct = np.where(n_defined >= window, pct, np.nan)
        # Also NaN out if current σ is NaN.
        pct = np.where(np.isnan(cur), np.nan, pct)
        out[t, :] = pct
    return pd.DataFrame(out, index=sigma.index, columns=sigma.columns)


def _sizing_kernel(sigma: pd.DataFrame,
                   eligible: pd.DataFrame,
                   sizing: str) -> pd.DataFrame:
    """Per-cell σ-derived sizing weight (pre-renormalization).

    Only defined for the σ-only kernels (``inv_vol``, ``inv_sqrt_vol``,
    ``inv_vol_pctl``). α-dependent kernels (``rank_prop``, ``alpha_prop``)
    are computed per-bar per-leg inside ``_leg_from_sizing`` and never
    touch this helper.

    σ is guaranteed strictly positive on the eligible mask (see
    ``xs_engine_v6._eligible_mask``), so no clipping is needed.

    For ``inv_vol_pctl``: 1/σ multiplied by exp(β·(0.5 − p_i,t)) where
    p_i,t is the per-ETF trailing-26w σ percentile. NaN percentile
    (early-life or pre-warmup bars) → multiplier = 1.0 (defaults to
    plain 1/σ), so the kernel degrades gracefully to inv_vol on
    warmup bars.
    """
    if sizing == "inv_vol":
        v = 1.0 / sigma
    elif sizing == "inv_sqrt_vol":
        v = 1.0 / np.sqrt(sigma)
    elif sizing == "inv_vol_pctl":
        p = _sigma_trailing_percentile(sigma, window=INV_VOL_PCTL_WINDOW)
        # NaN percentile → multiplier = 1.0 (equivalent to plain inv_vol).
        p_filled = p.fillna(0.5)
        mult = np.exp(INV_VOL_PCTL_BETA * (0.5 - p_filled))
        v = (1.0 / sigma) * mult
    else:
        raise ValueError(
            f"_sizing_kernel does not handle sizing={sizing!r}; "
            f"α-dependent kernels dispatch through _leg_from_sizing"
        )
    return v.where(eligible)


def _leg_weights_rank_prop(alpha_row: np.ndarray,
                           held_idx: np.ndarray,
                           target_sum: float) -> np.ndarray:
    """Rank-proportional per-leg weights on the held set.

    Rules
    -----
    - Rank α *within the held set*, descending. r_i = 1 for the best-α
      held name, r_i = H for the worst-α held name.
    - Per-name mass p_i = H − r_i + 1  →  (H, H−1, …, 1) in α-rank
      order. Σp = H·(H+1)/2.
    - w_i = sign(target_sum) · |target_sum| · p_i / Σp  on held_idx,
      zero elsewhere.

    Local-rank (not global rank on the eligible universe) guarantees
    every held name gets a strictly positive weight even when the
    hysteresis exit-buffer retains names at global ranks > K.

    Tie-break: ``np.argsort(kind="stable")`` on ``-a`` gives array-order
    tie-breaking on descending α, matching pandas
    ``rank(method="first", ascending=False)`` on positional data.
    """
    w = np.zeros_like(alpha_row, dtype=float)
    H_size = int(held_idx.size)
    if H_size == 0:
        return w
    a = alpha_row[held_idx]
    order = np.argsort(-a, kind="stable")     # order[0] = argmax α
    ranks = np.empty(H_size, dtype=int)
    ranks[order] = np.arange(1, H_size + 1)   # 1 = best-α held
    p = (H_size - ranks + 1).astype(float)    # H..1 in α-rank order
    denom = float(p.sum())
    if denom <= 0.0:
        return w
    w[held_idx] = np.sign(target_sum) * abs(target_sum) * p / denom
    return w


def _leg_weights_alpha_prop(alpha_row: np.ndarray,
                            held_idx: np.ndarray,
                            target_sum: float) -> np.ndarray:
    """v4pool / v5 alpha-proportional per-leg weights on the held set.

    Formula (v4pool/xs_ic_pipeline/scripts/book_xs.py convention):

        H      = |held|
        rng    = max(α_held) − min(α_held)
        ε      = max(rng / H, 1e-12)
        p_i    = α_i − min(α_held) + ε           on held; 0 elsewhere
        w_i    = sign(target) · |target| · p_i / Σp

    Behavior:
    - Equal α across the held set → p_i = ε uniformly → equal weight
      (the ε floor prevents 0/0 and matches v5's weights_topk_alphaprop_long).
    - Positive α spread → higher α gets proportionally more mass.
    - Sign-robust: min-shift makes all p ≥ ε > 0 even when raw α is
      centered near zero (v6 uses row-z α — half of the raw values are
      negative, so the shift is essential).
    - Local to the held set (not top-K on the eligible universe) —
      matches how ``rank_prop`` handles the hysteresis exit-buffer band.
    """
    w = np.zeros_like(alpha_row, dtype=float)
    H_size = int(held_idx.size)
    if H_size == 0:
        return w
    a = alpha_row[held_idx]
    a_min = float(a.min())
    rng   = float(a.max() - a_min)
    eps   = max(rng / H_size, 1e-12)
    p = a - a_min + eps
    denom = float(p.sum())
    if denom <= 0.0:
        return w
    w[held_idx] = np.sign(target_sum) * abs(target_sum) * p / denom
    return w


def _leg_from_sizing(sizing: str,
                     held_idx: np.ndarray,
                     target_sum: float,
                     *,
                     inv_row: np.ndarray | None,
                     alpha_row: np.ndarray | None) -> np.ndarray:
    """Dispatch on the sizing kernel. σ-based kernels reuse
    ``hysteresis_engine_v6._leg_weights`` on the precomputed 1/σ (or
    1/√σ) per-cell mass; α-based kernels compute locally."""
    if sizing in _SIGMA_SIZINGS:
        assert inv_row is not None, f"{sizing} requires inv_row"
        return H._leg_weights(inv_row, held_idx, target_sum)
    if sizing == "rank_prop":
        assert alpha_row is not None, "rank_prop requires alpha_row"
        return _leg_weights_rank_prop(alpha_row, held_idx, target_sum)
    if sizing == "alpha_prop":
        assert alpha_row is not None, "alpha_prop requires alpha_row"
        return _leg_weights_alpha_prop(alpha_row, held_idx, target_sum)
    raise ValueError(f"sizing must be one of {SIZINGS}, got {sizing!r}")


def build_hysteresis_weights_sized(alpha: pd.DataFrame,
                                   sigma: pd.DataFrame,
                                   membership: pd.DataFrame,
                                   q: float,
                                   mode: Literal["long", "ls"],
                                   epsilon: float,
                                   rule: Literal["buffer", "replace"],
                                   sizing: Literal["inv_vol",
                                                   "inv_sqrt_vol",
                                                   "rank_prop"]
                                   ) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Path-dependent weight builder with pluggable sizing kernel.

    Selection logic is byte-identical to ``hysteresis_engine_v6.build_hysteresis_weights``
    (same eligibility mask, same K_t / ExitK_t, same tie-break, same
    per-leg held-set update via ``_select_with_hysteresis``). Only the
    per-name sizing weight before renormalization changes.

    At ``sizing="inv_vol"`` and ``epsilon=0.0`` this reproduces
    ``xs_engine_v6.build_static_weights`` bit-for-bit.
    """
    if mode not in E.MODES:
        raise ValueError(f"mode must be one of {E.MODES}, got {mode!r}")
    if rule not in H.RULES:
        raise ValueError(f"rule must be one of {H.RULES}, got {rule!r}")
    if sizing not in SIZINGS:
        raise ValueError(f"sizing must be one of {SIZINGS}, got {sizing!r}")
    if not (0.0 < q <= 1.0):
        raise ValueError("q must be in (0, 1]")

    idx = alpha.index
    cols = alpha.columns
    S = sigma.reindex(index=idx, columns=cols)
    M = (membership.reindex(index=idx, columns=cols)
                   .astype("boolean").fillna(False).astype(bool))

    eligible = alpha.notna() & S.notna() & (S > 0.0) & M
    N_t = eligible.sum(axis=1).astype(int).rename("N_t")
    K_t = E._K_per_bar(N_t, q, mode)
    ExitK_t = H._exit_K(K_t, N_t, epsilon)

    ranks = alpha.where(eligible).rank(axis=1, method="first", ascending=False)

    A_rank = ranks.to_numpy()
    A_elig = eligible.to_numpy()

    if sizing in _SIGMA_SIZINGS:
        inv_sig = _sizing_kernel(S, eligible, sizing)
        A_inv   = np.nan_to_num(inv_sig.to_numpy(), nan=0.0)
        A_alpha = None
    else:  # α-dependent (rank_prop, alpha_prop) — computed per-leg per-bar
        A_inv   = None
        # NaN-filling for α on ineligible cells is safe: held_idx only
        # contains eligible indices (eligibility ⊆ α-defined), so those
        # NaNs are never dereferenced.
        A_alpha = alpha.where(eligible).to_numpy()

    N = len(cols)
    W_out = np.zeros(A_elig.shape, dtype=float)

    long_prev  = np.zeros(N, dtype=bool)
    short_prev = np.zeros(N, dtype=bool) if mode == "ls" else None

    K_arr  = K_t.to_numpy().astype(int)
    Ex_arr = ExitK_t.to_numpy().astype(int)
    N_arr  = N_t.to_numpy().astype(int)

    for t in range(len(idx)):
        K, Ex, Nt = int(K_arr[t]), int(Ex_arr[t]), int(N_arr[t])
        if K == 0:
            long_prev = np.zeros(N, dtype=bool)
            if mode == "ls":
                short_prev = np.zeros(N, dtype=bool)
            continue

        rank_row  = A_rank[t]
        elig_row  = A_elig[t]
        inv_row   = A_inv[t]   if A_inv   is not None else None
        alpha_row = A_alpha[t] if A_alpha is not None else None

        if mode == "long":
            long_new = H._select_with_hysteresis(
                rank_row, elig_row, long_prev, K, Ex, rule)
            W_out[t] = _leg_from_sizing(
                sizing, np.flatnonzero(long_new), +1.0,
                inv_row=inv_row, alpha_row=alpha_row)
            long_prev = long_new

        else:  # ls
            long_new = H._select_with_hysteresis(
                rank_row, elig_row, long_prev, K, Ex, rule)
            reflected = np.where(np.isnan(rank_row), np.nan,
                                 Nt + 1 - rank_row)
            short_new = H._select_with_hysteresis(
                reflected, elig_row, short_prev, K, Ex, rule)

            overlap = long_new & short_new
            if overlap.any():
                long_new  &= ~overlap
                short_new &= ~overlap

            w_long  = _leg_from_sizing(
                sizing, np.flatnonzero(long_new),  +0.5,
                inv_row=inv_row, alpha_row=alpha_row)
            w_short = _leg_from_sizing(
                sizing, np.flatnonzero(short_new), -0.5,
                inv_row=inv_row, alpha_row=alpha_row)
            W_out[t] = w_long + w_short

            long_prev  = long_new
            short_prev = short_new

    W = pd.DataFrame(W_out, index=idx, columns=cols)
    return W, N_t, K_t


def backtest_alpha_hysteresis_sized(alpha: pd.DataFrame,
                                    sigma: pd.DataFrame,
                                    fwd_1w: pd.DataFrame,
                                    membership: pd.DataFrame,
                                    q: float,
                                    mode: str,
                                    epsilon: float,
                                    rule: str,
                                    sizing: str,
                                    cost_per_trade: float = E.DEFAULT_COST_PER_TRADE
                                    ) -> tuple[E.BookResult, E.BookSummary]:
    W, N_t, K_t = build_hysteresis_weights_sized(
        alpha, sigma, membership, q, mode, epsilon, rule, sizing)
    res = E.run_book(W, fwd_1w, cost_per_trade=cost_per_trade,
                     N_t=N_t, K_t=K_t)
    return res, E.summarize_book(res)
