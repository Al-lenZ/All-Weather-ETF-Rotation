# v6 static baseline — oracle blender OOS shot (Phase 11.2 close-out)

Generated: 2026-07-21

## Purpose

Open the OOS window for the **alpha_prop + ramp + fwd_4w_rv** finalist
from the last round. The oracle uses actual weekly RV (from
`vol_forecast_v6/rv_panel.parquet`), so any Sharpe / CAGR it earns is
the **upper bound** any realistic vol forecast (HAR, etc.) could
reach. The user's stated decision rule: if the oracle doesn't hold
OOS with meaningful edge, fall back to solo defensive.

This is a one-shot, pre-registered evaluation. No hyperparameter
tuning between IS and OOS.

## Locked configuration (frozen before opening OOS)

```
cell              : long_q20 replace ε=0.20
aggressive kernel : alpha_prop   (v4pool / v5:
                                  w ∝ α − min(α_held) + rng_held/H,
                                  ε floor = max(rng/H, 1e-12))
defensive kernel  : inv_vol      (unchanged since Phase 9.2)
schedule          : ramp piecewise-linear
gates             : lower = 0.30, upper = 0.90
warmup_lambda     : 0.50
percentile        : expanding causal rank, min_history = 26
vol_source        : fwd_4w_rv    (mean of ACTUAL weekly RV over
                                  bars t+1..t+4; not shifted trailing σ)
transient NaN     : hold_through_transient_nan (post-warmup NaN
                                  holds last valid pct)
cost              : 10 bp / side
```

## Windows

| window | dates                       | n bars |
|:-------|:----------------------------|-------:|
| IS     | ≤ 2023-12-31                | 292    |
| OOS    | 2024-01-01 → 2025-07-31     | 82     |
| full   | IS ∪ OOS                    | 374    |
| hold-out | > 2025-07-31              | 51     |

Hold-out remains sealed.

## Headline — IS vs OOS side by side (net of 10 bp/side)

**IS (reproduces the alpha_prop last-round report; sanity check)**

| book                | n   | Sharpe | CAGR   | max DD  | ann vol | cost bps/yr |
|:--------------------|----:|-------:|-------:|--------:|--------:|------------:|
| solo_defensive      | 292 | +1.000 | +3.43% | −5.02%  | 3.71%   | 134         |
| solo_aggressive_ap  | 292 | +0.745 | +4.49% | −11.16% | 6.68%   | 226         |
| **blend_fwd_4w_rv** | 292 | **+0.940** | **+4.20%** | −5.67% | 4.92% | 199 |

**OOS — the shot**

| book                | n  | Sharpe | CAGR   | max DD | ann vol | cost bps/yr |
|:--------------------|---:|-------:|-------:|-------:|--------:|------------:|
| **solo_defensive**  | 82 | **+2.231** | +2.19% | **−0.78%** | **0.99%** | 129 |
| solo_aggressive_ap  | 82 | +0.979 | **+5.15%** | −3.73% | 5.34% | 240 |
| blend_fwd_4w_rv     | 82 | **+0.579** | +1.52% | −2.77% | 2.63% | 221 |

**Full window (IS + OOS)**

| book                | n   | Sharpe | CAGR   | max DD  | ann vol |
|:--------------------|----:|-------:|-------:|--------:|--------:|
| solo_defensive      | 374 | +1.021 | +3.07% | −5.02%  | 3.31%   |
| solo_aggressive_ap  | 374 | +0.786 | +4.39% | −11.16% | 6.40%   |
| blend_fwd_4w_rv     | 374 | +0.873 | +3.54% | −5.67%  | 4.52%   |

## OOS verdict

- **Δ Sharpe (blender − defensive) OOS = −1.652.** The blender loses
  by 1.65 Sharpe points on OOS, vs a promised −0.06 gap on IS.
- **Δ CAGR OOS = −0.67 pp** — the blender earns LESS CAGR than
  defensive on OOS. Not a Sharpe-for-CAGR tradeoff; a strict loss on
  both dimensions.
- **Δ max DD OOS = −1.99 pp** — worse drawdown too.
- Blender is **Pareto-dominated by both solo books on OOS.** Solo
  defensive wins Sharpe and DD; solo aggressive wins CAGR. The
  blender doesn't win any headline.

The oracle upper bound doesn't hold. That means a realistic HAR
forecast has zero chance of doing better than what we just measured
— HAR would just be a noisier version of the same signal that
already failed as an oracle.

## Why it failed — regime signal inverted on OOS

Bucketing IS and OOS bars by the same fwd_4w_rv percentile gate,
tracking the aggressive − defensive per-week return spread:

| window | low regime (pct < 0.3) | mid regime (0.3–0.9)  | **high regime (pct > 0.9)** | total |
|:-------|-----------------------:|----------------------:|----------------------------:|------:|
| IS     | +0.088% (65 bars)      | +0.026% (178 bars)    | **−0.147%** (21 bars)       | +0.024% |
| OOS    | +0.073% (29 bars)      | −0.085% (45 bars)     | **+0.813%** (8 bars)        | +0.058% |

**The high-regime sign flipped from −0.147%/wk on IS to +0.813%/wk
on OOS.** In the IS window, aggressive lost 15 bp/wk vs defensive
when forward RV was in the top decile — that's the pattern the
blender was designed to gate around. On OOS, aggressive *wins*
81 bp/wk vs defensive in the same regime. The blender was
defensive during exactly the weeks it should have been aggressive.

Attribution on the 8 OOS bars flagged as full-defensive
(pct > 0.90):

| what we did / what we could have done | return over those 8 bars |
|:--------------------------------------|-------------------------:|
| blender (was defensive)               | +1.23%                   |
| defensive alone (equivalent to what we did) | +1.24%             |
| **aggressive alone (what we should have done)** | **+7.75%**    |
| **blender lost vs aggressive-alone**  | **−6.51%**               |

Over the 82-bar OOS window, that −6.51% shortfall on 8 bars is a
~4.1 pp CAGR drag — nearly the entire CAGR gap between the blender
(1.52%) and solo aggressive (5.15%).

## Why aggressive suddenly wins in high vol on OOS

The IS pattern ("aggressive loses in the top-decile forward RV
weeks") was consistent with equity-heavy books getting hit in
crisis windows (COVID Feb-Apr 2020, 2022 Feb-May). The OOS window
(2024-01 to 2025-07) has NO comparable crisis:

- Solo defensive OOS Sharpe = +2.231, max DD = −0.78%. Bonds have
  been unusually stable — annualized vol is 0.99% (vs IS 3.71%,
  1/3.7×). Any "high-vol" bar on OOS is more likely a benign equity
  rally week that also happens to hit the RV top-decile, not a
  crisis week.
- Solo aggressive_ap OOS CAGR = +5.15%, DD = −3.73%. The aggressive
  book had a *good* OOS — 2024-2025 has been kind to Chinese
  equity-tilted books.

Under this regime, "forward RV in top decile" is picking up strong
equity days, not risk-off days. The blender gates aggressive off
right when equity is about to rip. Same signal, opposite meaning.

## Solo book correlation dropped on OOS

- IS solo return correlation: 0.906
- OOS solo return correlation: **0.600**

On IS the two books were 91% correlated (share selection + α,
differ only in sizing). On OOS the correlation drops to 60% —
because bond and equity paths de-coupled in 2024-2025. A blend of
two books with dropping correlation should mechanically get *more*
diversification benefit; but the timing of the blend (gate signal)
was aligned to the wrong regime, so the diversification benefit
was wasted on the wrong sides of the market.

## λ regime distribution — sanity check

Percentile normalization is expanding-causal, so OOS bars rank
against ALL prior bars (IS + OOS ≤ t). This is legitimate causal
behavior. The λ distribution on OOS looks reasonable:

| window | n bars | mean λ | share full agg (λ=1) | share full def (λ=0) | share ramp |
|:-------|-------:|-------:|---------------------:|---------------------:|-----------:|
| IS     | 292    | 0.590  | 22.6%                | 7.2%                 | 70.2%      |
| OOS    | 82     | 0.599  | 35.4%                | 9.8%                 | 54.9%      |
| full   | 374    | 0.592  | 25.4%                | 7.8%                 | 66.8%      |

Mean λ is essentially unchanged (0.59 IS → 0.60 OOS). Top-decile
gate fires 9.8% of OOS bars — slightly above the ~10% design
target, which means the score's percentile calibration is working.
The failure isn't a broken gate; it's that the *interpretation* of
"top-decile forward RV" changed sign OOS.

## Decision — per user's fallback rule

The user set the rule at the start of this round: **if the
oracle-blender OOS shot doesn't hold, choose solo defensive.**
The oracle shot delivered:
- Blender OOS Sharpe **+0.579**
- Solo defensive OOS Sharpe **+2.231**
- Solo aggressive OOS Sharpe +0.979
- Blender is Pareto-dominated by both solo books.

**Decision: adopt solo defensive as the v6 finalist.** The two-book
design is retired for now. It fit a specific IS regime that reversed
on OOS; even a perfect vol forecast can't rescue it.

Consequence for HAR (Phase 11.3): **do not open**. Phase 11.3 tests
a realistic forecast against the oracle upper bound; the oracle
upper bound failed. Any HAR result would be strictly worse. No
information to gain.

## What could resurrect the two-book design (not for now — future work)

- **The regime signal probably isn't forward RV.** Some structural
  variable that correlates *with* the aggressive-book advantage
  going forward (not just current market vol) would need to be
  identified. Candidates: forward return dispersion, momentum-of-
  vol, cross-block dispersion. Would need to be validated across
  multiple regime shifts — the 2024-2025 shift alone isn't enough
  data.
- **Selection-axis diversification.** The 88% IS solo-book
  correlation (dropping to 60% OOS) suggests the two books are too
  similar to be a real hedge. Making the aggressive book use a
  *different* selection rule (higher q, different α, different
  hysteresis) could give a more genuine hedge.
- **Longer OOS.** The current OOS is 1.6 years. Repeating this test
  after a full-cycle OOS window (5+ years including a real crisis)
  would validate whether the IS pattern holds under a mix of
  regimes, or whether the design is inherently fragile.

None of these is urgent. Solo defensive is the production choice.

## Files

- `data/v6_static/oos_shot_ap/summary.csv` — 3 books × 3 windows.
- `data/v6_static/oos_shot_ap/bar_{book}.csv` — per-bar detail
  (IS + OOS combined; hold-out excluded from evaluations but
  present in raw file).
- `data/v6_static/oos_shot_ap/lambdas.csv` — λ + score + pct
  full-sample series.
- `data/v6_static/oos_shot_ap/regime_by_window.csv` — λ regime
  histogram per window.
- `data/v6_static/oos_shot_ap/high_vol_spread.csv` — def−agg return
  in high-vol weeks per window.
- `scripts/blender_oos_shot_v6.py` — this driver. Config is frozen
  in module constants at the top; changing anything invalidates the
  OOS shot.

## Reproducing

```bash
python v6/scripts/blender_oos_shot_v6.py
```

Runtime < 10 s.
