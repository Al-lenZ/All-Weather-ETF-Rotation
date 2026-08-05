# Phase 13.4 — within-block isolated book (v6 pool, IS)

Generated: 2026-07-22 17:25:00  

Applied `BLOCK_MERGES = {smallcap_cn → broad_cn}` at load. q = 0.2, ε = 0.2 (replace rule), cost 10 bp/side. IS bars ≤ 2023-12-31. Two sizings per factor (1/σ, eqw). Two per-block nulls (eqw hold-all, 1/σ hold-all).

**Pass rule** (user, 2026-07-22): IS Sharpe > max(eqw_null Sharpe, invvol_null Sharpe) AND IS CAGR ≥ eqw_null CAGR. Both nulls on the same block, same window, same cost. A pass means the factor is producing net-of-cost selection value beyond block β + sizing.


## 1. Per-block nulls

| block | null | Sharpe | CAGR | max DD | ann vol | turnover |
|:---|:---|---:|---:|---:|---:|---:|
| cross_border_hk | eqw_null | -0.540 | -15.52% | -56.70% | +24.49% | 0.026 |
| cross_border_hk | invvol_null | -0.562 | -15.29% | -57.30% | +23.21% | 0.040 |

## 2. Pass counts per block × sizing

| block | sizing | tested | passed | best-factor Sharpe |
|:---|:---:|---:|---:|---:|
| cross_border_hk | invvol | 9 | 0 | -0.560 |
| cross_border_hk | eqw | 9 | 0 | -0.573 |

## 3. `cross_border_hk` — sizing = **invvol** (0 pass / 9 total)

Hurdle Sharpe = max(eqw=-0.540, invvol=-0.562) = -0.540; CAGR floor = eqw -15.52%.


| factor | pol | zstat | Sharpe | CAGR | max DD | turnover | ΔSh vs eqw | ΔSh vs 1/σ | ΔCAGR vs eqw | pass |
|:---|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| wq_054 | rev | -3.43 | -0.560 | -16.73% | -68.03% | 1.027 | -0.020 | +0.003 | -1.20% |  |
| alpha_142 | rev | -2.95 | -0.600 | -18.06% | -71.10% | 0.564 | -0.060 | -0.037 | -2.54% |  |
| shadow_up_5 | raw | +2.83 | -0.610 | -17.66% | -77.62% | 0.887 | -0.070 | -0.047 | -2.14% |  |
| alpha_025 | rev | -2.88 | -0.714 | -21.13% | -73.45% | 0.598 | -0.174 | -0.151 | -5.60% |  |
| alpha_062 | raw | +3.16 | -0.769 | -20.62% | -67.66% | 0.285 | -0.229 | -0.207 | -5.10% |  |
| alpha_098 | rev | -2.90 | -0.820 | -24.12% | -60.47% | 0.984 | -0.281 | -0.258 | -8.60% |  |
| alpha_028 | rev | -3.57 | -0.828 | -22.65% | -68.21% | 0.168 | -0.288 | -0.266 | -7.13% |  |
| alpha_103 | rev | -2.81 | -0.900 | -24.86% | -71.67% | 0.211 | -0.360 | -0.338 | -9.34% |  |
| wq_098 | rev | -3.01 | -1.062 | -35.99% | -77.77% | 1.012 | -0.522 | -0.499 | -20.47% |  |

## 3. `cross_border_hk` — sizing = **eqw** (0 pass / 9 total)

Hurdle Sharpe = max(eqw=-0.540, invvol=-0.562) = -0.540; CAGR floor = eqw -15.52%.


| factor | pol | zstat | Sharpe | CAGR | max DD | turnover | ΔSh vs eqw | ΔSh vs 1/σ | ΔCAGR vs eqw | pass |
|:---|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| alpha_142 | rev | -2.95 | -0.573 | -17.33% | -69.46% | 0.552 | -0.034 | -0.011 | -1.81% |  |
| wq_054 | rev | -3.43 | -0.594 | -18.15% | -69.01% | 1.018 | -0.054 | -0.031 | -2.63% |  |
| shadow_up_5 | raw | +2.83 | -0.649 | -19.40% | -78.60% | 0.866 | -0.110 | -0.087 | -3.88% |  |
| alpha_025 | rev | -2.88 | -0.731 | -22.27% | -75.36% | 0.561 | -0.191 | -0.168 | -6.75% |  |
| alpha_062 | raw | +3.16 | -0.751 | -20.30% | -67.82% | 0.278 | -0.212 | -0.189 | -4.78% |  |
| alpha_098 | rev | -2.90 | -0.815 | -24.48% | -60.92% | 0.969 | -0.275 | -0.252 | -8.96% |  |
| alpha_028 | rev | -3.57 | -0.822 | -22.74% | -68.06% | 0.167 | -0.282 | -0.260 | -7.21% |  |
| alpha_103 | rev | -2.81 | -0.917 | -25.95% | -71.57% | 0.197 | -0.377 | -0.354 | -10.43% |  |
| wq_098 | rev | -3.01 | -1.054 | -37.11% | -78.00% | 0.986 | -0.514 | -0.491 | -21.58% |  |

## 4. Read for next steps

- **`cross_border_hk` × invvol**: 0 pass. IC survived, but net-of-cost selection value doesn't clear the block-native null hurdle. Consider lower-turnover variants (higher ε, wider q) before ruling out the block × sizing combo.

- **`cross_border_hk` × eqw**: 0 pass. IC survived, but net-of-cost selection value doesn't clear the block-native null hurdle. Consider lower-turnover variants (higher ε, wider q) before ruling out the block × sizing combo.


