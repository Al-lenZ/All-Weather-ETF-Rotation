# v6 block-pooled HAR — forecast quality (Phase 10.2)

Generated: 2026-07-21

## Setup

Per-ETF weekly RV built from daily returns (Corsi convention, annualized ×√252, drop weeks with < 3 trading days). Ragged panel — each ETF starts at its own listing / first observable weekly bar. Only ETFs with ≥ 52 weekly bars of RV enter HAR training.

One HAR fit per **block**, shared β_1w/β_4w/β_13w within block + per-ETF fixed effect. Walk-forward, min_train = 52 w, refit every 4 w. Weighted OLS: within each block, per-obs weight = 1 / (n_etfs × T_i_train) so all ETFs contribute equal total weight regardless of history length (block total = 1).

Block partition (Phase-3 tags aggregated):

- **equity**: broad_cn + sector_cn + smallcap_cn + cross_border_dm + cross_border_hk  → 289 eligible ETFs
- **bond**: bond_rates + bond_credit  → 25 eligible ETFs
- **alt**: metals + commodity_other  → 7 eligible ETFs

### Predictors

- **HAR** — block-pooled HAR forecast (this branch).
- **RW** — σ̂_{t+1} = σ_t (naive random walk, standard hard-to-beat baseline in the vol-forecasting literature).
- **Roll26w** — trailing 26-week std of weekly log returns from `_common_v6.realized_vol_trailing`, annualized by ×√52 to bring it on the same scale as RV. This is what `xs_engine_v6` currently uses for position sizing.

### Sample discipline

Per [[project-oos-discipline]], **every metric below is IS only** (bars ≤ 2023-12-31). OOS metrics are neither computed nor printed. OOS is reserved for the eventual final shot when this forecast may or may not be swapped into the sizing kernel.

## Headline — median across ETFs (IS)

To make the comparison apples-to-apples, the table below is restricted to the **103 ETFs where all three predictors have ≥ 10 defined IS forecasts.** HAR has the narrowest coverage (double warmup: 52 w Gaussian rank + 52 w HAR min_train), so this intersection is essentially HAR's coverage set.

Reading guide: **QLIKE lower = better**; Pearson higher = better; dir hit > 50 % = better than coin flip; MZ b close to 1 = unbiased (b < 1 = forecast has narrower dispersion than realized; b > 1 = forecast overshoots).

### all

| predictor | n | RMSE(σ) | QLIKE | Pearson | dir hit | MZ a | MZ b |
|:---:|---:|---:|---:|---:|---:|---:|---:|
| har | 103 | 0.091 | 0.408 | 0.245 | 0.696 | 0.064 | 0.494 |
| rw | 103 | 0.122 | 0.819 | 0.347 | 0.500 | 0.137 | 0.347 |
| roll26w | 103 | 0.098 | 0.415 | 0.264 | 0.689 | 0.069 | 0.577 |

### equity

| predictor | n | RMSE(σ) | QLIKE | Pearson | dir hit | MZ a | MZ b |
|:---:|---:|---:|---:|---:|---:|---:|---:|
| har | 86 | 0.096 | 0.392 | 0.263 | 0.700 | 0.079 | 0.521 |
| rw | 86 | 0.124 | 0.778 | 0.346 | 0.500 | 0.148 | 0.342 |
| roll26w | 86 | 0.103 | 0.387 | 0.253 | 0.689 | 0.078 | 0.584 |

### bond

| predictor | n | RMSE(σ) | QLIKE | Pearson | dir hit | MZ a | MZ b |
|:---:|---:|---:|---:|---:|---:|---:|---:|
| har | 12 | 0.014 | 0.916 | 0.228 | 0.675 | 0.008 | 0.467 |
| rw | 12 | 0.017 | 3.255 | 0.372 | 0.503 | 0.014 | 0.372 |
| roll26w | 12 | 0.011 | 0.672 | 0.304 | 0.669 | 0.007 | 0.545 |

### alt

| predictor | n | RMSE(σ) | QLIKE | Pearson | dir hit | MZ a | MZ b |
|:---:|---:|---:|---:|---:|---:|---:|---:|
| har | 5 | 0.099 | 0.959 | 0.082 | 0.652 | 0.128 | 0.218 |
| rw | 5 | 0.106 | 1.191 | 0.381 | 0.531 | 0.104 | 0.381 |
| roll26w | 5 | 0.079 | 0.434 | 0.321 | 0.697 | 0.077 | 0.462 |

## High-vol regime detection (IS)

For each ETF, define the **actual** high-vol set as weeks whose realized RV_{t+1} sits in the top q of the ETF's own IS distribution; the **predicted** high-vol set is weeks whose forecast σ̂_{t+1} sits in its own top q. Reported values are the cross-ETF median recall / precision.

*Note: when the actual and predicted top-q% sets are both sized ⌊q · T⌋ (as here, using per-ETF within-series quantiles), recall and precision are numerically equal — |A ∩ B| / |A| = |A ∩ B| / |B|. The table below reports one number, labeled* **hit rate**.

### top 10 %

| predictor | block | hit rate |
|:---:|:---:|---:|
| har | all | 0.188 |
| har | equity | 0.188 |
| har | bond | 0.074 |
| har | alt | 0.077 |
| rw | all | 0.357 |
| rw | equity | 0.357 |
| rw | bond | 0.289 |
| rw | alt | 0.357 |
| roll26w | all | 0.200 |
| roll26w | equity | 0.200 |
| roll26w | bond | 0.167 |
| roll26w | alt | 0.252 |

### top 20 %

| predictor | block | hit rate |
|:---:|:---:|---:|
| har | all | 0.312 |
| har | equity | 0.312 |
| har | bond | 0.307 |
| har | alt | 0.280 |
| rw | all | 0.418 |
| rw | equity | 0.418 |
| rw | bond | 0.451 |
| rw | alt | 0.359 |
| roll26w | all | 0.333 |
| roll26w | equity | 0.325 |
| roll26w | bond | 0.375 |
| roll26w | alt | 0.359 |

## Crisis lead / lag on the long_q20 baseline

Each row is a contiguous drawdown episode ≥ 2 % on the `long_q20` Phase 9.1 baseline NAV path (IS window only). Realized / forecast peaks are argmax of the cross-sectional mean σ over modeled ETFs, taken in a **symmetric** [start − 8w, end + 4w] window applied to realized and every forecast (so the search space is identical across predictors — a peak that lives outside the window can't produce a phantom lead for one predictor and not another). **Lead > 0** = forecast peak *before* realized peak (early warning). Lead < 0 = the forecast lagged.

| start | trough | max DD | wks | realized peak | HAR peak | HAR lead (w) | RW peak | RW lead | Roll26w peak | Roll26w lead |
|:---:|:---:|---:|---:|:---:|:---:|---:|:---:|---:|:---:|---:|
| 2020-02-21 | 2020-03-13 | -5.24% | 9 | 2020-02-07 | None |  | 2020-02-14 | -1.0 | 2020-05-08 | -13.0 |
| 2020-08-28 | 2020-10-02 | -2.68% | 12 | 2020-07-10 | 2020-11-20 | -19.0 | 2020-07-17 | -1.0 | 2020-08-14 | -5.0 |
| 2021-12-31 | 2022-11-11 | -2.20% | 74 | 2022-04-29 | 2022-05-13 | -2.0 | 2022-05-13 | -2.0 | 2022-07-01 | -9.0 |

## Findings

**1. HAR clearly beats the random-walk baseline.** Cross-ETF median RMSE 0.091 vs 0.122 (−25 %); QLIKE 0.408 vs 0.819 (−50 %); direction-hit rate 69.6 % vs 50.0 % — the RW's 50 % is a coin flip by construction, HAR carries real one-week directional signal.

**2. HAR vs Roll26w is a wash — sometimes worse.** Roll26w RMSE 0.098, QLIKE 0.415, direction-hit 68.9 %. HAR wins on RMSE (0.091) but *loses on QLIKE* (0.408 > 0.415). Direction-hit is essentially tied (69.6 % vs 68.9 %). Roll26w is a smoothed backward estimator that mechanically avoids the under-forecasting that QLIKE penalizes — HAR's active tracking buys some RMSE but pays back on the asymmetric loss.

**3. Both HAR and Roll26w under-scale (MZ b < 1).** HAR MZ b = 0.49, Roll26w MZ b = 0.58. The realized vol distribution has fatter right tails than either forecast captures. A scale-recalibration step (multiply σ̂ by realized/σ̂ regression slope) would move both closer to unbiased — noted as a follow-up, not applied here.

**4. High-vol regime detection: HAR is the worst of the three predictors on the intended use case.** Top-10 % hit rate: HAR 18.8 %, Roll26w 20.0 %, **RW 35.7 %**. Top-20 %: HAR 31.2 %, Roll26w 33.3 %, **RW 41.8 %**. RW wins because vol clusters — a naive one-week shift inherits the persistence for free, at the cost of always lagging by one bar. HAR's smoothing helps average forecast quality (finding 1/2) but actively hurts extreme-regime tagging.

**5. Crisis lead/lag: no predictor leads consistently across the 3 IS drawdown episodes.** HAR leads: -19.0 … -2.0 w (median -10.5). Roll26w: -13.0 … -5.0 w (median -9.0). RW: -2.0 … -1.0 w (median -1.0). On the biggest IS episode (2020-02-21, Covid, max DD −5.24 %) HAR has no forecast — the walk-forward warmup (52 w Gaussian rank + 52 w HAR min_train) doesn't complete until mid-2020. RW / Roll26w both lag rather than lead — realized RV already spiked before the drawdown started, so lead > 0 is possible in principle but not delivered here. **Consistent early warning was not demonstrated.**

**6. Implication for the sizing-kernel branch (Phase 10.1).** The plan was to gate between defensive (1/σ) and aggressive (1/√σ) modes on a vol regime signal. The HAR forecast here does **not** dominate Roll26w on QLIKE, loses to *both* alternatives on extreme-regime hit rate, and provides no crisis lead. A regime gate built on HAR is unlikely to add signal over one built on Roll26w's percentile — which is already what sizes the book. **The block-pooled HAR as designed is not a strong regime signal for this pool.** Options for the next step: (a) scale-recalibrate HAR (fix MZ b) and re-check, especially on the top-q hit rate; (b) test a hybrid `max(HAR, Roll26w)` predictor that inherits the smoother's under-forecast protection; (c) skip HAR and build the regime gate directly on the Roll26w within-ETF percentile, using HAR only as an auxiliary confidence signal.

## Files

- `data/vol_forecast_v6/rv_panel.parquet` — realized RV.
- `data/vol_forecast_v6/forecasts_har_block_gaussian_rank.parquet` — HAR log σ̂.
- `data/vol_forecast_v6/forecasts_rw.parquet` — RW baseline log σ̂.
- `data/vol_forecast_v6/quality_per_etf.csv` — per-ETF row for each predictor.
- `data/vol_forecast_v6/quality_headline.csv` — median-by-block table shown above.
- `data/vol_forecast_v6/highvol_recall_precision.csv` — per-ETF recall/precision.
- `data/vol_forecast_v6/crisis_lead_lag.csv` — crisis-episode lead/lag detail.
- `scripts/vol_har_block_v6.py` — HAR engine (pure functions, WLS-capable).
- `scripts/vol_forecast_v6.py` — build driver (RV → g_panel → per-block fit → σ̂).
- `scripts/vol_forecast_quality_v6.py` — this comparison.

## Reproducing

```bash
python v6/scripts/vol_targets_v6.py
python v6/scripts/vol_forecast_v6.py
python v6/scripts/vol_forecast_quality_v6.py
```
