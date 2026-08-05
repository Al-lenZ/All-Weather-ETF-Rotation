# Factor cache — v6

Generated: 2026-08-04 10:02:40
Elapsed:   242.5s
Cache dir: `/Users/allenzhou/Downloads/YSJ Lab/etf_basket_strategy/v6/data/factor_cache`
Disk:      1573.8 MB

## Run outcome

| status | count |
|---|---:|
| wrote | 346 |

## Per-freq intersection

| freq | median n_factors | min n_factors | ∩ across codes |
|---|---:|---:|---:|
| 1d | 473 | 472 | 472 |

The right-most column is the number of factors present in **every** admitted code's cache — this is what `common_factors(...)` returns in ``etf_io``. Phase 7's PV sweep only sees these; a big drop vs the ~300+ v4pool sees means an ingestion problem somewhere upstream. Investigate before running Phase 7.

## All-NaN factors (top 30 by code-count)

None.

## Per-code factor counts (sample)

| code        |   1d |
|:------------|-----:|
| 159100.XSHE |  472 |
| 159110.XSHE |  472 |
| 159131.XSHE |  472 |
| 159141.XSHE |  472 |
| 159201.XSHE |  473 |
| 159206.XSHE |  473 |
| 159207.XSHE |  473 |
| 159209.XSHE |  473 |
| 159218.XSHE |  473 |
| 159227.XSHE |  473 |
| 159232.XSHE |  473 |
| 159256.XSHE |  473 |
| 159259.XSHE |  473 |
| 159262.XSHE |  473 |
| 159263.XSHE |  473 |
| 159265.XSHE |  473 |
| 159268.XSHE |  473 |
| 159273.XSHE |  473 |
| 159309.XSHE |  473 |
| 159316.XSHE |  473 |
| 159325.XSHE |  473 |
| 159326.XSHE |  473 |
| 159329.XSHE |  473 |
| 159338.XSHE |  473 |
| 159363.XSHE |  473 |
| 159366.XSHE |  473 |
| 159368.XSHE |  473 |
| 159378.XSHE |  473 |
| 159387.XSHE |  473 |
| 159395.XSHE |  473 |

(showing first 30 of 346 codes; full table on disk at each parquet)
