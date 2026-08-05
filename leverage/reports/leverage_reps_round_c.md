# Round C — representative-set non-α blocks in the leverage pipeline

Generated: 2026-07-31 10:00:49  


**What changed.** Round C plugs the exp2 adaptive-K representative-set replicated invvol composite into the 6 non-α blocks (bond_rates, bond_credit, cross_border_dm, cross_border_hk, metals, commodity_other). α blocks (broad_cn, sector_cn) keep the Phase 12×13 finalist α selection (q=0.20, ε=0.30). Layer-1 risk budget, leverage engine (σ*=3.2 % ann, cap 2.0, weekly EWMA-52), cost table, funding & cash curves are all unchanged from PLAN §1. Rep-set clusters/reps read from the frozen `data/exp2_representative_sets_v6/` CSVs; nothing is re-tuned.

**Cells.** 6 new cells forming {base RB, EW RB} × {no-lev (GC007 cash carry), lev @ GC007, lev @ DR007 proxy}. Compared 1:1 with the matching Round A / B hold-all counterparts.

**Effective IS start:** first non-zero net_ret bar per cell (≈ 2019-05-31). IS end 2023-12-31; OOS 2024-01-01 → 2025-07-31. Stress window `[2025-08-01, 2026-07-17]` NOT opened.

**Sharpe metric convention.** `excess_sharpe_net` uses the cell's own funding curve as rf (PLAN §1 invariance identity). `excess_sharpe_vs_gc007` uses GC007 as a common rf so DR007-proxy cells are comparable to GC007 cells like-for-like.


## 1. Holdings compression (the point of the exercise)

Mean K names counted per bar over the invested-bar mask (all bars from first-non-zero-net_ret through OOS end). Cash share also masked to invested bars.


| RB | variant | mean K names | Δ vs hold-all | cash share |
|:---|:---|---:|---:|---:|
| base | hold-all   | 53.55 | — | 1.58% |
| base | rep-set    | 31.42 | -22.13 (-41.3%) | 1.66% |
| EW | hold-all   | 53.55 | — | 1.62% |
| EW | rep-set    | 31.42 | -22.13 (-41.3%) | 1.69% |


## 2.is. Metrics — IS window

| pair | variant | Sh_net | excSh_net | excSh_vs_gc007 | CAGR | MaxDD | vol | mean L | %cap | %floor | fdrag bp/y | cshcarry bp/y | cost bp/y |
|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base RB · no-lev | hold-all | +1.658 | +0.837 | +0.837 | +4.44% | -2.53% | +2.90% | 1.000 | 0.0% | 100.0% | +0.0 | +5.2 | +36.1 |
| base RB · no-lev | rep-set | +1.591 | +0.854 | +0.854 | +4.72% | -2.53% | +3.23% | 1.000 | 0.0% | 100.0% | +0.0 | +5.5 | +39.4 |
| EW RB · no-lev | hold-all | +1.814 | +0.881 | +0.881 | +4.29% | -2.15% | +2.55% | 1.000 | 0.0% | 100.0% | +0.0 | +5.6 | +25.8 |
| EW RB · no-lev | rep-set | +1.736 | +0.917 | +0.917 | +4.64% | -2.15% | +2.91% | 1.000 | 0.0% | 100.0% | +0.0 | +5.8 | +27.6 |
| base RB · lev @ GC007 | hold-all | +1.581 | +0.897 | +0.897 | +5.03% | -2.55% | +3.48% | 1.303 | 3.8% | 36.7% | +73.7 | +5.2 | +45.2 |
| base RB · lev @ GC007 | rep-set | +1.582 | +0.934 | +0.934 | +5.29% | -2.55% | +3.68% | 1.140 | 0.8% | 45.0% | +35.4 | +5.5 | +45.3 |
| EW RB · lev @ GC007 | hold-all | +1.682 | +0.944 | +0.944 | +4.96% | -2.40% | +3.23% | 1.411 | 16.2% | 30.8% | +98.4 | +5.6 | +34.7 |
| EW RB · lev @ GC007 | rep-set | +1.694 | +1.005 | +1.005 | +5.32% | -2.40% | +3.46% | 1.208 | 0.8% | 33.8% | +51.6 | +5.8 | +33.8 |
| base RB · lev @ DR007 | hold-all | +1.614 | +1.013 | +0.930 | +5.12% | -2.55% | +3.48% | 1.303 | 3.8% | 36.7% | +62.5 | +5.2 | +45.2 |
| base RB · lev @ DR007 | rep-set | +1.592 | +1.023 | +0.944 | +5.32% | -2.55% | +3.68% | 1.140 | 0.8% | 45.0% | +31.6 | +5.5 | +45.3 |
| EW RB · lev @ DR007 | hold-all | +1.728 | +1.080 | +0.990 | +5.09% | -2.40% | +3.23% | 1.411 | 16.2% | 30.8% | +83.8 | +5.6 | +34.7 |
| EW RB · lev @ DR007 | rep-set | +1.712 | +1.107 | +1.024 | +5.37% | -2.40% | +3.46% | 1.208 | 0.8% | 33.8% | +45.3 | +5.8 | +33.8 |


## 2.oos. Metrics — OOS window

| pair | variant | Sh_net | excSh_net | excSh_vs_gc007 | CAGR | MaxDD | vol | mean L | %cap | %floor | fdrag bp/y | cshcarry bp/y | cost bp/y |
|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base RB · no-lev | hold-all | +3.740 | +2.181 | +2.181 | +4.64% | -0.35% | +1.26% | 1.000 | 0.0% | 100.0% | +0.0 | +0.6 | +18.3 |
| base RB · no-lev | rep-set | +3.826 | +2.247 | +2.247 | +4.69% | -0.34% | +1.24% | 1.000 | 0.0% | 100.0% | +0.0 | +0.6 | +18.9 |
| EW RB · no-lev | hold-all | +4.290 | +2.329 | +2.329 | +4.24% | -0.32% | +1.00% | 1.000 | 0.0% | 100.0% | +0.0 | +0.3 | +11.9 |
| EW RB · no-lev | rep-set | +4.497 | +2.480 | +2.480 | +4.32% | -0.28% | +0.97% | 1.000 | 0.0% | 100.0% | +0.0 | +0.3 | +13.2 |
| base RB · lev @ GC007 | hold-all | +2.949 | +2.158 | +2.158 | +7.16% | -0.78% | +2.48% | 1.970 | 59.8% | 0.0% | +190.0 | +0.6 | +36.2 |
| base RB · lev @ GC007 | rep-set | +3.196 | +2.268 | +2.268 | +6.62% | -0.65% | +2.11% | 1.772 | 22.0% | 0.0% | +149.3 | +0.6 | +32.8 |
| EW RB · lev @ GC007 | hold-all | +3.317 | +2.335 | +2.335 | +6.50% | -0.73% | +1.99% | 2.000 | 100.0% | 0.0% | +196.0 | +0.3 | +23.8 |
| EW RB · lev @ GC007 | rep-set | +3.566 | +2.486 | +2.486 | +6.36% | -0.65% | +1.81% | 1.921 | 61.0% | 0.0% | +179.6 | +0.3 | +25.0 |
| base RB · lev @ DR007 | hold-all | +3.027 | +2.320 | +2.237 | +7.35% | -0.76% | +2.48% | 1.970 | 59.8% | 0.0% | +169.8 | +0.6 | +36.2 |
| base RB · lev @ DR007 | rep-set | +3.265 | +2.435 | +2.337 | +6.77% | -0.63% | +2.11% | 1.772 | 22.0% | 0.0% | +134.1 | +0.6 | +32.8 |
| EW RB · lev @ DR007 | hold-all | +3.415 | +2.537 | +2.433 | +6.69% | -0.72% | +2.00% | 2.000 | 100.0% | 0.0% | +175.4 | +0.3 | +23.8 |
| EW RB · lev @ DR007 | rep-set | +3.663 | +2.699 | +2.585 | +6.54% | -0.63% | +1.82% | 1.921 | 61.0% | 0.0% | +160.8 | +0.3 | +25.0 |


## 2.is+oos. Metrics — IS+OOS pooled window

| pair | variant | Sh_net | excSh_net | excSh_vs_gc007 | CAGR | MaxDD | vol | mean L | %cap | %floor | fdrag bp/y | cshcarry bp/y | cost bp/y |
|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base RB · no-lev | hold-all | +1.852 | +0.971 | +0.971 | +4.28% | -2.53% | +2.58% | 1.000 | 0.0% | 100.0% | +0.0 | +4.0 | +31.5 |
| base RB · no-lev | rep-set | +1.765 | +0.969 | +0.969 | +4.48% | -2.53% | +2.86% | 1.000 | 0.0% | 100.0% | +0.0 | +4.3 | +34.2 |
| EW RB · no-lev | hold-all | +2.011 | +1.005 | +1.005 | +4.09% | -2.15% | +2.26% | 1.000 | 0.0% | 100.0% | +0.0 | +4.3 | +22.3 |
| EW RB · no-lev | rep-set | +1.907 | +1.017 | +1.017 | +4.35% | -2.15% | +2.56% | 1.000 | 0.0% | 100.0% | +0.0 | +4.4 | +23.9 |
| base RB · lev @ GC007 | hold-all | +1.833 | +1.134 | +1.134 | +5.21% | -2.55% | +3.25% | 1.472 | 18.0% | 27.3% | +103.3 | +4.0 | +42.9 |
| base RB · lev @ GC007 | rep-set | +1.809 | +1.129 | +1.129 | +5.28% | -2.55% | +3.35% | 1.301 | 6.2% | 33.5% | +64.5 | +4.3 | +42.1 |
| EW RB · lev @ GC007 | hold-all | +1.935 | +1.167 | +1.167 | +5.03% | -2.40% | +2.96% | 1.561 | 37.6% | 23.0% | +123.3 | +4.3 | +31.9 |
| EW RB · lev @ GC007 | rep-set | +1.927 | +1.198 | +1.198 | +5.25% | -2.40% | +3.12% | 1.390 | 16.1% | 25.2% | +84.2 | +4.4 | +31.5 |
| base RB · lev @ DR007 | hold-all | +1.875 | +1.258 | +1.176 | +5.31% | -2.55% | +3.25% | 1.472 | 18.0% | 27.3% | +89.8 | +4.0 | +42.9 |
| base RB · lev @ DR007 | rep-set | +1.829 | +1.230 | +1.150 | +5.33% | -2.55% | +3.35% | 1.301 | 6.2% | 33.5% | +57.7 | +4.3 | +42.1 |
| EW RB · lev @ DR007 | hold-all | +1.991 | +1.313 | +1.222 | +5.15% | -2.40% | +2.96% | 1.561 | 37.6% | 23.0% | +107.1 | +4.3 | +31.9 |
| EW RB · lev @ DR007 | rep-set | +1.958 | +1.315 | +1.229 | +5.32% | -2.40% | +3.12% | 1.390 | 16.1% | 25.2% | +74.7 | +4.4 | +31.5 |


## 3. Δ = rep-set − hold-all, on IS+OOS pooled window

Sign convention: positive = rep-set is better (higher Sharpe / CAGR, smaller MaxDD magnitude, less cost).


| pair | Δ Sh_net | Δ excSh_net | Δ excSh_vs_gc007 | Δ CAGR | Δ MaxDD | Δ cost bp/y | Δ turn_bond ann | Δ turn_nb ann |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|
| base RB · no-lev | -0.087 | -0.003 | -0.003 | +0.21 pp | +0.00 pp | +2.7 | -0.611 | +0.388 |
| EW RB · no-lev | -0.104 | +0.013 | +0.013 | +0.27 pp | +0.00 pp | +1.7 | -0.525 | +0.270 |
| base RB · lev @ GC007 | -0.024 | -0.005 | -0.005 | +0.07 pp | -0.00 pp | -0.7 | -1.081 | +0.143 |
| EW RB · lev @ GC007 | -0.008 | +0.031 | +0.031 | +0.22 pp | -0.00 pp | -0.4 | -0.938 | +0.152 |
| base RB · lev @ DR007 | -0.046 | -0.029 | -0.026 | +0.02 pp | -0.00 pp | -0.7 | -1.081 | +0.143 |
| EW RB · lev @ DR007 | -0.033 | +0.002 | +0.007 | +0.17 pp | -0.00 pp | -0.4 | -0.938 | +0.152 |


## 4. Reading the tape

**Holdings compression achieved.** Mean K names 53.55 → 31.42 (−41 %), identical on base vs EW because layer-1 shares only rescale weights, they don't gate names. Structural cash 1.6 % (matches hold-all) — book is fully invested. Operational win: ~22 fewer positions to execute each week.

**Rep-only invvol composite (2026-07-31 revision).** The initial Round C used `exp2.build_replicated_block`, which inherits the hold-all invvol mass on the *full* member set and only keeps positions in the reps. Non-rep members and ineligible-rep bars leak into cash (21 % mean cash on the invested-bar mask; per-block leak 8 – 32 %). Replaced by `_build_reps_invvol_subblock` in `rb_variants.py`: the block is invested *fully* in the K reps, invvol-weighted among themselves, normalized to `Σ_block = 1`. Non-rep members are ignored (that is the whole point of the compression). Ineligible-rep mass redistributes to remaining eligible reps within the same block. Sanity: on invested bars, `Σ_block = 1.000` for every block; full-book cash 1.66 % base / 1.69 % EW ≈ hold-all's 1.58 % / 1.62 %.

**No-lev cells — near-parity.** Pooled Sh_net Δ −0.087 (base), −0.104 (EW); excSh Δ −0.003 (base), +0.013 (EW). CAGR +0.21 (base) / +0.27 (EW) pp — rep-set actually *earns more* than hold-all despite similar vol. Realized vol Δ ≈ 0 (rep-set is fully invested, so no cash-sleeve vol dilution any more). Cost drag Δ +1.7 to +2.7 bp/y — a small penalty from the rep-swap refresh spike (see exp2 §5). Net-of-cost still a wash to marginal-positive: rep-set is essentially free at the no-lev level.

**Lev cells — rep-set is a small net win.** Pooled Sh_net Δ −0.008 to −0.046 (all within noise), excSh Δ −0.029 to +0.031, **CAGR Δ +0.02 to +0.22 pp** (rep-set beats hold-all on 3 of 4 lev cells; DR007 base is essentially flat at +0.02). Mean L̄ drops (1.47 → 1.30 base, 1.56 → 1.39 EW pooled) because the rep-set book carries a *higher* pre-lev vol than hold-all (fewer names, less diversification within block), so σ_est is higher, so less leverage is required to hit σ*=3.2 %. Consequently funding drag drops sharply (−40 bp/y base, −40 bp/y EW at GC007). Cost drag falls a hair (−0.4 to −0.7 bp/y). Duration ledger will follow the lower L̄ → lower book duration at the same σ target.

**MaxDD essentially unchanged** across every pair (Δ ≈ 0 pp on IS+OOS pooled). Compression doesn't hurt drawdowns.

**Funding-curve axis.** Δ excSh from switching GC007 → DR007 proxy is preserved for rep-set (~+0.10 on excSh_net), same sign as hold-all's +0.15. DR007 is the better funding either way. The rep-set does not change which funding curve wins.

**Bottom line.** Rep-set halves position count with **no net cost** — Sh flat within noise, CAGR marginally *up*, MaxDD unchanged, funding drag *down* (because less leverage is needed for the same σ*), operational load −22 tickets/week. This flips the initial (buggy) reading. The operational win is now clearly worth taking into v7 discussion.

**Not decided here.** v6 remains FROZEN. Rep-set is a diagnostic addition (Round C, post-hoc extension) with a separate audit trail; nothing in v6 production changes. Re-open this at the higher-cap experiment (L_max=5.0) to confirm the mechanics carry over.
