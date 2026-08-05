# Phase 8.2 — equal-weight baseline (v6)

Naive baseline: per-bar mean of the sign-oriented row-z-scored raw α panels across a shortlist of Phase 7 survivors. No fitting, no per-factor weight. **This is what the future return model must beat.**

**Ensembling**: row-z of raw α (v6 convention, matches `xs_screen_v6.build_ensemble_alpha`). The v4pool convention averaged stage-2 CS-rank panels; Phase 9.1's `diagnose_ensemble_v6.py` showed on the v6 pool that rank-averaging destroys conviction and produces high-turnover, low-Sharpe books. Row-z keeps magnitude structure.

IS / OOS here are calendar splits at 2023-12-31 — with no fitting, IS is not a 'training' window and OOS is not 'held out' in the usual sense; they are same-regime and shifted-regime evaluation windows respectively.

## Variants

- **dedup_v6** (28): `alpha_071`, `cvar5_60`, `wq_052`, `alpha015`, `alpha_062`, `alpha028`, `alpha_081`, `alpha_060`, `alpha_187`, `wq_021`⁻, `alpha_170`, `alpha_002`⁻, `alpha_012`⁻, `alpha030`, `wq_034`⁻, `alpha006`⁻, `wq_027`⁻, `wq_032`, `wq_088`, `wq_096`, `wq_039`, `wq_003`, `wq_060`⁻, `wq_058`⁻, `alpha021`⁻, `wq_056`, `alpha_165`⁻, `wq_016`⁻
- **stability_v6** (5): `alpha_071`, `alpha015`, `alpha028`, `alpha_081`, `wq_027`⁻

## A. Alpha diagnostics

Per-bar Spearman IC vs ỹ + prec@q at q = 0.10. Ragged `zstat = mean(ic·√(N-1)) · √T` is the primary metric.

| variant | period | n_bars | mean_ic | zstat | mean_ic_w | mean_N | pct_pos | mean_ic_52w | pct_pos_52w | prec@top10% | prec@bot10% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| dedup_v6 | IS | 241 | +0.0847 | +11.98 | +0.1018 | 76.3 | 61.0% | +0.079 | 99.1% | 0.162 | 0.143 |
| dedup_v6 | OOS | 74 | +0.0469 | +5.32 | +0.0467 | 176.2 | 56.8% | +0.046 | 100.0% | 0.197 | 0.091 |
| stability_v6 | IS | 241 | +0.0719 | +9.56 | +0.0763 | 76.3 | 59.8% | +0.068 | 100.0% | 0.220 | 0.136 |
| stability_v6 | OOS | 74 | +0.0921 | +10.42 | +0.0911 | 176.2 | 63.5% | +0.101 | 100.0% | 0.268 | 0.100 |

## B. Book diagnostics (net of 10 bp/side turnover cost)

Ensemble α through `xs_engine_v6` at the Phase 9.1 grid. Vol-scaled inside selection (`w ∝ 1/σ_causal_26w`). Windows: IS ≤ 2023-12-31, OOS 2024-01-01→2025-07-31, full = IS ∪ OOS (hold-out sealed). Sharpe / cumret / DD are net of cost.

**Comparability**: this is the same engine + grid + cost that produced `book_xs_v6_report.md`, but the α source is different — there it was per-cell book-screened, here it is Phase 7 IC-shortlisted (then sign-oriented and equal-weighted). Both are cost-net, so Sharpe / turnover numbers are directly comparable.


### dedup_v6

| mode | q | IS Sharpe | OOS Sharpe | full Sharpe | decay | IS cumret | OOS cumret | full cumret | full DD | avg turnover | mean_K |
|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| long | 0.05 | +0.633 | +0.409 | +0.591 | +0.65 | +56.69% | +6.31% | +62.99% | -13.50% | 1.357 | 4.7 |
| long | 0.10 | +0.614 | +0.470 | +0.586 | +0.77 | +43.24% | +6.60% | +49.85% | -9.38% | 1.233 | 8.9 |
| long | 0.20 | +0.515 | +0.369 | +0.487 | +0.72 | +28.68% | +3.72% | +32.40% | -9.32% | 1.040 | 17.4 |
| ls | 0.05 | +0.777 | -0.771 | +0.431 | -0.99 | +39.78% | -11.30% | +28.48% | -11.66% | 1.398 | 4.7 |
| ls | 0.10 | +0.640 | -0.659 | +0.328 | -1.03 | +28.60% | -9.29% | +19.31% | -10.67% | 1.281 | 8.9 |
| ls | 0.20 | +0.513 | -0.769 | +0.154 | -1.50 | +17.30% | -9.99% | +7.30% | -11.97% | 1.114 | 17.4 |

### stability_v6

| mode | q | IS Sharpe | OOS Sharpe | full Sharpe | decay | IS cumret | OOS cumret | full cumret | full DD | avg turnover | mean_K |
|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| long | 0.05 | +0.515 | -1.388 | +0.400 | -2.70 | +27.84% | -3.25% | +24.59% | -8.34% | 0.747 | 4.7 |
| long | 0.10 | +0.885 | -0.173 | +0.770 | -0.20 | +40.30% | -0.40% | +39.89% | -4.18% | 0.596 | 8.9 |
| long | 0.20 | +0.858 | +0.941 | +0.802 | +1.10 | +38.14% | +2.48% | +40.62% | -4.72% | 0.494 | 17.4 |
| ls | 0.05 | +0.238 | -1.202 | -0.114 | -5.05 | +11.81% | -19.34% | -7.53% | -23.47% | 0.955 | 4.7 |
| ls | 0.10 | +0.400 | -1.324 | -0.041 | -3.31 | +18.23% | -20.74% | -2.51% | -20.77% | 0.834 | 8.9 |
| ls | 0.20 | +0.507 | -0.934 | +0.104 | -1.84 | +20.85% | -14.84% | +6.02% | -15.92% | 0.704 | 17.4 |

## C. vs Phase 9.1 static baseline — 'beat this' targets

Side-by-side of the strongest EQW variant on this shortlist vs the Phase 9.1 per-cell book-screened baseline (`book_xs_v6_report.md`). Both are net-of-cost, same engine, same grid — the α source is the only difference. Numbers a future return model needs to beat live in the 9.1 column; the EQW column is the trivial-fitting floor.

Best EQW variant (by max full Sharpe across grid): **stability_v6**

| mode | q | 9.1 static full Sharpe | EQW full Sharpe | Δ (EQW − 9.1) | 9.1 turnover | EQW turnover |
|:---:|:---:|---:|---:|---:|---:|---:|
| long | 0.05 | +0.967 | +0.400 | -0.567 | 0.293 | 0.747 |
| long | 0.10 | +0.829 | +0.770 | -0.060 | 0.288 | 0.596 |
| long | 0.20 | +1.013 | +0.802 | -0.211 | 0.278 | 0.494 |
| ls | 0.05 | +0.000 | -0.114 | -0.114 | 0.000 | 0.955 |
| ls | 0.10 | +0.000 | -0.041 | -0.041 | 0.000 | 0.834 |
| ls | 0.20 | +0.450 | +0.104 | -0.346 | 0.812 | 0.704 |

## Files

- per-variant ensemble α : `data/eqw_baseline_v6/{variant}/ensemble_alpha.parquet`
- alpha diagnostics       : `data/eqw_baseline_v6/{variant}/alpha_diagnostics.csv`
- book grid summary       : `data/eqw_baseline_v6/{variant}/book_grid.csv`