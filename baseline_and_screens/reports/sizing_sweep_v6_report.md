# v6 static baseline — sizing-kernel branch (Phase 10.1)

Generated: 2026-07-21

## Motivation

The Phase 9.2 hysteresis picks are Sharpe-optimal but weight-heavy on
the lowest-vol names — bonds. On the `long_q20 replace ε=0.20` cell
(the reference control point for this experiment branch), the 1/σ
kernel concentrates ~66% of the book in `bond_rates` + `bond_credit`
and the effective number of names is ~4.5 out of 13.2 held. Net IS
CAGR sits at 3.4%, which is bond-like.

Softening the sizing kernel from `1/σ` to `1/√σ` should flatten the
weight distribution: bond names retain over-weights but higher-vol
equity names get more mass. Expected direction (as stated at kickoff):

- Sharpe roughly flat, likely not higher.
- CAGR up.
- Max drawdown up.

## Design

Everything except the sizing kernel is held constant.

|                    | control                        | treatment                        |
|:-------------------|:-------------------------------|:---------------------------------|
| cell               | `long_q20`                     | `long_q20`                       |
| hysteresis rule    | `replace`                      | `replace`                        |
| ε                  | 0.20                           | 0.20                             |
| ensemble α         | `long_q20/ensemble_alpha.parquet` (loaded, not rebuilt) | same |
| cost               | 10 bp / side                   | 10 bp / side                     |
| **sizing kernel**  | **`w_i ∝ 1 / σ_i`**            | **`w_i ∝ 1 / √σ_i`**             |

`hysteresis_engine_v6_sizing.build_hysteresis_weights_sized` at
`sizing="inv_vol"` reproduces `hysteresis_engine_v6.build_hysteresis_weights`
bit-for-bit at every ε — asserted at end of run, so no silent path
divergence.

## Sample discipline

Per [[project_oos_discipline]], **this experiment reports IS-only
metrics** (bars ≤ 2023-12-31). OOS + hold-out numbers exist in the raw
per-bar CSVs so the driver is reproducible, but they are not surfaced
here or in the narrative summary. OOS numbers will be opened later
only for final confirmatory shots on a chosen sizing scheme.

IS window: 292 W-FRI bars.

## Headline — control vs treatment (IS)

| metric                | control (1/σ) | treatment (1/√σ) | Δ (treatment − control) |
|:----------------------|-------------:|-----------------:|------------------------:|
| **net Sharpe**        | **+1.000**   | **+0.680**       | **−0.320**              |
| gross Sharpe          | +1.364       | +0.936           | −0.428                  |
| net CAGR              | 3.43%        | **4.09%**        | **+0.66 pp** (+19%)     |
| gross CAGR            | 4.55%        | 5.45%            | +0.90 pp (+20%)         |
| net cumulative return | 20.85%       | 25.25%           | +4.40 pp                |
| **net max drawdown**  | **−5.02%**   | **−10.56%**      | **−5.55 pp** (2.1×)     |
| gross max drawdown    | −4.85%       | −8.71%           | −3.86 pp                |
| annualized vol        | 3.71%        | 6.61%            | +2.90 pp (1.78×)        |
| cost drag             | 134.3 bps/yr | 168.9 bps/yr     | +34.6 bps/yr            |

**Reading:** CAGR direction was as predicted (+0.66 pp net) and max
drawdown blows out (2.1× larger). But Sharpe does not stay flat — it
drops materially, from +1.00 to +0.68 net (−0.32) and from +1.36 to
+0.94 gross (−0.43). Vol rises 1.78× while return only rises 1.19×,
so the risk-adjusted picture is worse on both a gross and net basis.
The gross Sharpe drop is the key signal: **the α itself is being used
less efficiently**, not just costed more, when the kernel softens.

Interestingly the Sharpe *drag from cost* is smaller under the
treatment (−0.256 gross → net) than under the control (−0.364) —
because higher vol absorbs the higher cost bill on Sharpe terms. So
the cost delta is not what kills risk-adjusted performance; the vol
inflation on top of a static α does.

## Weight-distribution shift (IS mean per bar)

Both books hold ~13.2 names each bar (identical selection rule and K).
The mass allocated to those names changes:

| metric                    | control | treatment | Δ         |
|:--------------------------|--------:|----------:|----------:|
| held-set mean size        | 13.2    | 13.2      | 0.0       |
| HHI (Σ w²)                | 0.326   | 0.143     | −0.183    |
| effective # names (1/HHI) | **4.5** | **9.7**   | **+5.2** (2.15×) |
| top-1 weight              | 48.7%   | 25.9%     | −22.8 pp  |
| top-3 weight sum          | 71.9%   | 49.7%     | −22.2 pp  |
| top-5 weight sum          | 82.2%   | 64.8%     | −17.4 pp  |

The book more than doubles in *effective* diversity even though the
*nominal* held count is unchanged. Top-1 weight halves. Top-5 goes
from 82% of book (essentially all mass on the same handful of low-vol
names each bar) to 65%.

## Block-level allocation (IS mean share of book weight)

| block            | control | treatment | Δ         |
|:-----------------|--------:|----------:|----------:|
| bond_rates       | 44.6%   | 33.9%     | −10.7 pp  |
| bond_credit      | 21.7%   | 12.3%     |  −9.4 pp  |
| **all bonds**    | **66.3%** | **46.2%** | **−20.1 pp** |
| sector_cn        |  4.3%   | 10.9%     |  +6.6 pp  |
| broad_cn         |  4.5%   |  9.4%     |  +4.9 pp  |
| cross_border_dm  |  3.9%   |  7.5%     |  +3.7 pp  |
| metals           |  2.8%   |  4.7%     |  +1.9 pp  |
| cross_border_hk  |  1.2%   |  3.1%     |  +1.9 pp  |
| smallcap_cn      |  0.6%   |  1.3%     |  +0.7 pp  |
| commodity_other  |  0.4%   |  0.8%     |  +0.4 pp  |

The 20 pp shift out of bonds is where the extra CAGR and the extra vol
both come from. Equity blocks (`broad_cn` + `sector_cn`) more than
double their share from 8.8% → 20.3%.

## Turnover-channel breakdown (IS)

| channel               | control | treatment | Δ        | Δ %      |
|:----------------------|--------:|----------:|---------:|---------:|
| turnover total        | 0.258   | 0.325     | +0.066   | +26%     |
| turnover selection    | 0.221   | 0.299     | +0.078   | +35%     |
| turnover sizing       | 0.037   | 0.026     | −0.011   | −30%     |
| selection share       | 85.6%   | 92.1%     | +6.6 pp  |          |
| sizing share          | 14.4%   |  7.9%     | −6.6 pp  |          |

Two mechanical effects moving in opposite directions:

- **Selection turnover ↑ (+35%).** The set of names entering / exiting
  is identical (same ranks, same ε, same rule) — but each entry / exit
  is now larger in |w| because the entering / exiting name typically
  sits closer to the middle of the vol distribution and picks up more
  mass under the flatter √σ kernel.
- **Sizing turnover ↓ (−30%).** On *retained* names, `1/√σ` responds
  less to changes in σ than `1/σ` does (dw/dσ ~ σ⁻³ᐟ² · ½ vs σ⁻²), so
  the bar-to-bar renormalization on the held set moves less.

Net effect: total turnover is up ~26%, and cost rises from 134 bps/yr
to 169 bps/yr on the IS window. This partially explains but does not
dominate the Sharpe deterioration (see the gross Sharpe drop, which
has no cost component and is still −0.428).

## Findings

**1. Directionally on the mark for CAGR and max DD; wrong on Sharpe
sign.** The kickoff guess had Sharpe "roughly flat, likely not higher"
and CAGR / DD both up. Reality: Sharpe drops meaningfully (−0.32 net,
−0.43 gross), while CAGR and DD move as expected. So the risk-return
frontier is worse, not equivalent, under 1/√σ at this ε and cell.

**2. Gross Sharpe drop rules out "it's just a cost story."** If the
issue were only extra selection cost, gross Sharpe would be flat and
the drop would show up entirely in the (gross − net) gap. Instead
gross Sharpe drops by more (−0.43) than net (−0.32). Softening the
kernel gives the same-α book worse mean-variance efficiency — you buy
more variance per unit of α by tilting away from the near-optimal
1/σ weighting (with equal α and uncorrelated names, 1/σ is close to
the risk-parity solution).

**3. The book is 2× more diversified but that's not free.** Effective
N goes from 4.5 → 9.7, top-1 weight halves, and bond share drops 20 pp.
Concentration was doing real work on the Sharpe side.

**4. Sizing turnover falls but selection turnover rises more.** The
1/√σ kernel is more forgiving to σ drift on retained names but pays
for it every time a name enters or exits, because entries / exits now
carry larger |w|. Net turnover is up ~26%. Any downstream cost-reduction
work (e.g., stacking with cadence reduction) will benefit slightly on
the sizing channel but has to work harder on selection.

**5. This is a "trade risk-adjusted return for absolute return"
change, not a "free CAGR" change.** Under this cell:
   - Net CAGR: +0.66 pp (3.43% → 4.09%)
   - Net max DD: −5.55 pp worse (−5.02% → −10.56%)
   - Net Sharpe: −0.32
   If the objective is absolute CAGR with a higher tolerance for
   drawdown, the treatment wins; on any risk-adjusted headline it loses.

## Implications for next work in this branch

Ranked:

1. **Do not adopt `1/√σ` as the default kernel on `long_q20 replace
   ε=0.2`.** The Sharpe drop is too large for the CAGR pickup, and the
   max DD doubles.

2. **The concentration itself is the leverage point.** The Sharpe gap
   is not primarily a cost story — it's a mean-variance efficiency
   story on top of a fixed α. Later experiments in this branch that
   want to preserve Sharpe while lifting CAGR should target the α or
   the *selection* rule, not just the sizing kernel — or blend
   sizing with a concentration cap (e.g., `1/σ` capped at 15% per name,
   see recommendation 4).

3. **Try `1/σ^β` with β ∈ (0, 1) as an interpolator.** β=1 is the
   control, β=0.5 is this treatment. Sharpe / CAGR / DD probably move
   monotonically with β. A single β sweep on the same cell would map
   the frontier and expose whether there is a sweet spot near, e.g.,
   β=0.75 that keeps Sharpe within ~0.05 of control while capturing
   half the CAGR uplift.

4. **Concentration cap without kernel change.** As a separate branch,
   try a per-name max weight (e.g., 15% or 20%) on the 1/σ book. That
   softens the top-1 without inflating the tail of the vol
   distribution; the mechanism is different from √σ (redistributes
   mass to the next-lowest-σ names, not to higher-vol names) and
   might get most of the diversification benefit at less Sharpe cost.

5. **Stop testing on `long_q20 replace ε=0.2` for kernel experiments
   without also comparing on `long_q05` and `long_q10`.** The
   Phase 9.2 report showed `long_q20` is the "already saturated"
   cell (near-zero hysteresis headroom); it's probably also the least
   informative cell for sizing-kernel changes because the held set is
   already large enough that concentration is arithmetically capped.
   The smaller-K cells will show a cleaner concentration → risk-return
   trade-off.

Explicitly *not* recommended: repeating this comparison on OOS
before doing (3) and (4) — the OOS window should stay sealed until
the sizing axis has a finalist worth confirming.

## Files

- `data/v6_static/sizing_sweep/summary.csv` — control + treatment row
  (IS Sharpe / CAGR / DD / turnover / concentration).
- `data/v6_static/sizing_sweep/bar_control.csv` — per-bar IS detail
  under `1/σ`.
- `data/v6_static/sizing_sweep/bar_treatment.csv` — per-bar IS detail
  under `1/√σ`.
- `data/v6_static/sizing_sweep/block_alloc.csv` — mean block share
  of book weight (IS, control / treatment / Δ).
- `scripts/hysteresis_engine_v6_sizing.py` — parameterized weight
  builder. `sizing ∈ {inv_vol, inv_sqrt_vol}`; extendable to
  `inv_pow_vol(β)` in a follow-up without another copy.
- `scripts/sizing_sweep_v6.py` — driver. Runs control + treatment,
  asserts `inv_vol` matches `hysteresis_engine_v6.build_hysteresis_weights`
  bit-for-bit, writes the summary + per-bar + block-share tables.

## Reproducing

```bash
python v6/scripts/sizing_sweep_v6.py
```

Runtime < 5 s. No re-screen, no re-ensemble — loads
`long_q20/ensemble_alpha.parquet` and rebuilds books only. Reverting
this branch = deleting `hysteresis_engine_v6_sizing.py` and
`sizing_sweep_v6.py`; all Phase 9.x artifacts are untouched.
