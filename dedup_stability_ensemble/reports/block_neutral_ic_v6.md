# v6 static — block-neutral IC diagnostic (DESIGN §8)

Generated: 2026-07-21 19:43:38  

IC vs ranked risk-adj label ỹ, IS window (bars ≤ 2023-12-31).

- **raw** — per-bar Spearman IC across all valid names.
- **within** — per-bar Pearson IC after subtracting the per-`BLOCK_TAG` mean from both the α-rank and ỹ-rank vectors. Blocks with fewer than 2 valid names in a bar are dropped.
- **between** — per-bar size-weighted Pearson IC of block-mean ranks. Positive between + near-zero within = pure sector rotation; positive within = relative-value information.
- zstat uses the ragged √(N−1) aggregation from `C.ic_summary` (N = row size for raw/between; block-neutral N for within).


| cell | factor | raw mean | raw z | raw pos% | within mean | within z | within pos% | between mean | between z | mean N | within N |
|:---:|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| long_q05 | alpha_186_rev | +0.0280 | +4.51 | 0.51 | -0.0053 | -1.32 | 0.48 | +0.1003 | +15.09 | 76.3 | 74.8 |
| long_q05 | alpha_104 | +0.0284 | +4.53 | 0.54 | -0.0152 | -1.84 | 0.48 | +0.1093 | +16.78 | 76.3 | 74.8 |
| long_q05 | alpha_103_rev | +0.0414 | +6.18 | 0.60 | +0.0095 | +0.74 | 0.46 | +0.1185 | +17.95 | 76.3 | 74.8 |
| long_q05 | h_pv_corr_48 | +0.0157 | -0.42 | 0.49 | +0.0078 | -0.65 | 0.51 | +0.0001 | -3.51 | 75.7 | 74.2 |
| long_q05 | alpha_098 | +0.0475 | +6.78 | 0.57 | +0.0103 | +1.83 | 0.54 | +0.1257 | +17.70 | 76.3 | 74.8 |
| long_q05 | *ensemble* | +0.0491 | +6.28 | 0.61 | +0.0164 | +1.05 | 0.51 | +0.1255 | +17.51 | 76.3 | 74.8 |
| long_q10 | alpha_102_rev | +0.0280 | +4.51 | 0.51 | -0.0052 | -1.31 | 0.48 | +0.1003 | +15.10 | 76.3 | 74.8 |
| long_q10 | alpha_104 | +0.0284 | +4.53 | 0.54 | -0.0152 | -1.84 | 0.48 | +0.1093 | +16.78 | 76.3 | 74.8 |
| long_q10 | autocorr_20 | +0.0174 | +2.48 | 0.54 | +0.0121 | +2.37 | 0.52 | +0.0154 | +0.90 | 76.3 | 74.8 |
| long_q10 | alpha_098 | +0.0475 | +6.78 | 0.57 | +0.0103 | +1.83 | 0.54 | +0.1257 | +17.70 | 76.3 | 74.8 |
| long_q10 | alpha_103_rev | +0.0414 | +6.18 | 0.60 | +0.0095 | +0.74 | 0.46 | +0.1185 | +17.95 | 76.3 | 74.8 |
| long_q10 | h_pv_corr_48 | +0.0157 | -0.42 | 0.49 | +0.0078 | -0.65 | 0.51 | +0.0001 | -3.51 | 75.7 | 74.2 |
| long_q10 | obv_20_rev | +0.0105 | +1.11 | 0.56 | +0.0106 | +1.08 | 0.53 | +0.0149 | +1.77 | 76.3 | 74.8 |
| long_q10 | *ensemble* | +0.0468 | +6.30 | 0.59 | +0.0172 | +1.62 | 0.53 | +0.1170 | +16.48 | 76.3 | 74.8 |
| long_q20 | alpha_102_rev | +0.0280 | +4.51 | 0.51 | -0.0052 | -1.31 | 0.48 | +0.1003 | +15.10 | 76.3 | 74.8 |
| long_q20 | h_pv_corr_48 | +0.0157 | -0.42 | 0.49 | +0.0078 | -0.65 | 0.51 | +0.0001 | -3.51 | 75.7 | 74.2 |
| long_q20 | alpha_071 | +0.0284 | +4.48 | 0.54 | -0.0164 | -2.00 | 0.47 | +0.1104 | +16.84 | 76.3 | 74.8 |
| long_q20 | alpha_103_rev | +0.0414 | +6.18 | 0.60 | +0.0095 | +0.74 | 0.46 | +0.1185 | +17.95 | 76.3 | 74.8 |
| long_q20 | neg_rank_high_rev | +0.0382 | +4.92 | 0.59 | +0.0302 | +3.64 | 0.54 | +0.0655 | +10.22 | 76.3 | 74.8 |
| long_q20 | h_vol_clust_24 | +0.0218 | +2.84 | 0.53 | +0.0187 | +2.78 | 0.54 | +0.0342 | +4.09 | 76.3 | 74.8 |
| long_q20 | *ensemble* | +0.0601 | +7.41 | 0.60 | +0.0376 | +3.54 | 0.54 | +0.1205 | +16.85 | 76.3 | 74.8 |
| ls_q20 | alpha_101 | +0.0218 | +2.01 | 0.53 | +0.0291 | +2.62 | 0.55 | -0.0030 | -0.53 | 76.3 | 74.8 |
| ls_q20 | *ensemble* | +0.0218 | +2.01 | 0.53 | +0.0291 | +2.62 | 0.55 | -0.0030 | -0.53 | 76.3 | 74.8 |
