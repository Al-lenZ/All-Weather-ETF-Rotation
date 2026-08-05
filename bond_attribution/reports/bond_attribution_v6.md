# v6 static — bond-tilt PnL attribution (IS window)

Generated: 2026-07-22 12:07:10  

Companion to `block_neutral_ic_v6.md`. Signal-side showed the long-book ensemble α's IC is between-block (bonds vs. rest); this asks whether that shows up in PnL.

**Books.** All cost 10 bp/side, static rebalance to target each W-FRI bar, IS = bars ≤ 2023-12-31.
- **long_q05, long_q20** — the static ensemble baselines from `v6_static/{cell}/ensemble_net_ret.csv`; α-ranked, top-⌈q·N_t⌉, inv_vol sized. Anchors.
- **T1 universe_invvol** — no ranking: every eligible member weighted ∝ 1/σ_causal.
- **T2 bond_invvol** — restrict eligible set to blocks ('bond_rates', 'bond_credit'), weight ∝ 1/σ.
- **T3 bond_eqw** — same restriction, weight = 1/N.
- **T4 equity_invvol** — restrict eligible set to equity blocks ('sector_cn', 'broad_cn', 'cross_border_hk', 'cross_border_dm', 'smallcap_cn'), weight ∝ 1/σ. Equity-β leg for the bivariate decomp in §6.


## 1. IS headline

| book | Sharpe | CAGR | max DD | ann vol | avg turnover | mean N | mean K |
|:---|---:|---:|---:|---:|---:|---:|---:|
| long_q05 | +1.052 | +2.11% | -4.68% | +2.11% | 0.272 | 70.0 | 3.7 |
| long_q20 | +1.002 | +3.48% | -5.24% | +3.76% | 0.281 | 70.0 | 13.2 |
| T1_universe_invvol | +0.707 | +5.46% | -8.09% | +8.75% | 0.055 | 69.0 | 69.0 |
| T2_bond_invvol | +1.425 | +2.40% | -4.26% | +1.78% | 0.050 | 5.2 | 5.2 |
| T3_bond_eqw | +1.122 | +2.78% | -4.37% | +2.65% | 0.035 | 5.3 | 5.3 |
| T4_equity_invvol | +0.375 | +5.28% | -18.93% | +15.89% | 0.045 | 61.7 | 61.7 |

## 2. IS mean block allocation (share of book by block)

| book | bond_credit | bond_rates | broad_cn | commodity_other | cross_border_dm | cross_border_hk | metals | sector_cn | smallcap_cn |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| long_q05 |  27.1% |  68.7% |   0.4% |   0.2% |   1.5% |   0.0% |   1.9% |   0.1% |   0.0% |
| long_q20 |  25.7% |  53.3% |   5.3% |   0.5% |   4.6% |   1.5% |   3.3% |   5.1% |   0.8% |
| T1_universe_invvol |  18.3% |  29.4% |  14.2% |   0.4% |   4.8% |   4.8% |   3.2% |  22.6% |   2.3% |
| T2_bond_invvol |  29.5% |  70.5% |    — |    — |    — |    — |    — |    — |    — |
| T3_bond_eqw |  25.6% |  74.4% |    — |    — |    — |    — |    — |    — |    — |
| T4_equity_invvol |    — |    — |  27.8% |    — |   9.2% |  10.2% |    — |  48.6% |   4.1% |

## 3. Per-calendar-year IS stats

### return (sum of weekly net)

| year | long_q05 | long_q20 | T1_universe_invvol | T2_bond_invvol | T3_bond_eqw | T4_equity_invvol |
|:---:|---:|---:|---:|---:|---:|---:|
| 2018 |  +1.44%  |  +1.02%  |  -1.87%  |  +1.44%  |  +2.69%  |  -5.51%  |
| 2019 |  +4.38%  |  +9.69%  |  +16.88%  |  +2.19%  |  +2.20%  |  +30.97%  |
| 2020 |  +0.73%  |  +6.51%  |  +21.09%  |  +1.54%  |  +1.34%  |  +31.25%  |
| 2021 |  +3.86%  |  +3.89%  |  +4.73%  |  +4.91%  |  +7.52%  |  +3.19%  |
| 2022 |  +0.69%  |  -1.89%  |  -4.40%  |  +1.41%  |  -0.40%  |  -14.63%  |
| 2023 |  +1.35%  |  +1.93%  |  -1.66%  |  +2.76%  |  +3.33%  |  -11.78%  |

### Sharpe

| year | long_q05 | long_q20 | T1_universe_invvol | T2_bond_invvol | T3_bond_eqw | T4_equity_invvol |
|:---:|---:|---:|---:|---:|---:|---:|
| 2018 |  +2.142  |  +2.092  |  -1.225  |  +2.142  |  +1.695  |  -1.654  |
| 2019 |  +1.846  |  +3.324  |  +2.196  |  +1.375  |  +1.376  |  +2.079  |
| 2020 |  +0.187  |  +0.895  |  +1.446  |  +0.476  |  +0.407  |  +1.506  |
| 2021 |  +2.535  |  +1.044  |  +0.486  |  +2.889  |  +2.212  |  +0.202  |
| 2022 |  +1.014  |  -1.270  |  -0.698  |  +1.722  |  -0.131  |  -0.830  |
| 2023 |  +1.750  |  +1.580  |  -0.391  |  +3.385  |  +3.274  |  -0.901  |

### max drawdown

| year | long_q05 | long_q20 | T1_universe_invvol | T2_bond_invvol | T3_bond_eqw | T4_equity_invvol |
|:---:|---:|---:|---:|---:|---:|---:|
| 2018 |  -0.06%  |  -0.05%  |  -2.52%  |  -0.06%  |  -1.11%  |  -6.51%  |
| 2019 |  -1.69%  |  -1.33%  |  -6.85%  |  -1.06%  |  -1.06%  |  -12.97%  |
| 2020 |  -5.19%  |  -5.95%  |  -9.81%  |  -4.65%  |  -4.80%  |  -13.06%  |
| 2021 |  -0.69%  |  -1.82%  |  -7.34%  |  -1.01%  |  -1.94%  |  -11.37%  |
| 2022 |  -0.72%  |  -2.66%  |  -7.93%  |  -0.71%  |  -2.88%  |  -25.54%  |
| 2023 |  -0.73%  |  -1.17%  |  -4.40%  |  -0.70%  |  -0.80%  |  -17.21%  |

## 4. IS weekly-net-return correlation

| | long_q05 | long_q20 | T1_universe_invvol | T2_bond_invvol | T3_bond_eqw | T4_equity_invvol |
|:---|---:|---:|---:|---:|---:|---:|
| long_q05 |  +1.000  |  +0.474  |  +0.061  |  +0.801  |  +0.583  |  -0.057  |
| long_q20 |  +0.474  |  +1.000  |  +0.744  |  +0.262  |  +0.298  |  +0.609  |
| T1_universe_invvol |  +0.061  |  +0.744  |  +1.000  |  -0.038  |  +0.159  |  +0.947  |
| T2_bond_invvol |  +0.801  |  +0.262  |  -0.038  |  +1.000  |  +0.788  |  -0.108  |
| T3_bond_eqw |  +0.583  |  +0.298  |  +0.159  |  +0.788  |  +1.000  |  +0.144  |
| T4_equity_invvol |  -0.057  |  +0.609  |  +0.947  |  -0.108  |  +0.144  |  +1.000  |

## 5. OLS regression: baseline ~ α + β · X, IS (univariate)

β near 1 with R² ≈ 1 and residual Sharpe ≈ 0 means the baseline is X up to noise (no within-block selection value beyond block composition + inv-vol sizing). long_q05 is a clean single-block book (bonds), so its T2 fit reads directly; long_q20 mixes bond + equity blocks and is *misspecified* by any single regressor — see §6 for the bivariate decomposition.


| baseline | n | β | R² | α (ann) | resid Sharpe |
|:---|---:|---:|---:|---:|---:|
| long_q05 | 292 | +0.947 | +0.642 | -0.19% | -0.149 |
| long_q20 | 292 | +0.552 | +0.069 | +2.36% | +0.652 |
| long_q05  (~ T1 universe_invvol) | 292 | +0.015 | +0.004 | +2.12% | +1.011 |
| long_q20  (~ T1 universe_invvol) | 292 | +0.319 | +0.553 | +1.79% | +0.713 |
| long_q05  (~ T4 equity_invvol) | 292 | -0.008 | +0.003 | +2.26% | +1.076 |
| long_q20  (~ T4 equity_invvol) | 292 | +0.144 | +0.371 | +2.91% | +0.976 |

## 6. OLS regression: baseline ~ α + β_bond · T2 + β_eq · T4, IS

The bivariate decomposition. T2 and T4 span the bond-block-β and equity-block-β legs of the pool; anything the baseline earns beyond a linear combination of them is *within-block* selection value. Compare α(ann) and residual Sharpe here vs. the univariate rows in §5: if the baseline is holding a slice of equity β that a T2-only regression can't see, the residual shrinks once T4 is added.


| baseline | n | β_bond | β_eq | R² | α (ann) | resid Sharpe |
|:---|---:|---:|---:|---:|---:|---:|
| long_q05 | 292 | +0.951 | +0.004 | +0.642 | -0.22% | -0.175 |
| long_q20 | 292 | +0.700 | +0.152 | +0.480 | +1.08% | +0.399 |

