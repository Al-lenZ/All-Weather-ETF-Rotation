# Phase 13.2 — within-block IC screen (v6 pool, IS only)

Generated: 2026-07-22 16:03:23  

Screen scope: 472 factors (REGISTRY daily/external/hourly/price_volume/sentiment/technical, intersected with the v6 cache-common set of 472) × 1 blocks. IS window: bars ≤ 2023-12-31. Cost is not paid here (IC only). Gate for a *trustworthy* survivor: |zstat| ≥ 2.0 AND n_bars ≥ 100. Thin blocks stay in the sweep — per-block top-K in §3 gives a directional read even when the gate isn't hit.

Method note: stage-1 expanding-z per name (min_periods = 26), then per-bar Spearman IC restricted to block members (min_valid = 5). No stage-2 CS Gaussian rank — Spearman IC is rank-invariant per bar, so skipping it gives identical per-block IC at a fraction of the compute.


## 1. Survivor counts per block

| block | mean N_b | thin? | rows evaluated | survivors (|z|≥2.0, n≥100) |
|:---|---:|:---:|---:|---:|
| cross_border_hk | +6.7 |  | 472 | 0 |

## 2. Trustworthy survivors — |zstat| ≥ 2.0, n_bars ≥ 100

*No factor × block pair clears the gate.*

## 3. Top-15 per block by |zstat| (directional; no coverage gate)

Included for thin blocks where the n_bars gate cannot be met. **Do not** treat these as tradable signals — read them as "factors worth eyeballing for a block-native diagnostic."


### `cross_border_hk`

| factor | polarity | n | mean N_b | zstat | mean_ic | pct_pos |
|:---|:---:|---:|---:|---:|---:|---:|
| alpha_028 | rev | 89 | +11.2 | -3.57 | -0.1234 |  39.3% |
| alpha_036 | rev | 89 | +11.2 | -3.46 | -0.1202 |  38.2% |
| alpha_104 | rev | 89 | +11.2 | -3.46 | -0.1202 |  38.2% |
| wq_054 | rev | 89 | +11.2 | -3.43 | -0.1028 |  39.3% |
| alpha_071 | rev | 89 | +11.2 | -3.42 | -0.1204 |  39.3% |
| alpha_062 | raw | 89 | +11.2 | +3.16 | +0.1073 |  58.4% |
| wq_098 | rev | 89 | +11.2 | -3.01 | -0.1003 |  33.7% |
| alpha_116 | raw | 89 | +11.2 | +3.00 | +0.1015 |  61.8% |
| alpha_142 | rev | 89 | +11.2 | -2.95 | -0.0937 |  40.4% |
| atr_10 | raw | 89 | +11.2 | +2.90 | +0.0953 |  57.3% |
| alpha_098 | rev | 89 | +11.2 | -2.90 | -0.0991 |  36.0% |
| alpha_025 | rev | 89 | +11.2 | -2.88 | -0.1046 |  42.7% |
| shadow_up_5 | raw | 89 | +11.2 | +2.83 | +0.0947 |  56.2% |
| alpha_103 | rev | 89 | +11.2 | -2.81 | -0.0992 |  36.0% |
| h_consec_10 | rev | 89 | +11.2 | -2.81 | -0.1028 |  38.2% |

## 4. Read for 13.3 / 13.4

- No (factor, block) pair passes the trustworthy gate on IS. Before closing Phase 13, sanity-check the top-K in §3 for a block-native signal that the pool-level pipeline was masking. If nothing survives interpretation, the pass rule for Phase 13.4 has no candidates — the two-layer architecture buys nothing over a T2/T4-style block-β book, and Phase 12 becomes "budget-only" mode.


