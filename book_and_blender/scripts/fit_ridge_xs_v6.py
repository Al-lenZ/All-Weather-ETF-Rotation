"""
v6/scripts/fit_ridge_xs_v6.py
=============================
Phase 8.3 — pooled ridge fit on the v6 pool.

Features
--------
Stage-2 CS Gaussian rank of the shortlist factors from Phase 7. Sign
column applied at load time so every feature enters +IC-oriented (from
`sign(zstat_full)` on `data/pv_sweep_xs_v6.csv`). Membership mask
applied before stage-1 expanding-z.

Target
------
ỹ = per-bar CS Gaussian rank of `fwd_1w / σ_causal_26w`
(`panels_v6/label_ranked_risk_adj.parquet`).

Model
-----
`sklearn.linear_model.Ridge(alpha=α, fit_intercept=False, solver='cholesky')`.
Per-bar CS-ranking makes X and y row-mean-zero, so no intercept /
fixed-effect terms.

WF-CV
-----
Expanding train, `init_train=78` W-FRI bars (~1.5 y), `step=13`
(~quarter), `purge=1`. α grid `{0.01, 0.1, 1.0, 10.0}`. α* chosen on
max IS-OOF mean per-bar Spearman IC (OOS bars never see the α
selection).

Variants
--------
    dedup_v6      — 28 features (Phase 7 dedup shortlist)
    stability_v6  —  5 features (halfsplit survivors)

Book
----
After fit, wide-pivot the α* OOF `s_hat` into a `T×N` score panel and
run it through `xs_engine_v6` at the (mode, q) grid used by Phase 9.1
and 8.2. Cost stays on (10 bp/side per `feedback_backtests_cost_on`).

Outputs
-------
    data/fit_ridge_xs_v6/{variant}/
        ridge_alpha_grid.csv     α × (IS/OOS OOF IC) grid
        ridge_oof.csv            long-form OOF predictions at α*
        ridge_fold_coefs.csv     per-fold β at α*
        ridge_score.parquet      T×N wide OOF score at α*
        book_grid.csv            book Sharpe/turnover per (mode, q)
    reports/fit_ridge_xs_v6_report.md

Run
---
    python v6/scripts/fit_ridge_xs_v6.py
"""
from __future__ import annotations

import argparse
import warnings
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

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


# ---------------------------------------------------------------------- #
# CV plan (matches v4pool for direct comparability)
# ---------------------------------------------------------------------- #
CV_INITIAL_TRAIN = 78
CV_STEP          = 13
CV_PURGE         = 1
ALPHA_GRID       = [0.01, 0.1, 1.0, 10.0]
STABILITY_LAST_N = 5
MIN_TRAIN_ROWS   = 100

BOOK_GRID = tuple(("long", q) for q in (0.05, 0.10, 0.20)) + \
            tuple(("ls",   q) for q in (0.05, 0.10, 0.20))

VARIANTS = ("dedup_v6", "stability_v6")
OUT_ROOT = C.DATA_DIR / "fit_ridge_xs_v6"


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
    stab  = pd.read_csv(data_dir / "stability_halfsplit_v6.csv")
    stab_survivors = stab.loc[stab["pass"], "factor"].tolist()

    variants = {
        "dedup_v6":     dedup["factor"].tolist(),
        "stability_v6": stab_survivors,
    }

    sign_map = dict(zip(
        sweep["factor"],
        np.where(sweep["zstat"] < 0, -1, 1).astype(int),
    ))

    # Only need to build stage-2 for the union — stability ⊂ dedup, so
    # dedup alone covers both variants.
    union_factors = sorted(set().union(*variants.values()))

    caches = C.load_caches_v6("1d", codes)
    return {
        "membership":     mem, "codes": codes,
        "label":          y, "fwd_1w": fwd, "sigma": sigma,
        "caches":         caches,
        "variants":       variants,
        "signs":          sign_map,
        "union_factors":  union_factors,
    }


# ---------------------------------------------------------------------- #
# Stage-2 feature panels (membership-masked, sign-oriented)
# ---------------------------------------------------------------------- #
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


def _build_stage2(data: dict) -> dict[str, pd.DataFrame]:
    mem   = data["membership"]
    codes = data["codes"]
    rebal = mem.index
    signs = data["signs"]
    out: dict[str, pd.DataFrame] = {}
    for f in data["union_factors"]:
        A = _weekly_alpha(data["caches"], f, rebal, codes)
        A = C.apply_membership(A, mem)
        A2 = C.cs_gaussian_rank(C.expanding_z(A))
        if signs[f] < 0:
            A2 = -A2
        out[f] = A2
    return out


# ---------------------------------------------------------------------- #
# Long panel builder for a given variant's feature list
# ---------------------------------------------------------------------- #
def _build_long_panel(stage2: dict[str, pd.DataFrame],
                      factors: list[str],
                      y: pd.DataFrame,
                      fwd: pd.DataFrame,
                      rebal: pd.DatetimeIndex,
                      codes: list[str]) -> pd.DataFrame:
    """One row per (bar, code) with all factor columns + y_tilde + fwd_1w."""
    frames = []
    for c in codes:
        rows = pd.DataFrame(
            {f: stage2[f][c].reindex(rebal) for f in factors},
            index=rebal,
        )
        rows["y_tilde"] = y[c].reindex(rebal)
        rows["fwd_1w"] = fwd[c].reindex(rebal)
        rows["etf"]  = c
        rows["date"] = rebal
        frames.append(rows)
    long = pd.concat(frames, axis=0, ignore_index=True)
    return long.sort_values(["date", "etf"]).reset_index(drop=True)


# ---------------------------------------------------------------------- #
# Walk-forward CV
# ---------------------------------------------------------------------- #
def _walk_forward(long_all: pd.DataFrame,
                  x_cols: list[str],
                  alpha: float
                  ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One α, one full WF pass over the whole (IS ∪ OOS) date grid.

    Returns (oof_long, fold_coefs). Each test fold's period tag is 'IS'
    if its whole window sits within IS, 'OOS' if fully OOS, else 'BRIDGE'
    (used for accounting only; the α selection uses IS OOF only).
    """
    dates = pd.DatetimeIndex(sorted(long_all["date"].unique()))
    n = len(dates)
    oof_rows: list[pd.DataFrame] = []
    fold_rows: list[dict] = []

    fold_id = 0
    start_test = CV_INITIAL_TRAIN + CV_PURGE
    while start_test < n:
        end_test = min(start_test + CV_STEP, n)
        train_end = dates[start_test - CV_PURGE - 1]
        test_dates = dates[start_test:end_test]

        train = long_all[long_all["date"] <= train_end]
        test  = long_all[long_all["date"].isin(test_dates)]

        mask_tr = train[x_cols + ["y_tilde"]].notna().all(axis=1)
        if int(mask_tr.sum()) < MIN_TRAIN_ROWS:
            start_test = end_test
            fold_id += 1
            continue

        Xt = train.loc[mask_tr, x_cols].astype(float).values
        yt = train.loc[mask_tr, "y_tilde"].astype(float).values
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            reg = Ridge(alpha=alpha, fit_intercept=False, solver="cholesky")
            reg.fit(Xt, yt)

        mask_te = test[x_cols].notna().all(axis=1).values
        s_hat = np.full(len(test), np.nan)
        if mask_te.any():
            s_hat[mask_te] = reg.predict(
                test.loc[mask_te, x_cols].astype(float).values
            )

        df = test[["date", "etf", "fwd_1w", "y_tilde"]].copy().reset_index(drop=True)
        df["s_hat"] = s_hat
        df["fold"]  = fold_id
        df["period"] = np.where(
            df["date"] <= C.IN_SAMPLE_END, "IS",
            np.where(df["date"] <= C.OOS_END, "OOS", "HOLDOUT")
        )
        oof_rows.append(df)

        fold_rows.append({
            "fold":       fold_id,
            "train_end":  train_end,
            "test_start": test_dates.min(),
            "test_end":   test_dates.max(),
            "n_train":    int(mask_tr.sum()),
            "period":     ("IS"     if test_dates.max() <= C.IN_SAMPLE_END
                           else "OOS"     if test_dates.min() > C.IN_SAMPLE_END and test_dates.max() <= C.OOS_END
                           else "HOLDOUT" if test_dates.min() > C.OOS_END
                           else "BRIDGE"),
            **{f"coef_{c}": float(v) for c, v in zip(x_cols, reg.coef_)},
        })

        start_test = end_test
        fold_id += 1

    if not oof_rows:
        return pd.DataFrame(), pd.DataFrame()
    return (pd.concat(oof_rows, axis=0, ignore_index=True),
            pd.DataFrame(fold_rows))


# ---------------------------------------------------------------------- #
# OOF diagnostics
# ---------------------------------------------------------------------- #
def _oof_per_bar_ic(oof: pd.DataFrame, period: str | None = None) -> pd.Series:
    if oof.empty:
        return pd.Series(dtype=float)
    o = oof if period is None else oof[oof["period"] == period]
    if o.empty:
        return pd.Series(dtype=float)
    s = o.pivot(index="date", columns="etf", values="s_hat")
    y = o.pivot(index="date", columns="etf", values="y_tilde")
    return C.per_bar_spearman(s, y)


def _oof_score_panel(oof: pd.DataFrame,
                     rebal: pd.DatetimeIndex,
                     codes: list[str]) -> pd.DataFrame:
    """Wide-pivot the OOF long panel to a T×N score suitable for
    xs_engine_v6. Bars before the first test fold (warm-up) stay NaN."""
    if oof.empty:
        return pd.DataFrame(np.nan, index=rebal, columns=codes)
    wide = oof.pivot(index="date", columns="etf", values="s_hat")
    return wide.reindex(index=rebal, columns=codes)


# ---------------------------------------------------------------------- #
# Book grid at chosen α
# ---------------------------------------------------------------------- #
def _book_grid(score: pd.DataFrame, data: dict,
               cost_per_trade: float = E.DEFAULT_COST_PER_TRADE
               ) -> pd.DataFrame:
    rows = []
    for mode, q in BOOK_GRID:
        _res, summ = E.backtest_alpha(
            score, data["sigma"], data["fwd_1w"], data["membership"],
            q, mode, cost_per_trade=cost_per_trade,
        )
        rows.append({"mode": mode, "q": q, **asdict(summ)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------- #
# Report helpers
# ---------------------------------------------------------------------- #
def _fmt_ic(v: float) -> str:
    return "n/a" if not np.isfinite(v) else f"{v:+.4f}"


def _fmt_t(v: float) -> str:
    return "n/a" if not np.isfinite(v) else f"{v:+.2f}"


def _fmt(v: float, spec: str) -> str:
    return "n/a" if not np.isfinite(v) else format(v, spec)


def _stability_summary(fold_star: pd.DataFrame,
                       factors: list[str]) -> dict[str, dict]:
    """Median coefficient sign match across the last STABILITY_LAST_N IS folds."""
    is_folds = fold_star[fold_star["period"] == "IS"].sort_values("fold")
    tail = is_folds.tail(STABILITY_LAST_N)
    out: dict[str, dict] = {}
    for f in factors:
        vals = tail[f"coef_{f}"].to_numpy()
        med  = float(np.median(vals)) if len(vals) else 0.0
        med_sign = int(np.sign(med)) if med != 0 else 0
        matches = int(np.sum(np.sign(vals) == med_sign)) if med_sign != 0 else 0
        out[f] = {
            "median":     med,
            "sign":       med_sign,
            "matches_n":  matches,
            "matches_of": int(len(vals)),
            "vals":       [float(v) for v in vals],
        }
    return out


def _load_static_grid(data_dir: Path) -> pd.DataFrame:
    return pd.read_csv(data_dir / "v6_static" / "grid_summary.csv")


def _load_eqw_grid(data_dir: Path, variant: str) -> pd.DataFrame:
    return pd.read_csv(data_dir / "eqw_baseline_v6" / variant / "book_grid.csv")


def _load_blend_grid(data_dir: Path, variant: str) -> pd.DataFrame | None:
    p = data_dir / "blend_book_v6" / variant / "blend_grid.csv"
    if not p.exists():
        return None
    return pd.read_csv(p)


# ---------------------------------------------------------------------- #
# Per-variant driver
# ---------------------------------------------------------------------- #
def run_variant(variant: str, factors: list[str], data: dict,
                stage2: dict[str, pd.DataFrame],
                cost_per_trade: float = E.DEFAULT_COST_PER_TRADE) -> dict:
    print(f"\n[{variant}]  {len(factors)} features")
    for f in factors:
        print(f"  {f:14s}  sign={data['signs'][f]:+d}")

    out_dir = OUT_ROOT / variant
    out_dir.mkdir(parents=True, exist_ok=True)

    rebal = data["membership"].index
    long_all = _build_long_panel(
        stage2, factors, data["label"], data["fwd_1w"], rebal, data["codes"]
    )
    finite = int(long_all[factors + ["y_tilde"]].notna().all(axis=1).sum())
    print(f"  long panel: {long_all.shape}   finite train rows: {finite}")

    # ---- α grid sweep ----
    print("  α grid (WF-OOF, mean per-bar XS Spearman IC):")
    grid_rows: list[dict] = []
    oof_by_alpha:  dict[float, pd.DataFrame] = {}
    fold_by_alpha: dict[float, pd.DataFrame] = {}
    for a in ALPHA_GRID:
        oof_a, folds_a = _walk_forward(long_all, factors, alpha=a)
        oof_by_alpha[a]  = oof_a
        fold_by_alpha[a] = folds_a

        ic_is  = _oof_per_bar_ic(oof_a, "IS")
        ic_oos = _oof_per_bar_ic(oof_a, "OOS")
        s_is   = C.ic_summary(ic_is)
        s_oos  = C.ic_summary(ic_oos)
        grid_rows.append({
            "alpha": a,
            "n_folds":     int(folds_a["fold"].nunique()) if not folds_a.empty else 0,
            "ic_is_mean":  s_is["mean"],
            "ic_is_tstat": s_is["tstat"],
            "ic_is_n":     s_is["n_bars"],
            "ic_oos_mean":  s_oos["mean"],
            "ic_oos_tstat": s_oos["tstat"],
            "ic_oos_n":     s_oos["n_bars"],
        })
        print(f"    α={a:>6g}   folds={int(folds_a['fold'].nunique()):>2d}   "
              f"IS mean={_fmt_ic(s_is['mean'])} (t={_fmt_t(s_is['tstat'])}, n={s_is['n_bars']:>3d})   "
              f"OOS mean={_fmt_ic(s_oos['mean'])} (t={_fmt_t(s_oos['tstat'])}, n={s_oos['n_bars']:>3d})")

    grid_df = pd.DataFrame(grid_rows)
    grid_df.to_csv(out_dir / "ridge_alpha_grid.csv", index=False)

    # ---- α selection: max IS OOF mean IC ----
    best_row = grid_df.loc[grid_df["ic_is_mean"].idxmax()]
    alpha_star = float(best_row["alpha"])
    print(f"  chosen α = {alpha_star:g}  "
          f"(IS OOF IC mean={_fmt_ic(best_row['ic_is_mean'])}, "
          f"tstat={_fmt_t(best_row['ic_is_tstat'])})")

    oof_star  = oof_by_alpha[alpha_star]
    fold_star = fold_by_alpha[alpha_star]
    oof_star.to_csv(out_dir / "ridge_oof.csv", index=False)
    fold_star.to_csv(out_dir / "ridge_fold_coefs.csv", index=False)

    # ---- OOF score panel + book grid ----
    score = _oof_score_panel(oof_star, rebal, data["codes"])
    score.to_parquet(out_dir / "ridge_score.parquet")
    book_grid = _book_grid(score, data, cost_per_trade=cost_per_trade)
    book_grid.to_csv(out_dir / "book_grid.csv", index=False)
    print(f"  book grid (net Sharpe):")
    for _, r in book_grid.iterrows():
        print(f"    {r['mode']:>4s} q={r['q']:.2f}   "
              f"IS={r['is_sharpe']:+.3f}  OOS={r['oos_sharpe']:+.3f}  "
              f"full={r['full_sharpe']:+.3f}  turn={r['avg_turnover']:.3f}")

    # ---- coef sign stability ----
    stab = _stability_summary(fold_star, factors)

    return {
        "variant":    variant,
        "factors":    factors,
        "alpha_star": alpha_star,
        "grid_df":    grid_df,
        "fold_star":  fold_star,
        "oof_star":   oof_star,
        "stability":  stab,
        "book_grid":  book_grid,
    }


# ---------------------------------------------------------------------- #
# Report
# ---------------------------------------------------------------------- #
def _write_report(results: dict[str, dict],
                  data: dict,
                  data_dir: Path,
                  reports_dir: Path,
                  cost_per_trade: float,
                  n_bars_is: int, is_start: pd.Timestamp) -> str:
    lines: list[str] = []
    lines.append("# Phase 8.3 — pooled ridge fit (v6)\n")
    lines.append(
        "Ridge on stage-2 CS-rank features → per-bar CS Gaussian rank target "
        "ỹ. Sign-oriented so every column enters +IC. Ragged panel + "
        "membership mask applied before stage-1 expanding-z.\n"
    )
    lines.append(
        f"**Model**: `Ridge(alpha, fit_intercept=False, solver='cholesky')`.  \n"
        f"**WF-CV**: expanding, init_train={CV_INITIAL_TRAIN}, "
        f"step={CV_STEP}, purge={CV_PURGE}.  \n"
        f"**α grid**: {ALPHA_GRID}; α* on max IS-OOF mean per-bar Spearman IC.  \n"
        f"**IS window**: {is_start.date()} → {C.IN_SAMPLE_END.date()} "
        f"({n_bars_is} weekly bars). OOS: {C.OOS_START.date()} → {C.OOS_END.date()}.  \n"
        f"**Book**: OOF s_hat wide-pivoted → `xs_engine_v6` at "
        f"(long, ls) × (0.05, 0.10, 0.20); net of "
        f"{cost_per_trade*1e4:.0f} bp/side.\n"
    )

    for vname, r in results.items():
        factors = r["factors"]
        alpha_star = r["alpha_star"]
        grid_df = r["grid_df"]
        fold_star = r["fold_star"]
        stab = r["stability"]
        book_grid = r["book_grid"]
        oof_star = r["oof_star"]

        lines.append(f"\n## {vname}\n")
        feats_desc = ", ".join(
            "`{}` (sign={:+d})".format(f, data["signs"][f]) for f in factors
        )
        lines.append(f"**Features ({len(factors)}, sign-oriented +IC):** "
                     f"{feats_desc}\n")

        # α grid
        lines.append(f"\n### α grid (WF-OOF)\n")
        lines.append("| α | n_folds | IS mean | IS t | IS n | OOS mean | OOS t | OOS n |")
        lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
        for _, gr in grid_df.iterrows():
            star = " *chosen*" if float(gr["alpha"]) == alpha_star else ""
            lines.append(
                f"| {gr['alpha']:g}{star} | {int(gr['n_folds'])} | "
                f"{_fmt_ic(gr['ic_is_mean'])} | {_fmt_t(gr['ic_is_tstat'])} | "
                f"{int(gr['ic_is_n'])} | "
                f"{_fmt_ic(gr['ic_oos_mean'])} | {_fmt_t(gr['ic_oos_tstat'])} | "
                f"{int(gr['ic_oos_n'])} |"
            )
        lines.append(f"\nα\\* = **{alpha_star:g}** (max IS OOF mean IC).\n")

        # Coefficient sign stability
        lines.append(f"\n### Coefficient sign stability (last "
                     f"{STABILITY_LAST_N} IS folds at α\\*)\n")
        lines.append("| feature | median coef | sign | matches | fold coefs |")
        lines.append("|---|---:|---:|---:|---|")
        all_pass = True
        for f in factors:
            s = stab[f]
            vals_str = ", ".join(f"{v:+.3f}" for v in s["vals"])
            ok = s["matches_n"] >= 4
            if not ok:
                all_pass = False
            lines.append(
                f"| `{f}` | {s['median']:+.3f} | {s['sign']:+d} | "
                f"{s['matches_n']}/{s['matches_of']} | {vals_str} |"
            )
        verdict = "**PASS**" if all_pass else "**FAIL**"
        lines.append(f"\nSign-stability rule (≥ 4/5 folds match median sign): "
                     f"{verdict}\n")

        # OOF IC by period
        ic_is  = _oof_per_bar_ic(oof_star, "IS")
        ic_oos = _oof_per_bar_ic(oof_star, "OOS")
        s_is   = C.ic_summary(ic_is)
        s_oos  = C.ic_summary(ic_oos)
        lines.append(f"\n### OOF per-bar XS Spearman IC vs ỹ (α\\*)\n")
        lines.append("| period | n_bars | mean | std | tstat | pct_pos |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for name, s in [("IS", s_is), ("OOS", s_oos)]:
            lines.append(
                f"| {name} | {s['n_bars']} | {_fmt_ic(s['mean'])} | "
                f"{_fmt_ic(s['std'])} | {_fmt_t(s['tstat'])} | "
                f"{s['pct_pos']*100:.1f}% |"
            )

        # Book grid
        lines.append(f"\n### Ridge book — grid (net of cost, α\\*)\n")
        lines.append("| mode | q | IS Sharpe | OOS Sharpe | full Sharpe | decay | "
                     "IS cumret | OOS cumret | full cumret | full DD | "
                     "avg turnover | mean_K |")
        lines.append("|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for _, br in book_grid.iterrows():
            lines.append(
                f"| {br['mode']} | {br['q']:.2f} | "
                f"{br['is_sharpe']:+.3f} | {br['oos_sharpe']:+.3f} | "
                f"{br['full_sharpe']:+.3f} | {br['decay_ratio']:+.2f} | "
                f"{br['is_cumret']*100:+.2f}% | {br['oos_cumret']*100:+.2f}% | "
                f"{br['full_cumret']*100:+.2f}% | {br['full_max_dd']*100:+.2f}% | "
                f"{br['avg_turnover']:.3f} | {br['mean_K']:.1f} |"
            )

        # Four-way side-by-side vs static (9.1), eqw (8.2), blend (8.5), ridge (this)
        static_grid = _load_static_grid(data_dir)
        eqw_grid    = _load_eqw_grid(data_dir, vname)
        blend_grid  = _load_blend_grid(data_dir, vname)

        lines.append(f"\n### Side-by-side vs static / eqw / blend "
                     f"(full Sharpe, then OOS Sharpe)\n")
        header = ("| mode | q | static | eqw | blend | **ridge** | "
                  "Δ ridge vs static | Δ ridge vs blend |")
        sub    = "|:---:|:---:|---:|---:|---:|---:|---:|---:|"
        for label, col in [("Full Sharpe", "full_sharpe"),
                           ("OOS Sharpe",  "oos_sharpe")]:
            lines.append(f"\n**{label}**\n")
            lines.append(header)
            lines.append(sub)
            for _, br in book_grid.iterrows():
                m, q = br["mode"], br["q"]
                s_row  = static_grid[(static_grid["mode"] == m) &
                                      (np.isclose(static_grid["q"], q))]
                e_row  = eqw_grid[(eqw_grid["mode"] == m) &
                                   (np.isclose(eqw_grid["q"], q))]
                b_row  = (blend_grid[(blend_grid["mode"] == m) &
                                      (np.isclose(blend_grid["q"], q))]
                          if blend_grid is not None else pd.DataFrame())
                s_v = float(s_row[col].iloc[0]) if len(s_row) else np.nan
                e_v = float(e_row[col].iloc[0]) if len(e_row) else np.nan
                b_v = float(b_row[col].iloc[0]) if len(b_row) else np.nan
                r_v = float(br[col])
                d_static = r_v - s_v if np.isfinite(s_v) else np.nan
                d_blend  = r_v - b_v if np.isfinite(b_v) else np.nan
                lines.append(
                    f"| {m} | {q:.2f} | "
                    f"{_fmt(s_v, '+.3f')} | {_fmt(e_v, '+.3f')} | "
                    f"{_fmt(b_v, '+.3f')} | **{_fmt(r_v, '+.3f')}** | "
                    f"{_fmt(d_static, '+.3f')} | {_fmt(d_blend, '+.3f')} |"
                )

    lines.append("\n## Files\n")
    lines.append("- α grid summary        : `data/fit_ridge_xs_v6/{variant}/ridge_alpha_grid.csv`")
    lines.append("- OOF panel at α\\*      : `data/fit_ridge_xs_v6/{variant}/ridge_oof.csv`")
    lines.append("- Per-fold coefs at α\\* : `data/fit_ridge_xs_v6/{variant}/ridge_fold_coefs.csv`")
    lines.append("- OOF score panel       : `data/fit_ridge_xs_v6/{variant}/ridge_score.parquet`")
    lines.append("- Ridge book grid       : `data/fit_ridge_xs_v6/{variant}/book_grid.csv`")

    reports_dir.mkdir(parents=True, exist_ok=True)
    p = reports_dir / "fit_ridge_xs_v6_report.md"
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

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    data = _load_inputs(data_dir)

    rebal = data["membership"].index
    is_idx = rebal[rebal <= C.IN_SAMPLE_END]
    print("=" * 78)
    print(f"Phase 8.3 ridge fit — cost = {cost_per_trade*1e4:.0f} bp/side")
    print(f"IS end = {C.IN_SAMPLE_END.date()}   "
          f"OOS: {C.OOS_START.date()} → {C.OOS_END.date()}")
    print(f"Stage-2 features to build (union): "
          f"{len(data['union_factors'])}")
    print("=" * 78)

    stage2 = _build_stage2(data)

    results: dict[str, dict] = {}
    for vname in VARIANTS:
        results[vname] = run_variant(
            vname, data["variants"][vname], data, stage2,
            cost_per_trade=cost_per_trade,
        )

    report_p = _write_report(
        results, data, data_dir, reports_dir, cost_per_trade,
        len(is_idx), is_idx.min(),
    )
    print(f"\nwrote {report_p}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir",    type=Path, default=None)
    ap.add_argument("--reports-dir", type=Path, default=None)
    args = ap.parse_args()
    run(args.data_dir, args.reports_dir)


if __name__ == "__main__":
    main()
