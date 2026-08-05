# Phase 12 layer-1 — block risk budgeting + trend gate (standalone, no α)

Generated: 2026-07-22 19:15:54  

Standalone contribution of the *first layer* on the v6 pool: block-level risk budgeting with the frozen Phase 12 policy shares, 10-month MA trend gate → cash, no within-block α selection (block-internal eqw or invvol on all eligible members).

Cost 10 bp/side. IS = bars ≤ 2023-12-31. Cov window 52w; trend MA 43w. Warmup 52 bars (book flat).

**Policy risk shares** (Phase 12 spec, frozen 2026-07-22):
- equity (broad_cn + sector_cn + cross_border_dm + cross_border_hk, smallcap merged): 55 %
- bond_rates : 20 %
- bond_credit: 10 %
- commodity (metals + commodity_other): 15 %

Two intra-block sizings × two budget solvers → 4 variants. Per user 2026-07-22, intra-block sizing (eqw vs invvol) and block-level hysteresis are open knobs — this branch reports both intra choices in parallel and leaves hysteresis for a follow-up.

*Solvers.* `naive` = **w_b ∝ √policy_b / σ_b** (closed-form ERC under diagonal cov; delivers RC_b ∝ policy_b exactly when Σ is diagonal). `lw_erc` = policy-weighted risk parity via log-barrier on the shrunk 4×4 cov; **shrinkage target = diag(S)** (Schäfer & Strimmer 2005 target-D), which preserves per-block variance and only regularizes off-diagonal terms — avoids the distortion an equal-variance target (Tr(S)/N · I) would inflict on this pool where block σ spans an order of magnitude.

*Trend gate.* Per group, 1 iff causal composite NAV > 43-week MA of the same. OFF → block weight 0, released mass to cash (no redistribution to on-trend blocks).


## 1. IS headline

| variant | IS Sharpe | IS CAGR | IS max DD | IS ann vol | avg turnover | mean K | cash share |
|:---|---:|---:|---:|---:|---:|---:|---:|
| eqw × naive | +1.333 | +3.30% | -2.60% | +2.59% | 0.055 | 51.6 | 30.6% |
| eqw × lw_erc | +1.429 | +3.40% | -2.55% | +2.45% | 0.053 | 51.6 | 30.1% |
| invvol × naive | +1.321 | +3.16% | -2.55% | +2.32% | 0.063 | 53.9 | 28.8% |
| invvol × lw_erc | +1.381 | +3.17% | -2.55% | +2.24% | 0.066 | 53.9 | 29.1% |

## 2. Comparison anchors (from prior work)

| anchor | IS Sharpe | IS CAGR | IS max DD | source |
|:---|---:|---:|---:|:---|
| solo_defensive | +1.002 | +3.48% | -5.24% | v6_static/long_q20/ensemble_net_ret.csv (Phase 11.2) |
| T1_universe_invvol | +0.707 | +5.46% | -8.09% | bond_attribution_v6 |
| T2_bond_invvol | +1.425 | +2.40% | -4.26% | bond_attribution_v6 |
| T3_bond_eqw | +1.122 | +2.78% | -4.37% | bond_attribution_v6 |
| T4_equity_invvol | +0.375 | +5.28% | -18.93% | bond_attribution_v6 |

## 3. Mean realized RC-share (IS)

Two views. **§3a** takes the mean over IS bars where *every* block group is trend-ON — no cross-block renormalization, so the number is what the risk-budget solver actually delivers. **§3b** averages over all invested IS bars (including bars where some groups are gated OFF): remaining ON blocks' RC%s renormalize to 1 each bar, so equity RC gets diluted below policy on bars where equity is OFF. §3a is the direct check on the solver; §3b shows what the book looks like in practice.


### 3a. Solver-delivered RC (bars where all 4 groups ON)

| variant | equity | bond_rates | bond_credit | commodity | n bars |
|:---|---:|---:|---:|---:|---:|
| **policy** | ** 55.0%** | ** 20.0%** | ** 10.0%** | ** 15.0%** | — |
| eqw × naive |  58.8% |  21.4% |  10.0% |  16.0% | 156 |
| eqw × lw_erc |  58.8% |  21.4% |  10.0% |  16.0% | 156 |
| invvol × naive |  58.4% |  21.2% |  10.0% |  15.9% | 163 |
| invvol × lw_erc |  58.4% |  21.2% |  10.0% |  15.9% | 163 |

### 3b. Mean RC over all invested IS bars (gate-averaged)

| variant | equity | bond_rates | bond_credit | commodity |
|:---|---:|---:|---:|---:|
| policy |  55.0% |  20.0% |  10.0% |  15.0% |
| eqw × naive |  41.5% |  30.8% |  12.1% |  20.5% |
| eqw × lw_erc |  42.0% |  34.5% |   7.7% |  18.9% |
| invvol × naive |  41.4% |  29.8% |  17.1% |  18.7% |
| invvol × lw_erc |  41.9% |  31.8% |  15.3% |  17.3% |

## 4. Trend-gate % ON per group (IS, post-warmup)

| variant | equity | bond_rates | bond_credit | commodity | mean n_switches |
|:---|---:|---:|---:|---:|---:|
| eqw × naive |  61.9% |  87.9% |  64.0% |  84.3% | 13.0 |
| eqw × lw_erc |  61.9% |  87.9% |  64.0% |  84.3% | 13.0 |
| invvol × naive |  61.9% |  87.9% |  92.0% |  80.3% | 11.2 |
| invvol × lw_erc |  61.9% |  87.9% |  92.0% |  80.3% | 11.2 |

## 5. Per-calendar-year IS return (sum of weekly net)

| year | eqw × naive | eqw × lw_erc | invvol × naive | invvol × lw_erc |
|:---:|---:|---:|---:|---:|
| 2018 | +0.00% | +0.00% | +0.00% | +0.00% |
| 2019 | +6.01% | +5.88% | +6.02% | +5.86% |
| 2020 | +8.55% | +8.77% | +8.09% | +8.22% |
| 2021 | +2.54% | +2.34% | +1.85% | +1.84% |
| 2022 | +1.21% | +1.53% | +1.48% | +1.50% |
| 2023 | +1.71% | +2.13% | +1.63% | +1.75% |

## 6. IS weekly-return correlation across variants

| | eqw×naive | eqw×lw_erc | invvol×naive | invvol×lw_erc | solo_defensive |
|:---|---:|---:|---:|---:|---:|
| eqw×naive |  +1.000  |  +0.995  |  +0.983  |  +0.981  |  +0.757  |
| eqw×lw_erc |  +0.995  |  +1.000  |  +0.982  |  +0.986  |  +0.746  |
| invvol×naive |  +0.983  |  +0.982  |  +1.000  |  +0.997  |  +0.770  |
| invvol×lw_erc |  +0.981  |  +0.986  |  +0.997  |  +1.000  |  +0.760  |
| solo_defensive |  +0.757  |  +0.746  |  +0.770  |  +0.760  |  +1.000  |

## 7. Read

Standalone layer-1 numbers say how much of the v6 book value the risk-budget + trend gate alone earns before any within-block α layer is added. Compare against:
- **solo defensive** (Phase 11.2 finalist) — the current production   book, which selects top-⌈0.20 · N_t⌉ α names pool-wide with 1/σ   sizing and no explicit block budget.
- **T2 bond_invvol** — the highest IS-Sharpe passive slice of the   pool (bond blocks, inv-vol), i.e. what the alpha stack is   competing with on Sharpe.
- **T1 universe_invvol** — hold everything, inv-vol; the   all-in passive benchmark.

**Open knobs (deferred, per user 2026-07-22):**
- intra-block sizing (eqw vs invvol) reported in parallel here;   choose in a follow-up branch once layer-1 semantics are locked.
- block-level hysteresis (ε) not applied — trend gate flips are   raw. Sweep ε ∈ {0, 0.10, 0.20, 0.30} in a follow-up.
- q = 0.20 / 0.10 within-block α overlays are Phase 13 territory   and get their own parallel branch.

