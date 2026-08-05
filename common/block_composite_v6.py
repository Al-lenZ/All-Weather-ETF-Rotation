"""
v6/scripts/block_composite_v6.py
================================
Phase 12 layer-1 building block — per-group ETF sub-portfolios.

The block-level risk budgeter consumes a small (T × G) return panel where
each column is one "block group's" own no-alpha sub-portfolio. This module
builds that panel from the raw fwd_1w / sigma / membership panels and the
tagged catalogue.

Block groups (Phase 12 spec, per user 2026-07-22):

    equity      = broad_cn ∪ sector_cn ∪ cross_border_dm ∪ cross_border_hk
                  (smallcap_cn folded into broad_cn per BLOCK_MERGES)
    bond_rates  = bond_rates
    bond_credit = bond_credit
    commodity   = metals ∪ commodity_other

Two intra-block sizing kernels, since the user flagged both as open knobs
to compare in this branch:

    eqw     — 1/N_g among eligible members of the group at bar t
    invvol  — proportional to 1/σ_causal_26w among eligible members

Weights are renormalized within the group so Σ_i w_{group,i,t} = 1.

Exports
-------
    BLOCK_GROUPS : dict[str, tuple[str, ...]]
    BLOCK_MERGES : dict[str, str]
    build_group_weights(sigma, mem, tag, group, members, sizing) -> DataFrame
    build_composites(shared, sizings=(...))
        -> dict[sizing_name -> {"weights": {group -> T×N df},
                                "returns": T×G df,
                                "nav":     T×G df}]

Run
---
    python v6/scripts/block_composite_v6.py            # persist under
                                                       # data/block_composite_v6/
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

import _common_v6 as C


# ---------------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------------- #
BLOCK_MERGES: dict[str, str] = {"smallcap_cn": "broad_cn"}

# Group -> constituent blocks (post-merge).
# UNTAGGED / any unlisted tag is dropped (never enters a group).
BLOCK_GROUPS: dict[str, tuple[str, ...]] = {
    "equity":      ("broad_cn", "sector_cn",
                    "cross_border_dm", "cross_border_hk"),
    "bond_rates":  ("bond_rates",),
    "bond_credit": ("bond_credit",),
    "commodity":   ("metals", "commodity_other"),
}
GROUP_ORDER: tuple[str, ...] = ("equity", "bond_rates", "bond_credit", "commodity")

SIZINGS: tuple[str, ...] = ("eqw", "invvol")

OUT_ROOT = C.DATA_DIR / "block_composite_v6"


# ---------------------------------------------------------------------- #
# Loader — shared with block_risk_budget_v6
# ---------------------------------------------------------------------- #
def load_shared(data_dir: Path | None = None) -> dict:
    """Membership + fwd_1w + sigma + block_tag (with smallcap merge)."""
    data_dir = Path(data_dir) if data_dir is not None else C.DATA_DIR
    mem = pd.read_parquet(data_dir / "universe_v6" / "membership.parquet")
    codes = list(mem.columns[mem.any(axis=0)])
    mem = mem[codes].astype(bool)
    fwd   = pd.read_parquet(data_dir / "panels_v6" / "fwd_1w.parquet")[codes]
    sigma = pd.read_parquet(data_dir / "panels_v6" / "sigma_causal_26w.parquet")[codes]

    cat = pd.read_csv(data_dir / "universe_v6" / "catalogue_tagged.csv")
    tag = (cat.set_index("code")["current_block"]
              .reindex(codes)
              .fillna("UNTAGGED")
              .replace(BLOCK_MERGES))
    return {"membership": mem, "codes": codes,
            "fwd_1w": fwd, "sigma": sigma, "block_tag": tag}


# ---------------------------------------------------------------------- #
# Weight builder — one group, one sizing
# ---------------------------------------------------------------------- #
def _group_members(tag: pd.Series, blocks: Iterable[str]) -> pd.Index:
    return pd.Index(tag[tag.isin(list(blocks))].index)


def build_group_weights(sigma: pd.DataFrame,
                        mem: pd.DataFrame,
                        tag: pd.Series,
                        group_blocks: Iterable[str],
                        sizing: str) -> pd.DataFrame:
    """Per-bar name-level weights within the group, renormalized to Σ=1.

    Eligibility = MEMBERSHIP AND (σ defined and > 0). For eqw we still
    require σ defined so eqw and invvol books trade on identical name sets
    at each bar; the σ>0 warmup is short (26 weeks) and irrelevant to the
    Phase-12 sample window.
    """
    if sizing not in SIZINGS:
        raise ValueError(f"sizing must be one of {SIZINGS}, got {sizing!r}")
    members = _group_members(tag, group_blocks)
    if len(members) == 0:
        return pd.DataFrame(0.0, index=mem.index, columns=[])

    sig_g = sigma[members]
    mem_g = mem[members]
    eligible = mem_g & sig_g.notna() & (sig_g > 0.0)

    if sizing == "eqw":
        N_t = eligible.sum(axis=1).astype(int)
        W = eligible.astype(float).div(N_t.replace(0, np.nan), axis=0)
    else:  # invvol
        inv = (1.0 / sig_g).where(eligible, 0.0)
        row = inv.sum(axis=1).replace(0.0, np.nan)
        W = inv.div(row, axis=0)
    return W.fillna(0.0)


# ---------------------------------------------------------------------- #
# Composite builder — all groups, one sizing
# ---------------------------------------------------------------------- #
def build_composites(shared: dict,
                     sizings: Iterable[str] = SIZINGS,
                     groups: dict[str, tuple[str, ...]] = BLOCK_GROUPS
                     ) -> dict[str, dict]:
    """For each sizing, build per-group weight panels + weekly returns + NAV.

    Weekly return of group g at bar t: r_{g,t} = Σ_i W_{g,i,t} · fwd_{i,t}.
    NAV_{g,t} = Π_{τ≤t}(1 + r_{g,τ}) with NAV_{g,0} = 1 on the first bar
    where the group has any invested weight.
    """
    fwd   = shared["fwd_1w"]
    sigma = shared["sigma"]
    mem   = shared["membership"]
    tag   = shared["block_tag"]

    out: dict[str, dict] = {}
    for sizing in sizings:
        weights: dict[str, pd.DataFrame] = {}
        rets: dict[str, pd.Series] = {}
        for grp, blocks in groups.items():
            W = build_group_weights(sigma, mem, tag, blocks, sizing)
            # r_g = Σ_i W_i * fwd_i, with fwd NaN treated as 0.
            fwd_g = fwd.reindex(columns=W.columns).fillna(0.0)
            r = (W * fwd_g).sum(axis=1)
            invested = (W.abs().sum(axis=1) > 0.0)
            r = r.where(invested)          # NaN when group flat (no eligible members)
            weights[grp] = W
            rets[grp] = r.rename(grp)

        R = pd.concat([rets[g] for g in groups], axis=1)
        # NAV — carry NaN through when a group is flat that bar; NAV
        # starts at 1 on the first invested bar per group.
        nav = pd.DataFrame(index=R.index, columns=R.columns, dtype=float)
        for g in R.columns:
            r_g = R[g].copy()
            active = r_g.notna()
            r0 = r_g.where(active, 0.0)
            nav[g] = (1.0 + r0).cumprod()
            nav.loc[~active, g] = np.nan
        out[sizing] = {"weights": weights, "returns": R, "nav": nav}
    return out


# ---------------------------------------------------------------------- #
# Persistence — for reuse by block_risk_budget_v6 and diagnostics
# ---------------------------------------------------------------------- #
def _fmt(x, digits=3):
    return f"{x:+.{digits}f}" if pd.notna(x) else "   —"


def persist(composites: dict[str, dict],
            out_root: Path = OUT_ROOT) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    for sizing, bundle in composites.items():
        d = out_root / sizing
        d.mkdir(parents=True, exist_ok=True)
        bundle["returns"].to_parquet(d / "returns.parquet")
        bundle["nav"].to_parquet(d / "nav.parquet")
        for g, W in bundle["weights"].items():
            W.to_parquet(d / f"weights_{g}.parquet")
    print(f"block_composite_v6: wrote {out_root}")


def _print_summary(composites: dict[str, dict], shared: dict) -> None:
    tag = shared["block_tag"]
    print("\ngroup membership (ever-admitted count):")
    for grp, blocks in BLOCK_GROUPS.items():
        n = int(tag.isin(list(blocks)).sum())
        print(f"  {grp:11s} = {'+'.join(blocks):50s} n={n}")

    print("\ncomposite IS metrics (bars ≤ IN_SAMPLE_END):")
    header = f"{'sizing':<7} {'group':<12} {'ann_ret':>8} {'ann_vol':>8} {'sharpe':>8} {'mean_N':>7}"
    print(header)
    print("-" * len(header))
    for sizing, bundle in composites.items():
        R  = bundle["returns"]
        is_R = R.loc[R.index <= C.IN_SAMPLE_END]
        for g in R.columns:
            r = is_R[g].dropna()
            if len(r) < 2:
                print(f"{sizing:<7} {g:<12}      —        —        —       —")
                continue
            av = float(r.std(ddof=1)) * np.sqrt(C.WEEKS_PER_YEAR)
            ar = float(r.mean()) * C.WEEKS_PER_YEAR
            sh = ar / av if av > 0 else np.nan
            W = bundle["weights"][g]
            mn = float((W.loc[W.index <= C.IN_SAMPLE_END] > 0).sum(axis=1).mean())
            print(f"{sizing:<7} {g:<12} {ar*100:>7.2f}% {av*100:>7.2f}% {sh:>+8.3f} {mn:>7.1f}")


# ---------------------------------------------------------------------- #
# Main
# ---------------------------------------------------------------------- #
def main() -> None:
    shared = load_shared()
    print(f"loaded: {len(shared['codes'])} codes, "
          f"{len(shared['fwd_1w'])} bars")

    composites = build_composites(shared)
    persist(composites)
    _print_summary(composites, shared)


if __name__ == "__main__":
    main()
