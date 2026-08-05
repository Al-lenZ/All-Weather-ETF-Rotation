# Phase 6 sanity — panels_v6 vs MEMBERSHIP

Generated: 2026-07-20 10:28:27  

MEMBERSHIP: 425 W-FRI bars × 344 ever-admitted codes, 46,793 member-bars total  


## Hard gate — no defined entry outside membership

A cell is a **leak** if the panel value is non-NaN but MEMBERSHIP is False at that (bar, code). The mask is supposed to zero these out (see `_common_v6.apply_membership`).

| panel | leaks | verdict |
|---|---:|:---|
| fwd_1w | 0 | **PASS** |
| sigma | 0 | **PASS** |
| label | 0 | **PASS** |

## Coverage — fraction of member-bars with a defined value

Coverage < 100% is expected but should be understood:
- `fwd_1w`: NaN at each name's last member-bar (needs t+1 close) and at delisting boundaries.
- `sigma`: NaN during rolling-vol warmup — a newly seasoned name may be admitted before 26 weekly log-returns exist in the data window (e.g., seasoning was gated on `list_date + 26w` but data begins later than list_date).
- `label` (ỹ): NaN wherever either input is NaN, plus rows with < `min_valid` finite entries (rare on the v6 pool).


### fwd_1w   —   overall 99.4% (46,534/46,793)

| year | members | defined | coverage |
|---:|---:|---:|---:|
| 2018 |     365 |     365 | 100.0% |
| 2019 |    1070 |    1070 | 100.0% |
| 2020 |    2376 |    2376 | 100.0% |
| 2021 |    3671 |    3671 | 100.0% |
| 2022 |    5614 |    5614 | 100.0% |
| 2023 |    7336 |    7336 | 100.0% |
| 2024 |    8685 |    8685 | 100.0% |
| 2025 |   10414 |   10414 | 100.0% |
| 2026 |    7262 |    7003 |  96.4% |

### sigma   —   overall 99.4% (46,507/46,793)

| year | members | defined | coverage |
|---:|---:|---:|---:|
| 2018 |     365 |      79 |  21.6% |
| 2019 |    1070 |    1070 | 100.0% |
| 2020 |    2376 |    2376 | 100.0% |
| 2021 |    3671 |    3671 | 100.0% |
| 2022 |    5614 |    5614 | 100.0% |
| 2023 |    7336 |    7336 | 100.0% |
| 2024 |    8685 |    8685 | 100.0% |
| 2025 |   10414 |   10414 | 100.0% |
| 2026 |    7262 |    7262 | 100.0% |

### label   —   overall 98.8% (46,248/46,793)

| year | members | defined | coverage |
|---:|---:|---:|---:|
| 2018 |     365 |      79 |  21.6% |
| 2019 |    1070 |    1070 | 100.0% |
| 2020 |    2376 |    2376 | 100.0% |
| 2021 |    3671 |    3671 | 100.0% |
| 2022 |    5614 |    5614 | 100.0% |
| 2023 |    7336 |    7336 | 100.0% |
| 2024 |    8685 |    8685 | 100.0% |
| 2025 |   10414 |   10414 | 100.0% |
| 2026 |    7262 |    7003 |  96.4% |

## Files

- `data/panels_v6/fwd_1w.parquet`
- `data/panels_v6/sigma_causal_26w.parquet`
- `data/panels_v6/label_ranked_risk_adj.parquet`

## Gate

Hard gate (no leaks outside MEMBERSHIP): **PASS**.
