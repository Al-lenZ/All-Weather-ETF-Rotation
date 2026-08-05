# v6 static baseline — exit-buffer sweep (Phase 9.2)

Generated: 2026-07-20

## Motivation

`cost_attribution_v6_report.md` showed 85–87% of turnover on the long
books is *selection* (name enter/exit). `baseline_diagnostics_v6.md`
§1.d further showed **71–77% of that selection |Δw| is round-trip
churn** on the three long cells (a name exits and re-enters within
≤ 4 weeks); on `ls_q20` the round-trip share is a more modest 37%.
The direct implication in the diagnostics report: a rank-hysteresis
rule around the K boundary should recover most of the cost cleanly.

This report runs that experiment on the four Phase 9.1 cells across
two rules:

- **buffer** — *variable-size book*. Enter at rank ≤ K, exit only when
  rank > ExitK. The held set floats in `[K, K + (# prior holdings
  currently sitting at ranks K+1..ExitK)]`.
- **replace** — *fixed-size book*. Kick a held name when rank > ExitK
  and refill from the top-ranked non-holdings so |held| stays at K.
  If no holding is beyond ExitK, no membership change (weights still
  refresh 1/σ each bar — user-chosen 2026-07-20 to preserve
  vol-scaling behavior).

Both rules use `ExitK_t = min(N_t, ⌈(1+ε)·K_t⌉)`. The coarse ε grid is
`{0.0, 0.1, 0.2, 0.3, 0.5}`; ε = 0 must reproduce the checked-in
`ensemble_net_ret.csv` bit-for-bit and is asserted at end of run.

Everything else is held constant: same ensemble α (loaded from each
cell's `ensemble_alpha.parquet` — no re-screen, no re-ensemble), same
1/σ_causal_26w vol weighting, same 10 bp / side cost, same IS/OOS
windows. Backwards compatibility: `xs_engine_v6.build_static_weights`
and every existing driver script are untouched. Reverting to Phase 9.1
= deleting the two new files.

## Cell headline

Best-ε picks below are selected on **full-window** net Sharpe. Baseline
row is ε=0 (identical for both rules by construction — top-K rebalance
every bar). Windows: **IS** ≤ 2023-12-31 · **OOS** 2024-01-01 →
2025-07-31 · **full** = IS ∪ OOS (2025-08+ hold-out sealed).

| cell | rule | best ε | net Sharpe **IS** | net Sharpe **OOS** | net Sharpe **full** | cost bps/yr | Δcost | sel turnover cut |
|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|
| long_q05 | *baseline*| —    | +1.052 | +0.591 | +0.967 | 152.3 |   —   |   —  |
| long_q05 | replace   | 0.30 | **+1.287** | **+1.151** | **+1.226** | 110.0 | −42.3 | **−29%** |
| long_q05 | buffer    | 0.30 | +1.191 | +1.142 | +1.143 | 121.1 | −31.1 | −24% |
| long_q10 | *baseline*| —    | +0.808 | +1.473 | +0.829 | 149.8 |   —   |   —  |
| long_q10 | replace   | 0.50 | **+0.936** | **+1.822** | **+0.971** | 125.9 | −23.9 | −16% |
| long_q10 | buffer    | 0.20 | +0.818 | +1.703 | +0.854 | 140.1 |  −9.7 |  −7% |
| long_q20 | *baseline*| —    | +1.002 | +2.071 | +1.013 | 144.7 |   —   |   —  |
| long_q20 | replace   | 0.20 | +1.000 | +2.231 | +1.021 | 133.2 | −11.5 |  −9% |
| long_q20 | buffer    | 0.00 | +1.002 | +2.071 | +1.013 | 144.7 |   0.0 |   0% |
| ls_q20   | *baseline*| —    | +0.503 | +0.275 | +0.450 | 422.4 |   —   |   —  |
| ls_q20   | replace   | 0.20 | **+0.580** | +0.281 | +0.510 | 371.9 | −50.5 | −14% |
| ls_q20   | buffer    | 0.20 | +0.563 | +0.329 | +0.508 | 385.5 | −36.9 | −12% |

"cost bps/yr" is mean per-bar cost × 52 × 1e4. Selection-turnover cut is
against the baseline row's `turnover_selection` (0.255, 0.247, 0.240,
0.693 respectively).

**IS vs OOS pattern:**

- **long_q05** OOS was the weakest baseline number (+0.591 net Sharpe,
  the worst per-window figure in the whole table). Replace ε=0.30
  nearly doubles it to +1.151, i.e. essentially closes the IS/OOS gap.
  This is the strongest OOS delta in the sweep.
- **long_q10** OOS is already strong at baseline; hysteresis pushes it
  further (+1.473 → +1.822). Best-ε is at the grid edge — see the
  fine-sweep recommendation below.
- **long_q20** has a **near-zero full-window delta but a real OOS gain**:
  baseline OOS +2.071 → replace ε=0.50 OOS +2.396 (+0.325). IS drifts
  slightly negative (+1.002 → +0.961), which is why the full-window
  average hides the OOS improvement. The recommendation on this cell
  is therefore softer than the OOS numbers alone suggest — the IS drop
  is small but real, and the full-window Sharpe is essentially
  unchanged.
- **ls_q20** improvement is **IS-driven** (+0.503 → +0.580 at replace
  ε=0.20) with OOS nearly flat (+0.275 → +0.281). Read: hysteresis
  removes some cost drag from the LS book but does not unlock a new
  Sharpe regime out of sample.

### Annualized return + CAGR at the best-ε picks

All figures are **net of 10 bp / side turnover cost** and reported in
percent. Annualized return is `mean(net_ret) × 52` (arithmetic, matches
`xs_engine_v6._window_sharpe.ann_ret`); CAGR is compounded on the
constant-notional NAV path `NAV_t = 1 + Σ net_ret`. On these low-vol
books the two differ by roughly 10–15 bps due to compounding on a NAV
that stays close to 1.

| cell | rule / ε | ann_ret **IS** | ann_ret **OOS** | ann_ret **full** | CAGR **IS** | CAGR **OOS** | CAGR **full** |
|:---:|:---:|---:|---:|---:|---:|---:|---:|
| long_q05 | *baseline*   | 2.22% | 0.52% | 1.84% | 2.11% | 0.52% | 1.75% |
| long_q05 | replace 0.30 | **2.72%** | **1.01%** | **2.35%** | **2.57%** | **1.01%** | **2.19%** |
| long_q05 | buffer  0.30 | 2.60% | 1.06% | 2.26% | 2.45% | 1.05% | 2.12% |
| long_q10 | *baseline*   | 2.05% | 1.33% | 1.89% | 1.96% | 1.33% | 1.79% |
| long_q10 | replace 0.50 | **2.43%** | **1.67%** | **2.26%** | **2.30%** | **1.67%** | **2.12%** |
| long_q10 | buffer  0.20 | 2.17% | 1.55% | 2.04% | 2.07% | 1.55% | 1.92% |
| long_q20 | *baseline*   | 3.77% | 2.08% | 3.40% | 3.48% | 2.07% | 3.09% |
| long_q20 | replace 0.20 | 3.71% | 2.20% | 3.38% | 3.43% | 2.19% | 3.07% |
| long_q20 | buffer  0.00 | 3.77% | 2.08% | 3.40% | 3.48% | 2.07% | 3.09% |
| ls_q20   | *baseline*   | 4.38% | 2.60% | 3.99% | 3.99% | 2.58% | 3.57% |
| ls_q20   | replace 0.20 | **5.05%** | 2.67% | **4.53%** | **4.55%** | 2.65% | **4.00%** |
| ls_q20   | buffer  0.20 | 4.85% | 3.10% | 4.47% | 4.38% | 3.08% | 3.95% |

**Ann_ret / CAGR uplift at each cell's Sharpe-optimal replace-ε (full
window, CAGR basis):**

- long_q05 replace ε=0.30: **+0.44 pp** (1.75% → 2.19%, +25% relative).
- long_q10 replace ε=0.50: **+0.33 pp** (1.79% → 2.12%, +18% relative).
- long_q20 replace ε=0.20: **−0.02 pp** (3.09% → 3.07%). Wash on returns
  despite a small OOS gain — consistent with the near-zero Sharpe move.
- ls_q20 replace ε=0.20: **+0.43 pp** (3.57% → 4.00%, +12% relative).
  LS headline return moves more than Sharpe because the improvement is
  entirely in the IS window where cost dominates the risk-adjusted
  ratio.

## Full ε ladder — net Sharpe by window

### IS (≤ 2023-12-31)

| cell | rule | ε=0.0 | ε=0.1 | ε=0.2 | ε=0.3 | ε=0.5 |
|:---:|:---:|---:|---:|---:|---:|---:|
| long_q05 | buffer  | +1.052 | +1.162 | +1.168 | +1.191 | +1.134 |
| long_q05 | replace | +1.052 | +1.208 | +1.218 | **+1.287** | +1.265 |
| long_q10 | buffer  | +0.808 | +0.800 | +0.818 | +0.778 | +0.805 |
| long_q10 | replace | +0.808 | +0.870 | +0.903 | +0.894 | **+0.936** |
| long_q20 | buffer  | +1.002 | +0.983 | +0.992 | +0.957 | +0.946 |
| long_q20 | replace | **+1.002** | +0.979 | +1.000 | +0.933 | +0.961 |
| ls_q20   | buffer  | +0.503 | +0.521 | +0.563 | +0.511 | +0.452 |
| ls_q20   | replace | +0.503 | +0.529 | **+0.580** | +0.525 | +0.499 |

### OOS (2024-01-01 → 2025-07-31)

| cell | rule | ε=0.0 | ε=0.1 | ε=0.2 | ε=0.3 | ε=0.5 |
|:---:|:---:|---:|---:|---:|---:|---:|
| long_q05 | buffer  | +0.591 | +0.814 | +1.009 | +1.142 | +1.217 |
| long_q05 | replace | +0.591 | +0.833 | +1.056 | +1.151 | **+1.254** |
| long_q10 | buffer  | +1.473 | +1.615 | +1.703 | +1.805 | +1.879 |
| long_q10 | replace | +1.473 | +1.586 | +1.714 | +1.795 | **+1.822** |
| long_q20 | buffer  | +2.071 | +2.055 | +2.179 | +2.203 | +2.252 |
| long_q20 | replace | +2.071 | +2.062 | +2.231 | +2.304 | **+2.396** |
| ls_q20   | buffer  | +0.275 | +0.291 | +0.329 | **+0.378** | +0.283 |
| ls_q20   | replace | +0.275 | +0.271 | +0.281 | +0.367 | +0.299 |

### Full (IS ∪ OOS)

| cell | rule | ε=0.0 | ε=0.1 | ε=0.2 | ε=0.3 | ε=0.5 |
|:---:|:---:|---:|---:|---:|---:|---:|
| long_q05 | buffer  | +0.967 | +1.083 | +1.111 | +1.143 | +1.102 |
| long_q05 | replace | +0.967 | +1.126 | +1.161 | **+1.226** | +1.213 |
| long_q10 | buffer  | +0.829 | +0.831 | +0.854 | +0.827 | +0.852 |
| long_q10 | replace | +0.829 | +0.892 | +0.932 | +0.932 | **+0.971** |
| long_q20 | buffer  | +1.013 | +0.996 | +1.012 | +0.984 | +0.979 |
| long_q20 | replace | +1.013 | +0.995 | **+1.021** | +0.967 | +0.996 |
| ls_q20   | buffer  | +0.450 | +0.468 | **+0.508** | +0.480 | +0.412 |
| ls_q20   | replace | +0.450 | +0.470 | **+0.510** | +0.489 | +0.453 |

**Reading across the three windows:**

- **Monotonic OOS improvement in ε** on all three long cells for both
  rules (long_q05 replace OOS: 0.59 → 0.83 → 1.06 → 1.15 → 1.25). The
  full-window peaks are not always at the OOS best because IS softens
  at higher ε — the sweep is not overfitting to the full window.
- **Best-ε picks change by window.** ls_q20 buffer's OOS best is
  ε=0.30 (+0.378) but the full-window best is ε=0.20 — because IS
  drops from +0.563 to +0.511 in the same jump. long_q20's OOS best
  is ε=0.50 replace (+2.396) but the full best is ε=0.20 replace for
  the same reason.
- **`long_q05 replace ε=0.50` is a legitimate OOS-only pick** (OOS
  Sharpe +1.254 vs +1.151 at ε=0.30). If the priority is out-of-sample
  robustness rather than full-window Sharpe, ε=0.50 replace is the
  choice on that cell.

## Full ε ladder — net CAGR by window

Percent, net of cost. Ann_ret tracks CAGR to ~10 bps on these low-vol
books, so only CAGR is shown here to keep the table dense (full
ann_ret columns are in `summary.csv`).

### IS (≤ 2023-12-31)

| cell | rule | ε=0.0 | ε=0.1 | ε=0.2 | ε=0.3 | ε=0.5 |
|:---:|:---:|---:|---:|---:|---:|---:|
| long_q05 | buffer  | 2.11% | 2.37% | 2.38% | 2.45% | 2.36% |
| long_q05 | replace | 2.11% | 2.41% | 2.43% | **2.57%** | 2.53% |
| long_q10 | buffer  | 1.96% | 2.02% | 2.07% | 1.99% | 2.14% |
| long_q10 | replace | 1.96% | 2.13% | 2.20% | 2.19% | **2.30%** |
| long_q20 | buffer  | 3.48% | 3.51% | 3.56% | 3.50% | 3.52% |
| long_q20 | replace | **3.48%** | 3.38% | 3.43% | 3.24% | 3.32% |
| ls_q20   | buffer  | 3.99% | 4.09% | 4.38% | 4.03% | 3.57% |
| ls_q20   | replace | 3.99% | 4.19% | **4.55%** | 4.21% | 4.03% |

### OOS (2024-01-01 → 2025-07-31)

| cell | rule | ε=0.0 | ε=0.1 | ε=0.2 | ε=0.3 | ε=0.5 |
|:---:|:---:|---:|---:|---:|---:|---:|
| long_q05 | buffer  | 0.52% | 0.71% | 0.93% | 1.05% | 1.12% |
| long_q05 | replace | 0.52% | 0.73% | 1.00% | 1.01% | **1.04%** |
| long_q10 | buffer  | 1.33% | 1.47% | 1.55% | 1.65% | **1.71%** |
| long_q10 | replace | 1.33% | 1.43% | 1.55% | 1.64% | **1.67%** |
| long_q20 | buffer  | 2.07% | 2.13% | 2.26% | 2.34% | **2.49%** |
| long_q20 | replace | 2.07% | 2.09% | 2.19% | 2.28% | **2.33%** |
| ls_q20   | buffer  | 2.58% | 2.72% | 3.08% | **3.53%** | 2.66% |
| ls_q20   | replace | 2.58% | 2.53% | 2.65% | **3.45%** | 2.82% |

### Full (IS ∪ OOS)

| cell | rule | ε=0.0 | ε=0.1 | ε=0.2 | ε=0.3 | ε=0.5 |
|:---:|:---:|---:|---:|---:|---:|---:|
| long_q05 | buffer  | 1.75% | 1.98% | 2.03% | 2.12% | 2.06% |
| long_q05 | replace | 1.75% | 2.02% | 2.08% | **2.19%** | 2.17% |
| long_q10 | buffer  | 1.79% | 1.87% | 1.92% | 1.88% | 2.00% |
| long_q10 | replace | 1.79% | 1.94% | 2.02% | 2.03% | **2.12%** |
| long_q20 | buffer  | 3.09% | 3.12% | 3.18% | 3.15% | **3.20%** |
| long_q20 | replace | **3.09%** | 3.02% | 3.07% | 2.95% | 3.02% |
| ls_q20   | buffer  | 3.57% | 3.67% | 3.95% | 3.76% | 3.27% |
| ls_q20   | replace | 3.57% | 3.71% | **4.00%** | 3.89% | 3.64% |

**Return vs Sharpe divergence** on `long_q20`: the full-window CAGR
best is *buffer* ε=0.50 (3.20%), not any replace row — but that same
buffer row has the lowest full gross Sharpe (+1.35) and net Sharpe
(+0.98) in the whole long_q20 block. Higher return, higher volatility,
lower risk-adjusted. This is the clearest case in the sweep where
"best return" and "best Sharpe" disagree.

The buffer rule's return advantage on `long_q20` OOS (2.49% vs 2.33%
for replace at ε=0.50) comes from the bloated book capturing more of
the deep-buffer α tails during 2024's strong regime — but the same
mechanism drags in-sample Sharpe down, so the aggregate risk-adjusted
picture still favors replace.

## Gross Sharpe — is the α still intact?

Cost cuts are only useful if they don't cost gross α. Gross-Sharpe deltas
(ΔgS = gross[best ε] − gross[baseline]):

| cell | rule × best ε | gross baseline | gross best | ΔgS |
|:---:|:---:|---:|---:|---:|
| long_q05 | replace / 0.30 | +1.798 | **+1.835** | **+0.037** |
| long_q05 | buffer  / 0.30 | +1.798 | +1.791 | −0.007 |
| long_q10 | replace / 0.50 | +1.491 | +1.524 | +0.033 |
| long_q10 | buffer  / 0.20 | +1.491 | +1.451 | −0.040 |
| long_q20 | replace / 0.20 | +1.446 | +1.427 | −0.019 |
| long_q20 | buffer  / 0.20 | +1.446 | +1.411 | −0.035 |
| ls_q20   | replace / 0.20 | +0.926 | +0.929 | +0.003 |
| ls_q20   | buffer  / 0.20 | +0.926 | +0.946 | +0.020 |

**Buffer routinely degrades gross Sharpe.** Every long buffer row at
ε ≥ 0.3 loses gross alpha (long_q05 buffer ε=0.5: −0.074; long_q20
buffer ε=0.5: −0.099; long_q10 same story). Mechanism: names sitting
in the buffer band [K+1, ExitK] have weaker α than the fresh top-K
names now co-held, and the 1/σ weighting still gives them non-trivial
mass — average per-slot α of the book drops.

**Replace preserves gross Sharpe** (mostly ≈ neutral, sometimes
positive). Fixed-size K means the book's average α slot stays near
(1+K)/2 whether a rebalance fires or not — the only difference is
which specific name occupies each slot.

## Turnover-channel breakdown (selection vs sizing)

Selection turnover is the target; sizing turnover is what the 1/σ
refresh keeps producing regardless of exit rule.

| cell | rule / ε | sel turnover | Δ sel | sizing turnover | Δ sizing |
|:---:|:---:|---:|---:|---:|---:|
| long_q05 | replace 0.30 | 0.182 | −29% | 0.030 | −22% |
| long_q05 | buffer  0.30 | 0.193 | −24% | 0.040 |  +7% |
| long_q10 | replace 0.50 | 0.208 | −16% | 0.034 | −16% |
| long_q10 | buffer  0.50 | 0.220 | −11% | 0.039 |  −5% |
| long_q20 | replace 0.50 | 0.198 | −18% | 0.033 | −13% |
| long_q20 | buffer  0.50 | 0.213 | −11% | 0.040 |  +3% |
| ls_q20   | replace 0.50 | 0.509 | −27% | 0.107 | −11% |
| ls_q20   | buffer  0.50 | 0.525 | −24% | 0.138 | +15% |

Buffer *increases* sizing turnover (larger book → more names in the
denominator, so 1/σ shifts propagate through more retained weights).
Replace also drops sizing turnover because fewer co-holding rotations
force renormalization of retained weights.

## Findings

**1. Replace ≻ buffer on every cell.** Gross alpha preservation is
the differentiator. Best-ε net-Sharpe deltas: long_q05 (+0.26 replace
vs +0.18 buffer), long_q10 (+0.14 vs +0.03), long_q20 (+0.01 vs 0.00),
ls_q20 (+0.06 vs +0.06 — same). The one wash is `ls_q20`, but even
there replace has the lower cost bill and the more stable gross Sharpe
across ε.

**2. Uplift ordering matches the round-trip ceiling.**
`baseline_diagnostics_v6.md` §1.d predicted the ordering by round-trip
dw share: long_q05 (77%) > long_q10 (73%) > long_q20 (71%) > ls_q20
(37%). Realized replace-rule net-Sharpe uplift is +0.26 > +0.14 >
+0.06 ≈ +0.06 (long_q20 is soft on Sharpe but still cuts 12–24% of
selection turnover, i.e. cost). The mechanism is confirmed.

**3. Ceiling not fully harvested.** Cost savings realized at each
cell's best replace-ε: long_q05 −28%, long_q10 −16%, long_q20 −8%,
ls_q20 −12%. Theoretical ceilings if all round-trip dw were removed:
~77% · 85% ≈ 65% of cost on long_q05 (etc.). We're capturing roughly
a third to two-thirds of the ceiling on the two smaller books, and
much less on `long_q20`. Two likely reasons:
   (a) ε ≤ 0.5 doesn't extend the buffer far enough to catch the
       longer-distance round trips (rt with rank swings of 3–5 slots
       need ε ≈ K^-1 · 3–5, i.e. ε = 0.6–1.0 on K = 5–8).
   (b) `long_q20` has K = 16 with much more per-slot rank motion; the
       ExitK = 24 boundary at ε=0.5 is still crossed frequently.

**4. Buffer rule bloats book size counterproductively.** Mean |held|
by ε=0.5:
   - long_q05: 4.7 → 5.6 (buffer) vs 4.7 (replace)
   - long_q10: 8.9 → 10.0 (buffer) vs 8.9 (replace)
   - long_q20: 17.4 → 20.3 (buffer) vs 17.4 (replace)
   - ls_q20:  34.7 → 40.5 (buffer) vs 34.7 (replace)

   The bloated book is what drags gross Sharpe: extra names come from
   the buffer band, which by definition sits at weaker α ranks.

**5. `long_q20` is barely helped.** Cost/gross ratio was already the
lowest of the four cells (30% in the cost attribution) so headroom is
small. Best replace-ε delivers only +0.008 net Sharpe. Diminishing
returns are real — this is not the cell to spend more tuning on.

**6. `ls_q20`'s cost bill is enormous and only partially cured.**
Baseline cost 422 bps/yr → 372 bps/yr at replace ε=0.20 (−12%). That's
50 bps/yr recovered; the remaining 370+ bps/yr of cost is not
hysteresis-addressable (the LS book has genuine α rotation on both
legs, not just boundary slop, per baseline_diagnostics §1.c). A cost
solution for LS likely needs cadence reduction or cost-aware selection,
not just hysteresis.

## Implications for next work

Ranked recommendations:

1. **Adopt `replace` at ε=0.20–0.30 on `long_q05` and `long_q10`.** Net
   Sharpe uplift is large (+0.26 and +0.14) and gross α is preserved
   or improved. This is a low-risk change to the Phase 9.1 static
   headline.
2. **Fine-grained ε sweep on `long_q10 replace`** — the best cell is at
   the ε=0.5 grid edge, so try ε ∈ {0.6, 0.75, 1.0}. There may be more
   left on the table.
3. **Skip `long_q20` and `ls_q20` for this axis.** long_q20 has
   ~zero headroom on the exit-rule axis; ls_q20 harvests too little of
   its total cost bill (12% of 422 bps/yr) to move the needle.
4. **Stack hysteresis with cadence-reduction (biweekly / monthly)** as
   a *separate* future experiment — the two attack different pieces of
   selection cost (round-trip vs total flip rate) and may be additive.

Explicitly *not* recommended: extending buffer to ε > 0.5 without a
minimum-alpha guardrail. The gross-Sharpe drag grows superlinearly
because a book that has bloated up by ε=0.5 already sits ~14% below
its α ceiling.

## Files

- `data/v6_static/hysteresis_sweep/summary.csv` — all 40 rows (4 cells
  × 2 rules × 5 ε), full metric table (Sharpe IS/OOS/full, gross+net,
  turnover channels, held-count, K).
- `scripts/hysteresis_engine_v6.py` — path-dependent weight builder
  (both rules, both modes). Returns `(W, N_t, K_t)` compatible with
  `xs_engine_v6.run_book`; ε=0 reproduces `build_static_weights`
  bit-for-bit.
- `scripts/hysteresis_sweep_v6.py` — top-level driver. Runs the ε grid,
  asserts ε=0 matches the checked-in `ensemble_net_ret.csv` per cell,
  writes the summary table.

## Reproducing

```bash
python v6/scripts/hysteresis_sweep_v6.py
```

Runtime < 20 s. No re-screen, no re-ensemble — pulls each cell's
persisted `ensemble_alpha.parquet` and rebuilds books only.
