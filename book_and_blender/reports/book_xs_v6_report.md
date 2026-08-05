# v6 static baseline — coarse (mode, q) grid

Generated: 2026-07-20 12:34:33  


## Setup

**Universe:** v6, ragged W-FRI membership panel  (mean_N = 85.0 in-panel, 292 IS bars + 82 OOS bars).  
**IS window:** ≤ 2023-12-31 · **OOS window:** 2024-01-01 → 2025-07-31 · **Hold-out (sealed):** > 2025-07-31  
**Engine:** weekly W-FRI rebal, vol-scaled inside selection (w ∝ 1/σ_causal_26w), 10 bp/side turnover cost. See `xs_engine_v6.py`.  
**Grid:** modes ['long', 'ls'] × q [0.05, 0.1, 0.2]  
**Screening thresholds** (reused from v4/v5): IS Sharpe ≥ 0.5, OOS Sharpe ≥ 0.2, decay ≥ 0.3, dedup |ρ| > 0.3 on the flattened stage-2 CS-Gaussian-rank panels.  
**Ensemble α** = mean of per-bar row-z-scored raw α of kept factors (polarity-oriented). Matches the v4pool convention (`build_combined_v5.ensemble_alpha`); see `diagnose_ensemble_v6.py` for why the earlier CS-rank combiner was replaced.  

## Grid results — Sharpe headline

| mode | q | scr | rlx | kept | IS Sharpe | OOS Sharpe | decay | avg turnover | mean_K | mean_N |
|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| long | 0.05 |  944 |  19 |   5 | +1.052 | +0.591 | +0.56 | 0.293 |   4.7 |  85.0 |
| long | 0.10 |  944 |  21 |   7 | +0.808 | +1.473 | +1.82 | 0.288 |   8.9 |  85.0 |
| long | 0.20 |  944 |  18 |   6 | +1.002 | +2.071 | +2.07 | 0.278 |  17.4 |  85.0 |
|   ls | 0.05 |  944 |   0 |   0 | +0.000 | +0.000 | +0.00 | 0.000 |   0.0 |   0.0 |
|   ls | 0.10 |  944 |   0 |   0 | +0.000 | +0.000 | +0.00 | 0.000 |   0.0 |   0.0 |
|   ls | 0.20 |  944 |   1 |   1 | +0.503 | +0.275 | +0.55 | 0.812 |  17.4 |  85.0 |

## Grid results — cumulative return, CAGR, max drawdown

Windows: **IS** ≤ 2023-12-31 · **OOS** 2024-01-01→2025-07-31 · **Full** = IS ∪ OOS. Cumret is Convention-A additive (Σ net_ret on constant notional). CAGR compounds the same NAV path. Max DD is on the constant-notional NAV.

| mode | q | IS cumret | IS CAGR | IS DD | OOS cumret | OOS CAGR | OOS DD | full cumret | full DD |
|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|
| long | 0.05 |   +12.44% |   +2.11% |   -4.68% |    +0.82% |   +0.52% |   -1.01% |   +13.26% |   -4.68% |
| long | 0.10 |   +11.53% |   +1.96% |   -3.77% |    +2.10% |   +1.33% |   -0.86% |   +13.63% |   -3.77% |
| long | 0.20 |   +21.15% |   +3.48% |   -5.24% |    +3.29% |   +2.07% |   -0.90% |   +24.43% |   -5.24% |
|   ls | 0.05 |    +0.00% |   +0.00% |   +0.00% |    +0.00% |   +0.00% |   +0.00% |    +0.00% |   +0.00% |
|   ls | 0.10 |    +0.00% |   +0.00% |   +0.00% |    +0.00% |   +0.00% |   +0.00% |    +0.00% |   +0.00% |
|   ls | 0.20 |   +24.59% |   +3.99% |   -9.15% |    +4.10% |   +2.58% |  -11.11% |   +28.70% |  -11.32% |

## Baseline selection

**Deferred.** All three q values are retained so the downstream model / combined-book sweeps can rerun the same grid and compare like-for-like. Design §7's IS-Sharpe pick rule is not applied here.


## Kept sets per cell (post-dedup)


### long_q05

| factor | polarity | IS Sharpe | OOS Sharpe | decay | turnover |
|---|:---:|---:|---:|---:|---:|
| alpha_186_rev | rev | +1.225 | +1.220 | +1.00 | 0.241 |
| alpha_104 | orig | +0.913 | +1.703 | +1.87 | 0.183 |
| alpha_103_rev | rev | +0.914 | +1.433 | +1.57 | 0.220 |
| h_pv_corr_48 | orig | +0.645 | +0.412 | +0.64 | 0.843 |
| alpha_098 | orig | +0.568 | +0.655 | +1.15 | 0.670 |

### long_q10

| factor | polarity | IS Sharpe | OOS Sharpe | decay | turnover |
|---|:---:|---:|---:|---:|---:|
| alpha_102_rev | rev | +0.967 | +1.943 | +2.01 | 0.209 |
| alpha_104 | orig | +0.648 | +1.883 | +2.91 | 0.192 |
| autocorr_20 | orig | +0.506 | +1.411 | +2.79 | 1.050 |
| alpha_098 | orig | +0.605 | +0.849 | +1.40 | 0.540 |
| alpha_103_rev | rev | +0.543 | +1.880 | +3.46 | 0.196 |
| h_pv_corr_48 | orig | +0.586 | +0.728 | +1.24 | 0.759 |
| obv_20_rev | rev | +0.557 | +0.761 | +1.37 | 0.673 |

### long_q20

| factor | polarity | IS Sharpe | OOS Sharpe | decay | turnover |
|---|:---:|---:|---:|---:|---:|
| alpha_102_rev | rev | +0.690 | +2.347 | +3.40 | 0.213 |
| h_pv_corr_48 | orig | +0.704 | +0.740 | +1.05 | 0.639 |
| alpha_071 | orig | +0.623 | +2.486 | +3.99 | 0.193 |
| alpha_103_rev | rev | +0.568 | +2.669 | +4.70 | 0.203 |
| neg_rank_high_rev | rev | +0.514 | +1.056 | +2.06 | 0.612 |
| h_vol_clust_24 | orig | +0.558 | +0.470 | +0.84 | 0.835 |

### ls_q05

_(no survivors)_

### ls_q10

_(no survivors)_

### ls_q20

| factor | polarity | IS Sharpe | OOS Sharpe | decay | turnover |
|---|:---:|---:|---:|---:|---:|
| alpha_101 | orig | +0.503 | +0.275 | +0.55 | 0.812 |

## Diagnostic — top-10 by full Sharpe pre-filter

Shows the strongest single-factor books at each cell regardless of whether they cleared the (IS, OOS, decay) gate. Useful for interpreting why some cells have empty kept sets.


### long_q05

| factor | IS Sharpe | OOS Sharpe | full Sharpe | decay | turnover |
|---|---:|---:|---:|---:|---:|
| alpha_186_rev | +1.225 | +1.220 | +1.160 | +1.00 | 0.241 |
| alpha_102_rev | +1.211 | +1.220 | +1.149 | +1.01 | 0.241 |
| alpha_062_rev | +1.114 | +0.800 | +1.027 | +0.72 | 0.288 |
| alpha_104 | +0.913 | +1.703 | +1.007 | +1.87 | 0.183 |
| alpha_036 | +0.913 | +1.703 | +1.007 | +1.87 | 0.183 |
| alpha_071 | +0.911 | +1.506 | +0.983 | +1.65 | 0.186 |
| alpha_028 | +0.902 | +1.532 | +0.980 | +1.70 | 0.186 |
| alpha_103_rev | +0.914 | +1.433 | +0.980 | +1.57 | 0.220 |
| alpha_068_rev | +1.124 | -0.016 | +0.975 | -0.01 | 0.391 |
| alpha_171_rev | +1.118 | -0.016 | +0.970 | -0.01 | 0.392 |

### long_q10

| factor | IS Sharpe | OOS Sharpe | full Sharpe | decay | turnover |
|---|---:|---:|---:|---:|---:|
| alpha_102_rev | +0.967 | +1.943 | +1.017 | +2.01 | 0.209 |
| alpha_186_rev | +0.967 | +1.942 | +1.016 | +2.01 | 0.209 |
| alpha_062_rev | +0.862 | +1.871 | +0.916 | +2.17 | 0.224 |
| alpha_095_rev | +0.778 | +1.836 | +0.833 | +2.36 | 0.287 |
| alpha_171_rev | +0.769 | +1.796 | +0.821 | +2.33 | 0.276 |
| alpha_108_rev | +0.769 | +1.796 | +0.821 | +2.33 | 0.276 |
| alpha_068_rev | +0.755 | +1.766 | +0.806 | +2.34 | 0.276 |
| alpha_036 | +0.648 | +1.883 | +0.739 | +2.91 | 0.192 |
| alpha_104 | +0.648 | +1.883 | +0.739 | +2.91 | 0.192 |
| alpha_071 | +0.611 | +1.883 | +0.703 | +3.08 | 0.192 |

### long_q20

| factor | IS Sharpe | OOS Sharpe | full Sharpe | decay | turnover |
|---|---:|---:|---:|---:|---:|
| alpha_102_rev | +0.690 | +2.347 | +0.767 | +3.40 | 0.213 |
| alpha_186_rev | +0.684 | +2.345 | +0.762 | +3.43 | 0.214 |
| alpha_062_rev | +0.647 | +2.406 | +0.745 | +3.72 | 0.227 |
| ma_disp | +0.604 | +1.083 | +0.724 | +1.79 | 0.670 |
| h_pv_corr_48 | +0.704 | +0.740 | +0.710 | +1.05 | 0.639 |
| alpha_071 | +0.623 | +2.486 | +0.694 | +3.99 | 0.193 |
| alpha_028 | +0.600 | +2.495 | +0.675 | +4.16 | 0.194 |
| alpha_103_rev | +0.568 | +2.669 | +0.664 | +4.70 | 0.203 |
| neg_rank_high_rev | +0.514 | +1.056 | +0.649 | +2.06 | 0.612 |
| alpha_036 | +0.571 | +2.417 | +0.645 | +4.23 | 0.192 |

### ls_q05

| factor | IS Sharpe | OOS Sharpe | full Sharpe | decay | turnover |
|---|---:|---:|---:|---:|---:|
| alpha_102 | +0.340 | +0.502 | +0.380 | +1.48 | 0.364 |
| alpha_036_rev | +0.252 | +0.712 | +0.369 | +2.83 | 0.222 |
| alpha_104_rev | +0.252 | +0.712 | +0.369 | +2.83 | 0.222 |
| alpha_035 | +0.102 | +1.101 | +0.357 | +10.75 | 0.713 |
| alpha_186 | +0.303 | +0.495 | +0.350 | +1.63 | 0.366 |
| alpha_062 | +0.246 | +0.582 | +0.326 | +2.36 | 0.506 |
| alpha_071_rev | +0.147 | +0.694 | +0.292 | +4.74 | 0.248 |
| cvar5_60 | +0.434 | -0.150 | +0.276 | -0.35 | 0.585 |
| h_vol_48_rev | +0.263 | +0.294 | +0.269 | +1.12 | 0.599 |
| alpha_028_rev | +0.112 | +0.691 | +0.266 | +6.19 | 0.242 |

### ls_q10

| factor | IS Sharpe | OOS Sharpe | full Sharpe | decay | turnover |
|---|---:|---:|---:|---:|---:|
| alpha_101 | +0.565 | -0.105 | +0.425 | -0.19 | 0.898 |
| alpha_071_rev | +0.197 | +0.776 | +0.362 | +3.93 | 0.230 |
| alpha_104_rev | +0.211 | +0.724 | +0.356 | +3.44 | 0.212 |
| alpha_036_rev | +0.211 | +0.724 | +0.356 | +3.44 | 0.212 |
| alpha_028_rev | +0.176 | +0.757 | +0.341 | +4.29 | 0.227 |
| alpha_102 | +0.246 | +0.585 | +0.333 | +2.37 | 0.321 |
| alpha_035 | +0.116 | +0.954 | +0.332 | +8.22 | 0.655 |
| alpha_186 | +0.236 | +0.606 | +0.331 | +2.56 | 0.319 |
| alpha_117 | +0.150 | +0.747 | +0.304 | +5.00 | 0.540 |
| alpha_024 | +0.144 | +0.704 | +0.289 | +4.88 | 0.538 |

### ls_q20

| factor | IS Sharpe | OOS Sharpe | full Sharpe | decay | turnover |
|---|---:|---:|---:|---:|---:|
| alpha_101 | +0.503 | +0.275 | +0.450 | +0.55 | 0.812 |
| ma_disp | +0.354 | +0.747 | +0.450 | +2.11 | 0.712 |
| neg_rank_high_rev | +0.398 | +0.149 | +0.318 | +0.37 | 0.563 |
| alpha_056 | +0.363 | +0.067 | +0.282 | +0.18 | 0.867 |
| alpha_121_rev | +0.175 | +0.542 | +0.271 | +3.10 | 0.809 |
| neg_rank_low_rev | +0.317 | +0.141 | +0.260 | +0.45 | 0.581 |
| alpha004_rev | +0.398 | -0.060 | +0.260 | -0.15 | 0.585 |
| alpha_186 | +0.151 | +0.522 | +0.253 | +3.45 | 0.295 |
| alpha_035 | +0.084 | +0.697 | +0.253 | +8.32 | 0.590 |
| alpha_102 | +0.139 | +0.531 | +0.247 | +3.83 | 0.295 |

## Files

- `data/v6_static/grid_summary.csv` — this table
- `data/v6_static/{cell}/all_factors.csv` — every (factor, polarity) row per cell
- `data/v6_static/{cell}/relaxed.csv` — filter survivors
- `data/v6_static/{cell}/dedup.csv` — kept set
- `data/v6_static/{cell}/dropped.csv` — dedup dropouts
- `data/v6_static/{cell}/ensemble_alpha.parquet` — the T×N ensemble α panel
- `data/v6_static/{cell}/ensemble_weights.parquet` — book weights
- `data/v6_static/{cell}/ensemble_net_ret.csv` — per-bar net return
- `data/v6_static/{cell}/ensemble_sharpe.csv` — one-row summary
- `data/v6_static/{cell}/ensemble_picks.csv` — per-bar non-zero weights (long side + short side)

**Raw data for downstream per-year / rolling-window diagnostics.** Per-bar net returns of the ensemble book live in `ensemble_net_ret.csv`; per-bar weights in `ensemble_weights.parquet`. Any per-year Sharpe / max DD / CAGR breakdown can be reconstructed from those without re-running the screen. Per-factor per-bar returns are not persisted — rerun the screen (~70 s per cell) if you need them.