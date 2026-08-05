# Phase 12 layer-1 — block risk budgeting + trend gate (standalone, no α)

Generated: 2026-07-22 19:16:15  

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
| eqw × naive | +1.309 | +3.58% | -2.68% | +2.90% | 0.033 | 91.1 | 17.8% |
| eqw × lw_erc | +1.405 | +3.63% | -2.47% | +2.68% | 0.034 | 91.1 | 17.8% |
| invvol × naive | +1.350 | +3.41% | -2.55% | +2.48% | 0.045 | 91.1 | 17.8% |
| invvol × lw_erc | +1.418 | +3.43% | -2.55% | +2.39% | 0.048 | 91.1 | 17.8% |

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
| eqw × naive |  57.5% |  20.9% |  10.0% |  15.7% | 292 |
| eqw × lw_erc |  57.5% |  20.9% |  10.0% |  15.7% | 292 |
| invvol × naive |  57.5% |  20.9% |  10.0% |  15.7% | 292 |
| invvol × lw_erc |  57.5% |  20.9% |  10.0% |  15.7% | 292 |

### 3b. Mean RC over all invested IS bars (gate-averaged)

| variant | equity | bond_rates | bond_credit | commodity |
|:---|---:|---:|---:|---:|
| policy |  55.0% |  20.0% |  10.0% |  15.0% |
| eqw × naive |  57.5% |  20.9% |  10.0% |  15.7% |
| eqw × lw_erc |  57.5% |  20.9% |  10.0% |  15.7% |
| invvol × naive |  57.5% |  20.9% |  10.0% |  15.7% |
| invvol × lw_erc |  57.5% |  20.9% |  10.0% |  15.7% |

## 4. Trend-gate % ON per group (IS, post-warmup)

| variant | equity | bond_rates | bond_credit | commodity | mean n_switches |
|:---|---:|---:|---:|---:|---:|
| eqw × naive | 100.0% | 100.0% | 100.0% | 100.0% | 0.0 |
| eqw × lw_erc | 100.0% | 100.0% | 100.0% | 100.0% | 0.0 |
| invvol × naive | 100.0% | 100.0% | 100.0% | 100.0% | 0.0 |
| invvol × lw_erc | 100.0% | 100.0% | 100.0% | 100.0% | 0.0 |

## 5. Per-calendar-year IS return (sum of weekly net)

| year | eqw × naive | eqw × lw_erc | invvol × naive | invvol × lw_erc |
|:---:|---:|---:|---:|---:|
| 2018 | +0.00% | +0.00% | +0.00% | +0.00% |
| 2019 | +6.01% | +5.88% | +6.02% | +5.86% |
| 2020 | +8.90% | +8.98% | +8.80% | +8.79% |
| 2021 | +4.46% | +4.50% | +3.71% | +3.95% |
| 2022 | +0.20% | +0.35% | +0.20% | +0.14% |
| 2023 | +2.24% | +2.45% | +1.98% | +2.12% |

## 6. IS weekly-return correlation across variants

| | eqw×naive | eqw×lw_erc | invvol×naive | invvol×lw_erc | solo_defensive |
|:---|---:|---:|---:|---:|---:|
| eqw×naive |  +1.000  |  +0.994  |  +0.976  |  +0.973  |  +0.738  |
| eqw×lw_erc |  +0.994  |  +1.000  |  +0.974  |  +0.980  |  +0.735  |
| invvol×naive |  +0.976  |  +0.974  |  +1.000  |  +0.995  |  +0.775  |
| invvol×lw_erc |  +0.973  |  +0.980  |  +0.995  |  +1.000  |  +0.767  |
| solo_defensive |  +0.738  |  +0.735  |  +0.775  |  +0.767  |  +1.000  |

## 7. Read

Standalone layer-1 numbers say how much of the v6 book value the risk-budget + trend gate alone earns before any within-block α layer is added. Compare against:
- **solo defensive** (Phase 11.2 finalist) — the current production   book, which selects top-⌈0.20 · N_t⌉ α names pool-wide with 1/σ   sizing and no explicit block budget.
- **T2 bond_invvol** — the highest IS-Sharpe passive slice of the   pool (bond blocks, inv-vol), i.e. what the alpha stack is   competing with on Sharpe.
- **T1 universe_invvol** — hold everything, inv-vol; the   all-in passive benchmark.

**Open knobs (deferred, per user 2026-07-22):**
- intra-block sizing (eqw vs invvol) reported in parallel here;   choose in a follow-up branch once layer-1 semantics are locked.
- block-level hysteresis (ε) not applied — trend gate flips are   raw. Sweep ε ∈ {0, 0.10, 0.20, 0.30} in a follow-up.
- q = 0.20 / 0.10 within-block α overlays are Phase 13 territory   and get their own parallel branch.

