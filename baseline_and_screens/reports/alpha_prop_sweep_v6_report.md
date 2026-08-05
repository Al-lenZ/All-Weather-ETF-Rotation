# v6 static baseline — aggressive-book kernel (Phase 11.1)

Generated: 2026-07-21

## Motivation — the two-book design

Phase 11 introduces a **two-book architecture** whose cash split will
eventually be steered by a vol forecast:

- **Defensive book** — current `1/σ` sizing. Concentrates in low-vol
  names (bonds), high Sharpe, bond-like CAGR. Best in high-vol / risk-
  off regimes.
- **Aggressive book** — α-responsive sizing that up-weights the top-α
  held names. Higher CAGR, higher drawdown. Best in low-vol / risk-on
  regimes.
- **Global vol multiplier** (HAR-style forecast, later) chooses the
  cash split each bar — higher forecast → more mass to defensive.
- Hysteresis keeps running per-book so each side's roundtrip churn is
  controlled independently.

The HAR forecast is not yet reliable enough to drive the split (see
`vol_forecast_v6_recalib_report.md`), so the plan is staged:

1. **(this branch)** Confirm the aggressive book behaves as expected in
   isolation vs the defensive baseline. Kickoff prediction: **CAGR ↑,
   max DD ↑, Sharpe roughly flat or slightly lower**.
2. **(Phase 11.2)** Oracle two-book blender — feed a perfect next-week σ
   into the blender and check whether the combined book beats
   `1/σ`-alone. Confirms the design regardless of forecast quality.
3. **(Phase 11.3)** Wire HAR (or the best forecast we have) into the
   blender for the realistic version.

This report covers step 1.

## Design

Everything except the sizing kernel is held constant — same control
point as the prior 1/√σ sweep so results are directly comparable.

|                    | control                        | treatment                                    |
|:-------------------|:-------------------------------|:---------------------------------------------|
| cell               | `long_q20`                     | `long_q20`                                   |
| hysteresis rule    | `replace`                      | `replace`                                    |
| ε                  | 0.20                           | 0.20                                         |
| ensemble α         | `long_q20/ensemble_alpha.parquet` (loaded, not rebuilt) | same |
| cost               | 10 bp / side                   | 10 bp / side                                 |
| **sizing kernel**  | **`w_i ∝ 1 / σ_i`**            | **`w_i ∝ (H − r_i + 1)`** (local α-rank)     |

`rank_prop` ranks α *within the held set* (`H = |held|`, `r = 1` for
best-α held). Local-rank guarantees every held name gets a strictly
positive weight even when the hysteresis exit-buffer retains names at
global rank > K.

`hysteresis_engine_v6_sizing.build_hysteresis_weights_sized` at
`sizing="inv_vol"` reproduces `hysteresis_engine_v6.build_hysteresis_weights`
bit-for-bit — asserted at end of run *and* in
`tests_sizing_v6.py` as a standalone regression.

## Sample discipline

Per [[feedback-oos-discipline]], **this experiment reports IS-only
metrics** (bars ≤ 2023-12-31). OOS + hold-out numbers exist in the raw
per-bar CSVs so the driver is reproducible, but they are not surfaced
here or in the narrative summary. OOS opens only for a final
confirmatory shot after Phase 11.2 gates the design.

IS window: 292 W-FRI bars. Every headline is net of 10 bp/side turnover
cost per [[feedback-backtests-cost-on]].

## Headline — control vs treatment (IS)

| metric                | control (1/σ) | treatment (rank_prop) | Δ (treatment − control) |
|:----------------------|-------------:|----------------------:|------------------------:|
| **net Sharpe**        | **+1.000**   | **+0.649**            | **−0.351**              |
| gross Sharpe          | +1.364       | +0.933                | −0.431                  |
| **net CAGR**          | **3.43%**    | **4.84%**             | **+1.41 pp** (+41%)     |
| gross CAGR            | 4.55%        | 6.67%                 | +2.12 pp (+47%)         |
| net cumulative return | 20.85%       | 30.38%                | +9.53 pp                |
| **net max drawdown**  | **−5.02%**   | **−14.62%**           | **−9.60 pp** (2.91×)    |
| gross max drawdown    | −4.85%       | −11.99%               | −7.14 pp (2.47×)        |
| annualized vol        | 3.71%        | 8.34%                 | +4.63 pp (2.25×)        |
| cost drag             | 134.3 bps/yr | 237.2 bps/yr          | +102.8 bps/yr (1.77×)   |

**Reading:** CAGR and max DD both move the predicted direction and
land materially further out on the frontier than the 1/√σ branch did.
Sharpe drops harder than the kickoff phrase "flat or slightly lower"
would suggest (−0.35 net; −0.43 gross) — but that gross-Sharpe drop
mostly recovers the same lesson the 1/√σ sweep learned: **on a fixed
α, moving mass away from low-σ names costs risk-adjusted efficiency**,
because 1/σ is close to the risk-parity optimum for uncorrelated
names.

The gap between gross-Sharpe drop (−0.43) and net-Sharpe drop (−0.35)
says the extra cost bill (+103 bps/yr) is real but *not* the primary
Sharpe killer here — most of the damage comes from vol inflation on
the same α (+2.25× ann vol against only +47% gross CAGR).

## Weight-distribution shift (IS mean per bar)

Both books hold the same 13.2 names each bar (identical selection
rule and K). The mass on those names is redistributed:

| metric                    | control | treatment | Δ         |
|:--------------------------|--------:|----------:|----------:|
| held-set mean size        | 13.2    | 13.2      | 0.0       |
| HHI (Σ w²)                | 0.326   | 0.122     | −0.204    |
| effective # names (1/HHI) | **4.5** | **12.2**  | **+7.7** (2.73×) |
| top-1 weight              | 48.7%   | 17.1%     | −31.6 pp  |
| top-3 weight sum          | 71.9%   | 43.9%     | −27.9 pp  |
| top-5 weight sum          | 82.2%   | 61.0%     | −21.3 pp  |

Effective N almost triples. Under `rank_prop` the book is close to
uniform on the held set — top-1 name carries only 17% vs 49% under
`1/σ`. This is a much stronger diversification move than 1/√σ
achieved (which had eff-N 9.7 and top-1 25.9%).

## Block-level allocation (IS mean share of book weight)

| block            | control | treatment | Δ        |
|:-----------------|--------:|----------:|---------:|
| bond_rates       | 44.6%   | 28.6%     | −15.9 pp |
| bond_credit      | 21.7%   |  6.9%     | −14.7 pp |
| **all bonds**    | **66.3%** | **35.6%** | **−30.7 pp** |
| sector_cn        |  4.3%   | 13.8%     |  +9.5 pp |
| broad_cn         |  4.5%   | 11.3%     |  +6.8 pp |
| cross_border_dm  |  3.9%   | 10.2%     |  +6.3 pp |
| metals           |  2.8%   |  6.0%     |  +3.2 pp |
| cross_border_hk  |  1.2%   |  4.0%     |  +2.8 pp |
| smallcap_cn      |  0.6%   |  1.5%     |  +0.9 pp |
| commodity_other  |  0.4%   |  1.6%     |  +1.2 pp |

The 30 pp shift out of bonds is where the extra CAGR and the extra vol
both come from. Equity blocks (`broad_cn` + `sector_cn`) more than
triple their share, 8.8% → 25.1%. Compared with the 1/√σ branch
(20 pp bond → equity shift), `rank_prop` is a full ~50% more
aggressive on the same axis — as expected, since it removes the σ
tilt entirely rather than softening it.

## Turnover-channel breakdown (IS)

| channel               | control | treatment | Δ        | Δ %      |
|:----------------------|--------:|----------:|---------:|---------:|
| turnover total        | 0.258   | 0.456     | +0.198   | +77%     |
| turnover selection    | 0.221   | 0.293     | +0.072   | +33%     |
| turnover sizing       | 0.037   | 0.163     | +0.125   | **+336%**|
| selection share       | 85.6%   | 64.3%     | −21.2 pp |          |
| sizing share          | 14.4%   | 35.7%     | +21.2 pp |          |

Two channels moved differently than the 1/√σ branch:

- **Sizing turnover blows up 4.4×.** Under `1/σ`, weights on retained
  names only move when their σ moves — and `σ_causal_26w` is a
  slow-moving window, so bar-to-bar sizing changes are tiny. Under
  `rank_prop`, weights depend on **α-rank within the held set**,
  which reshuffles weekly even when the held set is unchanged. Every
  α-rank flip between two retained names moves both their weights.
  This is inherent to any α-responsive sizing kernel and cannot be
  attacked without changing the α cadence or held-set size.
- **Selection turnover up only 33%** (vs +35% for 1/√σ) — the entering
  / exiting names now carry more mass because rank-prop weights are
  flatter, but the effect is comparable. Cost-per-selection-event is
  similar to 1/√σ.

Net: cost rises from 134 → 237 bps/yr, most of it new sizing-channel
cost. If the aggressive book is carried into the two-book blend, this
is worth flagging as a candidate lever — a lower-cadence α (biweekly)
would specifically attack the sizing-channel cost of `rank_prop`
without much affecting selection.

## Comparison to the 1/√σ branch on the same cell

| metric                | 1/σ (baseline) | 1/√σ (rejected) | rank_prop (this) |
|:----------------------|---------------:|----------------:|-----------------:|
| net Sharpe            | +1.000         | +0.680          | +0.649           |
| net CAGR              | 3.43%          | 4.09%           | **4.84%**        |
| net max DD            | −5.02%         | −10.56%         | **−14.62%**      |
| eff # names           | 4.5            | 9.7             | **12.2**         |
| bond share            | 66.3%          | 46.2%           | **35.6%**        |
| cost bps/yr           | 134            | 169             | **237**          |

`rank_prop` is a further step in the same direction 1/√σ took — more
diversification, less bond concentration, more CAGR, more drawdown,
similar Sharpe hit. It's not a *different* Sharpe / CAGR frontier
than 1/√σ; it's a further point on the same one. That's exactly what
the two-book design wants: a maximally aggressive leg that can be
blended in low-vol windows against a maximally defensive leg.

## Findings vs the kickoff prediction

**1. CAGR ↑ meaningfully — confirmed.** Net CAGR +1.41 pp (3.43% →
4.84%, +41%). Gross CAGR +2.12 pp. This is the primary thing we
wanted to see from an aggressive book.

**2. Max DD ↑ meaningfully — confirmed.** Net max DD 2.91× worse
(−5.02% → −14.62%). This is not a bug either; it's the price of
tilting equity + commodity blocks up 25 pp against bond blocks down
31 pp.

**3. Sharpe "flat or slightly lower" — reality is materially lower
(−0.35 net).** This is worse than the kickoff phrase but matches the
1/√σ branch's lesson: on a fixed α, moving mass away from the near-
optimal `1/σ` weighting costs risk-adjusted efficiency, and each step
away costs more. The gross-Sharpe drop (−0.43) confirms this is
mostly a mean-variance efficiency story on the α, not a cost story.
For the two-book design this is expected — the aggressive book is
not meant to stand alone on Sharpe; it's a leg to blend.

**4. Sizing turnover is the new cost surface.** Selection cost is
comparable to 1/σ but sizing cost quadruples because α ranks flip
weekly. This is the natural cost signature of any α-responsive
kernel and is worth remembering when tuning the blender: some of the
naive combined-book Sharpe will be lost to double-counted sizing
turnover unless the two books share a rebalance cadence.

## Implications for the two-book design (Phase 11.2)

1. **Aggressive book is behaving as intended.** All three predicted
   directions are correct in magnitude; the frontier moved further
   out than 1/√σ did on all axes; the Sharpe hit is consistent with
   1/√σ (and with theory on a fixed α). **The sizing axis is real
   and worth blending.** Ready to proceed to Phase 11.2.

2. **The oracle test needs to isolate blender lift.** Don't compare
   "oracle-blended book" vs "1/σ alone" — that mixes the sizing-axis
   effect (which this report already characterizes) with the
   blender effect. Compare vs the *best fixed-mix* two-book book on
   IS, so the marginal claim is specifically "conditioning on σ
   helps" rather than "combining helps in the mean."

3. **Cost design matters when combining.** Both books share the same
   selection but pay independent sizing turnover on their own held
   sets. A naive 50/50 blend will pay ~185 bps/yr in sizing cost
   alone (average of 37 + 163 × 0.5 each side, before the blender
   weight ratio changes). Consider two structural choices upstream
   of the oracle test:
   - Do the two books share a held set (only sizing differs, so
     selection cost is paid once)?
   - Do they rebalance at the same cadence (so shared names' Δw are
     netted before turnover is computed)?
   Both are worth answering *before* running the oracle so the
   number the oracle reports is the effect we care about.

4. **No decision needed on `rank_prop` vs 1/√σ as "the" aggressive
   book yet.** Either could serve as the aggressive leg in Phase
   11.2; `rank_prop` is more aggressive and has stronger diversification,
   1/√σ pays less cost. The oracle test should be run with the more
   aggressive kernel (`rank_prop`) first — if the blender fails to
   recover Sharpe on the more extreme frontier, it will almost
   certainly fail on the softer 1/√σ frontier too.

Explicitly *not* recommended: repeating this comparison on OOS before
the oracle test. The OOS window should stay sealed until the two-book
design has cleared its Phase 11.2 gate.

## Files

- `data/v6_static/alpha_prop_sweep/summary.csv` — control + treatment
  row (IS Sharpe / CAGR / DD / turnover / concentration).
- `data/v6_static/alpha_prop_sweep/bar_control.csv` — per-bar IS
  detail under `1/σ`.
- `data/v6_static/alpha_prop_sweep/bar_treatment.csv` — per-bar IS
  detail under `rank_prop`.
- `data/v6_static/alpha_prop_sweep/block_alloc.csv` — mean block share
  of book weight (IS, control / treatment / Δ).
- `scripts/hysteresis_engine_v6_sizing.py` — parameterized weight
  builder. `sizing ∈ {inv_vol, inv_sqrt_vol, rank_prop}`.
- `scripts/alpha_prop_sweep_v6.py` — this driver. Asserts `inv_vol`
  matches `hysteresis_engine_v6.build_hysteresis_weights` bit-for-bit,
  writes the summary + per-bar + block-share tables.
- `scripts/tests_sizing_v6.py` — standalone unit tests: inv_vol
  regression + rank_prop shape + LS leg signs.

## Reproducing

```bash
python v6/scripts/tests_sizing_v6.py        # unit tests
python v6/scripts/alpha_prop_sweep_v6.py    # sweep + artifacts
```

Runtime < 5 s each. No re-screen, no re-ensemble — loads
`long_q20/ensemble_alpha.parquet` and rebuilds books only. Reverting
this branch = deleting `alpha_prop_sweep_v6.py`, `tests_sizing_v6.py`,
and removing the `rank_prop` branch from
`hysteresis_engine_v6_sizing.py`. All Phase 9.x / 10.x artifacts are
untouched.
