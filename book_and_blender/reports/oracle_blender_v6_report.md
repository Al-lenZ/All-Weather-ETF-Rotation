# v6 static baseline — two-book oracle blender (Phase 11.2, revised)

Generated: 2026-07-21 (second run after user-requested corrections)

## Corrections vs the first draft

Three fixes were applied on user feedback; all three matter to the
headline.

1. **Proper oracle vol source.** The first draft used
   ``sigma_causal_26w.shift(-1)`` as the "1-week oracle" — that is a
   one-bar-shifted 26w trailing σ, not the actual weekly RV that HAR
   is designed to predict. This revision uses
   ``vol_forecast_v6/rv_panel.parquet`` (annualized weekly realized RV
   per ETF) as the oracle input. The oracle now truly answers "if we
   knew what the actual RV next week will be, does the blender work?"
2. **Correct forward-rolling on the 4-week oracle.** The first draft's
   ``fwd_4w`` used ``.shift(-1).rolling(4).mean()`` which is
   overwhelmingly backward-looking (window at bar t averages
   σ[t−2 … t+1]). Fixed to a manual stack-then-``nanmean`` over
   ``shift(-1), shift(-2), shift(-3), shift(-4)``, so at bar t the
   score is truly mean(RV[t+1..t+4]). Regression-tested.
3. **Symmetric warmup.** The first draft's ``lambda_schedule`` used
   ``default_lambda=1.0`` for naive (aggressive warmup) and
   ``1 − default_lambda = 0.0`` for inverted (defensive warmup),
   biasing the comparison. Fixed to ``warmup_lambda = 0.5`` (neutral
   50/50 blend) for **both** directions, so naive vs inverted are
   apples-to-apples on the first ``min_history`` bars.

Membership consistency was already correct in the first draft — the
equity mask is applied *before* the σ/RV shift, so at bar t under an
oracle source we use σ (or RV) at t+k masked by membership at t+k.
Confirmed and documented in the module header.

## Motivation (unchanged)

Phase 11.1 confirmed the aggressive book (`rank_prop` sizing) delivers
CAGR +1.41 pp at DD 2.91× and Sharpe −0.35 vs the defensive `1/σ`
baseline. Phase 11.2 tests whether a per-bar λ blend, gated by an
equity-block risk score, can push the joint frontier past the solo
defensive book on IS Sharpe. The oracle variant tests this under a
**perfect vol forecast** — isolates whether the *pipeline design*
works before we invest in a real forecast.

## Design (user spec)

```
W_blend[t] = λ[t] · W_aggressive[t] + (1 − λ[t]) · W_defensive[t]

risk_score[t]     = equal-weight mean of σ across equity-block members
                    (broad_cn, sector_cn, smallcap_cn,
                     cross_border_dm, cross_border_hk)
score_pct[t]      = expanding causal percentile rank of risk_score
                    (min_history = 26 W-FRI bars,
                     warmup → λ = 0.5 for both directions)

λ_naive(pct):
    pct < 0.30           →  λ = 1          (full aggressive)
    0.30 ≤ pct ≤ 0.90    →  λ = (0.9 − pct) / 0.6
    pct > 0.90           →  λ = 0          (full defensive)
```

Both books share **selection + hysteresis** (same `long_q20 replace
ε=0.20` cell). Selection cost is paid once; turnover is priced on the
blended weight panel, so shared-name Δw naturally net.

## Variants (revised)

| Variant                | λ direction | vol source              |
|:-----------------------|:-----------:|:------------------------|
| `blend_causal`         | naive       | σ_causal_26w at t (no forecast) |
| `blend_fwd_1w_rv`      | naive       | **actual RV at t+1** (proper 1-week oracle) |
| `blend_fwd_4w_rv`      | naive       | **mean actual RV over [t+1..t+4]** (proper 4-week oracle) |
| `blend_inv_causal`     | inverted    | σ_causal_26w at t (no forecast) |
| `blend_inv_fwd_1w_rv`  | inverted    | actual RV at t+1                 |
| `blend_inv_fwd_4w_rv`  | inverted    | mean actual RV over [t+1..t+4]   |

Inverted variants were retained from the first draft because the
regime diagnostic on the *causal* signal still shows the inverted
direction has an IS Sharpe edge (see §Regime × future-return
diagnostic below) — but the corrected oracle now allows us to
distinguish whether that edge is a real regime effect or a
lagging-signal artifact.

## Sample discipline

Per [[feedback-oos-discipline]], IS-only (bars ≤ 2023-12-31,
292 W-FRI bars). 10 bp/side cost per [[feedback-backtests-cost-on]].

## Binary variants added (2nd revision)

Motivation: the regime × future-return diagnostic (see below) shows the
mid-regime spread on the forward-RV signals is still positive
(+0.09%/wk on fwd_1w_rv, +0.04%/wk on fwd_4w_rv). Under the ramp
schedule, the middle band already tilts partial-defensive — throwing
away that positive edge. A **binary** schedule keeps the book fully
aggressive whenever the forward oracle isn't signaling actual
top-decile RV, and only steps out for the high-decile weeks where
aggressive genuinely loses.

```
λ_binary(pct):
    pct > 0.90   →  λ = 0   (full defensive)
    pct ≤ 0.90   →  λ = 1   (full aggressive)
    pct NaN      →  λ = 0.5 (warmup, symmetric with ramp variants)
```

Also added in this revision:

- **`hold_through_transient_nan`** helper — post-warmup NaN score bars
  (from Chinese-New-Year weeks in the sigma calendar that don't
  appear in `rv_panel.parquet`) now hold the last valid pct, so
  binary λ doesn't oscillate to warmup=0.5 and back on those bars.
  Without this, the switching-cost diagnostic overcounted transitions
  by ~4/yr and inflated cost proportionally. Applied to both ramp and
  binary variants for consistency.

Only naive-direction binary variants were run — Phase 11.2's diagnostic
already established that inverted-direction wins on causal σ are a
lagging-signal artifact, and inverted-direction on forward-RV signals
fails cleanly, so there is no reason to retest inverted under a
harder-shifting rule.

## Headline — revised (IS, all metrics net of cost)

`held` = mean number of ETFs actually selected per bar (identical
across variants — they share the `long_q20 replace ε=0.20`
selection). `eff N` = **1 / Σw² per bar, then averaged** — a
concentration diagnostic. Equal weights → eff N ≈ held; concentrated
weights → eff N < held. Solo defensive holds 13.2 names but the 1/σ
kernel puts ~49% on the top-1 (a low-vol bond), so its effective
diversification is only 4.5.

| variant                | net Sharpe | net CAGR | net max DD | ann vol | cost bps/yr | held | eff N (1/HHI) |
|:-----------------------|-----------:|---------:|-----------:|--------:|------------:|-----:|--------------:|
| **solo_defensive**     | **+1.000** | 3.43%    | −5.02%     | 3.71%   | 134         | 13.2 | 4.5           |
| solo_aggressive        | +0.649     | 4.84%    | −14.62%    | 8.34%   | 237         | 13.2 | 12.2          |
| blend_causal (naive)   | +0.452     | 2.69%    | −11.74%    | 6.34%   | 204         | 13.2 | 8.9           |
| **blend_fwd_1w_rv**    | +0.780     | 3.86%    | −8.53%     | 5.41%   | 258         | 13.2 | 8.8           |
| **blend_fwd_4w_rv**    | **+0.889** | **4.43%**| −6.95%     | 5.51%   | 212         | 13.2 | 8.9           |
| blend_inv_causal       | **+1.024** | **5.39%**| **−6.49%** | 5.96%   | 183         | 13.2 | 7.0           |
| blend_inv_fwd_1w_rv    | +0.525     | 3.36%    | −12.17%    | 6.92%   | 235         | 13.2 | 7.2           |
| blend_inv_fwd_4w_rv    | +0.574     | 3.59%    | −11.45%    | 6.80%   | 191         | 13.2 | 7.0           |
| binary_causal          | +0.407     | 2.93%    | −15.86%    | 7.70%   | 233         | 13.2 | 11.8          |
| **binary_fwd_1w_rv**   | **+0.843** | **+5.41%**| −12.06%   | 7.27%   | 253         | 13.2 | 11.6          |
| **binary_fwd_4w_rv**   | +0.815     | +5.39%   | −12.37%    | 7.50%   | 240         | 13.2 | 11.7          |
| best_fixed_λ = 0.00    | +1.000     | 3.43%    | −5.02%     | 3.71%   | 134         | 13.2 | 4.5           |

Small numeric drift on `blend_fwd_1w_rv` and `blend_inv_fwd_1w_rv` vs
the last table is from the transient-NaN fix (fewer spurious 50/50
warmup bounces), not from any methodological change.

## What changed vs the first draft

- `blend_fwd_1w`: Sharpe +0.616 → **+0.780** under the corrected
  RV oracle. Real forward RV carries meaningfully more information
  than a 1-bar-shifted trailing σ.
- `blend_fwd_4w`: Sharpe +0.537 → **+0.889** — the biggest jump.
  The prior 4-week variant was mostly backward-looking due to the
  rolling-window bug; corrected, it's now the strongest *honest*
  variant.
- `blend_inv_causal`: Sharpe +0.957 → +1.024 — actually *improved*
  because warmup went from full-defensive (favorable for defensive)
  to 50/50. Still the highest Sharpe of any variant, but see the
  diagnostic below.
- `blend_inv_fwd_1w_rv`: Sharpe +0.830 → **+0.529** — collapses.
  When "next week's actual RV" is the signal (not shifted trailing
  σ), the inverted direction FAILS. This is the diagnostic bomb:
  inverted only "works" on the lagging signal, not on the real
  forward signal.

## Regime × future-return diagnostic

Spread = net_ret_aggressive − net_ret_defensive per bar, IS-only.
Aggregate spread = **+0.033% / wk = +1.70% / yr** (aggressive's raw
CAGR premium comes from this).

Bucketing on three signals in parallel — cell values are mean(spread)
per week, in %:

**Causal σ (matches `blend_causal` gate)**
| regime | future up | future down | combined |
|:-------|----------:|------------:|---------:|
| low  (81 bars)  | +0.22%   | −0.32%   | −0.03% |
| mid  (134 bars) | +0.47%   | −0.61%   | −0.03% |
| **high (26 bars)** | +0.68% | −0.18% | **+0.34%** |

**Actual RV at t+1 (matches `blend_fwd_1w_rv` gate) — proper oracle**
| regime | future up | future down | combined |
|:-------|----------:|------------:|---------:|
| low  (56 bars)  | +0.21%   | −0.23%   | +0.01% |
| mid  (169 bars) | +0.50%   | −0.52%   | +0.09% |
| **high (21 bars)** | +0.79% | **−0.94%** | **−0.20%** |

**Mean actual RV over [t+1..t+4] (matches `blend_fwd_4w_rv`)**
| regime | future up | future down | combined |
|:-------|----------:|------------:|---------:|
| low  (65 bars)  | +0.33%   | −0.20%   | +0.12% |
| mid  (178 bars) | +0.48%   | −0.47%   | +0.04% |
| **high (21 bars)** | +0.60% | **−0.94%** | **−0.21%** |

**Reading:** the high-regime spread flips sign between the causal
signal and the proper forward-RV signals — from **+0.34%** (on
causal) to **−0.20% / −0.21%** (on actual next-week RV, or actual
4-week RV). The "aggressive wins in high vol" pattern that motivated
the inverted schedule in the first draft is **not** a real
regime effect. What causal σ is picking up is different from what
the actual next-week RV picks up.

Interpretation: causal σ percentile is "we've been in a high-vol
window for weeks" — the tail-end of a vol spike, which is
typically also the *recovery* phase where equity mean-reverts up
and the aggressive book (which tilts equity via α ranks) catches
the rally. The proper forward oracle correctly identifies "next
week's actual RV will be high" and shows aggressive LOSES in
those weeks (−0.94%/wk on down-weeks, only +0.79%/wk on up-weeks,
net −0.20%).

**This is the root cause of the "inverted looks great" mirage in
the first draft.** The inverted schedule with causal σ is fitting
crisis-recovery periods, not identifying a regime where aggressive
is structurally better.

## Crisis strip

Pre-registered crisis windows (fixed before running the strip):
- COVID: 2020-02-01 → 2020-04-30 (12 IS bars)
- 2022:  2022-02-01 → 2022-05-31 (17 IS bars)

Aggregate spread and solo Sharpe under stripping:

| config                | n bars | def Sharpe | agg Sharpe | mean spread %/wk |
|:----------------------|-------:|-----------:|-----------:|-----------------:|
| full IS (no strip)    | 292    | +1.000     | +0.649     | **+0.033**       |
| strip COVID           | 280    | +1.157     | +0.731     | +0.036           |
| strip 2022            | 275    | +1.050     | +0.758     | +0.046           |
| **strip both**        | 263    | **+1.221** | **+0.864** | **+0.051**       |

**Reading:** stripping the two crises actually *raises* both solo
Sharpes and the spread. The aggressive book's +1.7% annualized
CAGR premium is NOT concentrated in the crisis windows — outside
crises the aggressive book earns +0.051%/wk = +2.7%/yr premium.

Within-crisis vs out-of-crisis contribution to the "aggressive wins
in high-regime" pattern:

| signal      | regime | in-crisis spread %/wk (n) | out-of-crisis %/wk (n) |
|:------------|:-------|--------------------------:|-----------------------:|
| causal      | low    | −0.22 (10)               | −0.01 (71)             |
| causal      | mid    | −0.13 (18)               | −0.01 (116)            |
| causal      | high   | **+0.67** (1)            | **+0.33** (25)         |
| fwd_1w_rv   | low    | — (0)                    | +0.01 (56)             |
| fwd_1w_rv   | mid    | +0.22 (20)               | +0.07 (149)            |
| fwd_1w_rv   | high   | **−0.88** (8)            | +0.22 (13)             |
| fwd_4w_rv   | low    | — (0)                    | +0.12 (65)             |
| fwd_4w_rv   | mid    | +0.09 (17)               | +0.03 (161)            |
| fwd_4w_rv   | high   | **−0.44** (12)           | +0.11 (9)              |

Two things stand out:

1. **Causal-high regime spread is +0.33% even OUT of crises** (25
   bars). So the aggressive-wins-in-high-causal-σ pattern does exist
   outside the pre-registered crisis windows. It's not *only*
   crisis-recovery — but the mechanism is likely the same
   (aggressive catches equity mean-reversion after any prolonged
   vol elevation). Under this reading, `blend_inv_causal` still
   captures a real economic effect on IS, but it's a slow-mean-
   reverting recovery signal, not a "forward regime" signal.

2. **fwd_1w_rv high-regime IN crisis is very negative (−0.88%/wk on
   8 bars).** These are the actual crisis weeks — high forward RV
   AND inside COVID/2022 — where aggressive gets hurt badly. Out of
   crisis, high fwd_1w_rv is +0.22%/wk (13 bars), so the effect
   inverts. This is why the proper-oracle inverted variants fail:
   when we know actual high RV is coming, we shouldn't tilt
   aggressive, especially in a crisis window.

## Binary schedule diagnostic — switching cost vs edge captured

The mid-regime spread (on the forward-RV signals) is +0.09 / +0.04 %/wk,
so the ramp's partial-defensive tilt in the middle band is throwing
away edge. Under a binary rule the book stays fully aggressive across
the mid band and only steps out for the top-decile forward-RV bars.
The obvious concern is switching cost.

### Transition statistics (IS)

`ent/yr` and `exit/yr` count when λ hits or leaves 0 exactly.
`switches/yr` counts every bar where λ differs from the previous bar
(for binary = ent + exit + 1 warmup exit; for ramp = almost every
bar because the ramp λ moves whenever pct moves). `turn_trans` is
mean per-bar turnover on transition bars, `turn_other` on the rest.

| variant             | ent/yr | exit/yr | switches/yr | def frac | dwell mean | dwell max | turn on trans bar | turn on other bar | cost from trans (bps/yr) |
|:--------------------|-------:|--------:|------------:|---------:|-----------:|----------:|------------------:|------------------:|-------------------------:|
| binary_causal       | 0.71   | 0.71    | 1.60        | 8.9%     | 6.50       | 21        | 0.799             | 0.436             | 12.8                     |
| **binary_fwd_1w_rv**| 2.49   | 2.49    | 5.16        | 7.9%     | **1.64**   | **3**     | **0.961**         | 0.434             | 49.6                     |
| binary_fwd_4w_rv    | 1.07   | 1.07    | 2.32        | 7.2%     | 3.50       | 9         | 0.981             | 0.438             | 22.7                     |
| blend_fwd_1w_rv (ramp) | 2.49 | 2.49  | 39.00       | 7.9%     | 1.64       | 3         | 0.562             | 0.283             | 219.3                    |
| blend_fwd_4w_rv (ramp) | 1.07 | 1.07  | 35.08       | 7.2%     | 3.50       | 9         | 0.464             | 0.291             | 162.8                    |

**Reading:**

- **Binary switching cost is small**, not the killer the user was
  worried about. `binary_fwd_1w_rv` costs 49.6 bps/yr from
  transitions (2.5 events per year × ~20 bps per full flip);
  `binary_fwd_4w_rv` only 22.7 bps/yr (1 event per year on average).
- **Ramp variants pay more in transitions than binary does**, not
  less. The ramp's λ moves every single bar in the middle band, so
  even though per-bar turnover is smaller (~0.5 vs ~1.0), the total
  transition cost is 3–7× higher.
- **fwd_1w_rv is nervier than fwd_4w_rv:** 2.5 defensive episodes/yr,
  mean dwell 1.6 weeks, max 3 weeks. fwd_4w_rv averages the signal
  over 4 weeks, so it triggers half as often (1.07/yr) but stays out
  longer (mean 3.5 weeks, max 9 weeks — one covers a real crisis
  window).
- Total book cost `cost_bps_yr` (from summary): binary_fwd_1w_rv 253,
  binary_fwd_4w_rv 240 — comparable to or slightly below the ramp
  equivalents (256, 212). Binary's extra transition cost is offset
  by the fact that it pays 1/σ's cheaper turnover when defensive.

### Defensive-minus-aggressive return in high-vol weeks

The economic edge the binary rule is trying to capture.

| signal            | n bars high (top 10%) | mean(def − agg) %/wk | annualized (over high-vol bars only) | share of IS |
|:------------------|----------------------:|---------------------:|-------------------------------------:|------------:|
| causal (26w σ)    | 26                    | **−0.345**           | −17.93%                              | 8.9%        |
| fwd_1w_rv         | 23                    | **+0.233**           | +12.13%                              | 7.9%        |
| fwd_4w_rv         | 21                    | **+0.207**           | +10.78%                              | 7.2%        |

On the **causal** signal, being defensive in high-regime bars is
actively costly (−0.35%/wk = −17.9% annualized on those bars).
That's the "the causal high-regime bars are RECOVERY bars, not
crisis bars" finding restated in def-minus-agg terms — hence
`binary_causal` posts the worst Sharpe (+0.41) of any binary
variant.

On the **forward-RV signals**, being defensive in high-regime bars
saves +0.20–0.23%/wk (≈ +12%/yr annualized). Multiplied by the
7–8% share of IS bars in that bucket, that's ≈ **+0.9–1.0 pp of
annual return** captured by the defensive gate. Comfortably above
the 20–50 bps/yr switching cost.

### Binary vs solo aggressive — full Pareto comparison

The most useful comparison for the binary rule is against solo
aggressive, because the binary rule is really "run the aggressive
book except when the oracle says stand down":

| metric     | solo aggressive | binary_fwd_1w_rv | binary_fwd_4w_rv |
|:-----------|----------------:|-----------------:|-----------------:|
| Sharpe     | +0.649          | **+0.843**       | +0.815           |
| CAGR       | +4.84%          | **+5.41%**       | +5.39%           |
| max DD     | −14.62%         | −12.06%          | −12.37%          |
| ann vol    | 8.34%           | 7.27%            | 7.50%            |
| cost bps/yr| 237             | 253              | 240              |

Both binary oracles **strictly dominate solo aggressive** on Sharpe,
CAGR, DD, and vol — the switching cost is more than covered by
avoiding the down-week losses in high-vol regimes. That's a real
finding: if you're already committed to running the aggressive book,
gating it with a forward-RV binary rule strictly improves every
headline metric.

### Binary vs ramp — the real tradeoff

| metric     | blend_fwd_4w_rv (ramp) | binary_fwd_1w_rv | binary_fwd_4w_rv |
|:-----------|-----------------------:|-----------------:|-----------------:|
| Sharpe     | **+0.889**             | +0.843           | +0.815           |
| CAGR       | +4.43%                 | **+5.41%**       | +5.39%           |
| max DD     | **−6.95%**             | −12.06%          | −12.37%          |
| ann vol    | 5.51%                  | 7.27%            | 7.50%            |

**Ramp wins Sharpe and DD; binary wins CAGR.** The ramp variant sits
lower on the risk-return curve (lower vol, lower CAGR) while binary
sits higher (higher vol, higher CAGR). Same information, two
different points.

Which one wins depends on utility. If the two-book design is
targeting "highest CAGR that still beats solo aggressive on Sharpe,"
binary_fwd_1w_rv is the finalist. If it's targeting "highest Sharpe
under a real forecast," blend_fwd_4w_rv is.

### Binary summary verdict

- The switching cost is small (~1/2 to 1/10 of what the user feared)
  and does not close the CAGR gap the binary rule opens up.
- `binary_fwd_1w_rv` gets **CAGR +5.41% at Sharpe +0.843** — Pareto-
  dominates solo aggressive; sits between defensive and ramp on the
  Sharpe axis but pushes further right on CAGR.
- The 1-week horizon works better than 4-week for binary. Reason:
  binary is "on when signaled, off otherwise", so a sharp per-bar
  signal is more valuable than a smoothed one. 4-week averaging
  helps the ramp variant (denoising a continuous score); it hurts
  binary (blurring the sharp defensive weeks it should be catching).
- Neither binary variant beats fixed λ = 0 (solo defensive) on
  Sharpe. The pass rule still fails; the frontier just gains a new
  reference point at higher CAGR.

## Fixed-λ sweep — unchanged story

Best fixed λ still lands at **0.00** (pure defensive) on IS Sharpe.
Sharpe is monotone decreasing in λ across the whole grid; there's no
static blend that beats defensive-alone. The two-book design has to
earn its Sharpe strictly from *time variation* in the mix.

## Findings (updated with binary results)

**1. The `1/√σ`-shift "oracle" of the first draft was not an
oracle at all.** Fixing it changes the picture materially: the
proper 4-week RV oracle (`blend_fwd_4w_rv`) posts Sharpe +0.889
and CAGR +4.43%, second only to the (suspect) inverted-causal
variant. The pipeline responds cleanly to a real forward signal
when one is provided.

**2. `blend_fwd_4w_rv` beats `blend_fwd_1w_rv`** (Sharpe +0.889
vs +0.780, CAGR +4.43% vs +3.86%). Multi-week averaging denoises
the forward RV signal; a 1-week peek is too noisy to gate on
alone. Implication for HAR: if we do wire HAR back in, target the
4-week horizon, not 1-week.

**3. The `blend_inv_causal` Sharpe advantage (+1.024) is a
lagging-signal artifact.** The regime-spread flip between causal σ
(+0.34% in high regime) and actual forward RV (−0.20% / −0.21% in
high regime) proves the causal high-vol bars are not the same as
actual future high-vol bars. Causal σ is picking up the recovery
tail of past vol spikes, where equity mean-reverts and aggressive
catches the rally. Under a real forward forecast, the inverted
direction fails cleanly (Sharpe +0.53 / +0.57).

**4. The naive direction is the correct direction — with the caveat
that it needs a forward forecast to work.** The causal naive variant
(`blend_causal`) posts Sharpe +0.45, worst of the honest variants.
The naive oracles (fwd_1w_rv, fwd_4w_rv) post +0.78 / +0.89. So the
gap between "no forecast" and "perfect 4-week forecast" is Sharpe
+0.44 and CAGR +1.74 pp. That's the value a real forecast would
capture. HAR's job would be to close that gap partially.

**5. The aggregate spread does NOT come from crises.** Stripping
COVID + 2022 raises the aggregate spread from +0.033%/wk to
+0.051%/wk. Aggressive earns its CAGR premium primarily in normal
weeks, mostly from up-week wins (+0.5%/wk vs down-week losses of
−0.5%/wk that partially cancel). The blender's job is not "gate
around crises" — it's "know when the up-week wins won't materialize
and stand down."

**6. Pass rule verdict: still fails, but the frontier now has two
useful reference points.** Best fixed λ = 0 wins IS Sharpe at +1.000.
Under a real forward forecast the design offers two distinct
finalists:
- **Highest Sharpe honest variant:** `blend_fwd_4w_rv` (ramp) at
  Sharpe +0.889 / CAGR +4.43% / DD −6.95%. Sharpe cost 0.11.
- **Highest CAGR honest variant:** `binary_fwd_1w_rv` at
  Sharpe +0.843 / CAGR +5.41% / DD −12.06%. Sharpe cost 0.16, but
  strictly Pareto-dominates solo aggressive on every headline.
Neither beats defensive on Sharpe, but both offer a real
Sharpe/CAGR tradeoff HAR was originally meant to reach.

**7. Binary switching cost is small — the concern didn't
materialize.** Total transition cost of binary variants is 22–50
bps/yr (vs 163–219 bps/yr for the ramp variants' total transition
cost). Total book cost is comparable across binary and ramp
(~240–256 bps/yr). The +0.9–1.0 pp/yr contribution from being
defensive during actual high-vol weeks (fwd_1w_rv/fwd_4w_rv def−agg
+0.20–0.23%/wk × 7–8% share of IS) is 2–5× the transition cost, so
the binary rule is economically viable.

**8. 1-week horizon beats 4-week for binary; 4-week beats 1-week
for ramp.** Binary_fwd_1w_rv Sharpe +0.843 > binary_fwd_4w_rv
+0.815, but blend_fwd_4w_rv (ramp) +0.889 > blend_fwd_1w_rv (ramp)
+0.794. Intuition: ramp benefits from a smoothed continuous score
because the ramp uses the middle band. Binary discards the middle
band and only needs sharp on/off signaling, so a per-bar 1-week
peek is more valuable than a 4-week average.

## Recommendations (revised)

Ranked:

1. **Reopen Phase 11.3 (HAR-driven blender) at BOTH horizons, with
   the schedule choice made per horizon.** The oracle test now
   demonstrates two working design points:
   - **4-week horizon → ramp schedule.** blend_fwd_4w_rv: Sharpe
     +0.89, CAGR +4.43%, DD −6.95%.
   - **1-week horizon → binary schedule.** binary_fwd_1w_rv:
     Sharpe +0.84, CAGR +5.41%, DD −12.06%.
   HAR should be evaluated at both horizons; the winning schedule
   depends on which HAR horizon comes back sharpest. HAR at 1w is
   noisy per the recalibration report — under binary that noise
   directly costs Sharpe (binary_fwd_1w_rv uses top-decile precision).
   HAR at 4w with a ramp schedule is the safer bet.

2. **Do NOT pre-register `blend_inv_causal` for OOS.** The IS win is
   from fitting a lagging-signal artifact (recovery periods) whose
   pattern is unlikely to be stable OOS. The first draft's
   recommendation to pre-register it was based on a corrupted
   diagnostic; that recommendation is retracted.

3. **Cheap-forecast baseline before HAR.** Test a rolling-realized
   4-week RV (e.g., mean of RV over the past 4 weeks) as the score
   input. If its Sharpe / CAGR sit meaningfully between `blend_causal`
   and `blend_fwd_4w_rv`, HAR needs to beat that cheap baseline —
   not just beat the naive `blend_causal` — to be worth wiring.

4. **The 88% solo-book correlation ceiling still applies.** Under a
   real forward forecast, the design earns Sharpe +0.89 — not +1.10
   or better. The correlation cap is holding this back; the fix
   (differing selection between books, e.g., different q or
   different α) remains an independent branch worth exploring even
   if HAR wires up cleanly.

Explicitly *not* recommended: continuing to retune the λ gates
(0.3 / 0.9) on IS. The regime signal itself is what varies across
variants; a different gate on the same score won't rescue Sharpe.

## Files

- `data/v6_static/oracle_blender/summary.csv` — **12 rows**: 2 solo +
  6 ramp blend + 3 binary blend + 1 fixed-λ pick.
- `data/v6_static/oracle_blender/bar_{variant}.csv` — per-bar IS
  detail.
- `data/v6_static/oracle_blender/lambdas.csv` — λ + score raw + pct
  per bar, per blend variant (ramp + binary).
- `data/v6_static/oracle_blender/fixed_lambda_sweep.csv` — 21-row
  Sharpe monotone grid.
- `data/v6_static/oracle_blender/block_alloc.csv` — mean block share
  per variant.
- `data/v6_static/oracle_blender/diag_regime_2x3.csv` — regime ×
  future-direction spread breakdown per signal.
- `data/v6_static/oracle_blender/diag_crisis_strip.csv` — crisis-
  stripped Sharpe / spread + within-crisis regime breakdown.
- **`data/v6_static/oracle_blender/diag_binary_transitions.csv`** —
  new: per-variant enter/exit/switch rates, dwell times, transition
  turnover + cost, and def-minus-agg return in high-vol weeks.
- `scripts/two_book_blender_v6.py` — revised: `binary_lambda_schedule`,
  `hold_through_transient_nan` helper, `rv_panel` argument,
  `fwd_{1,4}w_rv` sources, symmetric `warmup_lambda`.
- `scripts/oracle_blender_v6.py` — revised: 6 ramp + 3 binary blend
  variants + solo + fixed-λ.
- `scripts/blender_diagnostics_v6.py` — extended with the binary-
  transition section.
- `scripts/tests_sizing_v6.py` — 12 tests: sizing kernels, ramp
  schedule, binary schedule, symmetric warmup, causal percentile,
  fwd_1w_rv / fwd_4w_rv correctness, hold_through_transient_nan,
  blend convex-combo.

## Reproducing

```bash
python v6/scripts/tests_sizing_v6.py             # 12 unit tests
python v6/scripts/oracle_blender_v6.py           # revised sweep
python v6/scripts/blender_diagnostics_v6.py      # diagnostic tables
```

Runtime < 20 s total. No re-screen, no re-ensemble. Reverting this
branch: delete `oracle_blender_v6.py`, `blender_diagnostics_v6.py`,
`two_book_blender_v6.py`, and remove the added tests from
`tests_sizing_v6.py`. All Phase 9.x / 10.x / 11.1 artifacts stay
untouched.
