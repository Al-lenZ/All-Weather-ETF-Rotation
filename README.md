# All-Weather ETF Rotation Strategy

A weekly-rebalanced, block-neutral rotation strategy on the Chinese ETF universe. The book is built in two layers: a **within-block cross-sectional α** on blocks where a proper cross-section exists, and a **risk-budgeted allocation across blocks** on the rest. The design was frozen after a pre-registered stress test, then extended with a whole-book vol-target leverage overlay and a forward hold-out shot.

This repo is a **public mirror of the research code**: engines, backtests, reports, and design docs are here; raw data, factor definitions, and any script that touches the data vendor's API are held back (see [Reproducibility & scope](#reproducibility--scope) below).

---

## Headline results

All figures are **net of 10 bp/side turnover cost** (always on). IS windows are warmup-trimmed to an apples-to-apples common start (2019-05-31); OOS is 2024-01-01 → 2025-07-31.

| Configuration | Window | Sharpe | CAGR | MaxDD |
|---|---|---:|---:|---:|
| Solo defensive baseline | IS | +1.00 | +3.48% | −5.24% |
| Solo defensive baseline | OOS | +2.23 | +2.19% | −0.78% |
| **Two-layer finalist** (q=0.20, ε=0.30) | IS | **+1.58** | **+4.24%** | **−2.54%** |
| **Two-layer finalist** | OOS | **+3.62** | **+4.48%** | **−0.36%** |
| Two-layer + vol-target overlay (σ*=3.2%, cap=2.0) | Hold-out (2025-08-01 → 2026-08-04, 53 weekly bars) | net **+2.10** (excess **+1.22**) | net **+3.42%** (excess **+1.99%**) | −0.52% |

The hold-out row folds in the pre-registered stress window (2025-08-01 → 2026-07-17) plus 2.5 weeks of newly-fetched forward bars. Excess-of-cash metrics use a DR007 proxy for funding and cash carry.

Full metric tables, block-level attribution, and figures are in the compiled reports under `two_layer_report_cn/`, `leverage/reports/`, and `hold_out_backtest/reports/`.

**Honest caveat:** the 2025-08 → 2026-08 hold-out window was bond-friendly (T2 bond-invvol alone printed Sharpe +2.94 over the pre-registered slice), so the finalist's hold-out pass is a "did the machinery survive a real forward window" result rather than a 2020/2022-class regime test. The 2026 slice is also visibly weaker than the 2025 slice (excess Sh ~0.73 vs ~1.91), consistent with the signal cooling into the newer bars.

---

## Method at a glance

**Universe.** ~100+ mainland Chinese ETFs plus a small HK convertibles pocket, index-deduped, membership-masked point-in-time. Blocks: `broad_cn`, `sector_cn`, `smallcap_cn`, `cross_border_dm`, `cross_border_hk`, `bond_rates`, `bond_credit`, `metals`, `commodity_other`.

**α layer (within-block).** A PV-style factor library is screened per block, deduped, then ensembled by row-z of raw α (not stage-2 rank). Positions are taken as top/bottom quantile with a hysteresis band ε to control turnover. Frozen finalists per block are documented in `dedup_stability_ensemble/reports/`.

**Non-α layer (across-block).** Blocks without a usable cross-section (broad, rates, commodities, cross-border) get a risk-budgeted allocation. The frozen layer-1 finalist uses equal-weight × Ledoit-Wolf ERC representative sets (see `block_risk_budget/reports/phase12_layer1_milestone.md`).

**Sizing & vol.** Inverse-vol sizing on a causal 26-week window; a dedicated vol-forecast module is recalibrated per phase.

**Leverage.** Optional whole-book vol-target overlay (σ* target, hard cap L). A diagnostic representative-set variant runs alongside; a higher-cap sensitivity round probes the risk/return frontier. GC007 is the reported funding curve, with a DR007 proxy check.

**Discipline.** Every design phase is IS-only until pre-registered OOS / stress shots. The 2025-08 → 2026-08 window is a **used** hold-out and is explicitly not reusable as OOS in any future version.

---

## Repo layout

```
common/                     shared cross-sectional & sizing engines
universe/                   universe construction, block tagging (API loaders redacted)
baseline_and_screens/       PV sweeps, EQW baseline, hysteresis / sizing / cost sweeps
book_and_blender/           book construction, ridge & oracle blenders
block_risk_budget/          layer-1 allocation, two-layer book
dedup_stability_ensemble/   within-block dedup, stability, ensemble finalists
vol_forecast/               vol forecasting module
bond_attribution/           bond-leg attribution & residual α
exp1_risk_budget_sensitivity/  sensitivity surface around the finalist
exp2_representative_sets/      adaptive-K residual-vol representative sets
leverage/                   vol-target overlay, funding, higher-cap Round D
hold_out_backtest/          live hold-out shot extended to 2026-08-04
two_layer_report_cn/        stress test pre-reg + Chinese finalist report
final_report_cn/            top-level Chinese v6 report
```

Most subdirectories follow the same shape: `scripts/` for runners, `reports/` for the Markdown / DOCX writeups.

## Reports worth reading first

- `two_layer_report_cn/two_layer_strategy_report_cn.pdf` — the finalist two-layer book.
- `two_layer_report_cn/STRESS_TEST_PREREG.md` + `v6_stress_test_report_cn.docx` — pre-registered stress test and result.
- `leverage/reports/leverage_ab_report.md` and `leverage_higher_cap_round_d.md` — leverage overlay and cap sensitivity.
- `hold_out_backtest/reports/v6_hold_out_shot_report_cn.pdf` — forward hold-out (2025-08-01 → 2026-08-04).
- `DESIGN_v6_universe.md` — universe design and the "power problem" framing that motivated the current pool.

## Reproducibility & scope

This repo is **not directly runnable**. Intentionally held back:

- **All data.** No price history, no factor cache, no panels, no backtest artifacts.
- **Vendor API code.** Any script that pulls from the data vendor is excluded, including its access mechanism.
- **Factor construction & panel build.** The exact factor library and label-panel builder are not published.

Downstream engines, blenders, sizers, backtest orchestration, and every writeup remain public so a reader can follow the design and evaluate the evidence. If you need to run against your own data, the engines expect abstract `(fwd_1w, sigma, label)` panels — see the report signatures for the contract.

## Contact

Author: Allen Zhou — allenzhou568@gmail.com
