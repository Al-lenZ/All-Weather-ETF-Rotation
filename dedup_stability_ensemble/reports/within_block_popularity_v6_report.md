# Phase 13.3 — within-block holdings popularity (v6 pool, IS)

Generated: 2026-07-22 16:20:23  

Applied `BLOCK_MERGES = {smallcap_cn → broad_cn}` at load. Top-⌈q·N_b(t)⌉ selection with q = 0.2 (matches production long_q20 finalist). IS-only; no cost, no PnL — pure selection diagnostic.

**Verdict thresholds.**
- `INV_VOL_LIKE`: mean Jaccard vs 1/σ null ≥ 0.7 AND effective N within ±20% of the 1/σ null's eff_N. Reading: the factor's top-K is essentially the low-σ core; it's an inv-vol dressing.
- `ROTATIONAL`:   mean Jaccard vs 1/σ null ≤ 0.5 AND per-bar turnover ≥ 0.15. Reading: the top-K meaningfully rotates across the block; the factor is doing actual selection.
- `MIXED`:        everything in between.

**Read.** Sector_cn's 13.2 top rows (var5_60, cvar5_60, kurt-family) are downside-risk factors; if the ranked risk-adjusted label rewards low-σ names in the tails, we should expect them to collapse to a bank / utility core (`INV_VOL_LIKE`). If most sector_cn 13.2b survivors carry that verdict, 13.2c (raw-label re-screen using block-internal rank(fwd)) opens.


## 1. Verdict counts per block

| block | ROTATIONAL | MIXED | INV_VOL_LIKE | total |
|:---|---:|---:|---:|---:|
| broad_cn | 24 | 0 | 0 | 24 |
| sector_cn | 27 | 0 | 0 | 27 |

## 2. `broad_cn` — factor popularity summary

1/σ null on this block: **eff_N = 11.95**, top-10 names → 510760.XSHG(98%); 510210.XSHG(91%); 512090.XSHG(85%); 510880.XSHG(62%); 515450.XSHG(61%); 510180.XSHG(49%); 515100.XSHG(48%); 515080.XSHG(46%); 515800.XSHG(40%); 512890.XSHG(33%)


| factor | pol | zstat | mean_K | eff_N | eff_N/null | jaccard_null | turnover | verdict |
|:---|:---:|---:|---:|---:|---:|---:|---:|:---|
| alpha_179 | raw | 4.48 | 2.8 | 20.11 | 1.68 | 0.132 | 0.554 | `ROTATIONAL` |
| alpha_025 | raw | 3.99 | 2.8 | 20.51 | 1.72 | 0.144 | 0.396 | `ROTATIONAL` |
| h_vol_ratio_48 | rev | -3.39 | 2.8 | 23.43 | 1.96 | 0.144 | 0.510 | `ROTATIONAL` |
| alpha015 | raw | 3.37 | 2.8 | 17.77 | 1.49 | 0.168 | 0.345 | `ROTATIONAL` |
| alpha_002 | raw | 3.35 | 2.8 | 20.64 | 1.73 | 0.142 | 0.626 | `ROTATIONAL` |
| alpha017 | raw | 3.21 | 2.8 | 19.94 | 1.67 | 0.123 | 0.441 | `ROTATIONAL` |
| alpha_071 | raw | 3.16 | 2.8 | 12.98 | 1.09 | 0.186 | 0.166 | `ROTATIONAL` |
| alpha_007 | rev | -3.03 | 2.8 | 21.25 | 1.78 | 0.130 | 0.625 | `ROTATIONAL` |
| wq_092 | raw | 2.85 | 2.8 | 21.27 | 1.78 | 0.151 | 0.607 | `ROTATIONAL` |
| alpha_082 | raw | 2.79 | 2.8 | 22.30 | 1.87 | 0.151 | 0.602 | `ROTATIONAL` |
| alpha_102 | raw | 2.70 | 2.8 | 19.29 | 1.61 | 0.090 | 0.234 | `ROTATIONAL` |
| alpha020 | raw | 2.66 | 2.8 | 21.98 | 1.84 | 0.137 | 0.593 | `ROTATIONAL` |
| h_mom_decay_12_48 | raw | 2.59 | 2.8 | 18.50 | 1.55 | 0.110 | 0.269 | `ROTATIONAL` |
| rsrs_18_250 | raw | 2.57 | 2.8 | 22.63 | 1.89 | 0.138 | 0.438 | `ROTATIONAL` |
| alpha006 | rev | -2.37 | 2.8 | 19.52 | 1.63 | 0.193 | 0.289 | `ROTATIONAL` |
| alpha002 | rev | -2.22 | 2.8 | 21.50 | 1.80 | 0.134 | 0.565 | `ROTATIONAL` |
| wq_034 | raw | 2.17 | 2.8 | 18.81 | 1.57 | 0.153 | 0.568 | `ROTATIONAL` |
| wq_011 | raw | 2.16 | 2.8 | 21.99 | 1.84 | 0.118 | 0.622 | `ROTATIONAL` |
| wq_044 | rev | -2.16 | 2.8 | 23.20 | 1.94 | 0.137 | 0.604 | `ROTATIONAL` |
| body_ratio_5 | rev | -2.08 | 2.8 | 22.17 | 1.85 | 0.145 | 0.619 | `ROTATIONAL` |
| mom_accel_10 | raw | 2.07 | 2.8 | 20.20 | 1.69 | 0.123 | 0.513 | `ROTATIONAL` |
| h_mr_speed_24 | raw | 2.06 | 2.8 | 21.29 | 1.78 | 0.150 | 0.373 | `ROTATIONAL` |
| alpha016 | raw | 2.03 | 2.8 | 20.84 | 1.74 | 0.090 | 0.582 | `ROTATIONAL` |
| wq_036 | rev | -2.00 | 2.8 | 22.21 | 1.86 | 0.133 | 0.613 | `ROTATIONAL` |

### `broad_cn` — top ROTATIONAL factors: which names get picked most?

- **alpha_179** (raw, jacc=0.13, turn=0.55): 515080.XSHG(35%); 510230.XSHG(35%); 510880.XSHG(34%); 515450.XSHG(31%); 159949.XSHE(31%); 512100.XSHG(29%); 159915.XSHE(29%); 159967.XSHE(27%); 159905.XSHE(24%); 510500.XSHG(22%)
- **alpha_025** (raw, jacc=0.14, turn=0.40): 510230.XSHG(40%); 512100.XSHG(30%); 510880.XSHG(30%); 562000.XSHG(30%); 159949.XSHE(29%); 515450.XSHG(26%); 159915.XSHE(25%); 510500.XSHG(25%); 515080.XSHG(24%); 510210.XSHG(22%)
- **h_vol_ratio_48** (rev, jacc=0.14, turn=0.51): 515450.XSHG(30%); 510230.XSHG(26%); 515800.XSHG(24%); 159901.XSHE(24%); 510180.XSHG(23%); 512100.XSHG(23%); 510300.XSHG(22%); 510880.XSHG(22%); 159905.XSHE(22%); 512090.XSHG(21%)
- **alpha015** (raw, jacc=0.17, turn=0.35): 510880.XSHG(54%); 515450.XSHG(46%); 512100.XSHG(44%); 510230.XSHG(38%); 510210.XSHG(33%); 515080.XSHG(33%); 159905.XSHE(31%); 159967.XSHE(30%); 159966.XSHE(28%); 562310.XSHG(24%)
- **alpha_002** (raw, jacc=0.14, turn=0.63): 510880.XSHG(32%); 159967.XSHE(31%); 510230.XSHG(29%); 159915.XSHE(27%); 515450.XSHG(27%); 159949.XSHE(25%); 510050.XSHG(24%); 510210.XSHG(22%); 512100.XSHG(21%); 159901.XSHE(20%)

## 2. `sector_cn` — factor popularity summary

1/σ null on this block: **eff_N = 34.20**, top-10 names → 560700.XSHG(100%); 512950.XSHG(100%); 159887.XSHE(100%); 561580.XSHG(100%); 512800.XSHG(92%); 561190.XSHG(86%); 159825.XSHE(82%); 510150.XSHG(77%); 159625.XSHE(70%); 515900.XSHG(70%)


| factor | pol | zstat | mean_K | eff_N | eff_N/null | jaccard_null | turnover | verdict |
|:---|:---:|---:|---:|---:|---:|---:|---:|:---|
| var5_60 | raw | 4.70 | 7.3 | 56.79 | 1.66 | 0.109 | 0.192 | `ROTATIONAL` |
| wq_039 | raw | 4.57 | 7.4 | 73.35 | 2.14 | 0.168 | 0.538 | `ROTATIONAL` |
| h_accel_12 | raw | 4.54 | 7.4 | 75.78 | 2.22 | 0.168 | 0.545 | `ROTATIONAL` |
| ma_disp | raw | 4.28 | 7.3 | 62.54 | 1.83 | 0.164 | 0.245 | `ROTATIONAL` |
| h_mom_decay_6_24 | raw | 4.09 | 7.4 | 67.98 | 1.99 | 0.162 | 0.336 | `ROTATIONAL` |
| alpha_012 | rev | -3.30 | 7.4 | 67.29 | 1.97 | 0.181 | 0.527 | `ROTATIONAL` |
| alpha_142 | raw | 3.07 | 7.4 | 59.29 | 1.73 | 0.153 | 0.338 | `ROTATIONAL` |
| alpha_187 | raw | 3.06 | 7.4 | 73.04 | 2.14 | 0.184 | 0.324 | `ROTATIONAL` |
| yj15_bias_mom_60_20 | rev | -2.97 | 7.3 | 68.61 | 2.01 | 0.114 | 0.286 | `ROTATIONAL` |
| wq_003 | raw | 2.93 | 7.4 | 73.99 | 2.16 | 0.177 | 0.492 | `ROTATIONAL` |
| wq_045 | rev | -2.82 | 7.4 | 74.94 | 2.19 | 0.183 | 0.574 | `ROTATIONAL` |
| mom_accel_5 | raw | 2.79 | 7.4 | 73.39 | 2.15 | 0.170 | 0.642 | `ROTATIONAL` |
| wq_009 | rev | -2.76 | 7.4 | 74.54 | 2.18 | 0.194 | 0.550 | `ROTATIONAL` |
| wq_068 | rev | -2.75 | 7.4 | 73.68 | 2.15 | 0.181 | 0.515 | `ROTATIONAL` |
| h_mom_decay_12_48 | raw | 2.75 | 7.3 | 64.29 | 1.88 | 0.138 | 0.241 | `ROTATIONAL` |
| alpha028 | raw | 2.71 | 7.4 | 68.82 | 2.01 | 0.178 | 0.371 | `ROTATIONAL` |
| h_vol_spike_24 | raw | 2.65 | 7.3 | 75.57 | 2.21 | 0.138 | 0.545 | `ROTATIONAL` |
| wq_034 | rev | -2.55 | 7.4 | 71.10 | 2.08 | 0.197 | 0.525 | `ROTATIONAL` |
| wq_054 | raw | 2.52 | 7.4 | 75.00 | 2.19 | 0.172 | 0.559 | `ROTATIONAL` |
| kurt_40 | rev | -2.41 | 7.3 | 68.30 | 2.00 | 0.148 | 0.242 | `ROTATIONAL` |
| alpha021 | rev | -2.28 | 7.4 | 72.83 | 2.13 | 0.185 | 0.349 | `ROTATIONAL` |
| ret_skew_20 | raw | 2.27 | 7.4 | 70.22 | 2.05 | 0.183 | 0.312 | `ROTATIONAL` |
| autocorr_20 | raw | 2.19 | 7.4 | 70.43 | 2.06 | 0.176 | 0.334 | `ROTATIONAL` |
| wq_008 | raw | 2.18 | 7.4 | 63.54 | 1.86 | 0.133 | 0.485 | `ROTATIONAL` |
| wq_058 | rev | -2.13 | 7.4 | 75.18 | 2.20 | 0.176 | 0.544 | `ROTATIONAL` |
| alpha_071 | raw | 2.12 | 7.4 | 41.44 | 1.21 | 0.189 | 0.152 | `ROTATIONAL` |
| wq_016 | rev | -2.10 | 7.4 | 73.49 | 2.15 | 0.161 | 0.538 | `ROTATIONAL` |

### `sector_cn` — top ROTATIONAL factors: which names get picked most?

- **var5_60** (raw, jacc=0.11, turn=0.19): 159819.XSHE(47%); 512200.XSHG(44%); 159611.XSHE(43%); 159852.XSHE(42%); 515880.XSHG(41%); 516510.XSHG(40%); 159928.XSHE(40%); 515750.XSHG(37%); 515230.XSHG(36%); 512010.XSHG(34%)
- **wq_039** (raw, jacc=0.17, turn=0.54): 512880.XSHG(34%); 512660.XSHG(31%); 512800.XSHG(31%); 159928.XSHE(30%); 515170.XSHG(28%); 512010.XSHG(27%); 512200.XSHG(27%); 159992.XSHE(26%); 515220.XSHG(26%); 512980.XSHG(26%)
- **h_accel_12** (raw, jacc=0.17, turn=0.54): 159939.XSHE(32%); 512200.XSHG(29%); 159819.XSHE(28%); 159928.XSHE(28%); 159992.XSHE(28%); 512800.XSHG(28%); 512660.XSHG(27%); 512010.XSHG(27%); 515220.XSHG(27%); 512880.XSHG(26%)
- **ma_disp** (raw, jacc=0.16, turn=0.25): 516970.XSHG(42%); 512200.XSHG(38%); 561190.XSHG(37%); 512070.XSHG(36%); 512980.XSHG(36%); 159745.XSHE(36%); 159928.XSHE(35%); 159768.XSHE(35%); 159625.XSHE(34%); 159993.XSHE(34%)
- **h_mom_decay_6_24** (raw, jacc=0.16, turn=0.34): 512880.XSHG(34%); 512010.XSHG(34%); 159939.XSHE(34%); 512800.XSHG(34%); 159928.XSHE(31%); 515790.XSHG(30%); 512690.XSHG(30%); 515220.XSHG(29%); 512710.XSHG(28%); 515650.XSHG(28%)

## 3. Read for 13.2c / 13.4

- **`broad_cn`**: ROTATIONAL 24 (100%), MIXED 0, INV_VOL_LIKE 0 (0%). Enough ROTATIONAL factors to advance to 13.4 book construction against the block-eqw null.

- **`sector_cn`**: ROTATIONAL 27 (100%), MIXED 0, INV_VOL_LIKE 0 (0%). Enough ROTATIONAL factors to advance to 13.4 book construction against the block-eqw null.

