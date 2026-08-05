"""
v6/scripts/universe_v6.py
=========================
Rule-based, point-in-time universe for the v6 XS-IC pipeline.

Exports (design §2.6):
    MEMBERSHIP : pd.DataFrame  # W-FRI × code, bool — set by build_membership()
    CODES      : list[str]     # union of all names ever admitted
    BLOCK_TAG  : dict[str,str] # code → block  (extends MARKET_TAG taxonomy)
    INDEX_OF   : dict[str,str] # code → underlying_index
    NAME_EN    : dict[str,str]

MEMBERSHIP, CODES, BLOCK_TAG, INDEX_OF, NAME_EN are populated after Phase 2
data pull + Phase 3 build_membership run. Until then the module-level
attributes are ``None``; consumers must call ``build_membership(...)``
themselves or import the persisted parquet.

Rule surface (design §2)
------------------------
1. Seasoning: SEASONING_BARS weekly bars after list_date.
2. Absolute floors (tradability): ADV ≥ ADV_FLOOR_ENTER on entry,
   ADV ≥ ADV_FLOOR_EXIT to stay in (hysteresis). Same for AUM.
3. Relative percentile (adaptivity): among names passing the floor at
   bar t, admit those in the top (1 - ADV_PCTL_ENTER) by trailing-60d
   ADV. To exit the relative test a name must fall below the
   (1 - ADV_PCTL_EXIT) percentile of the pool that day.
4. Index dedup: at each bar, the representative for each underlying_index
   is the incumbent unless a challenger beats it by ≥ INDEX_DEDUP_ADV_MARGIN
   (25%) in trailing-60d ADV.
5. Membership changes take effect at the *next* bar; no intra-bar
   entry/exit.

Values marked "provisional" in comments are frozen at Phase 3 human review
(see IMPLEMENTATION_PLAN.md Phase 3.4).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------- #
# Rule constants — freeze at Phase 3 human review
# ---------------------------------------------------------------------- #
SEASONING_BARS = 26                           # design §2.3, matches Z_MIN_PERIODS

# Absolute floors (RMB) — frozen at Phase 3.4 review (see DESIGN §2.4 addendum).
# Initial provisional values (50m/25m) produced N(2019-12)=18 vs target 40-60.
# Recalibration variant A (chosen 2026-07-17): halves the ADV floors to
# 20m/10m so IS crosses N≥40 by 2020-05-15 (vs baseline 2020-09-25). AUM
# floors unchanged — they were never the binding constraint in 2019.
ADV_FLOOR_ENTER = 20_000_000                  # ¥20m trailing-60d median amount
ADV_FLOOR_EXIT  = 10_000_000                  # 2:1 hysteresis
AUM_FLOOR_ENTER = 200_000_000                 # ¥200m
AUM_FLOOR_EXIT  = 100_000_000                 # 2:1 hysteresis

# Relative percentile cutoffs. ADV_PCTL_ENTER = 0.20 keeps the top 80%.
# ADV_PCTL_EXIT = 0.15 → exit only if you fall below the 15th percentile
# among floor-passers (i.e. keep bottom 85% once you're in).
ADV_PCTL_ENTER  = 0.20
ADV_PCTL_EXIT   = 0.15

# Rolling window for ADV
ADV_WINDOW_DAYS = 60

# Index dedup anti-churn margin — challenger must beat incumbent by 25%+ ADV
INDEX_DEDUP_ADV_MARGIN = 0.25

# Blocks — frozen taxonomy; tag list is a superset of MARKET_TAG in universe_v4
BLOCKS: Tuple[str, ...] = (
    "broad_cn",
    "sector_cn",
    "smallcap_cn",
    "cross_border_dm",
    "cross_border_hk",
    "bond_rates",
    "bond_credit",
    "metals",
    "commodity_other",
)


# ---------------------------------------------------------------------- #
# Module state — populated by build_membership + load_persisted
# ---------------------------------------------------------------------- #
MEMBERSHIP: Optional[pd.DataFrame] = None
CODES:      Optional[List[str]]    = None
BLOCK_TAG:  Optional[Dict[str, str]] = None
INDEX_OF:   Optional[Dict[str, str]] = None
NAME_EN:    Optional[Dict[str, str]] = None


# ---------------------------------------------------------------------- #
# Catalogue schema
# ---------------------------------------------------------------------- #
CATALOGUE_COLUMNS = (
    "code",
    "underlying_index",
    "list_date",
    "delist_date",   # NaT if still listed
    "block",
    "name_en",
)


@dataclass(frozen=True)
class CatalogueEntry:
    code: str
    underlying_index: str
    list_date: pd.Timestamp
    delist_date: Optional[pd.Timestamp]
    block: str
    name_en: str


def validate_catalogue(cat: pd.DataFrame) -> None:
    """Fail loudly on schema drift — every downstream step assumes these
    columns and dtypes exist."""
    missing = set(CATALOGUE_COLUMNS) - set(cat.columns)
    if missing:
        raise ValueError(f"catalogue missing columns: {sorted(missing)}")
    if cat["code"].duplicated().any():
        dup = cat.loc[cat["code"].duplicated(), "code"].tolist()
        raise ValueError(f"catalogue has duplicate codes: {dup}")
    # 'UNTAGGED' is allowed during MEMBERSHIP build (rules don't use block);
    # downstream diagnostics (Phase 8/9) should require full tagging.
    allowed = set(BLOCKS) | {"UNTAGGED"}
    bad_blocks = set(cat["block"]) - allowed
    if bad_blocks:
        raise ValueError(
            f"catalogue has unknown blocks {sorted(bad_blocks)}; "
            f"expected subset of {BLOCKS} (or 'UNTAGGED' pre-Phase 3)"
        )
    # list_date must parse; delist_date may be NaT
    for col in ("list_date", "delist_date"):
        if not np.issubdtype(cat[col].dtype, np.datetime64):
            raise TypeError(f"catalogue.{col} must be datetime64, got {cat[col].dtype}")


# ---------------------------------------------------------------------- #
# Helpers — ADV, seasoning, floors, percentile, hysteresis
# ---------------------------------------------------------------------- #
def _trailing_median_daily(amount_daily: pd.DataFrame,
                           window: int = ADV_WINDOW_DAYS) -> pd.DataFrame:
    """Trailing-window median per code on the daily grid.

    Uses a rolling window with min_periods = window // 2 so a name that has
    only recently listed but has ≥ 30 valid bars still gets an ADV read
    (otherwise the seasoning gate is the *only* thing masking it, and we
    lose the ability to floor-test young names).
    """
    return amount_daily.rolling(window=window, min_periods=window // 2).median()


def _hysteresis_gate(value_daily: pd.DataFrame,
                     enter: float,
                     exit_: float) -> pd.DataFrame:
    """Bar-forward hysteresis: once above ``enter``, stay in until below
    ``exit_``. Returns a bool DataFrame with the same shape."""
    if enter <= exit_:
        raise ValueError(f"enter ({enter}) must be strictly > exit_ ({exit_})")
    in_ = value_daily.ge(enter)                  # entry-strict
    stay = value_daily.ge(exit_)                 # exit-loose

    out = pd.DataFrame(False, index=value_daily.index, columns=value_daily.columns)
    # State machine per column: default False, flip to True on `in_`, back to
    # False when `stay` is False. Vectorized per column via cummax on entry
    # marker within each contiguous stay-run.
    for c in value_daily.columns:
        s_in = in_[c].to_numpy()
        s_stay = stay[c].to_numpy()
        state = False
        col_out = np.zeros(len(s_in), dtype=bool)
        for i in range(len(s_in)):
            if state:
                state = bool(s_stay[i]) and not pd.isna(value_daily[c].iat[i])
            else:
                state = bool(s_in[i])
            col_out[i] = state
        out[c] = col_out
    return out


def _relative_percentile_mask(adv_daily: pd.DataFrame,
                              floor_ok: pd.DataFrame) -> pd.DataFrame:
    """Per-bar percentile gate with hysteresis.

    A name is IN on bar t if it was IN on t-1 and still above the exit
    quantile, OR it is newly above the entry quantile. Both quantiles are
    computed only over names that pass ``floor_ok`` on that bar (so the
    cutoff isn't dragged down by untradeable candidates).
    """
    idx = adv_daily.index
    cols = adv_daily.columns
    out = pd.DataFrame(False, index=idx, columns=cols)

    prev = pd.Series(False, index=cols)
    for t in idx:
        adv_t   = adv_daily.loc[t]
        floor_t = floor_ok.loc[t]
        pool = adv_t[floor_t]
        n_pool = int(pool.notna().sum())
        # need enough eligible names to compute a stable percentile; when
        # the pool is too small, admit everyone who cleared the absolute
        # floor (percentile has no meaning on <5 names)
        if n_pool < 5:
            this = floor_t.astype(bool)
            out.loc[t] = this
            prev = this
            continue
        enter_cut = pool.quantile(ADV_PCTL_ENTER)
        exit_cut  = pool.quantile(ADV_PCTL_EXIT)
        new_in    = adv_t.ge(enter_cut) & floor_t
        stay_in   = prev & adv_t.ge(exit_cut) & floor_t
        this = (new_in | stay_in).astype(bool)
        out.loc[t] = this
        prev = this
    return out


def _representative_by_index(adv_daily: pd.DataFrame,
                             index_of: Dict[str, str],
                             prelim: pd.DataFrame) -> pd.DataFrame:
    """Collapse per-index groups to a single representative per bar.

    For each underlying_index at each bar:
      - restrict to members currently in ``prelim`` (passed seasoning +
        floor + percentile);
      - if no incumbent from the previous bar, pick highest-ADV;
      - if there is an incumbent and it still qualifies, only dethrone if
        some challenger's ADV exceeds incumbent's ADV by ≥
        INDEX_DEDUP_ADV_MARGIN;
      - if the incumbent is no longer in ``prelim``, pick the highest-ADV
        current qualifier.
    """
    idx = adv_daily.index
    cols = adv_daily.columns
    out = pd.DataFrame(False, index=idx, columns=cols)

    # invert: index -> [codes]
    groups: Dict[str, List[str]] = {}
    for code, ix in index_of.items():
        groups.setdefault(ix, []).append(code)

    incumbents: Dict[str, Optional[str]] = {ix: None for ix in groups}

    for t in idx:
        adv_t   = adv_daily.loc[t]
        prelim_t = prelim.loc[t]
        for ix, members in groups.items():
            elig = [c for c in members if bool(prelim_t.get(c, False))
                    and pd.notna(adv_t.get(c, np.nan))]
            if not elig:
                incumbents[ix] = None
                continue
            inc = incumbents[ix]
            if inc is None or inc not in elig:
                # cold start or incumbent lost eligibility -> highest ADV
                rep = max(elig, key=lambda c: float(adv_t[c]))
            else:
                # incumbent still eligible; check for a strong challenger
                inc_adv = float(adv_t[inc])
                cutoff  = inc_adv * (1.0 + INDEX_DEDUP_ADV_MARGIN)
                challengers = [c for c in elig
                               if c != inc and float(adv_t[c]) >= cutoff]
                if challengers:
                    rep = max(challengers, key=lambda c: float(adv_t[c]))
                else:
                    rep = inc
            incumbents[ix] = rep
            out.at[t, rep] = True
    return out


def _seasoning_mask(catalogue: pd.DataFrame,
                    daily_idx: pd.DatetimeIndex,
                    weekly_seasoning_bars: int = SEASONING_BARS
                    ) -> pd.DataFrame:
    """True on/after list_date + weekly_seasoning_bars weeks; also False
    on/after delist_date."""
    cols = catalogue["code"].tolist()
    out = pd.DataFrame(False, index=daily_idx, columns=cols)
    for _, r in catalogue.iterrows():
        earliest = r["list_date"] + pd.Timedelta(weeks=weekly_seasoning_bars)
        m = daily_idx >= earliest
        if pd.notna(r["delist_date"]):
            m = m & (daily_idx < r["delist_date"])
        out[r["code"]] = m
    return out


# ---------------------------------------------------------------------- #
# Main entry point
# ---------------------------------------------------------------------- #
def build_membership(catalogue: pd.DataFrame,
                     px_daily: pd.DataFrame,
                     amount_daily: pd.DataFrame,
                     aum_daily: pd.DataFrame,
                     rebal_idx: pd.DatetimeIndex
                     ) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Point-in-time MEMBERSHIP on the weekly W-FRI grid + audit trail.

    Parameters
    ----------
    catalogue : DataFrame with columns CATALOGUE_COLUMNS
    px_daily, amount_daily, aum_daily : wide DataFrames (date × code),
        daily grid, one column per code in the catalogue. Missing days may
        be NaN.
    rebal_idx : W-FRI weekly index that the panel evaluates on. Membership
        changes are computed on the daily grid but *applied* at the next
        weekly bar (design §2.4).

    Returns
    -------
    membership : DataFrame (rebal_idx × code, bool)
    changes    : DataFrame with columns (date, code, event, trigger_value)
        events ∈ {enter, exit_floor, exit_pctl, exit_delist, repr_switch}
    """
    validate_catalogue(catalogue)
    codes = catalogue["code"].tolist()
    index_of = dict(zip(catalogue["code"], catalogue["underlying_index"]))

    # Align all daily panels to the union index of the price panel + others.
    daily_idx = px_daily.index.union(amount_daily.index).union(aum_daily.index)
    daily_idx = pd.DatetimeIndex(sorted(daily_idx))
    px = px_daily.reindex(daily_idx).reindex(columns=codes)
    amt = amount_daily.reindex(daily_idx).reindex(columns=codes)
    aum = aum_daily.reindex(daily_idx).reindex(columns=codes)

    # ADV proxy: trailing-60d median amount
    adv = _trailing_median_daily(amt, window=ADV_WINDOW_DAYS)
    aum_smooth = _trailing_median_daily(aum, window=ADV_WINDOW_DAYS)

    # Rule 1 — seasoning + delist
    season = _seasoning_mask(catalogue, daily_idx)

    # Rule 2 — absolute floors with 2:1 hysteresis
    adv_floor = _hysteresis_gate(adv, ADV_FLOOR_ENTER, ADV_FLOOR_EXIT)
    aum_floor = _hysteresis_gate(aum_smooth, AUM_FLOOR_ENTER, AUM_FLOOR_EXIT)
    floor_ok = season & adv_floor & aum_floor

    # Rule 3 — relative percentile with hysteresis
    pctl_ok = _relative_percentile_mask(adv, floor_ok)
    prelim = floor_ok & pctl_ok

    # Rule 4 — one representative per underlying_index
    dedup = _representative_by_index(adv, index_of, prelim)

    # Rule 5 — evaluate on weekly grid, use *previous* daily state so a
    # daily entry within week t only appears at the start of week t+1.
    # We take the state as of the last daily bar strictly before each weekly
    # bar's start-of-week to enforce "changes take effect at next bar".
    weekly_state = dedup.reindex(rebal_idx, method="ffill")
    # But: membership is judged at rebal_idx (Fridays). To respect "changes
    # take effect at NEXT bar", shift by 1 weekly bar so week-t membership
    # is week-(t-1)'s daily state.
    weekly_state = weekly_state.astype(bool).shift(1, fill_value=False)
    # Seasoning + delist are hard PIT masks — a delisted ETF has no bar to
    # trade on the "next" Friday, so re-apply the seasoning mask after the
    # shift to force immediate exit on delist_date.
    season_weekly = season.reindex(rebal_idx, method="ffill").fillna(False).astype(bool)
    weekly_state = weekly_state & season_weekly

    # ------------------------------------------------------------------- #
    # Audit trail — rebuild change events from the weekly panel
    # ------------------------------------------------------------------- #
    changes = _emit_changes(weekly_state, adv, aum_smooth, season, adv_floor,
                            aum_floor, pctl_ok, dedup, rebal_idx)
    return weekly_state, changes


def _emit_changes(weekly: pd.DataFrame,
                  adv: pd.DataFrame,
                  aum_smooth: pd.DataFrame,
                  season: pd.DataFrame,
                  adv_floor: pd.DataFrame,
                  aum_floor: pd.DataFrame,
                  pctl_ok: pd.DataFrame,
                  dedup: pd.DataFrame,
                  rebal_idx: pd.DatetimeIndex) -> pd.DataFrame:
    """Emit one row per state change with the rule that most-plausibly fired.

    Priority when a code drops out: exit_delist > exit_floor > exit_pctl >
    repr_switch (loss of representative status).
    """
    rows = []
    weekly_bool = weekly.astype(bool)
    delta = weekly_bool.astype(int).diff().fillna(weekly_bool.iloc[0].astype(int))
    for t in weekly.index:
        for c in weekly.columns:
            d = int(delta.at[t, c])
            if d == 0:
                continue
            # look up the daily state as of the bar-1 daily grid point
            probe = rebal_idx[rebal_idx.get_loc(t) - 1] if rebal_idx.get_loc(t) > 0 else t
            # walk back to the previous daily observation
            probe_daily = adv.index[adv.index <= probe][-1] if len(adv.index[adv.index <= probe]) else t
            adv_v = float(adv.at[probe_daily, c]) if probe_daily in adv.index and c in adv.columns else np.nan
            aum_v = float(aum_smooth.at[probe_daily, c]) if probe_daily in aum_smooth.index and c in aum_smooth.columns else np.nan
            if d > 0:
                rows.append({"date": t, "code": c, "event": "enter",
                             "trigger_value": adv_v})
            else:
                # Attribute exit to the highest-priority failing rule
                if not bool(season.at[probe_daily, c]):
                    event = "exit_delist"; trig = np.nan
                elif not bool(adv_floor.at[probe_daily, c] and aum_floor.at[probe_daily, c]):
                    event = "exit_floor"
                    trig = min(adv_v if np.isfinite(adv_v) else np.inf,
                               aum_v if np.isfinite(aum_v) else np.inf)
                elif not bool(pctl_ok.at[probe_daily, c]):
                    event = "exit_pctl"; trig = adv_v
                else:
                    event = "repr_switch"; trig = adv_v
                rows.append({"date": t, "code": c, "event": event,
                             "trigger_value": trig})
    return pd.DataFrame(rows, columns=["date", "code", "event", "trigger_value"])


# ---------------------------------------------------------------------- #
# Persistence — Phase 3 writes these, downstream reads via load_persisted()
# ---------------------------------------------------------------------- #
def load_persisted(data_dir) -> Tuple[pd.DataFrame, List[str], Dict[str, str],
                                     Dict[str, str], Dict[str, str]]:
    """Load MEMBERSHIP + catalogue-derived dicts from disk (Phase 3 output)."""
    from pathlib import Path
    p = Path(data_dir)
    membership = pd.read_parquet(p / "membership.parquet")
    cat = pd.read_csv(p / "catalogue.csv", parse_dates=["list_date", "delist_date"])
    codes = list(membership.columns[membership.any(axis=0)])
    block_tag = dict(zip(cat["code"], cat["block"]))
    index_of  = dict(zip(cat["code"], cat["underlying_index"]))
    name_en   = dict(zip(cat["code"], cat["name_en"]))
    return membership, codes, block_tag, index_of, name_en


def install_module_state(data_dir) -> None:
    """Populate module-level MEMBERSHIP / CODES / BLOCK_TAG / INDEX_OF / NAME_EN
    from persisted artifacts. Called by consumers that expect these globals
    (mirror of universe_v4's import-time attributes)."""
    global MEMBERSHIP, CODES, BLOCK_TAG, INDEX_OF, NAME_EN
    MEMBERSHIP, CODES, BLOCK_TAG, INDEX_OF, NAME_EN = load_persisted(data_dir)


# ---------------------------------------------------------------------- #
# Phase 3 driver — reads Phase 2 parquets, builds MEMBERSHIP, persists
# ---------------------------------------------------------------------- #
def _pivot_long(long_df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """Long (date, code, value_col) → wide date × code, sorted."""
    wide = long_df.pivot(index="date", columns="code", values=value_col)
    return wide.sort_index()


def run_phase3(data_dir, out_dir=None):
    """Phase 3.1 + 3.2 driver.

    Reads catalogue.csv + px_daily.parquet + aum_daily.parquet from
    ``data_dir``, builds MEMBERSHIP on the W-FRI grid spanning the loaded
    price range, and writes membership.parquet + membership_changes.csv to
    ``out_dir`` (defaults to ``data_dir``).
    """
    from pathlib import Path
    import time
    src = Path(data_dir)
    out = Path(out_dir) if out_dir else src

    cat = pd.read_csv(src / "catalogue.csv",
                      parse_dates=["list_date", "delist_date"])
    px_long  = pd.read_parquet(src / "px_daily.parquet")
    aum_long = pd.read_parquet(src / "aum_daily.parquet")

    # Restrict to codes that actually returned data — a code in the catalogue
    # with no px rows was either delisted before FETCH_START or has list_date
    # in the future. Either way it can never be a member, so drop it and
    # save the state-machine loops the cycles.
    px_codes = set(px_long["code"].unique())
    n_before = len(cat)
    cat = cat[cat["code"].isin(px_codes)].reset_index(drop=True)
    print(f"[phase3] catalogue: {n_before} → {len(cat)} codes (dropped "
          f"{n_before - len(cat)} with no px data)")

    t0 = time.time()
    close = _pivot_long(px_long,  "close")
    amt   = _pivot_long(px_long,  "amount")
    aum   = _pivot_long(aum_long, "aum")
    # Align columns to catalogue order — build_membership reindexes anyway,
    # but this makes the assertion below trivial.
    codes = cat["code"].tolist()
    close = close.reindex(columns=codes)
    amt   = amt.reindex(columns=codes)
    aum   = aum.reindex(columns=codes)
    print(f"[phase3] pivot: {time.time()-t0:.1f}s, shape={close.shape}")

    rebal = pd.date_range(close.index.min(), close.index.max(), freq="W-FRI")
    print(f"[phase3] rebal_idx: {len(rebal)} W-FRI bars "
          f"{rebal.min().date()} → {rebal.max().date()}")

    t0 = time.time()
    membership, changes = build_membership(cat, close, amt, aum, rebal)
    print(f"[phase3] build_membership: {time.time()-t0:.1f}s, "
          f"membership={membership.shape}, changes={len(changes)}")

    mem_path = out / "membership.parquet"
    chg_path = out / "membership_changes.csv"
    membership.to_parquet(mem_path)
    changes.to_csv(chg_path, index=False)
    print(f"[phase3] wrote {mem_path}")
    print(f"[phase3] wrote {chg_path}")

    # Compact N(t) preview so the caller sees calibration signal immediately.
    nt = membership.sum(axis=1)
    print(f"[phase3] N(t) min/median/max = {nt.min()} / {int(nt.median())} / {nt.max()}")
    for date in ("2019-12-31", "2021-12-31", "2023-12-31", "2024-12-31"):
        ts = pd.Timestamp(date)
        # closest weekly bar ≤ date
        prior = membership.index[membership.index <= ts]
        if len(prior):
            print(f"[phase3]   N({prior[-1].date()}) = {int(nt.loc[prior[-1]])}")
    return membership, changes


def main():
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(description="Phase 3 MEMBERSHIP builder")
    default_data = Path(__file__).resolve().parents[1] / "data" / "universe_v6"
    ap.add_argument("--data-dir", default=str(default_data),
                    help=f"input+output dir (default: {default_data})")
    args = ap.parse_args()
    run_phase3(args.data_dir)


if __name__ == "__main__":
    main()
