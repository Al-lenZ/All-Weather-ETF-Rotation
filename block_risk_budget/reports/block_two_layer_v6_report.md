# Phase 12 × Phase 13 — two-layer book (layer-1 risk budget + layer-2 α on broad_cn + sector_cn)

Generated: 2026-07-22 19:37:46  

Layer-1: 4-group risk budget (equity 55 / bond_rates 20 / bond_credit 10 / commodity 15 %), LW-target-D shrinkage, log-barrier ERC solver. **Trend gate off** (ablation showed it Sharpe-neutral post-fix; user chose the simpler no-gate spec).  Sub-block share within group = N_b / N_g (static ever-admitted count) so at α off (q=1, ε=0) the book collapses exactly to the layer-1 all-invvol baseline.

Layer-2: production long_q20-`replace` α-hysteresis kernel on `broad_cn` (K=5 locked ensemble) and `sector_cn` (K=8 locked ensemble). Other 6 blocks (bond_rates, bond_credit, cross_border_dm, cross_border_hk, metals, commodity_other) stay hold-all with invvol sizing. Members are frozen per Phase 13.5 finalists.

Cost 10 bp/side. IS = bars ≤ 2023-12-31. **OOS sealed**. Sweep: q × ε = (0.10, 0.20, 0.30) × (0.00, 0.10, 0.20, 0.30) = 12 cells. Plateau rule: within Δ-Sharpe ≥ max − 0.05, pick lowest turnover cell (tie-break lower ε, then lower q).


## 0. Layer-1 baseline (α off; q=1, ε=0)

| metric | net | gross |
|:---|---:|---:|
| IS Sharpe | +1.365 | +1.461 |
| IS CAGR   | +3.20% | +3.41% |
| IS max DD | -2.43% | -2.42% |
| ann vol   | +2.31% | +2.31% |
| turnover  | 0.0465 | 0.0465 |
| mean K    | 91.1 | 91.1 |

## 1. Sweep — 12 cells (net metrics, Δ vs baseline)

| q | ε | Sharpe net | Δ Sh | CAGR net | Δ CAGR pp | max DD | turnover | Δ turn | cost drag bp/yr |
|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.10 | 0.00 | +1.389 | +0.025 | +3.35% | +0.15 | -2.45% | 0.0997 | +0.0532 | +55.3 |
| 0.10 | 0.10 | +1.461 | +0.097 | +3.62% | +0.42 | -2.57% | 0.0896 | +0.0431 | +44.8 |
| 0.10 | 0.20 | +1.461 | +0.096 | +3.62% | +0.41 | -2.57% | 0.0890 | +0.0425 | +44.2 |
| 0.10 | 0.30 | +1.468 | +0.103 | +3.63% | +0.43 | -2.57% | 0.0873 | +0.0408 | +42.4 |
| 0.20 | 0.00 | +1.406 | +0.041 | +3.41% | +0.21 | -2.49% | 0.0943 | +0.0478 | +49.7 |
| 0.20 | 0.10 | +1.381 | +0.016 | +3.37% | +0.17 | -2.54% | 0.0844 | +0.0379 | +39.4 |
| 0.20 | 0.20 | +1.389 | +0.025 | +3.39% | +0.19 | -2.54% | 0.0828 | +0.0363 | +37.7 |
| 0.20 **★** | 0.30 | +1.424 | +0.059 | +3.47% | +0.27 | -2.54% | 0.0813 | +0.0348 | +36.2 |
| 0.30 | 0.00 | +1.352 | -0.013 | +3.28% | +0.08 | -2.52% | 0.0901 | +0.0436 | +45.3 |
| 0.30 | 0.10 | +1.348 | -0.017 | +3.29% | +0.09 | -2.57% | 0.0807 | +0.0342 | +35.5 |
| 0.30 | 0.20 | +1.363 | -0.002 | +3.33% | +0.13 | -2.57% | 0.0788 | +0.0323 | +33.6 |
| 0.30 | 0.30 | +1.364 | -0.001 | +3.34% | +0.14 | -2.57% | 0.0766 | +0.0301 | +31.3 |

## 2. Plateau selection

Max Δ-Sharpe across sweep = **+0.103**. Plateau (Δ-Sharpe ≥ max − 0.05) contains **4** cell(s). Winner (lowest turnover within plateau, tie-break lower ε then lower q):

**q = 0.20, ε = 0.30** — Sharpe net +1.424 (Δ +0.059), CAGR net +3.47% (Δ +0.27 pp), turnover 0.0813.


Plateau members (sorted by turnover, then ε, then q):


| q | ε | Sharpe net | Δ Sh | turnover |
|:---:|:---:|---:|---:|---:|
| 0.20 | 0.30 | +1.424 | +0.059 | 0.0813 |
| 0.10 | 0.30 | +1.468 | +0.103 | 0.0873 |
| 0.10 | 0.20 | +1.461 | +0.096 | 0.0890 |
| 0.10 | 0.10 | +1.461 | +0.097 | 0.0896 |

## 3. Recommended cell (q = 0.20, ε = 0.30) — detailed

| metric | baseline | recommended | Δ |
|:---|---:|---:|---:|
| Sharpe net    | +1.365 | +1.424 | +0.059 |
| Sharpe gross  | +1.461 | +1.591 | +0.129 |
| CAGR net      | +3.20% | +3.47% | +0.27 pp |
| CAGR gross    | +3.41% | +3.85% | +0.44 pp |
| max DD        | -2.43% | -2.54% | -0.11 pp |
| ann vol       | +2.31% | +2.41% | +0.09 pp |
| turnover      | 0.0465 | 0.0813 | +0.0348 |
| mean K names  | 91.1 | 38.1 | -53.0 |

## 4. Cost attribution (gross vs net, all cells + baseline)

| q | ε | Sharpe gross | Sharpe net | Δ (cost drag) | CAGR gross | CAGR net | Δ pp |
|:---:|:---:|---:|---:|---:|---:|---:|---:|
| — | — | +1.461 | +1.365 | -0.096 | +3.41% | +3.20% | -0.21 |
| 0.10 | 0.00 | +1.599 | +1.389 | -0.209 | +3.82% | +3.35% | -0.47 |
| 0.10 | 0.10 | +1.640 | +1.461 | -0.178 | +4.03% | +3.62% | -0.41 |
| 0.10 | 0.20 | +1.638 | +1.461 | -0.177 | +4.02% | +3.62% | -0.41 |
| 0.10 | 0.30 | +1.642 | +1.468 | -0.174 | +4.03% | +3.63% | -0.40 |
| 0.20 | 0.00 | +1.603 | +1.406 | -0.197 | +3.86% | +3.41% | -0.44 |
| 0.20 | 0.10 | +1.554 | +1.381 | -0.173 | +3.76% | +3.37% | -0.39 |
| 0.20 | 0.20 | +1.559 | +1.389 | -0.170 | +3.77% | +3.39% | -0.38 |
| 0.20 | 0.30 | +1.591 | +1.424 | -0.167 | +3.85% | +3.47% | -0.38 |
| 0.30 | 0.00 | +1.541 | +1.352 | -0.189 | +3.71% | +3.28% | -0.43 |
| 0.30 | 0.10 | +1.514 | +1.348 | -0.167 | +3.67% | +3.29% | -0.38 |
| 0.30 | 0.20 | +1.526 | +1.363 | -0.163 | +3.70% | +3.33% | -0.37 |
| 0.30 | 0.30 | +1.522 | +1.364 | -0.158 | +3.70% | +3.34% | -0.36 |

## 5. Per-calendar-year IS return (sum of weekly net)

| year | baseline | ★ q=0.20 ε=0.30 | q=0.10 ε=0.30 | q=0.10 ε=0.10 |
|:---:|---:|---:|---:|---:|
| 2018 | +0.00% | +0.00% | +0.00% | +0.00% |
| 2019 | +4.99% | +5.88% | +5.79% | +5.79% |
| 2020 | +8.18% | +6.75% | +7.24% | +7.24% |
| 2021 | +3.71% | +5.46% | +5.57% | +5.24% |
| 2022 | +0.25% | +0.46% | +0.95% | +1.16% |
| 2023 | +2.22% | +2.57% | +2.64% | +2.65% |

## 6. Read

**layer-2 α helps** on this IS window at the chosen cell (+0.059 Sharpe, +0.27 pp CAGR vs the layer-1-only baseline). Compare to prior anchors:
- Layer-1 canonical (`invvol × lw_erc`, no trend): IS Sharpe +1.418 / CAGR +3.43% / DD −2.55%.
- Layer-1 with trend on (`eqw × lw_erc`): IS Sharpe +1.429 / CAGR +3.40% / DD −2.55%.
- T2 bond_invvol: IS Sharpe +1.425 / CAGR +2.40% / DD −4.26%.
- Solo defensive (Phase 11.2 finalist): IS Sharpe +1.002 / CAGR +3.48% / DD −5.24%.

**Plateau discipline.** The recommended cell was chosen by the plateau rule (Δ-Sharpe within 0.05 of max, lowest turnover). If the plateau contains only 1 cell the sweep is not that flat and the winner is a single-cell peak — watch out for OOS decay. If the plateau contains ≥ 3 cells spanning multiple q or ε, the recommended cell is robust to parameter perturbation.

**Open follow-ups.** (a) Try α on cross_border_hk once its 2024+ OOS opens and non-crashing regime data is available. (b) Per-block hysteresis knobs — this branch sweeps uniform (q, ε) across both α blocks; the frozen finalists actually had ε_broad_cn=0.20 vs ε_sector_cn=1.00 which the uniform sweep can't recover. (c) Combined intra-sizing sweep for the non-α blocks (eqw vs invvol) — currently held at `invvol` for clean Δ.

