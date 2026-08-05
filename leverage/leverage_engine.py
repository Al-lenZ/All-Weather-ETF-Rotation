"""v6/leverage/leverage_engine.py — whole-book vol-targeted leverage engine.

Consumes a pre-built book (from ``rb_variants.build_book``) and applies:

1. σ_est_t via ``vol_estimators.weekly_ewma_52`` on the *un-levered* book
   return series, shifted by 1 bar to enforce causality (σ_est at bar t
   uses only returns realized by t-1).
2. ``L_t = clip(σ*/σ_est_t, 1.0, cap)``, fixed σ* = 3.2 % annualized,
   cap = 2.0. If ``apply_leverage=False`` the engine falls back to
   ``L_t ≡ 1`` for the two "no-lev" cells.
3. Levered weights ``W_lev[t] = L_t · W_name[t]``. Split trading cost
   recomputed on ``W_lev`` at PLAN §1 rates (2 bp/side bond,
   10 bp/side non-bond).
4. Weekly bar net return, per PLAN §5A step 6:

       net_ret_t = L_t · r_book_pre_cost_t
                 + cash_carry_t
                 − funding_cost_t
                 − turnover_cost_t

   where ``cash_carry_t = cash_share_t · dr007_accrual_t`` (symmetric cash
   accounting per PLAN §1), and ``funding_cost_t = (L_t − 1) ·
   funding_accrual_t``. Both accrue only on bars where the book is
   invested (``Σ W_name > 0``) so the pre-warmup zero-net segment stays
   flat, matching the finalist net_ret series bit-for-bit when leverage
   and carry are both off.

The engine intentionally does NOT compute IS / OOS / stress metrics — that
lives in ``run_cell.py`` so the leverage kernel stays a pure function of
(book bundle, config).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

import _common_leverage as CL
import vol_estimators as VE
import funding_curves as FC


@dataclass
class LeverageResult:
    """Full artifact bundle a single leverage cell needs to persist."""
    # bar-level series (weekly index)
    net_ret:        pd.Series          # ← the PASS metric input
    r_book_lev:     pd.Series          # L · r_book_pre_cost (pre carry / cost)
    L_t:            pd.Series
    sigma_est:      pd.Series          # causal (shifted by 1)
    sigma_realized: pd.Series          # 4w-forward std × √52 (truth proxy)
    cash_share:     pd.Series
    cash_carry:     pd.Series          # DR007 credit on cash sleeve
    funding_cost:   pd.Series          # (L-1) · funding_accrual
    funding_accrual: pd.Series         # per-bar accrual, from curve
    dr007_accrual:  pd.Series
    turn_bond:      pd.Series          # split on the levered book
    turn_nonbond:   pd.Series
    cost:           pd.Series          # trading cost per bar
    invested:       pd.Series          # bool: Σ W_name > 0
    # book-level knobs
    sigma_star:     float
    cap:            float
    funding_curve:  str
    cash_carry_curve: str
    apply_leverage: bool
    apply_cash_carry: bool
    # frames
    W_lev:          pd.DataFrame       # L · W_name — for verification
    W_name:         pd.DataFrame       # un-levered (echo)
    is_bond:        dict


def _split_cost_on_lev(W_lev: pd.DataFrame,
                       is_bond: dict[str, bool]
                       ) -> tuple[pd.Series, pd.Series, pd.Series]:
    dW = W_lev.diff().abs().fillna(0.0)
    bond_cols = [c for c in W_lev.columns if is_bond.get(c, False)]
    nb_cols   = [c for c in W_lev.columns if not is_bond.get(c, False)]
    t_b = (dW[bond_cols].sum(axis=1) if bond_cols
           else pd.Series(0.0, index=W_lev.index))
    t_n = (dW[nb_cols].sum(axis=1) if nb_cols
           else pd.Series(0.0, index=W_lev.index))
    cost = (t_b * CL.COST_BOND_BP + t_n * CL.COST_NONBOND_BP) * 1e-4
    return (t_b.rename("turn_bond"),
            t_n.rename("turn_nonbond"),
            cost.rename("cost"))


def apply_book_vol_target(book: dict,
                          sigma_star: float = CL.SIGMA_STAR,
                          cap:        float = CL.CAP,
                          funding_curve:    str  = "gc007",
                          cash_carry_curve: str  = "dr007",
                          apply_leverage:   bool = True,
                          apply_cash_carry: bool = True,
                          L_mode:           str  = "vol_target",
                          halflife_weeks:   int  = CL.SIGMA_EST_WEEKLY_HALFLIFE,
                          min_periods:      int  = 13,
                          ) -> LeverageResult:
    """Apply vol-targeted leverage to a pre-built book.

    Parameters
    ----------
    book              output of ``rb_variants.build_book``.
    sigma_star, cap   book-level target vol (annualized) and hard L cap.
    funding_curve     curve id for the borrow leg (GC007 upper / DR007 proxy).
    cash_carry_curve  curve id for the deposit leg (DR007 proxy for now).
    apply_leverage    False → L_t ≡ 1 (used by no-lev cells).
    apply_cash_carry  False → cash sleeve earns nothing (used by the M3
                      "reproduce finalist within 1 bp" sanity check).
    L_mode            "vol_target" (default) → L_t = clip(σ*/σ_est, 1, cap);
                      "static"      → L_t ≡ cap on every invested bar.
                      σ_est / σ_realized still tracked as diagnostic-only
                      under "static" so PLAN §7 columns stay populated.
                      Used by the Round-B ``B_*_lev_static`` sanity cells.
    """
    if L_mode not in ("vol_target", "static"):
        raise ValueError(f"L_mode must be vol_target or static, got {L_mode!r}")
    W_name    = book["W_name"]
    fwd       = book["fwd_1w"]
    r_pre     = book["r_book_pre_cost"]
    cash      = book["cash_share"]
    is_bond   = book["is_bond"]
    weekly_idx = W_name.index

    invested = (W_name.abs().sum(axis=1) > 0.0).rename("invested")

    # 1. σ_est from un-levered book return series, causal (shift 1)
    sigma_est = VE.weekly_ewma_52(
        r_pre, halflife_weeks=halflife_weeks, min_periods=min_periods,
    ).shift(1).rename("sigma_est")

    # truth proxy for the σ_est-vs-realized ratio diagnostic column
    sigma_realized = VE.realized_forward_ann(
        r_pre, horizon_weeks=CL.SIGMA_EST_HORIZON_WEEKS,
    ).rename("sigma_realized")

    # 2. L_t. Bars where σ_est is NaN → L=1 (warmup); non-invested bars → L=1.
    if not apply_leverage:
        L_t = pd.Series(1.0, index=weekly_idx)
    elif L_mode == "static":
        L_t = pd.Series(float(cap), index=weekly_idx)
    else:   # "vol_target"
        L_raw = (sigma_star / sigma_est).where(sigma_est > 0)
        L_t = L_raw.clip(lower=1.0, upper=cap).fillna(1.0)
    L_t = L_t.where(invested, 1.0).rename("L_t")

    # 3. levered weights + split cost on levered turnover
    W_lev = W_name.mul(L_t, axis=0)
    turn_b, turn_n, cost = _split_cost_on_lev(W_lev, is_bond)

    # 4. funding + cash carry accruals (weekly, ACT/365 over bar's days)
    fund_daily  = FC.load(funding_curve)
    cash_daily  = FC.load(cash_carry_curve)
    fund_accrual = FC.weekly_accrual(fund_daily, weekly_idx).reindex(weekly_idx).fillna(0.0)
    dr007_accrual = FC.weekly_accrual(cash_daily, weekly_idx).reindex(weekly_idx).fillna(0.0)
    fund_accrual  = fund_accrual.rename("funding_accrual")
    dr007_accrual = dr007_accrual.rename("dr007_accrual")

    # Only accrue on invested bars — matches finalist's "flat before warmup"
    # semantic and keeps A_base_nolev(no-carry) bit-for-bit vs finalist.
    fund_accrual  = fund_accrual.where(invested, 0.0)
    dr007_accrual = dr007_accrual.where(invested, 0.0)

    funding_cost = ((L_t - 1.0) * fund_accrual).rename("funding_cost")
    if apply_cash_carry:
        cash_carry = (cash * dr007_accrual).rename("cash_carry")
    else:
        cash_carry = pd.Series(0.0, index=weekly_idx, name="cash_carry")

    # 5. bar net return
    r_book_lev = (L_t * r_pre).rename("r_book_lev")
    net_ret = (r_book_lev + cash_carry - funding_cost - cost).rename("net_ret")

    return LeverageResult(
        net_ret=net_ret,
        r_book_lev=r_book_lev,
        L_t=L_t,
        sigma_est=sigma_est,
        sigma_realized=sigma_realized,
        cash_share=cash,
        cash_carry=cash_carry,
        funding_cost=funding_cost,
        funding_accrual=fund_accrual,
        dr007_accrual=dr007_accrual,
        turn_bond=turn_b,
        turn_nonbond=turn_n,
        cost=cost,
        invested=invested,
        sigma_star=sigma_star,
        cap=cap,
        funding_curve=funding_curve,
        cash_carry_curve=cash_carry_curve,
        apply_leverage=apply_leverage,
        apply_cash_carry=apply_cash_carry,
        W_lev=W_lev,
        W_name=W_name,
        is_bond=is_bond,
    )


# ============================================================================
# Bond-leg-only sanity kernel (PLAN §5B / §6 Round B B_win_bondleg_lev)
# ============================================================================
def apply_bondleg_vol_target(book: dict,
                             sigma_star_bondleg: float = CL.SIGMA_STAR_BONDLEG,
                             cap: float = CL.CAP,
                             funding_curve:    str  = "gc007",
                             cash_carry_curve: str  = "dr007",
                             apply_cash_carry: bool = True,
                             halflife_weeks:   int  = CL.SIGMA_EST_WEEKLY_HALFLIFE,
                             min_periods:      int  = 13,
                             ) -> LeverageResult:
    """Bond-leg-only vol target. Equity / commodity legs pass through
    un-levered; L_t applies only to bond-tagged names (PLAN §5B). Written
    against ``LeverageResult`` so downstream `run_cell`/`metrics` code
    doesn't need a separate summary path.

    - σ_est_leg is computed on the *bond-leg* return series (Σ_bond
      W_name[t] · fwd_1w[t]) via weekly_ewma_52, shift(1) causal.
    - Funding cost = (L_t − 1) · bond_leg_share · funding_accrual.
      Only the borrowed portion of the bond leg pays repo.
    - Cost split, cash carry, duration ledger reused unchanged; duration
      ledger will show a proportional lift because W_lev = L·W on bonds only.

    Sanity check on PLAN §二: does leg-only leverage produce a materially
    different signature from whole-book leverage?
    """
    W_name    = book["W_name"]
    fwd       = book["fwd_1w"]
    r_pre     = book["r_book_pre_cost"]        # whole-book, for logging only
    cash      = book["cash_share"]
    is_bond   = book["is_bond"]
    weekly_idx = W_name.index

    invested = (W_name.abs().sum(axis=1) > 0.0).rename("invested")

    # Bond-leg-only weight sub-panel and its pre-cost return series
    bond_cols = [c for c in W_name.columns if is_bond.get(c, False)]
    if not bond_cols:
        raise RuntimeError("bondleg engine: no bond tickers in book")
    W_bond = W_name[bond_cols]
    fwd_bond = fwd[bond_cols]
    r_bond = (W_bond * fwd_bond).sum(axis=1).rename("r_bond_pre_cost")
    bond_share = W_bond.sum(axis=1).rename("bond_share")   # Σ_bond W ~ 0.9

    # σ_est on bond-leg return, causal (shift 1)
    sigma_est = VE.weekly_ewma_52(
        r_bond, halflife_weeks=halflife_weeks, min_periods=min_periods,
    ).shift(1).rename("sigma_est")

    sigma_realized = VE.realized_forward_ann(
        r_bond, horizon_weeks=CL.SIGMA_EST_HORIZON_WEEKS,
    ).rename("sigma_realized")

    # L_t
    L_raw = (sigma_star_bondleg / sigma_est).where(sigma_est > 0)
    L_t = (L_raw.clip(lower=1.0, upper=cap)
                 .fillna(1.0)
                 .where(invested, 1.0)
                 .rename("L_t"))

    # W_lev = L·W on bonds, W on non-bonds. Bond names concat with non-bond.
    nb_cols = [c for c in W_name.columns if not is_bond.get(c, False)]
    W_bond_lev = W_bond.mul(L_t, axis=0)
    W_lev = pd.concat([W_bond_lev, W_name[nb_cols]], axis=1)[W_name.columns]

    # Split cost on the levered W_lev
    turn_b, turn_n, cost = _split_cost_on_lev(W_lev, is_bond)

    # Funding & cash accruals
    fund_daily = FC.load(funding_curve)
    cash_daily = FC.load(cash_carry_curve)
    fund_accrual = FC.weekly_accrual(fund_daily, weekly_idx).reindex(weekly_idx).fillna(0.0)
    dr007_accrual = FC.weekly_accrual(cash_daily, weekly_idx).reindex(weekly_idx).fillna(0.0)
    fund_accrual  = fund_accrual.rename("funding_accrual").where(invested, 0.0)
    dr007_accrual = dr007_accrual.rename("dr007_accrual").where(invested, 0.0)

    # Funding cost on the bond-leg borrowed notional only
    funding_cost = ((L_t - 1.0) * bond_share * fund_accrual).rename("funding_cost")
    if apply_cash_carry:
        cash_carry = (cash * dr007_accrual).rename("cash_carry")
    else:
        cash_carry = pd.Series(0.0, index=weekly_idx, name="cash_carry")

    # Book return = L·r_bond + r_nonbond
    r_nb = (W_name[nb_cols] * fwd[nb_cols]).sum(axis=1) if nb_cols else pd.Series(0.0, index=weekly_idx)
    r_book_lev = (L_t * r_bond + r_nb).rename("r_book_lev")
    net_ret = (r_book_lev + cash_carry - funding_cost - cost).rename("net_ret")

    return LeverageResult(
        net_ret=net_ret,
        r_book_lev=r_book_lev,
        L_t=L_t,
        sigma_est=sigma_est,
        sigma_realized=sigma_realized,
        cash_share=cash,
        cash_carry=cash_carry,
        funding_cost=funding_cost,
        funding_accrual=fund_accrual,
        dr007_accrual=dr007_accrual,
        turn_bond=turn_b,
        turn_nonbond=turn_n,
        cost=cost,
        invested=invested,
        sigma_star=sigma_star_bondleg,        # leg σ*
        cap=cap,
        funding_curve=funding_curve,
        cash_carry_curve=cash_carry_curve,
        apply_leverage=True,
        apply_cash_carry=apply_cash_carry,
        W_lev=W_lev,
        W_name=W_name,
        is_bond=is_bond,
    )


__all__ = ["LeverageResult", "apply_book_vol_target", "apply_bondleg_vol_target"]
