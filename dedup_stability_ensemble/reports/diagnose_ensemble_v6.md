# v6 static — ensemble-vs-individual diagnostic

Generated: 2026-07-20 11:52:53  

Four ways to summarize the (mode, q) cell's Sharpe:
- **indiv mean** = arithmetic mean of the kept factors' *individual* book Sharpes.
- **ensemble-of-books** = Sharpe of the equal-weight average of kept factors' net-return series. Portfolio of separately-run books.
- **signal-mean rank** = current production: mean the stage-2 CS Gaussian rank panels, then run one book on the average. Ordering-only.
- **signal-mean row-z** = v4pool convention: mean the per-bar row-z of raw α panels, then run one book. Preserves magnitudes.

| mode | q | kept | indiv mean IS | indiv mean OOS | eob IS | eob OOS | rank IS | rank OOS | rowz IS | rowz OOS |
|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| long | 0.05 | 5 | +0.853 | +1.084 | +0.975 | +0.819 | +0.193 | -0.165 | +1.052 | +0.591 |
| long | 0.10 | 7 | +0.630 | +1.351 | +0.726 | +1.403 | -0.215 | +0.672 | +0.808 | +1.473 |
| long | 0.20 | 6 | +0.609 | +1.628 | +0.694 | +1.201 | +0.550 | -0.146 | +1.002 | +2.071 |
| ls | 0.20 | 1 | +0.503 | +0.275 | +0.503 | +0.275 | -0.131 | +0.275 | +0.503 | +0.275 |