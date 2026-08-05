# v6 static baseline — follow-up diagnostics

Generated: 2026-07-20

## Motivation

`cost_attribution_v6_report.md` showed 85–87% of turnover comes from
top-K rotation (the *selection* channel), not from σ-drift or
renormalization. This report goes one layer deeper on the same four
Phase 9.1 cells (`long_q05`, `long_q10`, `long_q20`, `ls_q20`) with
three questions:

1. **How much of the selection turnover is *marginal* churn** —
   names that flip in and out because their α rank sits ε-close to
   the K boundary — versus deep moves where α actually crossed most
   of the ranking?
2. **How does the strategy perform per calendar year?** Sharpe,
   annualized return, and max DD by year — the full-window Sharpe
   hides both the good years and the bad ones.
3. **When the max drawdown happens, who owns it?** Locate each cell's
   peak → trough on net NAV and decompose the loss by name.

All numbers are net of the 10 bp / side turnover cost (matches the
Phase 9.1 headline) and restricted to IS ∪ OOS (≤ 2025-07-31); the
2025-08+ hold-out remains sealed. Windows and cost rate come from
`_common_v6.py` / `xs_engine_v6.py` so this report re-uses the same
scoping as `cost_attribution_v6.py`.

## 1. Marginal churn — how much rotation is boundary-slop?

For each cell, at each W-FRI bar, we rank every eligible name by
ensemble α (top-K makes the book). An **entry** event is a name that
was zero-weight at t−1 and non-zero at t; an **exit** is the reverse.
The event's *flip distance* is how many rank slots outside the K
boundary the name sat on the "other side" of the flip (e.g. an exit
whose new rank is K+1 has flip distance 1). We also tag each event
with `round_trip_h` — the gap in weeks to the same name's paired
opposite event, capped at 4 weeks.

### Summary

| cell | flip events | ±2 slot dw share | rt≤1w exit share | rt≤2w exit share | rt≤4w exit share | rt≤4w dw share |
|:---:|---:|---:|---:|---:|---:|---:|
| long_q05 |    688 | 28.4% | 44.8% | 58.7% | 68.1% | **77.2%** |
| long_q10 |  1,912 | 13.3% | 30.0% | 43.0% | 48.9% | 72.5% |
| long_q20 |  3,475 | 10.2% | 27.2% | 36.8% | 46.6% | 71.0% |
| ls_q20   | 10,532 | 13.0% | 21.4% | 29.8% | 39.3% | 36.8% |

- **±2 slot dw share** — fraction of total selection turnover
  (|Δw|) attributable to flips within ±2 rank slots of the K
  boundary.
- **rt≤Xw exit share** — fraction of exit events that see the same
  name re-enter the book within X weeks.
- **rt≤4w dw share** — fraction of total selection |Δw| that is part
  of an entry ↔ exit pair with gap ≤ 4 weeks (both legs counted).

### Findings

**(a) Round-trip churn is the story, not the strict ±2 band.**
The fixed ±2-slot band captures only 10–13% of selection turnover on
the larger books (long_q10, long_q20, ls_q20) — with K = 10–40, a
±2 band is a narrow slice. But relax "marginal" to *any flip that
reverses within 4 weeks* and 47–68% of exits on the long cells are
round-trippers, weighted by |Δw| that's **71–77% of selection
turnover** on all three long books. In other words, most of the
selection cost is not paying for durable α rotation — it's paying
for names oscillating in and out.

**(b) Small books amplify it.** `long_q05` — K ≈ 5 — has the highest
round-trip *and* ±2-slot shares (28% and 77%). With so few slots the
boundary is thick relative to the whole book: a rank wiggle of 2
crosses ⅖ of the ranking. This lines up with `long_q05` having the
highest cost/gross ratio (45% in `cost_attribution_v6_report.md`).

**(c) LS is different.** `ls_q20` shows a much lower round-trip dw
share (37%) than the long books (~72%). Two effects: the short leg
adds a second boundary that captures rank moves the long leg would
not see, and K = 40 on each side means ranks near the boundary are
already dilute per name. Deep rank moves (>25 slots outside the
boundary) contribute 20–25% of dw versus 13–14% on long_q10 —
selection turnover in LS is more "real α rotation," less
boundary-slop.

**(d) Implication.** A hysteresis rule (name only exits when its
rank falls to > (1 + ε)·K, per the design note in
§`cost_attribution_v6_report.md`) should almost mechanically kill
the round-trip channel. The uplift ceiling is large on the long
cells (~70% of selection cost is round-trip dw); much smaller on
`ls_q20` (~37%).

### Per-cell files

- `data/v6_static/baseline_diagnostics/{cell}_flip_events.csv` — one
  row per entry/exit event (side, ranks, boundary distances, dw,
  round-trip gap).
- `data/v6_static/baseline_diagnostics/{cell}_marginal_histogram.csv`
  — flip counts + |Δw| bucketed by distance bins {1, 2, 3, 4-5,
  6-10, 11-25, >25} slots outside the boundary.

## 2. Per-year Sharpe / return / drawdown

Calendar years, IS ∪ OOS only. 2018 has 31 weekly bars (panel
starts 2018-06-01); 2025 has 30 bars (OOS_END = 2025-07-31, the
partial year). All returns net of cost.

| cell | year | n | ann_ret | Sharpe | max_dd |
|:---:|:---:|---:|---:|---:|---:|
| long_q05 | 2018 | 31 |  +2.4% | +2.14 | −0.1% |
| long_q05 | 2019 | 52 |  +4.4% | +1.85 | −1.7% |
| long_q05 | 2020 | 52 |  +0.7% | +0.19 | −4.9% |
| long_q05 | 2021 | 53 |  +3.8% | +2.53 | −0.7% |
| long_q05 | 2022 | 52 |  +0.7% | +1.01 | −0.7% |
| long_q05 | 2023 | 52 |  +1.3% | +1.75 | −0.7% |
| long_q05 | 2024 | 52 |  +1.8% | +1.94 | −0.7% |
| long_q05 | 2025 | 30 |  **−1.6%** | **−2.15** | −0.9% |
| long_q10 | 2018 | 31 |  +2.7% | +2.39 |  0.0% |
| long_q10 | 2019 | 52 |  +3.2% | +1.59 | −0.9% |
| long_q10 | 2020 | 52 |  +2.0% | +0.39 | −3.9% |
| long_q10 | 2021 | 53 |  +3.7% | +1.71 | −1.0% |
| long_q10 | 2022 | 52 |  **−0.6%** | **−0.73** | −1.1% |
| long_q10 | 2023 | 52 |  +1.5% | +1.73 | −0.9% |
| long_q10 | 2024 | 52 |  +2.6% | +2.99 | −0.5% |
| long_q10 | 2025 | 30 |  −0.8% | −0.89 | −0.8% |
| long_q20 | 2018 | 31 |  +1.7% | +2.09 |  0.0% |
| long_q20 | 2019 | 52 |  +9.7% | +3.32 | −1.3% |
| long_q20 | 2020 | 52 |  +6.5% | +0.90 | −5.8% |
| long_q20 | 2021 | 53 |  +3.8% | +1.04 | −1.8% |
| long_q20 | 2022 | 52 |  **−1.9%** | **−1.27** | −2.7% |
| long_q20 | 2023 | 52 |  +1.9% | +1.58 | −1.1% |
| long_q20 | 2024 | 52 |  +3.1% | +3.09 | −0.3% |
| long_q20 | 2025 | 30 |  +0.3% | +0.29 | −0.8% |
| ls_q20   | 2018 | 31 |  −0.6% | −0.23 | −1.3% |
| ls_q20   | 2019 | 52 |  +8.7% | +1.01 | −5.0% |
| ls_q20   | 2020 | 52 |  +8.2% | +0.77 | −6.5% |
| ls_q20   | 2021 | 53 | **+13.7%** | +1.35 | −3.6% |
| ls_q20   | 2022 | 52 |  **−6.7%** | **−0.71** | −10.2% |
| ls_q20   | 2023 | 52 |  +0.8% | +0.12 | −6.1% |
| ls_q20   | 2024 | 52 |  +4.1% | +0.40 | −11.1% |
| ls_q20   | 2025 | 30 |   0.0% | +0.00 | −4.3% |

### Findings

**(a) 2022 is the pressure test for the long book.** `long_q10` and
`long_q20` are the only years with negative full-year returns
(−0.6% / −1.9%); `ls_q20` had its worst year at −6.7%. The China
onshore drawdown that year (property + policy) hit the deeper long
tails.

**(b) 2025 partial year is soft across three of four cells.** With
only 30 bars, the standard error is wide, but `long_q05` at −1.6%
Sharpe −2.15 stands out. Concentrated books get concentrated year
tails; the small-K static baseline is the most exposed to a bad
partial year.

**(c) `long_q20` is the most consistent long variant.** Positive
Sharpe every year except 2022, 2019 and 2020 both above 1.0, 2024
best-in-class at +3.09. Deeper books smooth the year-to-year path
even after cost.

**(d) `ls_q20` has meaningfully higher year-to-year variance.**
+13.7% in 2021 and −6.7% in 2022 in the same book — the
long-short's calendar dispersion is 3–4× the long-only cells. Some
of that is by design (LS lifts idiosyncratic exposure) but the
per-year DDs (−10% in 2022, −11% in 2024) are also 3–5× the long
books, and cost drag is 3× worse (`cost_attribution` §Cell
headline). Not obviously the better book on a risk-adjusted year
basis.

### Files

- `data/v6_static/baseline_diagnostics/annual_stats.csv` — long
  format: cell × year × {n_bars, ann_ret, sharpe, max_dd, vol}.

## 3. Portfolio drawdown attribution

For each cell we find the max DD on the checked-in net-return
series over IS ∪ OOS: NAV_t = 1 + Σ_{s≤t} net_ret_s, trough =
argmin (NAV − cummax)/cummax, peak = argmax NAV on [0, trough].
Over the drawdown window (bars strictly after peak, up to and
including trough) we decompose per-name net contribution:

```
gross_contrib_i = Σ_t w_{i,t} · fwd_{i,t}
cost_contrib_i  = 0.001 · Σ_t |Δw_{i,t}|         # 10 bp / side
net_contrib_i   = gross_contrib_i − cost_contrib_i
```

By construction `Σ_i net_contrib_i = NAV_trough − NAV_peak` (the
absolute DD); residuals are ≤ 5·10⁻¹⁶ per cell (numeric noise).

### Header

| cell | peak | trough | weeks | DD % | NAV peak → trough |
|:---:|:---:|:---:|---:|---:|---:|
| long_q05 | 2020-04-24 | 2020-10-23 |  26 |  −4.68% | 1.1088 → 1.0568 |
| long_q10 | 2020-02-14 | 2020-03-13 |   4 |  −3.77% | 1.0645 → 1.0244 |
| long_q20 | 2020-02-14 | 2020-03-13 |   4 |  −5.24% | 1.1353 → 1.0758 |
| ls_q20   | 2022-07-01 | 2024-08-23 | 112 | −11.32% | 1.3439 → 1.1918 |

Two very different DD regimes: the long books' worst weeks were
short, sharp shocks in 2020 (COVID crash for `long_q10`/`long_q20`,
a longer bond-selloff-and-recovery period for `long_q05`); `ls_q20`
had a 2+ year slow bleed from mid-2022.

### 3.1 `long_q10` (Feb–Mar 2020, −3.77%, 4 weeks)

Average weights during the DD window (book was heavy in
long-duration bonds):

| code | block | avg weight |
|:---|:---|---:|
| 511010.XSHG (GTSZ5NQGZ, 5Y gov bond) | bond_rates | 70.3% |
| 518880.XSHG (HAHJ gold)              | metals     | 13.5% |
| 513500.XSHG (BSBP S&P 500 QDII)      | cross_border_dm |  4.9% |
| 513050.XSHG (YFDZZHW ZG-NASDAQ QDII) | cross_border_dm |  4.1% |
| 510500.XSHG (NFZZ500)                | smallcap_cn |  2.1% |
| 512290.XSHG (GTZZSW pharma)          | sector_cn   |  2.0% |

Top loss contributors (net_contrib, decomposition):

| code | gross | cost | net | own return (window) |
|:---|---:|---:|---:|---:|
| 518880 (gold) | −0.0111 | +0.0002 | **−0.0113** | −8.2% |
| 513500 (S&P 500) | −0.0099 | +0.0002 | **−0.0101** | −20.7% |
| 512290 (pharma) | −0.0059 | +0.0002 | **−0.0061** | −4.5% |
| 510500 (smallcap) | −0.0049 | +0.0002 | **−0.0051** | −10.0% |
| 513050 (NASDAQ) | −0.0039 | +0.0001 | **−0.0040** | −10.9% |
| 511010 (5Y bond) | +0.0030 | +0.0002 | **+0.0028** | +0.5% |

Read: the 70%-of-book 5Y bond held up (essentially flat), but the
30% of book allocated to risk assets (gold, US equity, small-cap,
pharma) took the full COVID drawdown. `long_q10` was picking up
the correct anchor (long-duration bonds) but its α ranking pushed
non-bond names into slots 2–10 that got clobbered in a
correlated-risk-off week. This is a *tail-of-book* drawdown, not a
top-pick failure.

### 3.2 `long_q20` (same 4 weeks, −5.24%)

Larger K, more names contribute. Biggest loser: `513500` (S&P 500
QDII) with 9.3% avg weight and −20.7% own return → −2.29% of book
NAV. `518880` (gold, 11.2% weight) → −0.93%. Same pattern as
long_q10 but with more equity/QDII exposure in the deeper slots.
`511010` again held up as the +0.21% offset. Cost contribution is
tiny across the board because the DD was only 4 weeks — turnover
had little time to compound.

### 3.3 `long_q05` (Apr–Oct 2020, −4.68%, 26 weeks)

Only 9 names touched the book over the 26-week window. Top
losers:

| code | block | avg weight | net_contrib | own return |
|:---|:---|---:|---:|---:|
| 511010 (5Y gov bond) | bond_rates | 37.4% | **−0.0159** | −4.3% |
| 511260 (10Y gov bond) | bond_rates | 29.3% | **−0.0115** | −3.0% |
| 511270 (10Y policy bank bond) | bond_rates | 16.1% | **−0.0104** | −2.6% |

The concentrated small book had ~85% weight in bond ETFs during a
period when the China yield curve backed up (2020 recovery
repricing). Cost contribution was 0.003 on the top holding
(19% of that name's loss) — meaningful because turnover had 26
weeks to accumulate. This is the *opposite* pattern to long_q10:
top-pick failure, not tail-of-book. The COVID risk-off period that
hit long_q10/q20 didn't dent long_q05 because that book had
already rotated to bonds; the DD came from bonds themselves
selling off later.

### 3.4 `ls_q20` (Jul 2022 – Aug 2024, −11.32%, 112 weeks)

Fundamentally different regime. 201 names touched at least one
side of the book during the DD; 132 lost money, 69 made money.

**Concentration.** Top 10 losers account for 24% of loser dollars;
top 20 for 40%. This is *not* concentrated — it's a diffuse bleed
across the whole book.

**Leg breakdown** (gross, excluding cost):

| leg | gross contrib |
|:---:|---:|
| long leg (+w) | −0.1253 |
| short leg (−w) | +0.0776 |
| net gross | −0.0477 |
| cost drag (both legs) | −0.1044 |
| **net contribution to DD** | **−0.1522** |

Two facts drop out:

1. **The short leg *worked* over this window** (+7.8% gross). The
   long-leg loss (−12.5%) is what pushed the book underwater on a
   gross basis.
2. **Cost drag (−10.4%) is bigger than the net-gross loss (−4.8%)**
   — most of the 2+ year DD is not from picking the wrong names,
   it's the 10 bp × 81% weekly turnover × 112 weeks tab. Consistent
   with `cost_attribution_v6_report.md` §1 (LS: 51% of gross return
   eaten by cost) but the DD-window snapshot makes it starker: over
   this specific stretch, the alpha barely lost money, cost lost
   the money.

**Top loser** at name level is `513360.XSHG` (education QDII) —
short-leg exposure that fought a rally, own return +4.4% over the
window, contributed −1.06% to DD. **Top winner** is `512980.XSHG`
(media sector) — short-leg exposure into a −4.5% own return, +0.85%
contribution. But magnitudes at the name level are tiny relative
to book (all << 1% each), so no single trade drove the drawdown.

### Files

- `data/v6_static/baseline_diagnostics/drawdown_summary.csv` — one
  row per cell (peak, trough, DD %, NAV peak, NAV trough, n_bars,
  residual).
- `data/v6_static/baseline_diagnostics/{cell}_dd_attribution.csv` —
  per-name (code, gross_contrib, cost_contrib, net_contrib,
  avg_abs_weight, name_return); rows sorted by net_contrib
  ascending.

## Cross-cutting takeaways

1. **Selection turnover is dominated by short-horizon round trips**
   (rt≤4w) — 71–77% of selection |Δw| on the long books, 37% on
   `ls_q20`. This is a direct, actionable target: a rank
   hysteresis at the K boundary should recover most of it.
2. **The long_q05 book is fragile.** Highest cost/gross ratio,
   worst 2025 partial year, single-block DD in 2020 (bonds only) —
   the small book concentrates whatever the α says at any point,
   and pays cost twice for the privilege.
3. **The long_q20 book is the calendar-year winner.** Positive
   Sharpe in 7 of 8 years, lowest year-to-year variance, biggest
   contribution to cost/gross ratio is still under one-third.
4. **`ls_q20`'s max DD is really a cost story**, not an alpha
   story: over Jul 2022 – Aug 2024, cost drag exceeded the
   net-of-hedging alpha loss by 2× (−10.4% vs −4.8%). Any cost
   reduction proportional to the round-trip / hysteresis fix would
   flow directly to this cell's DD.
5. **Both COVID DDs on the long books were tail-of-book, not
   top-pick, losses.** The top-weighted bond ETF held up in
   Feb-Mar 2020; the drawdown came from equity / QDII / commodity
   names sitting in slots 2–20. Points to a possible allocation
   check (max block concentration in the non-anchor sleeves) but
   the DDs are small enough (3.8% / 5.2%) that this is a
   nice-to-have, not a priority.

## Reproducing

```bash
python v6/scripts/baseline_diagnostics_v6.py
```

Reads persisted `ensemble_weights.parquet` + `ensemble_alpha.parquet`
under `data/v6_static/{cell}/` and the panels under
`data/panels_v6/`. No re-screen. Runtime < 10 s.
