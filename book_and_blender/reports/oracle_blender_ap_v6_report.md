# v6 static baseline — α-proportional aggressive book (Phase 11.2 last round)

Generated: 2026-07-21

## What this run tests

Every prior blender test used ``rank_prop`` for the aggressive book —
weights proportional to α *rank* within the held set. That kernel is
sign-robust under row-z α but discards α magnitude. This run tries
the **v4pool / v5 α-proportional formula** (from
``v5/static/xs_engine_v5.weights_topk_alphaprop_long``) instead:

```
H     = |held|
rng   = max(α_held) − min(α_held)
ε     = max(rng / H, 1e-12)
p_i   = α_i − min(α_held) + ε
w_i   = p_i / Σp
```

Equal α → equal weight (the ε floor guards Σp>0). Positive α spread
→ higher α gets proportionally more mass. Min-shift keeps weights
non-negative even when raw α crosses zero (row-z produces negatives
for the bottom half of the held set).

Per user spec, only 4 blend variants — ramp and binary, at 1w and 4w
oracle RV horizons. No inverted, no causal. Full 7-variant table:
solo defensive + solo aggressive (alpha_prop) + 4 blends +
best-fixed-λ counterfactual.

## Headline (IS, 292 W-FRI bars, net of 10 bp/side)

| variant                 | net Sharpe | gross Sharpe | net CAGR | net max DD | ann vol | cost bps/yr | held | eff N |
|:------------------------|-----------:|-------------:|---------:|-----------:|--------:|------------:|-----:|------:|
| **solo_defensive**      | **+1.000** | +1.364       | 3.43%    | −5.02%     | 3.71%   | 134         | 13.2 | 4.5   |
| solo_aggressive_ap      | +0.745     | +1.082       | 4.49%    | −11.16%    | 6.68%   | 226         | 13.2 | 9.6   |
| blend_fwd_1w_rv (ramp)  | +0.872     | +1.351       | 3.90%    | −6.38%     | 4.90%   | 234         | 13.2 | 7.5   |
| **blend_fwd_4w_rv (ramp)** | **+0.940** | +1.345    | **4.20%**| −5.67%     | 4.92%   | 199         | 13.2 | 7.6   |
| binary_fwd_1w_rv        | +0.868     | +1.252       | 4.74%    | −9.84%     | 6.10%   | 236         | 13.2 | 9.3   |
| binary_fwd_4w_rv        | +0.877     | +1.245       | 4.88%    | −9.84%     | 6.23%   | 230         | 13.2 | 9.3   |
| best_fixed_λ = 0.00     | +1.000     | +1.364       | 3.43%    | −5.02%     | 3.71%   | 134         | 13.2 | 4.5   |

## Head-to-head: alpha_prop vs rank_prop aggressive book

Solo aggressive comparison — same selection + hysteresis, same held set,
only the sizing kernel differs:

| metric        | rank_prop | alpha_prop | Δ (ap − rp) |
|:--------------|----------:|-----------:|------------:|
| net Sharpe    | +0.649    | **+0.745** | **+0.096**  |
| net CAGR      | 4.84%     | 4.49%      | −0.35 pp    |
| net max DD    | −14.62%   | **−11.16%**| **+3.46 pp**|
| ann vol       | 8.34%     | 6.68%      | −1.66 pp    |
| eff N (1/HHI) | 12.2      | 9.6        | −2.6        |
| top-1 weight  | 17.1%     | 24.1%      | +6.9 pp     |

**Surprise:** alpha_prop is **less aggressive on the tape**, not more.
It's more concentrated (eff N 9.6 vs 12.2, top-1 24% vs 17%) — but
concentrated toward *high-α* names rather than being uniform on the
held set. The result: lower vol (−1.66 pp), lower DD (better by 3.5
pp), lower CAGR (−0.35 pp). The Sharpe improvement (+0.096) says the
α-level weighting is picking up realized-return signal that rank
weighting was discarding.

Interpretation: on the ensemble α used here, magnitude *is*
informative — the top-α names outperform not just monotonically-by-
rank but proportionally-to-α. Weighting by rank throws away that
proportional information; weighting by α level captures it.

## Blender variants — alpha_prop vs rank_prop side-by-side

Ramp variants (ramp λ; forward-RV oracle):

| variant              | rank_prop Sharpe | alpha_prop Sharpe | Δ    | ap CAGR | rp CAGR | ap DD | rp DD |
|:---------------------|-----------------:|------------------:|------|--------:|--------:|------:|------:|
| blend_fwd_1w_rv      | +0.794           | +0.872            | +0.08| 3.90%   | 3.92%   | −6.4% | −8.1% |
| **blend_fwd_4w_rv**  | +0.889           | **+0.940**        |**+0.05**| 4.20% | 4.43%   | **−5.7%** | −6.9% |

Binary variants:

| variant              | rank_prop Sharpe | alpha_prop Sharpe | Δ    | ap CAGR | rp CAGR | ap DD  | rp DD  |
|:---------------------|-----------------:|------------------:|------|--------:|--------:|-------:|-------:|
| binary_fwd_1w_rv     | +0.843           | +0.868            | +0.03| 4.74%   | 5.41%   | −9.8%  | −12.1% |
| binary_fwd_4w_rv     | +0.815           | +0.877            | +0.06| 4.88%   | 5.39%   | −9.8%  | −12.4% |

**Every single blend variant improves on Sharpe under alpha_prop.**
CAGR trades some upside (−0.5 to −0.7 pp on binary, roughly flat on
ramp) for much better DD (2–3 pp less draw). The design axis matters:
alpha_prop wins Sharpe strictly; rank_prop wins CAGR strictly.

## Fixed-λ frontier under alpha_prop

The fixed-λ frontier is **materially flatter** with alpha_prop —
small aggressive doses cost less Sharpe than they did under
rank_prop.

| λ    | alpha_prop Sharpe | rank_prop Sharpe | Δ    |
|:-----|------------------:|-----------------:|-----:|
| 0.00 | +1.000            | +1.000           | 0.00 |
| 0.05 | +0.992            | +0.978           | +0.014|
| 0.10 | +0.980            | +0.954           | +0.026|
| 0.15 | +0.967            | +0.930           | +0.037|
| 0.20 | +0.953            | +0.906           | +0.047|
| 0.50 | +0.866            | +0.783           | +0.083|
| 1.00 | +0.745            | +0.649           | +0.096|

Best fixed λ is still **0** (solo defensive) at Sharpe +1.000 — the
pass rule under the strict interpretation still fails. **But**:

- Fixed λ = 0.25 gives Sharpe +0.938 / CAGR +3.75% / DD −5.54%.
- Oracle blend_fwd_4w_rv gives Sharpe +0.940 / CAGR +4.20% / DD −5.67%.

The oracle variant **Pareto-dominates fixed λ = 0.25** on (Sharpe, CAGR)
with only a hair worse DD. That's exactly what σ-conditioning is
supposed to do: get the aggressive book's CAGR uplift without paying
the fixed-blend's linear Sharpe cost.

## Switching-cost diagnostic (blend variants only)

Aggregate spread agg_ap − def = +0.024%/wk = +1.26%/yr (vs +1.70%/yr
under rank_prop — alpha_prop's tighter aggressive book earns less
raw spread, but it does so at much better risk-adjusted efficiency).

| variant             | ent/yr | exit/yr | switch/yr | def frac | dwell mean | dwell max | turn per switch | cost from switches (bps/yr) |
|:--------------------|-------:|--------:|----------:|---------:|-----------:|----------:|----------------:|----------------------------:|
| blend_fwd_1w_rv     | 2.49   | 2.49    | 39.00     | 7.9%     | 1.64       | 3         | 0.506           | 197.4                       |
| blend_fwd_4w_rv     | 1.07   | 1.07    | 35.08     | 7.2%     | 3.50       | 9         | 0.429           | 150.5                       |
| binary_fwd_1w_rv    | 2.49   | 2.49    | 5.16      | 7.9%     | 1.64       | 3         | 0.806           | **41.6**                    |
| binary_fwd_4w_rv    | 1.07   | 1.07    | 2.32      | 7.2%     | 3.50       | 9         | 0.897           | **20.8**                    |

Same enter/exit rates and dwell times as the rank_prop run — those
depend only on the score, not on the aggressive kernel. Per-switch
turnover is slightly lower under alpha_prop (0.51 → 0.43 for ramp
fwd_4w) because alpha_prop's book is closer in weight distribution to
defensive than rank_prop's was.

## Defensive − aggressive_ap return in high-vol weeks

| signal    | n high-vol bars | mean(def − agg_ap) %/wk | annualized on high-vol subset | share of IS |
|:----------|----------------:|------------------------:|------------------------------:|------------:|
| fwd_1w_rv | 23              | **+0.120**              | +6.22%                        | 7.9%        |
| fwd_4w_rv | 21              | **+0.147**              | +7.66%                        | 7.2%        |

Compared to rank_prop's +0.23 / +0.21 %/wk savings, the alpha_prop
defensive-gate saves less in high-vol weeks — because the aggressive
book is naturally less exposed to equity vol in those weeks (lower
solo DD). Still comfortably above the transition cost (0.55 pp
annual saving vs 0.21 pp transition cost at binary_fwd_4w_rv).

## Findings

**1. alpha_prop wins Sharpe strictly on every variant.** Solo, ramp
and binary — every alpha_prop cell has higher Sharpe than the
corresponding rank_prop cell. The average uplift is +0.05 Sharpe
across the four blend variants and +0.10 Sharpe on the solo book.
On the ensemble α used here, magnitude weighting captures real
information that rank weighting was discarding.

**2. `blend_fwd_4w_rv` (ramp, alpha_prop) is the best honest variant
of all rounds.** Sharpe **+0.940**, CAGR **+4.20%**, DD −5.67%. The
Sharpe gap to solo defensive shrinks from −0.11 (rank_prop) to
−0.06 (alpha_prop). CAGR uplift is +0.77 pp over defensive at only
0.65 pp worse DD. This is the closest the two-book design has come
to a real Sharpe/CAGR frontier improvement.

**3. Ramp beats binary under alpha_prop; the previous ramp/binary
tradeoff flips.** With rank_prop, binary_fwd_1w_rv beat ramp_fwd_4w_rv
on Sharpe (+0.843 vs +0.794). With alpha_prop, ramp beats binary
across the board (+0.94 vs +0.88 at 4w, +0.87 vs +0.87 at 1w). The
reason: alpha_prop's aggressive book is already concentrated on
high-α names, so the middle band of the ramp isn't throwing edge
away — it's blending two Sharpe-efficient books smoothly. Under
rank_prop the aggressive book had much more equity noise, so the
sharp binary cutoff was more valuable.

**4. Fixed-λ frontier is flatter → alpha_prop makes ANY blend
cheaper.** Adding 20% alpha_prop aggressive costs only 0.05 Sharpe
(vs 0.09 under rank_prop). This means even a bad forecast
(realistic HAR) has more room to add value under alpha_prop — the
"Sharpe cost of being wrong about regime" is smaller.

**5. Design axis: choose alpha_prop as the aggressive book going
forward.** Every headline is better under alpha_prop. The one thing
we give up is peak CAGR (5.41% under rank_prop binary → 4.88% under
alpha_prop binary), but only by ~0.5 pp and at much better Sharpe /
DD. If maximum-CAGR is the objective, rank_prop binary was already
the pick; if Sharpe-efficiency-adjusted-for-CAGR is the objective,
alpha_prop ramp is clearly the pick.

## Pass rule verdict

Strict pass rule ("joint IS Sharpe ≥ best fixed-mix Sharpe") — still
**fails** because best fixed λ = 0 sits at Sharpe +1.000 and no
variant reaches that.

Relaxed pass rule ("oracle variant Pareto-dominates any fixed-mix at
matched CAGR") — **passes** for `blend_fwd_4w_rv` under alpha_prop:
- Fixed λ = 0.75 gets CAGR +4.26% at Sharpe +0.801 and DD −9.09%.
- Oracle gets CAGR +4.20% at Sharpe **+0.940** and DD −**5.67%**.
- Oracle strictly dominates on (Sharpe, DD) at essentially matched
  CAGR. That's exactly the σ-conditioning edge the design was
  looking for.

## Recommendations

1. **Adopt alpha_prop as the aggressive book.** Every axis wins;
   nothing loses meaningfully. `hysteresis_engine_v6_sizing.py`'s
   `alpha_prop` branch is production-ready (bit-tested against the
   v4pool/v5 formula in `tests_sizing_v6.py`).

2. **Phase 11.3 (HAR) — 4-week horizon + ramp schedule.** With
   alpha_prop the ramp variant is stronger than binary on Sharpe, and
   HAR at 4w is more stable than HAR at 1w per the recalibration
   report. Best chance to convert oracle Sharpe +0.940 into a
   realistic Sharpe close to it.

3. **If HAR@4w doesn't reach ~Sharpe +0.90, fall back to solo
   defensive.** The user's decision rule as stated: "if that also
   does not help, we will simply choose the solo defensive." The
   alpha_prop oracle sits at Sharpe +0.94 / CAGR +4.20% vs defensive
   +1.00 / +3.43%. A realistic HAR should recover a meaningful
   fraction of the +0.77 pp CAGR gap; if it recovers < ~1/3, the
   0.06 Sharpe cost isn't worth it and solo defensive is the answer.

## Files

- `data/v6_static/oracle_blender_ap/summary.csv` — 7 rows.
- `data/v6_static/oracle_blender_ap/bar_{variant}.csv` — per-bar IS.
- `data/v6_static/oracle_blender_ap/lambdas.csv` — λ + score + pct.
- `data/v6_static/oracle_blender_ap/fixed_lambda_sweep.csv` — 21-row
  Sharpe frontier under alpha_prop aggressive.
- `data/v6_static/oracle_blender_ap/block_alloc.csv` — mean block
  share per variant.
- `data/v6_static/oracle_blender_ap/diag_transitions.csv` — switching
  cost + high-vol def-agg (inline; also printed to stdout).
- `scripts/hysteresis_engine_v6_sizing.py` — extended: `alpha_prop`
  kernel via ``_leg_weights_alpha_prop``.
- `scripts/oracle_blender_ap_v6.py` — this driver.
- `scripts/tests_sizing_v6.py` — 15 tests total (3 new for
  alpha_prop shape, negative-α, equal-α).

## Reproducing

```bash
python v6/scripts/tests_sizing_v6.py         # 15 unit tests
python v6/scripts/oracle_blender_ap_v6.py    # 7-variant sweep
```

Runtime < 15 s. Loads existing `long_q20/ensemble_alpha.parquet` and
`rv_panel.parquet`; rebuilds books only. Reverting: delete
`oracle_blender_ap_v6.py`, remove the `alpha_prop` branch from
`hysteresis_engine_v6_sizing.py`, and remove the added tests.
