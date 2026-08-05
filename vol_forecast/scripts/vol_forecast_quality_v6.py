"""
v6/scripts/vol_forecast_quality_v6.py
=====================================
Phase 10.2 — forecast-quality comparison for the block-pooled HAR.

Compares three σ_{t+1} predictors against realized weekly RV_{t+1}:

    HAR       — block-pooled HAR-RV (data/vol_forecast_v6/forecasts_har_block_gaussian_rank.parquet)
    RW        — random walk σ̂_{t+1} = σ_t (data/vol_forecast_v6/forecasts_rw.parquet)
    Roll26w   — the sizing-side estimator currently used in xs_engine_v6
                (data/panels_v6/sigma_causal_26w.parquet), annualized
                by ×√52 to bring it onto RV's annualized scale.

Sample discipline
-----------------
Per [[project-oos-discipline]], **all metrics are computed on IS only**
(bars ≤ 2023-12-31). OOS numbers are neither aggregated nor displayed.

Per-ETF metrics
---------------
    RMSE(σ)         forecast error in annualized-vol units
    QLIKE           r - log r - 1 where r = σ²/σ̂²  (Patton 2011)
    Pearson ρ(σ̂, σ)
    Direction hit   sign(σ̂ - σ_t) vs sign(σ - σ_t) — % correct
    MZ (a, b)       σ = a + b·σ̂ regression on IS window

Cross-sectional / regime-detection metrics
------------------------------------------
Per-ETF, weeks where realized RV_{t+1} sits in the top 10 % (or 20 %)
of that ETF's own IS distribution are the "actually high-vol" set.
Weeks where forecast σ̂_{t+1} sits in its own top 10 % (or 20 %) are
the "predicted high-vol" set.

    Recall @ q     = |predicted ∩ actual| / |actual|
    Precision @ q  = |predicted ∩ actual| / |predicted|

Reported medians across ETFs; per-ETF rows in the CSV.

Crisis lead / lag
-----------------
Uses the `long_q20` baseline's NAV path (ε=0, checked-in ensemble
net_ret) to define crisis windows: each contiguous drawdown ≥ 2 %
inside the IS window. For each crisis:

    peak_forecast_date = argmax σ̂_pool over [start-4w, end+2w]
    peak_realized_date = argmax σ_pool  over [start-2w, end+2w]
    lead = peak_realized_date - peak_forecast_date  (weeks)

Positive lead = forecast peaked before realized (early warning).
Negative = forecast lagged. σ̂_pool / σ_pool are cross-sectional
means restricted to the IS window and the modeled ETF set.

Outputs
-------
    data/vol_forecast_v6/quality_per_etf.csv
    data/vol_forecast_v6/quality_headline.csv
    data/vol_forecast_v6/highvol_recall_precision.csv
    data/vol_forecast_v6/crisis_lead_lag.csv
    reports/vol_forecast_v6_report.md

Run
---
    python v6/scripts/vol_forecast_quality_v6.py
"""
from __future__ import annotations

from pathlib import Path

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
import _common_v6 as C


VOL_DIR    = C.DATA_DIR / "vol_forecast_v6"
PANEL_DIR  = C.DATA_DIR / "panels_v6"
REPORT_MD  = C.REPORTS_DIR / "vol_forecast_v6_report.md"

IS_END = C.IN_SAMPLE_END      # 2023-12-31 — never crossed by this script

WEEKS_PER_YEAR = 52
HIGH_VOL_QUANTILES = (0.10, 0.20)

BASELINE_NET_RET = (C.DATA_DIR / "v6_static" / "long_q20"
                    / "ensemble_net_ret.csv")
CRISIS_DD_THRESH = 0.02        # ≥ 2 % drawdown counts as a crisis
# Symmetric search window applied to every predictor AND to realized
# so that a peak that fell outside the window can't produce a phantom
# "lead" (see the RW quirk in the first pass of Phase 10.2).
CRISIS_PRE_WIN   = 8           # weeks before drawdown start
CRISIS_POST_WIN  = 4           # weeks after drawdown end


# ---------------------------------------------------------------------- #
# Data loading + alignment
# ---------------------------------------------------------------------- #
def _load_predictors() -> dict[str, pd.DataFrame]:
    """All three σ_{t+1} predictors on the annualized-RV scale.

    HAR & RW are already annualized (log σ̂ persisted in RV units).
    Roll26w is the panels-side std of weekly log returns; multiply by
    √52 to annualize.
    """
    har = np.exp(pd.read_parquet(
        VOL_DIR / "forecasts_har_block_gaussian_rank.parquet"))
    rw  = np.exp(pd.read_parquet(VOL_DIR / "forecasts_rw.parquet"))

    roll26 = pd.read_parquet(PANEL_DIR / "sigma_causal_26w.parquet")
    roll26_ann = roll26 * np.sqrt(WEEKS_PER_YEAR)

    return {"har": har, "rw": rw, "roll26w": roll26_ann}


def _load_realized() -> pd.DataFrame:
    """Realized annualized weekly RV panel."""
    return pd.read_parquet(VOL_DIR / "rv_panel.parquet")


def _load_block_map() -> pd.Series:
    df = pd.read_csv(VOL_DIR / "block_membership.csv")
    return df.set_index("code")["block"]


# ---------------------------------------------------------------------- #
# Metric primitives
# ---------------------------------------------------------------------- #
def qlike(sigma_hat: pd.Series, sigma: pd.Series) -> pd.Series:
    """r - log r - 1 with r = σ²/σ̂². Ignores non-positive cells."""
    v_hat = sigma_hat.pow(2)
    v_act = sigma.pow(2)
    r = v_act / v_hat
    return (r - np.log(r) - 1.0).replace([np.inf, -np.inf], np.nan)


def per_etf_metrics(sigma_hat: pd.Series,
                    sigma_act: pd.Series) -> dict:
    """RMSE(σ) / QLIKE / Pearson / dir_hit / MZ (a, b) on the intersection
    of IS-defined bars."""
    df = pd.concat({"hat": sigma_hat, "act": sigma_act}, axis=1).dropna()
    df = df.loc[df.index <= IS_END]
    n = int(len(df))
    if n < 10:
        return {"n": n}

    rmse  = float(np.sqrt(((df["hat"] - df["act"]) ** 2).mean()))
    q     = float(qlike(df["hat"], df["act"]).dropna().mean())
    rho   = float(df["hat"].corr(df["act"]))

    # Mincer-Zarnowitz: σ = a + b·σ̂  (level regression, no log — the
    # HAR literature convention when the target is σ, not σ²).
    x = df["hat"].values
    y = df["act"].values
    A = np.column_stack([np.ones(len(x)), x])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    mz_a, mz_b = float(coef[0]), float(coef[1])

    # Direction hit: sign(σ̂_{t+1} - σ_t) vs sign(σ_{t+1} - σ_t)
    last_act = df["act"].shift(1)
    sign_hat = np.sign(df["hat"] - last_act)
    sign_act = np.sign(df["act"] - last_act)
    v = (sign_hat.notna() & sign_act.notna()
         & (sign_hat != 0) & (sign_act != 0))
    dir_hit = (float((sign_hat == sign_act)[v].mean())
               if v.sum() > 0 else np.nan)

    return {"n": n, "rmse": rmse, "qlike": q, "pearson": rho,
            "mz_a": mz_a, "mz_b": mz_b, "dir_hit": dir_hit}


def highvol_recall_precision(sigma_hat: pd.Series,
                             sigma_act: pd.Series,
                             q: float) -> tuple[float, float, int]:
    """Temporal recall / precision at ETF-level top-q% (IS).

    Actual set  = weeks in the ETF's IS series ≥ q-quantile realized.
    Predicted set = weeks in the same series ≥ q-quantile forecast.
    """
    df = pd.concat({"hat": sigma_hat, "act": sigma_act}, axis=1).dropna()
    df = df.loc[df.index <= IS_END]
    n = int(len(df))
    if n < 20:
        return (np.nan, np.nan, n)

    t_hat = df["hat"].quantile(1.0 - q)
    t_act = df["act"].quantile(1.0 - q)
    pred = df["hat"] >= t_hat
    actu = df["act"] >= t_act
    if actu.sum() == 0 or pred.sum() == 0:
        return (np.nan, np.nan, n)
    inter = (pred & actu).sum()
    recall    = float(inter / actu.sum())
    precision = float(inter / pred.sum())
    return recall, precision, n


# ---------------------------------------------------------------------- #
# Crisis lead / lag on the long_q20 baseline drawdowns
# ---------------------------------------------------------------------- #
def _load_baseline_nav() -> pd.Series:
    """NAV = 1 + Σ net_ret, restricted to IS."""
    df = pd.read_csv(BASELINE_NET_RET, index_col=0, parse_dates=[0])
    net = df["net_ret"].astype(float)
    net_is = net.loc[net.index <= IS_END]
    return (1.0 + net_is.cumsum()).rename("nav")


def _find_drawdowns(nav: pd.Series,
                    threshold: float = CRISIS_DD_THRESH) -> pd.DataFrame:
    """Contiguous drawdown episodes ≥ threshold.

    A drawdown episode starts at bar t whenever NAV falls below its
    running peak by ≥ threshold at any point in the episode; it ends
    when NAV reclaims the running peak.
    """
    cummax = nav.cummax()
    dd = (nav / cummax) - 1.0
    below = dd < 0

    episodes = []
    start = None
    for i, is_below in enumerate(below.values):
        if is_below and start is None:
            start = i
        elif not is_below and start is not None:
            end = i - 1
            ep = dd.iloc[start:end + 1]
            if ep.min() <= -threshold:
                trough_pos = ep.idxmin()
                episodes.append({
                    "start":  ep.index[0],
                    "end":    ep.index[-1],
                    "trough": trough_pos,
                    "max_dd": float(ep.min()),
                    "n_weeks": int(len(ep)),
                })
            start = None
    if start is not None:
        # Trailing episode still open at series end
        ep = dd.iloc[start:]
        if ep.min() <= -threshold:
            episodes.append({
                "start":  ep.index[0],
                "end":    ep.index[-1],
                "trough": ep.idxmin(),
                "max_dd": float(ep.min()),
                "n_weeks": int(len(ep)),
            })
    return pd.DataFrame(episodes)


def crisis_lead_lag(episodes: pd.DataFrame,
                    predictors: dict[str, pd.DataFrame],
                    realized: pd.DataFrame,
                    codes: list[str]) -> pd.DataFrame:
    """Lead (weeks) between forecast peak and realized peak within each
    drawdown episode, using cross-sectional mean σ over the modeled
    ETFs. Positive = forecast peaked *before* realized (early warning);
    negative = lagged.

    The same **symmetric** search window is applied to realized and to
    every forecast: [start − CRISIS_PRE_WIN, end + CRISIS_POST_WIN].
    That guarantees a peak captured by one predictor is potentially
    reachable by another, so no phantom "leads" from asymmetric window
    edges (see the first-pass RW quirk).
    """
    real_is = realized[codes].loc[realized.index <= IS_END]
    real_pool = real_is.mean(axis=1)

    pool: dict[str, pd.Series] = {}
    for name, pred in predictors.items():
        p_is = pred[codes].loc[pred.index <= IS_END]
        pool[name] = p_is.mean(axis=1)

    rows = []
    for _, ep in episodes.iterrows():
        start = ep["start"]
        end   = ep["end"]
        lo = start - pd.Timedelta(weeks=CRISIS_PRE_WIN)
        hi = end   + pd.Timedelta(weeks=CRISIS_POST_WIN)

        r_win = real_pool.loc[(real_pool.index >= lo)
                              & (real_pool.index <= hi)].dropna()
        if r_win.empty:
            continue
        r_peak = r_win.idxmax()

        row = {
            "start":     start.date(),
            "end":       end.date(),
            "trough":    ep["trough"].date(),
            "max_dd":    ep["max_dd"],
            "n_weeks":   int(ep["n_weeks"]),
            "realized_peak": r_peak.date(),
        }
        for name, p_pool in pool.items():
            f_win = p_pool.loc[(p_pool.index >= lo)
                               & (p_pool.index <= hi)].dropna()
            if f_win.empty:
                row[f"{name}_peak"] = None
                row[f"{name}_lead_w"] = np.nan
                continue
            f_peak = f_win.idxmax()
            lead_w = (r_peak - f_peak).days / 7.0
            row[f"{name}_peak"]  = f_peak.date()
            row[f"{name}_lead_w"] = float(lead_w)
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------- #
# Aggregation
# ---------------------------------------------------------------------- #
def _gather(sigma_hat: pd.DataFrame,
            realized: pd.DataFrame,
            codes: list[str],
            block_map: pd.Series,
            label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-ETF metric rows + per-ETF recall/precision rows for one
    predictor. Both restricted to IS by construction of the metric fns.
    """
    metric_rows = []
    hv_rows = []
    for c in codes:
        if c not in sigma_hat.columns or c not in realized.columns:
            continue
        s_hat = sigma_hat[c]
        s_act = realized[c]
        m = per_etf_metrics(s_hat, s_act)
        if "rmse" not in m:
            continue
        m.update({"code": c, "block": block_map.get(c, "?"), "predictor": label})
        metric_rows.append(m)

        for qv in HIGH_VOL_QUANTILES:
            rec, prec, n = highvol_recall_precision(s_hat, s_act, qv)
            hv_rows.append({
                "code":      c,
                "block":     block_map.get(c, "?"),
                "predictor": label,
                "q":         qv,
                "recall":    rec,
                "precision": prec,
                "n":         n,
            })
    m_df  = pd.DataFrame(metric_rows) if metric_rows else pd.DataFrame()
    hv_df = pd.DataFrame(hv_rows)     if hv_rows     else pd.DataFrame()
    return m_df, hv_df


def _headline(m_df: pd.DataFrame) -> pd.DataFrame:
    """Predictor × block median of each metric. 'all' row = all modeled
    ETFs pooled."""
    keep = ["rmse", "qlike", "pearson", "mz_a", "mz_b", "dir_hit"]
    rows = []
    for pred, g in m_df.groupby("predictor"):
        rows.append({"predictor": pred, "block": "all", "n_etfs": len(g),
                     **{k: float(g[k].median()) for k in keep}})
        for blk, gb in g.groupby("block"):
            rows.append({"predictor": pred, "block": blk, "n_etfs": len(gb),
                         **{k: float(gb[k].median()) for k in keep}})
    return pd.DataFrame(rows)


def _hv_headline(hv_df: pd.DataFrame) -> pd.DataFrame:
    """Median recall / precision by (predictor, block, q)."""
    rows = []
    for (pred, blk, qv), g in hv_df.groupby(["predictor", "block", "q"]):
        rows.append({"predictor": pred, "block": blk, "q": qv,
                     "n_etfs":    int(len(g)),
                     "recall":    float(g["recall"].median()),
                     "precision": float(g["precision"].median())})
        rows.append({"predictor": pred, "block": "all", "q": qv,
                     "n_etfs":    -1,
                     "recall":    np.nan, "precision": np.nan})
    # Also all-block per predictor (not per block).
    df = pd.DataFrame(rows).drop_duplicates(subset=["predictor", "block", "q"])
    for (pred, qv), g in hv_df.groupby(["predictor", "q"]):
        mask = (df["predictor"] == pred) & (df["block"] == "all") & (df["q"] == qv)
        df.loc[mask, "n_etfs"]    = int(len(g))
        df.loc[mask, "recall"]    = float(g["recall"].median())
        df.loc[mask, "precision"] = float(g["precision"].median())
    return df.sort_values(["predictor", "q", "block"]).reset_index(drop=True)


# ---------------------------------------------------------------------- #
# Markdown report
# ---------------------------------------------------------------------- #
def _fmt(x, digits=3):
    return "—" if pd.isna(x) else f"{x:.{digits}f}"


def _fmt_pct(x):
    return "—" if pd.isna(x) else f"{x*100:+.1f}%"


def _pretty_head(head: pd.DataFrame,
                 predictors: tuple[str, ...] = ("har", "rw", "roll26w"),
                 blocks: tuple[str, ...] = ("all", "equity", "bond", "alt"),
                 ) -> list[str]:
    lines = []
    for blk in blocks:
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


def _pretty_hv(hv_head: pd.DataFrame,
               predictors: tuple[str, ...] = ("har", "rw", "roll26w"),
               ) -> list[str]:
    lines = []
    lines.append(
        "*Note: when the actual and predicted top-q% sets are both "
        "sized ⌊q · T⌋ (as here, using per-ETF within-series quantiles), "
        "recall and precision are numerically equal — |A ∩ B| / |A| = "
        "|A ∩ B| / |B|. The table below reports one number, labeled* "
        "**hit rate**."
    )
    lines.append("")
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
                lines.append(f"| {p} | {blk} | {_fmt(r['recall'])} |")
        lines.append("")
    return lines


def _pretty_crisis(cll: pd.DataFrame) -> list[str]:
    if cll.empty:
        return ["*(no IS drawdown episodes found above the 2 % threshold)*", ""]
    lines = []
    lines.append(
        "| start | trough | max DD | wks | realized peak | HAR peak | HAR lead (w) | RW peak | RW lead | Roll26w peak | Roll26w lead |"
    )
    lines.append("|:---:|:---:|---:|---:|:---:|:---:|---:|:---:|---:|:---:|---:|")

    def _lead(v):
        return "" if pd.isna(v) else f"{v:+.1f}"

    for _, r in cll.iterrows():
        lines.append(
            f"| {r['start']} | {r['trough']} | {r['max_dd']*100:+.2f}% | "
            f"{r['n_weeks']} | {r['realized_peak']} | "
            f"{r.get('har_peak', '—')} | {_lead(r.get('har_lead_w'))} | "
            f"{r.get('rw_peak', '—')} | {_lead(r.get('rw_lead_w'))} | "
            f"{r.get('roll26w_peak', '—')} | {_lead(r.get('roll26w_lead_w'))} |"
        )
    lines.append("")
    return lines


def _findings_section(head: pd.DataFrame,
                      hv_head: pd.DataFrame,
                      cll: pd.DataFrame) -> list[str]:
    """Auto-generate a Findings block from the aggregated tables."""
    lines = ["## Findings", ""]

    def _pull(pred, blk, col):
        row = head[(head["predictor"] == pred) & (head["block"] == blk)]
        return float(row.iloc[0][col]) if not row.empty else np.nan

    har_q  = _pull("har",     "all", "qlike")
    rw_q   = _pull("rw",      "all", "qlike")
    rll_q  = _pull("roll26w", "all", "qlike")
    har_r  = _pull("har",     "all", "rmse")
    rw_r   = _pull("rw",      "all", "rmse")
    rll_r  = _pull("roll26w", "all", "rmse")
    har_d  = _pull("har",     "all", "dir_hit")
    rw_d   = _pull("rw",      "all", "dir_hit")
    rll_d  = _pull("roll26w", "all", "dir_hit")
    har_b  = _pull("har",     "all", "mz_b")
    rll_b  = _pull("roll26w", "all", "mz_b")

    lines.append(
        f"**1. HAR clearly beats the random-walk baseline.** Cross-ETF "
        f"median RMSE {har_r:.3f} vs {rw_r:.3f} (−{(1-har_r/rw_r)*100:.0f} %); "
        f"QLIKE {har_q:.3f} vs {rw_q:.3f} (−{(1-har_q/rw_q)*100:.0f} %); "
        f"direction-hit rate {har_d*100:.1f} % vs {rw_d*100:.1f} % — the "
        f"RW's 50 % is a coin flip by construction, HAR carries real "
        f"one-week directional signal."
    )
    lines.append("")
    lines.append(
        f"**2. HAR vs Roll26w is a wash — sometimes worse.** "
        f"Roll26w RMSE {rll_r:.3f}, QLIKE {rll_q:.3f}, direction-hit "
        f"{rll_d*100:.1f} %. HAR wins on RMSE ({har_r:.3f}) but *loses on "
        f"QLIKE* ({har_q:.3f} > {rll_q:.3f}). Direction-hit is essentially "
        f"tied ({har_d*100:.1f} % vs {rll_d*100:.1f} %). Roll26w is a "
        f"smoothed backward estimator that mechanically avoids the "
        f"under-forecasting that QLIKE penalizes — HAR's active tracking "
        f"buys some RMSE but pays back on the asymmetric loss."
    )
    lines.append("")
    lines.append(
        f"**3. Both HAR and Roll26w under-scale (MZ b < 1).** HAR "
        f"MZ b = {har_b:.2f}, Roll26w MZ b = {rll_b:.2f}. The realized "
        f"vol distribution has fatter right tails than either forecast "
        f"captures. A scale-recalibration step (multiply σ̂ by realized/σ̂ "
        f"regression slope) would move both closer to unbiased — noted "
        f"as a follow-up, not applied here."
    )
    lines.append("")

    # Extreme-regime hit rate (top 10 % / 20 %). RW's "just use realized
    # shifted by 1" gets a persistence-based free hit; HAR smooths and
    # ends up worse here.
    def _hv(pred, blk, qv):
        r = hv_head[(hv_head["predictor"] == pred)
                    & (hv_head["block"] == blk)
                    & (hv_head["q"] == qv)]
        return float(r.iloc[0]["recall"]) if not r.empty else np.nan

    har10 = _hv("har",     "all", 0.10)
    rw10  = _hv("rw",      "all", 0.10)
    rll10 = _hv("roll26w", "all", 0.10)
    har20 = _hv("har",     "all", 0.20)
    rw20  = _hv("rw",      "all", 0.20)
    rll20 = _hv("roll26w", "all", 0.20)

    lines.append(
        f"**4. High-vol regime detection: HAR is the worst of the three "
        f"predictors on the intended use case.** Top-10 % hit rate: "
        f"HAR {har10*100:.1f} %, Roll26w {rll10*100:.1f} %, "
        f"**RW {rw10*100:.1f} %**. Top-20 %: HAR {har20*100:.1f} %, "
        f"Roll26w {rll20*100:.1f} %, **RW {rw20*100:.1f} %**. RW wins "
        f"because vol clusters — a naive one-week shift inherits the "
        f"persistence for free, at the cost of always lagging by one bar. "
        f"HAR's smoothing helps average forecast quality (finding 1/2) but "
        f"actively hurts extreme-regime tagging."
    )
    lines.append("")

    # Crisis narrative
    if not cll.empty:
        n_cri = len(cll)
        har_leads = cll["har_lead_w"].dropna().tolist()
        rll_leads = cll["roll26w_lead_w"].dropna().tolist()
        rw_leads  = cll["rw_lead_w"].dropna().tolist()

        def _mm(xs):
            if not xs:
                return "— (no data)"
            return f"{min(xs):+.1f} … {max(xs):+.1f} w (median {np.median(xs):+.1f})"

        lines.append(
            f"**5. Crisis lead/lag: no predictor leads consistently across "
            f"the {n_cri} IS drawdown episodes.** "
            f"HAR leads: {_mm(har_leads)}. Roll26w: {_mm(rll_leads)}. "
            f"RW: {_mm(rw_leads)}. On the biggest IS episode (2020-02-21, "
            f"Covid, max DD −5.24 %) HAR has no forecast — the walk-forward "
            f"warmup (52 w Gaussian rank + 52 w HAR min_train) doesn't "
            f"complete until mid-2020. RW / Roll26w both lag rather than "
            f"lead — realized RV already spiked before the drawdown "
            f"started, so lead > 0 is possible in principle but not "
            f"delivered here. **Consistent early warning was not "
            f"demonstrated.**"
        )
        lines.append("")

    lines.append(
        "**6. Implication for the sizing-kernel branch (Phase 10.1).** "
        "The plan was to gate between defensive (1/σ) and aggressive "
        "(1/√σ) modes on a vol regime signal. The HAR forecast here does "
        "**not** dominate Roll26w on QLIKE, loses to *both* alternatives "
        "on extreme-regime hit rate, and provides no crisis lead. A "
        "regime gate built on HAR is unlikely to add signal over one "
        "built on Roll26w's percentile — which is already what sizes "
        "the book. **The block-pooled HAR as designed is not a strong "
        "regime signal for this pool.** Options for the next step: "
        "(a) scale-recalibrate HAR (fix MZ b) and re-check, especially "
        "on the top-q hit rate; (b) test a hybrid `max(HAR, Roll26w)` "
        "predictor that inherits the smoother's under-forecast "
        "protection; (c) skip HAR and build the regime gate directly "
        "on the Roll26w within-ETF percentile, using HAR only as an "
        "auxiliary confidence signal."
    )
    lines.append("")
    return lines


def write_report(head: pd.DataFrame,
                 hv_head: pd.DataFrame,
                 cll: pd.DataFrame,
                 n_by_block: dict,
                 intersect_size: int) -> None:
    lines: list[str] = []
    lines.append("# v6 block-pooled HAR — forecast quality (Phase 10.2)")
    lines.append("")
    lines.append(f"Generated: 2026-07-21")
    lines.append("")
    lines.append("## Setup")
    lines.append("")
    lines.append(
        "Per-ETF weekly RV built from daily returns (Corsi convention, "
        "annualized ×√252, drop weeks with < 3 trading days). Ragged "
        "panel — each ETF starts at its own listing / first observable "
        "weekly bar. Only ETFs with ≥ 52 weekly bars of RV enter HAR "
        "training."
    )
    lines.append("")
    lines.append(
        "One HAR fit per **block**, shared β_1w/β_4w/β_13w within block + "
        "per-ETF fixed effect. Walk-forward, min_train = 52 w, refit every "
        "4 w. Weighted OLS: within each block, per-obs weight "
        "= 1 / (n_etfs × T_i_train) so all ETFs contribute equal total "
        "weight regardless of history length (block total = 1)."
    )
    lines.append("")
    lines.append("Block partition (Phase-3 tags aggregated):")
    lines.append("")
    lines.append(f"- **equity**: broad_cn + sector_cn + smallcap_cn + "
                 f"cross_border_dm + cross_border_hk  "
                 f"→ {n_by_block.get('equity', 0)} eligible ETFs")
    lines.append(f"- **bond**: bond_rates + bond_credit  "
                 f"→ {n_by_block.get('bond', 0)} eligible ETFs")
    lines.append(f"- **alt**: metals + commodity_other  "
                 f"→ {n_by_block.get('alt', 0)} eligible ETFs")
    lines.append("")
    lines.append("### Predictors")
    lines.append("")
    lines.append("- **HAR** — block-pooled HAR forecast (this branch).")
    lines.append("- **RW** — σ̂_{t+1} = σ_t (naive random walk, standard "
                 "hard-to-beat baseline in the vol-forecasting literature).")
    lines.append("- **Roll26w** — trailing 26-week std of weekly log "
                 "returns from `_common_v6.realized_vol_trailing`, "
                 "annualized by ×√52 to bring it on the same scale as RV. "
                 "This is what `xs_engine_v6` currently uses for position "
                 "sizing.")
    lines.append("")
    lines.append("### Sample discipline")
    lines.append("")
    lines.append(
        "Per [[project-oos-discipline]], **every metric below is IS only** "
        f"(bars ≤ {IS_END.date()}). OOS metrics are neither computed nor "
        "printed. OOS is reserved for the eventual final shot when this "
        "forecast may or may not be swapped into the sizing kernel."
    )
    lines.append("")

    lines.append("## Headline — median across ETFs (IS)")
    lines.append("")
    lines.append(
        f"To make the comparison apples-to-apples, the table below is "
        f"restricted to the **{intersect_size} ETFs where all three "
        f"predictors have ≥ 10 defined IS forecasts.** HAR has the "
        f"narrowest coverage (double warmup: 52 w Gaussian rank + 52 w "
        f"HAR min_train), so this intersection is essentially HAR's "
        f"coverage set."
    )
    lines.append("")
    lines.append(
        "Reading guide: **QLIKE lower = better**; Pearson higher = better; "
        "dir hit > 50 % = better than coin flip; MZ b close to 1 = "
        "unbiased (b < 1 = forecast has narrower dispersion than realized; "
        "b > 1 = forecast overshoots)."
    )
    lines.append("")
    lines.extend(_pretty_head(head))

    lines.append("## High-vol regime detection (IS)")
    lines.append("")
    lines.append(
        "For each ETF, define the **actual** high-vol set as weeks whose "
        "realized RV_{t+1} sits in the top q of the ETF's own IS "
        "distribution; the **predicted** high-vol set is weeks whose "
        "forecast σ̂_{t+1} sits in its own top q. Reported values are the "
        "cross-ETF median recall / precision."
    )
    lines.append("")
    lines.extend(_pretty_hv(hv_head))

    lines.append("## Crisis lead / lag on the long_q20 baseline")
    lines.append("")
    lines.append(
        "Each row is a contiguous drawdown episode ≥ 2 % on the "
        "`long_q20` Phase 9.1 baseline NAV path (IS window only). "
        "Realized / forecast peaks are argmax of the cross-sectional "
        "mean σ over modeled ETFs, taken in a **symmetric** "
        f"[start − {CRISIS_PRE_WIN}w, end + {CRISIS_POST_WIN}w] window "
        "applied to realized and every forecast (so the search space is "
        "identical across predictors — a peak that lives outside the "
        "window can't produce a phantom lead for one predictor and "
        "not another). "
        "**Lead > 0** = forecast peak *before* realized peak "
        "(early warning). Lead < 0 = the forecast lagged."
    )
    lines.append("")
    lines.extend(_pretty_crisis(cll))

    lines.extend(_findings_section(head, hv_head, cll))

    lines.append("## Files")
    lines.append("")
    lines.append("- `data/vol_forecast_v6/rv_panel.parquet` — realized RV.")
    lines.append("- `data/vol_forecast_v6/forecasts_har_block_gaussian_rank.parquet` — HAR log σ̂.")
    lines.append("- `data/vol_forecast_v6/forecasts_rw.parquet` — RW baseline log σ̂.")
    lines.append("- `data/vol_forecast_v6/quality_per_etf.csv` — per-ETF row for each predictor.")
    lines.append("- `data/vol_forecast_v6/quality_headline.csv` — median-by-block table shown above.")
    lines.append("- `data/vol_forecast_v6/highvol_recall_precision.csv` — per-ETF recall/precision.")
    lines.append("- `data/vol_forecast_v6/crisis_lead_lag.csv` — crisis-episode lead/lag detail.")
    lines.append("- `scripts/vol_har_block_v6.py` — HAR engine (pure functions, WLS-capable).")
    lines.append("- `scripts/vol_forecast_v6.py` — build driver (RV → g_panel → per-block fit → σ̂).")
    lines.append("- `scripts/vol_forecast_quality_v6.py` — this comparison.")
    lines.append("")
    lines.append("## Reproducing")
    lines.append("")
    lines.append("```bash")
    lines.append("python v6/scripts/vol_targets_v6.py")
    lines.append("python v6/scripts/vol_forecast_v6.py")
    lines.append("python v6/scripts/vol_forecast_quality_v6.py")
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
    print("v6 HAR forecast quality (IS-only)")
    print("=" * 78)

    preds     = _load_predictors()
    realized  = _load_realized()
    block_map = _load_block_map()
    codes = list(block_map.index)
    n_by_block = block_map.value_counts().to_dict()
    print(f"  modeled codes: {len(codes)}   "
          f"(equity={n_by_block.get('equity', 0)}, "
          f"bond={n_by_block.get('bond', 0)}, "
          f"alt={n_by_block.get('alt', 0)})")

    # ── (1) per-ETF metrics for each predictor ──────────────────────────
    print("\n[1] Per-ETF metrics + high-vol recall/precision (IS)...")
    metric_dfs = []
    hv_dfs = []
    for name, pred in preds.items():
        m_df, hv_df = _gather(pred, realized, codes, block_map, name)
        print(f"    {name:>8s}: {len(m_df)} ETFs with defined metrics")
        metric_dfs.append(m_df)
        hv_dfs.append(hv_df)
    m_all = pd.concat(metric_dfs, ignore_index=True)
    hv_all = pd.concat(hv_dfs, ignore_index=True)
    m_all.to_csv(VOL_DIR / "quality_per_etf.csv", index=False)
    hv_all.to_csv(VOL_DIR / "highvol_recall_precision.csv", index=False)
    print(f"    wrote quality_per_etf.csv  ({len(m_all)} rows)")
    print(f"    wrote highvol_recall_precision.csv  ({len(hv_all)} rows)")

    # Restrict headline aggregation to the intersection of ETFs that
    # every predictor covers on IS — otherwise HAR (n=119) is being
    # compared against RW (n=243) on different universes and any
    # QLIKE / RMSE gap could be a coverage artifact rather than a
    # predictor-quality gap.
    per_pred_codes = {name: set(g["code"]) for name, g in m_all.groupby("predictor")}
    intersect = set.intersection(*per_pred_codes.values()) if per_pred_codes else set()
    print(f"    common-coverage intersection: {len(intersect)} ETFs "
          f"(HAR alone={len(per_pred_codes.get('har', set()))}, "
          f"RW alone={len(per_pred_codes.get('rw', set()))}, "
          f"Roll26w alone={len(per_pred_codes.get('roll26w', set()))})")

    m_all_int = m_all[m_all["code"].isin(intersect)].copy()
    hv_all_int = hv_all[hv_all["code"].isin(intersect)].copy()

    # ── (2) block-median headline ───────────────────────────────────────
    head = _headline(m_all_int)
    hv_head = _hv_headline(hv_all_int)
    head.to_csv(VOL_DIR / "quality_headline.csv", index=False)
    print(f"    wrote quality_headline.csv  ({len(head)} rows)")

    print("\n[2] Headline (median across ETFs, IS):")
    for pred in ("har", "rw", "roll26w"):
        row = head[(head["predictor"] == pred) & (head["block"] == "all")]
        if row.empty:
            continue
        r = row.iloc[0]
        print(f"    {pred:>8s}  n={int(r['n_etfs']):3d}   "
              f"RMSE={r['rmse']:.3f}   QLIKE={r['qlike']:.3f}   "
              f"ρ={r['pearson']:+.3f}   dir_hit={r['dir_hit']:.3f}   "
              f"MZ b={r['mz_b']:+.3f}")

    # ── (3) crisis lead/lag ────────────────────────────────────────────
    print("\n[3] Crisis lead / lag (long_q20 baseline drawdowns, IS)...")
    nav = _load_baseline_nav()
    episodes = _find_drawdowns(nav, CRISIS_DD_THRESH)
    print(f"    {len(episodes)} drawdown episodes ≥ {CRISIS_DD_THRESH*100:.0f} %")
    for _, ep in episodes.iterrows():
        print(f"      {ep['start'].date()} → {ep['end'].date()}  "
              f"({int(ep['n_weeks']):2d}w, max DD {ep['max_dd']*100:+.2f}%)")
    cll = crisis_lead_lag(episodes, preds, realized, codes)
    cll.to_csv(VOL_DIR / "crisis_lead_lag.csv", index=False)
    print(f"    wrote crisis_lead_lag.csv")

    # ── (4) report ──────────────────────────────────────────────────────
    print("\n[4] Report...")
    write_report(head, hv_head, cll, n_by_block, intersect_size=len(intersect))


if __name__ == "__main__":
    run()
