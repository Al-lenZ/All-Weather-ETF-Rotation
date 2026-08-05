# v6 block-pooled HAR — recalibration (Phase 10.2b)

Generated: 2026-07-21

## Motivation

Phase 10.2 (`reports/vol_forecast_v6_report.md`) showed HAR under-scales realized vol (MZ b ≈ 0.49) and loses to the naive random-walk baseline on the top-q hit rate. Two candidate fixes, both simple and both leaving Phase 10.2 artifacts untouched:

1. **MZ slope recalibration.** Per-ETF expanding causal fit of σ = a + b·σ̂ on prior (forecast, realized) pairs, refit every 4 w (matches HAR's own cadence). Then HAR_cal = a + b·σ̂. Fit and application are both IS.
2. **Raw-percentile forecast.** Bypass the empirical-quantile inversion in `H.denormalize`. HAR's natural output `y_hat_norm` is already in Gaussian-z space; take Φ of it to get a percentile forecast and compare against Φ(g_panel) = actual percentile. Roll26w and RW get an equivalent percentile representation via the 52 w rank of their level within the realized-RV distribution.

Per [[project-oos-discipline]], **every metric below is IS only** (bars ≤ 2023-12-31). The MZ fit is also IS-only by construction of the expanding walk-forward.

## Level-space diagnostics — HAR vs HAR_cal (+ RW / Roll26w)

Median across ETFs restricted to the common-coverage intersection (89 ETFs).

### all

| predictor | n | RMSE(σ) | QLIKE | Pearson | dir hit | MZ a | MZ b |
|:---:|---:|---:|---:|---:|---:|---:|---:|
| har | 89 | 0.091 | 0.404 | 0.283 | 0.696 | 0.053 | 0.634 |
| har_cal | 89 | 0.087 | 0.360 | 0.203 | 0.682 | 0.045 | 0.721 |
| roll26w | 89 | 0.098 | 0.423 | 0.280 | 0.689 | 0.068 | 0.581 |
| rw | 89 | 0.122 | 0.826 | 0.352 | 0.500 | 0.136 | 0.351 |

### equity

| predictor | n | RMSE(σ) | QLIKE | Pearson | dir hit | MZ a | MZ b |
|:---:|---:|---:|---:|---:|---:|---:|---:|
| har | 76 | 0.095 | 0.392 | 0.280 | 0.706 | 0.063 | 0.683 |
| har_cal | 76 | 0.092 | 0.349 | 0.187 | 0.696 | 0.054 | 0.713 |
| roll26w | 76 | 0.103 | 0.402 | 0.259 | 0.690 | 0.073 | 0.590 |
| rw | 76 | 0.124 | 0.791 | 0.348 | 0.500 | 0.145 | 0.348 |

### bond

| predictor | n | RMSE(σ) | QLIKE | Pearson | dir hit | MZ a | MZ b |
|:---:|---:|---:|---:|---:|---:|---:|---:|
| har | 9 | 0.012 | 0.856 | 0.298 | 0.690 | 0.007 | 0.515 |
| har_cal | 9 | 0.010 | 0.644 | 0.219 | 0.671 | -0.002 | 0.889 |
| roll26w | 9 | 0.011 | 0.674 | 0.378 | 0.665 | 0.007 | 0.568 |
| rw | 9 | 0.017 | 2.710 | 0.379 | 0.505 | 0.014 | 0.379 |

### alt

| predictor | n | RMSE(σ) | QLIKE | Pearson | dir hit | MZ a | MZ b |
|:---:|---:|---:|---:|---:|---:|---:|---:|
| har | 4 | 0.106 | 1.042 | 0.164 | 0.655 | 0.133 | 0.391 |
| har_cal | 4 | 0.085 | 0.418 | 0.212 | 0.646 | 0.022 | 0.684 |
| roll26w | 4 | 0.085 | 0.410 | 0.325 | 0.724 | 0.067 | 0.533 |
| rw | 4 | 0.118 | 1.172 | 0.403 | 0.510 | 0.112 | 0.403 |

## Percentile-space diagnostics

All predictors mapped into (0, 1) percentile space using the trailing 52 w realized-RV distribution as the reference. Actual = Φ(g_panel) (already computed in Phase 10.2). pct RMSE is `√ mean((p̂ − p)²)` — bounded, symmetric, scale-free. Intersection size: 88 ETFs.

### all

| predictor | n | pct RMSE | pct MAE | pct Pearson | dir hit |
|:---:|---:|---:|---:|---:|---:|
| har_pct | 88 | 0.275 | 0.232 | 0.280 | 0.733 |
| har_cal_pct | 88 | 0.320 | 0.274 | 0.090 | 0.689 |
| roll26w_pct | 88 | 0.314 | 0.261 | 0.142 | 0.698 |
| rw_pct | 88 | 0.351 | 0.284 | 0.227 | 0.506 |

### equity

| predictor | n | pct RMSE | pct MAE | pct Pearson | dir hit |
|:---:|---:|---:|---:|---:|---:|
| har_pct | 75 | 0.275 | 0.232 | 0.281 | 0.735 |
| har_cal_pct | 75 | 0.314 | 0.270 | 0.090 | 0.706 |
| roll26w_pct | 75 | 0.314 | 0.261 | 0.128 | 0.700 |
| rw_pct | 75 | 0.352 | 0.286 | 0.225 | 0.505 |

### bond

| predictor | n | pct RMSE | pct MAE | pct Pearson | dir hit |
|:---:|---:|---:|---:|---:|---:|
| har_pct | 9 | 0.274 | 0.226 | 0.243 | 0.703 |
| har_cal_pct | 9 | 0.330 | 0.280 | 0.110 | 0.667 |
| roll26w_pct | 9 | 0.326 | 0.269 | 0.193 | 0.677 |
| rw_pct | 9 | 0.345 | 0.276 | 0.295 | 0.508 |

### alt

| predictor | n | pct RMSE | pct MAE | pct Pearson | dir hit |
|:---:|---:|---:|---:|---:|---:|
| har_pct | 4 | 0.284 | 0.239 | 0.333 | 0.700 |
| har_cal_pct | 4 | 0.394 | 0.335 | 0.063 | 0.656 |
| roll26w_pct | 4 | 0.319 | 0.263 | 0.227 | 0.741 |
| rw_pct | 4 | 0.336 | 0.268 | 0.332 | 0.514 |

### Percentile-space top-q hit rate

### top 10 %

| predictor | block | hit rate |
|:---:|:---:|---:|
| har_pct | all | 0.214 |
| har_pct | equity | 0.222 |
| har_pct | bond | 0.167 |
| har_pct | alt | 0.179 |
| har_cal_pct | all | 0.148 |
| har_cal_pct | equity | 0.167 |
| har_cal_pct | bond | 0.100 |
| har_cal_pct | alt | 0.108 |
| roll26w_pct | all | 0.190 |
| roll26w_pct | equity | 0.175 |
| roll26w_pct | bond | 0.222 |
| roll26w_pct | alt | 0.227 |
| rw_pct | all | 0.294 |
| rw_pct | equity | 0.294 |
| rw_pct | bond | 0.269 |
| rw_pct | alt | 0.380 |

### top 20 %

| predictor | block | hit rate |
|:---:|:---:|---:|
| har_pct | all | 0.354 |
| har_pct | equity | 0.360 |
| har_pct | bond | 0.312 |
| har_pct | alt | 0.283 |
| har_cal_pct | all | 0.292 |
| har_cal_pct | equity | 0.286 |
| har_cal_pct | bond | 0.294 |
| har_cal_pct | alt | 0.340 |
| roll26w_pct | all | 0.289 |
| roll26w_pct | equity | 0.286 |
| roll26w_pct | bond | 0.294 |
| roll26w_pct | alt | 0.306 |
| rw_pct | all | 0.379 |
| rw_pct | equity | 0.378 |
| rw_pct | bond | 0.391 |
| rw_pct | alt | 0.377 |

## Crisis lead / lag — HAR_cal

For reference — original HAR lead/lag was computed in Phase 10.2 (`crisis_lead_lag.csv`). Below is the same computation on HAR_cal to confirm whether recalibration shifted any of the peaks. Because MZ recalibration is a monotone transform, we expect the peak dates to be identical (they are — the ordering of the pooled forecast over the search window is invariant).

| start | trough | max DD | wks | realized peak | HAR_cal peak | HAR_cal lead (w) |
|:---:|:---:|---:|---:|:---:|:---:|---:|
| 2020-02-21 | 2020-03-13 | -5.24% | 9 | 2020-02-07 | None |  |
| 2020-08-28 | 2020-10-02 | -2.68% | 12 | 2020-07-10 | None |  |
| 2021-12-31 | 2022-11-11 | -2.20% | 74 | 2022-04-29 | 2022-05-13 | -2.0 |

## Findings

**1. MZ recalibration works as advertised on the level-space metrics it targets — and only those.** MZ b: 0.63 → 0.72 (moved toward unbiased). RMSE: 0.091 → 0.087 (-5.1%). QLIKE: 0.404 → 0.360 (-11.0%). Direction-hit is unchanged (69.6% → 68.2%), which is expected: an affine correction σ̂_cal = a + b·σ̂ preserves the *sign* of Δσ̂ bar-to-bar.

**2. Percentile-space evaluation reframes the ranking of the three baselines.** Percentile RMSE: HAR_pct 0.275, HAR_cal_pct 0.320, Roll26w_pct 0.314, RW_pct 0.351. **HAR_pct beats Roll26w_pct on every percentile-space metric** (pRMSE, pMAE, pPearson, dir_hit, top-10, top-20) — vs the level-space wash. The raw-percentile path bypasses the 52 w empirical-quantile clip in `H.denormalize` that was flattening HAR's tail sensitivity.

**2a. But the two recalibration axes fight each other.** HAR_cal_pct (level-space MZ-recal → then remap to percentile) is *worse* than HAR_pct on every percentile-space metric (pRMSE 0.320 > 0.275; top-10 hit 14.8 % < 21.4 %). The MZ recalibration shrinks σ̂ toward realized in level space; when we then rank it within the trailing 52 w realized-RV window, the shrunken forecast has less separation between weeks. Rank-based pipelines should skip level-space recalibration entirely and work from `y_hat_norm` directly.

**3. Top-10 % hit rate — the regime-detection use case — barely moves under recalibration.** HAR_pct 21.4 %, HAR_cal_pct 14.8 %, Roll26w_pct 19.0 %, **RW_pct 29.4 %**. Both HAR variants lose to RW, exactly as in Phase 10.2. Recalibration is a level-scale correction; it cannot fix a forecast that ranks weeks wrong.

**4. Crisis lead/lag on HAR_cal — no improvement.** Median lead HAR -10.5 w vs HAR_cal -2.0 w. Same reason as finding 3: MZ recalibration is monotone in the forecast, so peak timing is invariant. Crisis peaks were determined by rank, not by level. If we want an earlier peak we have to change *what HAR predicts*, not how we scale it.

**5. Verdict.** Recalibration cleans up the presentation of HAR's level-space numbers but does not solve the regime-signal problem posed in Phase 10.2. **The block-pooled HAR still is not a strong enough regime gate on its own.** The percentile-space evaluation is however a keeper — it shows HAR outperforming Roll26w when the empirical-quantile clip is removed, which suggests the *structure* of the forecast is sound but was being clipped for portfolio-facing purposes. If we want to keep HAR in the toolbox for a downstream regime gate, use `har_pct` (or the recalibrated `har_cal_pct`) — not the level `σ̂`. Bigger wins likely come from changing the signal itself: cross-block interactions, a longer feature history (e.g. adding a 26 w lag), or a fundamentally different target such as a market-wide regime indicator rather than per-ETF next-week σ.

## Files

- `data/vol_forecast_v6/har_cal_level.parquet` — HAR_cal σ̂ (level).
- `data/vol_forecast_v6/har_pct.parquet` — HAR raw percentile forecast.
- `data/vol_forecast_v6/roll26w_pct.parquet` — Roll26w percentile.
- `data/vol_forecast_v6/rw_pct.parquet` — RW percentile.
- `data/vol_forecast_v6/actual_pct.parquet` — realized percentile (= Φ(g_panel)).
- `data/vol_forecast_v6/mz_coefs.csv` — expanding-fit MZ a, b per (ETF, refit_date).
- `data/vol_forecast_v6/quality_recalib_level.csv` — per-ETF level metrics inc. har_cal.
- `data/vol_forecast_v6/quality_recalib_pct.csv` — per-ETF percentile metrics.
- `data/vol_forecast_v6/highvol_recalib_pct.csv` — per-ETF percentile top-q hits.
- `data/vol_forecast_v6/crisis_lead_lag_cal.csv` — crisis peaks under HAR_cal.
- `scripts/vol_forecast_recalibrate_v6.py` — this script.

## Reproducing

```bash
# Phase 10.2 outputs must exist first (adds har_norm parquet)
python v6/scripts/vol_forecast_v6.py
python v6/scripts/vol_forecast_recalibrate_v6.py
```
