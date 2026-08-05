# v6 static baseline — cost-burn attribution

Generated: 2026-07-20

## Motivation

The Phase 9.1 static baseline (`book_xs_v6_report.md`) uses vol-scaled
weighting inside the top-⌈q·N⌉ selection: `w_i ∝ 1/σ_causal_26w_i`,
renormalized to Σw = 1 (long-only) or ±0.5 (long-short). Turnover on the
four surviving cells (`long_q05`, `long_q10`, `long_q20`, `ls_q20`) is
noticeably high, and the working theory was that vol-scaling itself is a
turnover generator — even with a stable α ranking, `σ_i` drifts each week
as the 26w window rolls and any rotation in the top-K forces every held
weight to renormalize.

This report tests that theory by decomposing each cell's weekly turnover
into two channels:

- **selection** — |Δw| on names that entered *or* exited the book
  between bar t-1 and bar t (one side had zero weight).
- **sizing** — |Δw| on names present in *both* bars (both sides
  non-zero). Pure weight adjustment, driven by σ-drift and by
  denominator renormalization when a co-holding rotates in/out.

Partitioning is exact: `Σ|Δw_t| = selection + sizing`, verified per bar
against a 1e-9 residual. Costs are recomputed at the Phase 9.1 rate
(10 bp / side turnover), gross Sharpe rerun by dropping the cost term on
the *same* weight panel and forward-return series that produced the
checked-in `ensemble_net_ret.csv`.

## Cell headline

Windows: **IS** ≤ 2023-12-31 · **OOS** 2024-01-01→2025-07-31 · **full** =
IS ∪ OOS (hold-out sealed).

| cell | turnover | selection | sizing | sizing % | cost bps/yr | gross Sharpe (full) | net Sharpe (full) | cost / gross ret |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|
| long_q05 | 0.293 | 0.255 | 0.038 | 13% |  152 | +1.798 | +0.967 | 45% |
| long_q10 | 0.288 | 0.247 | 0.041 | 14% |  150 | +1.491 | +0.829 | 44% |
| long_q20 | 0.278 | 0.240 | 0.038 | 14% |  145 | +1.446 | +1.013 | 30% |
| ls_q20   | 0.812 | 0.693 | 0.120 | 15% |  422 | +0.926 | +0.450 | 51% |

Turnover columns are per-bar averages (fraction of gross exposure
rotated in one week). "cost / gross ret" is `cost_bps_yr /
gross_ret_bps_yr` over the full IS ∪ OOS window.

## Gross vs net Sharpe by window

| cell | IS gross | IS net | OOS gross | OOS net | full gross | full net |
|:---:|---:|---:|---:|---:|---:|---:|
| long_q05 | +1.751 | +1.052 | +2.921 | +0.591 | +1.798 | +0.967 |
| long_q10 | +1.401 | +0.808 | +3.332 | +1.473 | +1.491 | +0.829 |
| long_q20 | +1.390 | +1.002 | +3.702 | +2.071 | +1.446 | +1.013 |
| ls_q20   | +0.965 | +0.503 | +0.795 | +0.275 | +0.926 | +0.450 |

## Findings

**1. Cost burn is high — confirmed.**  On the long books cost eats 30–45%
of gross return and roughly halves full-window Sharpe (long_q05:
+1.80 → +0.97; long_q10: +1.49 → +0.83; long_q20: +1.45 → +1.01). The LS
book is worse: 51% of gross gone to cost, Sharpe halved from +0.93 to
+0.45.

**2. Vol-scaling is not the dominant driver.**  Sizing turnover is 13–15%
of total turnover in every cell (13.1% · 14.3% · 13.6% · 14.7%).
Selection — names crossing the top-K boundary — is doing 85–87% of the
work. This refutes the working theory that σ-drift and renormalization
are the main cost generator.

**3. Ceiling on the equal-weight uplift is small.**  Equal-weight
(`w = 1/K_t`) eliminates σ-drift on retained names but *keeps* the
renormalization-on-rotation component of the sizing bucket
(retained name shifts from 1/(K-1) to 1/K when a co-holding rotates).
So the removable share of the ~14% sizing channel is bounded above by
14% of cost — call it ~15–20 bps/yr on the long cells, ~60 bps/yr on
ls_q20. Non-zero, but not close to bridging the gross↔net gap.

**4. Where the cost actually lives is the top-K churn.**  On long_q05,
selection turnover ≈ 25.5% per week means on average ~1.2 of the 4.7
picks rotate out each rebal (each entry + exit contributes ~w_i ≈ 21%
to selection turnover — one full-weight sell + one full-weight buy per
rotation). Similar picture across long_q10 and long_q20. The LS cell
churns much harder (69% selection turnover, roughly 2× the long books).

**5. Gate on the equal-weight experiment does NOT trip.**  The
pre-registered rule was: run EQW if sizing share ≥ 30% in ≥ 2 cells.
Sizing share is 13–15% everywhere; the gate does not fire on its
original rationale.

## Implication for next work

The mechanistic finding shifts the productive follow-ups from *weighting
scheme* to *set persistence*:

- A buffer / hysteresis around the top-K boundary (name only exits if
  rank falls to > (1 + ε) · K), analogous to the ADV hysteresis in the
  membership rules (design §2.4).
- Smoother alpha inputs (longer look-back / EWMA on the ensemble α
  before ranking) — direct attack on rank-flip frequency.
- Lower rebal cadence (biweekly, monthly) — the turnover-per-bar drop is
  larger than the return-per-bar drop if the alpha decays slower than
  weekly.
- Cost-aware selection (only rebalance a name if `expected_alpha_gain >
  2 · cost`).

Equal-weight is still worth a one-shot confirmation experiment because
the theoretical ceiling (~15% cost reduction) is easy to verify and
falsifies-or-confirms the sizing-channel size. But it is not the fix.

The user's original request permits either path — cost burn *is* high,
which was the trigger condition. Ask whether to (a) run the small EQW
confirmation, (b) go straight to a churn-reduction experiment, or (c)
park this and return to Phase 7 PV factor sweep.

## Files

- `data/v6_static/cost_attribution/summary.csv` — this table
- `data/v6_static/cost_attribution/{cell}_bar.csv` — per-bar
  port_ret / net_ret / cost / turnover / turn_selection / turn_sizing
  (IS ∪ OOS window only; hold-out sealed)
- `scripts/cost_attribution_v6.py` — one-shot rerun; no re-screen, reads
  persisted `ensemble_weights.parquet` for each cell
