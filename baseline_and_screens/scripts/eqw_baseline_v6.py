"""
v6/scripts/eqw_baseline_v6.py
=============================
Phase 8.2 — equal-weight baseline (no fitting).

For each variant's shortlist:
  1. Build membership-masked weekly α per factor.
  2. Multiply by ``sign(zstat_full)`` so every panel is +IC-oriented.
  3. Per-bar row-z-score each factor's α, then average across factors.
     This matches ``xs_screen_v6.build_ensemble_alpha`` (v6 convention).

Ensembling choice — row-z of raw α, NOT stage-2 CS rank
-------------------------------------------------------
The v4pool ``eqw_baseline.py`` averaged stage-2 CS Gaussian ranks. The
Phase 9.1 diagnostic (``diagnose_ensemble_v6.py``) showed on the v6 pool
that rank-averaging destroys conviction (rank is monotone-only), so the
consensus α has very high turnover and mediocre book Sharpe. Row-z of
raw α preserves magnitude — a factor with a strong top pick moves the
ensemble mean toward that name — and produces the +1.052 vs +0.193
(long q=0.05 IS) gap that Phase 9.1 documented. v6 uses row-z; this
port follows the v6 convention, not v4pool's.

Two reports on the ensemble α:
  A. **Alpha diagnostics** — per-bar Spearman IC vs ỹ on IS and OOS,
     ragged zstat, prec@q at q = 0.10 (top + bottom). This is the
     alpha-quality benchmark the future return model must beat.
  B. **Book diagnostics** — run the ensemble α through ``xs_engine_v6``
     at the Phase 9.1 grid (mode ∈ {long, ls}, q ∈ {0.05, 0.10, 0.20})
     with 10 bp / side turnover cost. Reports net Sharpe / turnover /
     cost — directly comparable to ``book_xs_v6_report.md`` numbers.

Variants
--------
  dedup_v6      = all 28 factors in ``data/pv_sweep_xs_v6_dedup.csv``
                  (post-|zstat| ≥ 2, |ρ| ≤ 0.5)
  stability_v6  = subset that also passes ``stability_halfsplit_v6``
                  (halfsplit sign + |zstat_half| ≥ 1.5 on both halves)

Since equal-weight uses no training data, "IS" and "OOS" here are just
calendar splits at ``IN_SAMPLE_END``, not train/test.

Outputs
-------
    data/eqw_baseline_v6/{variant}/ensemble_alpha.parquet
    data/eqw_baseline_v6/{variant}/alpha_diagnostics.csv
    data/eqw_baseline_v6/{variant}/book_grid.csv
    reports/eqw_baseline_v6_report.md

Run
---
    python v6/scripts/eqw_baseline_v6.py
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
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


PRECISION_Q  = 0.10
BOOK_GRID    = tuple(("long", q) for q in (0.05, 0.10, 0.20)) + \
               tuple(("ls",   q) for q in (0.05, 0.10, 0.20))
OUT_ROOT     = C.DATA_DIR / "eqw_baseline_v6"


# ---------------------------------------------------------------------- #
# Inputs
# ---------------------------------------------------------------------- #
def _load_inputs(data_dir: Path) -> dict:
    mem = pd.read_parquet(data_dir / "universe_v6" / "membership.parquet")
    codes = list(mem.columns[mem.any(axis=0)])
    mem = mem[codes].astype(bool)

    y     = pd.read_parquet(data_dir / "panels_v6" / "label_ranked_risk_adj.parquet")[codes]
    fwd   = pd.read_parquet(data_dir / "panels_v6" / "fwd_1w.parquet")[codes]
    sigma = pd.read_parquet(data_dir / "panels_v6" / "sigma_causal_26w.parquet")[codes]

    sweep = pd.read_csv(data_dir / "pv_sweep_xs_v6.csv")
    dedup = pd.read_csv(data_dir / "pv_sweep_xs_v6_dedup.csv")
    stab_p = data_dir / "stability_halfsplit_v6.csv"
    if not stab_p.exists():
        raise SystemExit(f"missing {stab_p} — run stability_halfsplit_v6.py first")
    stab  = pd.read_csv(stab_p)

    caches = C.load_caches_v6("1d", codes)
    return {
        "membership": mem, "codes": codes,
        "label": y, "fwd_1w": fwd, "sigma": sigma,
        "sweep": sweep, "dedup": dedup, "stability": stab,
        "caches": caches,
    }


def _weekly_alpha(caches: dict, factor: str,
                  rebal: pd.DatetimeIndex,
                  codes: list[str]) -> pd.DataFrame:
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
# Variants
# ---------------------------------------------------------------------- #
def _build_variants(data: dict) -> dict[str, dict]:
    """Return {variant_name: {'factors': [...], 'signs': {factor: ±1}}}.

    Sign is ``sign(zstat_full)`` on the IS-only Phase 7 sweep — a negative
    zstat means the factor is a good SHORT signal, entered flipped.
    """
    sweep_sign = dict(
        zip(data["sweep"]["factor"],
            np.where(data["sweep"]["zstat"] < 0, -1, 1).astype(int))
    )

    dedup_factors = data["dedup"]["factor"].tolist()
    stab_factors  = data["stability"].loc[data["stability"]["pass"],
                                          "factor"].tolist()

    return {
        "dedup_v6": {
            "factors": dedup_factors,
            "signs":   {f: sweep_sign[f] for f in dedup_factors},
        },
        "stability_v6": {
            "factors": stab_factors,
            "signs":   {f: sweep_sign[f] for f in stab_factors},
        },
    }


# ---------------------------------------------------------------------- #
# Ensemble α — row-z of sign-oriented raw α (matches xs_screen_v6)
# ---------------------------------------------------------------------- #
def _rowwise_zscore(A: pd.DataFrame) -> pd.DataFrame:
    """Per-bar z: (A - row_mean) / row_std, skipna. Zero-variance rows → NaN."""
    mu = A.mean(axis=1)
    sd = A.std(axis=1, ddof=1).replace(0.0, np.nan)
    return A.sub(mu, axis=0).div(sd, axis=0)


def build_ensemble_alpha(factors: list[str], signs: dict[str, int],
                         data: dict) -> pd.DataFrame:
    """Per-bar mean of the sign-oriented row-z panels (nanmean across
    factors). Membership mask applied to raw α before the z-score.

    Row-z of raw α (not stage-2 CS rank) — see module docstring for why
    v6 uses this convention. Matches ``xs_screen_v6.build_ensemble_alpha``.
    """
    rebal = data["membership"].index
    codes = data["codes"]
    mem   = data["membership"]
    if not factors:
        return pd.DataFrame(np.nan, index=rebal, columns=codes)

    stack = []
    for f in factors:
        A = _weekly_alpha(data["caches"], f, rebal, codes)
        A = C.apply_membership(A, mem)
        if signs[f] < 0:
            A = -A
        Z = _rowwise_zscore(A).reindex(index=rebal, columns=codes)
        stack.append(Z.values)
    arr = np.stack(stack, axis=0)   # (K, T, N)
    with np.errstate(invalid="ignore"):
        m = np.nanmean(arr, axis=0)
    return pd.DataFrame(m, index=rebal, columns=codes)


# ---------------------------------------------------------------------- #
# Diagnostics
# ---------------------------------------------------------------------- #
def _alpha_diagnostics(alpha: pd.DataFrame, data: dict) -> dict[str, dict]:
    """Per-bar IC + prec@q + ragged zstat on IS and OOS windows."""
    rebal = data["membership"].index
    is_bars  = rebal[rebal <= C.IN_SAMPLE_END]
    oos_bars = rebal[(rebal >= C.OOS_START) & (rebal <= C.OOS_END)]

    out: dict[str, dict] = {}
    for name, idx in [("IS", is_bars), ("OOS", oos_bars)]:
        ic  = C.per_bar_spearman(alpha.loc[idx], data["label"].loc[idx])
        N_t = C.per_bar_n_valid(alpha.loc[idx], data["label"].loc[idx],
                                membership=data["membership"])
        s   = C.ic_summary(ic, n_per_bar=N_t)
        pt  = C.precision_at_q(alpha.loc[idx], data["label"].loc[idx],
                               q=PRECISION_Q, side="top",
                               membership=data["membership"])
        pb  = C.precision_at_q(alpha.loc[idx], data["label"].loc[idx],
                               q=PRECISION_Q, side="bottom",
                               membership=data["membership"])
        out[name] = {
            "n_bars":       int(s["n_bars"]),
            "mean_ic":      float(s["mean"]),
            "zstat":        float(s["zstat"]),
            "mean_ic_w":    float(s["mean_ic_w"]),
            "mean_N":       float(s["mean_N"]),
            "pct_pos":      float(s["pct_pos"]),
            "mean_ic_52w":  float(s["mean_ic_52w"]),
            "pct_pos_52w":  float(s["pct_pos_52w"]),
            f"prec_top_q{int(PRECISION_Q*100):02d}":
                float(pt.dropna().mean()) if pt.notna().any() else np.nan,
            f"prec_bot_q{int(PRECISION_Q*100):02d}":
                float(pb.dropna().mean()) if pb.notna().any() else np.nan,
        }
    return out


def _book_grid(alpha: pd.DataFrame, data: dict,
               cost_per_trade: float = E.DEFAULT_COST_PER_TRADE
               ) -> pd.DataFrame:
    """Run the ensemble α through xs_engine_v6 at every (mode, q) cell.
    Returns one row per cell (net-of-cost per [[feedback-backtests-cost-on]])."""
    rows = []
    for mode, q in BOOK_GRID:
        _res, summ = E.backtest_alpha(alpha, data["sigma"], data["fwd_1w"],
                                       data["membership"], q, mode,
                                       cost_per_trade=cost_per_trade)
        rows.append({"mode": mode, "q": q, **asdict(summ)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------- #
# Report
# ---------------------------------------------------------------------- #
def _fmt(v: float, spec: str) -> str:
    return "n/a" if not np.isfinite(v) else format(v, spec)


def _load_static_baseline(data_dir: Path) -> pd.DataFrame | None:
    """Read Phase 9.1 static-baseline grid_summary.csv for the side-by-side
    comparison table. Returns None if absent."""
    p = data_dir / "v6_static" / "grid_summary.csv"
    if not p.exists():
        return None
    return pd.read_csv(p)


def _write_report(variants: dict[str, dict],
                  alpha_diag: dict[str, dict[str, dict]],
                  book_grid: dict[str, pd.DataFrame],
                  static_baseline: pd.DataFrame | None,
                  reports_dir: Path,
                  cost_per_trade: float) -> str:
    lines: list[str] = []
    lines.append("# Phase 8.2 — equal-weight baseline (v6)\n")
    lines.append(
        "Naive baseline: per-bar mean of the sign-oriented row-z-scored raw α "
        "panels across a shortlist of Phase 7 survivors. No fitting, no "
        "per-factor weight. **This is what the future return model must beat.**\n"
    )
    lines.append(
        "**Ensembling**: row-z of raw α (v6 convention, matches "
        "`xs_screen_v6.build_ensemble_alpha`). The v4pool convention averaged "
        "stage-2 CS-rank panels; Phase 9.1's `diagnose_ensemble_v6.py` showed "
        "on the v6 pool that rank-averaging destroys conviction and produces "
        "high-turnover, low-Sharpe books. Row-z keeps magnitude structure.\n"
    )
    lines.append(
        "IS / OOS here are calendar splits at 2023-12-31 — with no fitting, "
        "IS is not a 'training' window and OOS is not 'held out' in the "
        "usual sense; they are same-regime and shifted-regime evaluation "
        "windows respectively.\n"
    )

    lines.append("## Variants\n")
    for vname, vspec in variants.items():
        fs = vspec["factors"]
        signs = vspec["signs"]
        sign_str = ", ".join(
            f"`{f}`{'⁻' if signs[f] < 0 else ''}" for f in fs
        ) if fs else "_(empty)_"
        lines.append(f"- **{vname}** ({len(fs)}): {sign_str}")

    # A. Alpha diagnostics
    lines.append("\n## A. Alpha diagnostics\n")
    lines.append(f"Per-bar Spearman IC vs ỹ + prec@q at q = {PRECISION_Q:.2f}. "
                 "Ragged `zstat = mean(ic·√(N-1)) · √T` is the primary metric.\n")
    lines.append("| variant | period | n_bars | mean_ic | zstat | mean_ic_w | mean_N | "
                 "pct_pos | mean_ic_52w | pct_pos_52w | "
                 f"prec@top{int(PRECISION_Q*100)}% | prec@bot{int(PRECISION_Q*100)}% |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for vname in variants.keys():
        for pname in ("IS", "OOS"):
            d = alpha_diag[vname][pname]
            lines.append(
                f"| {vname} | {pname} | {d['n_bars']} | "
                f"{_fmt(d['mean_ic'], '+.4f')} | {_fmt(d['zstat'], '+.2f')} | "
                f"{_fmt(d['mean_ic_w'], '+.4f')} | {_fmt(d['mean_N'], '.1f')} | "
                f"{_fmt(d['pct_pos']*100, '.1f')}% | "
                f"{_fmt(d['mean_ic_52w'], '+.3f')} | "
                f"{_fmt(d['pct_pos_52w']*100, '.1f')}% | "
                f"{_fmt(d[f'prec_top_q{int(PRECISION_Q*100):02d}'], '.3f')} | "
                f"{_fmt(d[f'prec_bot_q{int(PRECISION_Q*100):02d}'], '.3f')} |"
            )

    # B. Book diagnostics
    lines.append("\n## B. Book diagnostics (net of "
                 f"{cost_per_trade*1e4:.0f} bp/side turnover cost)\n")
    lines.append(
        "Ensemble α through `xs_engine_v6` at the Phase 9.1 grid. "
        "Vol-scaled inside selection (`w ∝ 1/σ_causal_26w`). Windows: IS ≤ "
        "2023-12-31, OOS 2024-01-01→2025-07-31, full = IS ∪ OOS (hold-out "
        "sealed). Sharpe / cumret / DD are net of cost.\n"
    )
    lines.append(
        "**Comparability**: this is the same engine + grid + cost that "
        "produced `book_xs_v6_report.md`, but the α source is different — "
        "there it was per-cell book-screened, here it is Phase 7 IC-shortlisted "
        "(then sign-oriented and equal-weighted). Both are cost-net, so "
        "Sharpe / turnover numbers are directly comparable.\n"
    )
    for vname, grid in book_grid.items():
        lines.append(f"\n### {vname}\n")
        lines.append("| mode | q | IS Sharpe | OOS Sharpe | full Sharpe | decay | "
                     "IS cumret | OOS cumret | full cumret | full DD | "
                     "avg turnover | mean_K |")
        lines.append("|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for _, r in grid.iterrows():
            lines.append(
                f"| {r['mode']} | {r['q']:.2f} | "
                f"{r['is_sharpe']:+.3f} | {r['oos_sharpe']:+.3f} | "
                f"{r['full_sharpe']:+.3f} | {r['decay_ratio']:+.2f} | "
                f"{r['is_cumret']*100:+.2f}% | {r['oos_cumret']*100:+.2f}% | "
                f"{r['full_cumret']*100:+.2f}% | {r['full_max_dd']*100:+.2f}% | "
                f"{r['avg_turnover']:.3f} | {r['mean_K']:.1f} |"
            )

    # C. Side-by-side vs Phase 9.1 static baseline
    if static_baseline is not None and len(book_grid):
        lines.append("\n## C. vs Phase 9.1 static baseline — 'beat this' targets\n")
        lines.append(
            "Side-by-side of the strongest EQW variant on this shortlist vs "
            "the Phase 9.1 per-cell book-screened baseline "
            "(`book_xs_v6_report.md`). Both are net-of-cost, same engine, "
            "same grid — the α source is the only difference. Numbers a "
            "future return model needs to beat live in the 9.1 column; the "
            "EQW column is the trivial-fitting floor.\n"
        )
        best_variant = max(
            book_grid.keys(),
            key=lambda v: book_grid[v]["full_sharpe"].max(),
        )
        lines.append(f"Best EQW variant (by max full Sharpe across grid): "
                     f"**{best_variant}**\n")
        lines.append("| mode | q | 9.1 static full Sharpe | EQW full Sharpe | Δ (EQW − 9.1) | "
                     "9.1 turnover | EQW turnover |")
        lines.append("|:---:|:---:|---:|---:|---:|---:|---:|")
        eqw = book_grid[best_variant]
        for _, r in eqw.iterrows():
            sb = static_baseline[
                (static_baseline["mode"] == r["mode"])
                & (np.isclose(static_baseline["q"], r["q"]))
            ]
            if len(sb) == 0:
                continue
            sb0 = sb.iloc[0]
            delta = r["full_sharpe"] - sb0["full_sharpe"]
            lines.append(
                f"| {r['mode']} | {r['q']:.2f} | "
                f"{sb0['full_sharpe']:+.3f} | {r['full_sharpe']:+.3f} | "
                f"{delta:+.3f} | "
                f"{sb0['avg_turnover']:.3f} | {r['avg_turnover']:.3f} |"
            )

    lines.append("\n## Files\n")
    lines.append("- per-variant ensemble α : `data/eqw_baseline_v6/{variant}/ensemble_alpha.parquet`")
    lines.append("- alpha diagnostics       : `data/eqw_baseline_v6/{variant}/alpha_diagnostics.csv`")
    lines.append("- book grid summary       : `data/eqw_baseline_v6/{variant}/book_grid.csv`")

    reports_dir.mkdir(parents=True, exist_ok=True)
    p = reports_dir / "eqw_baseline_v6_report.md"
    p.write_text("\n".join(lines))
    return str(p)


# ---------------------------------------------------------------------- #
# Driver
# ---------------------------------------------------------------------- #
def run(data_dir: Path | None = None,
        reports_dir: Path | None = None,
        cost_per_trade: float = E.DEFAULT_COST_PER_TRADE) -> None:
    data_dir    = Path(data_dir)    if data_dir    else C.DATA_DIR
    reports_dir = Path(reports_dir) if reports_dir else C.REPORTS_DIR

    data = _load_inputs(data_dir)
    variants = _build_variants(data)

    print("=" * 78)
    print(f"Phase 8.2 EQW baseline — cost = {cost_per_trade*1e4:.0f} bp/side")
    print("=" * 78)
    for vname, v in variants.items():
        print(f"  {vname}: {len(v['factors'])} factors")

    alpha_diag: dict[str, dict[str, dict]] = {}
    book_grid:  dict[str, pd.DataFrame] = {}
    for vname, vspec in variants.items():
        print(f"\n[{vname}]  building ensemble α...")
        alpha = build_ensemble_alpha(vspec["factors"], vspec["signs"], data)
        out_dir = OUT_ROOT / vname
        out_dir.mkdir(parents=True, exist_ok=True)
        alpha.to_parquet(out_dir / "ensemble_alpha.parquet")

        diag = _alpha_diagnostics(alpha, data)
        alpha_diag[vname] = diag
        pd.DataFrame(diag).T.to_csv(out_dir / "alpha_diagnostics.csv")

        grid = _book_grid(alpha, data, cost_per_trade=cost_per_trade)
        book_grid[vname] = grid
        grid.to_csv(out_dir / "book_grid.csv", index=False)

        # Console preview
        for pname, d in diag.items():
            print(f"  [{pname}]  n_ic={d['n_bars']:>3d}  "
                  f"mean_ic={d['mean_ic']:+.4f}  zstat={d['zstat']:+.2f}  "
                  f"mean_N={d['mean_N']:.1f}  "
                  f"prec@top{int(PRECISION_Q*100)}%="
                  f"{d[f'prec_top_q{int(PRECISION_Q*100):02d}']:.3f}")
        print(f"  book grid (net Sharpe):")
        for _, r in grid.iterrows():
            print(f"    {r['mode']:>4s} q={r['q']:.2f}   "
                  f"IS={r['is_sharpe']:+.3f}  OOS={r['oos_sharpe']:+.3f}  "
                  f"full={r['full_sharpe']:+.3f}  "
                  f"turn={r['avg_turnover']:.3f}")

    static_baseline = _load_static_baseline(data_dir)
    report_p = _write_report(variants, alpha_diag, book_grid,
                             static_baseline, reports_dir, cost_per_trade)
    print(f"\nwrote {report_p}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir",    type=Path, default=None)
    ap.add_argument("--reports-dir", type=Path, default=None)
    args = ap.parse_args()
    run(args.data_dir, args.reports_dir)


if __name__ == "__main__":
    main()
