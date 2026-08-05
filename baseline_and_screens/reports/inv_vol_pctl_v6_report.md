# v6 static baseline — inv_vol × per-ETF trailing σ percentile

Generated: 2026-07-21

## Motivation

The Phase 11 close-out settled on solo defensive (`inv_vol` sizing on
long_q20 replace ε=0.20) as the v6 finalist. Every prior sizing kernel
measured σ on an *absolute* scale; the user proposed one last check:
does per-ETF vol-regime information (each ETF's current σ vs its own
recent history) improve or hurt the plain 1/σ book?

Rule (per user spec):

```
p_i,t = Pr(σ_i,τ ≤ σ_i,t | t − W + 1 ≤ τ ≤ t)      (per-ETF trailing rank)
u_i,t = (1 / σ_i,t) · exp(β · (0.5 − p_i,t))       (multiplied kernel)
w_i,t = u_i,t / Σu    on the held set              (renormalize)

W = 26 W-FRI bars, β = ln 2
```

Effect at the boundaries:
- p = 0.5 (own median) → multiplier = 1 (no adjustment)
- p = 0.0 (own trailing minimum) → ×√2 upweight
- p = 1.0 (own trailing maximum) → ÷√2 downweight

Selection, hysteresis, α and eligibility are unchanged.

## Locked config

```
cell         : long_q20 replace ε=0.20
control      : inv_vol           (v6 production finalist)
treatment    : inv_vol_pctl      (window=26, β=ln 2)
cost         : 10 bp / side
windows      : IS  (≤ 2023-12-31, 292 bars)
               OOS (2024-01-01 → 2025-07-31, 82 bars)
               full (IS ∪ OOS,  374 bars)
               hold-out (> 2025-07-31, sealed)
```

## Headline — IS + OOS + full (net of 10 bp/side)

**IS**

| book                       | n   | Sharpe | CAGR   | max DD | ann vol | cost bps/yr |
|:---------------------------|----:|-------:|-------:|-------:|--------:|------------:|
| inv_vol (control)          | 292 | +1.000 | 3.43%  | −5.02% | 3.71%   | 134         |
| inv_vol_pctl (treatment)   | 292 | +0.875 | 3.18%  | −5.99% | 3.91%   | 144         |
| **Δ**                      |     | **−0.125** | **−0.25 pp** | **−0.97 pp** | +0.20 pp | +10.1 |

**OOS**

| book                       | n  | Sharpe | CAGR   | max DD | ann vol | cost bps/yr |
|:---------------------------|---:|-------:|-------:|-------:|--------:|------------:|
| inv_vol (control)          | 82 | +2.231 | 2.19%  | −0.78% | 0.99%   | 129         |
| inv_vol_pctl (treatment)   | 82 | +2.050 | 1.98%  | −0.80% | 0.97%   | 144         |
| **Δ**                      |    | **−0.181** | **−0.21 pp** | −0.02 pp | −0.02 pp | +14.9 |

**Full window**

| book                       | n   | Sharpe | CAGR   | max DD | ann vol | cost bps/yr |
|:---------------------------|----:|-------:|-------:|-------:|--------:|------------:|
| inv_vol (control)          | 374 | +1.021 | 3.07%  | −5.02% | 3.31%   | 133         |
| inv_vol_pctl (treatment)   | 374 | +0.892 | 2.84%  | −5.99% | 3.48%   | 144         |
| **Δ**                      |     | **−0.129** | **−0.23 pp** | **−0.97 pp** | +0.17 pp | +11.1 |

**Reading:** the treatment loses on every headline in every window.
Sharpe hit is −0.13 (IS), −0.18 (OOS), −0.13 (full). CAGR uniformly
−0.2 pp. Max DD unchanged on OOS, roughly 1 pp worse on IS. Cost
uniformly ~11 bps/yr higher (from extra sizing turnover — the
multiplier moves every week even on retained names).

## Multiplier distribution — is the adjustment actually firing?

Yes, it's firing (values well inside [1/√2, √2]), but the average
adjustment is tiny in aggregate:

| window | n bars | median-of-median mult | avg per-bar mult 5%–95% range | mean mult |
|:-------|-------:|----------------------:|:------------------------------|----------:|
| IS     | 223    | 1.027                 | [0.716, 1.332]                | 1.045     |
| OOS    | 74     | 0.841                 | [0.711, 1.376]                | 0.992     |
| full   | 297    | 1.027                 | [0.715, 1.343]                | 1.032     |

The per-bar 5%–95% range says on any given bar, the extreme eligible
cells get a ±35% adjustment. But the *median* eligible cell gets
near-1 adjustment. In other words, the kernel is doing what it's
designed to do — flag the outliers in each ETF's own history — it
just doesn't move the aggregate book much.

## Block allocation — where the small shift lands

The reshuffle is essentially **within blocks**, not across blocks.
Bonds still dominate; the pctl adjustment just picks slightly
different bond names.

| block              | inv_vol (IS) | inv_vol_pctl (IS) | Δ pp    | inv_vol (OOS) | inv_vol_pctl (OOS) | Δ pp    |
|:-------------------|-------------:|------------------:|--------:|--------------:|-------------------:|--------:|
| bond_rates         | 44.6%        | 45.0%             | +0.41   | **51.5%**     | 50.4%              | −1.10   |
| bond_credit        | 21.7%        | 21.0%             | −0.65   | 33.2%         | 34.2%              | +1.06   |
| broad_cn           | 4.5%         | 4.6%              | +0.10   | 1.0%          | 1.0%               | −0.01   |
| sector_cn          | 4.3%         | 4.2%              | −0.03   | 1.7%          | 1.8%               | +0.07   |
| cross_border_dm    | 3.9%         | 4.0%              | +0.17   | 1.2%          | 1.1%               | −0.05   |
| metals             | 2.8%         | 2.7%              | −0.08   | 0.4%          | 0.4%               | −0.06   |
| cross_border_hk    | 1.2%         | 1.2%              | −0.02   | 1.0%          | 1.1%               | +0.07   |
| smallcap_cn        | 0.6%         | 0.7%              | +0.07   | 0.02%         | 0.03%              | +0.00   |
| commodity_other    | 0.4%         | 0.4%              | +0.04   | 0.1%          | 0.2%               | +0.01   |

All Δs are under 1 pp. Total bonds (rates + credit): IS 66.3% → 66.0%
(−0.24 pp); OOS 84.7% → 84.6% (−0.04 pp). The kernel is essentially
neutral at the block level.

## Why it didn't help

**1. The 1/σ book was already close to a within-block optimum.** On
   long_q20 with 13 held names, ~66–85% of book weight sits in bonds
   (depending on window). Within bonds, the σ ranking is stable
   week-to-week — Chinese government bond ETFs don't have
   meaningful "regime shifts" in their own trailing σ distribution.
   The pctl adjustment moves mass around inside a pool that's
   already correctly ranked by absolute σ; there's no free lunch to
   capture.

**2. The extra sizing turnover doesn't pay for itself.** Adding
   ~11 bps/yr of cost on a book earning 130–225 bps/yr of gross
   Sharpe-return is roughly a −0.1 Sharpe headwind at the
   volatilities on OOS. That drag alone accounts for a big chunk of
   the observed Sharpe delta.

**3. Percentile of σ is not correlated with next-week return on
   this pool.** The multiplier tilts toward ETFs at their own
   trailing low; if those ETFs then outperformed, we'd see the
   pctl book beating plain 1/σ. It doesn't (uniformly worse). So
   the tilt is at best noise, at worst mildly adverse.

**4. The concept is more likely to help on a pool where regime
   detection *matters* per-ETF.** Bonds are stable; equity ETFs
   have clearer regime shifts. If the book were equity-heavy (e.g.,
   the aggressive `rank_prop` / `alpha_prop` books that hold ~1/3
   equity), the pctl adjustment might actually help. On a
   bond-heavy defensive book, it's noise.

## Decision

**Do not adopt `inv_vol_pctl`.** Solo defensive (plain `inv_vol` on
long_q20 replace ε=0.20) remains the v6 production finalist. The
kernel is available in `hysteresis_engine_v6_sizing.py` if a future
branch wants to test it on a book with more equity exposure.

## Files

- `data/v6_static/inv_vol_pctl/summary.csv` — 2 books × 3 windows.
- `data/v6_static/inv_vol_pctl/bar_{book}.csv` — per-bar detail
  (full-sample; window filtering happens in the summary).
- `data/v6_static/inv_vol_pctl/mult_stats.csv` — per-bar multiplier
  distribution stats (mean, quantiles, 5%/50%/95%).
- `data/v6_static/inv_vol_pctl/block_alloc.csv` — mean block share
  per book × window.
- `scripts/hysteresis_engine_v6_sizing.py` — extended:
  `_sigma_trailing_percentile`, `inv_vol_pctl` branch of
  `_sizing_kernel`. `INV_VOL_PCTL_WINDOW = 26`,
  `INV_VOL_PCTL_BETA = ln 2` are module constants.
- `scripts/inv_vol_pctl_test_v6.py` — this driver.
- `scripts/tests_sizing_v6.py` — 4 new tests: trailing percentile
  monotone case, NaN handling, warmup fallback, full-window
  multiplier bounds.

## Reproducing

```bash
python v6/scripts/tests_sizing_v6.py        # 19 unit tests
python v6/scripts/inv_vol_pctl_test_v6.py   # 2-book × 3-window sweep
```

Runtime < 5 s.
