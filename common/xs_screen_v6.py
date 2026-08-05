"""
v6/scripts/xs_screen_v6.py
==========================
Phase 9.1 — static baseline screener for the v6 pool.

For a given (mode, q) grid cell (mode ∈ {"long", "ls"}, q ∈ (0, 1]) the
pipeline is:

    1. Screen — for every factor F in the v6 factor-cache intersection,
       both polarities (orig / rev), run the static book (weekly W-FRI,
       vol-scaled top-q). Record (IS Sharpe, OOS Sharpe, decay, turnover).
    2. Filter — keep rows with in_sharpe ≥ 0.5, out_sharpe ≥ 0.2,
       decay ≥ 0.3 (v4/v5 thresholds, reused for continuity).
    3. Dedup — greedy walk sorted by full Sharpe desc, drop any factor
       with |ρ| > 0.3 against a kept representative. Correlation is
       computed on the polarity-adjusted stage-2 CS-Gaussian-rank panels
       (matches v4pool's pv_sweep_xs dedup step).
    4. Ensemble — for each kept factor, per-bar row-z-score its α panel
       (sign-oriented via polarity); mean across kept factors → single
       ensemble α on the W-FRI grid.
    5. Book   — run the ensemble α through the static engine at the same
       (mode, q); write score / sharpe / diag CSVs.

Outputs per cell live in ``data/v6_static/{mode}_q{qq}/`` where ``qq =
int(round(q*100))``:

    all_factors.csv     — one row per (factor, polarity)
    relaxed.csv         — filter survivors
    dedup.csv           — dedup survivors (the kept set)
    dropped.csv         — dedup dropouts + representative + |ρ|
    ensemble_alpha.parquet    — the T×N ensemble α panel
    ensemble_weights.parquet  — the T×N book weight panel
    ensemble_net_ret.csv      — per-bar net return of the ensemble book
    ensemble_sharpe.csv       — one-row summary
    ensemble_picks.csv        — per-bar list of long/short picks (long side)

Run
---
    python v6/scripts/xs_screen_v6.py --mode long --q 0.2     # one cell
    python v6/scripts/xs_screen_v6.py --grid                  # all 6 cells
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

import _common_v6 as C
import xs_engine_v6 as E


# ---------------------------------------------------------------------- #
# Grid + thresholds
# ---------------------------------------------------------------------- #
MODES = ("long", "ls")
QS    = (0.05, 0.10, 0.20)

MIN_IN_SHARPE   = 0.5
MIN_OUT_SHARPE  = 0.2
MIN_DECAY       = 0.3
DEDUP_THRESHOLD = 0.3

OUT_ROOT = C.DATA_DIR / "v6_static"


# ---------------------------------------------------------------------- #
# Cell tag helpers
# ---------------------------------------------------------------------- #
def _q_tag(q: float) -> str:
    return f"q{int(round(q * 100)):02d}"


def _cell_tag(mode: str, q: float) -> str:
    return f"{mode}_{_q_tag(q)}"


def _cell_dir(mode: str, q: float, out_root: Path = OUT_ROOT) -> Path:
    return out_root / _cell_tag(mode, q)


# ---------------------------------------------------------------------- #
# Inputs — panels + factor caches
# ---------------------------------------------------------------------- #
def _load_inputs(data_dir: Path) -> dict:
    """Load MEMBERSHIP + panels + factor caches. Panels come from Phase 6."""
    mem = pd.read_parquet(data_dir / "universe_v6" / "membership.parquet")
    codes = list(mem.columns[mem.any(axis=0)])
    mem = mem[codes].astype(bool)

    fwd   = pd.read_parquet(data_dir / "panels_v6" / "fwd_1w.parquet")[codes]
    sigma = pd.read_parquet(data_dir / "panels_v6" / "sigma_causal_26w.parquet")[codes]

    caches = C.load_caches_v6("1d", codes)
    common = C.common_factors_v6(caches)
    if not common:
        raise RuntimeError("no common factors in v6 cache — build Phase 4 first")

    return {
        "membership": mem,
        "codes": codes,
        "fwd_1w": fwd,
        "sigma": sigma,
        "caches": caches,
        "common_factors": common,
        "daily_index": _union_daily_index(caches),
    }


def _union_daily_index(caches: dict) -> pd.DatetimeIndex:
    """Union of every cache's daily index. Using any single cache's index
    truncates other codes' history — e.g. 159100.XSHE was listed 2025-11
    and its cache only covers Nov 2025+, so picking it as the reference
    would zero out every other code's older bars."""
    idx = pd.DatetimeIndex([])
    for df in caches.values():
        idx = idx.union(df.index)
    return idx.sort_values()


def _weekly_alpha(caches: dict, factor: str,
                  rebal: pd.DatetimeIndex,
                  codes: list[str],
                  daily_index: pd.DatetimeIndex | None = None
                  ) -> pd.DataFrame:
    """Reindex each cache's factor Series directly to the W-FRI grid.

    Skips the intermediate daily-union DataFrame that
    ``build_alpha_panel_v6`` would build (~344×1972 cells per factor,
    dominant cost when iterated over 472 factors × 2 polarities × 6
    grid cells). Holiday-Fri entries stay NaN — those bars fall out of
    the engine's eligibility mask.
    """
    cols = {}
    for c in codes:
        df = caches.get(c)
        if df is None or factor not in df.columns:
            continue
        s = df[factor]
        if s.notna().any():
            cols[c] = s.reindex(rebal)
    if not cols:
        return pd.DataFrame(index=rebal, columns=codes, dtype=float)
    return pd.DataFrame(cols, index=rebal).reindex(columns=codes)


# ---------------------------------------------------------------------- #
# Stage-2 rank cache (for dedup + ensemble)
# ---------------------------------------------------------------------- #
def _stage2_panel(A_weekly: pd.DataFrame) -> pd.DataFrame:
    """Stage-1 expanding z (per name) then stage-2 CS Gaussian rank (per
    bar). Reuse _common_v6 helpers so the transform matches the ragged
    IC screening pipeline."""
    A1 = C.expanding_z(A_weekly)
    return C.cs_gaussian_rank(A1)


# ---------------------------------------------------------------------- #
# Step 1 — screen every factor × polarity
# ---------------------------------------------------------------------- #
def screen_cell(mode: str, q: float, data: dict,
                out_dir: Path,
                cost_per_trade: float = E.DEFAULT_COST_PER_TRADE
                ) -> pd.DataFrame:
    """Per-factor / per-polarity backtest → all_factors.csv."""
    codes = data["codes"]
    mem   = data["membership"]
    fwd   = data["fwd_1w"]
    sigma = data["sigma"]
    caches = data["caches"]
    common = data["common_factors"]
    rebal = fwd.index

    print(f"[{_cell_tag(mode, q)}] screening {len(common)} factors × 2 polarities")
    t0 = time.time()
    rows: list[dict] = []
    for i, f in enumerate(common):
        if i and i % 40 == 0:
            print(f"  ... {i}/{len(common)}   ({time.time() - t0:.1f}s)")
        A = _weekly_alpha(caches, f, rebal, codes, daily_index=data["daily_index"])
        if A.shape[1] < 2 or A.notna().to_numpy().sum() == 0:
            continue
        for pol_name, Apol in (("orig", A), ("rev", -A)):
            _res, s = E.backtest_alpha(Apol, sigma, fwd, mem, q, mode,
                                       cost_per_trade=cost_per_trade)
            rows.append({
                "factor":            f if pol_name == "orig" else f"{f}_rev",
                "base":              f,
                "polarity":          pol_name,
                "sharpe":            s.full_sharpe,
                "in_sharpe":         s.is_sharpe,
                "out_sharpe":        s.oos_sharpe,
                "decay_ratio":       s.decay_ratio,
                "is_cumret":         s.is_cumret,
                "oos_cumret":        s.oos_cumret,
                "full_cumret":       s.full_cumret,
                "is_cagr":           s.is_cagr,
                "oos_cagr":          s.oos_cagr,
                "full_cagr":         s.full_cagr,
                "is_max_dd":         s.is_max_dd,
                "oos_max_dd":        s.oos_max_dd,
                "full_max_dd":       s.full_max_dd,
                "annual_vol":        s.annual_vol,
                "avg_turnover":      s.avg_turnover,
                "net_exposure_mean": s.net_exposure_mean,
                "gross_mean":        s.gross_mean,
                "mean_N":            s.mean_N,
                "mean_K":            s.mean_K,
                "is_bars":           s.is_bars,
                "oos_bars":          s.oos_bars,
                "n_bars":            s.n_bars,
            })

    df = pd.DataFrame(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "all_factors.csv", index=False)
    print(f"  wrote all_factors.csv  ({len(df)} rows, {time.time() - t0:.1f}s)")
    return df


# ---------------------------------------------------------------------- #
# Step 2 — filter
# ---------------------------------------------------------------------- #
def filter_cell(all_factors: pd.DataFrame,
                out_dir: Path) -> pd.DataFrame:
    mask = ((all_factors["in_sharpe"]   >= MIN_IN_SHARPE) &
            (all_factors["out_sharpe"]  >= MIN_OUT_SHARPE) &
            (all_factors["decay_ratio"] >= MIN_DECAY))
    kept = (all_factors[mask]
                .copy()
                .sort_values("sharpe", ascending=False)
                .reset_index(drop=True))
    kept.to_csv(out_dir / "relaxed.csv", index=False)
    print(f"  filter: {int(mask.sum())}/{len(all_factors)} pass "
          f"(in≥{MIN_IN_SHARPE}, out≥{MIN_OUT_SHARPE}, decay≥{MIN_DECAY})")
    return kept


# ---------------------------------------------------------------------- #
# Step 3 — bond-style dedup (walk best-first, |corr|>0.3 → drop)
# ---------------------------------------------------------------------- #
def _flatten_stage2(kept: pd.DataFrame, data: dict) -> pd.DataFrame:
    """Stack each kept factor's polarity-adjusted stage-2 rank panel to a
    (T·N)-row column. Used only for the inter-factor correlation matrix."""
    caches = data["caches"]
    codes  = data["codes"]
    rebal  = data["fwd_1w"].index
    mem    = data["membership"]
    cols: dict[str, pd.Series] = {}
    for _, r in kept.iterrows():
        A = _weekly_alpha(caches, r["base"], rebal, codes, daily_index=data["daily_index"])
        if A.shape[1] < 2:
            continue
        if r["polarity"] == "rev":
            A = -A
        A = C.apply_membership(A, mem)
        A2 = _stage2_panel(A)
        cols[r["factor"]] = A2.stack(future_stack=True)
    return pd.DataFrame(cols)


def _greedy_bondstyle(kept: pd.DataFrame,
                      corr_abs: pd.DataFrame,
                      threshold: float
                      ) -> tuple[list[str], dict[str, tuple[str, float]]]:
    order = kept.sort_values("sharpe", ascending=False)["factor"].tolist()
    keep: list[str] = []
    drop_rep: dict[str, tuple[str, float]] = {}
    dropped: set[str] = set()
    for f in order:
        if f not in corr_abs.index or f in dropped:
            continue
        keep.append(f)
        for other in order:
            if (other != f and other in corr_abs.columns
                    and other not in keep and other not in dropped):
                c = float(corr_abs.at[f, other])
                if c > threshold:
                    dropped.add(other)
                    drop_rep[other] = (f, c)
    return keep, drop_rep


def dedup_cell(kept: pd.DataFrame, data: dict,
               out_dir: Path,
               threshold: float = DEDUP_THRESHOLD
               ) -> tuple[pd.DataFrame, dict]:
    if len(kept) == 0:
        (out_dir / "dedup.csv").write_text("")
        print("  dedup: no survivors")
        return pd.DataFrame(), {}
    if len(kept) == 1:
        kept.to_csv(out_dir / "dedup.csv", index=False)
        print("  dedup: 1 survivor (nothing to compare)")
        return kept, {}

    flat = _flatten_stage2(kept, data)
    corr_abs = flat.corr().abs().fillna(0.0)
    keep, drop_rep = _greedy_bondstyle(kept, corr_abs, threshold)

    kept_df = (kept[kept["factor"].isin(keep)]
                  .set_index("factor")
                  .loc[keep]
                  .reset_index())
    kept_df.to_csv(out_dir / "dedup.csv", index=False)

    dropped_rows = [
        {**kept.set_index("factor").loc[f].to_dict(),
         "factor": f, "representative": rep, "corr_to_rep": c}
        for f, (rep, c) in drop_rep.items()
    ]
    if dropped_rows:
        pd.DataFrame(dropped_rows).to_csv(out_dir / "dropped.csv", index=False)

    print(f"  dedup: {len(kept)} → {len(kept_df)} kept "
          f"({len(dropped_rows)} dropped at |ρ|>{threshold})")
    return kept_df, drop_rep


# ---------------------------------------------------------------------- #
# Step 4 — ensemble α (row-z of raw α per factor, mean across factors)
# ---------------------------------------------------------------------- #
def _rowwise_zscore(A: pd.DataFrame) -> pd.DataFrame:
    """Per-bar z: (A - row_mean) / row_std, skipna. Zero-variance rows
    (all-equal α) → NaN so they contribute nothing to the mean."""
    mu = A.mean(axis=1)
    sd = A.std(axis=1, ddof=1).replace(0.0, np.nan)
    return A.sub(mu, axis=0).div(sd, axis=0)


def build_ensemble_alpha(kept: pd.DataFrame, data: dict) -> pd.DataFrame:
    """v4pool convention (`build_combined_v5.ensemble_alpha`): per-bar
    row-z the polarity-adjusted raw α of each kept factor, then average
    across factors.

    Preserves magnitudes — a factor with a strong conviction pick (large
    z on one name) drives the ensemble mean toward that name. An earlier
    version used stage-2 CS Gaussian rank; that step erased conviction
    (rank is monotone-only) and produced a consensus signal that
    catastrophically underperformed. See ``diagnose_ensemble_v6.py`` for
    the side-by-side numbers.
    """
    codes  = data["codes"]
    rebal  = data["fwd_1w"].index
    mem    = data["membership"]

    if len(kept) == 0:
        return pd.DataFrame(np.nan, index=rebal, columns=codes)

    stack = []
    for _, r in kept.iterrows():
        A = _weekly_alpha(data["caches"], r["base"], rebal, codes,
                          daily_index=data["daily_index"])
        if r["polarity"] == "rev":
            A = -A
        A = C.apply_membership(A, mem)
        Z = _rowwise_zscore(A).reindex(columns=codes)
        stack.append(Z.values)
    arr = np.stack(stack, axis=0)  # (K, T, N)
    with np.errstate(invalid="ignore"):
        m = np.nanmean(arr, axis=0)
    return pd.DataFrame(m, index=rebal, columns=codes)


# ---------------------------------------------------------------------- #
# Step 5 — book on the ensemble α
# ---------------------------------------------------------------------- #
def book_on_ensemble(alpha_ens: pd.DataFrame, data: dict, mode: str, q: float,
                     out_dir: Path,
                     cost_per_trade: float = E.DEFAULT_COST_PER_TRADE
                     ) -> tuple[E.BookResult, E.BookSummary]:
    res, summ = E.backtest_alpha(alpha_ens, data["sigma"], data["fwd_1w"],
                                 data["membership"], q, mode,
                                 cost_per_trade=cost_per_trade)
    alpha_ens.to_parquet(out_dir / "ensemble_alpha.parquet")
    res.weights.to_parquet(out_dir / "ensemble_weights.parquet")
    res.net_ret.to_frame("net_ret").to_csv(out_dir / "ensemble_net_ret.csv")
    pd.DataFrame([asdict(summ) | {"mode": mode, "q": q}]).to_csv(
        out_dir / "ensemble_sharpe.csv", index=False)
    _write_picks(res.weights, out_dir / "ensemble_picks.csv")
    return res, summ


def _write_picks(W: pd.DataFrame, path: Path) -> None:
    """One row per (bar, side, code) for downstream inspection. Small
    file — only stores non-zero weights."""
    stacked = W.stack(future_stack=True)
    nz = stacked[stacked != 0.0].rename("weight").reset_index()
    nz.columns = ["date", "code", "weight"]
    nz["side"] = np.where(nz["weight"] > 0, "long", "short")
    nz.to_csv(path, index=False)


# ---------------------------------------------------------------------- #
# Cell driver
# ---------------------------------------------------------------------- #
def run_cell(mode: str, q: float, data: dict | None = None,
             data_dir: Path | None = None,
             out_root: Path = OUT_ROOT,
             cost_per_trade: float = E.DEFAULT_COST_PER_TRADE
             ) -> dict:
    """Full pipeline for one (mode, q) cell. Returns the per-cell summary
    dict (also written to ``ensemble_sharpe.csv``)."""
    if data is None:
        data_dir = Path(data_dir) if data_dir else C.DATA_DIR
        data = _load_inputs(data_dir)

    out_dir = _cell_dir(mode, q, out_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print(f"CELL {mode.upper()}  q={q:.2f}  ->  {out_dir}")
    print("=" * 72)

    all_f = screen_cell(mode, q, data, out_dir, cost_per_trade=cost_per_trade)
    relaxed = filter_cell(all_f, out_dir)
    kept, _drops = dedup_cell(relaxed, data, out_dir)
    alpha_ens = build_ensemble_alpha(kept, data)
    _res, summ = book_on_ensemble(alpha_ens, data, mode, q, out_dir,
                                   cost_per_trade=cost_per_trade)

    print(f"  ENSEMBLE: kept={len(kept)}  IS Sharpe={summ.is_sharpe:+.3f}  "
          f"OOS Sharpe={summ.oos_sharpe:+.3f}  decay={summ.decay_ratio:+.2f}  "
          f"turnover={summ.avg_turnover:.3f}")
    return {"mode": mode, "q": q, "kept_n": int(len(kept)),
            "relaxed_n": int(len(relaxed)), "screened_n": int(len(all_f)),
            **asdict(summ)}


# ---------------------------------------------------------------------- #
# Grid driver
# ---------------------------------------------------------------------- #
def run_grid(data_dir: Path | None = None,
             out_root: Path = OUT_ROOT,
             modes: tuple[str, ...] = MODES,
             qs: tuple[float, ...] = QS) -> pd.DataFrame:
    data = _load_inputs(Path(data_dir) if data_dir else C.DATA_DIR)
    print(f"pool: {len(data['codes'])} codes, {len(data['fwd_1w'])} W-FRI bars, "
          f"{len(data['common_factors'])} common factors")
    print(f"IS end: {C.IN_SAMPLE_END.date()}   OOS: "
          f"{C.OOS_START.date()} → {C.OOS_END.date()}")
    rows = []
    for mode in modes:
        for q in qs:
            rows.append(run_cell(mode, q, data=data, out_root=out_root))
    df = pd.DataFrame(rows)
    df.to_csv(out_root / "grid_summary.csv", index=False)
    print(f"\nwrote {out_root / 'grid_summary.csv'}")
    return df


# ---------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=MODES)
    ap.add_argument("--q", type=float)
    ap.add_argument("--grid", action="store_true",
                    help="run the full 2×3 (mode, q) grid")
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--out-root", type=Path, default=OUT_ROOT)
    args = ap.parse_args()

    if args.grid:
        run_grid(args.data_dir, args.out_root)
    else:
        if not (args.mode and args.q):
            ap.error("give --grid OR --mode + --q")
        run_cell(args.mode, args.q,
                 data_dir=args.data_dir, out_root=args.out_root)


if __name__ == "__main__":
    main()
