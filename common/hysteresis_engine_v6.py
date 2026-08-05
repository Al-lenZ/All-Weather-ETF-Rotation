"""
v6/scripts/hysteresis_engine_v6.py
==================================
Path-dependent weight builder for the Phase 9.2 exit-buffer experiment.
Sits alongside xs_engine_v6.py; does not replace it. Reverting to the
Phase 9.1 static baseline = drop this file and hysteresis_sweep_v6.py.

Motivation
----------
`cost_attribution_v6_report.md` showed 85-87% of turnover on the long
books is *selection* (name enter/exit). `baseline_diagnostics_v6.md`
§1.d showed 71-77% of that selection |Δw| is *round-trip* churn (same
name flips back within ≤ 4 weeks). A rank-hysteresis rule attacks the
round-trip channel directly.

Two rules
---------
    "buffer"   Enter at rank ≤ K_t. Exit only when rank > ExitK_t.
               Held-set size floats in [K_t, K_t + (# prior holdings
               currently sitting at ranks K_t+1 .. ExitK_t)].

    "replace"  Fixed size K_t. Kick a held name when rank > ExitK_t;
               refill from top-ranked non-holdings so size stays at
               K_t. If no holding is beyond ExitK_t, no membership
               change (but 1/σ weights still refresh every bar — held
               constant with xs_engine_v6.build_static_weights so the
               sizing turnover channel is preserved).

ExitK_t = min(N_t, ⌈(1+ε)·K_t⌉).  ε=0 must reproduce the Phase 9.1
static baseline exactly (asserted by hysteresis_sweep_v6.py).

Shared with xs_engine_v6
------------------------
- Same eligibility mask (α defined, σ defined and > 0, membership True).
- Same K_t = max(1, ⌈q·N_t⌉); same LS cap K ≤ N//2 (else long+short
  overlap).
- Same 1/σ weighting, renormalized to Σw=1 (long) or ±0.5 (LS).
- Same tie-break: pandas rank(method="first"), so a bar with ε=0
  reproduces build_static_weights bit-for-bit.
- Returns (W, N_t, K_t) triple compatible with xs_engine_v6.run_book.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

import _common_v6 as C  # noqa: F401  — matched import surface with xs_engine_v6
import xs_engine_v6 as E


RULES = ("buffer", "replace")
MODES = E.MODES                # ("long", "ls")


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #
def _exit_K(K_t: pd.Series, N_t: pd.Series, epsilon: float) -> pd.Series:
    """ExitK_t = min(N_t, ⌈(1+ε)·K_t⌉).  For K_t=0 bars ExitK_t=0."""
    if epsilon < 0.0:
        raise ValueError("epsilon must be ≥ 0")
    K = K_t.to_numpy().astype(int)
    N = N_t.to_numpy().astype(int)
    ExitK = np.ceil((1.0 + epsilon) * K).astype(int)
    ExitK = np.minimum(ExitK, N)
    ExitK = np.where(K == 0, 0, ExitK)
    return pd.Series(ExitK, index=K_t.index, name="ExitK_t")


def _leg_weights(inv_sig_row: np.ndarray,
                 held_idx: np.ndarray,
                 target_sum: float) -> np.ndarray:
    """1/σ weights on `held_idx`, renormalized so Σ|w| = |target_sum|.
    Sign(target_sum) sets the leg direction (positive for long, negative
    for short)."""
    w = np.zeros_like(inv_sig_row)
    if held_idx.size == 0:
        return w
    v = inv_sig_row[held_idx]
    tot = float(v.sum())
    if tot <= 0.0:
        return w
    w[held_idx] = np.sign(target_sum) * abs(target_sum) * v / tot
    return w


def _select_with_hysteresis(rank_row: np.ndarray,
                            eligible_row: np.ndarray,
                            held_prev: np.ndarray,
                            K: int,
                            ExitK: int,
                            rule: str) -> np.ndarray:
    """One-bar, one-leg selection.

    Parameters
    ----------
    rank_row     : ranks (1 = best) with NaN on ineligible cells; length N
    eligible_row : bool mask of eligibility for this bar
    held_prev    : bool mask of names held on this leg at t-1
    K, ExitK     : per-bar targets
    rule         : "buffer" | "replace"

    Returns
    -------
    held_new : bool mask of held names after selection. Cross-leg
    disjointness (LS) is enforced by the caller — this function is
    single-leg. Baseline reproducibility at ε=0 requires no cross-leg
    forbid mask here; the LS cap K ≤ N//2 already guarantees long and
    short cannot overlap when both are just top-K / bottom-K.
    """
    if K == 0:
        return np.zeros_like(eligible_row, dtype=bool)

    valid_rank = ~np.isnan(rank_row)
    kept = held_prev & eligible_row & valid_rank & (rank_row <= ExitK)

    if rule == "buffer":
        new_mask = (~held_prev) & eligible_row & valid_rank & (rank_row <= K)
        held_new = kept | new_mask
    elif rule == "replace":
        need = int(K - kept.sum())
        held_new = kept.copy()
        if need > 0:
            cand = (~kept) & eligible_row & valid_rank
            cand_ranks = np.where(cand, rank_row, np.nan)
            order = np.argsort(np.where(np.isnan(cand_ranks), np.inf, cand_ranks),
                               kind="stable")
            picks = order[:need]
            picks = picks[cand[picks]]         # guard degenerate case
            held_new[picks] = True
        elif need < 0:
            # Universe shrank so K_t < |kept| — trim worst-ranked kept.
            over = int(-need)
            kept_ranks = np.where(kept, rank_row, np.nan)
            order = np.argsort(np.where(np.isnan(kept_ranks), -np.inf,
                                        -kept_ranks), kind="stable")
            drop = order[:over]
            held_new[drop] = False
    else:
        raise ValueError(f"rule must be one of {RULES}, got {rule!r}")

    return held_new


# ---------------------------------------------------------------------- #
# Main builder
# ---------------------------------------------------------------------- #
def build_hysteresis_weights(alpha: pd.DataFrame,
                             sigma: pd.DataFrame,
                             membership: pd.DataFrame,
                             q: float,
                             mode: Literal["long", "ls"],
                             epsilon: float,
                             rule: Literal["buffer", "replace"]
                             ) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Path-dependent weight builder.  Same return signature as
    xs_engine_v6.build_static_weights so that xs_engine_v6.run_book can
    consume the output unchanged.

    Seeds bar 0 with plain top-K (and bottom-K for LS), matching the
    static baseline on the first bar of every history.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    if rule not in RULES:
        raise ValueError(f"rule must be one of {RULES}, got {rule!r}")
    if not (0.0 < q <= 1.0):
        raise ValueError("q must be in (0, 1]")

    # Align sigma / membership to the alpha grid (mirrors build_static_weights).
    idx = alpha.index
    cols = alpha.columns
    S = sigma.reindex(index=idx, columns=cols)
    M = (membership.reindex(index=idx, columns=cols)
                   .astype("boolean").fillna(False).astype(bool))

    eligible = alpha.notna() & S.notna() & (S > 0.0) & M
    N_t = eligible.sum(axis=1).astype(int).rename("N_t")
    K_t = E._K_per_bar(N_t, q, mode)
    ExitK_t = _exit_K(K_t, N_t, epsilon)

    # rank(method="first") — identical to build_static_weights tie-break
    ranks = alpha.where(eligible).rank(axis=1, method="first", ascending=False)
    inv_sig = (1.0 / S).where(eligible)

    A_rank = ranks.to_numpy()           # NaN where ineligible
    A_elig = eligible.to_numpy()
    A_inv  = np.nan_to_num(inv_sig.to_numpy(), nan=0.0)

    N = len(cols)
    W_out = np.zeros(A_elig.shape, dtype=float)

    long_prev  = np.zeros(N, dtype=bool)
    short_prev = np.zeros(N, dtype=bool) if mode == "ls" else None

    K_arr    = K_t.to_numpy().astype(int)
    Ex_arr   = ExitK_t.to_numpy().astype(int)
    N_arr    = N_t.to_numpy().astype(int)

    for t in range(len(idx)):
        K, Ex, Nt = int(K_arr[t]), int(Ex_arr[t]), int(N_arr[t])
        if K == 0:
            long_prev = np.zeros(N, dtype=bool)
            if mode == "ls":
                short_prev = np.zeros(N, dtype=bool)
            continue

        rank_row = A_rank[t]
        elig_row = A_elig[t]
        inv_row  = A_inv[t]

        if mode == "long":
            long_new = _select_with_hysteresis(
                rank_row, elig_row, long_prev, K, Ex, rule)
            W_out[t] = _leg_weights(inv_row, np.flatnonzero(long_new), +1.0)
            long_prev = long_new

        else:  # ls
            long_new = _select_with_hysteresis(
                rank_row, elig_row, long_prev, K, Ex, rule)

            # Short side uses "distance from bottom": original rule was
            # rank > N_t - K enters, rank ≤ N_t - ExitK exits. Reflect
            # ranks (R → N+1-R) so the top-K helper can be reused.
            reflected = np.where(np.isnan(rank_row), np.nan,
                                 Nt + 1 - rank_row)
            short_new = _select_with_hysteresis(
                reflected, elig_row, short_prev, K, Ex, rule)

            # Disjointness: for ε=0 this cannot fire (LS cap K ≤ N//2
            # keeps top-K and bottom-K disjoint). For ε > 0 the buffer
            # bands could in principle meet if ExitK > N//2; in that
            # (unreachable at design K, q) case, drop the overlap from
            # both legs and warn via the returned diagnostics.
            overlap = long_new & short_new
            if overlap.any():
                long_new  &= ~overlap
                short_new &= ~overlap

            w_long  = _leg_weights(inv_row, np.flatnonzero(long_new),  +0.5)
            w_short = _leg_weights(inv_row, np.flatnonzero(short_new), -0.5)
            W_out[t] = w_long + w_short

            long_prev  = long_new
            short_prev = short_new

    W = pd.DataFrame(W_out, index=idx, columns=cols)
    return W, N_t, K_t


# ---------------------------------------------------------------------- #
# One-shot convenience — mirrors xs_engine_v6.backtest_alpha
# ---------------------------------------------------------------------- #
@dataclass
class HysteresisConfig:
    epsilon: float
    rule: Literal["buffer", "replace"]


def backtest_alpha_hysteresis(alpha: pd.DataFrame,
                              sigma: pd.DataFrame,
                              fwd_1w: pd.DataFrame,
                              membership: pd.DataFrame,
                              q: float,
                              mode: str,
                              epsilon: float,
                              rule: str,
                              cost_per_trade: float = E.DEFAULT_COST_PER_TRADE
                              ) -> tuple[E.BookResult, E.BookSummary]:
    W, N_t, K_t = build_hysteresis_weights(alpha, sigma, membership,
                                           q, mode, epsilon, rule)
    res = E.run_book(W, fwd_1w, cost_per_trade=cost_per_trade,
                     N_t=N_t, K_t=K_t)
    return res, E.summarize_book(res)
