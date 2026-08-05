# v6 Implementation Plan

Companion checklist to `DESIGN_v6_universe.md`. Sequential — do steps in order,
respect the gates. Whenever a step says "port from v4pool," the reference is
`v4pool/xs_ic_pipeline/scripts/<file>.py`; the v6 counterpart is a new file, not
an in-place edit (see [[feedback-no-edit-artifacts]]).

## Folder layout (create up-front, then never re-organize)

```
v6/
├── DESIGN_v6_universe.md       # design doc, stays at root
├── IMPLEMENTATION_PLAN.md      # this file
├── scripts/                    # all .py — modules + runnable scripts
│   ├── _common_v6.py           # ported from v4pool _common.py, ragged-aware
│   ├── universe_v6.py          # rules + MEMBERSHIP builder
│   ├── loader_universe_v6.py   # catalogue + px + AUM data pull
│   ├── universe_v6_report.py   # diagnostics on MEMBERSHIP
│   ├── compute_factors_v6.py   # factor cache build for all admitted codes
│   ├── pv_sweep_xs_v6.py       # port of pv_sweep_xs.py, z-stat gate
│   ├── stability_halfsplit_v6.py
│   ├── eqw_baseline_v6.py
│   ├── fit_ridge_xs_v6.py
│   ├── book_xs_v6.py           # vol-scaled weights, quantile K
│   └── book_diagnostics_v6.py  # includes block-neutral IC
├── data/                       # every artifact the code writes
│   ├── universe_v6/            # catalogue.csv, px_daily.parquet, aum_daily.parquet,
│   │                           # membership.parquet, membership_changes.csv
│   ├── px_daily/               # per-code OHLCV parquets ({code}.parquet), split
│   │                           # out from universe_v6/px_daily.parquet for the
│   │                           # factor library (which is per-instrument)
│   ├── factor_cache/           # per-code wide factor parquets ({code}_1d.parquet,
│   │                           # {code}_60m.parquet) — v6-scoped, isolated from
│   │                           # global data/factors_cache/
│   ├── pv_sweep_xs_v6.csv
│   ├── pv_sweep_xs_v6_dedup.csv
│   ├── stability_halfsplit_v6.csv
│   ├── book_score_v6.csv
│   ├── book_sharpe_v6.csv
│   ├── book_diag_v6.csv
│   └── ...
└── reports/                    # every human-readable .md
    ├── universe_v6_report.md
    ├── pv_sweep_xs_v6_report.md
    ├── stability_halfsplit_v6_report.md
    ├── book_xs_v6_report.md
    └── book_diagnostics_v6_report.md
```

Rule: no `.csv`/`.parquet` under `scripts/`, no `.py` under `data/` or
`reports/`. Do not touch `v4pool/xs_ic_pipeline/` — clone the logic into
`v6/scripts/` and evolve it there.

---

## Phase 0 — scaffolding (no science)

- [ ] **0.1** Create the three subfolders above (`scripts/`, `data/`,
  `reports/`, plus `data/universe_v6/`).
- [ ] **0.2** Copy `v4pool/xs_ic_pipeline/scripts/_common.py` →
  `v6/scripts/_common_v6.py` unchanged (edits happen in Phase 4). Fix the
  `_HERE.parents[...]` path preamble so it still resolves the repo root, v4
  module dir, and v5 `static/return_model` dirs from the new location.
- [ ] **0.3** Add module-level constants block to `_common_v6.py`:
  `PIPELINE_ROOT = _HERE.parents[1]` → will now point at `v6/`. Verify
  `DATA_DIR = PIPELINE_ROOT / "data"` and `REPORTS_DIR = PIPELINE_ROOT /
  "reports"` resolve to `v6/data/` and `v6/reports/`.

---

## Phase 1 — universe module skeleton  (design §2, §9 step 1)

Logic-only pass — no data pull yet. The point is to lock the rule surface in
code and unit-test it on a synthetic panel so Phase 2's data pull has a fixed
consumer.

- [ ] **1.1** Write `v6/scripts/universe_v6.py` exporting the interface from
  design §2.6:
  - `MEMBERSHIP: pd.DataFrame` (W-FRI × code, bool)
  - `CODES: list[str]`
  - `BLOCK_TAG: dict[str, str]`  (blocks per §2.1)
  - `INDEX_OF: dict[str, str]`
  - `NAME_EN: dict[str, str]`
- [ ] **1.2** Encode rule constants as module-level named values (no magic
  numbers scattered downstream):
  - `SEASONING_BARS = 26`  (§2.3)
  - `ADV_FLOOR_ENTER = 50_000_000`, `ADV_FLOOR_EXIT = 25_000_000`  (§2.4 —
    provisional; frozen in Phase 3)
  - `ADV_PCTL_ENTER = 0.20`, `ADV_PCTL_EXIT = 0.15`  (top 80% enter / bottom
    exit boundary at 85th pctl; §2.4)
  - `AUM_FLOOR_ENTER = 200_000_000`, `AUM_FLOOR_EXIT = 100_000_000`
  - `INDEX_DEDUP_ADV_MARGIN = 0.25`  (§2.2 anti-churn)
  - `BLOCKS = ("broad_cn", "sector_cn", "smallcap_cn", "cross_border_dm",
    "cross_border_hk", "bond_rates", "bond_credit", "metals",
    "commodity_other")` — frozen before any IC.
- [ ] **1.3** Implement `build_membership(catalogue, px_daily, aum_daily,
  rebal_idx) -> (MEMBERSHIP, changes_log)` applying, per bar and in order:
  1. seasoning gate,
  2. absolute ADV + AUM floors with hysteresis,
  3. relative ADV percentile gate with hysteresis,
  4. per-`underlying_index` representative selection (25% margin).
  Membership changes take effect at the *next* bar (no intra-bar entry/exit).
- [ ] **1.4** Write a small synthetic-panel unit test (in the same script's
  `if __name__ == "__main__":` or a sibling `tests_universe_v6.py`) that:
  - a name below the floor never enters,
  - a name that crosses the entry floor then drifts to (floor_exit,
    floor_enter) stays in,
  - a challenger with < 25% higher ADV does *not* dethrone the incumbent,
  - a name delisted mid-panel exits at delist_date, not later.

Gate: rule text in this doc matches the code paths in `universe_v6.py`.

---

## Phase 2 — data pull  (design §4, §9 step 2)

Data-loading rules to respect (per the user, restated from design §4):
- **Everything point-in-time.** No look-ahead in ADV, AUM, or index membership.
- **All names in one shot** — pull the full candidate catalogue, filter in code,
  not at the query. The MEMBERSHIP builder is the only place membership rules
  live.
- **Timezone-safe date alignment** on the W-FRI grid; use the same
  `_rebalance_dates` helper as v4pool.
- **No intermediate CSV mutations** — parquet is the store of record, the
  audit CSV in step 2.5 is the *only* CSV written.

- [ ] **2.1** Write `v6/scripts/loader_universe_v6.py` (pattern:
  `v4pool/xs_ic_pipeline/scripts/loader_etf_native.py`). One entry point
  `pull_all(refresh=False)` orchestrating steps 2.2–2.4.
- [ ] **2.2** Pull the catalogue of all exchange-traded ETFs on SSE + SZSE
  (equity index, cross-border, bond, commodity; **exclude money-market**).
  Fields per design §2.1. Write `v6/data/universe_v6/catalogue.csv`.
  Manually tag `block` for every candidate before any downstream step runs.
- [ ] **2.3** Pull daily OHLCV + amount for every catalogue name over
  `[max(list_date, 2018-06-01), today]`. Write
  `v6/data/universe_v6/px_daily.parquet` (long: date, code, o/h/l/c, volume,
  amount).
- [ ] **2.4** Pull daily AUM (or shares_outstanding × NAV) →
  `v6/data/universe_v6/aum_daily.parquet`.
- [ ] **2.5** Print a coverage report to stdout: per-name % of expected bars
  with a defined ADV and a defined AUM; flag anything under 95%.

Gate: coverage report reviewed; any name with a data gap either explained or
excluded before Phase 3.

---

## Phase 3 — MEMBERSHIP build + rules freeze  (design §9 step 3)

- [ ] **3.1** Run `build_membership(...)` from Phase 1 on the Phase 2 data.
  Write `v6/data/universe_v6/membership.parquet` (W-FRI × code, bool).
- [ ] **3.2** Emit `v6/data/universe_v6/membership_changes.csv` — one row per
  event `∈ {enter, exit_floor, exit_pctl, exit_delist, repr_switch}` with
  the trigger value that fired the rule.
- [ ] **3.3** Write `v6/scripts/universe_v6_report.py` — produces
  `v6/reports/universe_v6_report.md` with:
  - N(t) curve (line, weekly),
  - block composition through time (stacked area, weekly),
  - churn rate per year (bar),
  - ADV distribution by year (box or histogram grid),
  - the pre-registered N(t) sanity targets from §2.5 side-by-side with
    actuals.
- [ ] **3.4** **Human review checkpoint.** If N(2019-12) falls outside
  40–60, recalibrate the floors *once*, rerun 3.1–3.3, record the change in a
  new §2.4 addendum inside `DESIGN_v6_universe.md`, then freeze.

**Gate:** rules and floors frozen in the design doc; no downstream step may
tune them.

---

## Phase 4 — factor cache build for admitted codes  (new; not in design §9)

Rationale: the screening scripts (`pv_sweep_xs.py` and every downstream
consumer) expect a per-code wide factor parquet on disk that `etf_io.load_caches`
can read and `etf_io.build_alpha_panel` can slice. The v4pool run built these
against `universe_v4.CODES`; v6's expanded catalogue means most admitted names
have no cache yet. Compute them **once**, after MEMBERSHIP is frozen (Phase 3),
so downstream sweeps have a stable, pool-scoped cache to read.

- [ ] **4.1** Derive the code set to compute for:
  `CODES_V6 = list(MEMBERSHIP.columns[MEMBERSHIP.any(axis=0)])` — the union
  of names ever admitted at any bar over IS + OOS. Never-admitted catalogue
  entries are skipped.
- [ ] **4.2** Split `v6/data/universe_v6/px_daily.parquet` (long-form) into
  per-code parquets at `v6/data/px_daily/{code}.parquet` with columns
  `open, high, low, close, volume, total_turnover` (rename `amount` →
  `total_turnover` if the loader uses the RQ convention). The factor library
  in `factors/registry.py` is per-instrument; it expects one ETF's OHLCV
  frame at a time (see `compute_factors.py`).
- [ ] **4.3** Write `v6/scripts/compute_factors_v6.py` — a v6-scoped clone of
  the root `compute_factors.py`. Differences from the original:
  - reads prices from `v6/data/px_daily/{code}.parquet` (not
    `_bootstrap.price_path`),
  - writes caches to `v6/data/factor_cache/{code}_{freq}.parquet` (not
    `_bootstrap.cache_path`),
  - iterates `CODES_V6` (Phase 4.1), not `universe.CODES`,
  - keeps the existing "skip if cache up-to-date by mtime" behavior and the
    `--force` override,
  - freq set: `1d` mandatory. `60m` only if intraday parquets exist for the
    admitted names — most v6 additions likely have daily-only data at first.
- [ ] **4.4** Add `load_caches_v6(freq, codes)` and (if needed)
  `build_alpha_panel_v6` to `v6/scripts/_common_v6.py` — thin wrappers over
  the `etf_io` versions that point at `v6/data/factor_cache/` instead of the
  global `data/factors_cache/`. This keeps v4pool's caches untouched and
  makes v6 sweeps hermetic.
- [ ] **4.5** Print a cache summary to stdout and to
  `v6/reports/factor_cache_v6_report.md`: per-code count of factors
  successfully computed, list of any factors that returned all-NaN, total
  disk footprint. Cross-check that `common_factors(load_caches_v6("1d",
  CODES_V6))` — the intersection of factor names across all admitted codes
  — is not surprisingly small.

Uses **the same `factors.registry.REGISTRY`** as v4pool — no new factor
construction in v6 (design §0/§10 explicit non-goal).

Gate: `common_factors(...)` on the v6 cache set contains the full PV
family expected by Phase 7's sweep (≈ the same 300+ that v4pool sees). A
big drop here means an ingestion problem in Phase 2, not a factor-library
problem — investigate before running Phase 7.

---

## Phase 5 — patch `_common_v6.py` for ragged panels  (design §5, §9 step 4)

- [ ] **5.1** Consumers now must pass membership-masked panels. Add a helper
  `apply_membership(panel, membership) -> panel` that NaNs out entries where
  membership is False, and call it from every stage-2 builder.
- [ ] **5.2** Extend `ic_summary` with the weighted mode from design §5:

  ```
  z_t   = ic_t * sqrt(N_t - 1)          # ~ N(0,1) under null
  Z     = mean(z_t) * sqrt(T)           # panel z-score  (primary sort key)
  ic_w  = sum(w_t * ic_t) / sum(w_t),  w_t = N_t - 1
  ```

  Return both the legacy `{mean, std, tstat, pct_pos, n_bars}` columns AND
  the new `{zstat, mean_ic_w, mean_N}` columns. Do NOT silently rename —
  downstream sweeps switch to `zstat` explicitly.
- [ ] **5.3** Rename `precision_at_k` → `precision_at_q(alpha, target, q,
  membership, side)` with `k_t = ceil(q * N_valid_t)` and `min_valid`
  scaled accordingly. Keep the old function under its old name as a shim
  that calls the new one with a resolved `k` — keeps v4pool scripts (if
  ever re-run for a cross-check) importable, though the v6 pipeline uses
  `precision_at_q` directly.
- [ ] **5.4** Add `load_universe(version="v6") -> (CODES, BLOCK_TAG,
  MEMBERSHIP)`. Default `version="v4"` keeps v4pool call sites bit-for-bit
  identical.
- [ ] **5.5** Regression test: rerun `v4pool/xs_ic_pipeline/scripts/
  pv_sweep_xs.py` with `_common_v6` swapped in (via a temporary sys.path
  hack in the test only — do NOT modify v4pool). Assert every column of
  `pv_sweep_xs.csv` matches the checked-in v4pool artifact bit-for-bit.

Gate: v4 path reproduces the v1 sweep numbers exactly. Only then do the v6
sweeps get to run.

---

## Phase 6 — label + panel wiring  (design §3, §9 step 5)

- [ ] **6.1** Build a small `panels_v6.py` helper (or add to `_common_v6.py`)
  that returns membership-masked `fwd_1w`, `sigma_causal_26w`, and
  `ranked_risk_adj_label` on the W-FRI grid, indexed by all-ever-admitted
  codes.
- [ ] **6.2** Sanity check: for every bar, the set of non-NaN entries in each
  panel equals `MEMBERSHIP[t]`. Print `assert` or a coverage table to
  `v6/reports/panels_v6_sanity.md`.

Gate: NaN pattern of every panel matches MEMBERSHIP.

---

## Phase 7 — PV sweep rerun + pre-registered v1 survivor check  (design §6, §9 step 6)

- [ ] **7.1** Copy `v4pool/xs_ic_pipeline/scripts/pv_sweep_xs.py` →
  `v6/scripts/pv_sweep_xs_v6.py`. Swap:
  - `codes, _blocks = C.load_universe()` → `load_universe(version="v6")`
  - `load_caches(...)` → `load_caches_v6(...)` (Phase 4.4)
  - stage-2 build applies membership mask (Phase 5.1)
  - gate: `|zstat| >= 2.0` (not tstat)
  - CSV columns include `zstat`, `mean_ic_w`, `mean_N`, `n_bars`
- [ ] **7.2** **Pre-registration** — hard-code the v1 IS survivor list inside
  the script *before running it*:

  ```python
  V1_SURVIVORS = [
      "wq_023", "wq_046", "alpha_071", "wq_081", "wq_048", "alpha_028",
      "alpha_104", "alpha_036", "wq_061", "wq_068", "wq_012", "wq_008",
      "wq_059",
  ]
  ```

  The report must show these 13 factors' v6 z-stats in a labeled table
  regardless of whether they pass the gate, so the "pass more decisively at
  larger N" question in design §6 gets a clean answer.
- [ ] **7.3** Outputs:
  - `v6/data/pv_sweep_xs_v6.csv` (full, ranked by `|zstat|`)
  - `v6/data/pv_sweep_xs_v6_dedup.csv` (post stage-2 |ρ| ≤ 0.5)
  - `v6/reports/pv_sweep_xs_v6_report.md`

Gate: none for this step — it's a measurement. Any decision about v1
survivors gets recorded in the report's narrative, not swept into a
threshold.

---

## Phase 8 — dedup + stability + ensemble  (design §9 step 7)

- [ ] **8.1** Port `stability_halfsplit.py` → `stability_halfsplit_v6.py`;
  same logic, ragged-aware, uses `zstat` on each half.
- [ ] **8.2** Port `eqw_baseline.py` → `eqw_baseline_v6.py` (equal-weight
  ensemble of the dedup survivors, sign-oriented).
- [ ] **8.3** Port `fit_ridge_xs.py` → `fit_ridge_xs_v6.py`.

**Gate (design §9):** ≥ 1 factor at `|zstat| ≥ 2` surviving half-split
stability. If nothing survives → stop, write a post-mortem to
`v6/reports/postmortem_pv_sweep_v6.md`, escalate. Do NOT tune the gate to
rescue.

---

## Phase 9 — book construction  (design §7, §9 step 8)

The construction here is *different* from v4pool: α-prop weighting is out,
vol-scaling is in. Everything else about the engine wiring is analogous.

- [ ] **9.1** Rebuild the **static baseline** on the v6 pool. Same
  construction logic as v4pool's static leg, membership-aware. Record its
  OOS Sharpe in `v6/reports/book_xs_v6_report.md` — this becomes the new
  reference (retiring the v4pool +1.617 anchor).
- [ ] **9.2** Port `book_xs.py` → `v6/scripts/book_xs_v6.py`. **Two
  behavioral changes from v4pool** (design §7):
  1. **Selection is quantile-based.** `K_t = ceil(q * N_t)` per bar, membership-
     masked. Grid `q ∈ {0.10, 0.20, 0.30}`. Choose `q` on IS only by model-leg
     IS Sharpe (ties → smaller turnover). Freeze the chosen `q` before OOS.
     OOS is scored **once**.
  2. **Within the selected set, weights are vol-scaled**, not α-prop.
     `w_i ∝ 1 / σ_causal_i`, normalized to sum to 1 on the selected set.
     This matches the design §3 label (both are risk-adjusted), so the
     model is trained and evaluated on the same quantity it trades.
- [ ] **9.3** Blend leg logic (rank-space average of static + model, then
  top-q) carries over from v4pool `book_xs.py`. Only the *weighting rule
  within the top-q* changed.
- [ ] **9.4** Add the **long-short research spread** (dollar-neutral top-q
  minus bottom-q, both vol-scaled) as an *evaluation-only* leg. Report its
  Sharpe in the book report; do not use for tradable positioning (design §7
  final paragraph).
- [ ] **9.5** Port `book_diagnostics.py` → `book_diagnostics_v6.py`, adding:
  - **block-neutral IC**: recompute per-bar IC after demeaning ranks within
    `BLOCK_TAG` blocks; report raw vs block-neutral side by side (design §8).
  - churn/turnover attribution: fraction of book turnover driven by
    membership changes vs signal changes (should be small if §2.4 hysteresis
    works as advertised).

Outputs:
- `v6/data/book_score_v6.csv`, `v6/data/book_sharpe_v6.csv`,
  `v6/data/book_diag_v6.csv`
- `v6/reports/book_xs_v6_report.md`, `v6/reports/book_diagnostics_v6_report.md`

Pre-registered pass rule (from v4pool, kept): blend ΔOOS Sharpe ≥ 0 vs
static-alone book on the v6 pool. Recorded once, on the chosen `q`, no
retuning.

---

## Phase 10 — optional retest, only if Phase 8 gate passed  (design §9 step 9)

- [ ] **10.1** Retest external-projection and native families
  (`pv_sweep_external.py`, `pv_sweep_native.py`) at v6 breadth. Same
  port pattern as Phase 7. Only opens if Phase 8 produced ≥ 1 stable |z|
  ≥ 2 PV survivor.

---

## Phase 11 — two-book architecture (aggressive + defensive)

Sits above the sizing-kernel branch (§Phase 10.2 sizing sweep). The
insight is that no single sizing kernel is Pareto-optimal across
regimes: `1/σ` wins Sharpe by concentrating in low-vol names but
loses CAGR; `rank_prop` (or `1/√σ`) wins CAGR by diversifying into
higher-vol names but loses Sharpe. A **cash split between two
independently-managed books** — one of each kernel — with a global
vol multiplier deciding the split can, in principle, sit on a better
frontier than either alone.

Design:

- **Defensive book** — current `1/σ` sizing. Same selection + hysteresis
  as the Phase 9.2 baseline.
- **Aggressive book** — α-responsive sizing (`rank_prop` chosen as the
  more extreme frontier point; see §11.1). Same selection + hysteresis.
- **Global vol multiplier** — steers the cash split between the two
  books per bar. Higher next-week σ forecast → more mass to defensive.
- Hysteresis runs *per book*, so each side's roundtrip churn is
  controlled independently. Selection is shared; only the sizing
  kernel differs.

State pointer: [[project-phase-8-state]] tracks HAR forecast quality.
HAR is not yet good enough as a global multiplier, so Phase 11 is
staged around that gap.

- [x] **11.1** Aggressive-book kernel validation — this branch.
  `alpha_prop_sweep_v6.py` runs the `rank_prop` treatment against the
  `1/σ` control on the same `long_q20 replace ε=0.20` cell used by the
  1/√σ sweep. Pass criteria (kickoff prediction):
  - Net CAGR ↑ meaningfully (target: ≥ +1 pp)  → **passed** (+1.41 pp)
  - Net max DD ↑ meaningfully                   → **passed** (2.91×)
  - Net Sharpe within ~0.4 of defensive on IS   → **passed** (−0.35)
  See `reports/alpha_prop_sweep_v6_report.md`. The aggressive book is
  worth carrying into the blender.

- [x] **11.2** Oracle two-book blender — done 2026-07-21, revised
  same day after user-flagged corrections. Blender spec (user): score
  = equal-weight mean σ across equity-block members; expanding causal
  percentile → piecewise-linear λ(pct) with gates 0.3 / 0.9. Six blend
  variants (naive/inverted × causal/fwd_1w_rv/fwd_4w_rv) + best-fixed-λ
  counterfactual. Corrections applied vs the first draft: (a) proper
  oracle uses actual weekly RV from `vol_forecast_v6/rv_panel.parquet`
  not shifted trailing σ; (b) fwd_4w rolling window fixed to be truly
  forward-looking; (c) symmetric `warmup_lambda = 0.5` on both
  directions.

  **Still fails the pass rule** — best fixed λ = 0 at Sharpe +1.000;
  best honest variant `blend_fwd_4w_rv` at +0.889 (−0.11). But the
  corrected numbers change the story materially:
  - `blend_fwd_4w_rv` (naive, proper 4-week RV oracle) is the top
    honest variant: Sharpe +0.889, CAGR **+4.43%**, DD −6.95%.
    A real forward signal at 4-week horizon delivers a genuine
    frontier point (+1.00 pp CAGR at −0.11 Sharpe vs defensive).
  - `blend_inv_causal` still tops IS Sharpe at +1.024 — but the
    regime × future-return diagnostic proves it's fitting a
    lagging-signal artifact. Causal-σ high-regime spread is
    +0.34%/wk (aggressive wins) but actual fwd_1w_rv high-regime
    spread is **−0.20%/wk** and fwd_4w_rv is **−0.21%/wk**
    (aggressive loses). Causal σ picks up crisis-recovery bars,
    not actual forward vol regimes.
  - Crisis strip: full IS spread +0.033%/wk → strip both COVID +
    2022 → +0.051%/wk. Aggressive premium is NOT crisis-concentrated
    — it comes from normal weeks' up-week wins.
  - The 88% solo-book correlation cap remains: the honest ceiling
    on this design at IS is Sharpe ~+0.89, not +1.10+.
  See `reports/oracle_blender_v6_report.md` (revised) and
  `blender_diagnostics_v6.py` outputs.

- [x] **11.2 (OOS shot on finalist)** — done 2026-07-21 (fifth /
  closing revision). One-shot pre-registered OOS opening on the
  alpha_prop + ramp + fwd_4w_rv finalist. Locked config: gates 0.30/0.90,
  warmup λ 0.5, min_history 26, fwd_4w_rv from rv_panel.parquet.
  Windows: IS 292 bars, OOS 82 bars (2024-01-05 → 2025-07-25), hold-out
  51 bars still sealed. **Blender OOS Sharpe +0.579 / CAGR +1.52% /
  DD −2.77% — Pareto-DOMINATED by both solo books.** Solo defensive
  OOS +2.231 / +2.19% / −0.78%; solo aggressive_ap OOS +0.979 /
  +5.15% / −3.73%. Δ Sharpe (blender − defensive) = **−1.652**;
  IS gap was only −0.06. **The regime signal inverted on OOS:**
  high-regime (pct > 0.9) def−agg spread was −0.147%/wk on IS
  (aggressive loses in high vol) but **+0.813%/wk on OOS**
  (aggressive wins). Blender was defensive during the 8 OOS high-vol
  bars where aggressive would have earned +7.75% — lost 6.51% vs
  aggressive-alone on those bars, which is ~4 pp of CAGR drag over
  the OOS window. Cause: 2024-2025 has been unusually kind to Chinese
  equity and bonds simultaneously (defensive OOS vol 0.99% vs IS
  3.71%; solo-book correlation dropped from 91% IS to 60% OOS); the
  "top-decile forward RV" bars are equity rallies not crisis weeks.
  **Decision (per user fallback): adopt solo defensive as v6 finalist.**
  Two-book design retired. See `reports/blender_oos_shot_v6_report.md`.

- [x] **11.3** HAR-driven blender — **do not open**. Phase 11.3 was
  designed to test how much of the oracle's Sharpe / CAGR edge a
  realistic HAR forecast could recover. The oracle itself failed OOS
  (Sharpe +0.579 vs defensive +2.231). A realistic forecast can only
  be a noisier version of the same failed signal — nothing to gain.

- [x] **11.2 (alpha_prop last round)** — done 2026-07-21 (fourth
  revision). User asked to test the v4pool/v5 α-**proportional** sizing
  (weights ∝ α − min(α_held) + rng/H) as the aggressive book, keeping
  rank_prop as the prior baseline for comparison. 4 blend variants
  (ramp/binary × 1w/4w RV oracle) + 2 solo + fixed-λ. **Best result of
  every round so far:** `blend_fwd_4w_rv` (ramp, alpha_prop) at Sharpe
  **+0.940** / CAGR +4.20% / DD −5.67% — closest to solo defensive
  Sharpe (−0.06 gap) with +0.77 pp CAGR uplift. All 6 blend variants
  and the solo book have higher Sharpe under alpha_prop than under
  rank_prop; average uplift +0.05 Sharpe on blends, +0.10 on solo.
  Alpha_prop is more concentrated on high-α names (eff N 9.6 vs
  rank_prop's 12.2), which lowers vol AND lifts Sharpe simultaneously
  — magnitude weighting captures α-realized-return signal that rank
  weighting was discarding. Ramp beats binary under alpha_prop
  (previous rank_prop finding was the opposite) because the α-level
  book already tilts toward the right names, so the ramp's middle
  band isn't giving up edge. **Passes the relaxed pass rule** (oracle
  Pareto-dominates fixed-λ=0.75 on Sharpe and DD at essentially
  matched CAGR); still fails strict rule (best fixed λ = 0 at
  Sharpe +1.000). See `reports/oracle_blender_ap_v6_report.md`.

- [x] **11.2 (binary addendum)** — done 2026-07-21 (third revision).
  User asked for a binary variant (λ=0 above pct 0.9, λ=1 otherwise)
  with switching-cost + high-vol-week def−agg diagnostics.
  `binary_fwd_1w_rv` gets Sharpe +0.843 / CAGR +5.41% / DD −12.06%
  — Pareto-dominates solo aggressive. `binary_fwd_4w_rv` gets
  Sharpe +0.815 / CAGR +5.39% / DD −12.37%. Switching cost small
  (23–50 bps/yr, 1–2.5 defensive episodes/yr, 1.6–3.5 week mean
  dwell). Also fixed a transient-NaN churn bug (holiday weeks with
  no RV data) via `hold_through_transient_nan`. See
  `reports/oracle_blender_v6_report.md` §Binary schedule diagnostic.

- [x] **11.2b** Retracted. First draft recommended pre-registering
  `blend_inv_causal` for OOS; the revised diagnostic shows the
  inverted-causal IS win is a lagging-signal artifact (crisis-recovery
  fitting), not a real regime effect. Do not run.

- [ ] **11.2c** Diversify the selection axis, not just sizing. The
  88% solo-book correlation is a structural cap on any same-selection
  blender. Under the oracle 4-week signal the IS Sharpe ceiling is
  +0.89 vs defensive +1.00 — the design earns CAGR at a Sharpe
  cost, but can't beat defensive on Sharpe with matched selection.
  Two concrete branches (independent of 11.3):
  - Aggressive book at larger q (0.30 or buffer rule) so the two
    books pick partially disjoint universes.
  - Aggressive book with momentum-tilted α, defensive with the current
    mean-reversion ensemble. Requires a second α stack.

---

## Phase 12 — block-level risk budgeting  (FROZEN — do not implement)

**Status.** Frozen 2026-07-22 pending Phase 13's within-block IC verdict.
Direction, spec, and rationale captured here so the design survives context
switches; no code work opens until the user green-lights it.

**Motivation.** `project_bond_attribution` + `project_block_neutral_ic` say
the v6 baseline's PnL is dominated by block-β (long_q05 IS *is* bond
inv-vol up to noise; long_q20's univariate residual over T2 collapses from
+2.36 % / +0.65 Sharpe to +1.08 % / +0.40 once the equity leg T4 is added
— see `bond_attribution_v6.md` §6). The right architecture separates the
two decisions: (a) at the block layer, decide *how much of the book each
block earns* (all-weather rotation); (b) inside each block, run α ranking
on the members. This phase specs layer (a) only.

**Design (per user 2026-07-22).**

- **Risk-based budgeting from the full covariance matrix**, not equal
  risk contribution. Equal RC would push credit + rates back to the
  same 50-70 % share the long_q05 book already learned by accident,
  which defeats the point.
- **Policy risk-contribution budget** (initial values, sum = 100 %):

  | block group | share | notes |
  |:---|---:|:---|
  | equity (broad_cn + sector_cn + smallcap_cn + cross_border_dm + cross_border_hk) | 55 % | one aggregate, split within later |
  | bond_rates  | 20 % | **must** stay separate from bond_credit — different stress behavior |
  | bond_credit | 10 % | |
  | metals + commodity_other | 15 % | |

  Later work may invert to solve for a Sharpe- or drawdown-optimal
  contribution ratio; the policy is the null it must beat.
- **Trend-gate overlay.** For each block, when its price is below
  the 10-month moving average, its share of the risk budget rolls to
  cash rather than being redistributed to on-trend blocks. This is
  the CTA-tail hedge on top of the risk-parity core; keeps the design
  no-crystal-ball but avoids doubling down on regimes that are
  bleeding.
- **Soft float.** Realized risk contribution may drift ±10 pp from the
  policy value per block based on the trend gate — no hard capital
  cap. This preserves the trend overlay's authority to fully de-risk
  a block if needed.
- **Estimator hygiene** (deferred to implementation):
  - Covariance window and shrinkage TBD; probably rolling 52 W with
    Ledoit-Wolf, but confirm on v6 data before locking.
  - Trend indicator on price index, not the α ensemble — kept
    independent of the selection layer.
  - Membership churn: block-level policy is on *the block*, not
    per-code, so no re-optimization on new admits.

**Thin-block treatment (per user 2026-07-22, Phase 13.1 census).**
Blocks flagged ``thin`` by `block_xs_census_v6` — bond_credit,
bond_rates, cross_border_dm, metals, commodity_other, plus the
merged-away smallcap_cn — get their **risk budget spent as block-
internal equal weight**, no α layer. Rationale: their cross-section
is structurally too narrow to screen factors on (see
[[project-within-block-ic]]); the trend-gate overlay + risk
contribution to policy budget carries all the block-level decision.
As their N_b grows past MIN_VALID_ROW = 5 in future data, revisit
whether within-block screening becomes viable.

**broad_cn α layer — LOCKED 2026-07-22 (do not retune before Phase 12 shot).**
Per 13.5 within-block ensemble (`within_block_ensemble_v6_report.md`):
K = 5 low-turnover, high-|z| ensemble on broad_cn (post-smallcap
merge) delivered **IS net Sharpe +0.907 / CAGR +11.85% / DD −13.70%**
at q = 0.20, ε = 0.20, cost 10 bp/side — ΔSharpe **+0.45** vs the
eqw hold-all null (+0.475) and **+5.3 pp CAGR** headroom. 1/σ and
eqw sizing essentially tied.

- **Members** (equal-weight row-z average of stage-1 z, polarity
  applied): `alpha015` (raw, z +3.37), `alpha_071` (raw, +3.16),
  `alpha_102` (raw, +2.70), `h_mom_decay_12_48` (raw, +2.59),
  `alpha006` (rev, −2.37).
- **Selection filter used**: |zstat| ≥ 2.0 AND 13.4 solo turnover
  ≤ 0.60. Rank in the pool by |zstat|, tie-break by lower turnover.
- **Frozen ε / q**: 0.20 / 0.20 (production long_q20 replace kernel).
  Both sizings stay in Phase 12 until the shot; final pick between
  1/σ and eqw is a Phase-12 decision, not a 13.5 branch.
- **OOS**: SEALED. Do not open until Phase 12 opens its OOS shot.

**sector_cn α layer — LOCKED 2026-07-22 (accepted despite photo-finish miss).**
Per 13.5 ε sweep (`within_block_ensemble_v6_sector_full_eps_report.md`),
best configuration = K=8 ε=1.0 invvol ensemble on the default filter
(|z|≥2.0, turn≤0.60, no solo-Sharpe floor).

- **Members** (row-z of stage-1 z with polarity, equal-weight):
  `var5_60` (raw), `ma_disp` (raw), `alpha_142` (raw), `alpha_187` (raw),
  `yj15_bias_mom_60_20` (rev), `h_mom_decay_12_48` (raw), `kurt_40` (rev),
  `ret_skew_20` (raw).
- **Frozen settings**: q=0.20, **ε=1.00** (much stickier than broad_cn's
  ε=0.20 — the higher hysteresis is what saved the book from cost
  drag), invvol sizing, replace rule, cost 10 bp/side.
- **IS result**: Sharpe **+0.447 / CAGR +6.76% / DD −16.88% / turn 0.381**.
- **Vs null**: photo-finish miss (eqw null Sharpe +0.466, invvol +0.470;
  ΔSharpe −0.023, ΔCAGR −1.01 pp). User accepted 2026-07-22 —
  within-noise miss on IS is acceptable given the broader project
  need for a demonstrable second layer; the alternative (β-bucket
  demotion) buys nothing over just holding sector_cn eqw.
- **OOS**: SEALED. Same discipline as broad_cn — opens with the
  Phase 12 shot.

Note the asymmetry: broad_cn's α layer earns +0.45 Sharpe over null
(strong pass); sector_cn's α layer sits at −0.02 (nominal fail).
Combined into a Phase 12 book at their respective risk shares, the
broad_cn contribution carries most of the α-layer value.

**cross_border_hk α layer — DEFERRED to β-bucket 2026-07-22.**
Full 2021+ pipeline (`within_block_ensemble_v6_hk_2021_report.md`):
2021-2023 nulls collapse to Sharpe −0.540 / CAGR −15.52% (HK-tech
bear market); every K × ε × sizing ensemble loses even more.
Best "pass" (K=9 ε=0.30 eqw Sharpe −0.529, ΔSh +0.011 vs null) is
noise-level and not tradable. In Phase 12 cbHK gets treated as a
β sub-bucket inside the equity 55 % risk share, held block-eqw
under the trend-gate overlay. Revisit after 2024+ OOS opens and
includes a non-crashing regime — the IC statistic (|z| up to 3.57
on 89 bars) suggests a real signal, but it needs a base-return
window where "picking better names" translates to positive PnL.

**Block merges (per user 2026-07-22).**
`smallcap_cn` is folded into `broad_cn` for all downstream work.
Cross-section too thin to screen separately (mean N_b = 1.5); the
50-odd smallcap ETFs get treated as broad_cn members going forward.
broad_cn does **not** need re-screening — the 13.2 / 13.2b factor
lists remain the working set (the marginal addition of 1–2
smallcap codes per bar is small enough to accept without a rerun).
Encoded as `BLOCK_MERGES = {"smallcap_cn": "broad_cn"}` at script
level in new work (13.3 onward); the existing 13.2 / 13.2b outputs
are frozen on the pre-merge tag.

**Non-goals for Phase 12.**
- No within-block α combination — that's Phase 13's problem.
- No cash-management / financing-cost model. Cash is a zero-return,
  zero-cost bucket for the trend gate.
- No dynamic re-solve of the policy budget from realized Sharpes;
  that's a separate research question that only opens if the fixed
  policy proves competitive.

**Gate to open Phase 12.**
Phase 13 has to demonstrate a within-block signal that stands up on
its own — otherwise the two-layer architecture buys nothing over
"weight the blocks and hold." If Phase 13 returns null, Phase 12
becomes a portfolio-construction-only variant of the current defensive
finalist (no α layer) and the priority drops.

---

## Phase 13 — within-block factor screening  (OPEN — active branch)

**Purpose.** Decide *only* whether within-block IC exists. The rest of
the project's shape depends on this answer:

- If yes: Phase 12 (block budget) × Phase 13 (per-block α) becomes the
  v7 architecture.
- If no: drop the α layer entirely and ship a T2-style block-β book
  (long_q05 already IS that up to noise).

IS-only throughout (`bars ≤ C.IN_SAMPLE_END`; feedback-oos-discipline).

- [ ] **13.1** N_{t,b} census — `scripts/block_xs_census_v6.py`.
  Time-series of member count per (bar, block) from
  `data/universe_v6/membership.parquet` + `catalogue_tagged.csv`. IS
  summary per block (median / mean / min / max / p10 / p90). Flag any
  block whose mean N_b falls below `MIN_VALID_ROW = 5` — those blocks
  can still be screened qualitatively, but the z-stat there is not a
  meaningful ranker. Report: `reports/block_xs_census_v6.md`.

  *Caveat (per user).* "Cross-section too narrow to test a z-stat" ≠
  "no signal" — narrow blocks (broad_cn, cross-border, bond blocks)
  stay in the screen, they just get flagged for interpretation, not
  dropped.

- [ ] **13.2** Per-block IC screen — `scripts/within_block_ic_v6.py`.
  Scope (user, 2026-07-22): every factor in `common_factors_v6`
  across all six REGISTRY families (daily 81, external 10, hourly 41,
  price_volume 322, sentiment 9, technical 9 = **472 total** intersected
  over the 344 admitted-ever codes). Broader than `pv_sweep_xs_v6`'s
  price_volume-only screen — the point is to give any family a fair
  shot at being within-block-real even if it wasn't pool-level real.
  For every (factor × block): per-bar Spearman IC restricted to that
  block's admitted members, ragged-N zstat across bars (Phase 5.2
  convention). Both polarities kept. Outputs:
  - `data/within_block_ic_v6.csv` — long form (factor, block, zstat,
    mean_ic_w, mean_N, n_bars, pct_pos, polarity).
  - `data/within_block_ic_v6_top.csv` — per-block top-K by |zstat|,
    survivors of `|zstat| ≥ 2 AND n_bars ≥ MIN_COVERAGE`.
  - `reports/within_block_ic_v6_report.md`.

  Screen is per-block: a factor that clears the gate in `sector_cn`
  but nowhere else is a `sector_cn`-only α candidate, not a global
  survivor.

- [ ] **13.2b** Within-block ρ-dedup — `scripts/within_block_dedup_v6.py`.
  Added 2026-07-22 after 13.2 returned 127 broad_cn + 94 sector_cn
  survivors, many of which are known near-duplicates (macd_12_26 =
  macd_signal_12_26 by construction; alpha_179 ↔ alpha_180 nearly
  identical zstats). Purpose: reduce the survivor list to
  ~independent factors before running 13.3's holdings popularity on
  100+ redundant candidates. Method (parallel to `pv_sweep_xs_v6`'s
  stage-2 dedup at the within-block scope):
  - For each surviving block (broad_cn, sector_cn), restrict
    stage-1-z panels to that block's members and stack (T × N_b).
  - Compute pairwise Pearson |ρ| across factor panels.
  - Greedy dedup ordered by |zstat| desc; drop any factor whose |ρ|
    with an already-kept factor exceeds 0.5 (same threshold as
    pv_sweep). Both polarities: |ρ| is sign-agnostic, so
    anti-correlated pairs get caught automatically.
  Outputs:
  - `data/within_block_dedup_v6/{block}/kept.csv` — surviving
    factors + zstat + polarity, ordered by |zstat|.
  - `data/within_block_dedup_v6/{block}/drop_map.csv` — dropped
    factor → representative kept factor + |ρ|.
  - `reports/within_block_dedup_v6_report.md`.

- [ ] **13.3** Within-block holdings popularity for the 13.2b kept
  set — `scripts/within_block_popularity_v6.py`. Applies
  `BLOCK_MERGES = {"smallcap_cn": "broad_cn"}` at load. Working set:
  24 kept broad_cn factors + 27 kept sector_cn factors = 51 total.
  Per (factor, block):
  - Apply polarity + membership mask + block filter + smallcap merge.
  - At each bar, pick top-K = ⌈q · N_b(t)⌉ with q = 0.20
    (matches production long_q20 finalist).
  - Track per-name presence share (fraction of eligible bars picked).
  - Compute:
    - **effective_N** = 1 / Σ p_i² across block members.
    - **Jaccard vs 1/σ null** per bar, then averaged. 1/σ null =
      pick top-K by lowest σ_causal (no factor input). If mean Jaccard
      > 0.7, the factor is essentially an inv-vol dressing.
    - **Turnover** = mean per-bar Σ|1_picked_t XOR 1_picked_{t−1}| / (2K).
  Verdict flags:
  - `INV_VOL_LIKE` — Jaccard vs 1/σ > 0.7 AND eff_N within 20% of
    the 1/σ null's eff_N. Factor is not adding rotation on top of σ.
  - `ROTATIONAL` — Jaccard < 0.5 AND turnover > 0.15. Factor is
    picking a moving set of names, not a static core.
  Rationale (user, 2026-07-22): "mini-bond problem inside sector_cn"
  — the risk-adjusted label rewards low-σ names in the tails, so
  var5_60 / cvar5_60 / kurt-style factors naturally overweight
  bank / utility ETFs. If popularity confirms most 13.2b sector_cn
  survivors are inv-vol-dressed, open 13.2c.
  Outputs:
  - `data/within_block_popularity_v6/{block}/{factor}.csv` — per
    name-level popularity.
  - `data/within_block_popularity_v6/{block}/summary.csv` — one
    row per factor with the metrics above.
  - `reports/within_block_popularity_v6_report.md`.

- [ ] **13.2c** *(conditional on 13.3)* Raw-label re-screen —
  `scripts/within_block_raw_label_ic_v6.py`. Opens only if 13.3 shows
  most 13.2b survivors are `INV_VOL_LIKE`. Swap the current label
  (`ranked_risk_adj_label` = block-neutral rank of fwd/σ) for a
  block-internal rank of raw `fwd_1w` — no vol adjustment. Re-run the
  13.2 pipeline on the same 472 factors, compare the two survivor
  lists side by side. Pass rule: at least one 13.3-verified rotational
  factor should survive under both labels; a survivor that only
  clears under the vol-adjusted label is likely fitting σ, not signal.
  Report: `reports/within_block_raw_label_ic_v6.md`.

- [ ] **13.4** Within-block isolated book — one book per
  (factor, block) that made it through 13.2 + 13.3.
  `scripts/within_block_book_v6.py`. Setup:
  - Universe = block members only (membership-masked as usual).
  - Baseline (zero-signal null): eqw hold of the whole block.
  - Treatment: top-q of factor × sizing ∈ {inv_vol, eqw}, same q as
    Phase 9.2 finalist (or scanned locally if the block is too narrow).
  - Cost 10 bp/side, hysteresis same as production.
  - Compare Sharpe / CAGR / DD IS to the eqw null. Pass rule:
    strictly better on Sharpe with turnover-adjusted CAGR ≥ 0 vs the
    null.

  No block-level budget applied — this is the isolated
  demonstration that within-block α translates to PnL after cost.
  Report: `reports/within_block_book_v6.md`.

**Gate.** At least one (factor, block) pair passes 13.4 vs the block's
eqw null. If nothing passes, close Phase 13, drop the α layer for
v7, and open Phase 12 in "budget-only" mode.

---

## Open decisions (to resolve as we hit them)

### D1 — block tagging workflow for 1703 candidates *(open, deferred)*

After Phase 2's catalogue pull, `catalogue.csv` has 1703 rows with `block =
'UNTAGGED'`. The MEMBERSHIP rules do not use `block` (validation was loosened
to accept `'UNTAGGED'` for exactly this reason), but Phase 8/9 diagnostics
require it. Options identified:

- **A. Tag after MEMBERSHIP** — run Phase 3 first, then tag only the ~150–300
  admitted-ever codes. Cleanest scope, wastes no manual effort on codes that
  never enter the pool. Phase 8/9 gate on full tagging of the admitted set.
- **B. Tag upfront** — user edits `catalogue.csv` for all 1703 codes before
  Phase 3 runs. Slow but keeps Phase 3 linear.
- **C. Rule-based auto-tag** — write a small script that maps
  `underlying_name` substrings (e.g., `沪深300 → broad_cn`, `黄金 → metals`,
  `纳指 → cross_border_dm`) then user audits the output.

Decision pending. Not blocking on Phases 1, 2 (loader), 5 (ragged panels), 6
(labels), 7 (PV sweep). Blocking on Phase 8 (block-neutral IC diagnostics).

---

## Cross-cutting reminders

- **No in-place edits to v4pool.** Every file under `v6/scripts/` is a clone
  or fresh write.
- **OOS discipline (see [[oos-discipline]]).** OOS window (2024-01-01+) is
  sealed. All q/gate/hyperparameter selection happens inside IS
  walk-forward. OOS is scored one-shot per variant.
- **Absolute → quantile.** Anywhere the v4pool code used `K = 5` or
  `min_valid = 5` or `k=5` — audit every call site during ports and
  re-express as a quantile of `N_valid_t`. This is the second-most
  common bug source after look-ahead in the membership rules.
- **The panel is ragged.** Any pooled statistic that doesn't weight by
  `N_t - 1` (Phase 4.2) is wrong at the tail-early-years boundary where
  N(t) is small.
