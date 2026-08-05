# Blend book (static + EQW) — v6

Rank-space equal-weight blend of the Phase 9.1 static α (per-cell book-screened) and the Phase 8.2 equal-weight α (IC-shortlisted). Recipe (v4pool convention, design §7):

```
blend[t, i] = 0.5 · cs_rank(static)[t, i] + 0.5 · cs_rank(eqw)[t, i]
```

Membership mask applied before ranking. Blend α → `xs_engine_v6` at the same (mode, q) with 10 bp/side cost. v4pool used ridge for the second leg; v6 subs EQW while the ridge is deferred, so this test isolates the *blending idea* (rank-space combination of orthogonal selections) from the model quality itself.


**Skipped cells** (2): ls_q05, ls_q10. Phase 9.1 had no static leg here (no factor cleared the book-Sharpe screen at those q's), so blend is undefined. Fallback to EQW-alone would silently inflate the blend column — omitted instead.


## dedup_v6

### Blend book — grid (net of cost)

| mode | q | IS Sharpe | OOS Sharpe | full Sharpe | decay | IS cumret | OOS cumret | full cumret | full DD | avg turnover | mean_K |
|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| long | 0.05 | +0.073 | -0.976 | +0.003 | -13.33 | +1.91% | -1.81% | +0.10% | -8.59% | 0.847 | 4.7 |
| long | 0.10 | +0.563 | +0.762 | +0.545 | +1.35 | +13.99% | +1.53% | +15.51% | -5.84% | 0.669 | 8.9 |
| long | 0.20 | +0.607 | +1.774 | +0.627 | +2.92 | +19.39% | +3.42% | +22.80% | -6.00% | 0.534 | 17.4 |
| ls | 0.20 | +0.881 | -0.424 | +0.529 | -0.48 | +36.22% | -6.34% | +29.88% | -9.22% | 1.030 | 17.4 |

### Side-by-side vs static-alone (9.1) vs EQW-alone (8.2)

Full Sharpe and OOS Sharpe for each of the three variants at the same (mode, q). Positive Δ = blend beats the reference leg.

| mode | q | static full | eqw full | **blend full** | Δ vs static | Δ vs eqw | static OOS | eqw OOS | **blend OOS** | Δ vs static | Δ vs eqw |
|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| long | 0.05 | +0.967 | +0.591 | **+0.003** | -0.964 | -0.588 | +0.591 | +0.409 | **-0.976** | -1.567 | -1.385 |
| long | 0.10 | +0.829 | +0.586 | **+0.545** | -0.284 | -0.041 | +1.473 | +0.470 | **+0.762** | -0.711 | +0.292 |
| long | 0.20 | +1.013 | +0.487 | **+0.627** | -0.386 | +0.140 | +2.071 | +0.369 | **+1.774** | -0.297 | +1.404 |
| ls | 0.20 | +0.450 | +0.154 | **+0.529** | +0.079 | +0.374 | +0.275 | -0.769 | **-0.424** | -0.699 | +0.345 |

## stability_v6

### Blend book — grid (net of cost)

| mode | q | IS Sharpe | OOS Sharpe | full Sharpe | decay | IS cumret | OOS cumret | full cumret | full DD | avg turnover | mean_K |
|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| long | 0.05 | +0.786 | -0.541 | +0.659 | -0.69 | +18.86% | -0.81% | +18.04% | -3.27% | 0.490 | 4.7 |
| long | 0.10 | +0.977 | +1.339 | +0.930 | +1.37 | +23.29% | +1.99% | +25.28% | -3.55% | 0.387 | 8.9 |
| long | 0.20 | +0.964 | +2.227 | +0.951 | +2.31 | +30.32% | +3.71% | +34.03% | -3.56% | 0.354 | 17.4 |
| ls | 0.20 | +0.530 | -0.571 | +0.233 | -1.08 | +22.88% | -9.02% | +13.86% | -13.92% | 0.826 | 17.4 |

### Side-by-side vs static-alone (9.1) vs EQW-alone (8.2)

Full Sharpe and OOS Sharpe for each of the three variants at the same (mode, q). Positive Δ = blend beats the reference leg.

| mode | q | static full | eqw full | **blend full** | Δ vs static | Δ vs eqw | static OOS | eqw OOS | **blend OOS** | Δ vs static | Δ vs eqw |
|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| long | 0.05 | +0.967 | +0.400 | **+0.659** | -0.308 | +0.259 | +0.591 | -1.388 | **-0.541** | -1.131 | +0.847 |
| long | 0.10 | +0.829 | +0.770 | **+0.930** | +0.101 | +0.160 | +1.473 | -0.173 | **+1.339** | -0.134 | +1.512 |
| long | 0.20 | +1.013 | +0.802 | **+0.951** | -0.062 | +0.149 | +2.071 | +0.941 | **+2.227** | +0.156 | +1.286 |
| ls | 0.20 | +0.450 | +0.104 | **+0.233** | -0.217 | +0.129 | +0.275 | -0.934 | **-0.571** | -0.847 | +0.362 |

## Files

- per-cell blend α       : `data/blend_book_v6/{variant}/{cell}/blend_alpha.parquet`
- per-cell blend weights : `data/blend_book_v6/{variant}/{cell}/blend_weights.parquet`
- per-cell net returns   : `data/blend_book_v6/{variant}/{cell}/blend_net_ret.csv`
- per-variant grid       : `data/blend_book_v6/{variant}/blend_grid.csv`