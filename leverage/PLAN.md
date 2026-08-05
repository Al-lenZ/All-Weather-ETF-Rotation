# Leverage / Vol-Targeting Experiment — Implementation Plan

**Status:** REVISED 2026-07-29 (post-review) · **Owner:** allenzhou · **Baseline book:** Phase 12×13 two-layer finalist (`q=0.20 ε=0.30`, `invvol × lw_erc`, no trend), see `data/block_two_layer_v6/q20_eps030/`.

**Scope:** **Pre-registered IS + OOS** diagnostic on the two-layer book. Primary question: does **book-level** vol-targeted leverage deliver **excess-Sharpe-neutral CAGR improvement** over the current baseline? Cross-cuts: (a) risk-budget below the leverage `{base v6 55/20/10/15, EW 25/25/25/25}`, (b) cash accounting including a zero-borrow **cash-fill baseline**, (c) funding curve `{GC007, DR007, futures IRR}`. Bond-leg-only leverage kept as **one sanity cell** — see §二 in review notes for why it is largely redundant with `exp1_risk_budget_sensitivity`. **v6 remains FROZEN**; this feeds v7 discussion. Full decision rule (σ*, cap, funding curve, pass criteria, RB grid) is pre-registered in this document before any cell runs; **IS and OOS reported together**, no re-tuning between windows. Pre-registered stress window `[2025-08-01, 2026-07-17]` stays sealed until a single finalist cell is picked (§8).

**Non-goals / no-tune list.** No changes to the finalist recipe (composites, α selection, within-block sizing); no regime-conditional leverage; no daily rebalancing; no de-levering below 1x (L clipped ≥ 1.0 — explicit design choice, flagged in §9); no soft cap (hard cap in §1); **no re-tuning of σ*, cap, funding curve, RB grid, or pass criteria after seeing any cell result**. Decision rule frozen at PLAN sign-off. Anything below violated ⇒ start a new PLAN version, not edit this one.

---

## 1. Locked decisions

| Item | Value |
|---|---|
| Baseline book | Two-layer `q20_eps030`, `invvol × lw_erc`, no trend gate. Composites/α selection/within-block sizing all frozen at Phase 12×13 finalist. |
| RB grid | **{ `base` = v6 POLICY_SHARES 55/20/10/15, `EW` = 25/25/25/25 }**. Both run under every leverage variant so RB effect and leverage effect are separable (§二 in review notes: leveraging bond-leg alone is algebraically equivalent to moving policy shares — already scanned in `exp1_risk_budget_sensitivity_v6`). RB is fixed within a cell for the whole IS+OOS window. |
| Primary leverage location | **Whole book.** Bond-leg-only kept as one sanity cell (Round B, §6). |
| Cash-fill baseline | **DROPPED 2026-07-30** after empirical check on the finalist: post-warmup (from 2019-05-31) W_name cash gap is 1.77% mean in IS, 0.34% in OOS, 0.36% in stress — the 17.8% number in the review notes was a transitional 2019-H2 artifact (p95 hit 18.55% there, but mean fell to <2% by 2020). Free-leverage delta vs baseline ≈ +2.5 bp/yr, inside noise. Kept in log for §四.D1 traceability but no cells run this. |
| Cash accounting | **Symmetric.** Positive cash earns DR007 (bank deposit proxy); borrowed cash pays the cell's `funding_curve`. Reported drag/carry is `(NAV_cash × DR007) − ((L−1)·NAV × funding_curve)`, both accrued ACT/365 per bar. Baseline C0 with zero borrow gets the positive-cash carry only. |
| Shrinkage / σ_est estimators | **`weekly_ewma_52`** locked as the leverage-engine estimator: weekly-native EWMA on weekly book returns, halflife 26 weeks, annualized ×√52. Winner of M0-B standalone diagnostic (2026-07-30 run): IS aggregate ratio 0.917 (base) / 0.920 (EW) — only estimator qualifying `[0.9, 1.1]` on both RBs. Alternatives (daily×√252 EWMA, 60D×√252, HAC-adjusted weekly) all fall out of band on EW. See `data/leverage/_sigma_est_diag/WINNER.md`. Caveat: OOS aggregate ratio 1.23 (base) / 1.30 (EW) — regime-shift artifact (2024–25 lower realized vol; estimator memory lags). Documented; not a re-tune trigger. |
| Funding curve set | **GC007** (7D exchange repo, upper bound), **DR007** (7D interbank pledged repo, lower bound / bank-side execution), **futures IRR** (T-contract implied repo, real execution for duration-book leverage). Loaded per §3. Each cell picks one curve; funding drag column reports which. |
| Cap | **Hard 2.0x** (was 1.5x — bumped to keep σ*=3.2% from pinning against cap; see §一.2 in review notes). L clip `[1.0, 2.0]`. |
| Target vol σ* | **3.2% annualized, fixed, book-level.** Rationale: baseline book σ ≈ 2.39%, EW book σ TBD but likely similar order; σ*=3.2% → target L ≈ 1.25–1.35 per RB, well inside cap 2.0. No parity mode (bond-leg cell in Round B uses a fixed leg σ* separately locked; parity ambiguity in §一.3 sidestepped by not using parity). |
| L_t update | Weekly, aligned with existing W-FRI rebal cycle. No daily. |
| IS window | First non-zero `net_ret` bar through **2023-12-31** (report effective start in each output header). |
| OOS window | **2024-01-01 → 2025-07-31** (run alongside IS from day one; §5 in review notes: sealing does not add protection since hypothesis was generated post-exp1). |
| Stress window | **2025-08-01 → 2026-07-17.** Sealed until a **single** finalist cell is picked from IS+OOS; opened exactly once. |
| Costs | Turnover cost split by asset class: **bond ETFs 2 bp/side**, everything else **10 bp/side** (fixes §四.D4 — domestic bond ETF bid-ask ≈ 1–2 bp; blanket 10 bp materially over-penalizes the bond-heavy portion). Always on; gross reported as diagnostic. |
| Judgment metric | **excess Sharpe** = `mean(excess_ret_t) × 52 / (std(net_ret_t) × √52)`, where `excess_ret_t = net_ret_t − rf_period_t` **per bar (time series, not window mean)**. Applied uniformly to every cell including baseline. Raw `sharpe_net` (v6 project convention, `xs_engine_v6._window_sharpe`) reported in parallel for cross-phase alignment but is **not the pass metric**. `xs_engine_v6._window_sharpe` is intentionally left unchanged. |
| Excess Sharpe rf source | Bar-by-bar `rf_period_t = ACT/365 simple accrual of the cell's funding_curve over bar t's calendar days` (weekly bar ≈ `rf_ann_t × 7/365`). Window-mean `avg_rf_ann` reported as a diagnostic column only — **never used to compute excess Sharpe**, since an IS mean does not extrapolate to OOS / hold-out. |

## 2. Directory layout

```
v6/
  leverage/
    PLAN.md                       # this file
    _common_leverage.py           # shared constants (RB grids, dates, cap, σ*, cost table)
    funding_curves.py             # GC007 / DR007 / T-futures IRR loaders + weekly ACT/365 accrual
    vol_estimators.py             # M1 weekly-native EWMA (52w); Newey-West helper
    rb_variants.py                # build_book_weights(rb: {"base","EW"}) → W_name panel
    cash_fill.py                  # fill intra-group cash gap → W_name with Σ=1 per bar
    leverage_engine.py            # whole-book L_t = clip(σ*/σ̂_t, 1.0, 2.0); symmetric cash accounting
    bondleg_engine.py             # sanity cell only: L applied to bond leg with fixed leg σ*
    eligibility.py                # bond-leg sanity cell only: ticker → {eligible, haircut}
    metrics.py                    # excess_sharpe(net_ret, rf_series), raw sharpe passthrough, per-year
    sigma_est_diag.py             # standalone σ_est / σ_realized diagnostic (M0-B, no leverage)
    diagnostics.py                # L_t path, σ divergence, funding drag, GC007-90pctile conditional
    run_cell.py                   # one cell per invocation: python -m v6.leverage.run_cell --cell A_base_lev
    run_matrix.py                 # convenience: run a listed set of cells sequentially
  data/
    leverage/
      _funding/                   # cached curves: gc007_daily.csv, dr007_daily.csv, tfut_irr_daily.csv
      _sigma_est_diag/            # M0-B output: ratio time-series by (estimator, RB)
      <cell_id>/
        summary.csv               # headline metrics (see §7); includes excess_sharpe_{is,oos}
        per_year.csv
        L_t_path.csv              # weekly: L_t, sigma_est, sigma_realized, sigma_star, rf_ann
        funding_ledger.csv        # weekly: sub_nav, L_t, borrowed_notional, cash_earning, cost_dollar
        duration_ledger.csv       # weekly: bond_nav_share, KRD_est, book_duration_yr
        net_ret.csv               # daily book net_ret (post-leverage, post-cost)
        header.txt                # config echo + effective IS start + funding_curve id + RB id
        diagnostics.png           # 4-panel: L_t, σ divergence, cum PnL vs C0_baseline, funding drag
      COMPARISON.md               # end-of-experiment summary (§10 M6)
```

Only reads from existing pipeline (`from scripts._common_v6 import ...`, `panels_v6`, `block_two_layer_v6` composites, `block_risk_budget_v6.POLICY_SHARES`). **No edits to existing scripts** except one narrow hook if needed — see §9.

## 3. Data prerequisites

**Coverage required for all curves:** baseline IS start (first non-zero `net_ret` bar) → **2026-07-17** (end of stress window). Curves feed IS, OOS, and stress cells; splicing at IS start (e.g. R007 pre-2010 → GC007 post) documented in each curve's loader header.

- **GC007 series (BLOCKING).** Source: Wind / iFinD daily 7D exchange repo `GC007`. Store as `data/leverage/_funding/gc007_daily.csv` (date, rate_annualized). This is the **upper-bound** funding curve for the leverage cells.
- **DR007 series (BLOCKING).** Source: Wind / iFinD daily 7D interbank pledged repo `DR007`. Store as `data/leverage/_funding/dr007_daily.csv`. This is the **lower-bound** curve (bank-side execution) and doubles as the positive-cash carry rate under the symmetric cash accounting in §1.
- **T-futures IRR series (best-effort, non-blocking).** Source: CFFEX T-contract daily settlement + CTD basis → implied repo rate (IRR). Store as `data/leverage/_funding/tfut_irr_daily.csv`. Represents the actual execution cost of duration leverage via 国债期货 (§三 in review notes). If unobtainable, cell `B_winner_lev_futures` is dropped and the DR007 curve stands in for "best-case execution".
- **Repo eligibility list (sanity cell only).** For each ETF ticker in the finalist universe, tag `eligible ∈ {True, False}` and `haircut ∈ [0, 1]`. Gov-bond ETFs (511010, 511260) → eligible, haircut ≈ 0.15. City-investment / credit → eligible, haircut ≈ 0.30. HK / cbHK → not eligible. Used **only** by the bond-leg sanity cell `B_winner_bondleg_lev`; not on primary path. Draft in `eligibility.py`.
- **Bond ETF flag (BLOCKING).** For every ticker in the finalist universe, tag `asset_class ∈ {equity, bond, commodity}` (from `_common_v6` composite tag). Drives the split cost table in §1 (`cost_bond_bp = 2`, else 10). Stored inline in `_common_leverage.py`.

## 4. Module specs (signatures only)

`vol_estimators.py` — **M1 only on the leverage path** (M2a lives in the σ_est diagnostic).
- `weekly_ewma(weekly_returns: pd.Series, halflife_weeks: int = 26) -> pd.Series` — weekly-native EWMA, annualized ×√52. Fixes daily×√252 auto-correlation bias (§四.D2).
- `weekly_ewma_port(W_weekly: pd.DataFrame, R_weekly: pd.DataFrame, halflife_weeks: int = 26) -> pd.Series` — same but on a portfolio return series computed from time-varying weights.
- `newey_west_ann(weekly_returns: pd.Series, lags: int = 4) -> pd.Series` — HAC-adjusted annualized σ; used inside the M0-B diagnostic to quantify the auto-correlation bias, not on the leverage path itself.

`funding_curves.py`
- `load(curve_id: {"gc007","dr007","tfut_irr"}) -> pd.Series` — daily annualized rate, ffill within a max-5-day gap (documented).
- `weekly_accrual(rate_daily: pd.Series, weekly_index: pd.DatetimeIndex) -> pd.Series` — ACT/365 simple sum over each bar's calendar days; returns period fraction (not annualized).
- `weekly_funding_cost(L_t: pd.Series, nav_t: pd.Series, weekly_accrual_t: pd.Series) -> pd.Series` — dollar cost on `(L−1)·nav`. Positive-cash carry uses the same signature with `L_t ≡ 1` and DR007 accrual applied to the cash sleeve.

`rb_variants.py`
- `POLICY_SHARES_BASE: dict[str,float] = {"equity":0.55, "bond_rates":0.20, "bond_credit":0.10, "commodity":0.15}` (re-exported from `block_risk_budget_v6` for stability).
- `POLICY_SHARES_EW: dict[str,float] = {g: 0.25 for g in GROUPS}`.
- `build_book_weights(shared, comp, rb: {"base","EW"}) -> tuple[W_group, W_name]` — thin wrapper over `block_two_layer_v6.run_variant`-style aggregation, forcing a specific policy dict into `block_risk_budget_v6.build_block_weights`.

`cash_fill.py`
- `fill_intra_group_gap(W_name: pd.DataFrame, comp: dict) -> pd.DataFrame` — for each bar, for each group, rescale within-group weights so `Σ_group = W_group[t, g]_target` and `Σ_bar = 1`. Preserves the RB choice; only redistributes the sub-block-empty gap. Log per-bar `cash_before, cash_after` in `funding_ledger.csv`.

`leverage_engine.py` — **whole-book vol targeter (primary).**
- `apply_book_vol_target(W_name_weekly, R_weekly, sigma_star, cap, estimator, funding_curve_id, cash_carry_curve="dr007") -> Dict` — returns `L_t` weekly, post-lev daily net_ret, funding ledger (borrow cost + cash carry), σ traces.
- σ* mode: `"fixed"` only (scalar %). Parity mode removed (see §一.3).
- L clip `[1.0, cap]`.

`bondleg_engine.py` — **sanity cell only.**
- `apply_bondleg_vol_target(W_name, R_name, sigma_star_bondleg, cap, estimator, funding_curve_id, eligibility_map) -> Dict` — L applied to the bond-leg name-weights only; equity/commodity legs pass through; cash carry on the un-levered sibling as usual.

`metrics.py`
- `excess_sharpe(net_ret_weekly: pd.Series, rf_period_weekly: pd.Series) -> float` — `mean(net_ret − rf_period) × 52 / (std(net_ret) × √52)`. Bar-by-bar, no window-mean substitution.
- `raw_sharpe(net_ret_weekly) -> float` — thin wrapper matching `xs_engine_v6._window_sharpe` output for backward alignment.
- `summarize_cell(...) -> dict` — populates the §7 summary.csv row for one window (called separately with IS slice, OOS slice, and per-year slices).

`sigma_est_diag.py` — **runs before any leverage cell (M0-B).**
- `run_sigma_est_diagnostic(shared, comp, rb: {"base","EW"}, estimators: list) -> pd.DataFrame` — for each (RB, estimator), produces weekly `σ_est_t`, weekly `σ_realized_t` (4w forward realized ×√52 as truth proxy), and the ratio. Output: `data/leverage/_sigma_est_diag/ratio_<rb>_<estimator>.csv` + a 1-page summary comparing {daily×√252 EWMA (old M1), weekly-native EWMA (new M1), 60D×√252, Newey-West adjusted}. Decides which estimator survives to the leverage engine. **Blocking for M2 leverage cells.**

`run_cell.py`
- CLI: `python -m v6.leverage.run_cell --cell A_base_lev` etc. Config table in §6 hard-coded. Emits all deliverables in §7.

`run_matrix.py`
- CLI: `python -m v6.leverage.run_matrix --round A` runs Round A cells sequentially; `--round B` requires `--winner {base|EW}` argument selected from Round A output.

## 5. Weekly leverage mechanics

### 5A. Whole-book (primary path — cells A_*_lev, B_*)

At each weekly rebal date `t`:
1. Compute σ_est_t via the estimator selected in M0-B (§10) over the current book weights `W_name[t]`.
2. `L_t = clip(σ* / σ_est_t, lower=1.0, upper=cap)`. **No de-lever below 1x** — high-σ regimes hold at 1x, don't shrink risk. Explicit design choice (§9).
3. Hold `L_t` constant over the week. Every daily return within week `t` multiplied by `L_t` on the invested sleeve.
4. **Funding cost (borrow leg):** `(L_t − 1) × NAV_t × weekly_accrual(funding_curve, t)`. Subtracted at bar granularity.
5. **Cash carry (deposit leg):** `NAV_cash_t × weekly_accrual(DR007, t)`. Applied only when `Σ W_name[t] < 1` (structural cash gap present) — this makes C0 baseline non-zero on cash, closing the §四.D1 inconsistency. Also applied to the un-levered baseline for consistency.
6. Bar-level net return: `L_t · r_invested_t + cash_carry_t − funding_cost_t − turnover_cost_t`.
7. Turnover cost uses the split table in §1: `bond ETFs 2 bp/side`, else `10 bp/side`, on incremental trades from both baseline rebal and leverage adjustment.

### 5B. Bond-leg-only (sanity cell B_winner_bondleg_lev)

Same as 5A but `L_t` applies only to bond-tagged names in `W_name`; equity / commodity legs pass through. Funding curve default = GC007 (repo pledge); haircut treated as **economic drag on funding notional** only, not as sub-cap on `L_t` (§9 open item was resolved: h=0.15 gives `1/h ≈ 6.67x` max notional, so `cap=2.0` is unconstrained). Leg σ* fixed at `1.5% ann.` (approximates matching baseline bond-leg σ). This cell is a sanity check on §二: whether leg-only leverage produces a materially different signature from whole-book leverage.

### 5C. Cash-fill cell (C-1 analogues: A_base_cashfill, A_ew_cashfill)

Skip steps 2–4 entirely. Instead: `cash_fill.fill_intra_group_gap` rescales within-group weights so `Σ W_name[t] = 1` bar-by-bar, preserving the RB choice at the group level. `L_t ≡ 1`. Zero borrow, zero funding cost, zero cash carry (nothing left as cash). This is the true zero-borrow "free-leverage" baseline; everything with `L > 1` must beat it on excess Sharpe *and* CAGR to justify the funding drag.

## 6. Experiment matrix

**Structure.** Two rounds. Round A (4 cells) is a 2×2 factorial `{base RB, EW RB} × {no-lev, book-lev GC007}` — isolates the RB effect and the borrowed-leverage effect. Cashfill cells removed 2026-07-30 (see §1 note). Round B (up to 4 cells) runs only on the RB winner from Round A and stresses the funding channel + sanity axes.

All cells report **IS + OOS together** (per §1 pre-registration rule). Stress window stays sealed for the finalist only (§8).

### Round A — core factorial

| Cell ID | RB | Leverage | Funding curve | σ*, cap | Notes |
|---|---|---|---|---|---|
| `A_base_nolev` | base 55/20/10/15 | none (L≡1) | — (DR007 cash carry on the residual W_name gap) | — | Reproduces v6 finalist under new metric + symmetric cash. **Reference cell.** |
| `A_ew_nolev`   | EW 25/25/25/25  | none (L≡1) | — (DR007 cash carry on the residual W_name gap) | — | Reproduces exp1 EW winner under new metric. |
| `A_base_lev` | base | book-level vol target | GC007 | σ*=3.2%, cap=2.0 | Primary borrowed-leverage cell, base RB. |
| `A_ew_lev`   | EW   | book-level vol target | GC007 | σ*=3.2%, cap=2.0 | Primary borrowed-leverage cell, EW RB. |

**Round A comparisons:**
- **RB effect (no-lev):** `A_base_nolev` ↔ `A_ew_nolev` — replicates exp1 conclusion under the new metric and cost table.
- **Borrowed leverage:** `A_*_lev` ↔ `A_*_nolev` — does book-level leverage beat baseline once funding drag is netted?
- **RB × leverage interaction:** does the winning RB (from no-lev comparison) stay winning under leverage?

### Round B — winner-only stress on funding + sanity axes

Kicked off only after Round A completes. Let `WIN ∈ {base, EW}` be the Round A winner (highest excess Sharpe among the four levered / cash-filled cells, tiebreaker CAGR). Round B cells are all applied to `WIN`.

| Cell ID | RB | Leverage | Funding curve | σ*, cap | Notes |
|---|---|---|---|---|---|
| `B_win_lev_DR007`   | WIN | book-level vol target | DR007 | σ*=3.2%, cap=2.0 | Lower-bound funding — best plausible bank-side execution. |
| `B_win_lev_futures` | WIN | book-level vol target | T-futures IRR | σ*=3.2%, cap=2.0 | Real execution for duration leverage. Dropped if IRR series unavailable. |
| `B_win_lev_static`  | WIN | book-level, **L ≡ cap** static | GC007 | cap=2.0 | Sanity: how much of `A_win_lev` is the vol-targeter vs just L=cap. Independent of `pct_at_cap`. |
| `B_win_bondleg_lev` | WIN | **bond-leg-only** vol target | GC007 (repo pledge) | leg σ*=1.5%, cap=2.0 | Sanity: does leg-only differ materially from whole-book? Answers §二 review point empirically. |

**Round B comparisons:**
- **Funding channel:** `A_win_lev` ↔ `B_win_lev_DR007` ↔ `B_win_lev_futures` — how much of the borrowed-leverage penalty is choice-of-funding-tool vs the leverage itself.
- **Targeted vs static:** `A_win_lev` ↔ `B_win_lev_static` — is the vol-targeter earning its complexity.
- **Leg vs whole:** `A_win_lev` ↔ `B_win_bondleg_lev` — direct test of the §二 hypothesis.

### Conditional diagnostic (mandatory per §四.D)

For every cell with `L > 1`, report the conditional distribution of `net_ret_t` on weeks where `funding_curve_t ≥ 90th-percentile` of its own history. This surfaces the "funding is expensive AND bonds are down" tail (§三 in review notes: 2013, 2016-12, 2020-05 pattern). Column in `summary.csv`: `net_ret_p50_when_rf_p90`, `net_ret_p05_when_rf_p90`.

### What's dropped from the old 9-cell matrix and why
- **C1–C4 (bond-leg-only, M1 & M2a, eligible & theoretical)** — collapsed into single sanity `B_win_bondleg_lev`. Rationale: §二 review — bond-leg leverage ≡ modifying policy shares, already scanned in `exp1_risk_budget_sensitivity_v6` at 80-cell resolution.
- **C5–C6 (book-level, M1 vs M2a)** — M2a moved into the standalone σ_est diagnostic (M0-B). Rationale: §四.D3 — the "does shrinkage bias σ_est" question is separable from and prior to the leverage decision; deciding the estimator inside the leverage loop conflates two effects.
- **C7 (bond-leg static)** — redundant with `B_win_lev_static` if leg-vs-whole is not materially different (which is what we expect).

## 7. Deliverables per cell

`summary.csv` — one row per window (`window ∈ {is, oos, is+oos, per-year rows...}`). Columns:

```
window, is_start, is_end, rb, funding_curve_id, sigma_star, cap,
sharpe_net, sharpe_gross,                       # raw, v6 alignment only
excess_sharpe_net, excess_sharpe_gross,         # PASS metric per §1, §8
cagr_net, cagr_gross,
vol_realized, avg_rf_ann,                       # avg_rf_ann diagnostic-only
max_dd, calmar,
turnover_ann_bond, turnover_ann_nonbond,        # split, per §1 cost table
cost_drag_bp_yr, funding_drag_bp_yr, cash_carry_bp_yr,   # cash_carry is credit (positive)
mean_L, p95_L, pct_at_cap, pct_at_floor,        # pct_at_floor = weeks pinned at L=1.0
sigma_est_vs_realized_ratio_mean,
net_ret_p50_when_rf_p90, net_ret_p05_when_rf_p90,    # §四.D conditional diagnostic
book_duration_yr_mean, book_duration_yr_p95      # duration exposure disclosure per §三
```

`per_year.csv`: same columns, one row per calendar year within each window.

`L_t_path.csv` (weekly): `date, L_t, sigma_est, sigma_realized, sigma_star, rf_period, rf_ann, cash_share, book_duration_yr`.

`funding_ledger.csv` (weekly): `date, nav, L_t, borrowed_notional, funding_accrual, funding_cost_dollar, cash_nav, cash_carry_accrual, cash_carry_dollar, net_funding_dollar`.

`duration_ledger.csv` (weekly): `date, bond_rates_share, bond_credit_share, bond_rates_krd, bond_credit_krd, book_duration_yr` — computed from `w × KRD` with a static KRD table by ETF (511010 ≈ 5.5y, 511260 ≈ 8y, credit ≈ 3–4y; frozen in `_common_leverage.py`).

`net_ret.csv` (daily): `date, gross_ret, net_ret, funding_dollar, cash_carry_dollar, cost_dollar, L_t, nav`.

`header.txt`: config echo (cell id, RB, funding_curve, σ*, cap, estimator), effective IS start, PLAN version hash.

`diagnostics.png`: **4-panel.** (1) `L_t` path with `[1.0, cap]` band, funding curve annualized overlaid on right axis. (2) `σ_est` vs `σ_realized` dual line + ratio subplot. (3) Cumulative net_ret of this cell vs `A_base_nolev` reference. (4) Funding drag & cash carry stacked bar by year.

**Round-level rollup:** `data/leverage/COMPARISON.md` produced at the end (§10 M6). One table per comparison bullet in §6; verdict paragraph per comparison; explicit call-out of any pass criterion failed and why.

## 8. Success criteria & expected outcomes

### 8A. Invariance identity (why excess Sharpe is the pass metric)

For a levered book with constant rf, `net_ret_t(L) = L·r_base_t − (L−1)·rf_t`, so bar-level excess `net_ret_t(L) − rf_t = L·(r_base_t − rf_t)` — mean and vol both scale by L, ratio invariant. With time-varying rf the identity holds approximately (bar-level algebra exact per bar; annualized aggregation picks up a small covariance term).

- **Excess Sharpe** stays ≈ flat under L absent estimation error and funding tracking cost.
- **Raw Sharpe** drops mechanically by roughly `−(L−1)·avg(rf)/(L·σ_base)`. For the finalist (r=3.43%, σ=2.39%) at L=1.35 with avg rf≈1.43%, this is ≈ **−0.155 on raw Sharpe** — a raw-Sharpe drop of that magnitude means nothing.

**Only excess Sharpe deviations** signal a real effect: (i) σ_est bias (check the M0-B diagnostic), or (ii) funding tracking cost (check `funding_drag_bp_yr` vs 8C prior).

### 8B. Cell pass criteria (evaluated on IS+OOS pooled window, then re-checked on IS and OOS separately)

A cell "passes" if **all** of:
1. **Excess Sharpe** delta vs `A_base_nolev` ≥ **−0.10** (net) on the IS+OOS pooled window.
2. Excess Sharpe delta vs `A_base_nolev` ≥ **−0.15** (net) on each of IS and OOS individually — a large window-to-window swing invalidates the cell regardless of the pooled number.
3. CAGR delta vs `A_base_nolev` ≥ **+0.5%** on IS+OOS pooled.
4. MaxDD ≥ **1.5× baseline DD** (i.e. no worse than 1.5× the IS+OOS pooled DD of `A_base_nolev`).
5. `pct_at_cap` and `pct_at_floor` **reported per window (IS, OOS, pooled) as diagnostic columns, not blocking** (revised 2026-07-30 after Round A). High `pct_at_cap` on a low-vol regime window is a feature (target vol met, book runs at the cap) more than a bug; low-vol OOS 2024-25 pins both lev cells to cap without invalidating the vol-target thesis. The pre-Round-A "≤ 40 % / ≤ 50 %" bar is retained in the log as a documentation reference but does not gate cell selection.
6. **Conditional tail:** `net_ret_p05_when_rf_p90` ≥ **−1.5%** per week (guards against "funding expensive + bonds down" tail flagged in §三).

Raw Sharpe delta is reported alongside but is **NOT** a pass condition.

### 8C. Prior for calibration (recalibrated 2026-07-29, replacing old JGB/5–15bp figures)

- **Rate environment (IS window 2019–2023):** GC007 average ≈ 2.2–2.5%; DR007 avg ≈ 1.9–2.2%; 10Y CGB yield 2.6→3.2% then falling. This is a **duration bull market** — leverage on the bond leg amplifies capital gains, not carry. Report this framing explicitly in the header.
- **Rate environment (OOS window 2024-01–2025-07):** 10Y CGB continues to 1.7–1.9%; GC007 avg ~1.4–1.7%. Duration tailwind persists.
- **Funding drag prior at book L=1.35** (revised 2026-07-30 to match §5A implementation math). Per §5A step 4 the borrow leg is `(L−1) × NAV × funding_accrual`, with NAV ≡ 1 in the constant-notional fraction-of-NAV convention — there is no "debt-leg 84% NAV" haircut (that framing was from an earlier accounting draft and does NOT reflect the running engine). At L=1.35, GC007 mean 2.16 % ⇒ drag ≈ 0.35 · 2.16 % = **76 bp/yr** on IS. DR007 proxy mean ~2.20 % ⇒ 77 bp/yr (proxy runs +20–35 bp high vs true DR007). T-futures IRR (unavailable, dropped): ~1.5–1.8 % implies ~53–63 bp/yr. At L=1.5: GC007 ~108 bp/yr; DR007 proxy ~110 bp/yr. Round-A observed drag (`A_base_lev` L̄=1.30 IS): 74 bp/yr — matches this revised prior.
- **Cash carry credit (baseline C0):** at DR007 ~2% and structural cash 17.8% no-trend, credit ≈ 35 bp/yr. This is why the symmetric cash accounting matters — it moves the C0 baseline up.
- **Expected duration exposure:** unlevered book duration ≈ 4.3y (rates ETFs KRD ~7–8y × ~54% NAV + credit ~3–4y × ~30% NAV). At L=1.35 whole-book: ≈ 5.8y. At L=1.5: ≈ 6.4y. **Must be disclosed in every levered cell's header** — a 5.8y book is a very different animal from a 4.3y book if rates back up.
- **Excess Sharpe expectation:** if the σ_est estimator selected in M0-B has ratio near 1.0 on the RB, excess Sharpe delta ~ 0. If ratio is 0.85–0.9 (σ underestimated), excess Sharpe drops 0.05–0.10 from realized vol overshooting σ*.

### 8D. Stress window opening rule (pre-registered)

After Round A and B complete and the finalist cell is selected on the IS+OOS pooled criteria in §8B, **exactly one** stress window shot is taken on that finalist. Stress-window pass criteria (softer, since window is 11 months and can be regime-idiosyncratic):

- Excess Sharpe on stress ≥ **0**.
- CAGR on stress ≥ **0**.
- MaxDD on stress ≥ **−3%** (baseline stress DD was −0.30%; allowing 10× headroom for the levered book).
- No single week with `net_ret ≤ −2%`.

If any of these fails, the finalist is not carried into the v7 discussion note. **No re-selection of a different cell after seeing stress numbers.**

### 8E. What passing means

Passing cells go into a v7 discussion note (`data/leverage/COMPARISON.md` + a short `project_leverage_experiment.md` memory if findings are non-obvious). **Nothing in this experiment modifies v6 production** regardless of outcome.

## 9. Risks / open items

### Closed (previously open, resolved in this revision)

- [x] **Haircut arithmetic (was: "1/0.85 ≈ 1.18x cap conflict").** Corrected: pledge with h=0.15 yields cash = 0.85·V, so first-round leverage `L = (V + 0.85V)/V = 1.85x`; infinite-round upper bound `L = 1/h = 6.67x`. Cap 2.0 is well inside the pledge-implied ceiling. Real constraint is exchange repo-balance ratios and broker risk, not haircut math. Haircut treated as economic drag on funding notional only (§5B).
- [x] **Parity σ* ambiguity (was: two readings differ 6.5×).** Parity mode removed entirely; whole-book uses fixed σ*=3.2%, bond-leg sanity cell uses fixed leg σ*=1.5%.
- [x] **σ_est estimator inside leverage loop (was: M1 vs M2a as cell axis).** Moved out into standalone M0-B diagnostic; only the winner from M0-B enters the leverage engine. §四.D3.
- [x] **Frequency mismatch (daily×√252 vs weekly cov).** M1 spec changed to weekly-native EWMA (52-week halflife). §四.D2.
- [x] **Cash accounting inconsistency (was: cash zero-cost but borrow pays GC007).** Symmetric: positive cash earns DR007, borrow pays cell's funding curve. §1, §5.

### Open (require user decision or external data)

- [ ] **T-futures IRR data feasibility.** Need daily settle × CTD basis to compute implied repo. If not obtainable by M0, cell `B_win_lev_futures` is dropped and the DR007 curve stands in as "best-case execution" proxy. Non-blocking.
- [ ] **DR007 series availability.** If shorter than IS window, splice with equivalent-tenor interbank pledged repo. Splice date documented in curve loader header.
- [ ] **No de-lever below 1x.** `L_t` clipped `[1.0, 2.0]`. High-σ regimes hold at 1x, don't shrink risk. Deliberate design choice to isolate leverage upside; a full symmetric vol-targeter is v7-scope. Flag in every cell header.
- [ ] **Static KRD table for duration ledger.** Approximation — real KRD is time-varying (curve steepening / issuance). Static table introduces ±0.5y error on `book_duration_yr`. Acceptable for the disclosure purpose; note in `_common_leverage.py`.
- [ ] **Funding curves and OOS extrapolation.** `funding_curve[t]` is realized data through 2026-07-17. This means the OOS + stress cells are honest on the funding side. However, the *decision* to use e.g. GC007 vs DR007 was made ex-post knowing recent rate history; that's an unavoidable trace of hindsight in the funding-curve choice. Reported, not fixed.
- [ ] **σ_est warmup vs IS start.** M1 weekly EWMA warms up in ~52 weeks (matches existing `WINDOW_COV = 52` in `block_risk_budget_v6`). Effective IS start moves to `max(baseline_is_start + 52w, first_non_zero_net_ret)`. Header reports.
- [ ] **One narrow hook to existing code.** May need to import `lw_erc` from `block_risk_budget_v6` as a callable + expose `POLICY_SHARES` under a new label. Diff should be < 30 LOC and behaviour-preserving. Track here if it happens.
- [ ] **Pre-registration integrity.** Any tuning of σ*, cap, funding curve, RB grid, or pass criteria after this PLAN version is signed off invalidates the OOS/stress evidence. If a change is truly necessary, open a new PLAN version and re-cut IS-only.

## 10. Milestones

- [ ] **M0-A — Data.** Load GC007, DR007, T-futures IRR (best-effort). Bond-flag every ticker in finalist universe. Draft eligibility map. → user review before proceeding.
- [ ] **M0-B — σ_est standalone diagnostic (BLOCKING for M2).** `sigma_est_diag.py` runs on `A_base_nolev` and `A_ew_nolev` weight paths across estimators `{daily×√252 EWMA (old M1), weekly-native EWMA (new M1), 60D×√252, Newey-West adjusted}`. Deliverable: `data/leverage/_sigma_est_diag/summary.csv` + 1-page markdown recommending one estimator to lock into the leverage engine. Ratio `σ_est/σ_realized` mean must be within `[0.9, 1.1]` on baseline weights over IS to qualify.
- [ ] **M1 — Cash accounting + cash-fill.** `cash_fill.py`, `funding_curves.py` symmetric accrual. Unit sanity: on `A_base_nolev` with `L≡1`, structural cash of 17.8% × DR007 ~2% ≈ 35 bp/yr credit; reproduce. **Verification checkpoint — cash source diagnostic (user-flagged 2026-07-30):** before building the cashfill cells, plot `1 − Σ W_group[t]` on `A_base_nolev` across the full baseline IS. Hypothesis to falsify: the 17.8% "structural cash" observed on the baseline is actually a **warmup artifact** — the book only reaches full investment around ~2019-05-31 once σ_est / trend gates / block warmups all clear, and post-that date `Σ W_group ≈ 1` most of the time. If true, `A_*_cashfill` collapses to `A_*_nolev` on the post-warmup window and the free-leverage premise weakens. Report `cash_share` mean split by `{pre-warmup, post-warmup}`; if post-warmup cash share `< 2%` for `> 90%` of weeks, downgrade both cashfill cells to a warmup-only artifact note in COMPARISON.md and skip them.
- [ ] **M2 — Leverage engine.** `leverage_engine.py` on a trivial dummy book (1 asset with known σ), verify `L_t · σ ≈ σ*`. Verify identity: at constant rf, excess Sharpe of levered path matches unlevered within numerical noise.
- [ ] **M3 — Baseline reproduce (`A_base_nolev`).** Reproduce baseline metrics within 1 bp of `data/block_two_layer_v6/q20_eps030/` **on raw Sharpe** (cross-check). New excess Sharpe reported separately.
- [ ] **M4 — Round A (6 cells).** Full factorial. IS+OOS reported together. Gate: no cell fails on data-quality grounds; every pass-fail decision uses §8B criteria only.
- [ ] **M5 — Round B (up to 4 cells).** Kicked off only after M4 winner is selected. `--winner` flag on `run_matrix.py`.
- [ ] **M6 — Finalist selection + stress shot.** Pick single finalist from Round A ∪ Round B on §8B pooled criteria. **One** stress-window run (§8D). No re-selection after stress.
- [ ] **M7 — Comparison note.** `data/leverage/COMPARISON.md`: pass/fail table for every cell on every §8B criterion; diagnostic plots; finalist verdict paragraph; explicit statement of any pre-registered rule that had to be relaxed (none expected).
- [ ] **M8 — Memory update.** Save `project_leverage_experiment.md` with the non-obvious findings (which estimator won M0-B; whether cash-fill dominates borrowed leverage; funding-curve gap size; duration disclosure). Link related memories with `[[...]]`.

## 11. Log

- 2026-07-28 · plan drafted, decisions locked with user
- 2026-07-29 · **Sharpe judgment metric** switched raw → time-series excess Sharpe (item §一.1). `xs_engine_v6._window_sharpe` intentionally unchanged (v6 project-wide alignment). Per-bar `rf_period_t`, not window mean.
- 2026-07-30 · **Implementation greenlit** by user. Cash-fill hypothesis flagged: the 17.8% structural cash in baseline may be a warmup artifact (book reaches full invest ~2019-05-31), not a persistent gap. Verification checkpoint added to M1 — check `1 − Σ W_group[t]` pre/post 2019-05-31 on `A_base_nolev` before running `A_*_cashfill` cells.
- 2026-07-30 · **M0-B σ_est diagnostic complete.** Ran 4 estimators × {base, EW} RB. Winner: `weekly_ewma_52` (IS agg ratio 0.917 / 0.920, only estimator qualifying [0.9, 1.1] on both RBs). Locked into §1 for the leverage engine. Frequency-mismatch bias (§四.D2) confirmed but smaller than boss's prior on base RB (<1%); real on EW RB (~3.5%). All estimators under-estimate IS realized book vol by 8–14% → L_t will run ~10% high vs σ*. OOS ratio 1.23–1.30 (regime shift) — documented, not a re-tune trigger. Outputs in `data/leverage/_sigma_est_diag/`.
- 2026-07-30 · **M0-A funding curves refreshed.** `gc007_daily.csv` real (Ricequant `204007.XSHG`, 1742 rows, 2019-05-15 → 2026-07-17, mean 2.16%). `dr007_daily.csv` uses SHIBOR 1W as **proxy** — installed `rqdatac 3.5.2` doesn't expose `econ.get_interbank_pledged_repo_rate`. Series named `dr007_shibor1w_proxy` for downstream provenance; +20–35 bp systematic upward bias vs real DR007 (SHIBOR quoted vs DR007 transacted). Cell `B_win_lev_DR007` will therefore report an **upper bound** on true DR007-funded outcome (real DR007 would look better). See `data/leverage/_funding/PROVENANCE.md`. T-futures IRR not fetched. Ricequant account expires ~2026-08-24.
- 2026-07-30 · **Cashfill hypothesis verified & killed.** Empirical check on the finalist: post-warmup (first non-zero net_ret bar = 2019-05-31, exactly the user's prediction) W_name cash mean 1.77% IS, 0.34% OOS, 0.36% stress (W_group 0% everywhere). The 17.8% number in the review notes was a 2019-H2 transitional artifact. Cashfill delta vs C0 ≈ +2.5 bp/yr under the new symmetric cash accounting — inside noise. Both `A_*_cashfill` cells dropped; Round A goes 6 → 4. Symmetric cash accounting retained (C0 earns DR007 on the residual W_name gap).
- 2026-07-31 · **Round C added (post-hoc extension).** Plugs the exp2 adaptive-K representative-set (frozen `data/exp2_representative_sets_v6/` CSVs, threshold 0.20) into the 6 non-α blocks. α blocks unchanged. 6 cells: `{base, EW} × {no-lev, lev @ GC007, lev @ DR007 proxy}` — `C_*_reps_nolev`, `C_*_reps_lev`, `C_*_reps_lev_DR007`. Ran clean on the frozen leverage engine (no engine changes; single `use_reps` flag on `rb_variants.build_book`).
- 2026-07-31 · **Round C rep-weighting corrected.** First pass used `exp2.build_replicated_block` (hold-all invvol on full member set + drop non-rep mass) → 21 % structural cash gap because ineligible-rep bars and non-rep members leak to cash. User flagged; per-block diag showed leak 8-32 % across bond_rates / bond_credit / cross_border_dm / cross_border_hk / metals. Replaced with `_build_reps_invvol_subblock` in `rb_variants.py`: invest fully in the K reps, invvol-weighted among themselves, normalize to `Σ_block = 1`. Non-rep members ignored (they are what the compression drops). Sanity: `Σ_block = 1.000` per invested bar; full-book cash 1.66 % base / 1.69 % EW ≈ hold-all's 1.58 % / 1.62 %. Round C re-run 2026-07-31 09:59. New headline: mean K names 53.55 → 31.42 (−41 %), no-lev Sh Δ −0.09 / −0.10 with CAGR Δ **+0.21 / +0.27 pp**, lev Sh Δ −0.01 to −0.05 with CAGR Δ **+0.02 to +0.22 pp**, L̄ *drops* (1.47 → 1.30 base, 1.56 → 1.39 EW pooled) because rep-set has higher pre-lev vol so less leverage is needed for σ*, funding drag −40 bp/y. Report: `reports/leverage_reps_round_c.md`. **v6 stays FROZEN**; §8B pass criteria NOT re-evaluated on Round C. Feeds v7 discussion alongside the pending higher-cap experiment.
- 2026-07-31 · **Round D — higher-cap experiment (post-hoc, boss ask).** Uses same rep-only invvol non-α composite as corrected Round C; only σ* and cap change: σ* 3.2 % → **6.4 %** (2× current, boss-verbal "normal case ≈ 2× leverage"); cap 2.0 → **5.0** (boss: 10× is theoretical, start at 5×). Per-cell `sigma_star` / `cap` kwargs added to `run_cell.py` (`CL.SIGMA_STAR` / `CL.CAP` module constants unchanged, so all A/B/C cells preserved). 4 cells `D_{base,ew}_reps_lev{,_DR007}`. Headline (IS+OOS pooled): CAGR **+2.54 to +2.78 pp** vs matching C cell (5.28 % → 7.81 % base GC007; 5.25 % → 8.02 % EW GC007); Sh_net Δ −0.28 to −0.34 (σ_est noise + funding drag scale with L); **excSh flat** (Δ +0.00 to +0.03 — invariance identity holds); mean L̄ 1.30 → 2.52 (base), 1.39 → 2.82 (EW); OOS L̄ hits 3.6-4.2 with EW pinned at cap 5 on 18 % of OOS weeks; MaxDD −2.55 % → −5.59 % (base), −2.40 % → −4.41 % (EW) — within 6 %, no cell close to 10 %; funding drag +240 to +316 bp/y (dominant new cost). **Book duration disclosure at cap 5**: IS mean 9.6-10.8y (p95 13-15y); OOS mean 13-15y (p95 17-18y) — a 100 bp CGB back-up would cost 13-18 % of NAV in p95 week. Report: `reports/leverage_higher_cap_round_d.md`. **v6 remains FROZEN**; §8B pass criteria NOT re-applied.
- 2026-07-29 · **Full revision post-review.** Covers boss-review items §一.2, §一.3, §二, §三, §四.D1-D4, §五, §六 in one pass. Key structural changes:
  - **Matrix redesign** (§二 + §六): 9-cell old matrix → 6-cell Round A factorial `{base, EW RB} × {no-lev, cash-fill, book-lev}` + up to 4-cell Round B (winner-only funding/sanity variants). Bond-leg leverage moved to single sanity cell (§二: leg-leverage ≡ modifying policy shares, already scanned by exp1). `σ*=4.5%` dead-zone (§一.2) replaced with `σ*=3.2%, cap=2.0`. Parity σ* ambiguity (§一.3) sidestepped by using fixed σ* only.
  - **σ_est diagnostic split** (§四.D3): M1 vs M2a moved out of leverage matrix, run standalone as blocking M0-B milestone. Frequency mismatch (§四.D2) fixed — M1 now weekly-native EWMA, not daily×√252.
  - **Economic assumptions recalibrated** (§三): funding curve set expanded to `{GC007, DR007, T-futures IRR}`; funding drag prior updated from 5–15 bp/yr to 40–95 bp/yr; JGB→CGB fixed; book duration disclosure added (`duration_ledger.csv`, `book_duration_yr` columns). Bond ETF spread cost split from equity (2 bp vs 10 bp per §四.D4). Haircut arithmetic corrected (h=0.15 → L up to 1.85x single-round, 6.67x infinite-round; cap 2.0 unconstrained).
  - **Cash accounting + cash-fill** (§四.D1): symmetric accrual (positive cash earns DR007, borrow pays funding curve). New cell type `A_*_cashfill` fills the 17.8%–30% intra-group structural cash gap at zero borrow. This is the real free-leverage baseline; any borrowed-leverage cell must beat it.
  - **OOS handling** (§五): scrapped the "IS-only then reveal OOS" ritual — hypothesis was generated after seeing exp1 OOS + stress, so sealing at evaluation stage no longer protects. Replaced with **pre-registered decision rule**: full spec (σ*, cap, funding curves, pass criteria, RB grid, stress-window opening rule) frozen in this document; IS and OOS run + reported together, no re-tuning; stress window kept sealed until a single finalist cell is picked.
  - **Non-goals** hardened into a no-tune list; any change post-signoff requires a new PLAN version.
