# Phase 8.6 — ridge + static blend (v6)

v4pool production book recipe: rank-space equal-weight blend of the Phase 9.1 per-cell static α and the Phase 8.3 ridge OOF s_hat.

```
blend[t, i] = 0.5 · cs_rank(static)[t, i] + 0.5 · cs_rank(ridge)[t, i]
```

Ridge OOF s_hat is NaN before the first test fold (warm-up); the rank-space blend degrades to static-alone in that window. Membership mask applied before ranking. Blend α → `xs_engine_v6` at the same (mode, q) with 10 bp/side cost.


**Skipped cells** (2): ls_q05, ls_q10. Phase 9.1 had no static leg here so blend is undefined (see `blend_book_v6_report.md`).


## dedup_v6

### Ridge+static blend — grid (net of cost)

| mode | q | IS Sharpe | OOS Sharpe | full Sharpe | decay | IS cumret | OOS cumret | full cumret | full DD | avg turnover | mean_K |
|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| long | 0.05 | -0.093 | -1.718 | -0.151 | +18.50 | -3.15% | -2.66% | -5.82% | -13.30% | 0.760 | 4.7 |
| long | 0.10 | -0.026 | +0.542 | +0.007 | -21.26 | -0.74% | +0.99% | +0.24% | -13.76% | 0.648 | 8.9 |
| long | 0.20 | +0.364 | +0.872 | +0.364 | +2.40 | +11.72% | +1.60% | +13.31% | -12.39% | 0.497 | 17.4 |
| ls | 0.20 | +0.639 | -0.523 | +0.355 | -0.82 | +29.45% | -7.77% | +21.68% | -11.58% | 0.995 | 17.4 |

### 5-way Full Sharpe — static / eqw / eqw+static blend / ridge / **ridge+static blend**

| mode | q | static | eqw | eqw⊕static | ridge | **ridge⊕static** | Δ vs static | Δ vs eqw⊕static |
|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|
| long | 0.05 | +0.967 | +0.591 | +0.003 | +0.254 | **-0.151** | -1.118 | -0.154 |
| long | 0.10 | +0.829 | +0.586 | +0.545 | +0.362 | **+0.007** | -0.822 | -0.538 |
| long | 0.20 | +1.013 | +0.487 | +0.627 | +0.309 | **+0.364** | -0.649 | -0.263 |
| ls | 0.20 | +0.450 | +0.154 | +0.529 | -0.291 | **+0.355** | -0.095 | -0.174 |

### 5-way OOS Sharpe — static / eqw / eqw+static blend / ridge / **ridge+static blend**

| mode | q | static | eqw | eqw⊕static | ridge | **ridge⊕static** | Δ vs static | Δ vs eqw⊕static |
|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|
| long | 0.05 | +0.591 | +0.409 | -0.976 | +0.207 | **-1.718** | -2.309 | -0.742 |
| long | 0.10 | +1.473 | +0.470 | +0.762 | +0.501 | **+0.542** | -0.931 | -0.220 |
| long | 0.20 | +2.071 | +0.369 | +1.774 | +0.761 | **+0.872** | -1.198 | -0.901 |
| ls | 0.20 | +0.275 | -0.769 | -0.424 | -0.854 | **-0.523** | -0.798 | -0.099 |

## stability_v6

### Ridge+static blend — grid (net of cost)

| mode | q | IS Sharpe | OOS Sharpe | full Sharpe | decay | IS cumret | OOS cumret | full cumret | full DD | avg turnover | mean_K |
|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| long | 0.05 | +0.707 | -0.335 | +0.601 | -0.47 | +19.55% | -0.59% | +18.96% | -5.19% | 0.589 | 4.7 |
| long | 0.10 | +0.716 | +1.101 | +0.691 | +1.54 | +16.68% | +1.67% | +18.35% | -4.61% | 0.488 | 8.9 |
| long | 0.20 | +1.087 | +1.581 | +1.052 | +1.45 | +27.73% | +2.95% | +30.67% | -4.10% | 0.381 | 17.4 |
| ls | 0.20 | +0.650 | -0.522 | +0.339 | -0.80 | +29.95% | -8.61% | +21.34% | -15.18% | 0.845 | 17.4 |

### 5-way Full Sharpe — static / eqw / eqw+static blend / ridge / **ridge+static blend**

| mode | q | static | eqw | eqw⊕static | ridge | **ridge⊕static** | Δ vs static | Δ vs eqw⊕static |
|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|
| long | 0.05 | +0.967 | +0.400 | +0.659 | +0.343 | **+0.601** | -0.366 | -0.059 |
| long | 0.10 | +0.829 | +0.770 | +0.930 | +0.576 | **+0.691** | -0.138 | -0.239 |
| long | 0.20 | +1.013 | +0.802 | +0.951 | +0.516 | **+1.052** | +0.039 | +0.101 |
| ls | 0.20 | +0.450 | +0.104 | +0.233 | +0.095 | **+0.339** | -0.111 | +0.105 |

### 5-way OOS Sharpe — static / eqw / eqw+static blend / ridge / **ridge+static blend**

| mode | q | static | eqw | eqw⊕static | ridge | **ridge⊕static** | Δ vs static | Δ vs eqw⊕static |
|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|
| long | 0.05 | +0.591 | -1.388 | -0.541 | +0.318 | **-0.335** | -0.926 | +0.206 |
| long | 0.10 | +1.473 | -0.173 | +1.339 | +0.501 | **+1.101** | -0.372 | -0.239 |
| long | 0.20 | +2.071 | +0.941 | +2.227 | +0.617 | **+1.581** | -0.490 | -0.646 |
| ls | 0.20 | +0.275 | -0.934 | -0.571 | -0.854 | **-0.522** | -0.797 | +0.050 |

## Files

- per-cell blend α       : `data/ridge_static_blend_v6/{variant}/{cell}/blend_alpha.parquet`
- per-cell blend weights : `data/ridge_static_blend_v6/{variant}/{cell}/blend_weights.parquet`
- per-cell net returns   : `data/ridge_static_blend_v6/{variant}/{cell}/blend_net_ret.csv`
- per-variant grid       : `data/ridge_static_blend_v6/{variant}/blend_grid.csv`