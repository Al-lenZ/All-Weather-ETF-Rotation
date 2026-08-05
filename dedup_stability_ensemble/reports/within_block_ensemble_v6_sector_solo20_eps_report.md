# Phase 13.5 — within-block ensemble book (v6 pool, IS)

Generated: 2026-07-22 17:00:11  

Applied `BLOCK_MERGES = {smallcap_cn → broad_cn}` at load. q = 0.2, ε = 0.2 (replace rule), cost 10 bp/side, IS bars ≤ 2023-12-31. Ensemble scope filter: |zstat| ≥ 2.0 AND turnover ≤ 0.6 (turnover measured from 13.4 invvol-sizing solo book). Ensemble score = mean across members of `row_z(polarity · expanding_z(α))`, restricted to block members. Feed as α into the production hysteresis engine.

**Pass rule** (same as 13.4): IS Sharpe > max(eqw_null, invvol_null) AND CAGR ≥ eqw_null CAGR.


## 1. Filter yield + null hurdles

| block | 13.2b kept | passes filter | eqw null Sh | invvol null Sh | hurdle Sh | eqw null CAGR |
|:---|---:|---:|---:|---:|---:|---:|
| sector_cn | 27 | 3 | +0.466 | +0.470 | +0.470 | +7.77% |

## 2. Ensemble members (top by |zstat|, tie-break by lower turnover)

### `sector_cn` — filter-pass pool (3 factors)

| # | factor | pol | zstat | 13.4 solo Sharpe | solo turnover |
|---:|:---|:---:|---:|---:|---:|
| 1 | var5_60 | raw | +4.70 | +0.278 | 0.342 |
| 2 | alpha_187 | raw | +3.06 | +0.219 | 0.581 |
| 3 | kurt_40 | rev | -2.41 | +0.218 | 0.433 |

## 3. Ensemble book results

### `sector_cn`

Hurdle Sharpe = +0.470; CAGR floor = +7.77%


| K | ε | sizing | Sharpe | CAGR | max DD | turnover | ΔSh vs eqw | ΔSh vs 1/σ | ΔCAGR vs eqw | pass |
|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| 3 | 0.20 | invvol | +0.310 | +5.32% | -21.42% | 0.467 | -0.156 | -0.161 | -2.45% |  |
| 3 | 0.20 | eqw | +0.287 | +5.05% | -22.84% | 0.439 | -0.179 | -0.183 | -2.72% |  |
| 3 | 0.30 | invvol | +0.365 | +6.17% | -19.48% | 0.446 | -0.101 | -0.105 | -1.60% |  |
| 3 | 0.30 | eqw | +0.320 | +5.58% | -20.88% | 0.417 | -0.146 | -0.150 | -2.19% |  |
| 3 | 0.50 | invvol | +0.328 | +5.64% | -20.99% | 0.417 | -0.137 | -0.142 | -2.13% |  |
| 3 | 0.50 | eqw | +0.272 | +4.84% | -23.25% | 0.390 | -0.194 | -0.198 | -2.93% |  |
| 3 | 1.00 | invvol | +0.271 | +4.75% | -21.74% | 0.357 | -0.195 | -0.199 | -3.02% |  |
| 3 | 1.00 | eqw | +0.202 | +3.69% | -25.19% | 0.333 | -0.264 | -0.268 | -4.08% |  |

## 4. Read

- **`sector_cn`**: 0/8 pass. Best raw = K=3/invvol Sharpe +0.365, ΔSh vs eqw -0.101. Ensemble smoothing helped vs solo books but the block-native null still isn't cleared — try wider q or larger ε next.

