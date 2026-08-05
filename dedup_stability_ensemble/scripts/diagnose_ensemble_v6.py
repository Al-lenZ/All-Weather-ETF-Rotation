"""
v6/scripts/diagnose_ensemble_v6.py
==================================
Diagnostic — why does the v6 static ensemble underperform its kept factors?

For a given (mode, q) cell, load the dedup kept set and compare four
Sharpes on the ensemble book:

  (a) individual — recompute each kept factor's book, print its
      IS/OOS/full Sharpe (regression check against dedup.csv). Also
      print the arithmetic mean of individual Sharpes.

  (b) ensemble-of-books — average each factor's *net-return series*
      equally, then compute Sharpe on the averaged series. Isolates
      "portfolio-of-books" behavior (correlations of per-bar P&L) from
      the signal-averaging + top-K reselection that (c) and (d) do.

  (c) signal-mean, CS Gaussian rank — the current xs_screen_v6.build_
      ensemble_alpha: stage-1 expanding-z + stage-2 CS Gaussian rank
      per factor, mean across factors, feed to top-K engine.
      Sharpe should reproduce the number in the cell's
      ensemble_sharpe.csv.

  (d) signal-mean, row-wise z — v4pool convention: per-bar row-z each
      factor's raw α (no CS Gaussian rank), mean, feed to top-K engine.
      Preserves magnitudes; a factor with outlier picks contributes
      proportionally rather than as a normal-quantile.

Prints one table per cell and writes the same to
``reports/diagnose_ensemble_v6.md``.

Run
---
    python v6/scripts/diagnose_ensemble_v6.py                     # long_q20 only
    python v6/scripts/diagnose_ensemble_v6.py --cells all         # every cell
    python v6/scripts/diagnose_ensemble_v6.py --mode long --q 0.1
"""
from __future__ import annotations

import argparse
from datetime import datetime
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
import xs_screen_v6 as S


DEFAULT_CELL   = ("long", 0.20)


# ---------------------------------------------------------------------- #
# Alternative combiners
# ---------------------------------------------------------------------- #
def _rowwise_zscore(A: pd.DataFrame) -> pd.DataFrame:
    """Per-bar z: (A - row_mean) / row_std. skipna. NaN rows stay NaN."""
    mu = A.mean(axis=1)
    sd = A.std(axis=1, ddof=1).replace(0.0, np.nan)
    Z  = A.sub(mu, axis=0).div(sd, axis=0)
    return Z


def _ensemble_alpha_rowz(kept: pd.DataFrame, data: dict) -> pd.DataFrame:
    """(d): row-z per factor, mean across factors. No stage-2 rank."""
    codes = data["codes"]; rebal = data["fwd_1w"].index; mem = data["membership"]
    if len(kept) == 0:
        return pd.DataFrame(np.nan, index=rebal, columns=codes)
    stack = []
    for _, r in kept.iterrows():
        A = S._weekly_alpha(data["caches"], r["base"], rebal, codes,
                            daily_index=data["daily_index"])
        if r["polarity"] == "rev":
            A = -A
        A = C.apply_membership(A, mem)
        Z = _rowwise_zscore(A).reindex(columns=codes)
        stack.append(Z.values)
    arr = np.stack(stack, axis=0)
    with np.errstate(invalid="ignore"):
        m = np.nanmean(arr, axis=0)
    return pd.DataFrame(m, index=rebal, columns=codes)


# ---------------------------------------------------------------------- #
# Cell driver
# ---------------------------------------------------------------------- #
def diagnose_cell(mode: str, q: float, data: dict,
                  out_root: Path = S.OUT_ROOT) -> dict:
    cell_dir = S._cell_dir(mode, q, out_root)
    dedup = pd.read_csv(cell_dir / "dedup.csv") if (cell_dir / "dedup.csv").stat().st_size else pd.DataFrame()
    if dedup.empty:
        print(f"[{S._cell_tag(mode, q)}] no kept factors — nothing to diagnose")
        return {"mode": mode, "q": q, "kept_n": 0}

    print("=" * 72)
    print(f"DIAGNOSE {S._cell_tag(mode, q)}  ({len(dedup)} kept factors)")
    print("=" * 72)

    fwd   = data["fwd_1w"]
    sigma = data["sigma"]
    mem   = data["membership"]
    codes = data["codes"]
    rebal = fwd.index

    # ---- (a) individual factor Sharpes + per-bar net return series ----
    indiv_summaries = []
    indiv_net = {}
    for _, r in dedup.iterrows():
        A = S._weekly_alpha(data["caches"], r["base"], rebal, codes,
                            daily_index=data["daily_index"])
        if r["polarity"] == "rev":
            A = -A
        res, s = E.backtest_alpha(A, sigma, fwd, mem, q, mode)
        indiv_summaries.append({
            "factor": r["factor"],
            "IS Sharpe":  s.is_sharpe,
            "OOS Sharpe": s.oos_sharpe,
            "full":       s.full_sharpe,
            "turnover":   s.avg_turnover,
        })
        indiv_net[r["factor"]] = res.net_ret

    indiv_df = pd.DataFrame(indiv_summaries)
    mean_is  = float(indiv_df["IS Sharpe"].mean())
    mean_oos = float(indiv_df["OOS Sharpe"].mean())
    print("\n(a) INDIVIDUAL factor books (recomputed from dedup):")
    print(indiv_df.to_string(index=False,
        formatters={"IS Sharpe":lambda x:f"{x:+.3f}",
                    "OOS Sharpe":lambda x:f"{x:+.3f}",
                    "full":lambda x:f"{x:+.3f}",
                    "turnover":lambda x:f"{x:.3f}"}))
    print(f"    → mean of individual Sharpes:  IS={mean_is:+.3f}   OOS={mean_oos:+.3f}")

    # ---- (b) ensemble-of-books: equal-weight NAV average --------------
    idx = None
    for series in indiv_net.values():
        idx = series.index if idx is None else idx.intersection(series.index)
    NR = pd.DataFrame({k: v.reindex(idx) for k, v in indiv_net.items()})
    eob_net = NR.mean(axis=1)                # simple equal-weight combine
    eob_is,  _, _, _ = E._window_sharpe(eob_net[eob_net.index <= C.IN_SAMPLE_END])
    eob_oos, _, _, _ = E._window_sharpe(eob_net[(eob_net.index >= C.OOS_START) &
                                                (eob_net.index <= C.OOS_END)])
    print(f"\n(b) ENSEMBLE-OF-BOOKS (mean of net-return series):")
    print(f"    IS Sharpe={eob_is:+.3f}   OOS Sharpe={eob_oos:+.3f}")

    # ---- (c) signal-mean w/ CS Gaussian rank (current production) ----
    alpha_rank = S.build_ensemble_alpha(dedup, data)
    res_c, s_c = E.backtest_alpha(alpha_rank, sigma, fwd, mem, q, mode)
    print(f"\n(c) SIGNAL-MEAN with CS Gaussian rank (current prod):")
    print(f"    IS Sharpe={s_c.is_sharpe:+.3f}   OOS Sharpe={s_c.oos_sharpe:+.3f}   "
          f"turnover={s_c.avg_turnover:.3f}   mean_K={s_c.mean_K:.1f}")

    # ---- (d) signal-mean w/ row-wise z-score (v4pool convention) -----
    alpha_rowz = _ensemble_alpha_rowz(dedup, data)
    res_d, s_d = E.backtest_alpha(alpha_rowz, sigma, fwd, mem, q, mode)
    print(f"\n(d) SIGNAL-MEAN with row-wise z-score (v4pool convention):")
    print(f"    IS Sharpe={s_d.is_sharpe:+.3f}   OOS Sharpe={s_d.oos_sharpe:+.3f}   "
          f"turnover={s_d.avg_turnover:.3f}   mean_K={s_d.mean_K:.1f}")

    # ---- Correlation of the four net-return series (in OOS) ----------
    def _oos(x): return x[(x.index >= C.OOS_START) & (x.index <= C.OOS_END)]
    corr = pd.DataFrame({
        "individual_mean_ret": NR.mean(axis=1),
        "ensemble_rank":       res_c.net_ret,
        "ensemble_rowz":       res_d.net_ret,
    }).apply(_oos).corr()
    print(f"\n    OOS net-return correlation matrix:")
    print(corr.to_string(float_format=lambda x: f"{x:+.3f}"))

    return {
        "mode": mode, "q": q,
        "kept_n":              int(len(dedup)),
        "indiv_mean_is":       mean_is,
        "indiv_mean_oos":      mean_oos,
        "eob_is":              eob_is,
        "eob_oos":             eob_oos,
        "rank_is":             s_c.is_sharpe,
        "rank_oos":            s_c.oos_sharpe,
        "rowz_is":             s_d.is_sharpe,
        "rowz_oos":            s_d.oos_sharpe,
    }


# ---------------------------------------------------------------------- #
def _write_report(rows: list[dict], report_path: Path) -> None:
    df = pd.DataFrame(rows)
    if df.empty:
        return
    lines: list[str] = []
    lines.append("# v6 static — ensemble-vs-individual diagnostic\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    lines.append(
        "Four ways to summarize the (mode, q) cell's Sharpe:\n"
        "- **indiv mean** = arithmetic mean of the kept factors' *individual* "
        "book Sharpes.\n"
        "- **ensemble-of-books** = Sharpe of the equal-weight average of "
        "kept factors' net-return series. Portfolio of separately-run books.\n"
        "- **signal-mean rank** = current production: mean the stage-2 CS "
        "Gaussian rank panels, then run one book on the average. Ordering-only.\n"
        "- **signal-mean row-z** = v4pool convention: mean the per-bar row-z "
        "of raw α panels, then run one book. Preserves magnitudes.\n"
    )
    lines.append("| mode | q | kept | indiv mean IS | indiv mean OOS | "
                 "eob IS | eob OOS | rank IS | rank OOS | rowz IS | rowz OOS |")
    lines.append("|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in df.iterrows():
        lines.append(
            f"| {r['mode']} | {r['q']:.2f} | {int(r['kept_n'])} | "
            f"{r['indiv_mean_is']:+.3f} | {r['indiv_mean_oos']:+.3f} | "
            f"{r['eob_is']:+.3f} | {r['eob_oos']:+.3f} | "
            f"{r['rank_is']:+.3f} | {r['rank_oos']:+.3f} | "
            f"{r['rowz_is']:+.3f} | {r['rowz_oos']:+.3f} |"
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines))
    print(f"\nwrote {report_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", choices=("default", "all"), default="default")
    ap.add_argument("--mode", choices=S.MODES)
    ap.add_argument("--q",    type=float)
    args = ap.parse_args()

    data = S._load_inputs(C.DATA_DIR)

    if args.mode and args.q:
        cells = [(args.mode, args.q)]
    elif args.cells == "all":
        cells = [(m, q) for m in S.MODES for q in S.QS]
    else:
        cells = [DEFAULT_CELL]

    rows = [x for x in (diagnose_cell(m, q, data) for m, q in cells)
            if x.get("kept_n", 0) > 0]
    _write_report(rows, C.REPORTS_DIR / "diagnose_ensemble_v6.md")


if __name__ == "__main__":
    main()
