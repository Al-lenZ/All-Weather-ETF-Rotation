# Phase 13.5 — within-block ensemble book (v6 pool, IS)

Generated: 2026-07-22 16:51:18  

Applied `BLOCK_MERGES = {smallcap_cn → broad_cn}` at load. q = 0.2, ε = 0.2 (replace rule), cost 10 bp/side, IS bars ≤ 2023-12-31. Ensemble scope filter: |zstat| ≥ 2.0 AND turnover ≤ 0.6 (turnover measured from 13.4 invvol-sizing solo book). Ensemble score = mean across members of `row_z(polarity · expanding_z(α))`, restricted to block members. Feed as α into the production hysteresis engine.

**Pass rule** (same as 13.4): IS Sharpe > max(eqw_null, invvol_null) AND CAGR ≥ eqw_null CAGR.


## 1. Filter yield + null hurdles

| block | 13.2b kept | passes filter | eqw null Sh | invvol null Sh | hurdle Sh | eqw null CAGR |
|:---|---:|---:|---:|---:|---:|---:|
| broad_cn | 24 | 5 | +0.459 | +0.475 | +0.475 | +6.63% |
| sector_cn | 27 | 9 | +0.466 | +0.470 | +0.470 | +7.77% |

## 2. Ensemble members (top by |zstat|, tie-break by lower turnover)

### `broad_cn` — filter-pass pool (5 factors)

| # | factor | pol | zstat | 13.4 solo Sharpe | solo turnover |
|---:|:---|:---:|---:|---:|---:|
| 1 | alpha015 | raw | +3.37 | +0.446 | 0.551 |
| 2 | alpha_071 | raw | +3.16 | +0.543 | 0.251 |
| 3 | alpha_102 | raw | +2.70 | +0.604 | 0.387 |
| 4 | h_mom_decay_12_48 | raw | +2.59 | +0.198 | 0.485 |
| 5 | alpha006 | rev | -2.37 | +0.371 | 0.481 |

### `sector_cn` — filter-pass pool (9 factors)

| # | factor | pol | zstat | 13.4 solo Sharpe | solo turnover |
|---:|:---|:---:|---:|---:|---:|
| 1 | var5_60 | raw | +4.70 | +0.278 | 0.342 |
| 2 | ma_disp | raw | +4.28 | +0.125 | 0.428 |
| 3 | alpha_142 | raw | +3.07 | +0.174 | 0.599 |
| 4 | alpha_187 | raw | +3.06 | +0.219 | 0.581 |
| 5 | yj15_bias_mom_60_20 | rev | -2.97 | -0.106 | 0.570 |
| 6 | h_mom_decay_12_48 | raw | +2.75 | +0.158 | 0.487 |
| 7 | kurt_40 | rev | -2.41 | +0.218 | 0.433 |
| 8 | ret_skew_20 | raw | +2.27 | +0.046 | 0.580 |
| 9 | alpha_071 | raw | +2.12 | +0.051 | 0.280 |

## 3. Ensemble book results

### `broad_cn`

Hurdle Sharpe = +0.475; CAGR floor = +6.63%


| K | sizing | Sharpe | CAGR | max DD | turnover | ΔSh vs eqw | ΔSh vs 1/σ | ΔCAGR vs eqw | pass |
|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| 3 | invvol | +0.629 | +8.85% | -15.86% | 0.393 | +0.170 | +0.154 | +2.22% | ✓ |
| 3 | eqw | +0.614 | +8.81% | -15.92% | 0.363 | +0.155 | +0.139 | +2.17% | ✓ |
| 5 | invvol | +0.907 | +11.85% | -13.70% | 0.503 | +0.448 | +0.431 | +5.22% | ✓ |
| 5 | eqw | +0.905 | +11.94% | -13.05% | 0.475 | +0.445 | +0.429 | +5.30% | ✓ |

### `sector_cn`

Hurdle Sharpe = +0.470; CAGR floor = +7.77%


| K | sizing | Sharpe | CAGR | max DD | turnover | ΔSh vs eqw | ΔSh vs 1/σ | ΔCAGR vs eqw | pass |
|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| 3 | invvol | +0.230 | +3.79% | -23.32% | 0.468 | -0.235 | -0.240 | -3.98% |  |
| 3 | eqw | +0.194 | +3.28% | -24.46% | 0.443 | -0.272 | -0.276 | -4.49% |  |
| 5 | invvol | +0.152 | +2.45% | -23.33% | 0.509 | -0.314 | -0.318 | -5.32% |  |
| 5 | eqw | +0.100 | +1.67% | -25.77% | 0.481 | -0.366 | -0.370 | -6.10% |  |
| 8 | invvol | +0.294 | +4.56% | -21.10% | 0.517 | -0.172 | -0.176 | -3.21% |  |
| 8 | eqw | +0.251 | +4.02% | -21.08% | 0.487 | -0.214 | -0.219 | -3.75% |  |
| 9 | invvol | +0.249 | +4.08% | -21.41% | 0.495 | -0.217 | -0.221 | -3.70% |  |
| 9 | eqw | +0.190 | +3.22% | -23.73% | 0.469 | -0.275 | -0.280 | -4.55% |  |

## 4. Read

- **`broad_cn`**: 4/4 ensemble variants pass. Best pass = K=5/invvol Sharpe +0.907, CAGR +11.85%, ΔSh vs eqw +0.448. Ready as the per-block α layer for Phase 12.

- **`sector_cn`**: 0/8 pass. Best raw = K=8/invvol Sharpe +0.294, ΔSh vs eqw -0.172. Ensemble smoothing helped vs solo books but the block-native null still isn't cleared — try wider q or larger ε next.

