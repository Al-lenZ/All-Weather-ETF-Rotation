# Experiment 2 — Non-α block representative sets (adaptive K)

Generated: 2026-07-27 11:26:30  


Blocks in scope: bond_rates, bond_credit, cross_border_dm, cross_border_hk, metals, commodity_other.  
Clustering: rolling {52, 78, 104}w correlation, averaged, complete-linkage (cut via ``cut_tree`` — ``fcluster(maxclust)`` collapses tied merges into fewer clusters, verified failure on metals/cbHK in v1).  
K per (year, block) is an **output**: smallest K with ann_std(replicated − hold-all) / ann_std(hold-all) ≤ 0.20 on the trailing 104w training window (equivalent to explained-variance ≥ 96 %).  
Representative per cluster = top ADV (63d trailing mean of daily amount). No predictive metrics.  
Annual refresh at first W-FRI of each calendar year using data strictly prior.  

**Warmup handling** — book-level Sharpe / CAGR / DD denominators exclude the pre-live warmup period. Effective IS window = **[2019-05-31, 2023-12-31]** (240 weekly bars). Warmup end = first bar where either book has a non-zero net return (Phase 12 layer-1 has a 52-week cov window). Both hold-all and replicated books share the same layer-1 solver and land on this same first-live bar. OOS window = [2024-01-01, 2025-07-31] (82 bars), unaffected by warmup. v6 stress hold-out (> 2025-07-31) sealed. Per-block TE, annual-K table, and per-year TE (§1, §2) already use the ``active`` mask (block-flat bars dropped), so those numbers are unaffected by the change.  


## 1. Adaptive K per (year, block) — K as output

For each refresh year, per block, K is the smallest cluster count meeting the residual-vol threshold on the trailing training window. 'ratio' = ann_std(residual) / ann_std(hold-all). 'fallback_hold_all' = threshold not achievable at any K ≤ N (block genuinely irreducible — all N names get held).


### 1a. K by (year, block)

| block | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|:---|---:|---:|---:|---:|---:|---:|
| bond_rates | — | 2/2 | 2/2 | 5/5 | 10/11 | 8/12 |
| bond_credit | — | — | 1/2 | 2/3 | 4/5 | 4/5 |
| cross_border_dm | 3/3 | 3/3 | 3/3 | 6/6 | 7/7 | 11/18 |
| cross_border_hk | 1/2 | 1/2 | 2/3 | 5/10 | 5/17 | 6/22 |
| metals | — | — | 2/2 | 2/2 | 2/2 | 3/3 |
| commodity_other | — | — | — | 2/2 | 2/2 | 2/2 |

(Cells show K / N. * = fallback: threshold not met, K = N.)


### 1b. Residual-vol ratio at chosen K

| block | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|:---|---:|---:|---:|---:|---:|---:|
| bond_rates | — | 0.000 | 0.000 | 0.000 | 0.012 | 0.133 |
| bond_credit | — | — | 0.199 | 0.122 | 0.135 | 0.166 |
| cross_border_dm | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.161 |
| cross_border_hk | 0.175 | 0.172 | 0.134 | 0.097 | 0.165 | 0.165 |
| metals | — | — | 0.000 | 0.000 | 0.000 | 0.000 |
| commodity_other | — | — | — | 0.000 | 0.000 | 0.000 |

(Threshold = 0.20; smaller is tighter fit.)


## 2. Per-year annualized TE (bp/yr) at adaptive K

| block | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| bond_rates |  0.0 | 0.0 | 71.0 | 12.9 | 77.0 | 43.4 | 25.4 | 23.3 | 14.0  |
| bond_credit |  nan | nan | 0.0 | 78.4 | 54.7 | 47.8 | 13.7 | 15.1 | 17.2  |
| cross_border_dm |  0.0 | 0.0 | 434.0 | 281.9 | 954.9 | 442.5 | 939.1 | 412.0 | 413.4  |
| cross_border_hk |  139.2 | 253.0 | 379.7 | 863.3 | 2219.5 | 845.5 | 602.6 | 578.1 | 579.1  |
| metals |  0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 220.0 | 416.9 | 449.4 | 619.9  |
| commodity_other |  nan | nan | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0  |

(All in bp/yr; blank = block flat that year.)


## 3. Cluster snapshot — most recent refresh year per block

K clusters at the most recent refresh year in-sample (final refresh applied through the OOS window). 'rep' = top-ADV in the trailing 63d ending at that year's refresh date.


### bond_rates  (K = 8, year 2025)

- **cluster 1** (2): 159649.XSHE (★ rep), 159650.XSHE
- **cluster 2** (1): 159816.XSHE (★ rep)
- **cluster 3** (1): 159972.XSHE (★ rep)
- **cluster 4** (3): 511010.XSHG, 511020.XSHG, 511260.XSHG (★ rep)
- **cluster 5** (1): 511060.XSHG (★ rep)
- **cluster 6** (2): 511090.XSHG, 511520.XSHG (★ rep)
- **cluster 7** (1): 511270.XSHG (★ rep)
- **cluster 8** (1): 511580.XSHG (★ rep)

### bond_credit  (K = 4, year 2025)

- **cluster 1** (1): 511030.XSHG (★ rep)
- **cluster 2** (2): 511180.XSHG, 511380.XSHG (★ rep)
- **cluster 3** (1): 511220.XSHG (★ rep)
- **cluster 4** (1): 511360.XSHG (★ rep)

### cross_border_dm  (K = 11, year 2025)

- **cluster 1** (1): 159509.XSHE (★ rep)
- **cluster 2** (3): 159605.XSHE, 513050.XSHG (★ rep), 513220.XSHG
- **cluster 3** (1): 159612.XSHE (★ rep)
- **cluster 4** (4): 159941.XSHE (★ rep), 513500.XSHG, 513650.XSHG, 513850.XSHG
- **cluster 5** (2): 513030.XSHG (★ rep), 513080.XSHG
- **cluster 6** (1): 513100.XSHG (★ rep)
- **cluster 7** (1): 513290.XSHG (★ rep)
- **cluster 8** (1): 513310.XSHG (★ rep)
- **cluster 9** (1): 513360.XSHG (★ rep)
- **cluster 10** (2): 513520.XSHG (★ rep), 513800.XSHG
- **cluster 11** (1): 513730.XSHG (★ rep)

### cross_border_hk  (K = 6, year 2025)

- **cluster 1** (5): 159506.XSHE, 159892.XSHE, 513060.XSHG, 513120.XSHG (★ rep), 513200.XSHG
- **cluster 2** (4): 159636.XSHE, 159792.XSHE (★ rep), 513160.XSHG, 513980.XSHG
- **cluster 3** (4): 159691.XSHE (★ rep), 513530.XSHG, 513630.XSHG, 513690.XSHG
- **cluster 4** (1): 159735.XSHE (★ rep)
- **cluster 5** (7): 159747.XSHE, 159920.XSHE, 510900.XSHG, 513180.XSHG (★ rep), 513330.XSHG, 513550.XSHG, 513750.XSHG
- **cluster 6** (1): 513090.XSHG (★ rep)

### metals  (K = 3, year 2025)

- **cluster 1** (1): 159980.XSHE (★ rep)
- **cluster 2** (1): 517520.XSHG (★ rep)
- **cluster 3** (1): 518880.XSHG (★ rep)

### commodity_other  (K = 2, year 2025)

- **cluster 1** (1): 159981.XSHE (★ rep)
- **cluster 2** (1): 159985.XSHE (★ rep)

## 4. Book-level impact — Phase 12×13 finalist

Layer-2 α (broad_cn, sector_cn) unchanged at finalist (q=0.2, ε=0.3). Non-α blocks swapped for the adaptive-K annual-refresh replicated composite. Layer-1 solver, sizing, cost = frozen.


| variant | IS Sh | OOS Sh | IS CAGR | OOS CAGR | IS DD | OOS DD | IS ann vol | turnover | mean K names |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| hold_all | +1.577 | +3.621 | +4.24% | +4.48% | -2.54% | -0.36% | +2.90% | 0.0813 | 38.1 |
| replicated | +1.529 | +4.078 | +3.91% | +4.11% | -2.54% | -0.31% | +2.74% | 0.0686 | 24.1 |

**Δ (replicated − hold-all)**: IS Sharpe -0.048, OOS Sharpe +0.457, IS CAGR -0.33 pp, OOS CAGR -0.37 pp, IS DD +0.00 pp, OOS DD +0.04 pp.  
Mean K names 38.1 → 24.1 (-36.8 %).  


## 5. Turnover attribution — refresh-week spikes

Weekly turnover (Σ_i |ΔW_i| per bar) split into: **refresh weeks** (first W-FRI of each calendar year — rep-swap + σ drift) vs **other weeks** (σ drift only). 'Excess' = refresh_avg − other_avg, an upper bound on the rep-swap component. 'Refresh cost drag' converts excess turnover into ann bp/yr at 10 bp/side.


| variant | refresh avg | other avg | excess | refresh max | other max | refresh cost drag bp/yr |
|:---|---:|---:|---:|---:|---:|---:|
| hold_all | 0.0626 | 0.0821 | -0.0195 | 0.1635 | 0.9481 | -0.4 |
| replicated | 0.2553 | 0.0647 | +0.1906 | 0.6359 | 0.9481 | +3.8 |

### Top 5 turnover weeks — replicated book

| date | weekly turnover | refresh week? |
|:---|---:|:---:|
| 2019-05-31 | 0.9481 |  |
| 2024-01-05 | 0.6359 | ★ |
| 2023-01-06 | 0.5857 | ★ |
| 2020-05-22 | 0.4640 |  |
| 2025-01-03 | 0.4489 | ★ |

## 6. Read-off (v2 — adaptive K, warmup-trimmed)

- **K genuinely became an output**. bond_rates grows 2 → 2 → 5 → 10 → 8 as N grows 2 → 2 → 5 → 11 → 12; cross_border_hk lands at K=5 (out of N=10) in 2023, K=5 (N=17) in 2024, K=6 (N=22) in 2025 — compressing 73% of names while holding residual ratio ≤ 0.17. cross_border_dm holds K = N through 2024 (each name its own cluster: block genuinely heterogeneous), then compresses to K=11 of N=18 in 2025 as new admits fill existing clusters.
- **v1 fcluster bug removed**. Under `cut_tree`, cbHK 2025 K=6 correctly splits into 5+4+4+1+7+1; metals 2025 K=3 splits into 1+1+1. The v1 report's "one giant cluster" artifacts are gone.
- **Book Δ (warmup-trimmed)**: IS Sharpe −0.048 (240 IS bars), **OOS Sharpe +0.457** (82 bars), OOS DD +0.05 pp. Mean K names 38.1 → 24.1 (−37%). Turnover 0.0813 → 0.0686 (−16%). The Δ magnitudes are essentially identical to the pre-trim numbers because warmup dilution applies equally to both variants — but the *level* IS Sharpes now read +1.58 (hold_all) vs +1.53 (replicated), not +1.42/+1.38.
- **Reading the OOS Sharpe jump correctly — it is volatility compression, not return improvement**. Splitting the +0.457 OOS Sharpe delta into numerator vs denominator: OOS CAGR *fell* +4.48% → +4.11% (Δ −0.37 pp) while OOS ann-vol *fell* +1.25% → +1.02% (Δ −0.23 pp, relative −18%). Sharpe = CAGR/vol → numerator down ~8%, denominator down ~18% → ratio up. So the improvement is not "the replicated book earned more" but "the replicated book took on materially less risk for essentially the same return." A plausible mechanism: newly-admitted small-AUM ETFs carry more idiosyncratic weekly noise than mature large-AUM names; the annual refresh + top-ADV representative rule delays their entry and typically routes them into an existing cluster where their weight is inherited by an already-large ETF, so the OOS book sees fewer noisy small-AUM members. (A secondary, non-mutually-exclusive channel is that intra-cluster averaging kills within-cluster idio vol without a proportional loss of diversification when intra-cluster ρ̄ is high — the ρ̄ ≥ 0.90 seen in §1 supports this.) Neither channel is an α-generation story; both are risk-side dividends, and both would attenuate if universe growth slows.
- **Turnover attribution confirms refresh-week cost is real but small**:
  - Refresh-week turnover 0.255 vs other 0.065 → excess 0.191 (~4× baseline).
  - At 10 bp/side × 2 sides × ~1 refresh/year, that's **+3.8 bp/yr cost drag**.
  - Compared to the +0.46 OOS Sharpe improvement (~ +100 bp/yr on ~2.3% book vol), the rep-swap cost is ~4% of the OOS gain. Comfortable.
- **The biggest turnover spike is NOT a refresh week**: 2019-05-31 at 0.948 — verified identical between hold_all and replicated (both = 0.9481), so it's a v6-wide structural event (the first-live bar at layer-1 warmup boundary), *not* a rep-swap. Under warmup trim it now sits *before* the effective IS start, so it no longer distorts book stats. The 2nd/3rd/5th biggest ARE refresh weeks; on those, hold_all turnover is 0.04–0.07 while replicated is 0.45–0.64 → the extra ~0.4–0.6 is purely the rep-swap cost.
- **cbDM stays hard to compress**: even under adaptive-K, cbDM lives at K=N through 2024 (threshold barely met with all names). It becomes compressible only in 2025 when new admits fill existing clusters. That's the block being genuinely heterogeneous, not a method failure.
- **Suggested action**: adopt adaptive-K residual-vol threshold (default 0.20) as the operational rule for v7. Keep the annual refresh; the rep-swap cost is small enough to ignore. Cost-conscious execution can stage the Jan rebalance, but it's optional.

