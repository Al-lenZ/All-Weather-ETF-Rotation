# Two-layer OOS shot — 2026-07-22

Generated: 2026-07-22 22:29:07  

**User-authorized OOS opening** on the Phase 12 × 13 two-layer book (see `block_two_layer_v6_report.md` for the IS-only sweep). Compares two two-layer variants (q=0.20 ε=0.30 plateau pick + q=0.10 ε=0.30 best-raw-IS cell) against the Phase 12 layer-1 canonical (invvol × lw_erc, no trend gate) and the T2 bond_invvol passive book. Two-layer baseline (α off) included so the α layer's OOS contribution is directly readable as Δ.

Windows: **IS = [2019-05-31, 2023-12-31]** (warmup stripped), OOS 2024-01-01 → 2025-07-31 (hold-out > 2025-07-31 sealed). Cost 10 bp/side. Weekly W-FRI grid.

**Warmup handling** (user 2026-07-22): each book's first-live bar (first non-zero net-return) marks the end of its own warmup. The common start = **2019-05-31** is the latest of those across all 5 books, so all IS metrics + per-year table + correlations are computed on the same window and are strictly apples-to-apples. Per-book first-live bars: `two_layer_q20_e30` 2019-05-31; `two_layer_q10_e30` 2019-05-31; `layer1_invvol_lw_erc` 2019-05-31; `T2_bond_invvol` 2018-11-30; `two_layer_baseline` 2019-05-31. Warmup bars are excluded from Sharpe / CAGR / DD denominators, and the per-year table no longer shows the 2018 (all-zero) row.


## 1. Headline: IS / OOS / full per book

| book | IS Sharpe | OOS Sharpe | full Sharpe | decay | IS CAGR | OOS CAGR | full CAGR | IS DD | OOS DD | IS ann vol | OOS ann vol | OOS bars |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| two_layer_q20_e30 | +1.577 | +3.621 | +1.768 | +2.297 | +4.24% | +4.48% | +4.10% | -2.54% | -0.36% | +2.90% | +1.25% | 82 |
| two_layer_q10_e30 | +1.626 | +3.657 | +1.809 | +2.249 | +4.44% | +4.54% | +4.26% | -2.57% | -0.38% | +2.96% | +1.26% | 82 |
| layer1_invvol_lw_erc | +1.570 | +3.499 | +1.765 | +2.229 | +4.19% | +4.52% | +4.08% | -2.55% | -0.38% | +2.88% | +1.31% | 82 |
| T2_bond_invvol | +1.462 | +3.770 | +1.726 | +2.579 | +2.60% | +3.31% | +2.69% | -4.32% | -0.56% | +1.86% | +0.89% | 82 |
| two_layer_baseline | +1.511 | +3.539 | +1.733 | +2.343 | +3.91% | +4.57% | +3.89% | -2.43% | -0.38% | +2.78% | +1.31% | 82 |

## 2. α contribution: Δ vs `two_layer_baseline` (two-layer, α off)

| book | Δ Sharpe IS | Δ Sharpe OOS | Δ CAGR IS | Δ CAGR OOS | Δ DD OOS |
|:---|---:|---:|---:|---:|---:|
| two_layer_q20_e30 | +0.066 | +0.082 | +0.33 pp | -0.09 pp | +0.02 pp |
| two_layer_q10_e30 | +0.115 | +0.118 | +0.53 pp | -0.03 pp | +0.00 pp |
| layer1_invvol_lw_erc | +0.060 | -0.040 | +0.28 pp | -0.05 pp | -0.01 pp |
| T2_bond_invvol | -0.049 | +0.231 | -1.31 pp | -1.26 pp | -0.19 pp |

## 3. Per-calendar-year net return (sum of weekly)

| year | two_layer_q20_e30 | two_layer_q10_e30 | layer1_invvol_lw_erc | T2_bond_invvol | two_layer_baseline |
|:---:|---:|---:|---:|---:|---:|
| 2019 | +5.88% | +5.79% | +5.86% | +1.96% | +4.99% |
| 2020 | +6.75% | +7.24% | +8.79% | +1.54% | +8.18% |
| 2021 | +5.46% | +5.57% | +3.95% | +4.91% | +3.71% |
| 2022 | +0.46% | +0.95% | +0.14% | +1.41% | +0.25% |
| 2023 | +2.57% | +2.64% | +2.12% | +2.76% | +2.22% |
| 2024 | +5.71% | +5.84% | +5.80% | +4.80% | +5.85% |
| 2025 | +1.44% | +1.41% | +1.42% | +0.47% | +1.44% |

Note: 2024–2025 rows are OOS bars.

## 4. Weekly-return correlation

### IS

| | two_layer_q20_e30 | two_layer_q10_e30 | layer1_invvol_lw_erc | T2_bond_invvol | two_layer_baseline |
|:---|---:|---:|---:|---:|---:|
| two_layer_q20_e30 |  +1.000  |  +0.977  |  +0.928  |  +0.441  |  +0.930  |
| two_layer_q10_e30 |  +0.977  |  +1.000  |  +0.907  |  +0.435  |  +0.910  |
| layer1_invvol_lw_erc |  +0.928  |  +0.907  |  +1.000  |  +0.454  |  +0.993  |
| T2_bond_invvol |  +0.441  |  +0.435  |  +0.454  |  +1.000  |  +0.476  |
| two_layer_baseline |  +0.930  |  +0.910  |  +0.993  |  +0.476  |  +1.000  |

### OOS

| | two_layer_q20_e30 | two_layer_q10_e30 | layer1_invvol_lw_erc | T2_bond_invvol | two_layer_baseline |
|:---|---:|---:|---:|---:|---:|
| two_layer_q20_e30 |  +1.000  |  +0.995  |  +0.973  |  +0.342  |  +0.972  |
| two_layer_q10_e30 |  +0.995  |  +1.000  |  +0.964  |  +0.378  |  +0.960  |
| layer1_invvol_lw_erc |  +0.973  |  +0.964  |  +1.000  |  +0.324  |  +0.997  |
| T2_bond_invvol |  +0.342  |  +0.378  |  +0.324  |  +1.000  |  +0.318  |
| two_layer_baseline |  +0.972  |  +0.960  |  +0.997  |  +0.318  |  +1.000  |

## 5. Read

- OOS Sharpe: two_layer q=0.20 ε=0.30 = **+3.621**, two_layer q=0.10 ε=0.30 = **+3.657**, layer-1 canonical = +3.499, T2 = +3.770, baseline (α off) = +3.539.
- α layer OOS Δ = q20: +0.082 Sharpe, q10: +0.118 Sharpe.


Decay ratio (OOS Sharpe / IS Sharpe) close to 1.0 means the IS edge survived; ratio < 0.5 means significant decay. Compare across the 5 books to isolate which layer (α, budget, or bond passive) held up OOS.

