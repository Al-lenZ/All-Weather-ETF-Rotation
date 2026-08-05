# Phase 8.1 — half-split IC stability (v6)

Splits the 266-bar valid IS ỹ window in half by bar index and recomputes per-bar Spearman IC + ragged zstat on each half, for the 28 factors in `data/pv_sweep_xs_v6_dedup.csv`.

**Stability pass rule**: sign matches full on both halves AND `|zstat_hK| ≥ 1.5` on both halves. The zstat gate is softened from the full 2.0 screening gate because splitting T in half reduces the expected zstat by √0.5 ≈ 0.71 under a constant-IC null alternative (2.0 · √0.5 ≈ 1.41; rounded up to 1.5 for a small margin).

**Halves**: h1 = 2018-11-30 → 2021-06-11 (133 bars), h2 = 2021-06-18 → 2023-12-29 (133 bars).


## Per-factor half-split IC

| factor | n_full | mean_full | z_full | mean_h1 | z_h1 | mean_h2 | z_h2 | sign_ok | z_ok | pass |
|---|---:|---:|---:|---:|---:|---:|---:|:-:|:-:|:-:|
| alpha_071 | 234 | +0.0589 | +6.65 | +0.0560 | +2.76 | +0.0616 | +6.57 | ✓ | ✓ | **PASS** |
| cvar5_60 | 226 | +0.0422 | +5.60 | +0.0133 | +0.76 | +0.0668 | +6.92 | ✓ | ✗ | FAIL |
| wq_052 | 234 | +0.0458 | +5.52 | +0.0258 | +1.00 | +0.0641 | +6.69 | ✓ | ✗ | FAIL |
| alpha015 | 233 | +0.0543 | +5.13 | +0.0717 | +3.59 | +0.0385 | +3.67 | ✓ | ✓ | **PASS** |
| alpha_062 | 234 | +0.0379 | +4.31 | +0.0254 | +0.76 | +0.0494 | +5.24 | ✓ | ✗ | FAIL |
| alpha028 | 232 | +0.0362 | +3.85 | +0.0415 | +2.04 | +0.0315 | +3.37 | ✓ | ✓ | **PASS** |
| alpha_081 | 234 | +0.0405 | +3.75 | +0.0405 | +1.54 | +0.0404 | +3.73 | ✓ | ✓ | **PASS** |
| alpha_060 | 234 | +0.0260 | +3.63 | +0.0081 | +0.49 | +0.0424 | +4.56 | ✓ | ✗ | FAIL |
| alpha_187 | 234 | +0.0288 | +3.49 | +0.0187 | +1.26 | +0.0382 | +3.63 | ✓ | ✗ | FAIL |
| wq_021 | 234 | -0.0291 | -3.43 | -0.0207 | -0.80 | -0.0368 | -3.99 | ✓ | ✗ | FAIL |
| alpha_170 | 234 | +0.0265 | +3.24 | +0.0119 | +0.30 | +0.0399 | +4.20 | ✓ | ✗ | FAIL |
| alpha_002 | 234 | -0.0140 | -3.22 | +0.0468 | +3.24 | -0.0698 | -7.56 | ✗ | ✓ | FAIL |
| alpha_012 | 234 | -0.0254 | -3.12 | -0.0232 | -1.39 | -0.0275 | -2.99 | ✓ | ✗ | FAIL |
| alpha030 | 233 | +0.0261 | +3.12 | +0.0243 | +1.35 | +0.0277 | +3.03 | ✓ | ✗ | FAIL |
| wq_034 | 234 | -0.0290 | -2.88 | -0.0364 | -1.42 | -0.0222 | -2.62 | ✓ | ✗ | FAIL |
| alpha006 | 233 | -0.0346 | -2.78 | -0.0626 | -3.06 | -0.0091 | -0.92 | ✓ | ✗ | FAIL |
| wq_027 | 234 | -0.0255 | -2.73 | -0.0371 | -2.22 | -0.0148 | -1.65 | ✓ | ✓ | **PASS** |
| wq_032 | 234 | +0.0191 | +2.69 | +0.0182 | +1.26 | +0.0200 | +2.52 | ✓ | ✗ | FAIL |
| wq_088 | 233 | +0.0251 | +2.56 | +0.0268 | +1.08 | +0.0236 | +2.51 | ✓ | ✗ | FAIL |
| wq_096 | 234 | +0.0267 | +2.50 | +0.0446 | +2.68 | +0.0102 | +0.90 | ✓ | ✗ | FAIL |
| wq_039 | 234 | +0.0147 | +2.49 | -0.0045 | -0.23 | +0.0324 | +3.67 | ✗ | ✗ | FAIL |
| wq_003 | 234 | +0.0197 | +2.36 | +0.0158 | +1.01 | +0.0233 | +2.30 | ✓ | ✗ | FAIL |
| wq_060 | 234 | -0.0213 | -2.27 | -0.0161 | -0.17 | -0.0261 | -2.98 | ✓ | ✗ | FAIL |
| wq_058 | 233 | -0.0174 | -2.17 | -0.0195 | -1.32 | -0.0155 | -1.73 | ✓ | ✗ | FAIL |
| alpha021 | 233 | -0.0162 | -2.16 | -0.0122 | -0.79 | -0.0198 | -2.23 | ✓ | ✗ | FAIL |
| wq_056 | 234 | +0.0132 | +2.15 | -0.0081 | -0.24 | +0.0328 | +3.21 | ✗ | ✗ | FAIL |
| alpha_165 | 234 | -0.0288 | -2.05 | -0.0469 | -2.21 | -0.0121 | -0.72 | ✓ | ✗ | FAIL |
| wq_016 | 232 | -0.0161 | -2.00 | -0.0143 | -0.94 | -0.0177 | -1.87 | ✓ | ✗ | FAIL |

**Survivors (5/28)**: alpha_071, alpha015, alpha028, alpha_081, wq_027


## Phase 8 gate

Design §9 requires ≥ 1 factor at |zstat| ≥ 2 surviving half-split stability. 
**Gate passes** (5 survivors). Phase 8.2 (eqw baseline) and downstream may proceed.

## Files

- per-factor per-half : `data/stability_halfsplit_v6.csv`