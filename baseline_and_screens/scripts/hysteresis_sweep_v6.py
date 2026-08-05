"""
v6/scripts/hysteresis_sweep_v6.py
=================================
Phase 9.2 — exit-buffer sweep on the Phase 9.1 baselines.

For each of the four surviving baseline cells (long_q05, long_q10,
long_q20, ls_q20), read the persisted ensemble α + shared panels and
rebuild books under two hysteresis rules across a coarse ε grid:

    rule ∈ {"buffer", "replace"}
    ε    ∈ {0.0, 0.1, 0.2, 0.3, 0.5}

ε=0 must reproduce the checked-in ensemble_net_ret.csv bit-for-bit;
that reproduction is asserted at end of run so a silent path-dependent
bug can't slip through.

Outputs
-------
    data/v6_static/hysteresis_sweep/summary.csv       — one row per
        (cell, rule, epsilon): turnover / selection / sizing / cost
        bps/yr / gross+net Sharpe IS/OOS/full / mean K held / holdings-
        change per bar.
    data/v6_static/hysteresis_sweep/{cell}_{rule}_eps{XX}_bar.csv
        — per-bar detail for the plotting later; only written when
        DETAIL_BARS=True (default False to keep the tree small).

Run
---
    python v6/scripts/hysteresis_sweep_v6.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# --- v6/common sys.path bootstrap ---
import sys as _v6_sys
from pathlib import Path as _V6Path
_v6_p = _V6Path(__file__).resolve().parent
while _v6_p.name != "v6" and _v6_p.parent != _v6_p:
    _v6_p = _v6_p.parent
_v6_sys.path.insert(0, str(_v6_p / "common"))
del _v6_p
# --------------------------------------
import _common_v6 as C
import xs_engine_v6 as E
import hysteresis_engine_v6 as H
import cost_attribution_v6 as CA


CELLS: tuple[tuple[str, float], ...] = (
    ("long", 0.05),
    ("long", 0.10),
    ("long", 0.20),
    ("ls",   0.20),
)
RULES:    tuple[str, ...]   = ("buffer", "replace")
EPSILONS: tuple[float, ...] = (0.0, 0.1, 0.2, 0.3, 0.5)

COST_PER_TRADE = E.DEFAULT_COST_PER_TRADE
OUT_ROOT = C.DATA_DIR / "v6_static" / "hysteresis_sweep"

DETAIL_BARS = False   # flip True to persist per-bar CSVs for every run


# ---------------------------------------------------------------------- #
# Loaders — reproduce xs_screen_v6._load_inputs shape (minus factor caches)
# ---------------------------------------------------------------------- #
def _load_shared(data_dir: Path) -> dict:
    mem = pd.read_parquet(data_dir / "universe_v6" / "membership.parquet")
    codes = list(mem.columns[mem.any(axis=0)])
    mem = mem[codes].astype(bool)
    fwd   = pd.read_parquet(data_dir / "panels_v6" / "fwd_1w.parquet")[codes]
    sigma = pd.read_parquet(data_dir / "panels_v6" / "sigma_causal_26w.parquet")[codes]
    return {"membership": mem, "codes": codes, "fwd_1w": fwd, "sigma": sigma}


def _cell_tag(mode: str, q: float) -> str:
    return f"{mode}_q{int(round(q * 100)):02d}"


def _load_ensemble_alpha(data_dir: Path, mode: str, q: float) -> pd.DataFrame:
    cell = _cell_tag(mode, q)
    return pd.read_parquet(data_dir / "v6_static" / cell / "ensemble_alpha.parquet")


def _load_baseline_net_ret(data_dir: Path, mode: str, q: float) -> pd.Series:
    cell = _cell_tag(mode, q)
    df = pd.read_csv(data_dir / "v6_static" / cell / "ensemble_net_ret.csv",
                     index_col=0, parse_dates=[0])
    return df["net_ret"].astype(float)


# ---------------------------------------------------------------------- #
# One (cell, rule, ε) run
# ---------------------------------------------------------------------- #
def _run_one(alpha: pd.DataFrame, shared: dict,
             mode: str, q: float, epsilon: float, rule: str
             ) -> tuple[E.BookResult, dict]:
    W, N_t, K_t = H.build_hysteresis_weights(
        alpha, shared["sigma"], shared["membership"],
        q=q, mode=mode, epsilon=epsilon, rule=rule,
    )
    res = E.run_book(W, shared["fwd_1w"],
                     cost_per_trade=COST_PER_TRADE, N_t=N_t, K_t=K_t)

    # Turnover decomposition — reuse cost_attribution_v6 to stay consistent
    # with the Phase 6.5 headline definitions.
    attrib = CA.decompose_turnover(res.weights)

    port_ret = res.port_ret
    net_ret  = res.net_ret
    cost     = attrib.total * COST_PER_TRADE

    win_gross = CA._split_windows(port_ret)
    win_net   = CA._split_windows(net_ret)
    win_cost  = CA._split_windows(cost)
    win_total = CA._split_windows(attrib.total)
    win_sel   = CA._split_windows(attrib.selection)
    win_size  = CA._split_windows(attrib.sizing)

    def _bps_yr(s: pd.Series) -> float:
        return float(s.mean() * C.WEEKS_PER_YEAR * 1e4)

    def _ann_ret(s: pd.Series) -> float:
        """Arithmetic annualized return (mean × 52). Same convention as
        xs_engine_v6._window_sharpe.ann_ret. Fractional units."""
        if len(s) < 1:
            return 0.0
        return float(s.mean()) * C.WEEKS_PER_YEAR

    def _cagr(s: pd.Series) -> float:
        """CAGR on the constant-notional NAV path (NAV_t = 1 + Σ net_ret).
        Same convention as xs_engine_v6._window_sharpe.cagr — guards a
        blown NAV with max(1e-9, ...) before the fractional power.
        Fractional units."""
        n = len(s)
        if n < 1:
            return 0.0
        cumret = float(s.sum())
        n_years = max(n / C.WEEKS_PER_YEAR, 1e-3)
        return max(1.0 + cumret, 1e-9) ** (1.0 / n_years) - 1.0

    # Held-count change per bar — a raw diagnostic for the buffer rule
    # (which lets |held| float in [K, K + slots in buffer band]).
    held_now  = (res.weights != 0.0).sum(axis=1)
    held_diff = held_now.diff().abs().fillna(0.0)

    row = {
        "cell":    _cell_tag(mode, q),
        "mode":    mode,
        "q":       q,
        "rule":    rule,
        "epsilon": epsilon,
        # Sharpe (gross vs net, per window)
        "gross_sharpe_is":   CA._sharpe(win_gross["is"]),
        "net_sharpe_is":     CA._sharpe(win_net["is"]),
        "gross_sharpe_oos":  CA._sharpe(win_gross["oos"]),
        "net_sharpe_oos":    CA._sharpe(win_net["oos"]),
        "gross_sharpe_full": CA._sharpe(win_gross["full"]),
        "net_sharpe_full":   CA._sharpe(win_net["full"]),
        # Return / cost drag (full-window bps/yr headline)
        "gross_ret_bps_yr":  _bps_yr(win_gross["full"]),
        "net_ret_bps_yr":    _bps_yr(win_net["full"]),
        "cost_bps_yr":       _bps_yr(win_cost["full"]),
        # Annualized return (arithmetic mean × 52) — per window
        "gross_ann_ret_is":   _ann_ret(win_gross["is"]),
        "gross_ann_ret_oos":  _ann_ret(win_gross["oos"]),
        "gross_ann_ret_full": _ann_ret(win_gross["full"]),
        "net_ann_ret_is":     _ann_ret(win_net["is"]),
        "net_ann_ret_oos":    _ann_ret(win_net["oos"]),
        "net_ann_ret_full":   _ann_ret(win_net["full"]),
        # CAGR on constant-notional NAV — per window
        "gross_cagr_is":      _cagr(win_gross["is"]),
        "gross_cagr_oos":     _cagr(win_gross["oos"]),
        "gross_cagr_full":    _cagr(win_gross["full"]),
        "net_cagr_is":        _cagr(win_net["is"]),
        "net_cagr_oos":       _cagr(win_net["oos"]),
        "net_cagr_full":      _cagr(win_net["full"]),
        # Turnover channels
        "turnover_total":     float(win_total["full"].mean()),
        "turnover_selection": float(win_sel["full"].mean()),
        "turnover_sizing":    float(win_size["full"].mean()),
        # Position diagnostics
        "held_mean":          float(held_now.reindex(win_net["full"].index).mean()),
        "held_change_mean":   float(held_diff.reindex(win_net["full"].index).mean()),
        "K_mean":             float(K_t.reindex(win_net["full"].index).mean()),
        "n_bars":             int(len(win_net["full"])),
    }
    denom = row["turnover_total"] if row["turnover_total"] > 0 else np.nan
    row["sizing_share"]    = float(row["turnover_sizing"]    / denom) if denom else 0.0
    row["selection_share"] = float(row["turnover_selection"] / denom) if denom else 0.0
    row["cost_share_of_gross"] = (
        float(row["cost_bps_yr"] / row["gross_ret_bps_yr"])
        if row["gross_ret_bps_yr"] > 0 else np.nan
    )
    return res, row


# ---------------------------------------------------------------------- #
# Baseline reproduction guard
# ---------------------------------------------------------------------- #
def _assert_baseline_match(res: E.BookResult,
                           baseline_net: pd.Series,
                           cell: str, rule: str) -> None:
    """ε=0 must reproduce the checked-in ensemble_net_ret.csv within
    numeric noise on the intersection of grids."""
    idx = res.net_ret.index.intersection(baseline_net.index)
    if len(idx) == 0:
        raise AssertionError(
            f"[{cell}/{rule}/eps=0] baseline grid empty intersection"
        )
    diff = (res.net_ret.reindex(idx) - baseline_net.reindex(idx)).abs()
    if diff.max() > 1e-10:
        # Find the first offending bar for the traceback
        first_bad = diff[diff > 1e-10].index[0]
        raise AssertionError(
            f"[{cell}/{rule}/eps=0] baseline reproduction failed: "
            f"max |Δ net_ret| = {diff.max():.3g}, first at {first_bad}"
        )


# ---------------------------------------------------------------------- #
# Top-level driver
# ---------------------------------------------------------------------- #
def run(data_dir: Path | None = None) -> pd.DataFrame:
    data_dir = Path(data_dir) if data_dir else C.DATA_DIR
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    shared = _load_shared(data_dir)

    rows: list[dict] = []
    for mode, q in CELLS:
        cell = _cell_tag(mode, q)
        alpha = _load_ensemble_alpha(data_dir, mode, q)
        baseline_net = _load_baseline_net_ret(data_dir, mode, q)

        for rule in RULES:
            for eps in EPSILONS:
                res, row = _run_one(alpha, shared, mode, q, eps, rule)
                rows.append(row)

                if eps == 0.0:
                    _assert_baseline_match(res, baseline_net, cell, rule)

                if DETAIL_BARS:
                    bar_df = pd.DataFrame({
                        "port_ret": res.port_ret,
                        "net_ret":  res.net_ret,
                        "turnover": res.turnover,
                        "K":        res.K_t,
                        "N":        res.N_t,
                    }).reindex(res.port_ret.index)
                    stub = f"{cell}_{rule}_eps{int(round(eps*100)):02d}"
                    bar_df.to_csv(OUT_ROOT / f"{stub}_bar.csv")

                print(
                    f"  {cell:>8s}  {rule:>7s}  ε={eps:.2f}  "
                    f"turn={row['turnover_total']:.3f} "
                    f"(sel={row['turnover_selection']:.3f}, "
                    f"size={row['turnover_sizing']:.3f})  "
                    f"cost={row['cost_bps_yr']:6.1f} bps/yr  "
                    f"gross→net Sharpe (full)= "
                    f"{row['gross_sharpe_full']:+.3f} → "
                    f"{row['net_sharpe_full']:+.3f}   "
                    f"|H|̄={row['held_mean']:.2f}"
                )

    summary = pd.DataFrame(rows)
    summary.to_csv(OUT_ROOT / "summary.csv", index=False)
    print(f"\nwrote {OUT_ROOT / 'summary.csv'}  ({len(summary)} rows)")
    return summary


if __name__ == "__main__":
    run()
