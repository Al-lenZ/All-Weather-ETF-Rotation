# v6 static — block cross-section census (Phase 13.1, IS window)

Generated: 2026-07-22 15:33:56  

Bar × block count of admitted members over the IS window (bars ≤ 2023-12-31, n_bars = 292). Total-pool mean N_t = 70.0. UNTAGGED codes kept as their own bucket so per-block counts sum back to N_t.

Reads for the Phase 13.2 within-block IC screen: a block whose mean N_b < MIN_VALID_ROW = 5 won't have a well-resolved per-bar IC — its z-stat is directional only. Such blocks are **not** dropped from the screen (per user); they're just flagged so the report reads them as qualitative.


## 1. IS block census (sorted by mean N_b)

| block | mean N | median | min | p10 | p90 | max | bars ≥ 5 / total | flag |
|:---|---:|---:|---:|---:|---:|---:|---:|:---:|
| sector_cn | 37.9 | 35.0 | 0 | 2.0 | 79.0 | 83 | 244 / 292 |  |
| broad_cn | 12.5 | 14.0 | 0 | 7.0 | 19.9 | 21 | 285 / 292 |  |
| cross_border_hk | 6.7 | 3.0 | 0 | 2.0 | 16.0 | 18 | 124 / 292 |  |
| cross_border_dm | 3.9 | 3.0 | 0 | 2.0 | 6.0 | 8 | 93 / 292 | **thin** |
| bond_rates | 3.3 | 2.0 | 0 | 1.0 | 9.0 | 12 | 67 / 292 | **thin** |
| bond_credit | 1.9 | 1.0 | 0 | 0.0 | 5.0 | 5 | 63 / 292 | **thin** |
| metals | 1.6 | 2.0 | 0 | 1.0 | 2.0 | 3 | 0 / 292 | **thin** |
| smallcap_cn | 1.5 | 2.0 | 0 | 1.0 | 2.0 | 2 | 0 / 292 | **thin** |
| commodity_other | 0.6 | 0.0 | 0 | 0.0 | 2.0 | 2 | 0 / 292 | **thin** |

## 2. Per-year mean N_b by block

| year | sector_cn | broad_cn | cross_border_hk | cross_border_dm | bond_rates | bond_credit | metals | smallcap_cn | commodity_other |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2018 | 1.7 | 4.8 | 1.5 | 1.2 | 0.8 | 0.0 | 0.8 | 1.0 | 0.0 |
| 2019 | 4.4 | 7.2 | 2.0 | 2.9 | 1.2 | 0.0 | 1.0 | 1.9 | 0.0 |
| 2020 | 23.4 | 10.9 | 2.2 | 3.6 | 1.9 | 0.2 | 1.2 | 1.9 | 0.3 |
| 2021 | 40.5 | 14.1 | 4.2 | 3.0 | 2.1 | 2.1 | 1.6 | 1.5 | 0.2 |
| 2022 | 64.0 | 15.7 | 11.6 | 4.6 | 3.9 | 3.6 | 2.0 | 1.0 | 1.6 |
| 2023 | 78.6 | 19.2 | 16.7 | 6.9 | 9.2 | 5.0 | 2.4 | 1.7 | 1.3 |

## 3. Read for the 13.2 screen

- **Well-resolved blocks (mean N ≥ 5):** `sector_cn`, `broad_cn`, `cross_border_hk`. Per-block zstat here is comparable to the pool-level zstat from `pv_sweep_xs_v6`.
- **Thin blocks (mean N < 5):** `cross_border_dm`, `bond_rates`, `bond_credit`, `metals`, `smallcap_cn`, `commodity_other`. Screen still runs; treat zstat as directional. Consider quotient thresholds (top-1 / top-2 hit rate) as the actionable read here.

The mini-bond diagnostic (13.3) is most relevant on the wider equity blocks where a naive 1/σ can still collapse to a fixed 3-4 name portfolio — flagged separately in that report.

