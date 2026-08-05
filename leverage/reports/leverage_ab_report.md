# Leverage experiment — Round A + B report

**Status:** Round A + B complete on 2026-07-30. Finalist picked: **`B_base_lev`** (base RB 55/20/10/15 + whole-book vol-target σ*=3.2 % cap=2.0), reported under both funding curves (`A_base_lev` = GC007, `B_base_lev_DR007` = DR007-proxy) for sensitivity. **v6 production remains frozen.** Feeds v7 discussion only.
**Windows:** IS = `[first non-zero net_ret bar, 2023-12-31]` (post-warmup start 2019-05-31 empirically), OOS = `[2024-01-01, 2025-07-31]`. Consistent with prior v6 reports.

---

## 0. Metric conventions used in this report

Every cell reports both raw and excess return numbers. Where "excess" is used in the report body, the **cross-cell comparison uses GC007 as the common cash-carry rate** (see §0a).

- `sharpe_net`, `cagr_net`, `max_dd` — raw, on the constant-notional `net_ret` series (v6 convention).
- `excess_cagr_vs_gc007` — `(1 + Σ(net_ret_t − gc007_accrual_t))^(1/n_years) − 1`. Compounded excess return over the GC007 curve. Used in report tables.
- `excess_sharpe_vs_gc007` — same numerator, divided by `std(net_ret) × √52`. Used in report tables.
- `excess_cagr_net`, `excess_sharpe_net` — same formula but using the **cell's own funding curve** as rf. Preserves the §8A invariance identity under leverage. **This is the §8B PASS metric.**
- `avg_rf_ann` — window-mean annualized funding rate of the cell's own curve (diagnostic).

### 0a. Common-rf vs own-rf excess: why we report both

Excess Sharpe / CAGR against the cell's own funding curve keep the theoretical invariance property under leverage but are **not directly comparable across cells with different funding curves**. E.g. `B_base_lev_DR007` has excCAGR_own +3.72 % vs `A_base_lev` GC007 +3.38 % — the +0.34 pp difference decomposes into (i) ~10 bp/yr real funding-drag saving, plus (ii) ~24 bp/yr rf-denominator effect (DR007 proxy runs 29 bp/yr below GC007 IS). The GC007-common column strips out (ii): both cells then post excCAGR_vs_gc007 ≈ +3.38–3.49 %, and the real DR007 benefit is +11 bp/yr (compounded) — modest but real.

---

## 1. M3 — baseline plumbing verification

Engine reproduces the frozen finalist bit-for-bit under the finalist's flat 10 bp cost table.

| check | value |
|---|---:|
| max \|Δnet_ret\| per bar (`A_base_nolev_raw` vs finalist) | 1.0e-16 |
| ΔSharpe on unstripped IS | 1.1e-15 |
| W_name max \|Δw\| any (t, i) | 0.0 (identical panel) |
| turnover mean per bar (IS ≤ 2023-12-31) | 0.0855 (both) |

M1 unit tests all pass: excess Sharpe invariance identity for L ∈ {1.0, 1.35, 1.5, 2.0} holds to 1e-10 on synthetic data; `weekly_accrual` matches hand-calc within 1e-9.

Under the production split cost table (2 bp/side bond, 10 bp/side non-bond) the engine's `A_base_nolev` raw IS Sharpe is +1.481 vs the finalist's +1.424 — the +0.057 delta is the intended §四.D4 effect (bond turnover ~42 % × 8 bp/side saved → ~18 bp/yr cost saving).

---

## 2. Finalist — `B_base_lev` (base RB 55/20/10/15, whole-book vol-target)

Two funding-curve variants shown side by side. All numbers net of trading cost + funding + cash carry. **§8B PASS metric column is `excSh_own` (invariance-preserving).**

### 2a. IS+OOS pooled headline

| variant | curve | avg rf | L̄ | Sharpe | excSh_own | excSh_GC007 | CAGR | excCAGR_GC007 | MaxDD | dur (yr) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_base_nolev (baseline) | GC007 | 2.28 % | 1.000 | +1.852 | +0.971 | +0.971 | +4.28 % | +2.36 % | −2.53 % | 4.15 |
| **A_base_lev (GC007-funded)** | GC007 | 2.28 % | 1.472 | +1.833 | **+1.134** | **+1.134** | **+5.21 %** | **+3.38 %** | −2.55 % | 5.96 |
| **B_base_lev_DR007** | DR007 proxy | 2.01 % | 1.472 | +1.875 | **+1.258** | **+1.176** | **+5.31 %** | **+3.49 %** | −2.55 % | 5.96 |

### 2b. IS window

| variant | Sharpe | excSh_own | CAGR | excCAGR_GC007 | avg rf_ann | MaxDD | L̄ | cap% | floor% | fund drag bp/yr |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_base_nolev | +1.658 | +0.837 | +4.44 % | +2.33 % | 2.39 % | −2.53 % | 1.000 | — | — | 0 |
| A_base_lev (GC007) | +1.581 | +0.897 | +5.03 % | +2.96 % | 2.39 % | −2.55 % | 1.303 | 3.8 | 36.7 | 74 |
| B_base_lev_DR007 | +1.614 | +1.013 | +5.12 % | +3.04 % | 2.10 % | −2.55 % | 1.303 | 3.8 | 36.7 | 63 |

### 2c. OOS window

| variant | Sharpe | excSh_own | CAGR | excCAGR_GC007 | avg rf_ann | MaxDD | L̄ | cap% | floor% | fund drag bp/yr |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_base_nolev | +3.740 | +2.181 | +4.64 % | +2.72 % | 1.97 % | −0.35 % | 1.000 | — | — | 0 |
| A_base_lev (GC007) | +2.949 | +2.158 | +7.16 % | +5.27 % | 1.97 % | −0.78 % | 1.970 | 59.8 | 0.0 | 190 |
| B_base_lev_DR007 | +3.027 | +2.320 | +7.35 % | +5.42 % | 1.76 % | −0.76 % | 1.970 | 59.8 | 0.0 | 170 |

### 2d. Per-calendar-year net CAGR (annualized) and L̄ — finalist under both curves vs baseline

Reads per-year rows of each cell's `per_year.csv`. Years marked (partial) span less than 52 weekly bars — annualized figure inflates by construction; treat as directional.

| year | n bars | A_base_nolev CAGR | A_base_lev (GC007) CAGR / L̄ | B_base_lev_DR007 CAGR / L̄ |
|---|---:|---:|---:|---:|
| 2019 (partial, warmup starts 2019-05-31) | 31 | +10.32 % | +15.45 % / 1.54 | +15.48 % / 1.54 |
| 2020 | 52 | +7.00 % | +7.58 % / 1.05 | +7.59 % / 1.05 |
| 2021 | 53 | +5.52 % | +5.51 % / 1.01 | +5.52 % / 1.01 |
| 2022 | 52 | +0.74 % | +0.42 % / 1.24 | +0.50 % / 1.24 |
| 2023 | 52 | +2.80 % | +2.84 % / 1.78 | +3.25 % / 1.78 |
| 2024 (OOS) | 52 | +5.89 % | +9.56 % / 1.95 | +9.78 % / 1.95 |
| 2025 (OOS partial ≤ 2025-07) | 30 | +2.66 % | +3.43 % / 2.00 | +3.61 % / 2.00 |

Read: (i) 2021 has L̄ ≈ 1.0 — vol targeter's estimator sees ~3.2 % ann realized, exactly matches σ*, so lev CAGR ≈ nolev CAGR. (ii) 2022 has L̄ = 1.24 but IS the one year lev CAGR is *lower* than nolev — 2022 was the equity drawdown year and the vol targeter re-levered during the compression, catching the tail; the funding drag on that lev bar wasn't earned back. (iii) 2024 OOS at L̄=1.95 delivers +367 bp CAGR over nolev — the low-vol regime where the vol targeter capitalizes.

### 2e. `B_base_lev` finalist read

- **excCAGR_GC007 = +3.38 % (GC007-funded) → +3.49 % (DR007-proxy-funded)** vs baseline +2.36 % — a +102 to +113 bp/yr excess-return lift over the un-levered book.
- **excSh_own = +1.134 → +1.258** vs baseline +0.971 — leverage improves the risk-adjusted number under both curves.
- **DD identical to baseline** at −2.55 % pooled and marginally deeper on OOS (−0.78 % vs −0.35 %). Vol targeter's floor at L=1 lets the finalist skip the low-vol OOS-2020 spike gains but keeps the DD tight.
- **Duration lifts from 4.15 y to 5.96 y** pooled, 3.84 y → 7.56 y OOS at L̄=2.0. Real risk. See §4 duration disclosure.
- Funding curve choice contributes ~10 bp/yr real drag saving (rf-adjusted). Boss preference for GC007 (upper-bound funding, no proxy risk) is a defensible pick if the DR007 proxy provenance is a concern.

---

## 3. Ablation results (Round B sanity cells)

Three sanity axes on the finalist recipe. All net of cost + funding + carry, IS+OOS pooled, evaluated against baseline `A_base_nolev` on the invariance-preserving `excSh_own`.

### 3a. Funding channel (already covered — GC007 vs DR007 proxy)

DR007-proxy funded finalist: +10 bp/yr real CAGR saving after removing the rf-denominator effect. Modest. Real DR007 rate is likely between the proxy (2.08 % IS) and GC007 (2.37 % IS); the +10 bp/yr saving is an upper bound on what a real bank-side depo can capture. Conservative pick is GC007.

### 3b. Vol-target vs static L≡cap (`B_base_lev_static`)

| variant | excSh_own | CAGR | excCAGR_GC007 | MaxDD | L̄ |
|---|---:|---:|---:|---:|---:|
| A_base_lev (vol-target) | +1.134 | +5.21 % | +3.38 % | −2.55 % | 1.472 |
| B_base_lev_static (L≡2) | +0.964 | +6.17 % | +4.43 % | **−4.84 %** | 2.000 |

Static L=2 raises CAGR by +96 bp/yr but **doubles the IS drawdown** (−4.84 % vs −2.55 %) and drops risk-adjusted return by −0.17 excSh. Vol targeter's de-lever-in-vol behavior earns the risk-adjusted number — verdict: **vol targeter is not free complexity**, static-L fails the §8B C4 DD criterion.

### 3c. Leg-only vs whole book (`B_base_bondleg_lev`, PLAN §二 answer)

| variant | excSh_own | CAGR | excCAGR_GC007 | MaxDD | L̄ | bond share pooled |
|---|---:|---:|---:|---:|---:|---:|
| A_base_lev (whole book) | +1.134 | +5.21 % | +3.38 % | −2.55 % | 1.472 | 0.89 |
| B_base_bondleg_lev | +1.070 | +4.60 % | +2.72 % | −2.56 % | 1.355 | 0.65 |

Bond-leg-only lev applies L to ~60 % NAV → effective book leverage ~1.18 vs whole-book 1.47. CAGR lift over baseline is only +32 bp/yr, fails §8B C3 (ΔCAGR ≥ +0.5 %). Empirical answer to PLAN §二: **YES, leg-only leverage produces a materially weaker signature than whole-book**; leg-lev is roughly equivalent to reshaping the policy shares (already scanned in `exp1_risk_budget_sensitivity`), whereas whole-book is a genuinely new axis.

---

## 4. Duration disclosure

Static KRD table wired in `_common_leverage.py`: rates default 5.5y, credit default 3.5y; explicit overrides for 30y CGB (511090 → 20y), 10y CGB / CDB (511130/511260/511270 → 8y), 5y CGB (511010 → 5.5y), Shenzhen short-tenor (159649/159650/159651/159816 → 3y). ±0.5 yr accuracy per PLAN §9.

`book_duration_yr` reported below uses **levered** weights `L·W_name`, i.e. the dollar-duration exposure the book actually carries under leverage.

| cell | window | book dur mean | book dur p95 | rates share | credit share |
|---|---|---:|---:|---:|---:|
| A_base_nolev | is+oos | 4.15 y | 4.93 y | 0.62 | 0.20 |
| A_base_nolev | oos | 3.84 y | 3.98 y | 0.61 | 0.30 |
| A_base_lev (GC007) | is+oos | **5.96 y** | 7.66 y | 0.89 | 0.33 |
| A_base_lev (GC007) | oos | **7.56 y** | 7.93 y | **1.19** | 0.59 |
| B_base_lev_DR007 | is+oos | 5.96 y | 7.66 y | 0.89 | 0.33 |
| B_base_lev_DR007 | oos | 7.56 y | 7.93 y | 1.19 | 0.59 |

**Read.** Un-levered book carries ≈ 4.2 yr; the finalist at IS L̄=1.30 carries ≈ 5.4 yr; at OOS L̄=1.97 carries **≈ 7.6 yr**. Bond-notional shares blow past 100 % of NAV in the rates leg at OOS. A 100 bp parallel curve back-up on `A_base_lev` OOS state is a ~7.5 % capital hit vs a ~4 % hit unlevered. This is the primary structural risk the levered finalist adds to v6.

---

## 5. PLAN §8B pass/fail — all Round A + B cells (IS+OOS pooled, C5 as diagnostic only per §5.1 revision)

Baseline `A_base_nolev` IS+OOS: excSh_own +0.971, CAGR +4.28 %, MaxDD −2.53 %. C4 threshold: MaxDD ≥ 1.5×|baseline| = −3.80 %.

| cell | C1 ΔexcSh_pool | C2a ΔexcSh_IS | C2b ΔexcSh_OOS | C3 ΔCAGR_pool | C4 MaxDD_pool | C6 tail | verdict |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---|
| A_ew_nolev | ✅ +0.033 | ✅ +0.045 | ✅ +0.148 | ❌ −0.19 % | ✅ −2.15 | ✅ | 5/6 fail C3 |
| **A_base_lev** | ✅ +0.163 | ✅ +0.061 | ✅ −0.023 | ✅ +0.93 % | ✅ −2.55 | ✅ | **6/6 PASS** |
| A_ew_lev | ✅ +0.196 | ✅ +0.107 | ✅ +0.153 | ✅ +0.75 % | ✅ −2.40 | ✅ | 6/6 PASS |
| **B_base_lev_DR007** | ✅ +0.287 | ✅ +0.176 | ✅ +0.139 | ✅ +1.03 % | ✅ −2.55 | ✅ | **6/6 PASS** |
| B_ew_lev_DR007 | ✅ +0.342 | ✅ +0.199 | ✅ +0.356 | ✅ +0.87 % | ✅ −2.40 | ✅ | 6/6 PASS |
| B_base_lev_static | ✅ | ✅ | ✅ | ✅ +1.89 % | ❌ **−4.84** | ✅ | 5/6 fail C4 |
| B_ew_lev_static | ✅ | ✅ | ✅ | ✅ +1.54 % | ❌ **−4.60** | ✅ | 5/6 fail C4 |
| B_base_bondleg_lev | ✅ +0.099 | ✅ | ✅ | ❌ +0.32 % | ✅ | ✅ | 5/6 fail C3 |
| B_ew_bondleg_lev | ✅ +0.097 | ✅ | ✅ | ❌ +0.09 % | ✅ | ✅ | 5/6 fail C3 |

---

## 6. Funding curve means (IS + OOS)

Direct data: GC007 real from Ricequant `204007.XSHG`; DR007 from SHIBOR-1W proxy (see `_funding/PROVENANCE.md`).

| window | GC007 mean | DR007 proxy mean | Δ (DR − GC) |
|---|---:|---:|---:|
| IS post-warmup 2019-05-31 → 2023-12-31 | 2.373 % | 2.084 % | −0.289 pp |
| OOS 2024-01-01 → 2025-07-31 | 1.938 % | 1.756 % | −0.182 pp |

**Provenance note.** Installed `rqdatac 3.5.2` does not expose the real DR007 endpoint; the loader falls back to SHIBOR-1W. Empirically the proxy runs 6–29 bp *below* GC007 in every window sampled here, opposite to what the PROVENANCE memo initially feared. Real DR007 is typically 10-30 bp below GC007 on average, so the proxy is probably near-real DR007 in level. Nonetheless the DR007-cell's ~10 bp/yr real advantage over the GC007 cell should be interpreted as a **plausible but uncertain estimate**, not a locked number.

---

## 7. PLAN revisions locked during Round A + B (2026-07-30)

Explicit changes to `v6/leverage/PLAN.md` after seeing Round A results:

- **§8B C5** (`pct_at_cap`/`pct_at_floor`) demoted from blocking to per-window diagnostic. Rationale: high `pct_at_cap` on a low-vol regime is the vol-targeter behaving as intended, not a signal-invalidating clamp.
- **§8C funding-drag prior** rewritten to match §5A engine math (no 84 % debt-leg haircut). New prior: L=1.35 GC007 ~76 bp/yr; observed Round-A 74 bp/yr matches.
- **KRD table wired** (`_common_leverage.KRD_DEFAULT_BY_BLOCK`, `KRD_OVERRIDES`). Duration ledger populated per cell; `book_duration_yr_mean/p95` in `summary.csv`.
- **Excess-return columns** added to `summary.csv`: `excess_cagr_net` (own rf, §8B invariance-preserving), `ann_excess_ret_net`, plus cross-cell `excess_cagr_vs_gc007`, `excess_sharpe_vs_gc007`, `ann_excess_ret_vs_gc007` (common rf = GC007).

---

## 8. Open items

- **Real DR007 curve.** Ricequant account access to `econ.get_interbank_pledged_repo_rate` would replace the SHIBOR-1W proxy and remove the residual ±20 bp uncertainty in the DR007-cell drag. Account expires ~2026-08-24.
- **T-futures IRR curve.** Dropped from Round B — CFFEX T-contract settlement + CTD basis not wired. If procured later, `B_base_lev_futures` becomes a natural add-on to isolate real duration-leverage execution cost.
- **Duration ceiling.** Levered finalist carries OOS p95 duration 7.9 yr. No explicit p95 cap in the PLAN; adding one (e.g. ≤ 8.0 yr) would prevent regime-driven duration blow-outs on future OOS. Open design point for v7.

**v6 production stays frozen** regardless of anything in this report.
