# Phase 13.2b — within-block ρ-dedup (v6 pool, IS)

Generated: 2026-07-22 16:06:30  

Threshold: |ρ| ≤ 0.5 on IS stage-1-z panels stacked across each block's admitted-ever codes (matches `pv_sweep_xs_v6`'s pool-level dedup at the within-block scope). Greedy walk in descending |zstat| — kept if |ρ| with every already-kept representative is under threshold; else dropped and mapped to its conflicting representative.


## 1. Survivor counts

| block | codes tagged | 13.2 survivors | kept after dedup |
|:---|---:|---:|---:|
| broad_cn | 49 | 127 | **24** |
| sector_cn | 167 | 94 | **27** |

## 2. `broad_cn` — kept survivors (24 of 127)

| # | factor | polarity | zstat | n | mean_ic | mean_ic_w | pct_pos |
|---:|:---|:---:|---:|---:|---:|---:|---:|
| 1 | alpha_179 | raw | +4.48 | 234 | +0.0879 | +0.0943 |  55.1% |
| 2 | alpha_025 | raw | +3.99 | 234 | +0.0803 | +0.0829 |  54.7% |
| 3 | h_vol_ratio_48 | rev | -3.39 | 228 | -0.0804 | -0.0597 |  39.0% |
| 4 | alpha015 | raw | +3.37 | 233 | +0.0741 | +0.0645 |  54.9% |
| 5 | alpha_002 | raw | +3.35 | 234 | +0.0819 | +0.0569 |  55.6% |
| 6 | alpha017 | raw | +3.21 | 233 | +0.0672 | +0.0662 |  58.8% |
| 7 | alpha_071 | raw | +3.16 | 234 | +0.0772 | +0.0559 |  56.0% |
| 8 | alpha_007 | rev | -3.03 | 234 | -0.0698 | -0.0550 |  41.5% |
| 9 | wq_092 | raw | +2.85 | 234 | +0.0616 | +0.0569 |  55.1% |
| 10 | alpha_082 | raw | +2.79 | 234 | +0.0650 | +0.0506 |  56.4% |
| 11 | alpha_102 | raw | +2.70 | 234 | +0.0544 | +0.0559 |  54.7% |
| 12 | alpha020 | raw | +2.66 | 233 | +0.0586 | +0.0520 |  55.4% |
| 13 | h_mom_decay_12_48 | raw | +2.59 | 228 | +0.0448 | +0.0607 |  53.5% |
| 14 | rsrs_18_250 | raw | +2.57 | 233 | +0.0463 | +0.0588 |  56.7% |
| 15 | alpha006 | rev | -2.37 | 233 | -0.0591 | -0.0401 |  45.5% |
| 16 | alpha002 | rev | -2.22 | 232 | -0.0384 | -0.0524 |  46.1% |
| 17 | wq_034 | raw | +2.17 | 234 | +0.0304 | +0.0568 |  51.3% |
| 18 | wq_011 | raw | +2.16 | 232 | +0.0448 | +0.0438 |  52.6% |
| 19 | wq_044 | rev | -2.16 | 234 | -0.0504 | -0.0388 |  47.0% |
| 20 | body_ratio_5 | rev | -2.08 | 234 | -0.0495 | -0.0363 |  42.7% |
| 21 | mom_accel_10 | raw | +2.07 | 233 | +0.0394 | +0.0445 |  52.4% |
| 22 | h_mr_speed_24 | raw | +2.06 | 228 | +0.0371 | +0.0467 |  53.1% |
| 23 | alpha016 | raw | +2.03 | 232 | +0.0526 | +0.0329 |  53.4% |
| 24 | wq_036 | rev | -2.00 | 234 | -0.0337 | -0.0464 |  47.0% |

### `broad_cn` — top drops (first 20 by |ρ|)

| dropped factor | absorbed by | |ρ| | dropped zstat |
|:---|:---|---:|---:|
| alpha034 | alpha015 | +0.996 | +3.35 |
| alpha035 | alpha015 | +0.995 | +3.30 |
| neg_rank_low | alpha015 | +0.748 | -2.83 |
| alpha054 | alpha015 | +0.741 | -2.79 |
| alpha004 | alpha015 | +0.740 | -2.83 |
| neg_rank_high | alpha015 | +0.733 | -2.68 |
| alpha031 | alpha015 | +0.684 | -2.87 |
| alpha042 | alpha015 | +0.684 | +2.95 |
| alpha030 | alpha015 | +0.584 | +3.07 |
| wq_031 | alpha015 | +0.523 | -2.64 |
| alpha043 | alpha017 | +0.994 | +2.90 |
| alpha_073 | alpha_002 | +0.719 | -3.25 |
| alpha_072 | alpha_002 | +0.716 | +3.34 |
| alpha041 | alpha_002 | +0.705 | +3.11 |
| alpha_152 | alpha_002 | +0.688 | -2.86 |
| alpha_001 | alpha_002 | +0.639 | -2.00 |
| alpha_054 | alpha_002 | +0.639 | -2.00 |
| alpha053 | alpha_002 | +0.630 | +2.15 |
| alpha_151 | alpha_002 | +0.616 | +2.02 |
| alpha_107 | alpha_002 | +0.604 | -2.06 |

## 2. `sector_cn` — kept survivors (27 of 94)

| # | factor | polarity | zstat | n | mean_ic | mean_ic_w | pct_pos |
|---:|:---|:---:|---:|---:|---:|---:|---:|
| 1 | var5_60 | raw | +4.70 | 193 | +0.0555 | +0.0577 |  58.0% |
| 2 | wq_039 | raw | +4.57 | 193 | +0.0605 | +0.0545 |  55.4% |
| 3 | h_accel_12 | raw | +4.54 | 193 | +0.0561 | +0.0542 |  54.9% |
| 4 | ma_disp | raw | +4.28 | 193 | +0.0532 | +0.0505 |  57.5% |
| 5 | h_mom_decay_6_24 | raw | +4.09 | 193 | +0.0507 | +0.0474 |  56.5% |
| 6 | alpha_012 | rev | -3.30 | 193 | -0.0531 | -0.0357 |  44.6% |
| 7 | alpha_142 | raw | +3.07 | 193 | +0.0577 | +0.0291 |  57.5% |
| 8 | alpha_187 | raw | +3.06 | 193 | +0.0472 | +0.0301 |  54.9% |
| 9 | yj15_bias_mom_60_20 | rev | -2.97 | 193 | -0.0373 | -0.0374 |  45.1% |
| 10 | wq_003 | raw | +2.93 | 193 | +0.0520 | +0.0244 |  59.6% |
| 11 | wq_045 | rev | -2.82 | 193 | -0.0305 | -0.0365 |  42.5% |
| 12 | mom_accel_5 | raw | +2.79 | 193 | +0.0382 | +0.0348 |  56.0% |
| 13 | wq_009 | rev | -2.76 | 193 | -0.0165 | -0.0464 |  43.5% |
| 14 | wq_068 | rev | -2.75 | 193 | -0.0384 | -0.0339 |  44.6% |
| 15 | h_mom_decay_12_48 | raw | +2.75 | 193 | +0.0239 | +0.0336 |  49.2% |
| 16 | alpha028 | raw | +2.71 | 193 | +0.0275 | +0.0366 |  54.9% |
| 17 | h_vol_spike_24 | raw | +2.65 | 193 | +0.0369 | +0.0332 |  54.4% |
| 18 | wq_034 | rev | -2.55 | 193 | -0.0381 | -0.0275 |  47.2% |
| 19 | wq_054 | raw | +2.52 | 193 | +0.0255 | +0.0356 |  49.7% |
| 20 | kurt_40 | rev | -2.41 | 193 | -0.0641 | -0.0127 |  45.1% |
| 21 | alpha021 | rev | -2.28 | 193 | -0.0272 | -0.0283 |  43.5% |
| 22 | ret_skew_20 | raw | +2.27 | 193 | +0.0288 | +0.0285 |  54.4% |
| 23 | autocorr_20 | raw | +2.19 | 193 | +0.0340 | +0.0239 |  50.8% |
| 24 | wq_008 | raw | +2.18 | 193 | +0.0314 | +0.0206 |  53.9% |
| 25 | wq_058 | rev | -2.13 | 193 | -0.0260 | -0.0249 |  48.2% |
| 26 | alpha_071 | raw | +2.12 | 193 | +0.0396 | +0.0178 |  59.1% |
| 27 | wq_016 | rev | -2.10 | 193 | -0.0296 | -0.0216 |  45.6% |

### `sector_cn` — top drops (first 20 by |ρ|)

| dropped factor | absorbed by | |ρ| | dropped zstat |
|:---|:---|---:|---:|
| alpha049 | alpha021 | +1.000 | -2.28 |
| alpha034 | alpha_142 | +0.565 | +2.45 |
| alpha015 | alpha_142 | +0.559 | +2.26 |
| autocorr_10 | autocorr_20 | +0.585 | +2.14 |
| h_price_accel_12 | h_accel_12 | +1.000 | +4.54 |
| alpha046 | h_accel_12 | +0.647 | +2.75 |
| alpha_168 | h_accel_12 | +0.645 | +2.26 |
| alpha_162 | h_accel_12 | +0.642 | +2.02 |
| alpha_170 | h_accel_12 | +0.612 | +2.25 |
| alpha_146 | h_accel_12 | +0.548 | +2.36 |
| alpha_072 | h_accel_12 | +0.536 | -2.27 |
| alpha014 | h_accel_12 | +0.529 | +2.68 |
| alpha_144 | h_accel_12 | +0.523 | +2.63 |
| alpha_107 | h_accel_12 | +0.510 | +2.05 |
| kst | h_mom_decay_6_24 | +0.887 | -3.54 |
| alpha_023 | h_mom_decay_6_24 | +0.833 | -3.38 |
| alpha_088 | h_mom_decay_6_24 | +0.833 | -3.37 |
| ichi_9 | h_mom_decay_6_24 | +0.832 | -2.42 |
| accel_5_20 | h_mom_decay_6_24 | +0.828 | +2.14 |
| h_macd_12_26 | h_mom_decay_6_24 | +0.796 | -2.21 |

## 3. Read for 13.3

Down from 221 raw survivors to 51 after |ρ| ≤ 0.5 dedup. Holdings popularity in 13.3 runs against this reduced list — same treatment as `pv_sweep_xs_v6_dedup.csv` at the pool level.

