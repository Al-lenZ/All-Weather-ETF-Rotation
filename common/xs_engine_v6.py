"""
v6/scripts/xs_engine_v6.py
==========================
Weekly, ragged, quantile-K static book engine for the v6 pool.

Two book modes, vol-scaled within selection (design §7):

    "long" (baseline)
        Pick top-⌈q·N_t⌉ names by α at each W-FRI bar. Weight each by
        1/σ_causal_26w, renormalize so Σw = 1. Long-only, gross = 1.

    "ls"   (research-only experiment)
        Long the top-⌈q·N_t⌉ + short the bottom-⌈q·N_t⌉. Each side
        weighted 1/σ (short leg gets its negative sign), each side
        renormalized to Σ|w|=0.5. Long-side sum = +0.5, short-side sum =
        -0.5, gross = 1, net = 0 (dollar-neutral).

Universe rules:
- Selection eligible only where α is defined, σ is defined and > 0, and
  the name is a member at bar t (MEMBERSHIP[t, i] = True). Non-eligible
  cells drop out of the per-bar ranking naturally.
- N_t := # eligible cells at bar t. K_t := max(1, ⌈q·N_t⌉). LS mode
  additionally requires N_t ≥ 2 (else both sides are empty → flat bar).

Cadence:
- Everything runs directly on the W-FRI grid. Weight at bar t earns
  ``fwd_1w[t] = close(t+1)/close(t) - 1`` (matches ``panels_v6.fwd_1w``).
  Turnover = Σ|Δw| between consecutive rebal bars (weekly).
- Cost = ``COST_PER_TRADE`` per unit turnover, default 10 bp/side.
- Sharpe annualized by ``_common_v6.WEEKS_PER_YEAR = 52``.

IS/OOS split (frozen at [[oos-discipline]]):
- IS  : ≤ IN_SAMPLE_END           (2023-12-31)
- OOS : OOS_START ≤ t ≤ OOS_END   (2024-01-01 → 2025-07-31)
- Bars > OOS_END are ignored by ``evaluate_book`` — the hold-out is
  sealed until the user explicitly opens it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import _common_v6 as C


DEFAULT_COST_PER_TRADE  = 0.001      # 10 bp / side
DEFAULT_INITIAL_CAPITAL = 1_000_000
MODES = ("long", "ls")


# ---------------------------------------------------------------------- #
# Result containers
# ---------------------------------------------------------------------- #
@dataclass
class BookResult:
    """Full backtest artifacts + rich per-bar diagnostics."""
    nav:          pd.Series
    net_ret:      pd.Series
    port_ret:     pd.Series
    turnover:     pd.Series
    weights:      pd.DataFrame
    gross:        pd.Series
    net_exposure: pd.Series
    N_t:          pd.Series
    K_t:          pd.Series


@dataclass
class BookSummary:
    """One-row summary — Sharpe / cumret / CAGR / drawdown / turnover, each
    broken out by IS / OOS / full (= IS ∪ OOS, hold-out excluded).

    Raw per-bar data is preserved in ``BookResult.net_ret`` (persisted per
    ensemble as ``ensemble_net_ret.csv``), so any downstream per-year or
    rolling-window analysis can be reconstructed without re-running the
    engine.
    """
    n_bars:            int   = 0
    is_bars:           int   = 0
    oos_bars:          int   = 0
    # Sharpe
    is_sharpe:         float = 0.0
    oos_sharpe:        float = 0.0
    full_sharpe:       float = 0.0
    decay_ratio:       float = 0.0
    # Cumulative return (constant-notional; = Σ net_ret over window)
    is_cumret:         float = 0.0
    oos_cumret:        float = 0.0
    full_cumret:       float = 0.0
    # CAGR (annualized compound growth on the constant-notional NAV path)
    is_cagr:           float = 0.0
    oos_cagr:          float = 0.0
    full_cagr:         float = 0.0
    # Max drawdown (fraction of NAV, always ≤ 0)
    is_max_dd:         float = 0.0
    oos_max_dd:        float = 0.0
    full_max_dd:       float = 0.0
    # Volatility + position/turnover diagnostics
    annual_vol:        float = 0.0
    avg_turnover:      float = 0.0
    net_exposure_mean: float = 0.0
    gross_mean:        float = 0.0
    mean_N:            float = 0.0
    mean_K:            float = 0.0


# ---------------------------------------------------------------------- #
# Weight builders
# ---------------------------------------------------------------------- #
def _eligible_mask(alpha: pd.DataFrame,
                   sigma: pd.DataFrame,
                   membership: pd.DataFrame) -> pd.DataFrame:
    """Per-cell eligibility: α defined, σ defined and positive, member."""
    idx  = alpha.index
    cols = alpha.columns
    s = sigma.reindex(index=idx, columns=cols)
    m = (membership.reindex(index=idx, columns=cols)
                   .astype("boolean").fillna(False))
    return alpha.notna() & s.notna() & (s > 0) & m.astype(bool)


def _K_per_bar(N_t: pd.Series, q: float, mode: str) -> pd.Series:
    """K_t := max(1, ⌈q·N_t⌉); LS requires ≥ 2 eligible names else 0."""
    N = N_t.astype(int).to_numpy()
    K = np.maximum(1, np.ceil(q * N)).astype(int)
    K = np.where(N == 0, 0, K)
    if mode == "ls":
        # LS needs at least one long + one short. If K > N/2, cap so long
        # and short sets don't overlap.
        K = np.minimum(K, np.maximum(0, N // 2))
        K = np.where(N < 2, 0, K)
    return pd.Series(K, index=N_t.index, name="K_t")


def build_static_weights(alpha: pd.DataFrame,
                         sigma: pd.DataFrame,
                         membership: pd.DataFrame,
                         q: float,
                         mode: str) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Build the T×N weight panel for one static book variant.

    Returns
    -------
    W    : T×N weight panel (0.0 where flat / ineligible)
    N_t  : eligible-count per bar
    K_t  : selection-size per bar (0 = flat)
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    if not (0.0 < q <= 1.0):
        raise ValueError("q must be in (0, 1]")

    eligible = _eligible_mask(alpha, sigma, membership)
    N_t = eligible.sum(axis=1).astype(int).rename("N_t")
    K_t = _K_per_bar(N_t, q, mode)

    # Vectorized: eligibility → per-row rank → mask by K → 1/σ weights.
    # ~30× faster than the row-loop version — matters at 944 factors × 6
    # grid cells.
    A = alpha.where(eligible)
    ranks = A.rank(axis=1, method="first", ascending=False)   # 1 = top-α
    inv_sig = (1.0 / sigma).where(eligible)

    K_col = K_t.astype(float)          # per-bar broadcast target

    long_mask = ranks.le(K_col, axis=0) & ranks.notna()
    long_num  = inv_sig.where(long_mask, 0.0)
    long_den  = long_num.sum(axis=1).replace(0.0, np.nan)
    long_w    = long_num.div(long_den, axis=0).fillna(0.0)

    if mode == "long":
        W = long_w
    else:  # ls — bottom-K by rank (rank > N_t - K_t)
        cutoff = (N_t.astype(float) - K_col)
        short_mask = ranks.gt(cutoff, axis=0) & ranks.notna()
        short_num  = inv_sig.where(short_mask, 0.0)
        short_den  = short_num.sum(axis=1).replace(0.0, np.nan)
        short_w    = short_num.div(short_den, axis=0).fillna(0.0)
        W = 0.5 * long_w - 0.5 * short_w

    # Belt-and-suspenders: zero out any bar where K_t == 0.
    zero_bars = K_t.eq(0)
    if zero_bars.any():
        W.loc[zero_bars.values] = 0.0
    return W, N_t, K_t


# ---------------------------------------------------------------------- #
# Backtest driver
# ---------------------------------------------------------------------- #
@dataclass
class _WindowStats:
    sharpe:   float = 0.0
    ann_ret:  float = 0.0
    ann_vol:  float = 0.0
    cumret:   float = 0.0
    cagr:     float = 0.0
    max_dd:   float = 0.0
    n_bars:   int   = 0


def _window_sharpe(net: pd.Series) -> _WindowStats:
    """Per-window backtest stats on a per-bar net-return series.

    Convention A (constant-notional): NAV = 1 + Σ net_ret. Cumulative
    return = Σ net_ret = NAV[-1] − 1. CAGR is compounded on the NAV path
    itself, so a −100%+ drawdown is treated as a full loss (guarded by
    ``max(1e-9, ...)`` before the fractional power). Sharpe uses
    arithmetic-mean annualization at ``C.WEEKS_PER_YEAR`` — matches the
    v4pool convention for direct comparability.
    """
    n = int(len(net))
    if n < 2:
        return _WindowStats(n_bars=n)
    ann_vol  = float(net.std(ddof=1)) * np.sqrt(C.WEEKS_PER_YEAR)
    ann_ret  = float(net.mean()) * C.WEEKS_PER_YEAR
    sharpe   = (ann_ret / ann_vol) if ann_vol > 0 else 0.0
    cumret   = float(net.sum())
    n_years  = max(n / C.WEEKS_PER_YEAR, 1e-3)
    cagr     = max(1.0 + cumret, 1e-9) ** (1.0 / n_years) - 1.0
    nav      = 1.0 + net.cumsum()
    cummax   = nav.cummax()
    max_dd   = float(((nav - cummax) / cummax).min())
    return _WindowStats(sharpe=sharpe, ann_ret=ann_ret, ann_vol=ann_vol,
                        cumret=cumret, cagr=cagr, max_dd=max_dd, n_bars=n)


def run_book(W: pd.DataFrame,
             fwd_1w: pd.DataFrame,
             cost_per_trade: float = DEFAULT_COST_PER_TRADE,
             initial_capital: float = DEFAULT_INITIAL_CAPITAL,
             N_t: pd.Series | None = None,
             K_t: pd.Series | None = None) -> BookResult:
    """Backtest a pre-built weight panel W against W-FRI forward returns.

    W and fwd_1w must share the same W-FRI grid. Weight at bar t earns
    fwd_1w[t] (return t → t+1). NaN fwd is treated as 0 return (a delisted
    or missing name contributes nothing that bar, consistent with the
    static-baseline convention).
    """
    idx = W.index.intersection(fwd_1w.index)
    W = W.reindex(idx).fillna(0.0)
    F = fwd_1w.reindex(idx)[W.columns].fillna(0.0)

    port_ret = (W * F).sum(axis=1)
    turnover = W.diff().abs().sum(axis=1).fillna(0.0)
    cost = turnover * cost_per_trade
    net  = port_ret - cost

    nav_body = 1.0 + net.cumsum()
    nav = initial_capital * nav_body

    return BookResult(
        nav=nav,
        net_ret=net,
        port_ret=port_ret,
        turnover=turnover,
        weights=W,
        gross=W.abs().sum(axis=1),
        net_exposure=W.sum(axis=1),
        N_t=(N_t.reindex(idx) if N_t is not None else pd.Series(np.nan, index=idx)),
        K_t=(K_t.reindex(idx) if K_t is not None else pd.Series(np.nan, index=idx)),
    )


def _windowize(net: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Split a net-return series into (IS, OOS, hold-out) by _common_v6 dates.

    Hold-out (> OOS_END) is discarded outright — the engine must never
    surface it in any Sharpe number without an explicit request.
    """
    idx = net.index
    is_mask   = idx <= C.IN_SAMPLE_END
    oos_mask  = (idx >= C.OOS_START) & (idx <= C.OOS_END)
    hold_mask = idx > C.OOS_END
    return net[is_mask], net[oos_mask], net[hold_mask]


def summarize_book(res: BookResult) -> BookSummary:
    """Compute IS/OOS/full stats: Sharpe, cumret, CAGR, max drawdown,
    plus turnover + gross/net exposure diagnostics.

    Full = IS ∪ OOS (the hold-out beyond ``OOS_END`` is excluded — see
    ``_windowize``). Decay = OOS/IS Sharpe when |IS Sharpe| > 0.
    """
    net = res.net_ret
    is_net, oos_net, _hold = _windowize(net)
    full_net = pd.concat([is_net, oos_net])

    is_s   = _window_sharpe(is_net)
    oos_s  = _window_sharpe(oos_net)
    full_s = _window_sharpe(full_net)
    decay  = (oos_s.sharpe / is_s.sharpe) if abs(is_s.sharpe) > 1e-12 else 0.0

    N_defined = res.N_t.dropna()
    K_defined = res.K_t.dropna()

    return BookSummary(
        n_bars           = full_s.n_bars,
        is_bars          = is_s.n_bars,
        oos_bars         = oos_s.n_bars,
        is_sharpe        = float(is_s.sharpe),
        oos_sharpe       = float(oos_s.sharpe),
        full_sharpe      = float(full_s.sharpe),
        decay_ratio      = float(decay),
        is_cumret        = float(is_s.cumret),
        oos_cumret       = float(oos_s.cumret),
        full_cumret      = float(full_s.cumret),
        is_cagr          = float(is_s.cagr),
        oos_cagr         = float(oos_s.cagr),
        full_cagr        = float(full_s.cagr),
        is_max_dd        = float(is_s.max_dd),
        oos_max_dd       = float(oos_s.max_dd),
        full_max_dd      = float(full_s.max_dd),
        annual_vol       = float(full_s.ann_vol),
        avg_turnover     = float(res.turnover.reindex(full_net.index).mean()),
        net_exposure_mean= float(res.net_exposure.reindex(full_net.index).mean()),
        gross_mean       = float(res.gross.reindex(full_net.index).mean()),
        mean_N           = float(N_defined.reindex(full_net.index).mean()),
        mean_K           = float(K_defined.reindex(full_net.index).mean()),
    )


# ---------------------------------------------------------------------- #
# One-shot convenience
# ---------------------------------------------------------------------- #
def backtest_alpha(alpha: pd.DataFrame,
                   sigma: pd.DataFrame,
                   fwd_1w: pd.DataFrame,
                   membership: pd.DataFrame,
                   q: float,
                   mode: str,
                   cost_per_trade: float = DEFAULT_COST_PER_TRADE
                   ) -> tuple[BookResult, BookSummary]:
    """Build weights → backtest → summarize. Convenience wrapper for the
    screener loop where we don't need intermediate access to weights."""
    W, N_t, K_t = build_static_weights(alpha, sigma, membership, q, mode)
    res = run_book(W, fwd_1w, cost_per_trade=cost_per_trade, N_t=N_t, K_t=K_t)
    return res, summarize_book(res)
