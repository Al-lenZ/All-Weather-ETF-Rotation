"""v6/leverage/sigma_est_diag.py — M0-B standalone σ_est diagnostic.

Compares four σ estimators on the unlevered two-layer book, for both the
base and EW risk-budget variants, against a forward-realized truth proxy.

Why this exists (PLAN §四.D2, §四.D3, §10 M0-B)
--------------------------------------------------
- On the leverage path we need one σ estimator to compute weekly L_t.
- The choice affects L_t materially: an under-biased estimator overshoots L,
  a mismatched-frequency estimator (daily × √252) systematically under-
  estimates for serially-correlated bond returns.
- The "which estimator is unbiased" question is separable from and prior to
  the leverage decision. We answer it here first, then plug the winner into
  ``leverage_engine.py``.

Ratio ``σ_est_t / σ_realized_t`` mean is expected within ``[0.9, 1.1]`` to
qualify. Estimator with the tightest mean-abs-deviation from 1.0 across
IS wins, tiebreaker = smallest σ of the ratio.

Outputs
-------
    data/leverage/_sigma_est_diag/
        ratio_<rb>_<estimator>.csv     — weekly ratio time-series
        book_ret_<rb>.csv              — weekly + daily book returns used
        summary.csv                    — one row per (rb, estimator) with
                                         is_mean, is_mad_from_1, is_std,
                                         oos_mean, oos_mad_from_1, oos_std,
                                         qualifies (bool)
        WINNER.md                      — recommended estimator + rationale

Run
---
    python v6/leverage/sigma_est_diag.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import _common_leverage as CL

# these come via _common_leverage's path preamble
# --- v6/common sys.path bootstrap ---
import sys as _v6_sys
from pathlib import Path as _V6Path
_v6_p = _V6Path(__file__).resolve().parent
while _v6_p.name != "v6" and _v6_p.parent != _v6_p:
    _v6_p = _v6_p.parent
_v6_sys.path.insert(0, str(_v6_p / "common"))
del _v6_p
# --------------------------------------
import block_composite_v6 as BC
import block_risk_budget_v6 as BR
import block_two_layer_v6 as TL
import xs_engine_v6 as E

import vol_estimators as VE


# ---------------------------------------------------------------------- #
# Book weights per RB variant
# ---------------------------------------------------------------------- #
def _build_w_name(shared: dict,
                  alpha_scores: dict[str, pd.DataFrame],
                  policy_shares: dict[str, float]) -> pd.DataFrame:
    """Reproduce block_two_layer_v6.run_variant's aggregation, forcing a
    specific ``policy_shares`` into the layer-1 solver.

    Matches exp1_risk_budget_sensitivity_v6.run_with_shares — no changes."""
    # Finalist q=0.20, ε=0.30 per Phase 12×13 lock.
    comp = TL.build_composites_two_layer(shared, 0.20, 0.30, alpha_scores)
    R = comp["returns"][list(BC.GROUP_ORDER)]
    trend = pd.DataFrame(True, index=R.index, columns=R.columns)
    W_group, _, _ = BR.build_block_weights(R, trend, TL.BUDGET_METHOD, policy_shares)
    frames = []
    for grp in BC.GROUP_ORDER:
        Wg = comp["weights_group"][grp]
        if Wg.shape[1] == 0:
            continue
        scale = W_group[grp].reindex(Wg.index).fillna(0.0)
        frames.append(Wg.mul(scale, axis=0))
    W_name = pd.concat(frames, axis=1) if frames else pd.DataFrame(index=R.index)
    return W_name


# ---------------------------------------------------------------------- #
# Book return construction
# ---------------------------------------------------------------------- #
def _weekly_book_ret(W_name: pd.DataFrame, fwd_1w: pd.DataFrame) -> pd.Series:
    """Weekly gross book return = Σ w[t] × fwd_1w[t]. No cost — this is a
    σ measurement, cost drag doesn't belong in it."""
    idx = W_name.index.intersection(fwd_1w.index)
    W = W_name.reindex(idx).fillna(0.0)
    F = fwd_1w.reindex(idx)[W.columns].fillna(0.0)
    return (W * F).sum(axis=1).rename("weekly_book_ret")


def _daily_book_ret(W_name: pd.DataFrame, px_daily_wide: pd.DataFrame
                    ) -> pd.Series:
    """Daily gross book return.

    Convention: xs_engine's ``fwd_1w[t] = r(t → t+1)``. So daily returns
    on trading days d ∈ (t_k, t_{k+1}] are earned by weights ``W[t_k]``.
    We build this by pushing W's Friday index one business day forward
    (so W[t] labels the next Monday) then ffill onto the daily index.
    """
    tickers = [c for c in W_name.columns if c in px_daily_wide.columns]
    W = W_name[tickers].copy()
    px = px_daily_wide[tickers].sort_index()
    daily_ret = px.pct_change()
    W_shifted = W.copy()
    W_shifted.index = pd.DatetimeIndex(
        [t + pd.tseries.offsets.BDay(1) for t in W.index]
    )
    W_daily = (W_shifted.reindex(daily_ret.index, method="ffill")
                        .fillna(0.0))
    daily_book = (W_daily * daily_ret).sum(axis=1)
    daily_book = daily_book.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return daily_book.rename("daily_book_ret")


# ---------------------------------------------------------------------- #
# Estimator ratio per RB
# ---------------------------------------------------------------------- #
def _run_estimators(weekly_ret: pd.Series, daily_ret: pd.Series
                    ) -> pd.DataFrame:
    """One row per weekly bar, one column per estimator. Daily estimators
    are computed on the daily series then sampled at the weekly (Friday)
    index."""
    weekly_idx = weekly_ret.index
    out = {}
    for name, (freq, fn) in VE.ESTIMATORS.items():
        if freq == "weekly":
            s = fn(weekly_ret)
            out[name] = s.reindex(weekly_idx)
        else:
            s = fn(daily_ret)
            out[name] = s.reindex(weekly_idx, method="ffill")
    return pd.DataFrame(out)


def _summarize(sigma_est: pd.Series,
               weekly_ret: pd.Series,
               is_end, oos_start, oos_end) -> dict:
    """Two families of stats:

    1. **Aggregate ratio.** ``mean(σ_est_t)`` over window vs
       ``std(weekly_ret_t) × √52`` over the same window. Robust to the
       per-bar right skew that swamps ``σ_realized_4w`` (a 4-week window is
       too short and often catches calm periods → per-bar ratio blows up
       even when the estimator is well calibrated). This is the primary
       calibration metric for the leverage engine.

    2. **Per-bar forward-realized ratio.** ``σ_est_t / σ_realized_4w_t`` and
       ``σ_est_t / σ_realized_13w_t``. p50 / p95 diagnostics for shape.
    """
    # Aggregate ratios
    def _agg(est: pd.Series, r: pd.Series, tag: str) -> dict:
        est = est.dropna()
        r   = r.dropna()
        if len(est) < 8 or len(r) < 8:
            return {f"{tag}_agg_est":  np.nan, f"{tag}_agg_realized": np.nan,
                    f"{tag}_agg_ratio": np.nan, f"{tag}_n_est": len(est)}
        est_mean = float(est.mean())
        realized_ann = float(r.std(ddof=1) * np.sqrt(VE.WEEKS_PER_YEAR))
        return {f"{tag}_agg_est":      est_mean,
                f"{tag}_agg_realized": realized_ann,
                f"{tag}_agg_ratio":    (est_mean / realized_ann
                                        if realized_ann > 0 else np.nan),
                f"{tag}_n_est":        int(len(est))}

    def _per_bar(ratio: pd.Series, tag: str) -> dict:
        r = ratio.replace([np.inf, -np.inf], np.nan).dropna()
        if len(r) < 4:
            return {f"{tag}_mean": np.nan, f"{tag}_p50": np.nan,
                    f"{tag}_p95": np.nan}
        return {f"{tag}_mean": float(r.mean()),
                f"{tag}_p50":  float(r.quantile(0.5)),
                f"{tag}_p95":  float(r.quantile(0.95))}

    is_mask  = sigma_est.index <= is_end
    oos_mask = (sigma_est.index >= oos_start) & (sigma_est.index <= oos_end)

    est_is  = sigma_est[is_mask]
    est_oos = sigma_est[oos_mask]
    ret_is  = weekly_ret[weekly_ret.index <= is_end]
    ret_oos = weekly_ret[(weekly_ret.index >= oos_start)
                         & (weekly_ret.index <= oos_end)]

    r4_is  = est_is  / VE.realized_forward_ann(weekly_ret, horizon_weeks=4).reindex(est_is.index)
    r13_is = est_is  / VE.realized_forward_ann(weekly_ret, horizon_weeks=13).reindex(est_is.index)
    r4_oos = est_oos / VE.realized_forward_ann(weekly_ret, horizon_weeks=4).reindex(est_oos.index)
    r13_oos = est_oos / VE.realized_forward_ann(weekly_ret, horizon_weeks=13).reindex(est_oos.index)

    d: dict = {}
    d.update(_agg(est_is,  ret_is,  "is"))
    d.update(_agg(est_oos, ret_oos, "oos"))
    d.update(_per_bar(r4_is,  "is_fwd4"))
    d.update(_per_bar(r13_is, "is_fwd13"))
    d.update(_per_bar(r4_oos, "oos_fwd4"))
    d.update(_per_bar(r13_oos, "oos_fwd13"))
    is_agg = d.get("is_agg_ratio", np.nan)
    d["qualifies"] = bool(not np.isnan(is_agg) and 0.9 <= is_agg <= 1.1)
    return d


# ---------------------------------------------------------------------- #
# Main
# ---------------------------------------------------------------------- #
def main() -> None:
    out_dir: Path = CL.LEV_SIGMA_EST_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    print("--- M0-B σ_est standalone diagnostic ---")
    print(f"out: {out_dir}")
    print("[data] loading shared + composites (may take a minute)...")
    shared = BC.load_shared()
    alpha_scores = TL.build_alpha_scores(shared)
    fwd_1w = shared["fwd_1w"]

    # daily prices — use the unified panel
    print("[data] loading px_daily panel...")
    px_long = pd.read_parquet(CL.DATA_DIR / "universe_v6" / "px_daily.parquet")
    px_wide = (px_long.pivot(index="date", columns="code", values="close")
                       .sort_index())

    rb_map = {"base": CL.POLICY_SHARES_BASE, "ew": CL.POLICY_SHARES_EW}
    rows: list[dict] = []
    for rb_tag, shares in rb_map.items():
        print(f"\n[rb={rb_tag}] building W_name...")
        W = _build_w_name(shared, alpha_scores, shares)
        wk_ret = _weekly_book_ret(W, fwd_1w)
        dy_ret = _daily_book_ret(W, px_wide)

        # persist raw book returns
        wk_ret.to_frame().to_csv(out_dir / f"weekly_book_ret_{rb_tag}.csv")
        dy_ret.to_frame().to_csv(out_dir / f"daily_book_ret_{rb_tag}.csv")

        est_df = _run_estimators(wk_ret, dy_ret)
        realized = VE.realized_forward_ann(
            wk_ret, horizon_weeks=CL.SIGMA_EST_HORIZON_WEEKS,
        )

        realized_fwd13 = VE.realized_forward_ann(wk_ret, horizon_weeks=13)
        for est_name in est_df.columns:
            frame = pd.DataFrame({
                "sigma_est":       est_df[est_name],
                "sigma_real_fwd4": realized,
                "sigma_real_fwd13": realized_fwd13,
                "ratio_fwd4":      est_df[est_name] / realized,
                "ratio_fwd13":     est_df[est_name] / realized_fwd13,
            })
            frame.to_csv(out_dir / f"ratio_{rb_tag}_{est_name}.csv")
            d = _summarize(est_df[est_name], wk_ret,
                           CL.IN_SAMPLE_END, CL.OOS_START, CL.OOS_END)
            d["rb"] = rb_tag
            d["estimator"] = est_name
            rows.append(d)
            print(f"  {est_name:>20s}: "
                  f"IS agg est {d['is_agg_est']*100:5.2f}% "
                  f"realized {d['is_agg_realized']*100:5.2f}% "
                  f"→ ratio {d['is_agg_ratio']:.3f}  "
                  f"| fwd13 p50 {d.get('is_fwd13_p50', float('nan')):.3f}  "
                  f"| OOS agg ratio {d['oos_agg_ratio']:.3f}")

    summary = pd.DataFrame(rows).set_index(["rb", "estimator"])
    summary.to_csv(out_dir / "summary.csv")

    # Winner selection: |is_agg_ratio − 1| averaged across RBs, tiebreak by |oos_agg_ratio − 1|.
    ranking = (summary.reset_index()
                       .assign(is_abs_dev=lambda d: (d["is_agg_ratio"] - 1.0).abs(),
                               oos_abs_dev=lambda d: (d["oos_agg_ratio"] - 1.0).abs())
                       .groupby("estimator")
                       .agg(is_abs_dev=("is_abs_dev", "mean"),
                            oos_abs_dev=("oos_abs_dev", "mean"),
                            all_qualify=("qualifies", "all")))
    ranking = ranking.sort_values(["all_qualify", "is_abs_dev", "oos_abs_dev"],
                                   ascending=[False, True, True])
    winner = ranking.index[0]
    print(f"\n[winner] {winner}  "
          f"|IS-1|={ranking.loc[winner, 'is_abs_dev']:.3f}  "
          f"|OOS-1|={ranking.loc[winner, 'oos_abs_dev']:.3f}  "
          f"qualifies_both={ranking.loc[winner, 'all_qualify']}")

    winner_md = out_dir / "WINNER.md"
    winner_md.write_text(
        "# M0-B σ_est diagnostic — WINNER\n\n"
        f"**Winner:** `{winner}` (recommendation for leverage_engine.py).\n\n"
        "Selection metric: smallest `|is_agg_ratio − 1|` averaged across RBs "
        "(base, EW). Aggregate ratio = mean σ_est over IS ÷ realized σ of "
        "weekly book returns over the same IS × √52. Robust to per-bar right "
        "skew from 4-week forward std (individual 4w windows are noisy).\n\n"
        "## Ranking (avg across RB = base, EW)\n\n"
        "| Estimator | |IS agg ratio − 1| | |OOS agg ratio − 1| | qualifies (both RB, IS ∈ [0.9, 1.1]) |\n"
        "|---|---:|---:|:---:|\n" +
        "\n".join(
            f"| `{e}` | {ranking.loc[e, 'is_abs_dev']:.3f} | "
            f"{ranking.loc[e, 'oos_abs_dev']:.3f} | "
            f"{'yes' if ranking.loc[e, 'all_qualify'] else 'no'} |"
            for e in ranking.index
        ) + "\n\n"
        "## Per (RB, estimator) summary\n\n"
        + summary.round(3).to_markdown() + "\n\n"
        "## Interpretation\n\n"
        "**Aggregate ratio.** `mean(σ_est) / realized_ann`. Ratio > 1 → σ_est "
        "over-estimates → L_t too low → book under-invested vs σ*. Ratio < 1 "
        "→ σ_est under-estimates → L_t too high → book realizes vol > σ*. "
        "Qualification band [0.9, 1.1] per PLAN §10 M0-B.\n\n"
        "**Per-bar forward ratios** (`fwd4`, `fwd13`). `fwd4` is noisy — 4w "
        "windows often catch calm periods, inflating the per-bar ratio "
        "distribution. `fwd13` is the standard quarterly realized-vol horizon "
        "and gives a cleaner shape but eats 13 weeks of tail. Both reported "
        "as diagnostics; **aggregate ratio drives the winner pick.**\n\n"
        "**Frequency-mismatch bias (§四.D2).** Compare `daily_ewma_252` vs "
        "`weekly_ewma_52` on the same RB: gap size tells us how much the "
        "daily×√252 convention was under- or over-shooting due to serial "
        "correlation in bond returns.\n"
    )
    print(f"\nwrote {winner_md}")


if __name__ == "__main__":
    main()
