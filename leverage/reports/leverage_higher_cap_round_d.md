# Round D — higher-cap experiment on the rep-set book

Generated: 2026-07-31 10:11:33  


**What changed.** Round D uses the same rep-only invvol non-α composite as Round C (α blocks unchanged; PLAN §11 log 2026-07-31). Only two knobs move:

- **σ\*** raised 3.2 % → **6.4 %** annualized (2× current target). Rationale (user, boss-approved): 'normal case ≈ 2× leverage'.
- **Cap** raised 2.0 → **5.0**. Rationale (boss): theoretical ceiling is 10×; start with 5× first.

Everything else — layer-1 solver, weekly_ewma_52 σ_est, split-cost table (2/10 bp), funding curves (GC007 & DR007-proxy), cash carry (DR007-proxy on residual), warmup convention — is unchanged from PLAN §1.

**Cells.** 4 cells: `{base RB, EW RB} × {GC007, DR007-proxy}`, all rep-set. Direct 1:1 comparison with the matching Round C lev cells so the delta is entirely the cap-and-σ\* effect. Stress window `[2025-08-01, 2026-07-17]` NOT opened.

**Sharpe metric convention.** `excess_sharpe_net` uses the cell's own funding curve as rf (PLAN §1 invariance identity). `excess_sharpe_vs_gc007` uses GC007 as a common rf so DR007 cells are comparable to GC007 cells like-for-like.



## 1.is. Metrics — IS window

| pair | variant | Sh_net | excSh_net | excSh_vs_gc007 | CAGR | MaxDD | vol | mean L | %cap | %floor | fdrag bp/y | cshcarry bp/y | dur mean y | dur p95 y |
|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base RB · GC007 | cap=2, σ*=3.2 | +1.582 | +0.934 | +0.934 | +5.29% | -2.55% | +3.68% | 1.140 | 0.8% | 45.0% | +35.4 | +5.5 | 5.16 | 6.62 |
| base RB · GC007 | cap=5, σ*=6.4 | +1.255 | +0.918 | +0.918 | +7.71% | -5.59% | +7.05% | 2.136 | 0.8% | 0.4% | +275.2 | +5.5 | 9.64 | 13.27 |
| EW RB · GC007 | cap=2, σ*=3.2 | +1.694 | +1.005 | +1.005 | +5.32% | -2.40% | +3.46% | 1.208 | 0.8% | 33.8% | +51.6 | +5.8 | 5.58 | 7.37 |
| EW RB · GC007 | cap=5, σ*=6.4 | +1.361 | +1.014 | +1.014 | +8.07% | -4.41% | +6.86% | 2.342 | 0.8% | 0.4% | +324.3 | +5.8 | 10.82 | 14.82 |
| base RB · DR007 | cap=2, σ*=3.2 | +1.592 | +1.023 | +0.944 | +5.32% | -2.55% | +3.68% | 1.140 | 0.8% | 45.0% | +31.6 | +5.5 | 5.16 | 6.62 |
| base RB · DR007 | cap=5, σ*=6.4 | +1.303 | +1.006 | +0.965 | +7.96% | -5.44% | +7.05% | 2.136 | 0.8% | 0.4% | +242.1 | +5.5 | 9.64 | 13.27 |
| EW RB · DR007 | cap=2, σ*=3.2 | +1.712 | +1.107 | +1.024 | +5.37% | -2.40% | +3.46% | 1.208 | 0.8% | 33.8% | +45.3 | +5.8 | 5.58 | 7.37 |
| EW RB · DR007 | cap=5, σ*=6.4 | +1.420 | +1.115 | +1.073 | +8.37% | -4.41% | +6.85% | 2.342 | 0.8% | 0.4% | +284.7 | +5.8 | 10.82 | 14.82 |


## 1.oos. Metrics — OOS window

| pair | variant | Sh_net | excSh_net | excSh_vs_gc007 | CAGR | MaxDD | vol | mean L | %cap | %floor | fdrag bp/y | cshcarry bp/y | dur mean y | dur p95 y |
|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base RB · GC007 | cap=2, σ*=3.2 | +3.196 | +2.268 | +2.268 | +6.62% | -0.65% | +2.11% | 1.772 | 22.0% | 0.0% | +149.3 | +0.6 | 6.54 | 7.37 |
| base RB · GC007 | cap=5, σ*=6.4 | +2.759 | +2.297 | +2.297 | +11.34% | -1.32% | +4.24% | 3.634 | 0.0% | 0.0% | +509.2 | +0.6 | 13.40 | 16.88 |
| EW RB · GC007 | cap=2, σ*=3.2 | +3.566 | +2.486 | +2.486 | +6.36% | -0.65% | +1.81% | 1.921 | 61.0% | 0.0% | +179.6 | +0.3 | 6.99 | 7.27 |
| EW RB · GC007 | cap=5, σ*=6.4 | +3.028 | +2.514 | +2.514 | +11.18% | -1.55% | +3.81% | 4.203 | 18.3% | 0.0% | +621.6 | +0.3 | 15.28 | 18.04 |
| base RB · DR007 | cap=2, σ*=3.2 | +3.265 | +2.435 | +2.337 | +6.77% | -0.63% | +2.11% | 1.772 | 22.0% | 0.0% | +134.1 | +0.6 | 6.54 | 7.37 |
| base RB · DR007 | cap=5, σ*=6.4 | +2.876 | +2.464 | +2.415 | +11.83% | -1.27% | +4.25% | 3.634 | 0.0% | 0.0% | +457.4 | +0.6 | 13.40 | 16.88 |
| EW RB · DR007 | cap=2, σ*=3.2 | +3.663 | +2.699 | +2.585 | +6.54% | -0.63% | +1.82% | 1.921 | 61.0% | 0.0% | +160.8 | +0.3 | 6.99 | 7.27 |
| EW RB · DR007 | cap=5, σ*=6.4 | +3.188 | +2.729 | +2.675 | +11.79% | -1.49% | +3.82% | 4.203 | 18.3% | 0.0% | +557.1 | +0.3 | 15.28 | 18.04 |


## 1.is+oos. Metrics — IS+OOS pooled window

| pair | variant | Sh_net | excSh_net | excSh_vs_gc007 | CAGR | MaxDD | vol | mean L | %cap | %floor | fdrag bp/y | cshcarry bp/y | dur mean y | dur p95 y |
|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base RB · GC007 | cap=2, σ*=3.2 | +1.809 | +1.129 | +1.129 | +5.28% | -2.55% | +3.35% | 1.301 | 6.2% | 33.5% | +64.5 | +4.3 | 5.51 | 7.32 |
| base RB · GC007 | cap=5, σ*=6.4 | +1.485 | +1.133 | +1.133 | +7.81% | -5.59% | +6.45% | 2.517 | 0.6% | 0.3% | +334.8 | +4.3 | 10.60 | 15.37 |
| EW RB · GC007 | cap=2, σ*=3.2 | +1.927 | +1.198 | +1.198 | +5.25% | -2.40% | +3.12% | 1.390 | 16.1% | 25.2% | +84.2 | +4.4 | 5.94 | 7.36 |
| EW RB · GC007 | cap=5, σ*=6.4 | +1.591 | +1.225 | +1.225 | +8.02% | -4.41% | +6.22% | 2.816 | 5.3% | 0.3% | +400.0 | +4.4 | 11.96 | 17.66 |
| base RB · DR007 | cap=2, σ*=3.2 | +1.829 | +1.230 | +1.150 | +5.33% | -2.55% | +3.35% | 1.301 | 6.2% | 33.5% | +57.7 | +4.3 | 5.51 | 7.32 |
| base RB · DR007 | cap=5, σ*=6.4 | +1.545 | +1.234 | +1.192 | +8.07% | -5.44% | +6.45% | 2.517 | 0.6% | 0.3% | +296.9 | +4.3 | 10.60 | 15.37 |
| EW RB · DR007 | cap=2, σ*=3.2 | +1.958 | +1.315 | +1.229 | +5.32% | -2.40% | +3.12% | 1.390 | 16.1% | 25.2% | +74.7 | +4.4 | 5.94 | 7.36 |
| EW RB · DR007 | cap=5, σ*=6.4 | +1.666 | +1.343 | +1.300 | +8.33% | -4.41% | +6.22% | 2.816 | 5.3% | 0.3% | +354.1 | +4.4 | 11.96 | 17.66 |


## 2. Δ = D − C on IS+OOS pooled window

Sign convention: positive = D (cap=5, σ\*=6.4) is 'better' on Sh / CAGR (higher), 'worse' on MaxDD (more negative = smaller number here).


| pair | Δ Sh_net | Δ excSh_net | Δ CAGR | Δ MaxDD | Δ vol | Δ mean L | Δ fdrag bp/y | Δ dur mean | Δ dur p95 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base RB · GC007 | -0.324 | +0.003 | +2.54 pp | -3.04 pp | +3.10 pp | +1.216 | +270.4 | +5.09y | +8.04y |
| EW RB · GC007 | -0.336 | +0.027 | +2.78 pp | -2.01 pp | +3.10 pp | +1.427 | +315.8 | +6.02y | +10.30y |
| base RB · DR007 | -0.285 | +0.004 | +2.74 pp | -2.89 pp | +3.10 pp | +1.216 | +239.2 | +5.09y | +8.04y |
| EW RB · DR007 | -0.292 | +0.028 | +3.01 pp | -2.00 pp | +3.10 pp | +1.427 | +279.3 | +6.02y | +10.30y |


## 3. Duration exposure disclosure

Book duration = Σ_i W_lev[t, i] · KRD_i (static KRD table in `_common_leverage.py`; ±0.5y accuracy). At cap=5 the borrowed notional lands mostly in bonds (base 55/20/10/15 RB × invvol sizing → bond-heavy), so duration scales roughly with L.


| cell | window | dur mean | dur p95 | 100bp back-up impact |
|:---|:---|---:|---:|---:|
| D_base_reps_lev | is | 9.64y | 13.27y | ~0.13% (at p95 duration) |
| D_base_reps_lev | oos | 13.40y | 16.88y | ~0.17% (at p95 duration) |
| D_base_reps_lev | is+oos | 10.60y | 15.37y | ~0.15% (at p95 duration) |
| D_ew_reps_lev | is | 10.82y | 14.82y | ~0.15% (at p95 duration) |
| D_ew_reps_lev | oos | 15.28y | 18.04y | ~0.18% (at p95 duration) |
| D_ew_reps_lev | is+oos | 11.96y | 17.66y | ~0.18% (at p95 duration) |
| D_base_reps_lev_DR007 | is | 9.64y | 13.27y | ~0.13% (at p95 duration) |
| D_base_reps_lev_DR007 | oos | 13.40y | 16.88y | ~0.17% (at p95 duration) |
| D_base_reps_lev_DR007 | is+oos | 10.60y | 15.37y | ~0.15% (at p95 duration) |
| D_ew_reps_lev_DR007 | is | 10.82y | 14.82y | ~0.15% (at p95 duration) |
| D_ew_reps_lev_DR007 | oos | 15.28y | 18.04y | ~0.18% (at p95 duration) |
| D_ew_reps_lev_DR007 | is+oos | 11.96y | 17.66y | ~0.18% (at p95 duration) |

**Interpretation.** A 100 bp parallel CGB curve back-up would hit p95-duration weeks by dur_p95 × 1 % = 13–18 % of NAV. That's a real tail risk the boss needs to be aware of. Stress window (2025 H2 – 2026 H1) is sealed but if it opens, the p05 net_ret conditional-on-high-rf diagnostic will tell us how the OOS high-L regime handled duration shocks in practice.


## 4. Reading the tape

**CAGR scales roughly with L, but Sharpe compresses.** IS+OOS pooled CAGR jumps from ~5.3 % (cap 2) to ~7.8-8.3 % (cap 5) — +2.5 to +3.0 pp. Mean L̄ goes 1.30 → 2.52 (base) and 1.39 → 2.82 (EW), roughly a doubling. So CAGR uplift ≈ L̄ multiplier × incremental excess return, as the invariance identity predicts. Sh_net drops ~0.32 (base) and ~0.28 (EW) pooled — σ_est model error and funding-drag noise both scale with L, chipping at the ratio.

**Funding drag is the dominant cost at higher cap.** Pooled GC007 funding drag jumps from ~65 bp/y (base cap=2) to ~335 bp/y (base cap=5). That's ~5× — matches the (L̄−1) × funding rate scaling. On DR007 proxy the drag is ~297 bp/y (base), still ~5× the C-cell 58 bp/y. Excess Sharpe (which nets rf out) stays roughly flat (Δ 0.00 to −0.03), which is the correct invariance signal — the CAGR gain is real, not an artifact of the funding accounting.

**OOS L̄ hits 3.6–4.2 in low-vol regime.** The 2024-25 vol environment lets σ*=6.4 % pull leverage up to ~4.2 mean on EW; EW hits cap 18 % of OOS weeks. Base cap only 0.6 % of weeks. IS L̄ 2.14 base / 2.34 EW — well below cap. So the cap 5.0 headroom mostly matters for the OOS low-vol regime, not for 'normal case'.

**MaxDD doubles.** Pooled MaxDD: base −2.55 % → −5.59 % (cap 2 → cap 5); EW −2.40 % → −4.41 %. Both stay inside 6 %, well within any reasonable risk tolerance for a duration-levered book, but the scaling is close to linear in L̄ as expected. No cell approaches 10 %.

**Book duration is the real disclosure.** OOS mean 13-15 y, p95 17-18 y. A 100 bp CGB back-up costs 13-18 % of NAV in the p95 week. That is the risk the boss should hear alongside the CAGR uplift. This is why the pre-registered stress diagnostic (`net_ret_p05_when_rf_p90`) matters more at cap 5.

**Funding-curve axis.** DR007-proxy delivers ~+0.10 Sh_net and ~+0.10 excSh_net at cap 5, same shape as at cap 2. Same conclusion: real DR007 (or better, T-futures IRR) beats GC007 for execution.

**Which cell to bring to the boss.** `D_ew_reps_lev_DR007` gives the best CAGR (+8.33 % pooled, +11.79 % OOS) with the smallest MaxDD (−4.41 %) — but caveat: OOS L̄ 4.20 with 18 % of weeks pinned at cap 5 signals σ*=6.4 % isn't enough headroom in low-vol regimes. If normal-case L̄ ≈ 2 is the boss's benchmark, base RB delivers that (IS L̄ 2.14 base vs 2.34 EW). Suggest surfacing both.

**Not decided here.** v6 remains FROZEN. Round D is a diagnostic. PLAN §8B pass criteria (pre-registered on Round A axis at cap 2) are NOT re-applied. Real decision waits for boss review, stress-window open (if requested), and v7 scope conversation.
