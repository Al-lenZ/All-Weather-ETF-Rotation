"""
v6/scripts/exp2_representative_sets_v6.py
=========================================
Experiment 2 — Compress the 6 non-α blocks into per-cluster representatives.

Motivation
----------
Non-α blocks (bond_rates, bond_credit, cross_border_dm, cross_border_hk,
metals, commodity_other) are held equal / inv-vol on all members. As the
block universe grows, executing on every name gets impractical. Goal:
mirror the hold-all invvol composite with the smallest possible name set.

Method (per user spec 2026-07-27, revised after v1 review)
----------------------------------------------------------
1. **Cluster** on past weekly returns (52–104w rolling correlation, averaged
   into a distance matrix D = √(2·(1 − ρ̄))). Complete-linkage; K clusters
   cut via ``scipy.cluster.hierarchy.cut_tree`` — guarantees exactly K
   partitions when N ≥ K (``fcluster`` with maxclust silently collapses
   tied-height merges into fewer clusters; verified failure on metals K=2,
   cbHK K=2 in v1).
2. **K is an output, not an input**: at each refresh date, per block,
   sweep K = 1..N causally on the trailing training window and pick the
   smallest K whose replicated-vs-holdall residual satisfies

       ann_std(r_rep − r_hold) / ann_std(r_hold) ≤ RESID_VOL_RATIO_MAX

   (default 0.20, equivalent to explained-variance ≥ 96%). Adaptive per
   (year, block), so tiny blocks trivially resolve to K = N, and blocks
   growing over time increase K automatically at the next refresh.
3. **Pick representative** per cluster by top ADV (63d rolling mean of
   daily amount). NO predictive metrics.
4. **Weight** representatives = the invvol mass of their whole cluster.
5. **Hysteresis** = annual refresh at first W-FRI of each calendar year,
   using only data strictly prior; adaptive K per refresh.
6. **TE + turnover attribution** — per-block TE at chosen K on IS + pre-
   stress OOS; book-level turnover split into refresh-week rep-swap spike
   vs non-refresh-week σ-drift baseline.
7. **Book impact** — swap non-α sub-block builders with representative-only
   versions inside the frozen finalist (q=0.20, ε=0.30), rerun the
   Phase 12×13 two-layer book, report Sharpe/CAGR/DD delta.

Windows
-------
IS  = bars ≤ 2023-12-31.
OOS = 2024-01-01 → 2025-07-31 (pre-stress OOS, v6 stress hold-out sealed).
The threshold rule is applied causally in both windows; the *only* IS-fit
choice is the residual-vol threshold itself (design constant, not a tuned
parameter).

Outputs
-------
    data/exp2_representative_sets_v6/
        clusters_yearly.csv          — per year, per block, cluster labels
        reps_yearly.csv              — per year, per block, cluster → rep code
        te_by_k.csv                  — per-block, per-K, IS/OOS TE + Sharpe
        te_by_year.csv               — chosen K per block, per year TE
        book_impact.csv              — book Sharpe/CAGR/DD delta vs hold-all
    reports/exp2_representative_sets_v6_report.md

Run
---
    python v6/scripts/exp2_representative_sets_v6.py
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import cut_tree, linkage
from scipy.spatial.distance import squareform

# --- v6/common sys.path bootstrap ---
import sys as _v6_sys
from pathlib import Path as _V6Path
_v6_p = _V6Path(__file__).resolve().parent
while _v6_p.name != "v6" and _v6_p.parent != _v6_p:
    _v6_p = _v6_p.parent
_v6_sys.path.insert(0, str(_v6_p / "common"))
del _v6_p
# --------------------------------------
import _common_v6 as C
import xs_engine_v6 as E
import block_composite_v6 as BC
import block_risk_budget_v6 as BR
import block_two_layer_v6 as TL


# ---------------------------------------------------------------------- #
# Config
# ---------------------------------------------------------------------- #
NON_ALPHA_BLOCKS: tuple[str, ...] = (
    "bond_rates", "bond_credit",
    "cross_border_dm", "cross_border_hk",
    "metals", "commodity_other",
)

K_GRID:      tuple[int, ...]   = (2, 3, 4, 5, 6)
CORR_WINDOWS_W: tuple[int, ...] = (52, 78, 104)   # rolling weekly windows
CORR_MIN_OBS = 26                                # min weekly obs per window
ADV_WIN_D    = 63                                # trading days rolling mean
TRAIN_WIN_W  = 104                                # training window for K selection
MIN_CLUSTER_YEARS = 1                            # minimum year in-sample per block

# K-selection threshold — smallest K with ann_std(residual)/ann_std(hold-all)
# ≤ RESID_VOL_RATIO_MAX passes. 0.20 ↔ explained-variance ≥ 96%. This is
# a design constant, not a tuned parameter (choose once by economic
# rationale, then hold it fixed).
RESID_VOL_RATIO_MAX = 0.20

# Cost/finalist (matches Phase 12×13 frozen spec, cf. block_two_layer_v6)
Q_FIN, EPS_FIN = 0.20, 0.30

OUT_ROOT = C.DATA_DIR / "exp2_representative_sets_v6"
REPORT_PATH = C.DATA_DIR.parent / "reports" / "exp2_representative_sets_v6_report.md"


# ---------------------------------------------------------------------- #
# Warmup-trim helpers (convention per block_two_layer_oos_shot_v6)
# ---------------------------------------------------------------------- #
def _first_live_bar(net_ret: pd.Series) -> pd.Timestamp:
    """First bar where |net_ret| > 0 — end of the book's own warmup."""
    nz = (net_ret.abs() > 0.0)
    if not bool(nz.any()):
        return net_ret.index[0]
    return net_ret.index[int(nz.values.argmax())]


def _window_metrics(net: pd.Series) -> dict:
    n = int(len(net))
    if n < 2:
        return {"n_bars": n, "sharpe": np.nan, "cagr": np.nan,
                "max_dd": np.nan, "ann_vol": np.nan}
    ann_vol = float(net.std(ddof=1)) * np.sqrt(C.WEEKS_PER_YEAR)
    ann_ret = float(net.mean()) * C.WEEKS_PER_YEAR
    sharpe  = (ann_ret / ann_vol) if ann_vol > 0 else np.nan
    cumret  = float(net.sum())
    n_yrs   = max(n / C.WEEKS_PER_YEAR, 1e-3)
    cagr    = max(1.0 + cumret, 1e-9) ** (1.0 / n_yrs) - 1.0
    nav     = 1.0 + net.cumsum()
    max_dd  = float(((nav - nav.cummax()) / nav.cummax()).min())
    return {"n_bars": n, "sharpe": sharpe, "cagr": cagr, "max_dd": max_dd,
            "ann_vol": ann_vol}


def _trimmed_book_metrics(net_ret: pd.Series,
                          start: pd.Timestamp) -> dict:
    """IS on [start, IN_SAMPLE_END], OOS on [OOS_START, OOS_END]."""
    idx = net_ret.index
    is_slice  = net_ret[(idx >= start) & (idx <= C.IN_SAMPLE_END)]
    oos_slice = net_ret[(idx >= C.OOS_START) & (idx <= C.OOS_END)]
    is_m  = _window_metrics(is_slice)
    oos_m = _window_metrics(oos_slice)
    return {
        "is_sharpe":   is_m["sharpe"],
        "oos_sharpe":  oos_m["sharpe"],
        "is_cagr":     is_m["cagr"],
        "oos_cagr":    oos_m["cagr"],
        "is_max_dd":   is_m["max_dd"],
        "oos_max_dd":  oos_m["max_dd"],
        "is_ann_vol":  is_m["ann_vol"],
        "oos_ann_vol": oos_m["ann_vol"],
        "is_bars":     is_m["n_bars"],
        "oos_bars":    oos_m["n_bars"],
    }


# ---------------------------------------------------------------------- #
# ADV panel — weekly-sampled 63d rolling mean of daily amount
# ---------------------------------------------------------------------- #
def build_adv_weekly(px_daily: pd.DataFrame,
                     fwd_index: pd.DatetimeIndex) -> pd.DataFrame:
    """T×N W-FRI panel of ADV = rolling-63d mean of daily amount (RMB).

    Any missing daily row is left NaN — the .rolling().mean() natively
    handles gaps (min_periods reduced so early bars still get a number).
    """
    amt = (px_daily.pivot(index="date", columns="code", values="amount")
                    .sort_index())
    amt = amt.rolling(ADV_WIN_D, min_periods=max(5, ADV_WIN_D // 3)).mean()
    # Reindex to W-FRI grid via forward-fill of last known daily value.
    # W-FRI dates are the same physical Fridays as fwd_1w's index.
    amt = amt.reindex(fwd_index, method="ffill")
    return amt


# ---------------------------------------------------------------------- #
# Past weekly returns (for correlation clustering)
# ---------------------------------------------------------------------- #
def build_past_weekly(fwd_1w: pd.DataFrame) -> pd.DataFrame:
    """Past 1w return at bar t = fwd_1w at bar t-1 (the return realized
    between t-1 and t). We shift the whole fwd panel by one to get a
    causal past-return series aligned to the same W-FRI grid.
    """
    return fwd_1w.shift(1)


# ---------------------------------------------------------------------- #
# Clustering — per block, at one refresh date
# ---------------------------------------------------------------------- #
def _rolling_avg_corr(R_block: pd.DataFrame,
                      windows: tuple[int, ...] = CORR_WINDOWS_W,
                      min_obs: int = CORR_MIN_OBS) -> pd.DataFrame:
    """Average of pairwise correlations across multiple rolling-window
    snapshots ending at R_block.index[-1]. Each window computes one
    correlation matrix; the final matrix is the elementwise average over
    windows that actually have enough obs.
    """
    codes = list(R_block.columns)
    if len(codes) < 2:
        return pd.DataFrame(index=codes, columns=codes, dtype=float)
    mats: list[np.ndarray] = []
    T = len(R_block)
    for w in windows:
        if T < min_obs:
            continue
        take = R_block.iloc[max(0, T - w):]
        # need at least min_obs obs and at least 2 non-null columns
        if len(take) < min_obs:
            continue
        # pairwise-complete correlation (drops NaN pairwise)
        c = take.corr(method="pearson", min_periods=min_obs)
        if c.isna().values.all():
            continue
        mats.append(c.reindex(index=codes, columns=codes).to_numpy(dtype=float))
    if not mats:
        return pd.DataFrame(np.nan, index=codes, columns=codes, dtype=float)
    stack = np.stack(mats, axis=0)
    with np.errstate(invalid="ignore"):
        avg = np.nanmean(stack, axis=0)
    # ensure diag = 1 (correlation of a series with itself)
    np.fill_diagonal(avg, 1.0)
    return pd.DataFrame(avg, index=codes, columns=codes)


def _distance_from_corr(C_mat: pd.DataFrame) -> np.ndarray:
    """d_ij = √(2(1 − ρ̄_ij)); NaN entries filled with max distance = √2
    so those pairs never cluster except as a last resort."""
    R = C_mat.to_numpy(dtype=float).copy()
    R = np.clip(R, -1.0, 1.0)
    D = np.sqrt(np.maximum(0.0, 2.0 * (1.0 - R)))
    np.fill_diagonal(D, 0.0)
    # symmetrize + fill NaN with the theoretical max
    D = (D + D.T) / 2.0
    D[~np.isfinite(D)] = np.sqrt(2.0)
    return D


def _linkage_from_returns(R_block: pd.DataFrame,
                          windows: tuple[int, ...] = CORR_WINDOWS_W,
                          ) -> tuple[np.ndarray | None, pd.DataFrame]:
    """Correlation-distance complete-linkage tree Z on R_block; returns
    (Z, corr matrix). Z is None if fewer than 2 usable codes."""
    codes = list(R_block.columns)
    if len(codes) < 2:
        return None, pd.DataFrame()
    C_mat = _rolling_avg_corr(R_block, windows=windows)
    D = _distance_from_corr(C_mat)
    cond = squareform(D, checks=False)
    Z = linkage(cond, method="complete")
    return Z, C_mat


def cluster_block(R_block: pd.DataFrame, K: int,
                  windows: tuple[int, ...] = CORR_WINDOWS_W,
                  ) -> tuple[list[int], pd.DataFrame, dict]:
    """Complete-linkage into exactly K clusters on the multi-window average
    correlation.

    Uses ``scipy.cluster.hierarchy.cut_tree`` for exact-K partitioning —
    ``fcluster(criterion='maxclust')`` silently collapses tied merge
    heights into fewer clusters (bug caught 2026-07-27 on cbHK K=2
    returning a single 22-item cluster, and metals K=2 returning a single
    3-item cluster). cut_tree walks the tree from top, guaranteed to yield
    exactly K partitions when N ≥ K.
    """
    codes = list(R_block.columns)
    N = len(codes)
    if N == 0:
        return [], pd.DataFrame(), {"n": 0, "K_eff": 0,
                                     "avg_intra_corr": float("nan")}
    if N <= K:
        return list(range(1, N + 1)), pd.DataFrame(), {
            "n": N, "K_eff": N, "avg_intra_corr": float("nan"),
        }

    Z, C_mat = _linkage_from_returns(R_block, windows=windows)
    labels = cut_tree(Z, n_clusters=K).flatten() + 1
    labels = [int(x) for x in labels]
    return labels, C_mat, {
        "n": N, "K_eff": int(len(set(labels))),
        "avg_intra_corr": float(_avg_intra_corr(C_mat, labels)),
    }


def _avg_intra_corr(C_mat: pd.DataFrame, labels: list[int]) -> float:
    if C_mat.empty:
        return float("nan")
    R = C_mat.to_numpy(dtype=float)
    labs = np.array(labels)
    tot, cnt = 0.0, 0
    for k in np.unique(labs):
        idx = np.where(labs == k)[0]
        if len(idx) < 2:
            continue
        sub = R[np.ix_(idx, idx)]
        # off-diagonal mean
        mask = ~np.eye(len(idx), dtype=bool)
        vals = sub[mask]
        vals = vals[np.isfinite(vals)]
        if len(vals) == 0:
            continue
        tot += float(vals.mean())
        cnt += 1
    return tot / cnt if cnt > 0 else float("nan")


def pick_representative(codes: list[str],
                        labels: list[int],
                        adv: pd.Series) -> dict[int, str]:
    """Per cluster, pick the code with the highest ADV. Ties → alphabetical."""
    df = pd.DataFrame({"code": codes, "label": labels, "adv": adv.reindex(codes).values})
    df["adv"] = df["adv"].fillna(0.0)
    reps: dict[int, str] = {}
    for k, g in df.groupby("label"):
        g_sorted = g.sort_values(["adv", "code"], ascending=[False, True])
        reps[int(k)] = str(g_sorted.iloc[0]["code"])
    return reps


# ---------------------------------------------------------------------- #
# Threshold K selection — K becomes an output
# ---------------------------------------------------------------------- #
def _train_holdall_block_return(shared: dict, keep: list[str],
                                train_index: pd.DatetimeIndex,
                                past_1w: pd.DataFrame) -> tuple[pd.DataFrame,
                                                                 pd.Series]:
    """Per-week hold-all invvol weight panel + hold-all block return series
    on ``train_index`` restricted to the ``keep`` codes. Uses the causal σ
    panel and MEMBERSHIP so the training-window r_hold matches the exact
    production series over that period."""
    sig = shared["sigma"][keep].reindex(train_index)
    mem = shared["membership"][keep].reindex(train_index)
    eligible = mem & sig.notna() & (sig > 0.0)
    inv_sig = (1.0 / sig).where(eligible, 0.0)
    denom = inv_sig.sum(axis=1).replace(0.0, np.nan)
    W_hold = inv_sig.div(denom, axis=0).fillna(0.0)
    past = past_1w[keep].reindex(train_index).fillna(0.0)
    r_hold = (W_hold * past).sum(axis=1)
    return W_hold, r_hold


def _train_replicated_block_return(W_hold: pd.DataFrame,
                                   labels: list[int],
                                   reps: dict[int, str],
                                   keep: list[str],
                                   past_1w: pd.DataFrame,
                                   train_index: pd.DatetimeIndex,
                                   shared: dict) -> pd.Series:
    """Given cluster labels + reps + hold-all invvol weights on the training
    window, compute the replicated block return series. Ineligible-rep
    bars drop that cluster's mass (implicit cash inside the block, same
    convention as the production replicated composite)."""
    W_rep = pd.DataFrame(0.0, index=W_hold.index, columns=W_hold.columns)
    code_to_lab = dict(zip(keep, labels))
    sig = shared["sigma"][keep].reindex(train_index)
    mem = shared["membership"][keep].reindex(train_index)
    eligible = mem & sig.notna() & (sig > 0.0)
    for c in keep:
        lab = code_to_lab.get(c)
        if lab is None:
            continue
        rep = reps.get(int(lab))
        if rep is None or rep not in W_rep.columns:
            continue
        W_rep[rep] = W_rep[rep] + W_hold[c].where(eligible[rep], 0.0)
    past = past_1w[keep].reindex(train_index).fillna(0.0)
    return (W_rep * past).sum(axis=1)


def select_K_by_residual_vol(shared: dict, block: str,
                             past_1w: pd.DataFrame,
                             adv_snap: pd.Series,
                             refresh_date: pd.Timestamp,
                             threshold: float = RESID_VOL_RATIO_MAX,
                             train_win_w: int = TRAIN_WIN_W,
                             ) -> dict | None:
    """Causally choose K at ``refresh_date`` for ``block``.

    Sweep K = 1..N on the trailing ``train_win_w`` weekly bars strictly
    before refresh_date. Pick the smallest K such that

        ann_std(r_rep − r_hold) / ann_std(r_hold) ≤ threshold

    If no K meets the bar (only happens when the block is genuinely
    irreducible), fall back to K = N — i.e., hold-all.

    Returns a dict with:
        K, labels, reps, keep, K_max, residual_ratio_by_K,
        block_vol_ann, avg_intra_corr, notes
    or None if the block has < 2 eligible names / no linkage tree.
    """
    tag = shared["block_tag"]
    codes_b = [c for c in shared["codes"] if tag.get(c) == block]
    if not codes_b:
        return None
    past_slice = past_1w.loc[past_1w.index < refresh_date, codes_b]
    if past_slice.empty:
        return None
    obs = past_slice.notna().sum(axis=0)
    keep = list(obs.index[obs >= CORR_MIN_OBS])
    N = len(keep)
    if N < 2:
        return None
    past_b = past_slice[keep]

    Z, C_mat = _linkage_from_returns(past_b)
    if Z is None:
        return None

    # Training window for the residual criterion — last train_win_w bars
    # ending strictly before refresh_date, restricted to the same keep set.
    T = len(past_b)
    tw = min(train_win_w, T)
    train_index = past_b.index[-tw:]
    W_hold_train, r_hold_train = _train_holdall_block_return(
        shared, keep, train_index, past_1w,
    )
    block_std = float(r_hold_train.std(ddof=1))
    if block_std <= 0 or not np.isfinite(block_std):
        return None
    block_vol_ann = block_std * np.sqrt(C.WEEKS_PER_YEAR)

    residual_ratio_by_K: dict[int, dict] = {}
    K_chosen: int | None = None
    K_labels: list[int] = []
    K_reps: dict[int, str] = {}
    K_C_mat = C_mat
    for K in range(1, N + 1):
        labels = cut_tree(Z, n_clusters=K).flatten() + 1
        labels = [int(x) for x in labels]
        reps = pick_representative(keep, labels, adv_snap)
        r_rep_train = _train_replicated_block_return(
            W_hold_train, labels, reps, keep, past_1w, train_index, shared,
        )
        resid = (r_rep_train - r_hold_train).dropna()
        if len(resid) < 4:
            residual_ratio_by_K[K] = {"ratio": float("nan"),
                                       "resid_vol_ann": float("nan")}
            continue
        r_std = float(resid.std(ddof=1))
        ratio = r_std / block_std if block_std > 0 else float("inf")
        residual_ratio_by_K[K] = {
            "ratio":         float(ratio),
            "resid_vol_ann": float(r_std * np.sqrt(C.WEEKS_PER_YEAR)),
        }
        if K_chosen is None and ratio <= threshold:
            K_chosen = K
            K_labels = labels
            K_reps = reps

    if K_chosen is None:
        # Threshold never met — fall back to hold-all (K = N). By
        # construction the residual is 0, so this is safe; means the
        # block is genuinely irreducible under the chosen threshold.
        K_chosen = N
        K_labels = cut_tree(Z, n_clusters=N).flatten() + 1
        K_labels = [int(x) for x in K_labels]
        K_reps = pick_representative(keep, K_labels, adv_snap)

    return {
        "K":                     K_chosen,
        "N":                     N,
        "labels":                K_labels,
        "reps":                  K_reps,
        "keep":                  keep,
        "residual_ratio_by_K":   residual_ratio_by_K,
        "block_vol_ann":         float(block_vol_ann),
        "avg_intra_corr":        float(_avg_intra_corr(K_C_mat, K_labels)),
        "notes":                 "fallback_hold_all"
                                 if residual_ratio_by_K
                                 and residual_ratio_by_K[K_chosen]["ratio"] > threshold
                                 else "threshold_met",
    }


# ---------------------------------------------------------------------- #
# Annual refresh — build (year → block → labels + reps)
# ---------------------------------------------------------------------- #
def _refresh_dates(index: pd.DatetimeIndex,
                   start_year: int,
                   end_year: int) -> dict[int, pd.Timestamp]:
    """Nearest W-FRI at or after Jan-1 of each calendar year in
    [start_year, end_year]. First-year fallback = first available bar in
    the panel (so we always have a labelling for year_1)."""
    out: dict[int, pd.Timestamp] = {}
    for y in range(start_year, end_year + 1):
        target = pd.Timestamp(y, 1, 1)
        after = index[index >= target]
        if len(after) == 0:
            continue
        out[y] = after[0]
    # earliest year may need to start at panel start
    if start_year not in out and len(index) > 0:
        out[start_year] = index[0]
    return out


def build_annual_refresh(shared: dict,
                         adv_w: pd.DataFrame,
                         past_1w: pd.DataFrame,
                         blocks: tuple[str, ...] = NON_ALPHA_BLOCKS,
                         Ks: dict[str, int] | None = None,
                         K_default: int = 4,
                         use_threshold: bool = False,
                         threshold: float = RESID_VOL_RATIO_MAX,
                         ) -> tuple[pd.DataFrame, pd.DataFrame,
                                    dict[tuple[int, str], dict]]:
    """For each calendar year, for each block, build the cluster labelling
    from past returns available *strictly before* the year's refresh date,
    and pick reps by ADV averaged over the trailing ADV_WIN_D days ending
    on that date.

    Two modes:
      * ``use_threshold=False`` — fixed K per block from ``Ks``. Missing
        blocks fall back to ``K_default``. Reserved for the diagnostic
        K sweep only.
      * ``use_threshold=True`` — K is an OUTPUT: at each refresh, sweep
        K = 1..N causally on the trailing training window and pick the
        smallest K with ann_std(residual) / ann_std(hold-all) ≤ threshold.

    Returns
    -------
    clusters_df : long-format rows (year, block, code, label, K_chosen)
    reps_df     : long-format rows (year, block, label, rep_code)
    diag        : dict keyed by (year, block) → {'n', 'K', 'residual_ratio',
                     'block_vol_ann', 'avg_intra_corr', 'notes'} for
                     threshold mode, or {'n', 'K_eff', 'avg_intra_corr'}
                     for fixed-K mode.
    """
    if Ks is None:
        Ks = {}
    idx = past_1w.index
    tag = shared["block_tag"]

    y_start, y_end = idx[0].year, C.OOS_END.year
    refresh = _refresh_dates(idx, y_start, y_end)

    clusters_rows: list[dict] = []
    reps_rows: list[dict]     = []
    diag: dict[tuple[int, str], dict] = {}

    for y in sorted(refresh):
        t_refresh = refresh[y]
        adv_at = adv_w.loc[adv_w.index < t_refresh]
        adv_snap = (adv_at.tail(1).iloc[0]
                    if len(adv_at) > 0 else pd.Series(dtype=float))

        if use_threshold:
            for b in blocks:
                out = select_K_by_residual_vol(
                    shared, b, past_1w, adv_snap, t_refresh,
                    threshold=threshold,
                )
                if out is None:
                    continue
                K_used = out["K"]
                keep   = out["keep"]
                labels = out["labels"]
                reps   = out["reps"]
                ratio_at_K = out["residual_ratio_by_K"].get(K_used, {}).get("ratio")
                resid_vol_at_K = out["residual_ratio_by_K"].get(K_used, {}).get(
                    "resid_vol_ann"
                )
                diag[(y, b)] = {
                    "n":                out["N"],
                    "K":                K_used,
                    "residual_ratio":   ratio_at_K,
                    "resid_vol_ann":    resid_vol_at_K,
                    "block_vol_ann":    out["block_vol_ann"],
                    "avg_intra_corr":   out["avg_intra_corr"],
                    "notes":            out["notes"],
                }
                for c, lab in zip(keep, labels):
                    clusters_rows.append({
                        "year": y, "block": b, "code": c, "label": lab,
                        "K_chosen": K_used,
                    })
                for lab, r in reps.items():
                    reps_rows.append({
                        "year": y, "block": b, "label": lab, "rep_code": r,
                    })
        else:
            # fixed-K mode (diagnostic)
            past_slice = past_1w.loc[past_1w.index < t_refresh]
            for b in blocks:
                codes_b = [c for c in shared["codes"] if tag.get(c) == b]
                past_b = past_slice.reindex(columns=codes_b)
                obs = past_b.notna().sum(axis=0)
                keep = list(obs.index[obs >= CORR_MIN_OBS])
                if len(keep) < 2:
                    continue
                past_b = past_b[keep]
                K = Ks.get(b, K_default)
                labels, C_mat, dg = cluster_block(past_b, K=K)
                diag[(y, b)] = dg
                reps = pick_representative(keep, labels, adv_snap)
                for c, lab in zip(keep, labels):
                    clusters_rows.append({
                        "year": y, "block": b, "code": c, "label": lab,
                        "K_chosen": K,
                    })
                for lab, r in reps.items():
                    reps_rows.append({
                        "year": y, "block": b, "label": lab, "rep_code": r,
                    })
    clusters_df = pd.DataFrame(clusters_rows)
    reps_df     = pd.DataFrame(reps_rows)
    return clusters_df, reps_df, diag


# ---------------------------------------------------------------------- #
# Replicated invvol composite (with annual-refresh membership)
# ---------------------------------------------------------------------- #
def build_replicated_block(shared: dict,
                           block: str,
                           clusters_df: pd.DataFrame,
                           reps_df: pd.DataFrame,
                           ) -> pd.DataFrame:
    """Weight panel for the replicated block (representatives inheriting
    cluster invvol mass). Σ_block-per-bar ≤ 1; equals 1 if all reps
    eligible that bar and the cluster covers all block-eligible members
    at t. Any weight tied to an ineligible rep just drops (implicit cash).
    """
    tag = shared["block_tag"]
    mem = shared["membership"]
    sig = shared["sigma"]
    codes_b = [c for c in shared["codes"] if tag.get(c) == block]
    if not codes_b:
        return pd.DataFrame(0.0, index=mem.index, columns=[])
    sig_b = sig[codes_b]
    mem_b = mem[codes_b]

    # Precompute hold-all invvol weights (per bar) inside the block:
    # W_hold[t, i] = 1/σ_i(t) · eligible / Σ_j 1/σ_j(t) · eligible
    eligible = mem_b & sig_b.notna() & (sig_b > 0)
    inv_sig = (1.0 / sig_b).where(eligible, 0.0)
    denom = inv_sig.sum(axis=1).replace(0.0, np.nan)
    W_hold = inv_sig.div(denom, axis=0).fillna(0.0)

    # Empty replicated weight panel with same shape as hold-all
    W_rep = pd.DataFrame(0.0, index=W_hold.index, columns=W_hold.columns)

    if reps_df.empty or clusters_df.empty:
        return W_rep
    clusters_b = clusters_df[clusters_df["block"] == block]
    reps_b     = reps_df[reps_df["block"] == block]
    if clusters_b.empty or reps_b.empty:
        return W_rep

    # Refresh years present for this block, sorted.
    years_available = sorted({int(y) for y in clusters_b["year"].unique()})
    if not years_available:
        return W_rep

    # Per-year: {code → label} and {label → rep_code}
    year_to_cl: dict[int, dict[str, int]] = {
        y: dict(zip(g["code"].astype(str),
                     g["label"].astype(int)))
        for y, g in clusters_b.groupby("year")
    }
    year_to_rep: dict[int, dict[int, str]] = {
        y: dict(zip(g["label"].astype(int),
                     g["rep_code"].astype(str)))
        for y, g in reps_b.groupby("year")
    }

    # For each bar's calendar year, choose the latest refresh year ≤ y
    # (as-of lookup — first-year bars fall back to years_available[0]).
    ya = np.array(years_available, dtype=int)
    idx_years = W_hold.index.year.astype(int)
    y_use_arr = np.array([
        int(ya[ya <= y].max()) if (ya <= y).any() else int(ya[0])
        for y in idx_years
    ])

    W_hold_np = W_hold.to_numpy()
    codes_arr = np.array(W_hold.columns, dtype=object)
    col_pos = {c: i for i, c in enumerate(codes_arr)}
    W_rep_np = np.zeros_like(W_hold_np)
    eligible_np = eligible.to_numpy()

    # Per-bar collapse hold-all invvol mass into representative slots.
    for i, y_use in enumerate(y_use_arr):
        cl = year_to_cl.get(int(y_use))
        rp = year_to_rep.get(int(y_use))
        if not cl or not rp:
            continue
        row_w = W_hold_np[i]
        if row_w.sum() == 0.0:
            continue
        acc: dict[int, float] = {}
        for c, lab in cl.items():
            pos = col_pos.get(c)
            if pos is None:
                continue
            w = row_w[pos]
            if w == 0.0:
                continue
            acc[lab] = acc.get(lab, 0.0) + float(w)
        for lab, mass in acc.items():
            rep_code = rp.get(int(lab))
            if rep_code is None:
                continue
            pos = col_pos.get(rep_code)
            if pos is None:
                continue
            if eligible_np[i, pos]:
                W_rep_np[i, pos] += mass

    return pd.DataFrame(W_rep_np, index=W_hold.index, columns=W_hold.columns)


# ---------------------------------------------------------------------- #
# TE evaluation — per block, per K, IS/OOS
# ---------------------------------------------------------------------- #
def block_return(W_block: pd.DataFrame,
                 fwd_1w: pd.DataFrame) -> pd.Series:
    F = fwd_1w.reindex(columns=W_block.columns).fillna(0.0)
    return (W_block * F).sum(axis=1)


def ann_te(diff: pd.Series) -> float:
    """Annualized weekly tracking error, std × sqrt(52)."""
    d = diff.dropna()
    if len(d) < 4:
        return float("nan")
    return float(d.std(ddof=1)) * np.sqrt(C.WEEKS_PER_YEAR)


def _window_slice(s: pd.Series, kind: str) -> pd.Series:
    idx = s.index
    if kind == "is":
        return s[idx <= C.IN_SAMPLE_END]
    if kind == "oos":
        return s[(idx >= C.OOS_START) & (idx <= C.OOS_END)]
    if kind == "full":
        return s[idx <= C.OOS_END]
    raise ValueError(kind)


def evaluate_te(shared: dict, adv_w: pd.DataFrame, past_1w: pd.DataFrame,
                block: str, K: int) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """Build the K-cluster annual-refresh replicated block, compute
    r_rep - r_hold weekly, return IS/OOS TE + Sharpe deltas."""
    Ks = {block: K}
    clusters_df, reps_df, diag = build_annual_refresh(
        shared, adv_w, past_1w, blocks=(block,), Ks=Ks,
    )
    W_rep  = build_replicated_block(shared, block, clusters_df, reps_df)
    # hold-all invvol composite
    W_hold = BC.build_group_weights(
        shared["sigma"], shared["membership"], shared["block_tag"],
        (block,), "invvol",
    )
    fwd = shared["fwd_1w"]
    r_hold = block_return(W_hold, fwd).rename("hold")
    r_rep  = block_return(W_rep,  fwd).rename("rep")
    diff   = (r_rep - r_hold).rename("diff")

    # Only bars where the block is invested at all
    active = (W_hold.abs().sum(axis=1) > 0.0)
    diff   = diff.where(active)
    r_hold = r_hold.where(active)
    r_rep  = r_rep.where(active)

    out = {"block": block, "K": K,
           "N_avg":  float(clusters_df[clusters_df.block == block]
                           .groupby("year").size().mean()) if not clusters_df.empty else np.nan,
           "K_eff_avg":  float(reps_df[reps_df.block == block]
                               .groupby("year").size().mean()) if not reps_df.empty else np.nan,
           "avg_intra_corr":  float(pd.Series(
               [d["avg_intra_corr"] for (_y, b), d in diag.items() if b == block]
           ).mean())}
    for kind in ("is", "oos", "full"):
        d = _window_slice(diff, kind)
        h = _window_slice(r_hold, kind)
        rp = _window_slice(r_rep, kind)
        out[f"te_{kind}"] = ann_te(d)
        out[f"n_bars_{kind}"] = int(d.notna().sum())
        out[f"mean_ret_diff_bp_{kind}"] = float(d.mean() * 10000) if len(d.dropna()) > 0 else np.nan
        out[f"sharpe_hold_{kind}"]  = _sharpe(h)
        out[f"sharpe_rep_{kind}"]   = _sharpe(rp)
        out[f"dd_hold_{kind}"]      = _max_dd(h)
        out[f"dd_rep_{kind}"]       = _max_dd(rp)
    return out, clusters_df, reps_df


def _sharpe(s: pd.Series) -> float:
    s = s.dropna()
    if len(s) < 2 or s.std(ddof=1) == 0:
        return float("nan")
    return float(s.mean() / s.std(ddof=1)) * float(np.sqrt(C.WEEKS_PER_YEAR))


def _max_dd(s: pd.Series) -> float:
    s = s.dropna()
    if len(s) < 2:
        return float("nan")
    nav = 1.0 + s.cumsum()
    cummax = nav.cummax()
    return float(((nav - cummax) / cummax).min())


# ---------------------------------------------------------------------- #
# Book impact — swap replicated composites into the two-layer book
# ---------------------------------------------------------------------- #
def build_composites_replicated(shared: dict,
                                q: float, epsilon: float,
                                alpha_scores: dict[str, pd.DataFrame],
                                reps_yearly: dict[str, tuple[pd.DataFrame, pd.DataFrame]],
                                ) -> dict:
    """Same as ``block_two_layer_v6.build_composites_two_layer`` but for
    the 6 non-α blocks it substitutes the *replicated* invvol composite
    (representatives inherit cluster invvol mass). α blocks unchanged.

    reps_yearly : block → (clusters_df, reps_df).
    """
    N_counts = TL._static_member_counts(shared)
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
            if b in TL.ALPHA_BLOCKS and q < 1.0:
                W_sub = TL.build_alpha_subblock(
                    shared, b, alpha_scores[b], q, epsilon,
                    sizing=TL.ALPHA_SIZING,
                )
            elif b in reps_yearly:
                cdf, rdf = reps_yearly[b]
                W_sub = build_replicated_block(shared, b, cdf, rdf)
            else:
                W_sub = TL.build_holdall_subblock(
                    shared, b,
                    sizing=(TL.ALPHA_SIZING if b in TL.ALPHA_BLOCKS
                                             else TL.NONALPHA_SIZING),
                )
            share = N_b / N_g if N_g > 0 else 0.0
            W_scaled = W_sub * share
            pb[b] = W_scaled
            frames.append(W_scaled)
        per_block[grp] = pb
        concat_group[grp] = (pd.concat(frames, axis=1)
                             if frames else pd.DataFrame(index=shared["fwd_1w"].index))

    fwd = shared["fwd_1w"]
    rets = {}
    for grp, W_g in concat_group.items():
        if W_g.shape[1] == 0:
            rets[grp] = pd.Series(np.nan, index=fwd.index, name=grp)
            continue
        fwd_g = fwd.reindex(columns=W_g.columns).fillna(0.0)
        r_g = (W_g * fwd_g).sum(axis=1)
        invested = (W_g.abs().sum(axis=1) > 0.0)
        rets[grp] = r_g.where(invested).rename(grp)
    R = pd.concat([rets[g] for g in BC.GROUP_ORDER], axis=1)
    return {"returns": R, "weights_group": concat_group, "weights_per_block": per_block}


def run_book_with_reps(shared: dict, alpha_scores: dict[str, pd.DataFrame],
                       reps_yearly: dict[str, tuple[pd.DataFrame, pd.DataFrame]],
                       q: float = Q_FIN, epsilon: float = EPS_FIN
                       ) -> tuple[E.BookSummary, E.BookResult]:
    comp = build_composites_replicated(shared, q, epsilon, alpha_scores,
                                       reps_yearly)
    R    = comp["returns"][list(BC.GROUP_ORDER)]
    trend = pd.DataFrame(True, index=R.index, columns=R.columns)
    W_group, RC_pct, diag = BR.build_block_weights(
        R, trend, TL.BUDGET_METHOD, BR.POLICY_SHARES,
    )
    frames = []
    for grp in BC.GROUP_ORDER:
        Wg = comp["weights_group"][grp]
        if Wg.shape[1] == 0:
            continue
        scale = W_group[grp].reindex(Wg.index).fillna(0.0)
        frames.append(Wg.mul(scale, axis=0))
    W_name = pd.concat(frames, axis=1) if frames else pd.DataFrame(index=R.index)
    fwd = shared["fwd_1w"].reindex(columns=W_name.columns).fillna(0.0)
    K_t = (W_name.abs() > 0).sum(axis=1).astype(int).rename("K_t")
    res = E.run_book(W_name, fwd, cost_per_trade=TL.COST,
                     N_t=K_t.rename("N_t"), K_t=K_t)
    return E.summarize_book(res), res


# ---------------------------------------------------------------------- #
# Turnover attribution — refresh-week spike vs σ-drift baseline
# ---------------------------------------------------------------------- #
def refresh_week_dates(index: pd.DatetimeIndex,
                       y_start: int, y_end: int) -> list[pd.Timestamp]:
    """First W-FRI at or after Jan-1 of each calendar year in [y_start, y_end]."""
    out: list[pd.Timestamp] = []
    for y in range(y_start, y_end + 1):
        target = pd.Timestamp(y, 1, 1)
        after = index[index >= target]
        if len(after) == 0:
            continue
        out.append(after[0])
    return out


def attribute_turnover(res: E.BookResult,
                       refresh_dates: list[pd.Timestamp]) -> dict:
    """Split the book-level per-week turnover into a refresh-week component
    (rep-swap spike + σ drift) vs a non-refresh-week component (σ drift
    only). Also report the top-5 spike weeks and the extra cost drag
    attributable to refresh-week rep swaps.

    Note: refresh-week turnover mixes two effects — the rep-set change
    (jump) AND the ongoing σ drift that would have happened anyway. The
    "clean" rep-swap cost is upper-bounded by (refresh_avg − non_refresh_avg);
    we report both the raw refresh average and this difference.
    """
    turn = res.turnover
    mask_refresh = turn.index.isin(refresh_dates)
    refresh_turn = turn[mask_refresh]
    other_turn   = turn[~mask_refresh]

    top5 = turn.nlargest(5)
    out = {
        "n_refresh_weeks":  int(refresh_turn.notna().sum()),
        "n_other_weeks":    int(other_turn.notna().sum()),
        "avg_turnover":     float(turn.mean()),
        "refresh_avg":      float(refresh_turn.mean()),
        "other_avg":        float(other_turn.mean()),
        "refresh_max":      float(refresh_turn.max()) if len(refresh_turn) else float("nan"),
        "other_max":        float(other_turn.max()) if len(other_turn) else float("nan"),
        "top5_dates":       [str(t.date()) for t in top5.index],
        "top5_values":      [float(v) for v in top5.values],
        "excess_refresh":   float(refresh_turn.mean() - other_turn.mean())
                             if len(other_turn) else float("nan"),
    }
    # Attribute annual cost drag from the refresh-week excess:
    # refresh weeks per year × excess × cost_per_side × 2 (buy+sell).
    n_refresh_per_year = len(refresh_dates) / max(
        1, (res.turnover.index[-1] - res.turnover.index[0]).days / 365.25
    )
    out["refresh_cost_drag_bp_yr"] = float(
        out["excess_refresh"] * TL.COST * 2.0 * n_refresh_per_year * 10000.0
    )
    return out


# ---------------------------------------------------------------------- #
# Report
# ---------------------------------------------------------------------- #
def _fmt(x, d=3): return f"{x:+.{d}f}" if pd.notna(x) else "   —"
def _fmt_pct(x, d=2): return f"{x*100:+.{d}f}%" if pd.notna(x) else "     —"
def _fmt_bp(x, d=1): return f"{x*10000:+.{d}f} bp" if pd.notna(x) else "     —"


def write_report(te_by_k: pd.DataFrame,
                 te_by_year: pd.DataFrame,
                 K_by_year: pd.DataFrame,
                 book_impact_trim: dict[str, dict],
                 book_impact_summ: dict[str, E.BookSummary],
                 clusters_df: pd.DataFrame,
                 reps_df: pd.DataFrame,
                 turn_att: dict[str, dict],
                 refresh_dates: list[pd.Timestamp],
                 first_live: pd.Timestamp,
                 report_path: Path) -> None:
    ht = book_impact_trim.get("hold_all", {})
    is_bars = int(ht.get("is_bars", 0))
    oos_bars = int(ht.get("oos_bars", 0))
    lines: list[str] = []
    lines.append("# Experiment 2 — Non-α block representative sets (adaptive K)\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n\n")
    lines.append(
        f"Blocks in scope: {', '.join(NON_ALPHA_BLOCKS)}.  \n"
        f"Clustering: rolling {{{', '.join(str(w) for w in CORR_WINDOWS_W)}}}w "
        "correlation, averaged, complete-linkage (cut via ``cut_tree`` — "
        "``fcluster(maxclust)`` collapses tied merges into fewer clusters, "
        "verified failure on metals/cbHK in v1).  \n"
        f"K per (year, block) is an **output**: smallest K with "
        "ann_std(replicated − hold-all) / ann_std(hold-all) ≤ "
        f"{RESID_VOL_RATIO_MAX:.2f} on the trailing {TRAIN_WIN_W}w training "
        "window (equivalent to explained-variance ≥ "
        f"{100.0*(1 - RESID_VOL_RATIO_MAX**2):.0f} %).  \n"
        f"Representative per cluster = top ADV ({ADV_WIN_D}d trailing mean of "
        "daily amount). No predictive metrics.  \n"
        "Annual refresh at first W-FRI of each calendar year using data "
        "strictly prior.  \n\n"
        "**Warmup handling** — book-level Sharpe / CAGR / DD denominators "
        "exclude the pre-live warmup period. Effective IS window = "
        f"**[{first_live.date()}, {C.IN_SAMPLE_END.date()}]** "
        f"({is_bars} weekly bars). Warmup end = first bar where either book "
        "has a non-zero net return (Phase 12 layer-1 has a 52-week cov "
        "window). Both hold-all and replicated books share the same "
        "layer-1 solver and land on this same first-live bar. OOS window "
        f"= [{C.OOS_START.date()}, {C.OOS_END.date()}] ({oos_bars} bars), "
        "unaffected by warmup. v6 stress hold-out (> 2025-07-31) sealed. "
        "Per-block TE, annual-K table, and per-year TE (§1, §2) already "
        "use the ``active`` mask (block-flat bars dropped), so those "
        "numbers are unaffected by the change.  \n\n"
    )

    # -------------------------------------------------------------
    # §1. Adaptive K per (year, block)
    # -------------------------------------------------------------
    lines.append("## 1. Adaptive K per (year, block) — K as output\n")
    lines.append(
        "For each refresh year, per block, K is the smallest cluster count "
        "meeting the residual-vol threshold on the trailing training window. "
        "'ratio' = ann_std(residual) / ann_std(hold-all). 'fallback_hold_all' "
        "= threshold not achievable at any K ≤ N (block genuinely irreducible "
        "— all N names get held).\n\n"
    )
    if K_by_year.empty:
        lines.append("no adaptive rows.\n\n")
    else:
        yrs = sorted(K_by_year["year"].unique())
        # per-block, per-year: show K
        lines.append("### 1a. K by (year, block)\n")
        hdr = "| block | " + " | ".join(str(y) for y in yrs) + " |"
        sep = "|:---|" + "---:|" * len(yrs)
        lines.append(hdr); lines.append(sep)
        for b in NON_ALPHA_BLOCKS:
            row = [f"{b}"]
            for y in yrs:
                sub = K_by_year[(K_by_year["year"] == y) &
                                (K_by_year["block"] == b)]
                if sub.empty:
                    row.append("—")
                else:
                    r = sub.iloc[0]
                    tag = f"{int(r['K'])}/{int(r['n'])}"
                    if r["notes"] == "fallback_hold_all":
                        tag = tag + "*"
                    row.append(tag)
            lines.append("| " + " | ".join(row) + " |")
        lines.append("\n(Cells show K / N. * = fallback: threshold not met, K = N.)\n\n")

        # per-block, per-year: show residual ratio
        lines.append("### 1b. Residual-vol ratio at chosen K\n")
        hdr = "| block | " + " | ".join(str(y) for y in yrs) + " |"
        sep = "|:---|" + "---:|" * len(yrs)
        lines.append(hdr); lines.append(sep)
        for b in NON_ALPHA_BLOCKS:
            row = [f"{b}"]
            for y in yrs:
                sub = K_by_year[(K_by_year["year"] == y) &
                                (K_by_year["block"] == b)]
                if sub.empty:
                    row.append("—")
                else:
                    row.append(f"{float(sub.iloc[0]['residual_ratio']):.3f}")
            lines.append("| " + " | ".join(row) + " |")
        lines.append(
            f"\n(Threshold = {RESID_VOL_RATIO_MAX:.2f}; smaller is tighter fit.)\n\n"
        )

    # -------------------------------------------------------------
    # §2. Per-year TE at adaptive K
    # -------------------------------------------------------------
    lines.append("## 2. Per-year annualized TE (bp/yr) at adaptive K\n")
    if te_by_year.empty:
        lines.append("no per-year rows.\n\n")
    else:
        yrs = sorted(te_by_year["year"].unique())
        hdr = "| block | " + " | ".join(str(y) for y in yrs) + " |"
        sep = "|:---|" + "---:|" * len(yrs)
        lines.append(hdr); lines.append(sep)
        for b in NON_ALPHA_BLOCKS:
            sub = te_by_year[te_by_year["block"] == b]
            if sub.empty:
                continue
            cells_ = []
            for y in yrs:
                r = sub[sub["year"] == y]
                if r.empty:
                    cells_.append(" — ")
                else:
                    cells_.append(f" {float(r.te.iloc[0])*10000:.1f} ")
            lines.append(f"| {b} | " + "|".join(cells_) + " |")
        lines.append("\n(All in bp/yr; blank = block flat that year.)\n\n")

    # -------------------------------------------------------------
    # §3. Cluster snapshot (final refresh year)
    # -------------------------------------------------------------
    lines.append("## 3. Cluster snapshot — most recent refresh year per block\n")
    lines.append(
        "K clusters at the most recent refresh year in-sample (final refresh "
        "applied through the OOS window). 'rep' = top-ADV in the trailing "
        f"{ADV_WIN_D}d ending at that year's refresh date.\n\n"
    )
    for b in NON_ALPHA_BLOCKS:
        cb = clusters_df[clusters_df["block"] == b]
        if cb.empty:
            continue
        last_y = int(cb["year"].max())
        sub_c = cb[cb["year"] == last_y]
        sub_r = reps_df[(reps_df["block"] == b) & (reps_df["year"] == last_y)]
        rep_map = {int(r.label): str(r.rep_code) for r in sub_r.itertuples(index=False)}
        K_this_year = int(sub_c["K_chosen"].iloc[0]) if "K_chosen" in sub_c.columns else len(sub_c["label"].unique())
        lines.append(f"### {b}  (K = {K_this_year}, year {last_y})\n")
        for lab in sorted(sub_c["label"].unique()):
            members = sub_c[sub_c["label"] == lab]["code"].tolist()
            rep = rep_map.get(int(lab), "—")
            rep_marker = " (★ rep)"
            members_fmt = ", ".join(
                (f"{c}{rep_marker}" if c == rep else c) for c in members
            )
            lines.append(f"- **cluster {lab}** ({len(members)}): {members_fmt}")
        lines.append("")

    # -------------------------------------------------------------
    # §4. Book-level impact
    # -------------------------------------------------------------
    lines.append("## 4. Book-level impact — Phase 12×13 finalist\n")
    lines.append(
        f"Layer-2 α (broad_cn, sector_cn) unchanged at finalist "
        f"(q={Q_FIN}, ε={EPS_FIN}). Non-α blocks swapped for the "
        "adaptive-K annual-refresh replicated composite. Layer-1 solver, "
        "sizing, cost = frozen.\n\n"
    )
    hdr = ("| variant | IS Sh | OOS Sh | IS CAGR | OOS CAGR | IS DD | OOS DD "
           "| IS ann vol | turnover | mean K names |")
    sep = "|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    lines.append(hdr); lines.append(sep)
    for label in ("hold_all", "replicated"):
        t = book_impact_trim.get(label)
        s = book_impact_summ.get(label)
        if t is None or s is None:
            lines.append(f"| {label} | — | — | — | — | — | — | — | — | — |")
            continue
        lines.append(
            f"| {label} | {_fmt(t['is_sharpe'])} | {_fmt(t['oos_sharpe'])} | "
            f"{_fmt_pct(t['is_cagr'])} | {_fmt_pct(t['oos_cagr'])} | "
            f"{_fmt_pct(t['is_max_dd'])} | {_fmt_pct(t['oos_max_dd'])} | "
            f"{_fmt_pct(t['is_ann_vol'])} | {s.avg_turnover:.4f} | {s.mean_K:.1f} |"
        )
    ht = book_impact_trim.get("hold_all")
    rt = book_impact_trim.get("replicated")
    hs = book_impact_summ.get("hold_all")
    rs = book_impact_summ.get("replicated")
    if ht and rt and hs and rs:
        lines.append(
            f"\n**Δ (replicated − hold-all)**: IS Sharpe {rt['is_sharpe'] - ht['is_sharpe']:+.3f}, "
            f"OOS Sharpe {rt['oos_sharpe'] - ht['oos_sharpe']:+.3f}, "
            f"IS CAGR {(rt['is_cagr'] - ht['is_cagr'])*100:+.2f} pp, "
            f"OOS CAGR {(rt['oos_cagr'] - ht['oos_cagr'])*100:+.2f} pp, "
            f"IS DD {(rt['is_max_dd'] - ht['is_max_dd'])*100:+.2f} pp, "
            f"OOS DD {(rt['oos_max_dd'] - ht['oos_max_dd'])*100:+.2f} pp.  \n"
            f"Mean K names {hs.mean_K:.1f} → {rs.mean_K:.1f} "
            f"({(rs.mean_K - hs.mean_K)/hs.mean_K*100:+.1f} %).  \n"
        )

    # -------------------------------------------------------------
    # §5. Turnover attribution — refresh-week spike vs σ-drift baseline
    # -------------------------------------------------------------
    lines.append("\n## 5. Turnover attribution — refresh-week spikes\n")
    lines.append(
        "Weekly turnover (Σ_i |ΔW_i| per bar) split into: **refresh weeks** "
        "(first W-FRI of each calendar year — rep-swap + σ drift) vs **other "
        "weeks** (σ drift only). 'Excess' = refresh_avg − other_avg, an "
        "upper bound on the rep-swap component. 'Refresh cost drag' converts "
        f"excess turnover into ann bp/yr at {TL.COST*10000:.0f} bp/side.\n\n"
    )
    lines.append("| variant | refresh avg | other avg | excess | "
                 "refresh max | other max | refresh cost drag bp/yr |")
    lines.append("|:---|---:|---:|---:|---:|---:|---:|")
    for label in ("hold_all", "replicated"):
        d = turn_att.get(label)
        if d is None:
            continue
        lines.append(
            f"| {label} | {d['refresh_avg']:.4f} | {d['other_avg']:.4f} | "
            f"{d['excess_refresh']:+.4f} | "
            f"{d['refresh_max']:.4f} | {d['other_max']:.4f} | "
            f"{d['refresh_cost_drag_bp_yr']:+.1f} |"
        )
    d_rep = turn_att.get("replicated")
    if d_rep is not None:
        lines.append("\n### Top 5 turnover weeks — replicated book\n")
        lines.append("| date | weekly turnover | refresh week? |")
        lines.append("|:---|---:|:---:|")
        refresh_set = set(pd.Timestamp(t) for t in refresh_dates)
        for dt, v in zip(d_rep["top5_dates"], d_rep["top5_values"]):
            marker = "★" if pd.Timestamp(dt) in refresh_set else ""
            lines.append(f"| {dt} | {v:.4f} | {marker} |")
        lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {report_path}")


# ---------------------------------------------------------------------- #
# Main
# ---------------------------------------------------------------------- #
def main() -> None:
    print("--- exp2 non-α block representative sets (adaptive K) ---")
    shared = BC.load_shared()
    fwd = shared["fwd_1w"]

    # ADV panel
    px_daily = pd.read_parquet(
        C.DATA_DIR / "universe_v6" / "px_daily.parquet"
    )
    adv_w = build_adv_weekly(px_daily, fwd.index)
    past_1w = build_past_weekly(fwd)

    # -------------------------------------------------------------
    # (a) Adaptive K per (year, block) via residual-vol threshold —
    # HEADLINE PATH. K is an output.
    # -------------------------------------------------------------
    print(f"\n[adaptive K] threshold: resid_vol / block_vol ≤ {RESID_VOL_RATIO_MAX:.2f}")
    clusters_adaptive, reps_adaptive, diag_adaptive = build_annual_refresh(
        shared, adv_w, past_1w,
        blocks=NON_ALPHA_BLOCKS, use_threshold=True,
        threshold=RESID_VOL_RATIO_MAX,
    )
    adaptive_summary_rows: list[dict] = []
    for (y, b), d in sorted(diag_adaptive.items()):
        adaptive_summary_rows.append({
            "year": y, "block": b, **d,
        })
        print(f"  {y} {b:18s} N={d['n']:2d} K={d['K']:2d} "
              f"resid_ratio={d['residual_ratio']:.3f} "
              f"resid_vol={d['resid_vol_ann']*10000:.1f}bp/yr "
              f"block_vol={d['block_vol_ann']*100:.2f}% "
              f"intra_ρ={d['avg_intra_corr']:+.3f}  {d['notes']}")
    K_by_year = pd.DataFrame(adaptive_summary_rows)

    reps_yearly_adaptive: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for b in NON_ALPHA_BLOCKS:
        cb = clusters_adaptive[clusters_adaptive["block"] == b]
        rb = reps_adaptive[reps_adaptive["block"] == b]
        if not cb.empty:
            reps_yearly_adaptive[b] = (cb, rb)

    # per-year TE at adaptive K
    per_year_rows: list[dict] = []
    for b in NON_ALPHA_BLOCKS:
        if b not in reps_yearly_adaptive:
            continue
        cb, rb = reps_yearly_adaptive[b]
        W_rep = build_replicated_block(shared, b, cb, rb)
        W_hold = BC.build_group_weights(
            shared["sigma"], shared["membership"], shared["block_tag"],
            (b,), "invvol",
        )
        diff = (block_return(W_rep, fwd) - block_return(W_hold, fwd))
        active = (W_hold.abs().sum(axis=1) > 0.0)
        diff = diff.where(active)
        for y, g in diff.groupby(diff.index.year):
            K_year = int(diag_adaptive.get((int(y), b), {}).get("K", -1))
            per_year_rows.append({
                "block": b, "K": K_year, "year": int(y),
                "te": ann_te(g), "n": int(g.notna().sum()),
            })
    te_by_year = pd.DataFrame(per_year_rows)

    # -------------------------------------------------------------
    # (b) Fixed-K sweep (DIAGNOSTIC) — kept so K sweep table still
    # renders, but no longer drives the chosen K per block.
    # -------------------------------------------------------------
    print("\n[K sweep — diagnostic] per block, K = 2..6 (fixed-K path)")
    te_rows: list[dict] = []
    per_block_reps_by_K: dict[tuple[str, int], tuple[pd.DataFrame, pd.DataFrame]] = {}
    for b in NON_ALPHA_BLOCKS:
        print(f"  block {b}")
        for K in K_GRID:
            out, cdf, rdf = evaluate_te(shared, adv_w, past_1w, b, K)
            print(f"    K={K}  N_avg={out['N_avg']:.1f}  intra_ρ={out['avg_intra_corr']:+.3f}  "
                  f"TE IS={out['te_is']*10000:.1f}bp  TE OOS={out['te_oos']*10000:.1f}bp")
            te_rows.append(out)
            per_block_reps_by_K[(b, K)] = (cdf, rdf)
    te_by_k = pd.DataFrame(te_rows)

    # -------------------------------------------------------------
    # (c) Book impact — hold-all vs adaptive-K replicated. Warmup-trim
    # the IS / OOS metrics to the common first-live bar so denominators
    # don't include the pre-live all-zero warmup weeks.
    # -------------------------------------------------------------
    print("\n[book impact] hold-all vs adaptive-K replicated (finalist q, ε)")
    alpha_scores = TL.build_alpha_scores(shared)
    hold_summ, hold_res = _run_holdall(shared, alpha_scores)
    rep_summ,  rep_res  = run_book_with_reps(
        shared, alpha_scores, reps_yearly_adaptive,
        q=Q_FIN, epsilon=EPS_FIN,
    )

    first_live = max(
        _first_live_bar(hold_res.net_ret),
        _first_live_bar(rep_res.net_ret),
    )
    print(f"  first-live bar (common, warmup end): {first_live.date()}")
    hold_trim = _trimmed_book_metrics(hold_res.net_ret, first_live)
    rep_trim  = _trimmed_book_metrics(rep_res.net_ret,  first_live)
    print(f"  hold_all:   IS Sh {hold_trim['is_sharpe']:+.3f}  OOS Sh {hold_trim['oos_sharpe']:+.3f}"
          f"  IS DD {hold_trim['is_max_dd']*100:+.2f}%  OOS DD {hold_trim['oos_max_dd']*100:+.2f}%"
          f"  turn {hold_summ.avg_turnover:.4f}  mean K names {hold_summ.mean_K:.1f}"
          f"  IS bars {hold_trim['is_bars']}")
    print(f"  replicated: IS Sh {rep_trim['is_sharpe']:+.3f}  OOS Sh {rep_trim['oos_sharpe']:+.3f}"
          f"  IS DD {rep_trim['is_max_dd']*100:+.2f}%  OOS DD {rep_trim['oos_max_dd']*100:+.2f}%"
          f"  turn {rep_summ.avg_turnover:.4f}  mean K names {rep_summ.mean_K:.1f}"
          f"  IS bars {rep_trim['is_bars']}")

    # -------------------------------------------------------------
    # (d) Turnover attribution — refresh-week spike vs σ-drift baseline
    # -------------------------------------------------------------
    idx = fwd.index
    y_start = idx[0].year
    y_end   = C.OOS_END.year
    refresh_dates = refresh_week_dates(idx, y_start, y_end)
    turn_att_hold = attribute_turnover(hold_res, refresh_dates)
    turn_att_rep  = attribute_turnover(rep_res,  refresh_dates)
    print(f"\n[turnover attribution]")
    print(f"  hold_all   refresh_avg={turn_att_hold['refresh_avg']:.4f}  "
          f"other_avg={turn_att_hold['other_avg']:.4f}  "
          f"excess={turn_att_hold['excess_refresh']:+.4f}  "
          f"refresh cost drag {turn_att_hold['refresh_cost_drag_bp_yr']:+.1f} bp/yr")
    print(f"  replicated refresh_avg={turn_att_rep['refresh_avg']:.4f}  "
          f"other_avg={turn_att_rep['other_avg']:.4f}  "
          f"excess={turn_att_rep['excess_refresh']:+.4f}  "
          f"refresh cost drag {turn_att_rep['refresh_cost_drag_bp_yr']:+.1f} bp/yr")
    print("  top-5 replicated turnover weeks:")
    for d, v in zip(turn_att_rep["top5_dates"], turn_att_rep["top5_values"]):
        marker = " ★" if pd.Timestamp(d) in refresh_dates else ""
        print(f"    {d}  {v:.4f}{marker}")

    # -------------------------------------------------------------
    # Persist + report
    # -------------------------------------------------------------
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    te_by_k.to_csv(OUT_ROOT / "te_by_k.csv", index=False)
    te_by_year.to_csv(OUT_ROOT / "te_by_year.csv", index=False)
    K_by_year.to_csv(OUT_ROOT / "K_by_year.csv", index=False)
    clusters_adaptive.to_csv(OUT_ROOT / "clusters_yearly.csv", index=False)
    reps_adaptive.to_csv(OUT_ROOT / "reps_yearly.csv", index=False)
    pd.DataFrame([{
        "variant": "hold_all",
        "is_sharpe": hold_trim["is_sharpe"],
        "oos_sharpe": hold_trim["oos_sharpe"],
        "is_cagr":    hold_trim["is_cagr"],
        "oos_cagr":   hold_trim["oos_cagr"],
        "is_max_dd":  hold_trim["is_max_dd"],
        "oos_max_dd": hold_trim["oos_max_dd"],
        "is_ann_vol": hold_trim["is_ann_vol"],
        "is_bars":    hold_trim["is_bars"],
        "oos_bars":   hold_trim["oos_bars"],
        "avg_turnover": hold_summ.avg_turnover,
        "mean_K":     hold_summ.mean_K,
    }, {
        "variant": "replicated_adaptive",
        "is_sharpe": rep_trim["is_sharpe"],
        "oos_sharpe": rep_trim["oos_sharpe"],
        "is_cagr":    rep_trim["is_cagr"],
        "oos_cagr":   rep_trim["oos_cagr"],
        "is_max_dd":  rep_trim["is_max_dd"],
        "oos_max_dd": rep_trim["oos_max_dd"],
        "is_ann_vol": rep_trim["is_ann_vol"],
        "is_bars":    rep_trim["is_bars"],
        "oos_bars":   rep_trim["oos_bars"],
        "avg_turnover": rep_summ.avg_turnover,
        "mean_K":     rep_summ.mean_K,
    }]).to_csv(OUT_ROOT / "book_impact.csv", index=False)
    pd.DataFrame([turn_att_hold | {"variant": "hold_all"},
                  turn_att_rep  | {"variant": "replicated_adaptive"}]
                 ).to_csv(OUT_ROOT / "turnover_attribution.csv", index=False)

    write_report(
        te_by_k=te_by_k, te_by_year=te_by_year,
        K_by_year=K_by_year,
        book_impact_trim={"hold_all": hold_trim, "replicated": rep_trim},
        book_impact_summ={"hold_all": hold_summ, "replicated": rep_summ},
        clusters_df=clusters_adaptive, reps_df=reps_adaptive,
        turn_att={"hold_all": turn_att_hold, "replicated": turn_att_rep},
        refresh_dates=refresh_dates,
        first_live=first_live,
        report_path=REPORT_PATH,
    )


def _run_holdall(shared: dict,
                 alpha_scores: dict[str, pd.DataFrame]
                 ) -> tuple[E.BookSummary, E.BookResult]:
    """Frozen finalist with all non-α blocks held-all invvol (baseline).
    Duplicates ``block_two_layer_v6.run_variant`` at (Q_FIN, EPS_FIN) but
    returns the BookResult in addition to the summary so turnover can be
    attributed."""
    bundle = TL.run_variant(shared, q=Q_FIN, epsilon=EPS_FIN,
                            alpha_scores=alpha_scores)
    return bundle["summary_net"], bundle["res_net"]


if __name__ == "__main__":
    main()
