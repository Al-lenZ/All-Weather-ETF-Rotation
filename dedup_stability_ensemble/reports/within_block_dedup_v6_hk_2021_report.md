# Phase 13.2b — within-block ρ-dedup (v6 pool, IS)

Generated: 2026-07-22 17:21:17  

Threshold: |ρ| ≤ 0.5 on IS stage-1-z panels stacked across each block's admitted-ever codes (matches `pv_sweep_xs_v6`'s pool-level dedup at the within-block scope). Greedy walk in descending |zstat| — kept if |ρ| with every already-kept representative is under threshold; else dropped and mapped to its conflicting representative.


## 1. Survivor counts

| block | codes tagged | 13.2 survivors | kept after dedup |
|:---|---:|---:|---:|
| cross_border_hk | 55 | 15 | **9** |

## 2. `cross_border_hk` — kept survivors (9 of 15)

| # | factor | polarity | zstat | n | mean_ic | mean_ic_w | pct_pos |
|---:|:---|:---:|---:|---:|---:|---:|---:|
| 1 | alpha_028 | rev | -3.57 | 89 | -0.1234 | -0.1177 |  39.3% |
| 2 | wq_054 | rev | -3.43 | 89 | -0.1028 | -0.1273 |  39.3% |
| 3 | alpha_062 | raw | +3.16 | 89 | +0.1073 | +0.1058 |  58.4% |
| 4 | wq_098 | rev | -3.01 | 89 | -0.1003 | -0.1040 |  33.7% |
| 5 | alpha_142 | rev | -2.95 | 89 | -0.0937 | -0.1024 |  40.4% |
| 6 | alpha_098 | rev | -2.90 | 89 | -0.0991 | -0.0985 |  36.0% |
| 7 | alpha_025 | rev | -2.88 | 89 | -0.1046 | -0.0948 |  42.7% |
| 8 | shadow_up_5 | raw | +2.83 | 89 | +0.0947 | +0.0956 |  56.2% |
| 9 | alpha_103 | rev | -2.81 | 89 | -0.0992 | -0.0917 |  36.0% |

### `cross_border_hk` — top drops (first 20 by |ρ|)

| dropped factor | absorbed by | |ρ| | dropped zstat |
|:---|:---|---:|---:|
| h_consec_10 | alpha_025 | +0.859 | -2.81 |
| alpha_071 | alpha_028 | +0.988 | -3.42 |
| alpha_036 | alpha_028 | +0.952 | -3.46 |
| alpha_104 | alpha_028 | +0.952 | -3.46 |
| atr_10 | alpha_062 | +0.937 | +2.90 |
| alpha_116 | alpha_062 | +0.634 | +3.00 |

## 3. Read for 13.3

Down from 15 raw survivors to 9 after |ρ| ≤ 0.5 dedup. Holdings popularity in 13.3 runs against this reduced list — same treatment as `pv_sweep_xs_v6_dedup.csv` at the pool level.

