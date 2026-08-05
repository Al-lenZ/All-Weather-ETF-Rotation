# XS-IC pipeline — v6, universe expansion

Status: **design, pre-implementation.** Companion to `DESIGN.md` (v1) and
`DESIGN_v2_features.md`; inherits every choice from those docs except where
explicitly noted in §10.

Version lineage note: **v5 was a failed experiment on a reduced 5-ETF pool**
and is retired; nothing in it carries forward. v6 branches from the v2/v4pool
state of the pipeline. The universe module introduced here is `universe_v6`
(v5 never shipped a universe module of its own).

## 0. Why we're expanding

Post-mortem of the v1/v2 sweeps, restated as a *power* problem rather than a
*factor* problem:

- Screening 322 PV factors at |t| ≥ 2.0 passed 13. Expected false positives
  under an independent null at that bar: ~16. The IS screen never
  distinguished the library from noise.
- Median per-bar `std_ic` across the sweep: **0.313**. The pure-noise floor
  for a Spearman IC on n = 15 names is 1/√14 ≈ **0.267**. Per-bar ICs on the
  v4pool are barely wider than random rankings.
- Consequently the OOS "collapse" (EW-6: IS t +5.21 → OOS t +1.01; ridge:
  → +0.71) is better read as regression to the truth than as regime break.
- The v2 feature families (external-projection, ETF-native) did not clear the
  bar either — same pool, same noise floor, same verdict.

Two mechanisms make breadth the highest-leverage change:

1. **Statistical.** Per-bar IC null std scales as 1/√(N−1): 0.267 at N=15,
   ~0.100 at N=100. Holding true IC fixed, sweep t-stats roughly triple over
   the same bar count, and realized IR improves via the fundamental law
   (IR ≈ IC·√breadth).
2. **Economic.** The PV library encodes within-market relative-value logic
   built for stock cross-sections. On 15 ETFs spanning ~5 asset-class blocks,
   ranking is asset-class timing — outside the library's domain. A 100+ pool
   creates within-block peers (sector/theme equity especially), which is the
   library's native habitat.

**Explicit non-goal:** no new factor construction in v6. Same libraries, same
screening pipeline. v6 swaps the cross-section, not the fuel — the mirror
image of v2's principle 6.

## 1. Design principles

v1 §1 five principles unchanged; v2 additions 6–7 unchanged. New in v6:

8. **Rules, not quotas.** Universe membership at every historical bar is the
   output of written admission rules applied point-in-time. We never
   reverse-engineer thresholds to hit a target N at a target date. Target
   sizes (§2.5) are calibration sanity checks only.
9. **The panel is ragged and every consumer must know it.** N_t grows through
   the sample. Any statistic that pools across bars must account for the
   per-bar noise floor 1/√(N_t−1) (§5). Any book parameter expressed as an
   absolute count must be re-expressed as a quantile (§7).

## 2. Universe construction — `universe_v6`

### 2.1 Candidate catalogue

Start from the full listing of exchange-traded ETFs on SSE + SZSE (equity
index, cross-border, bond, commodity, money-market **excluded**). For each
candidate, catalogue:

| field | source | use |
|---|---|---|
| `code` | exchange listing | id |
| `underlying_index` | fund prospectus / data vendor | dedup key (§2.2) |
| `list_date` | exchange | seasoning (§2.3) |
| `delist_date` (if any) | exchange | point-in-time exit |
| `block` | manual tag, extends `MARKET_TAG` taxonomy | diagnostics (§8) |
| daily close/volume/amount | vendor | returns, ADV |
| daily AUM (or shares_out × NAV) | vendor | liquidity filter |

Blocks (superset of the v4pool tags): `broad_cn`, `sector_cn`, `smallcap_cn`,
`cross_border_dm`, `cross_border_hk`, `bond_rates`, `bond_credit`,
`metals`, `commodity_other`. Tag list is fixed before any IC is computed.

### 2.2 Index dedup — one per index

Multiple trackers of the same `underlying_index` are clones; ranks among them
are meaningless and inflate nominal breadth. Rule:

- Group candidates by `underlying_index`.
- At each rebalance bar, the group's **representative** is the member with
  the highest trailing-60d ADV *at that bar*, among members passing §2.3–2.4.
- Representative switches are allowed but damped: a challenger must exceed
  the incumbent's trailing-60d ADV by ≥ 25% to take over (anti-churn).
- Near-clone indices (e.g. CSI 300 vs CSI 300 Growth style slices) are NOT
  merged in v6 — dedup is exact-index only. If the block-neutral diagnostics
  (§8) later show clone-like behavior, revisit in v7.

### 2.3 Seasoning

A name is admissible from `list_date + 26 weekly bars`. Rationale: aligns
with `Z_MIN_PERIODS = 26` and `VOL_WINDOW = 26`, so on the first admissible
bar the name already has a defined stage-1 z and causal σ; and it clears the
post-launch ramp (creation-driven flows, thin books) that contaminates early
prints.

### 2.4 Liquidity filter — hybrid floor + percentile, with hysteresis

Two-part test on trailing-60d median daily amount (RMB):

- **Absolute floor (tradability):** enter ≥ ¥50m, exit < ¥25m.
- **Relative cap (adaptivity):** among candidates passing the floor, keep the
  top 80% by trailing-60d ADV; a name exits the relative test only if it
  falls below the 90th-percentile-of-the-bottom, i.e. exit threshold is the
  85th percentile boundary. (Entry stricter than exit on both tests.)

The absolute floor guards against the percentile rule admitting untradeable
names in the small 2019 market; the percentile rule keeps the filter from
being anachronistically strict in early years. Floor values are **provisional
pending the data pull** (§9 step 2) — set them after seeing the 2019 ADV
distribution, then freeze. AUM ≥ ¥200m as a secondary floor with the same
2:1 entry/exit hysteresis.

**§2.4 addendum — floor freeze (2026-07-17, Phase 3.4 review).** Initial
provisional floors (ADV ¥50m/25m; AUM ¥200m/100m; pctl 20/15%) produced
N(2019-12) = 18 vs the §2.5 target of 40–60. Diagnostic: among 185 seasoned
candidates at 2019-12-27, only 28 cleared the ¥50m ADV floor, and index
dedup collapsed those 28 to 18 unique underlying_index groups. AUM was
never the bind (27 of the 28 ADV-passers also cleared ¥200m AUM). The
percentile cutoffs are non-binding at that pool size — the small-pool
bypass (n_pool < 5) doesn't fire but the 20-percentile cut on 28 names
barely trims anyone. Recalibration (one-shot, this doc is the record):

- `ADV_FLOOR_ENTER`: ¥50m → **¥20m**
- `ADV_FLOOR_EXIT`:  ¥25m → **¥10m** (2:1 hysteresis preserved)
- AUM floors and percentile cutoffs unchanged.

Resulting N(t) at the sanity dates: N(2019-12) = 27, N(2021-12) = 89,
N(2023-12) = 152, N(2024-12) = 185. IS N first crosses 40 at 2020-05-15
(vs 2020-09-25 under the original floors), buying ~5 months of IS
history. The 2019 target is still not fully met — the CN ETF market at
that date genuinely had few tradable names outside the top handful of
indices — but N(2019-12) = 27 is a workable cross-section, and the
alternative (further loosening to hit 40) both admits marginal names in
recent years (N(2024) 202+) and dilutes the tradability meaning of the
floor. This is the frozen floor; no further tuning below Phase 3.

Membership is evaluated on the W-FRI grid; changes take effect at the next
bar (no intra-bar entry/exit).

### 2.5 Expected N(t) — calibration check only

Sanity targets, not constraints: N(2019-12) ≈ 40–60, N(2021-12) ≈ 80–100,
N(2024+) ≈ 100–150. If the rules produce 38 at 2019, we take 38. If they
produce 15, the floors are miscalibrated — recalibrate **once**, before any
IC is computed on the new pool, and record the change in this doc.

### 2.6 Module interface

`universe_v6.py` exports:

```
MEMBERSHIP : pd.DataFrame  # W-FRI × code, bool — point-in-time admissibility
CODES      : list[str]     # union of all names ever admitted
BLOCK_TAG  : dict[str,str] # code → block  (extends MARKET_TAG taxonomy)
INDEX_OF   : dict[str,str] # code → underlying_index
NAME_EN    : dict[str,str]
```

`_common.load_universe()` gains a `version="v6"` parameter returning
`(CODES, BLOCK_TAG, MEMBERSHIP)`; the v4 path stays intact so v1/v2
artifacts remain reproducible.

## 3. Label — return to risk-adjusted, and the book follows

v2 §2 chose the raw-return label to match the α-prop raw-return book and
preserve the static OOS +1.617 anchor. On the v6 pool that anchor is dead
regardless (§7), so we resolve the v1 mismatch in the opposite, cleaner
direction:

- **Label:** ỹ = per-bar CS Gaussian rank of `fwd_1w / σ_causal`
  (i.e. v1's `ranked_risk_adj_label`, unchanged code).
- **Book:** model leg weights are vol-scaled (positions ∝ 1/σ within the
  selected set), so the model is trained and scored on the same quantity.

Label and book geometry move as one decision. The raw-label machinery
(`ranked_raw_label`) is retained for the v2 diff-checks only.

## 4. Data loading

New loader `loader_universe_v6.py` (pattern: `loader_etf_native.py`):

1. Pull candidate catalogue (§2.1) → `data/universe_v6/catalogue.csv`.
2. Pull daily OHLCV + amount for **all** catalogue names from
   max(list_date, 2018-06-01) — the 18-month pre-2019 runway covers the
   26-bar seasoning + z warm-up so the 2019 cross-section is fully formed.
   → `data/universe_v6/px_daily.parquet` (long format: date, code, o/h/l/c,
   volume, amount).
3. Pull daily AUM / shares outstanding → `data/universe_v6/aum_daily.parquet`.
4. Build `MEMBERSHIP` from §2.2–2.4 → `data/universe_v6/membership.parquet`
   plus a human-readable audit `membership_changes.csv` (bar, code, event ∈
   {enter, exit_floor, exit_pctl, repr_switch}, trigger value).
5. Diagnostics notebook-style script `universe_v6_report.py`: N(t) curve,
   block composition through time, churn rate per year, ADV distribution by
   year. **This report is reviewed and the rules frozen before any IC runs.**

Premium/IOPV and creation/redemption pulls for the expanded pool are
**deferred** — the v2 native family didn't clear the bar at N=15 and re-testing
it is a post-v6-core task (§9 step 8).

## 5. Ragged-panel statistics — changes to `_common.py`

The single most important code change in v6.

- `per_bar_spearman` — unchanged math, but consumers must pass
  membership-masked panels (non-members NaN at that bar).
- **`ic_summary` gains a weighted mode.** With N_t varying, the per-bar IC
  under the null has std 1/√(N_t−1); pooling raw ICs into a plain mean/t
  overweights thin early bars. New aggregation:

  ```
  z_t   = ic_t · sqrt(N_t − 1)          # ≈ N(0,1) under the null
  Z     = mean(z_t) · sqrt(T)           # panel z-score  (primary sort key)
  ic_w  = Σ w_t ic_t / Σ w_t,  w_t = N_t − 1   # effective mean IC (report)
  ```

  Sweep outputs report both the legacy unweighted columns (continuity) and
  `zstat`, `mean_ic_w`, `n_bars`, `mean_N`. Screening bar for v6: |zstat| ≥ 2
  replaces |tstat| ≥ 2.
- `precision_at_k` → `precision_at_q` (§7): k_t = ceil(q·N_valid_t),
  `min_valid` scaled accordingly.
- `cs_gaussian_rank` / stage-1 z: unchanged — both are already NaN-tolerant
  and per-bar, so ragged membership is free.

## 6. Screening reruns — the confirmation experiment

Order matters: the first science run on the v6 pool is a **confirmation
test**, not a fresh mine.

1. Rerun `pv_sweep_xs.py` (parameterized on `universe="v6"`, label §3) over
   the full 322-factor library, IS end unchanged (2023-12-31).
2. **Pre-registered check:** the 13 v1 IS survivors (`wq_023, wq_046,
   alpha_071, wq_081, wq_048, alpha_028, alpha_104, alpha_036, wq_061,
   wq_068, wq_012, wq_008, wq_059`) are flagged before the run. If they are
   real, they should pass *more* decisively at N≈50–100. If they don't
   separate from the pack, that's a clean kill of the v1 shortlist and the
   v6 sweep ranking supersedes it wholesale.
3. Stage-2 dedup (|ρ| ≤ 0.5) and `stability_halfsplit.py` unchanged in
   logic, rerun on v6 panels.
4. External-projection and native families: **deferred** to post-core (§9).

## 7. Book — quantile K, vol-scaled weights, new static baseline

- **Static baseline is rebuilt** on the v6 pool (same construction logic as
  the v4pool static leg, membership-aware). The +1.617 OOS anchor is retired;
  the v6 static number becomes the new reference. Recorded once, before any
  model-leg tuning.
- **Selection is quantile-based:** K_t = ceil(q·N_t). Coarse grid
  q ∈ {0.10, 0.20, 0.30}, evaluated on IS only, one value chosen by IS
  Sharpe of the model leg (ties → smaller turnover), then frozen for OOS.
  OOS is scored once, on the chosen q.
- **Weights within the selected set:** vol-scaled (∝ 1/σ_causal, renormed),
  matching the §3 label. α-prop raw weighting retired with the raw label.
- Blend-vs-static comparison logic (`book_xs*.py`) carries over with the new
  static reference.
- **Long-short, research-only:** add the dollar-neutral top-q minus bottom-q
  spread (vol-scaled legs) to the evaluation suite — cleanest isolation of
  the XS signal from the market leg. The *tradable* book remains long-only in
  v6; CN ETF borrow outside the largest broad-index products is thin to
  nonexistent, and a futures-hedged (IF/IC/IM) variant is a v7 question that
  only opens if the LS spread clears the screening bar OOS.

## 8. New diagnostics

- **Block-neutral IC.** For each surviving factor and the ensemble: recompute
  per-bar IC after demeaning ranks within `BLOCK_TAG` blocks. Report raw vs
  block-neutral side by side. This answers *where* the IC lives — picking
  blocks (sector rotation) vs picking within blocks (relative value). On the
  v4pool there was no within-block cross-section to measure; creating one is
  the point of v6, so measure it directly.
- `book_diagnostics.py` block decomposition carries over with the extended
  tag set; picks table gains `block` share-through-time.
- Churn/turnover attribution: how much book turnover is caused by membership
  changes vs signal changes (should be small if §2.4 hysteresis works).

## 9. Implementation sequence

Deliberately front-loaded with script editing and data loading; no science
runs until step 6.

| step | task | artifact | gate |
|---|---|---|---|
| 1 | `universe_v6.py` skeleton: catalogue schema, rule constants, MEMBERSHIP builder (logic only, no data) | module + unit tests on synthetic panel | rules in this doc match code |
| 2 | Data pull: catalogue, px_daily, aum_daily for all candidates | `data/universe_v6/*.parquet` | coverage report: % names with gap-free ADV history |
| 3 | Build MEMBERSHIP + audit trail; run `universe_v6_report.py` | membership.parquet, N(t)/churn/block report | **human review; freeze rules & floors** |
| 4 | `_common.py` edits: ragged-IC aggregation (§5), `precision_at_q`, `load_universe(version=)` | patched module + regression test that v4 path reproduces v1 sweep numbers bit-for-bit | v1 reproduction passes |
| 5 | Label wiring: §3 label on v6 panels; membership-masked fwd_1w/σ builders | label parquet + row-count sanity vs MEMBERSHIP | NaN pattern == membership pattern |
| 6 | PV sweep rerun (§6) incl. pre-registered 13-survivor check | `pv_sweep_xs_v6.csv` | — |
| 7 | Dedup + half-split + EW ensemble + ridge on v6 survivors | v6 counterparts of existing CSVs | ≥1 factor at \|z\| ≥ 2 surviving stability, else stop and write post-mortem |
| 8 | Static baseline rebuild → q-grid → model leg → blend; LS spread; block-neutral diagnostics | `book_*_v6.csv`, report | — |
| 9 | (post-core, optional) re-test external-projection & native families at v6 breadth | — | opens only if step 7 gate passed |

Step 7's gate is the honest version of the v1 experience: if a ~10× larger
effective cross-section still can't separate the library from noise at
|z| ≥ 2 with half-split stability, the conclusion is that CN-ETF weekly PV
alpha at this horizon is not there, and v7 goes hunting for different signal
families rather than different universes.

## 10. Deltas vs v1/v2 docs (summary)

| item | v1/v2 | v6 |
|---|---|---|
| universe | `universe_v4`, 15 fixed | `universe_v6`, rule-based ragged N(t) |
| label | v1: rank(fwd/σ); v2: rank(fwd) | rank(fwd/σ) — reverts to v1 |
| book weights | α-prop raw | vol-scaled within selection |
| selection | K = 5 fixed | quantile q ∈ {10, 20, 30}% grid, frozen on IS |
| screening stat | per-bar-IC t-stat | √(N_t−1)-weighted z-stat |
| precision@5 | fixed k | precision@q |
| static anchor | OOS +1.617 | rebuilt on v6 pool |
| LS | — | research-metric spread; tradable book stays long-only |
| new factors | v2: two new families | none (explicit non-goal) |
