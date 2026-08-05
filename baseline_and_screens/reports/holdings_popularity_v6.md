# v6 static baseline — holdings popularity

Generated: 2026-07-21


Which names actually make it into each Phase 9.1 baseline book, and how often. Restricted to IS ∪ OOS bars (hold-out beyond 2025-07-31 sealed). Source: persisted `ensemble_weights.parquet` per cell — same weight panels used by `cost_attribution_v6.py` and `baseline_diagnostics_v6.py`.

## Metrics

- **presence_share** — fraction of the cell's bars in which the name held a non-zero weight (on the given leg).
- **hit_bars** — integer count corresponding to presence_share.
- **mean_w** — average |w| in bars where the name is held. For long books normalized to Σ = 1; for the LS book each leg is normalized to 0.5.
- **weight-time share** — `Σ_t |w_{i,t}| / Σ_t Σ_j |w_{j,t}|` on this leg. Answers 'of all the dollar-weeks this leg spent, what fraction went to this name'.

## Coverage

| cell | n_bars | mean_held_per_bar | max_held_per_bar | unique_names_total | unique_names_long | unique_names_short |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| long_q05 | 374 | 4.69 | 10 | 49 | — | — |
| long_q10 | 374 | 8.92 | 20 | 162 | — | — |
| long_q20 | 374 | 17.36 | 39 | 217 | — | — |
| ls_q20 | 374 | 34.73 | 78 | 257 | 243 | 242 |

## long_q05

### Top 15 names — long leg (by weight-time share)

| rank | code | name_en | block | presence | hit_bars | mean_w | wt-time share |
|:---:|:---|:---|:---|---:|---:|---:|---:|
| 1 | 511010.XSHG | GTSZ5NQGZETF | bond_rates | 79.7% | 298 | 32.67% | 30.52% |
| 2 | 511360.XSHG | HFTZZDRETF | bond_credit | 46.3% | 173 | 48.76% | 26.44% |
| 3 | 511260.XSHG | SZ10NQGZETF | bond_rates | 62.3% | 233 | 16.69% | 12.19% |
| 4 | 159972.XSHE | 5NDZ | bond_rates | 38.8% | 145 | 9.15% | 4.16% |
| 5 | 159816.XSHE | 0-4DZ | bond_rates | 22.2% | 83 | 13.95% | 3.63% |
| 6 | 159650.XSHE | BSZZ0-3NGKHETF | bond_rates | 15.5% | 58 | 18.01% | 3.28% |
| 7 | 511270.XSHG | HFTSZ10NQDFZFZETF | bond_rates | 24.3% | 91 | 10.12% | 2.89% |
| 8 | 159649.XSHE | HAZZ1-5NGKHZQETF | bond_rates | 21.4% | 80 | 11.23% | 2.82% |
| 9 | 511030.XSHG | PAZGDJGSZLCYZETF | bond_credit | 19.5% | 73 | 11.05% | 2.53% |
| 10 | 511060.XSHG | HFTSZ5NQDFZFZETF | bond_rates | 24.3% | 91 | 8.44% | 2.41% |
| 11 | 511580.XSHG | ZSZZGZJZCXJRZ0-3NETF | bond_rates | 16.0% | 60 | 11.70% | 2.20% |
| 12 | 511020.XSHG | PA5-10NQGZHYQETF | bond_rates | 22.2% | 83 | 6.98% | 1.82% |
| 13 | 518880.XSHG | HAHJETF | metals | 12.3% | 46 | 9.64% | 1.39% |
| 14 | 513500.XSHG | BSBP500ETF | cross_border_dm | 11.5% | 43 | 7.07% | 0.95% |
| 15 | 511520.XSHG | FGZZ7-10NZCXJRZETF | bond_rates | 11.5% | 43 | 5.03% | 0.68% |

### Block aggregate — long_q05

| side | block | n names ever held | Σ weight-time | mean presence |
|:---:|:---|---:|---:|---:|
| long | bond_rates | 16 | 67.0% | 21.9% |
| long | bond_credit | 5 | 29.8% | 15.3% |
| long | metals | 2 | 1.4% | 7.2% |
| long | cross_border_dm | 5 | 1.2% | 3.3% |
| long | broad_cn | 9 | 0.3% | 0.5% |
| long | commodity_other | 1 | 0.1% | 0.8% |
| long | sector_cn | 7 | 0.1% | 0.7% |
| long | smallcap_cn | 1 | 0.0% | 0.3% |
| long | cross_border_hk | 3 | 0.0% | 0.4% |

## long_q10

### Top 15 names — long leg (by weight-time share)

| rank | code | name_en | block | presence | hit_bars | mean_w | wt-time share |
|:---:|:---|:---|:---|---:|---:|---:|---:|
| 1 | 511010.XSHG | GTSZ5NQGZETF | bond_rates | 84.5% | 316 | 27.57% | 27.31% |
| 2 | 511360.XSHG | HFTZZDRETF | bond_credit | 51.1% | 191 | 40.39% | 24.19% |
| 3 | 511260.XSHG | SZ10NQGZETF | bond_rates | 66.8% | 250 | 13.08% | 10.25% |
| 4 | 159972.XSHE | 5NDZ | bond_rates | 43.0% | 161 | 6.84% | 3.45% |
| 5 | 159816.XSHE | 0-4DZ | bond_rates | 27.3% | 102 | 9.95% | 3.18% |
| 6 | 511270.XSHG | HFTSZ10NQDFZFZETF | bond_rates | 38.5% | 144 | 6.98% | 3.15% |
| 7 | 511030.XSHG | PAZGDJGSZLCYZETF | bond_credit | 34.0% | 127 | 7.25% | 2.89% |
| 8 | 159650.XSHE | BSZZ0-3NGKHETF | bond_rates | 20.6% | 77 | 11.73% | 2.83% |
| 9 | 511060.XSHG | HFTSZ5NQDFZFZETF | bond_rates | 38.8% | 145 | 6.14% | 2.79% |
| 10 | 159649.XSHE | HAZZ1-5NGKHZQETF | bond_rates | 28.1% | 105 | 7.65% | 2.52% |
| 11 | 511580.XSHG | ZSZZGZJZCXJRZ0-3NETF | bond_rates | 24.9% | 93 | 8.57% | 2.50% |
| 12 | 511020.XSHG | PA5-10NQGZHYQETF | bond_rates | 34.8% | 130 | 4.66% | 1.90% |
| 13 | 513500.XSHG | BSBP500ETF | cross_border_dm | 29.1% | 109 | 5.45% | 1.86% |
| 14 | 518880.XSHG | HAHJETF | metals | 23.3% | 87 | 5.46% | 1.49% |
| 15 | 511520.XSHG | FGZZ7-10NZCXJRZETF | bond_rates | 27.8% | 104 | 3.44% | 1.12% |

### Block aggregate — long_q10

| side | block | n names ever held | Σ weight-time | mean presence |
|:---:|:---|---:|---:|---:|
| long | bond_rates | 16 | 62.4% | 30.0% |
| long | bond_credit | 5 | 29.1% | 26.0% |
| long | cross_border_dm | 17 | 2.6% | 3.5% |
| long | metals | 4 | 1.7% | 8.4% |
| long | sector_cn | 70 | 1.7% | 1.4% |
| long | broad_cn | 25 | 1.7% | 2.4% |
| long | cross_border_hk | 20 | 0.4% | 1.0% |
| long | commodity_other | 2 | 0.4% | 5.9% |
| long | smallcap_cn | 3 | 0.1% | 0.6% |

## long_q20

### Top 15 names — long leg (by weight-time share)

| rank | code | name_en | block | presence | hit_bars | mean_w | wt-time share |
|:---:|:---|:---|:---|---:|---:|---:|---:|
| 1 | 511010.XSHG | GTSZ5NQGZETF | bond_rates | 84.0% | 314 | 23.31% | 22.95% |
| 2 | 511360.XSHG | HFTZZDRETF | bond_credit | 51.3% | 192 | 37.49% | 22.56% |
| 3 | 511260.XSHG | SZ10NQGZETF | bond_rates | 68.7% | 257 | 10.38% | 8.36% |
| 4 | 159972.XSHE | 5NDZ | bond_rates | 43.3% | 162 | 6.27% | 3.19% |
| 5 | 159816.XSHE | 0-4DZ | bond_rates | 27.8% | 104 | 9.08% | 2.96% |
| 6 | 511270.XSHG | HFTSZ10NQDFZFZETF | bond_rates | 40.9% | 153 | 5.97% | 2.87% |
| 7 | 511030.XSHG | PAZGDJGSZLCYZETF | bond_credit | 34.0% | 127 | 6.89% | 2.74% |
| 8 | 511060.XSHG | HFTSZ5NQDFZFZETF | bond_rates | 40.1% | 150 | 5.59% | 2.63% |
| 9 | 159650.XSHE | BSZZ0-3NGKHETF | bond_rates | 20.9% | 78 | 10.52% | 2.57% |
| 10 | 511580.XSHG | ZSZZGZJZCXJRZ0-3NETF | bond_rates | 26.2% | 98 | 7.76% | 2.38% |
| 11 | 159649.XSHE | HAZZ1-5NGKHZQETF | bond_rates | 28.3% | 106 | 6.99% | 2.32% |
| 12 | 518880.XSHG | HAHJETF | metals | 49.2% | 184 | 3.96% | 2.29% |
| 13 | 511020.XSHG | PA5-10NQGZHYQETF | bond_rates | 33.7% | 126 | 4.39% | 1.73% |
| 14 | 513500.XSHG | BSBP500ETF | cross_border_dm | 42.5% | 159 | 3.37% | 1.68% |
| 15 | 511220.XSHG | HFTSZCTZETF | bond_credit | 22.2% | 83 | 5.31% | 1.38% |

### Block aggregate — long_q20

| side | block | n names ever held | Σ weight-time | mean presence |
|:---:|:---|---:|---:|---:|
| long | bond_rates | 16 | 54.1% | 30.2% |
| long | bond_credit | 5 | 28.3% | 33.3% |
| long | sector_cn | 101 | 4.4% | 3.9% |
| long | broad_cn | 30 | 4.3% | 7.3% |
| long | cross_border_dm | 24 | 3.8% | 7.9% |
| long | metals | 5 | 2.6% | 15.6% |
| long | cross_border_hk | 30 | 1.4% | 5.1% |
| long | smallcap_cn | 4 | 0.6% | 5.3% |
| long | commodity_other | 2 | 0.4% | 14.2% |

## ls_q20

### Top 15 names — long leg (by weight-time share)

| rank | code | name_en | block | presence | hit_bars | mean_w | wt-time share |
|:---:|:---|:---|:---|---:|---:|---:|---:|
| 1 | 511010.XSHG | GTSZ5NQGZETF | bond_rates | 13.1% | 49 | 17.25% | 5.30% |
| 2 | 159949.XSHE | HACYB50ETF | broad_cn | 20.6% | 77 | 5.16% | 2.49% |
| 3 | 159915.XSHE | YFDCYBETF | broad_cn | 16.8% | 63 | 5.65% | 2.23% |
| 4 | 511360.XSHG | HFTZZDRETF | bond_credit | 4.8% | 18 | 19.49% | 2.20% |
| 5 | 512800.XSHG | HBZZYHETF | sector_cn | 28.9% | 108 | 2.98% | 2.02% |
| 6 | 159928.XSHE | HTFZZZYXFETF | sector_cn | 18.7% | 70 | 4.46% | 1.96% |
| 7 | 159901.XSHE | YFDSZ100ETF | broad_cn | 9.1% | 34 | 8.85% | 1.89% |
| 8 | 512690.XSHG | JETF | sector_cn | 29.4% | 110 | 2.64% | 1.82% |
| 9 | 512880.XSHG | GTZZQZZQGSETF | sector_cn | 22.2% | 83 | 3.31% | 1.72% |
| 10 | 159816.XSHE | 0-4DZ | bond_rates | 4.8% | 18 | 13.63% | 1.54% |
| 11 | 512480.XSHG | GLABDTETF | sector_cn | 27.5% | 103 | 2.29% | 1.48% |
| 12 | 512660.XSHG | GTZZJGETF | sector_cn | 22.2% | 83 | 2.81% | 1.46% |
| 13 | 512170.XSHG | HBZZYLETF | sector_cn | 18.4% | 69 | 3.25% | 1.41% |
| 14 | 512760.XSHG | GTCESBDTXPHYETF | sector_cn | 24.6% | 92 | 2.42% | 1.40% |
| 15 | 515220.XSHG | GTZZMTETF | sector_cn | 30.5% | 114 | 1.93% | 1.38% |

### Top 15 names — short leg (by weight-time share)

| rank | code | name_en | block | presence | hit_bars | mean_w | wt-time share |
|:---:|:---|:---|:---|---:|---:|---:|---:|
| 1 | 511010.XSHG | GTSZ5NQGZETF | bond_rates | 17.1% | 64 | 17.11% | 6.87% |
| 2 | 159920.XSHE | HXHSETF | cross_border_hk | 34.2% | 128 | 4.24% | 3.40% |
| 3 | 510900.XSHG | YFDHSGQ(QDII-ETF) | cross_border_hk | 36.4% | 136 | 3.73% | 3.18% |
| 4 | 511360.XSHG | HFTZZDRETF | bond_credit | 6.1% | 23 | 19.50% | 2.81% |
| 5 | 518880.XSHG | HAHJETF | metals | 20.9% | 78 | 5.00% | 2.44% |
| 6 | 511260.XSHG | SZ10NQGZETF | bond_rates | 12.3% | 46 | 7.72% | 2.23% |
| 7 | 513050.XSHG | YFDZZHWZGHLW50(QDII-ETF) | cross_border_dm | 35.0% | 131 | 2.63% | 2.16% |
| 8 | 512880.XSHG | GTZZQZZQGSETF | sector_cn | 16.0% | 60 | 4.25% | 1.60% |
| 9 | 512660.XSHG | GTZZJGETF | sector_cn | 15.0% | 56 | 4.12% | 1.45% |
| 10 | 513090.XSHG | YFDZZXGZQTZZT(GGT)ETF | cross_border_hk | 28.9% | 108 | 2.10% | 1.42% |
| 11 | 159949.XSHE | HACYB50ETF | broad_cn | 13.1% | 49 | 4.42% | 1.36% |
| 12 | 513500.XSHG | BSBP500ETF | cross_border_dm | 15.0% | 56 | 3.39% | 1.19% |
| 13 | 159939.XSHE | GFZZQZXXJSETF | sector_cn | 11.8% | 44 | 4.16% | 1.15% |
| 14 | 512290.XSHG | GTZZSWYYETF | sector_cn | 17.9% | 67 | 2.66% | 1.12% |
| 15 | 510880.XSHG | HTBRSZHLETF | broad_cn | 14.2% | 53 | 3.30% | 1.10% |

### Block aggregate — ls_q20

| side | block | n names ever held | Σ weight-time | mean presence |
|:---:|:---|---:|---:|---:|
| long | sector_cn | 118 | 54.7% | 9.9% |
| long | broad_cn | 33 | 17.6% | 6.5% |
| long | bond_rates | 15 | 12.4% | 4.5% |
| long | cross_border_dm | 27 | 4.0% | 3.6% |
| long | cross_border_hk | 35 | 3.3% | 2.9% |
| long | bond_credit | 5 | 3.3% | 3.7% |
| long | smallcap_cn | 4 | 2.7% | 8.0% |
| long | metals | 4 | 1.6% | 7.3% |
| long | commodity_other | 2 | 0.3% | 5.9% |
| short | sector_cn | 116 | 40.7% | 7.2% |
| short | cross_border_hk | 38 | 18.2% | 11.0% |
| short | bond_rates | 16 | 14.3% | 5.2% |
| short | broad_cn | 28 | 9.9% | 4.6% |
| short | cross_border_dm | 28 | 6.7% | 6.4% |
| short | bond_credit | 5 | 5.0% | 5.9% |
| short | metals | 5 | 3.1% | 7.5% |
| short | smallcap_cn | 4 | 1.5% | 2.3% |
| short | commodity_other | 2 | 0.6% | 7.5% |

## Cross-cutting findings

**1. The three long cells share the same three anchor bonds.** On
`long_q05`, `long_q10`, and `long_q20`, the top-3 by weight-time share
are always `511010.XSHG` (5Y government bond), `511360.XSHG` (a credit
bond fund), and `511260.XSHG` (10Y government bond), in that order.
Combined shares: 69.2% / 61.7% / 53.9% as K grows. The books look
different in name-count and diversification but they're all built on
the same bond core.

**2. Bond concentration decays with K but stays dominant.** Combined
`bond_rates + bond_credit` share of long-leg weight-time:
   - long_q05: **96.8%**
   - long_q10: **91.6%**
   - long_q20: **82.5%**

Even at q=0.20, the long book is a bond book with a risk-asset tilt,
not the other way around.

So the "smaller K → higher concentration" story from `cost_attribution`
also shows up in composition: long_q05 saw only 49 unique names ever
touch the book across 374 bars (mean |H| = 4.69); long_q10 saw 162;
long_q20 saw 217. Deeper books do rotate through more of the universe.

**3. `long_q05` is essentially a bond-tilt strategy.** Bond blocks
account for 96.8% of book weight-time. Non-bond exposure lives almost
entirely in `518880.XSHG` (gold, 1.4%) and a smattering of QDII names
(1.2%). This matches the drawdown attribution in
`baseline_diagnostics_v6.md` §3.3 — long_q05's 26-week 2020 DD was
almost entirely from bonds selling off.

**4. `ls_q20` has a very different long leg from the long books.**
The LS long leg is majority Chinese equity — sector_cn (54.7% of
weight-time) + broad_cn (17.6%) + smallcap_cn (2.7%). Bonds shrink to
15.7% (rates + credit). The α ordering says "bonds outperform on
average" (which is why they dominate long-only books), but at q=0.20
in an LS frame the bottom-K short leg picks up bond names too when
their α ranks flip.

**5. Bonds appear at the top of BOTH LS legs.** `511010.XSHG` is
weight-time-rank-1 on the LS long leg (5.30%) **and** rank-1 on the
short leg (6.87%). Same story for `511360` and `511260`. This means
the 5Y bond ETF gets shorted roughly as often as it gets bought in the
LS book — its α rank flips sides frequently. Combined with its low σ
(→ high 1/σ weight), a rank flip costs a lot in turnover. This is
consistent with the ls_q20 cost drag flagged in
`cost_attribution_v6_report.md` §1 (422 bps/yr, 51% of gross return).

**6. LS short leg concentrates in cross-border ETFs.** After sector_cn
(40.7%), the biggest short-leg blocks are `cross_border_hk` (18.2%)
and `cross_border_dm` (6.7%). The top three short-only names are all
Hong Kong or US QDII (`159920` HSI, `510900` HSCEI-QDII, `513050`
Nasdaq-QDII). The book systematically shorts offshore-equity exposure.

**7. Universe coverage is thin at small K.** Only 49 of the ~344
eligible codes ever entered the long_q05 book (14%). long_q20 hits
217 (63%). ls_q20 touches 257 (75%), split roughly evenly between the
two legs (243 long-side, 242 short-side — big overlap since names flip
sides).

## Files

- `data/v6_static/holdings_popularity/coverage.csv` — one row per cell,
  bar count, unique names, mean |held|, per-leg counts for LS.
- `data/v6_static/holdings_popularity/{cell}_names.csv` — full
  per-name × side table (all names ever held, sorted by weight-time
  share). Includes `code, name_en, block, presence_share, hit_bars,
  mean_w_when_held, weight_time_share`.
- `data/v6_static/holdings_popularity/{cell}_blocks.csv` — block
  aggregate per leg (n names, Σ weight-time, mean presence).
- `scripts/holdings_popularity_v6.py` — one-shot rerun; no re-screen,
  reads persisted `ensemble_weights.parquet` per cell. Runtime ~2 s.
