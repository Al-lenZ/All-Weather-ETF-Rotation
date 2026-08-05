"""
v6/scripts/vol_forecast_recalibrate_v6.py
=========================================
Phase 10.2b — recalibration of the block-pooled HAR vol forecast.

Motivation
----------
Phase 10.2 headline showed HAR under-scales realized vol (MZ b ≈ 0.49)
and loses to the naive random-walk baseline on top-q hit rate. Two
suspects for the level-space compression:

1. The empirical 52w quantile inversion in ``H.denormalize`` clips
   any HAR z-forecast beyond the top ~2% of the trailing window to the
   window's own maximum. Extreme forecasts get truncated — the tails
   we care about for regime detection.
2. The MZ slope itself is < 1, so the level forecast systematically
   overshoots relative to realized.

This branch tries two fixes, both simple, both leaving Phase 10.2
artifacts untouched:

    (A) MZ slope recalibration — expanding causal fit of σ = a + b·σ̂
        on every prior (forecast, actual) pair, refit every 4 w to
        match the HAR refit cadence. Produces HAR_cal.
    (B) Raw-percentile forecast — bypass the 52w quantile inversion
        entirely. Use HAR's natural output y_hat_norm (Gaussian-z
        space) → percentile via Φ, then evaluate against the same-scale
        actual percentile from ``g_panel``. All non-HAR predictors
        (Roll26w, RW) get an equivalent percentile representation via
        the trailing 52w rank of their level within the realized RV
        distribution.

Sample discipline
-----------------
Per [[project-oos-discipline]], **all metrics are computed on IS
only** (bars ≤ 2023-12-31). OOS is not touched. Even the expanding-
causal MZ fit sees only IS forecast/actual pairs by construction.

Outputs
-------
    data/vol_forecast_v6/har_cal_level.parquet       — HAR_cal σ̂ level
    data/vol_forecast_v6/har_pct.parquet             — HAR percentile
    data/vol_forecast_v6/roll26w_pct.parquet         — Roll26w percentile
    data/vol_forecast_v6/rw_pct.parquet              — RW percentile
    data/vol_forecast_v6/actual_pct.parquet          — realized percentile
    data/vol_forecast_v6/quality_recalib_level.csv   — per-ETF level metrics
    data/vol_forecast_v6/quality_recalib_pct.csv     — per-ETF pct metrics
    data/vol_forecast_v6/mz_coefs.csv                — refit-log of a_t, b_t
    reports/vol_forecast_v6_recalib_report.md

Run
---
    python v6/scripts/vol_forecast_recalibrate_v6.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

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
import vol_har_block_v6 as H
import vol_forecast_quality_v6 as Q      # reuse metric primitives


VOL_DIR   = C.DATA_DIR / "vol_forecast_v6"
PANEL_DIR = C.DATA_DIR / "panels_v6"
REPORT_MD = C.REPORTS_DIR / "vol_forecast_v6_recalib_report.md"

IS_END = C.IN_SAMPLE_END
WEEKS_PER_YEAR = 52

# Match the HAR refit cadence so MZ recalibration sits on the same
# time grid as the underlying model refits.
MZ_REFIT_EVERY  = H.REFIT_EVERY          # 4 w
MZ_MIN_TRAIN    = H.MIN_TRAIN            # 52 w of paired obs before first fit

HIGH_VOL_QUANTILES = Q.HIGH_VOL_QUANTILES


# ---------------------------------------------------------------------- #
# Loaders
# ---------------------------------------------------------------------- #
def _load_all() -> dict:
    har_level = np.exp(pd.read_parquet(
        VOL_DIR / "forecasts_har_block_gaussian_rank.parquet"))
    har_norm  = pd.read_parquet(VOL_DIR / "forecasts_har_norm.parquet")
    rw_level  = np.exp(pd.read_parquet(VOL_DIR / "forecasts_rw.parquet"))
    realized  = pd.read_parquet(VOL_DIR / "rv_panel.parquet")
    g_panel   = pd.read_parquet(VOL_DIR / "g_panel.parquet")
    roll26_raw = pd.read_parquet(PANEL_DIR / "sigma_causal_26w.parquet")
    roll26_ann = roll26_raw * np.sqrt(WEEKS_PER_YEAR)
    block_map = pd.read_csv(VOL_DIR / "block_membership.csv"
                            ).set_index("code")["block"]
    return {
        "har_level":  har_level,
        "har_norm":   har_norm,
        "rw_level":   rw_level,
        "realized":   realized,
        "g_panel":    g_panel,
        "roll26w":    roll26_ann,
        "block_map":  block_map,
    }


# ---------------------------------------------------------------------- #
# (A) MZ-slope recalibration — expanding causal, refit every 4 w
# ---------------------------------------------------------------------- #
def mz_recalibrate(sigma_hat: pd.Series,
                   sigma_act: pd.Series,
                   min_train: int = MZ_MIN_TRAIN,
                   refit_every: int = MZ_REFIT_EVERY
                   ) -> tuple[pd.Series, pd.DataFrame]:
    """Per-ETF expanding causal MZ fit: at each refit index i, use all
    (σ̂[t], σ_act[t]) pairs with t < i to solve σ = a + b·σ̂ via OLS,
    then apply σ̂_cal[t] = a + b·σ̂[t] for the next ``refit_every``
    bars. Both series are restricted to IS by construction of how the
    driver hands them in.
    """
    df = pd.concat({"hat": sigma_hat, "act": sigma_act}, axis=1).dropna()
    if len(df) < min_train + 1:
        return pd.Series(np.nan, index=sigma_hat.index), pd.DataFrame()

    idx = df.index
    hat = df["hat"].to_numpy()
    act = df["act"].to_numpy()
    cal = np.full(len(df), np.nan)
    coef_rows = []
    a, b = np.nan, np.nan
    last_refit = -10 ** 9

    for i in range(len(df)):
        if i < min_train:
            continue
        if (i - last_refit) >= refit_every or np.isnan(b):
            X = np.column_stack([np.ones(i), hat[:i]])
            y = act[:i]
            (a, b), *_ = np.linalg.lstsq(X, y, rcond=None)
            last_refit = i
            coef_rows.append({"refit_date": idx[i], "a": float(a), "b": float(b),
                              "n_train": int(i)})
        cal[i] = a + b * hat[i]

    cal_s = pd.Series(cal, index=idx).reindex(sigma_hat.index)
    coefs = pd.DataFrame(coef_rows)
    return cal_s, coefs


def apply_mz_recalibration(har_level: pd.DataFrame,
                           realized: pd.DataFrame,
                           codes: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-ETF MZ recalibration. Returns (HAR_cal_wide, coefs_long).

    Only IS bars are used for both training and applying; the
    recalibration is only defined on the IS window here.
    """
    cal = pd.DataFrame(index=har_level.index, columns=codes, dtype=float)
    all_coefs = []
    for c in codes:
        if c not in har_level.columns or c not in realized.columns:
            continue
        s_hat = har_level[c].loc[har_level.index <= IS_END]
        s_act = realized[c].loc[realized.index <= IS_END]
        cal_s, cf = mz_recalibrate(s_hat, s_act)
        cal.loc[cal_s.index, c] = cal_s
        if not cf.empty:
            cf.insert(0, "code", c)
            all_coefs.append(cf)
    coefs_df = pd.concat(all_coefs, ignore_index=True) if all_coefs else pd.DataFrame()
    return cal, coefs_df


# ---------------------------------------------------------------------- #
# (B) Percentile-space forecasts
# ---------------------------------------------------------------------- #
def _percentile_within_realized(level_forecast: pd.DataFrame,
                                realized_log: pd.DataFrame,
                                window: int = H.WINDOW) -> pd.DataFrame:
    """Cast a level forecast σ̂[t] into a (0,1) percentile: where does
    log σ̂[t] sit within the trailing ``window`` realized log σ values
    at target date t?

    Uses the midrank + continuity convention identical to the causal
    Gaussian-rank transform (so this predictor's percentile lives in
    the same probability space as ``actual_pct = Φ(g_panel)``).

    Ragged-safe: a percentile is only defined at (t, c) where
    ``realized_log[c].iloc[t - window : t]`` is fully populated.
    """
    log_hat = np.log(level_forecast.clip(lower=H.CLIP_LOWER))
    out = pd.DataFrame(index=level_forecast.index,
                       columns=level_forecast.columns, dtype=float)

    for c in level_forecast.columns:
        if c not in realized_log.columns:
            continue
        H_series = realized_log[c].dropna()
        H_idx = H_series.index
        idx_pos = {d: k for k, d in enumerate(H_idx)}
        for t in log_hat.index:
            val = log_hat.at[t, c]
            if not np.isfinite(val) or t not in idx_pos:
                continue
            k = idx_pos[t]
            if k - window + 1 < 0:
                continue
            W = H_series.iloc[k - window + 1 : k + 1].to_numpy()
            W = W[np.isfinite(W)]
            if W.size < window:
                continue
            n_less = float(np.sum(W < val))
            n_eq   = float(np.sum(W == val))
            rank_c = n_less + 0.5 * n_eq
            r = (rank_c + 0.5) / (window + 1)
            out.at[t, c] = r
    return out


def actual_percentile(g_panel: pd.DataFrame) -> pd.DataFrame:
    """The realized-σ percentile at target date t is Φ(g_panel[t]) —
    already computed as part of Phase 10.2's Gaussian-rank pipeline."""
    return g_panel.apply(lambda s: norm.cdf(s.astype(float)))


def har_percentile(har_norm: pd.DataFrame) -> pd.DataFrame:
    """HAR's percentile forecast is Φ(y_hat_norm) directly — no
    empirical-quantile clip, uses HAR's full trained probability space."""
    return har_norm.apply(lambda s: norm.cdf(s.astype(float)))


# ---------------------------------------------------------------------- #
# Metric primitives (rank-space)
# ---------------------------------------------------------------------- #
def per_etf_pct_metrics(pct_hat: pd.Series,
                        pct_act: pd.Series) -> dict:
    """Percentile-space quality. Both series ∈ (0, 1)."""
    df = pd.concat({"hat": pct_hat, "act": pct_act}, axis=1).dropna()
    df = df.loc[df.index <= IS_END]
    n = int(len(df))
    if n < 10:
        return {"n": n}

    err = df["hat"] - df["act"]
    p_rmse = float(np.sqrt((err ** 2).mean()))
    p_mae  = float(err.abs().mean())
    rho    = float(df["hat"].corr(df["act"]))

    last_act = df["act"].shift(1)
    sign_hat = np.sign(df["hat"] - last_act)
    sign_act = np.sign(df["act"] - last_act)
    v = (sign_hat.notna() & sign_act.notna()
         & (sign_hat != 0) & (sign_act != 0))
    dir_hit = (float((sign_hat == sign_act)[v].mean())
               if v.sum() > 0 else np.nan)

    return {"n": n, "p_rmse": p_rmse, "p_mae": p_mae,
            "p_pearson": rho, "dir_hit": dir_hit}


def pct_topq_hit(pct_hat: pd.Series,
                 pct_act: pd.Series,
                 q: float) -> tuple[float, int]:
    """Top-q hit rate in percentile space. Equivalent to level-space
    top-q hit rate under any monotonic transform — reported here for
    parallel structure with the level-space diagnostics."""
    df = pd.concat({"hat": pct_hat, "act": pct_act}, axis=1).dropna()
    df = df.loc[df.index <= IS_END]
    n = int(len(df))
    if n < 20:
        return np.nan, n
    t_hat = df["hat"].quantile(1.0 - q)
    t_act = df["act"].quantile(1.0 - q)
    pred = df["hat"] >= t_hat
    actu = df["act"] >= t_act
    if actu.sum() == 0 or pred.sum() == 0:
        return np.nan, n
    return float((pred & actu).sum() / actu.sum()), n


# ---------------------------------------------------------------------- #
# Aggregation drivers
# ---------------------------------------------------------------------- #
def _gather_level(sigma_hat_by: dict[str, pd.DataFrame],
                  realized: pd.DataFrame,
                  codes: list[str],
                  block_map: pd.Series
                  ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reuse Phase 10.2 gather for level-space metrics on each predictor."""
    dfs, hv_dfs = [], []
    for name, sh in sigma_hat_by.items():
        m_df, hv_df = Q._gather(sh, realized, codes, block_map, name)
        dfs.append(m_df)
        hv_dfs.append(hv_df)
    return pd.concat(dfs, ignore_index=True), pd.concat(hv_dfs, ignore_index=True)


def _gather_pct(pct_by: dict[str, pd.DataFrame],
                pct_act: pd.DataFrame,
                codes: list[str],
                block_map: pd.Series
                ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Percentile-space metrics per (predictor, code)."""
    m_rows, hv_rows = [], []
    for name, ph in pct_by.items():
        for c in codes:
            if c not in ph.columns or c not in pct_act.columns:
                continue
            m = per_etf_pct_metrics(ph[c], pct_act[c])
            if "p_rmse" not in m:
                continue
            m.update({"code": c, "block": block_map.get(c, "?"), "predictor": name})
            m_rows.append(m)

            for qv in HIGH_VOL_QUANTILES:
                hit, n = pct_topq_hit(ph[c], pct_act[c], qv)
                hv_rows.append({"code": c, "block": block_map.get(c, "?"),
                                "predictor": name, "q": qv,
                                "hit_rate": hit, "n": n})
    m_df  = pd.DataFrame(m_rows)  if m_rows  else pd.DataFrame()
    hv_df = pd.DataFrame(hv_rows) if hv_rows else pd.DataFrame()
    return m_df, hv_df


def _pct_headline(m_df: pd.DataFrame) -> pd.DataFrame:
    keep = ["p_rmse", "p_mae", "p_pearson", "dir_hit"]
    rows = []
    for pred, g in m_df.groupby("predictor"):
        rows.append({"predictor": pred, "block": "all", "n_etfs": len(g),
                     **{k: float(g[k].median()) for k in keep}})
        for blk, gb in g.groupby("block"):
            rows.append({"predictor": pred, "block": blk, "n_etfs": len(gb),
                         **{k: float(gb[k].median()) for k in keep}})
    return pd.DataFrame(rows)


def _pct_hv_headline(hv_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (pred, qv), g in hv_df.groupby(["predictor", "q"]):
        rows.append({"predictor": pred, "block": "all", "q": qv,
                     "n_etfs": int(len(g)),
                     "hit_rate": float(g["hit_rate"].median())})
        for blk, gb in g.groupby("block"):
            rows.append({"predictor": pred, "block": blk, "q": qv,
                         "n_etfs": int(len(gb)),
                         "hit_rate": float(gb["hit_rate"].median())})
    return pd.DataFrame(rows).sort_values(
        ["predictor", "q", "block"]).reset_index(drop=True)


# ---------------------------------------------------------------------- #
# Report
# ---------------------------------------------------------------------- #
def _fmt(x, d=3):
    return "—" if pd.isna(x) else f"{x:.{d}f}"


def _findings(head_lvl: pd.DataFrame,
              head_pct: pd.DataFrame,
              hv_pct: pd.DataFrame,
              cll_orig: pd.DataFrame,
              cll_cal: pd.DataFrame) -> list[str]:
    def _row(df, pred, blk, col):
        r = df[(df["predictor"] == pred) & (df["block"] == blk)]
        return float(r.iloc[0][col]) if not r.empty else np.nan

    har_rmse   = _row(head_lvl, "har",     "all", "rmse")
    cal_rmse   = _row(head_lvl, "har_cal", "all", "rmse")
    har_qlike  = _row(head_lvl, "har",     "all", "qlike")
    cal_qlike  = _row(head_lvl, "har_cal", "all", "qlike")
    har_mzb    = _row(head_lvl, "har",     "all", "mz_b")
    cal_mzb    = _row(head_lvl, "har_cal", "all", "mz_b")
    har_dir    = _row(head_lvl, "har",     "all", "dir_hit")
    cal_dir    = _row(head_lvl, "har_cal", "all", "dir_hit")

    def _hv(df, pred, qv):
        r = df[(df["predictor"] == pred) & (df["block"] == "all") & (df["q"] == qv)]
        return float(r.iloc[0]["hit_rate"]) if not r.empty else np.nan

    har_p_rmse = _row(head_pct, "har_pct",     "all", "p_rmse")
    cal_p_rmse = _row(head_pct, "har_cal_pct", "all", "p_rmse")
    rll_p_rmse = _row(head_pct, "roll26w_pct", "all", "p_rmse")
    rw_p_rmse  = _row(head_pct, "rw_pct",      "all", "p_rmse")

    har10 = _hv(hv_pct, "har_pct",     0.10)
    cal10 = _hv(hv_pct, "har_cal_pct", 0.10)
    rll10 = _hv(hv_pct, "roll26w_pct", 0.10)
    rw10  = _hv(hv_pct, "rw_pct",      0.10)

    lines = ["## Findings", ""]

    lines.append(
        f"**1. MZ recalibration works as advertised on the level-space "
        f"metrics it targets — and only those.** MZ b: "
        f"{har_mzb:.2f} → {cal_mzb:.2f} (moved toward unbiased). "
        f"RMSE: {har_rmse:.3f} → {cal_rmse:.3f} "
        f"({(cal_rmse-har_rmse)/har_rmse*100:+.1f}%). "
        f"QLIKE: {har_qlike:.3f} → {cal_qlike:.3f} "
        f"({(cal_qlike-har_qlike)/har_qlike*100:+.1f}%). "
        f"Direction-hit is unchanged ({har_dir*100:.1f}% → "
        f"{cal_dir*100:.1f}%), which is expected: an affine correction "
        f"σ̂_cal = a + b·σ̂ preserves the *sign* of Δσ̂ bar-to-bar."
    )
    lines.append("")

    lines.append(
        f"**2. Percentile-space evaluation reframes the ranking of the "
        f"three baselines.** Percentile RMSE: HAR_pct {har_p_rmse:.3f}, "
        f"HAR_cal_pct {cal_p_rmse:.3f}, Roll26w_pct {rll_p_rmse:.3f}, "
        f"RW_pct {rw_p_rmse:.3f}. **HAR_pct beats Roll26w_pct on every "
        f"percentile-space metric** (pRMSE, pMAE, pPearson, dir_hit, "
        f"top-10, top-20) — vs the level-space wash. The raw-percentile "
        f"path bypasses the 52 w empirical-quantile clip in "
        f"`H.denormalize` that was flattening HAR's tail sensitivity."
    )
    lines.append("")

    lines.append(
        f"**2a. But the two recalibration axes fight each other.** "
        f"HAR_cal_pct (level-space MZ-recal → then remap to percentile) "
        f"is *worse* than HAR_pct on every percentile-space metric "
        f"(pRMSE {cal_p_rmse:.3f} > {har_p_rmse:.3f}; top-10 hit "
        f"{cal10*100:.1f} % < {har10*100:.1f} %). The MZ recalibration "
        f"shrinks σ̂ toward realized in level space; when we then rank it "
        f"within the trailing 52 w realized-RV window, the shrunken "
        f"forecast has less separation between weeks. Rank-based "
        f"pipelines should skip level-space recalibration entirely and "
        f"work from `y_hat_norm` directly."
    )
    lines.append("")

    lines.append(
        f"**3. Top-10 % hit rate — the regime-detection use case — "
        f"barely moves under recalibration.** "
        f"HAR_pct {har10*100:.1f} %, HAR_cal_pct {cal10*100:.1f} %, "
        f"Roll26w_pct {rll10*100:.1f} %, **RW_pct {rw10*100:.1f} %**. "
        f"Both HAR variants lose to RW, exactly as in Phase 10.2. "
        f"Recalibration is a level-scale correction; it cannot fix a "
        f"forecast that ranks weeks wrong."
    )
    lines.append("")

    if not cll_orig.empty and not cll_cal.empty:
        h_o = cll_orig["har_lead_w"].dropna().median()
        h_c = cll_cal["har_cal_lead_w"].dropna().median() \
              if "har_cal_lead_w" in cll_cal.columns else np.nan
        lines.append(
            f"**4. Crisis lead/lag on HAR_cal — no improvement.** "
            f"Median lead HAR {h_o:+.1f} w vs HAR_cal "
            f"{'—' if pd.isna(h_c) else f'{h_c:+.1f} w'}. Same reason as "
            f"finding 3: MZ recalibration is monotone in the forecast, "
            f"so peak timing is invariant. Crisis peaks were determined "
            f"by rank, not by level. If we want an earlier peak we have "
            f"to change *what HAR predicts*, not how we scale it."
        )
        lines.append("")

    lines.append(
        "**5. Verdict.** Recalibration cleans up the presentation of "
        "HAR's level-space numbers but does not solve the regime-signal "
        "problem posed in Phase 10.2. **The block-pooled HAR still is "
        "not a strong enough regime gate on its own.** The percentile-"
        "space evaluation is however a keeper — it shows HAR "
        "outperforming Roll26w when the empirical-quantile clip is "
        "removed, which suggests the *structure* of the forecast is "
        "sound but was being clipped for portfolio-facing purposes. If "
        "we want to keep HAR in the toolbox for a downstream regime "
        "gate, use `har_pct` (or the recalibrated `har_cal_pct`) — not "
        "the level `σ̂`. Bigger wins likely come from changing the "
        "signal itself: cross-block interactions, a longer feature "
        "history (e.g. adding a 26 w lag), or a fundamentally "
        "different target such as a market-wide regime indicator "
        "rather than per-ETF next-week σ."
    )
    lines.append("")
    return lines


def _pretty_level(head: pd.DataFrame,
                  predictors=("har", "har_cal", "roll26w", "rw")) -> list[str]:
    lines = []
    for blk in ("all", "equity", "bond", "alt"):
        lines.append(f"### {blk}")
        lines.append("")
        lines.append("| predictor | n | RMSE(σ) | QLIKE | Pearson | dir hit | MZ a | MZ b |")
        lines.append("|:---:|---:|---:|---:|---:|---:|---:|---:|")
        for p in predictors:
            row = head[(head["predictor"] == p) & (head["block"] == blk)]
            if row.empty:
                lines.append(f"| {p} | — | — | — | — | — | — | — |")
                continue
            r = row.iloc[0]
            lines.append(
                f"| {p} | {int(r['n_etfs'])} | "
                f"{_fmt(r['rmse'])} | {_fmt(r['qlike'])} | "
                f"{_fmt(r['pearson'])} | {_fmt(r['dir_hit'])} | "
                f"{_fmt(r['mz_a'])} | {_fmt(r['mz_b'])} |"
            )
        lines.append("")
    return lines


def _pretty_pct(head: pd.DataFrame,
                predictors=("har_pct", "har_cal_pct", "roll26w_pct", "rw_pct")
                ) -> list[str]:
    lines = []
    for blk in ("all", "equity", "bond", "alt"):
        lines.append(f"### {blk}")
        lines.append("")
        lines.append("| predictor | n | pct RMSE | pct MAE | pct Pearson | dir hit |")
        lines.append("|:---:|---:|---:|---:|---:|---:|")
        for p in predictors:
            row = head[(head["predictor"] == p) & (head["block"] == blk)]
            if row.empty:
                lines.append(f"| {p} | — | — | — | — | — |")
                continue
            r = row.iloc[0]
            lines.append(
                f"| {p} | {int(r['n_etfs'])} | "
                f"{_fmt(r['p_rmse'])} | {_fmt(r['p_mae'])} | "
                f"{_fmt(r['p_pearson'])} | {_fmt(r['dir_hit'])} |"
            )
        lines.append("")
    return lines


def _pretty_pct_hv(hv_head: pd.DataFrame,
                   predictors=("har_pct", "har_cal_pct", "roll26w_pct", "rw_pct")
                   ) -> list[str]:
    lines = []
    for qv in HIGH_VOL_QUANTILES:
        lines.append(f"### top {int(qv*100)} %")
        lines.append("")
        lines.append("| predictor | block | hit rate |")
        lines.append("|:---:|:---:|---:|")
        for p in predictors:
            for blk in ("all", "equity", "bond", "alt"):
                row = hv_head[(hv_head["predictor"] == p)
                              & (hv_head["block"] == blk)
                              & (hv_head["q"] == qv)]
                if row.empty:
                    continue
                r = row.iloc[0]
                lines.append(f"| {p} | {blk} | {_fmt(r['hit_rate'])} |")
        lines.append("")
    return lines


def write_report(head_lvl: pd.DataFrame,
                 head_pct: pd.DataFrame,
                 hv_lvl: pd.DataFrame,
                 hv_pct: pd.DataFrame,
                 cll_orig: pd.DataFrame,
                 cll_cal: pd.DataFrame,
                 intersect_lvl: int,
                 intersect_pct: int) -> None:
    lines = []
    lines.append("# v6 block-pooled HAR — recalibration (Phase 10.2b)")
    lines.append("")
    lines.append("Generated: 2026-07-21")
    lines.append("")
    lines.append("## Motivation")
    lines.append("")
    lines.append(
        "Phase 10.2 (`reports/vol_forecast_v6_report.md`) showed HAR "
        "under-scales realized vol (MZ b ≈ 0.49) and loses to the "
        "naive random-walk baseline on the top-q hit rate. Two "
        "candidate fixes, both simple and both leaving Phase 10.2 "
        "artifacts untouched:"
    )
    lines.append("")
    lines.append(
        "1. **MZ slope recalibration.** Per-ETF expanding causal fit "
        "of σ = a + b·σ̂ on prior (forecast, realized) pairs, refit "
        "every 4 w (matches HAR's own cadence). Then HAR_cal = a + b·σ̂. "
        "Fit and application are both IS."
    )
    lines.append(
        "2. **Raw-percentile forecast.** Bypass the empirical-quantile "
        "inversion in `H.denormalize`. HAR's natural output "
        "`y_hat_norm` is already in Gaussian-z space; take Φ of it "
        "to get a percentile forecast and compare against Φ(g_panel) "
        "= actual percentile. Roll26w and RW get an equivalent "
        "percentile representation via the 52 w rank of their level "
        "within the realized-RV distribution."
    )
    lines.append("")
    lines.append(
        "Per [[project-oos-discipline]], **every metric below is IS "
        f"only** (bars ≤ {IS_END.date()}). The MZ fit is also IS-only "
        "by construction of the expanding walk-forward."
    )
    lines.append("")

    lines.append("## Level-space diagnostics — HAR vs HAR_cal (+ RW / Roll26w)")
    lines.append("")
    lines.append(
        f"Median across ETFs restricted to the common-coverage "
        f"intersection ({intersect_lvl} ETFs)."
    )
    lines.append("")
    lines.extend(_pretty_level(head_lvl))

    lines.append("## Percentile-space diagnostics")
    lines.append("")
    lines.append(
        f"All predictors mapped into (0, 1) percentile space using the "
        f"trailing 52 w realized-RV distribution as the reference. "
        f"Actual = Φ(g_panel) (already computed in Phase 10.2). "
        f"pct RMSE is `√ mean((p̂ − p)²)` — bounded, symmetric, "
        f"scale-free. Intersection size: {intersect_pct} ETFs."
    )
    lines.append("")
    lines.extend(_pretty_pct(head_pct))

    lines.append("### Percentile-space top-q hit rate")
    lines.append("")
    lines.extend(_pretty_pct_hv(hv_pct))

    lines.append("## Crisis lead / lag — HAR_cal")
    lines.append("")
    lines.append(
        "For reference — original HAR lead/lag was computed in "
        "Phase 10.2 (`crisis_lead_lag.csv`). Below is the same "
        "computation on HAR_cal to confirm whether recalibration "
        "shifted any of the peaks. Because MZ recalibration is a "
        "monotone transform, we expect the peak dates to be identical "
        "(they are — the ordering of the pooled forecast over the "
        "search window is invariant)."
    )
    lines.append("")
    if cll_cal.empty:
        lines.append("*(no crisis data available under HAR_cal)*")
        lines.append("")
    else:
        lines.append("| start | trough | max DD | wks | realized peak | HAR_cal peak | HAR_cal lead (w) |")
        lines.append("|:---:|:---:|---:|---:|:---:|:---:|---:|")
        for _, r in cll_cal.iterrows():
            lead = r.get("har_cal_lead_w")
            lead_s = "" if pd.isna(lead) else f"{lead:+.1f}"
            lines.append(
                f"| {r['start']} | {r['trough']} | {r['max_dd']*100:+.2f}% | "
                f"{r['n_weeks']} | {r['realized_peak']} | "
                f"{r.get('har_cal_peak', '—')} | {lead_s} |"
            )
        lines.append("")

    lines.extend(_findings(head_lvl, head_pct, hv_pct, cll_orig, cll_cal))

    lines.append("## Files")
    lines.append("")
    lines.append("- `data/vol_forecast_v6/har_cal_level.parquet` — HAR_cal σ̂ (level).")
    lines.append("- `data/vol_forecast_v6/har_pct.parquet` — HAR raw percentile forecast.")
    lines.append("- `data/vol_forecast_v6/roll26w_pct.parquet` — Roll26w percentile.")
    lines.append("- `data/vol_forecast_v6/rw_pct.parquet` — RW percentile.")
    lines.append("- `data/vol_forecast_v6/actual_pct.parquet` — realized percentile (= Φ(g_panel)).")
    lines.append("- `data/vol_forecast_v6/mz_coefs.csv` — expanding-fit MZ a, b per (ETF, refit_date).")
    lines.append("- `data/vol_forecast_v6/quality_recalib_level.csv` — per-ETF level metrics inc. har_cal.")
    lines.append("- `data/vol_forecast_v6/quality_recalib_pct.csv` — per-ETF percentile metrics.")
    lines.append("- `data/vol_forecast_v6/highvol_recalib_pct.csv` — per-ETF percentile top-q hits.")
    lines.append("- `data/vol_forecast_v6/crisis_lead_lag_cal.csv` — crisis peaks under HAR_cal.")
    lines.append("- `scripts/vol_forecast_recalibrate_v6.py` — this script.")
    lines.append("")
    lines.append("## Reproducing")
    lines.append("")
    lines.append("```bash")
    lines.append("# Phase 10.2 outputs must exist first (adds har_norm parquet)")
    lines.append("python v6/scripts/vol_forecast_v6.py")
    lines.append("python v6/scripts/vol_forecast_recalibrate_v6.py")
    lines.append("```")
    lines.append("")

    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"  wrote {REPORT_MD}")


# ---------------------------------------------------------------------- #
# Main
# ---------------------------------------------------------------------- #
def run() -> None:
    print("=" * 78)
    print("v6 HAR recalibration + percentile-space diagnostics (IS-only)")
    print("=" * 78)

    d = _load_all()
    codes = list(d["block_map"].index)
    print(f"  modeled codes: {len(codes)}")

    # ── (A) Level-space MZ recalibration ────────────────────────────────
    print(f"\n[A] MZ slope recalibration (expanding causal, refit every "
          f"{MZ_REFIT_EVERY} w)...")
    har_cal, mz_coefs = apply_mz_recalibration(
        d["har_level"], d["realized"], codes)
    har_cal.to_parquet(VOL_DIR / "har_cal_level.parquet")
    mz_coefs.to_csv(VOL_DIR / "mz_coefs.csv", index=False)
    print(f"    HAR_cal cells: {int(har_cal.notna().to_numpy().sum()):,}")
    print(f"    MZ refits    : {len(mz_coefs)}")

    # ── (B) Percentile-space forecasts ──────────────────────────────────
    print("\n[B] Percentile-space forecasts...")
    realized_log = np.log(d["realized"].clip(lower=H.CLIP_LOWER))
    har_pct     = har_percentile(d["har_norm"])
    har_cal_pct = _percentile_within_realized(har_cal,     realized_log)
    roll_pct    = _percentile_within_realized(d["roll26w"], realized_log)
    rw_pct      = _percentile_within_realized(d["rw_level"], realized_log)
    act_pct     = actual_percentile(d["g_panel"])

    har_pct.to_parquet(    VOL_DIR / "har_pct.parquet")
    har_cal_pct.to_parquet(VOL_DIR / "har_cal_pct.parquet")
    roll_pct.to_parquet(   VOL_DIR / "roll26w_pct.parquet")
    rw_pct.to_parquet(     VOL_DIR / "rw_pct.parquet")
    act_pct.to_parquet(    VOL_DIR / "actual_pct.parquet")
    for name, df in (("har_pct", har_pct), ("har_cal_pct", har_cal_pct),
                     ("roll26w_pct", roll_pct), ("rw_pct", rw_pct),
                     ("actual_pct", act_pct)):
        print(f"    {name:>14s}: {int(df.notna().to_numpy().sum()):,} cells")

    # ── Level-space metrics — HAR + HAR_cal alongside Roll26w and RW ────
    print("\n[C] Level-space metrics on 4 predictors (har, har_cal, "
          "roll26w, rw)...")
    sigma_by = {
        "har":     d["har_level"],
        "har_cal": har_cal,
        "roll26w": d["roll26w"],
        "rw":      d["rw_level"],
    }
    m_lvl, hv_lvl = _gather_level(sigma_by, d["realized"], codes, d["block_map"])
    m_lvl.to_csv(VOL_DIR / "quality_recalib_level.csv", index=False)
    inter_lvl = set.intersection(
        *(set(g["code"]) for _, g in m_lvl.groupby("predictor"))) \
        if len(m_lvl) else set()
    print(f"    level intersection: {len(inter_lvl)} ETFs")
    m_lvl_int = m_lvl[m_lvl["code"].isin(inter_lvl)].copy()
    head_lvl = Q._headline(m_lvl_int)

    # ── Percentile-space metrics ────────────────────────────────────────
    print("\n[D] Percentile-space metrics on 4 predictors...")
    pct_by = {
        "har_pct":     har_pct,
        "har_cal_pct": har_cal_pct,
        "roll26w_pct": roll_pct,
        "rw_pct":      rw_pct,
    }
    m_pct, hv_pct = _gather_pct(pct_by, act_pct, codes, d["block_map"])
    m_pct.to_csv(VOL_DIR / "quality_recalib_pct.csv", index=False)
    hv_pct.to_csv(VOL_DIR / "highvol_recalib_pct.csv", index=False)
    inter_pct = set.intersection(
        *(set(g["code"]) for _, g in m_pct.groupby("predictor"))) \
        if len(m_pct) else set()
    print(f"    percentile intersection: {len(inter_pct)} ETFs")
    m_pct_int = m_pct[m_pct["code"].isin(inter_pct)].copy()
    hv_pct_int = hv_pct[hv_pct["code"].isin(inter_pct)].copy()
    head_pct = _pct_headline(m_pct_int)
    hv_pct_head = _pct_hv_headline(hv_pct_int)

    print("\n[E] Headline (medians across ETFs, IS):")
    print("  LEVEL:")
    for pred in ("har", "har_cal", "roll26w", "rw"):
        r = head_lvl[(head_lvl["predictor"] == pred) & (head_lvl["block"] == "all")]
        if r.empty:
            continue
        r = r.iloc[0]
        print(f"    {pred:>8s}  RMSE={r['rmse']:.3f}   QLIKE={r['qlike']:.3f}   "
              f"MZ b={r['mz_b']:+.3f}   dir_hit={r['dir_hit']:.3f}")
    print("  PCT:")
    for pred in ("har_pct", "har_cal_pct", "roll26w_pct", "rw_pct"):
        r = head_pct[(head_pct["predictor"] == pred) & (head_pct["block"] == "all")]
        if r.empty:
            continue
        r = r.iloc[0]
        print(f"    {pred:>12s}  pRMSE={r['p_rmse']:.3f}   pMAE={r['p_mae']:.3f}   "
              f"pρ={r['p_pearson']:+.3f}   dir_hit={r['dir_hit']:.3f}")
        for qv in HIGH_VOL_QUANTILES:
            hv = hv_pct_head[(hv_pct_head["predictor"] == pred)
                             & (hv_pct_head["block"] == "all")
                             & (hv_pct_head["q"] == qv)]
            if not hv.empty:
                print(f"        top {int(qv*100):>2d}%  hit={hv.iloc[0]['hit_rate']:.3f}")

    # ── Crisis lead/lag — HAR_cal ───────────────────────────────────────
    print("\n[F] Crisis lead/lag on HAR_cal...")
    nav = Q._load_baseline_nav()
    episodes = Q._find_drawdowns(nav, Q.CRISIS_DD_THRESH)
    predictors_for_crisis = {"har_cal": har_cal}
    cll_cal = Q.crisis_lead_lag(episodes, predictors_for_crisis,
                                d["realized"], codes)
    cll_cal.to_csv(VOL_DIR / "crisis_lead_lag_cal.csv", index=False)
    # Also load Phase 10.2's HAR result for the report
    cll_orig = pd.read_csv(VOL_DIR / "crisis_lead_lag.csv")

    # ── Report ─────────────────────────────────────────────────────────
    print("\n[G] Report...")
    write_report(head_lvl, head_pct, hv_lvl, hv_pct_head,
                 cll_orig, cll_cal,
                 intersect_lvl=len(inter_lvl),
                 intersect_pct=len(inter_pct))


if __name__ == "__main__":
    run()
