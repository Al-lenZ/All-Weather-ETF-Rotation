"""v6/leverage/rb_variants.py — book-weight builder for {base, EW} RB.

Wraps ``block_two_layer_v6.run_variant`` but forces a specific policy dict
into the layer-1 risk budgeter. The two-layer q=0.20 ε=0.30 finalist recipe
(invvol × lw_erc, no trend gate, α on broad_cn+sector_cn) is frozen — only
the layer-1 policy shares vary.

Return bundle (per PLAN §4):

- ``W_group``           T×G group weight panel (Σ_group_col over t is what
                        the risk budgeter allocated; 1 − Σ = structural cash).
- ``W_name``            T×N name-level weight panel (each column is W_group ×
                        within-block sub-book share; Σ per bar ≤ 1).
- ``r_book_gross``      pre-leverage weekly book return series
                        (net of trading cost at PLAN split cost table).
- ``r_book_pre_cost``   pre-leverage weekly book return series, before any
                        trading cost — used to compute σ_est so estimator
                        is not muddied by cost-driven noise.
- ``turnover_wkly``     per-name Σ|Δw|; needed downstream to recompute
                        cost after leverage scales the book.
- ``turnover_bond``,
  ``turnover_nonbond``  split turnover series (bar-level Σ over bond and
                        non-bond ticker sets). Cost = 2 bp/side * turnover_bond
                        + 10 bp/side * turnover_nonbond per PLAN §1.
- ``is_bond``           dict[code -> bool], asset-class flag from block_tag →
                        group_of(block) ∈ {bond_rates, bond_credit}.
- ``cash_share``        (1 − Σ_i W_name[t, i]) per bar; ≥ 0. DR007 accrues
                        on this sleeve under symmetric cash accounting.

Note: the two-layer builder in ``block_two_layer_v6.run_variant`` calls
``block_risk_budget_v6.build_block_weights`` with the module-level
``BR.POLICY_SHARES`` hard-coded. To route a different policy in without
touching frozen code, this file replicates the tail of ``run_variant``
(post-composite aggregation → layer-1 solve → name-level aggregation) with
``policy_shares`` as a parameter. The α-block composite construction
(``build_composites_two_layer``) is unchanged and reused.
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

import _common_leverage as CL

# these come from v6/scripts (added to sys.path by _common_leverage)
# --- v6/common sys.path bootstrap ---
import sys as _v6_sys
from pathlib import Path as _V6Path
_v6_p = _V6Path(__file__).resolve().parent
while _v6_p.name != "v6" and _v6_p.parent != _v6_p:
    _v6_p = _v6_p.parent
_v6_sys.path.insert(0, str(_v6_p / "common"))
del _v6_p
# --------------------------------------
import block_composite_v6 as BC          # noqa: E402
import block_risk_budget_v6 as BR        # noqa: E402
import block_two_layer_v6 as BT          # noqa: E402
import exp2_representative_sets_v6 as EX2  # noqa: E402


RbId = Literal["base", "EW"]


# Non-α blocks eligible for representative-set compression (matches
# EX2.NON_ALPHA_BLOCKS). α blocks (broad_cn, sector_cn) are never
# compressed — they carry the finalist α selection at q=0.20, ε=0.30.
_REPS_BLOCKS: tuple[str, ...] = EX2.NON_ALPHA_BLOCKS
_REPS_CSV_DIR = CL.DATA_DIR / "exp2_representative_sets_v6"


def _load_frozen_reps() -> dict[str, tuple[pd.DataFrame, pd.DataFrame]]:
    """Load the frozen exp2 annual-refresh clusters/reps CSVs and split
    per-block. These are the *adaptive-K* output of
    `exp2_representative_sets_v6` at the 0.20 residual-vol threshold —
    treated here as an input-data source of truth, not recomputed.

    Returns {block -> (clusters_df, reps_df)} for the 6 non-α blocks.
    Missing files raise so a mis-configured cell fails loud rather than
    silently degrading to hold-all.
    """
    c_path = _REPS_CSV_DIR / "clusters_yearly.csv"
    r_path = _REPS_CSV_DIR / "reps_yearly.csv"
    if not c_path.exists() or not r_path.exists():
        raise FileNotFoundError(
            f"reps CSVs not found under {_REPS_CSV_DIR}. Run "
            "`python v6/scripts/exp2_representative_sets_v6.py` first."
        )
    clusters = pd.read_csv(c_path)
    reps     = pd.read_csv(r_path)
    out: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for b in _REPS_BLOCKS:
        cb = clusters[clusters["block"] == b]
        rb = reps[reps["block"] == b]
        if cb.empty or rb.empty:
            continue
        out[b] = (cb.reset_index(drop=True), rb.reset_index(drop=True))
    return out


def _reps_by_year(reps_df: pd.DataFrame) -> dict[int, list[str]]:
    """{year -> [rep_code, ...]} from the per-year reps_df. Preserves the
    exp2 refresh-date semantics (annual, first-W-FRI of Jan)."""
    out: dict[int, list[str]] = {}
    for y, g in reps_df.groupby("year"):
        out[int(y)] = [str(c) for c in g["rep_code"].astype(str).tolist()]
    return out


def _asof_year_lookup(idx_years: np.ndarray,
                      years_available: list[int]) -> np.ndarray:
    """For each bar's calendar year, pick the latest refresh year ≤ y.
    Bars before the earliest refresh fall back to years_available[0]
    (matches exp2 convention)."""
    ya = np.array(years_available, dtype=int)
    return np.array([
        int(ya[ya <= y].max()) if (ya <= y).any() else int(ya[0])
        for y in idx_years
    ])


def _build_reps_invvol_subblock(shared: dict,
                                block: str,
                                clusters_df: pd.DataFrame,
                                reps_df: pd.DataFrame,
                                ) -> pd.DataFrame:
    """Rep-only invvol sub-block: pick the K reps for bar t's refresh year,
    weight each rep by 1/σ_i(t) among the reps that are eligible on bar t,
    normalize so ``Σ_block = 1``.

    Semantics (vs the exp2 `build_replicated_block`):
      * Old exp2: inherit the *hold-all* invvol mass of the full block
        member set, then collapse cluster mass onto the rep IF the rep is
        eligible; otherwise drop to cash. Systematically leaks 8-32 %
        block mass into cash on early years where reps aren't yet listed
        or when non-rep members are eligible but their rep isn't. See
        `data/leverage/_reps_diag/` diagnostic (2026-07-31).
      * New (this function): invest the block FULLY in the K reps,
        invvol-weighted among *themselves* only. Ignores non-rep members
        entirely (that's the whole point of the compression). If a rep is
        ineligible on bar t, redistribute among the remaining eligible
        reps. If all reps ineligible, block sum = 0 (rare data-boundary
        case). Uses `shared["sigma"]` for the causal σ estimate — same
        panel the hold-all invvol composite already uses.
    """
    mem = shared["membership"]
    sig = shared["sigma"]
    reps_b = reps_df[reps_df["block"] == block]
    if reps_b.empty:
        return pd.DataFrame(0.0, index=mem.index, columns=[])

    reps_by_year = _reps_by_year(reps_b)
    years_available = sorted(reps_by_year)
    if not years_available:
        return pd.DataFrame(0.0, index=mem.index, columns=[])

    # Every rep_code that ever appears across all years — form the
    # column universe of the sub-block panel.
    all_reps = sorted({r for reps in reps_by_year.values() for r in reps})
    all_reps = [r for r in all_reps if r in mem.columns]
    if not all_reps:
        return pd.DataFrame(0.0, index=mem.index, columns=[])

    mem_r = mem[all_reps]
    sig_r = sig[all_reps]
    eligible = mem_r & sig_r.notna() & (sig_r > 0)
    inv_sig  = (1.0 / sig_r).where(eligible, 0.0)

    idx_years = mem_r.index.year.astype(int).to_numpy()
    y_use_arr = _asof_year_lookup(idx_years, years_available)

    # Per-bar year → active rep set → invvol-weight → normalize
    inv_np = inv_sig.to_numpy()
    W_np   = np.zeros_like(inv_np)
    col_pos = {c: i for i, c in enumerate(all_reps)}

    active_mask_by_year: dict[int, np.ndarray] = {}
    for y in years_available:
        m = np.zeros(len(all_reps), dtype=bool)
        for r in reps_by_year[y]:
            j = col_pos.get(r)
            if j is not None:
                m[j] = True
        active_mask_by_year[int(y)] = m

    for i, y_use in enumerate(y_use_arr):
        active = active_mask_by_year[int(y_use)]
        row_inv = inv_np[i] * active   # zero out non-active-year reps
        s = float(row_inv.sum())
        if s > 0:
            W_np[i] = row_inv / s

    return pd.DataFrame(W_np, index=mem_r.index, columns=all_reps)


def _build_composites_reps(shared: dict,
                           q: float, epsilon: float,
                           alpha_scores: dict[str, pd.DataFrame],
                           reps_yearly: dict[str, tuple[pd.DataFrame,
                                                          pd.DataFrame]],
                           ) -> dict:
    """Two-layer composite build with non-α blocks swapped for the
    representative-set replicated invvol composite. Mirrors
    `block_two_layer_v6.build_composites_two_layer` in shape so the
    downstream layer-1 solver / name aggregation stays identical.

    α blocks (broad_cn, sector_cn) keep the finalist α sub-blocks.
    Any non-α block missing from `reps_yearly` falls back to hold-all
    (defensive — should not happen if the CSVs are the frozen exp2 set).
    """
    N_counts = BT._static_member_counts(shared)
    concat_group: dict[str, pd.DataFrame] = {}
    per_block:    dict[str, dict[str, pd.DataFrame]] = {}
    for grp, blocks in BC.BLOCK_GROUPS.items():
        N_g = sum(N_counts.get(b, 0) for b in blocks)
        pb: dict[str, pd.DataFrame] = {}
        frames = []
        for b in blocks:
            N_b = N_counts.get(b, 0)
            if N_b == 0:
                continue
            if b in BT.ALPHA_BLOCKS and q < 1.0:
                W_sub = BT.build_alpha_subblock(
                    shared, b, alpha_scores[b], q, epsilon,
                    sizing=BT.ALPHA_SIZING,
                )
            elif b in reps_yearly:
                cdf, rdf = reps_yearly[b]
                W_sub = _build_reps_invvol_subblock(shared, b, cdf, rdf)
            else:
                W_sub = BT.build_holdall_subblock(
                    shared, b,
                    sizing=(BT.ALPHA_SIZING if b in BT.ALPHA_BLOCKS
                                             else BT.NONALPHA_SIZING),
                )
            share = N_b / N_g if N_g > 0 else 0.0
            W_scaled = W_sub * share
            pb[b] = W_scaled
            frames.append(W_scaled)
        per_block[grp] = pb
        concat_group[grp] = (pd.concat(frames, axis=1)
                             if frames
                             else pd.DataFrame(index=shared["fwd_1w"].index))

    fwd = shared["fwd_1w"]
    rets: dict[str, pd.Series] = {}
    for grp, W_g in concat_group.items():
        if W_g.shape[1] == 0:
            rets[grp] = pd.Series(np.nan, index=fwd.index, name=grp)
            continue
        fwd_g = fwd.reindex(columns=W_g.columns).fillna(0.0)
        r_g = (W_g * fwd_g).sum(axis=1)
        invested = (W_g.abs().sum(axis=1) > 0.0)
        rets[grp] = r_g.where(invested).rename(grp)
    R = pd.concat([rets[g] for g in BC.GROUP_ORDER], axis=1)
    nav = pd.DataFrame(index=R.index, columns=R.columns, dtype=float)
    for g in R.columns:
        active = R[g].notna()
        r0 = R[g].where(active, 0.0)
        nav[g] = (1.0 + r0).cumprod()
        nav.loc[~active, g] = np.nan
    return {"returns": R, "nav": nav, "weights_group": concat_group,
            "weights_per_block": per_block}


def policy_shares(rb: RbId) -> dict[str, float]:
    if rb == "base":
        return dict(CL.POLICY_SHARES_BASE)
    if rb == "EW":
        return dict(CL.POLICY_SHARES_EW)
    raise ValueError(f"unknown rb: {rb!r}")


def _is_bond_map(block_tag: pd.Series) -> dict[str, bool]:
    """Map ticker → True iff its block is in a bond group (per PLAN §1
    split cost table). Uses ``block_composite_v6.BLOCK_GROUPS``: block
    ∈ (bond_rates,) or (bond_credit,) → bond."""
    bond_blocks: set[str] = set()
    for grp in ("bond_rates", "bond_credit"):
        bond_blocks.update(BC.BLOCK_GROUPS.get(grp, ()))
    return {code: bool(tag in bond_blocks) for code, tag in block_tag.items()}


def _bond_group_map(block_tag: pd.Series) -> dict[str, str]:
    """Map bond ticker → 'bond_rates' or 'bond_credit' (else absent)."""
    out: dict[str, str] = {}
    for grp in ("bond_rates", "bond_credit"):
        blocks = set(BC.BLOCK_GROUPS.get(grp, ()))
        for code, tag in block_tag.items():
            if tag in blocks:
                out[code] = grp
    return out


def _krd_map(bond_group: dict[str, str]) -> dict[str, float]:
    """Static KRD per bond ticker: explicit override if listed, else the
    per-block default (PLAN §7). Non-bond tickers omitted."""
    out: dict[str, float] = {}
    for code, grp in bond_group.items():
        if code in CL.KRD_OVERRIDES:
            out[code] = float(CL.KRD_OVERRIDES[code])
        else:
            out[code] = float(CL.KRD_DEFAULT_BY_BLOCK[grp])
    return out


def _split_cost(W_lev: pd.DataFrame,
                is_bond: dict[str, bool]) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Turnover series split by asset class + total dollar cost per bar.

    W_lev is the *effective* invested weight panel (already scaled by L_t
    if leverage is on). Turnover measured as Σ|Δw|; cost applied at
    2 bp/side for bond names, 10 bp/side for non-bond.
    """
    dW = W_lev.diff().abs().fillna(0.0)
    bond_cols = [c for c in W_lev.columns if is_bond.get(c, False)]
    nb_cols   = [c for c in W_lev.columns if not is_bond.get(c, False)]
    turn_bond = dW[bond_cols].sum(axis=1) if bond_cols else pd.Series(0.0, index=W_lev.index)
    turn_nb   = dW[nb_cols].sum(axis=1)   if nb_cols   else pd.Series(0.0, index=W_lev.index)
    cost_bp = (turn_bond * CL.COST_BOND_BP + turn_nb * CL.COST_NONBOND_BP) * 1e-4
    return turn_bond.rename("turn_bond"), turn_nb.rename("turn_nonbond"), cost_bp.rename("cost")


def build_book(shared: dict,
               rb: RbId,
               q: float = 0.20,
               epsilon: float = 0.30,
               use_trend: bool = BT.USE_TREND,
               budget_method: str = BT.BUDGET_METHOD,
               use_reps: bool = False,
               ) -> dict:
    """Build the two-layer finalist book with a swapable layer-1 policy.

    Mirrors ``block_two_layer_v6.run_variant`` in its layer-1 tail, but
    routes ``policy_shares`` (base 55/20/10/15 vs EW 25/25/25/25) into
    ``BR.build_block_weights`` explicitly.

    Bar-level book returns are computed here (not by ``xs_engine_v6.run_book``)
    so the leverage engine can attach L_t and cash / funding accruals
    downstream without re-doing the (W, fwd_1w) walk.

    ``use_reps`` — when True, the 6 non-α blocks are replaced by their
    representative-set replicated invvol composites (frozen exp2
    output; annual refresh, adaptive K at residual-vol threshold 0.20).
    α blocks stay on the finalist α selection. Used by the Round C
    leverage cells (post-hoc extension, PLAN §11 log 2026-07-31).
    """
    p_shares = policy_shares(rb)

    # α scores (invariant across cells; cached by caller if run in a loop)
    alpha_scores = BT.build_alpha_scores(shared)

    # 1. layer-2 composites (α on broad_cn + sector_cn, hold-all elsewhere)
    if use_reps:
        reps_yearly = _load_frozen_reps()
        comp = _build_composites_reps(shared, q, epsilon, alpha_scores,
                                      reps_yearly)
    else:
        comp = BT.build_composites_two_layer(shared, q, epsilon, alpha_scores)
    R    = comp["returns"][list(BC.GROUP_ORDER)]
    NAV  = comp["nav"][list(BC.GROUP_ORDER)]

    if use_trend:
        trend = BR.compute_trend_gate(NAV)
    else:
        trend = pd.DataFrame(True, index=R.index, columns=R.columns)

    # 2. layer-1 solve — this is where the policy dict actually matters
    W_group, RC_pct, diag = BR.build_block_weights(
        R, trend, budget_method, p_shares,
    )

    # 3. aggregate to name-level (identical to BT.run_variant tail)
    frames = []
    for grp in BC.GROUP_ORDER:
        Wg = comp["weights_group"][grp]
        if Wg.shape[1] == 0:
            continue
        scale = W_group[grp].reindex(Wg.index).fillna(0.0)
        frames.append(Wg.mul(scale, axis=0))
    W_name = pd.concat(frames, axis=1) if frames else pd.DataFrame(index=R.index)

    # 4. pre-leverage book returns (before cost)
    fwd = shared["fwd_1w"].reindex(columns=W_name.columns).fillna(0.0)
    r_book_pre_cost = (W_name * fwd).sum(axis=1).rename("r_book_pre_cost")

    # 5. asset-class map + split turnover / cost at un-levered baseline
    is_bond = _is_bond_map(shared["block_tag"])
    turn_bond, turn_nb, cost_ser = _split_cost(W_name, is_bond)
    r_book_gross = (r_book_pre_cost - cost_ser).rename("r_book_gross")   # net of cost, pre-lev

    cash_share = (1.0 - W_name.sum(axis=1)).clip(lower=0.0).rename("cash_share")

    # 6. bond ticker → group + static KRD (PLAN §7 duration ledger)
    bond_group = _bond_group_map(shared["block_tag"])
    krd = _krd_map(bond_group)

    return {
        "rb": rb, "q": q, "epsilon": epsilon,
        "use_reps": use_reps,
        "policy_shares": p_shares,
        "composites": comp,
        "W_group": W_group, "W_name": W_name,
        "trend_gate": trend, "RC_pct": RC_pct, "diag": diag,
        "r_book_pre_cost": r_book_pre_cost,
        "r_book_gross":    r_book_gross,   # pre-lev, net of cost
        "turn_bond":       turn_bond,
        "turn_nonbond":    turn_nb,
        "cost_series":     cost_ser,       # pre-lev cost series
        "cash_share":      cash_share,
        "is_bond":         is_bond,
        "bond_group":      bond_group,     # ticker -> {bond_rates, bond_credit}
        "krd":             krd,            # bond ticker -> years
        "fwd_1w":          fwd,
    }


def duration_ledger(W_lev: pd.DataFrame,
                    bond_group: dict[str, str],
                    krd: dict[str, float]) -> pd.DataFrame:
    """Per-bar duration disclosure (PLAN §7). Uses the *levered* weights
    so ``book_duration_yr`` reflects the actual dollar-duration exposure
    a levered book carries — that is the number risk managers care about.

    Columns
    -------
    bond_rates_share, bond_credit_share
        Σ_i W_lev[t, i] for i in the respective block. Under leverage
        L_t = 1.5 and unchanged W_name the share doubles to reflect the
        borrowed notional in that leg.
    bond_rates_krd, bond_credit_krd
        Weight-average KRD of names in the block at bar t, using ``W_lev``
        as the weight (NaN when the block share is 0).
    book_duration_yr
        Σ_i W_lev[t, i] · KRD_i over all bond names. Same as
        `Σ_g share_g · krd_g` where g ∈ {bond_rates, bond_credit}.
    """
    if W_lev.shape[1] == 0:
        idx = W_lev.index
        return pd.DataFrame({
            "bond_rates_share":  0.0, "bond_credit_share": 0.0,
            "bond_rates_krd":    np.nan, "bond_credit_krd":   np.nan,
            "book_duration_yr":  0.0,
        }, index=idx)

    rates_codes  = [c for c in W_lev.columns if bond_group.get(c) == "bond_rates"]
    credit_codes = [c for c in W_lev.columns if bond_group.get(c) == "bond_credit"]

    def _leg(codes: list[str]) -> tuple[pd.Series, pd.Series]:
        if not codes:
            idx = W_lev.index
            return (pd.Series(0.0, index=idx), pd.Series(np.nan, index=idx))
        W_g = W_lev[codes]
        share = W_g.sum(axis=1)
        krd_vec = np.array([krd[c] for c in codes], dtype=float)
        # dollar-duration in the leg = Σ w_i * krd_i
        dol_dur = (W_g.mul(krd_vec, axis=1)).sum(axis=1)
        krd_avg = (dol_dur / share.replace(0.0, np.nan))
        return share, krd_avg

    rt_share, rt_krd = _leg(rates_codes)
    cr_share, cr_krd = _leg(credit_codes)
    book_dur = (rt_share * rt_krd.fillna(0.0)
                + cr_share * cr_krd.fillna(0.0))

    return pd.DataFrame({
        "bond_rates_share":  rt_share.round(6),
        "bond_credit_share": cr_share.round(6),
        "bond_rates_krd":    rt_krd.round(4),
        "bond_credit_krd":   cr_krd.round(4),
        "book_duration_yr":  book_dur.round(4),
    })


__all__ = ["policy_shares", "build_book", "duration_ledger", "RbId"]
