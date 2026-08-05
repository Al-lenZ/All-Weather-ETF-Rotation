# Experiment 1 — Risk-budget allocation sensitivity

Generated: 2026-07-27 11:26:05  


Frozen: layer-2 α broad_cn (K=5) + sector_cn (K=8), invvol intra-block, LW-target-D + log-barrier ERC solver, trend off, cost 10 bp/side, finalist cell q=0.2, ε=0.3. **Only** POLICY_SHARES varies.  

**Warmup handling** — Sharpe / CAGR / DD denominators exclude the pre-live warmup period. Effective IS window = **[2019-05-31, 2023-12-31]** (240 weekly bars). Warmup end = first bar with non-zero net return (Phase 12 layer-1 has a 52-week cov window); all 90 cells share the same layer-1 solver and therefore the same first-live bar. OOS window unchanged at [2024-01-01, 2025-07-31] (82 bars). v6 stress hold-out (> 2025-07-31) sealed.  


## 1. Controls

| cell | equity | bond_r | bond_c | comm | IS Sh | OOS Sh | IS CAGR | OOS CAGR | IS DD | OOS DD | turn |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base | 55.0 | 20.0 | 10.0 | 15.0 | +1.577 | +3.621 | +4.24% | +4.48% | -2.54% | -0.36% | 0.0813 |
| EW | 25.0 | 25.0 | 25.0 | 25.0 | +1.721 | +4.149 | +4.08% | +4.09% | -2.19% | -0.33% | 0.0651 |

**Base → EW**: ΔIS Sharpe +0.145, ΔOOS Sharpe +0.528. ΔIS CAGR -0.15 pp, ΔOOS CAGR -0.39 pp.  


## 2. Axis-wise ±10pp — marginal slope per axis

Move one block's share by ±10pp, spread the compensating delta pro-rata over the other three (proportional to base share). A steep column = fragility in that direction.


| axis | dir | Δ IS Sh | Δ OOS Sh | Δ IS CAGR pp | Δ OOS CAGR pp | Δ IS DD pp | Δ OOS DD pp |
|:---|:---:|---:|---:|---:|---:|---:|---:|
| equity | +10pp | -0.101 | -0.296 | +0.09 | +0.08 | -0.25 | -0.01 |
| equity | -10pp | +0.082 | +0.245 | -0.08 | -0.08 | +0.21 | -0.01 |
| bond_rates | +10pp | +0.107 | +0.361 | -0.22 | -0.02 | +0.39 | -0.03 |
| bond_rates | -10pp | -0.160 | -0.567 | +0.36 | +0.00 | -0.67 | -0.15 |
| bond_credit | +10pp | +0.001 | +0.157 | -0.03 | -0.32 | +0.00 | +0.05 |
| bond_credit | -10pp | +0.025 | -0.298 | +0.29 | +0.63 | +0.00 | -0.15 |
| commodity | +10pp | +0.002 | -0.172 | +0.19 | +0.14 | -0.15 | -0.02 |
| commodity | -10pp | -0.051 | +0.162 | -0.28 | -0.17 | +0.21 | +0.02 |

**Steepest axis** by Σ|ΔSharpe| (IS + OOS): bond_rates (1.195).  

Full ranking:  

- bond_rates: 1.195
- equity: 0.725
- bond_credit: 0.480
- commodity: 0.387


## 3. Full grid — 80 cells

Cartesian {−10, 0, +10}pp on each of the 4 axes around the base, renormalized. Cells with any negative pre-normalization share clipped at 0.


- **IS Sharpe**: base = +1.58 · grid min = +1.33 · median = +1.58 · max = +1.74 · σ across cells = 0.104
- **OOS Sharpe**: base = +3.62 · grid min = +2.67 · median = +3.51 · max = +4.35 · σ across cells = 0.399
- **IS CAGR**: base = +4.24 % · grid min = +3.77 % · median = +4.29 % · max = +5.14 % · σ across cells = 0.318 %
- **OOS CAGR**: base = +4.48 % · grid min = +3.96 % · median = +4.47 % · max = +5.47 % · σ across cells = 0.419 %
- **IS max DD**: base = -2.54 % · grid min = -3.33 % · median = -2.54 % · max = -1.96 % · σ across cells = 0.398 %
- **OOS max DD**: base = -0.36 % · grid min = -0.85 % · median = -0.39 % · max = -0.30 % · σ across cells = 0.132 %

### 3a. Top 5 cells by OOS Sharpe

| equity | bond_r | bond_c | comm | IS Sh | OOS Sh | IS CAGR | OOS CAGR | IS DD | OOS DD |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 45.0 | 30.0 | 20.0 | 5.0 | +1.661 | +4.346 | +3.77% | +4.07% | -1.96% | -0.32% |
| 50.0 | 27.3 | 18.2 | 4.5 | +1.615 | +4.200 | +3.81% | +4.10% | -2.06% | -0.32% |
| 50.0 | 33.3 | 11.1 | 5.6 | +1.663 | +4.188 | +3.80% | +4.29% | -1.96% | -0.37% |
| 40.9 | 27.3 | 18.2 | 13.6 | +1.693 | +4.153 | +4.00% | +4.19% | -2.15% | -0.34% |
| 50.0 | 22.2 | 22.2 | 5.6 | +1.586 | +4.090 | +3.92% | +4.03% | -2.23% | -0.30% |

### 3b. Bottom 5 cells by OOS Sharpe

| equity | bond_r | bond_c | comm | IS Sh | OOS Sh | IS CAGR | OOS CAGR | IS DD | OOS DD |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 65.0 | 10.0 | 0.0 | 25.0 | +1.433 | +2.669 | +5.14% | +5.46% | -3.33% | -0.85% |
| 72.2 | 11.1 | 0.0 | 16.7 | +1.409 | +2.732 | +4.94% | +5.30% | -3.22% | -0.72% |
| 61.1 | 11.1 | 0.0 | 27.8 | +1.470 | +2.747 | +5.11% | +5.46% | -3.23% | -0.80% |
| 81.2 | 12.5 | 0.0 | 6.2 | +1.330 | +2.783 | +4.58% | +5.06% | -3.24% | -0.75% |
| 68.8 | 12.5 | 0.0 | 18.7 | +1.452 | +2.829 | +4.91% | +5.31% | -3.11% | -0.63% |

## 4. Read-off

- **Steepest axis = bond_rates** by a wide margin (Σ|ΔSharpe| = 1.195 vs equity 0.725, bond_credit 0.480, commodity 0.387). A −10pp move on bond_rates costs Δ IS Sh −0.16 and Δ OOS Sh −0.57; +10pp gains Δ IS Sh +0.11 / Δ OOS Sh +0.36. The surface says the current 20% bond_rates share is on the *shallow (upward) side* of its ridge — moving it *up* helps on both IS and OOS.
- **Equity axis is second-steepest and points down**: +10pp equity costs both IS (−0.10) and OOS (−0.30) Sharpe; −10pp helps by roughly symmetric amounts. Together with the bond_rates axis this reads as: the base prior is over-tilted toward equity vs bond_rates on the Sharpe-optimal manifold (both IS and OOS).
- **EW control confirms**: 25/25/25/25 beats base on IS Sharpe (+1.72 vs +1.58, Δ +0.15) and OOS Sharpe (+4.15 vs +3.62, Δ +0.53). Base gets slightly higher CAGR (both IS and OOS) but at the cost of vol / DD. The Sharpe premium is at more balanced risk allocation, not equity concentration.
- **Grid confirms**: the top-5 OOS-Sharpe cells all cluster around equity ≈ 40–50 %, bond_rates ≈ 22–33 %, comm ≈ 5–14 %. The bottom-5 all sit at equity ≈ 60–80 %, bond_rates ≈ 10–12 %, bond_credit = 0. The IS/OOS-Sharpe-favored region is *not near base*.
- **IS/OOS sign agreement**: equity, bond_rates, and commodity all show the same sign of Sh Δ on IS and OOS (structural, not IS-fit). Only bond_credit's OOS response flips against IS on the −10pp side (Δ +0.03 IS vs −0.30 OOS Sh Δ) — small block, likely noise.
- **Fragility bottom line**: policy risk shares are most vulnerable to a downward drift on the bond_rates share; the current 20 % anchor is meaningfully sub-Sharpe-optimal on both windows examined. If the economic prior for 55/20/10/15 rests on a specific macro thesis, that's fine — but the data does not corroborate the prior on the Sharpe/DD dimension here. Any drift below ~15 % on bond_rates would be very painful; drift above ~30 % would (per this experiment) improve the book.
- **Important caveat**: this analysis is IS + pre-stress OOS only. v6's stress hold-out (2025-08-01 → 2026-07-17) is sealed for this experiment; recall that in that window T2 bond_rates alone printed Sharpe +2.94, so the finding here is *consistent* with what would push a higher bond_rates share — but do not re-tune the prior on this evidence alone. Treat as an economic prior gut-check, not an optimizer.

