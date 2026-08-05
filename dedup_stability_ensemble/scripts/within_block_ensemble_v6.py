"""
v6/scripts/within_block_ensemble_v6.py
======================================
Phase 13.5 — within-block factor ensemble.

Motivation. 13.4's per-factor books at q=0.20, ε=0.20 weekly
rebalance produced 3 pass on broad_cn but 0 pass on sector_cn: the
raw IC (zstat up to +4.70 on var5_60) was real, but weekly rotation
cost drag (~7 %/yr at turnover 0.35) ate the edge. A row-z + equal-
weight ensemble across the low-turnover, high-|zstat| subset should
smooth the top-K selection substantially — the ensemble score
changes less bar-to-bar than any single constituent, so top-⌈q·N_b⌉
rotates less.

Method
------
Selection filter on 13.2b kept.csv × 13.4 summary.csv (invvol
sizing turnover as the canonical measure):

    |zstat| ≥ MIN_ABSZ = 2.0    AND    turnover ≤ MAX_TURN = 0.60

Ensemble score construction (per user's project-ensembling-rowz
convention: row-z of the raw α, not stage-2 rank):

    for each surviving factor f:
        A_f       = weekly_alpha(f)
        A_f_z     = expanding_z(apply_membership(A_f))
        A_f_pol   = polarity_f · A_f_z                # "raw" or "rev"
        A_f_bloc  = A_f_pol restricted to block columns
        row_z_f   = (A_f_bloc − mean_across_names_t)
                       / std_across_names_t           # per-bar CS z

    ensemble_score = mean_across_f(row_z_f)  (skipna, per-cell)

Then feed `ensemble_score` into `hysteresis_engine_v6` at q, ε from
production (0.20, 0.20). Two sizings: 1/σ (production kernel) and
eqw (constant-σ sigma feed).

Ensemble sizes swept: **K ∈ {3, 5, 8, N_pass}** — top-K by |zstat|
after the filter, tie-break by lower turnover.

Nulls loaded from `data/within_block_book_v6/{block}/nulls.csv`
(same eqw hold-all + invvol hold-all as 13.4). Pass rule identical
to 13.4: net Sharpe > max(both nulls) AND CAGR ≥ eqw null CAGR.

IS-only (bars ≤ `C.IN_SAMPLE_END`). Cost 10 bp/side.

Outputs
-------
    data/within_block_ensemble_v6/{block}/summary.csv
    data/within_block_ensemble_v6/{block}/members_{K}.csv
    data/within_block_ensemble_v6/{block}/{K}_{sizing}_net_ret.csv
    reports/within_block_ensemble_v6_report.md

Run
---
    python v6/scripts/within_block_ensemble_v6.py
    python v6/scripts/within_block_ensemble_v6.py --max-turn 0.50
    python v6/scripts/within_block_ensemble_v6.py --min-absz 2.5
"""
from __future__ import annotations

import argparse
import time
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
import hysteresis_engine_v6 as H
from within_block_ic_v6 import _weekly_alpha


# ---------------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------------- #
BLOCK_MERGES = {"smallcap_cn": "broad_cn"}      # per user 2026-07-22
Q_DEFAULT    = 0.20
EPSILON      = 0.20
RULE         = "replace"
COST         = E.DEFAULT_COST_PER_TRADE
MIN_ABSZ     = 2.0
MAX_TURN     = 0.60
MIN_SOLO_SH  = -np.inf                          # no filter by default
K_GRID_BASE  = (3, 5, 8)                        # + "all_pass"
OUT_DIR      = C.DATA_DIR / "within_block_ensemble_v6"
DEDUP_ROOT   = C.DATA_DIR / "within_block_dedup_v6"
BOOK_ROOT    = C.DATA_DIR / "within_block_book_v6"


# ---------------------------------------------------------------------- #
# Loaders
# ---------------------------------------------------------------------- #
def _load_shared(data_dir: Path) -> dict:
    mem = pd.read_parquet(data_dir / "universe_v6" / "membership.parquet")
    codes = list(mem.columns[mem.any(axis=0)])
    mem = mem[codes].astype(bool)
    fwd = pd.read_parquet(data_dir / "panels_v6" / "fwd_1w.parquet")[codes]
    sigma = pd.read_parquet(
        data_dir / "panels_v6" / "sigma_causal_26w.parquet"
    )[codes]
    cat = pd.read_csv(data_dir / "universe_v6" / "catalogue_tagged.csv")
    block_tag = cat.set_index("code")["current_block"].reindex(codes) \
                   .fillna("UNTAGGED").replace(BLOCK_MERGES)
    caches = C.load_caches_v6("1d", codes)
    return {"membership": mem, "codes": codes, "fwd_1w": fwd,
            "sigma": sigma, "block_tag": block_tag, "caches": caches}


def _load_kept_with_turnover(block: str,
                              dedup_root: Path,
                              book_root: Path) -> pd.DataFrame:
    kept = pd.read_csv(dedup_root / block / "kept.csv")
    book = pd.read_csv(book_root / block / "summary.csv")
    book = book[book["sizing"] == "invvol"][
        ["factor", "polarity", "turnover", "sharpe", "cagr"]
    ].rename(columns={"sharpe": "solo_sharpe", "cagr": "solo_cagr"})
    return kept.merge(book, on=["factor", "polarity"], how="left")


def _load_nulls(block: str, book_root: Path) -> pd.DataFrame:
    return pd.read_csv(book_root / block / "nulls.csv")


# ---------------------------------------------------------------------- #
# Ensemble score
# ---------------------------------------------------------------------- #
def _row_z(panel: pd.DataFrame) -> pd.DataFrame:
    mu = panel.mean(axis=1, skipna=True)
    sd = panel.std(axis=1, skipna=True, ddof=1)
    return panel.sub(mu, axis=0).div(sd.replace(0.0, np.nan), axis=0)


def build_ensemble_score(members: pd.DataFrame,
                         data: dict,
                         block_codes: pd.Index) -> pd.DataFrame:
    """Row-z + equal-weight mean across members. Returns a (T × N_b)
    frame of ensemble scores; higher = better after polarity applied.
    """
    mem = data["membership"]; codes = data["codes"]
    mem_b = mem[block_codes]
    rebal = mem.index

    accum = None
    count = None
    for _, r in members.iterrows():
        f = r["factor"]; pol = r["polarity"]
        A = _weekly_alpha(data["caches"], f, rebal, codes)
        if A.shape[1] < 2:
            continue
        A = C.apply_membership(A, mem)
        A1 = C.expanding_z(A)
        A1 = A1 if pol == "raw" else -A1
        A_b = A1[block_codes].where(mem_b)
        rz = _row_z(A_b)
        if accum is None:
            accum = rz.fillna(0.0)
            count = rz.notna().astype(float)
        else:
            accum = accum.add(rz.fillna(0.0), fill_value=0.0)
            count = count.add(rz.notna().astype(float), fill_value=0.0)

    if accum is None:
        return pd.DataFrame(index=rebal, columns=block_codes, dtype=float)
    ensemble = accum.div(count.replace(0.0, np.nan))
    return ensemble


# ---------------------------------------------------------------------- #
# Metrics + book runner
# ---------------------------------------------------------------------- #
def _is_slice(s: pd.Series,
              start_date: pd.Timestamp | None = None) -> pd.Series:
    m = s.index <= C.IN_SAMPLE_END
    if start_date is not None:
        m = m & (s.index >= start_date)
    return s[m]


def _window_metrics(net: pd.Series) -> dict:
    n = int(len(net))
    if n < 2:
        return {"sharpe": np.nan, "cagr": np.nan, "max_dd": np.nan,
                "ann_vol": np.nan, "n_bars": n}
    ann_vol = float(net.std(ddof=1)) * np.sqrt(C.WEEKS_PER_YEAR)
    ann_ret = float(net.mean()) * C.WEEKS_PER_YEAR
    sharpe  = (ann_ret / ann_vol) if ann_vol > 0 else np.nan
    cumret  = float(net.sum())
    n_yrs   = max(n / C.WEEKS_PER_YEAR, 1e-3)
    cagr    = max(1.0 + cumret, 1e-9) ** (1.0 / n_yrs) - 1.0
    nav     = 1.0 + net.cumsum()
    max_dd  = float(((nav - nav.cummax()) / nav.cummax()).min())
    return {"sharpe": sharpe, "cagr": cagr, "max_dd": max_dd,
            "ann_vol": ann_vol, "n_bars": n}


def _turnover(W: pd.DataFrame,
              start_date: pd.Timestamp | None = None) -> float:
    m = W.index <= C.IN_SAMPLE_END
    if start_date is not None:
        m = m & (W.index >= start_date)
    is_W = W.loc[m]
    return float(is_W.diff().abs().sum(axis=1).fillna(0.0).mean())


def run_ensemble_book(score: pd.DataFrame,
                      mem_b: pd.DataFrame,
                      sigma_source: pd.DataFrame,
                      fwd_b: pd.DataFrame,
                      q: float,
                      epsilon: float = EPSILON,
                      start_date: pd.Timestamp | None = None) -> dict:
    W, N_t, K_t = H.build_hysteresis_weights(
        score, sigma_source, mem_b, q=q, mode="long",
        epsilon=epsilon, rule=RULE,
    )
    res = E.run_book(W, fwd_b, cost_per_trade=COST, N_t=N_t, K_t=K_t)
    is_net = _is_slice(res.net_ret, start_date=start_date)
    m = _window_metrics(is_net)
    m["turnover"] = _turnover(W, start_date=start_date)
    return {"metrics": m, "net_ret": res.net_ret, "W": W}


# ---------------------------------------------------------------------- #
# Per-block runner
# ---------------------------------------------------------------------- #
def run_block(block: str, data: dict, q: float,
              min_absz: float, max_turn: float,
              min_solo_sh: float,
              k_grid: tuple[int, ...],
              epsilon_grid: tuple[float, ...],
              out_dir: Path,
              dedup_root: Path,
              book_root: Path,
              start_date: pd.Timestamp | None = None) -> dict:
    codes    = data["codes"]
    mem      = data["membership"]
    fwd      = data["fwd_1w"]
    sigma    = data["sigma"]
    tag      = data["block_tag"]

    block_codes = pd.Index([c for c in codes if tag.get(c) == block])
    mem_b   = mem[block_codes]
    fwd_b   = fwd[block_codes]
    sigma_b = sigma[block_codes]
    sigma_eqw = pd.DataFrame(1.0, index=sigma_b.index,
                             columns=sigma_b.columns).where(mem_b, np.nan)

    # ---- filter kept ----
    kept = _load_kept_with_turnover(block, dedup_root, book_root)
    kept["abs_z"] = kept["zstat"].abs()
    pool = kept[(kept["abs_z"] >= min_absz) &
                (kept["turnover"] <= max_turn) &
                (kept["solo_sharpe"] >= min_solo_sh)].copy()
    pool = pool.sort_values(["abs_z", "turnover"],
                             ascending=[False, True]).reset_index(drop=True)
    print(f"[{block}] {len(kept)} 13.2b kept → "
          f"{len(pool)} pass filter (|z| ≥ {min_absz}, "
          f"turn ≤ {max_turn}, solo Sharpe ≥ {min_solo_sh})")
    if pool.empty:
        return {"block": block, "pool": pool, "summary": pd.DataFrame()}
    print(pool[["factor","polarity","zstat","turnover","solo_sharpe"]] \
              .head(10).round(3).to_string(index=False))

    # ---- null hurdle ----
    nulls = _load_nulls(block, book_root)
    eqw_sh = float(nulls.loc[nulls["book"] == "eqw_null",    "sharpe"].iloc[0])
    iv_sh  = float(nulls.loc[nulls["book"] == "invvol_null", "sharpe"].iloc[0])
    eqw_cg = float(nulls.loc[nulls["book"] == "eqw_null",    "cagr"].iloc[0])
    hurdle = max(eqw_sh, iv_sh)
    print(f"[{block}] hurdle Sharpe = max(eqw={eqw_sh:+.3f}, "
          f"invvol={iv_sh:+.3f}) = {hurdle:+.3f};  "
          f"CAGR floor = {eqw_cg*100:+.2f}%")

    # ---- sweep K × ε × sizing ----
    K_set = tuple(k for k in k_grid if k <= len(pool)) + (len(pool),)
    K_set = tuple(sorted(set(K_set)))
    rows = []
    for K in K_set:
        members = pool.head(K).copy()
        members.to_csv(out_dir / f"members_{K}.csv", index=False)
        print(f"\n[{block}] ensemble K={K}: "
              + ", ".join(f"{r.factor}({r.polarity})"
                          for r in members.itertuples()))
        score = build_ensemble_score(members, data, block_codes)

        for eps in epsilon_grid:
            for sizing_name, sigma_used in (
                ("invvol", sigma_b),
                ("eqw",    sigma_eqw),
            ):
                r = run_ensemble_book(score, mem_b, sigma_used, fwd_b, q,
                                      epsilon=eps, start_date=start_date)
                m = r["metrics"]
                passed = (
                    np.isfinite(m["sharpe"])
                    and m["sharpe"] > hurdle
                    and m["cagr"] >= eqw_cg
                )
                rows.append({
                    "K":                K,
                    "epsilon":          eps,
                    "sizing":           sizing_name,
                    "sharpe":           m["sharpe"],
                    "cagr":             m["cagr"],
                    "max_dd":           m["max_dd"],
                    "ann_vol":          m["ann_vol"],
                    "turnover":         m["turnover"],
                    "d_sharpe_vs_eqw":  m["sharpe"] - eqw_sh,
                    "d_sharpe_vs_iv":   m["sharpe"] - iv_sh,
                    "d_cagr_vs_eqw":    m["cagr"]   - eqw_cg,
                    "pass":             bool(passed),
                    "members":          ";".join(members["factor"].tolist()),
                })
                r["net_ret"].to_frame("net_ret").to_csv(
                    out_dir / f"K{K:02d}_eps{int(eps*100):03d}_{sizing_name}_net_ret.csv"
                )
                print(f"    ε={eps:.2f}  {sizing_name:6s}  "
                      f"Sharpe={m['sharpe']:+.3f}  "
                      f"CAGR={m['cagr']*100:+.2f}%  "
                      f"DD={m['max_dd']*100:+.2f}%  "
                      f"turn={m['turnover']:.3f}  "
                      f"{'PASS ✓' if passed else ''}")

    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "summary.csv", index=False)
    return {"block": block, "pool": pool, "summary": df,
            "eqw_sh": eqw_sh, "iv_sh": iv_sh, "eqw_cg": eqw_cg,
            "hurdle": hurdle}


# ---------------------------------------------------------------------- #
# Report
# ---------------------------------------------------------------------- #
def _fmt(x, digits=3):
    return f"{x:+.{digits}f}" if pd.notna(x) else "   —"


def _fmt_pct(x, digits=2):
    return f"{x*100:+.{digits}f}%" if pd.notna(x) else "     —"


def write_report(results: list[dict], min_absz: float, max_turn: float,
                 q: float, report_path: Path,
                 dedup_root: Path = DEDUP_ROOT) -> None:
    lines: list[str] = []
    lines.append("# Phase 13.5 — within-block ensemble book (v6 pool, IS)\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    lines.append(
        f"Applied `BLOCK_MERGES = {{smallcap_cn → broad_cn}}` at load. "
        f"q = {q}, ε = {EPSILON} (replace rule), cost {COST*10000:.0f} bp/side, "
        f"IS bars ≤ {C.IN_SAMPLE_END.date()}. "
        f"Ensemble scope filter: |zstat| ≥ {min_absz} AND turnover ≤ "
        f"{max_turn} (turnover measured from 13.4 invvol-sizing solo book). "
        "Ensemble score = mean across members of `row_z(polarity · "
        "expanding_z(α))`, restricted to block members. Feed as α into "
        "the production hysteresis engine.\n\n"
        "**Pass rule** (same as 13.4): IS Sharpe > max(eqw_null, "
        "invvol_null) AND CAGR ≥ eqw_null CAGR.\n\n"
    )

    lines.append("## 1. Filter yield + null hurdles\n")
    lines.append("| block | 13.2b kept | passes filter | eqw null Sh | "
                 "invvol null Sh | hurdle Sh | eqw null CAGR |")
    lines.append("|:---|---:|---:|---:|---:|---:|---:|")
    for r in results:
        n_kept = len(pd.read_csv(dedup_root / r["block"] / "kept.csv"))
        lines.append(
            f"| {r['block']} | {n_kept} | {len(r['pool'])} | "
            f"{_fmt(r['eqw_sh'])} | {_fmt(r['iv_sh'])} | "
            f"{_fmt(r['hurdle'])} | {_fmt_pct(r['eqw_cg'])} |"
        )
    lines.append("")

    lines.append("## 2. Ensemble members (top by |zstat|, tie-break by lower turnover)\n")
    for r in results:
        pool = r["pool"]
        if pool.empty:
            continue
        lines.append(f"### `{r['block']}` — filter-pass pool ({len(pool)} factors)\n")
        lines.append("| # | factor | pol | zstat | 13.4 solo Sharpe | "
                     "solo turnover |")
        lines.append("|---:|:---|:---:|---:|---:|---:|")
        for i, row in pool.iterrows():
            lines.append(
                f"| {i + 1} | {row['factor']} | {row['polarity']} | "
                f"{_fmt(row['zstat'], 2)} | {_fmt(row['solo_sharpe'])} | "
                f"{row['turnover']:.3f} |"
            )
        lines.append("")

    lines.append("## 3. Ensemble book results\n")
    for r in results:
        if r["summary"].empty:
            continue
        lines.append(f"### `{r['block']}`\n")
        lines.append(
            f"Hurdle Sharpe = {_fmt(r['hurdle'])}; "
            f"CAGR floor = {_fmt_pct(r['eqw_cg'])}\n\n"
        )
        has_eps = "epsilon" in r["summary"].columns and \
                  r["summary"]["epsilon"].nunique() > 1
        if has_eps:
            lines.append("| K | ε | sizing | Sharpe | CAGR | max DD | "
                         "turnover | ΔSh vs eqw | ΔSh vs 1/σ | ΔCAGR vs eqw | pass |")
            lines.append("|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|:---:|")
            for _, row in r["summary"].iterrows():
                mark = "✓" if row["pass"] else ""
                lines.append(
                    f"| {int(row['K'])} | {row['epsilon']:.2f} | "
                    f"{row['sizing']} | "
                    f"{_fmt(row['sharpe'])} | {_fmt_pct(row['cagr'])} | "
                    f"{_fmt_pct(row['max_dd'])} | {row['turnover']:.3f} | "
                    f"{_fmt(row['d_sharpe_vs_eqw'])} | "
                    f"{_fmt(row['d_sharpe_vs_iv'])} | "
                    f"{_fmt_pct(row['d_cagr_vs_eqw'])} | {mark} |"
                )
        else:
            lines.append("| K | sizing | Sharpe | CAGR | max DD | turnover | "
                         "ΔSh vs eqw | ΔSh vs 1/σ | ΔCAGR vs eqw | pass |")
            lines.append("|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|:---:|")
            for _, row in r["summary"].iterrows():
                mark = "✓" if row["pass"] else ""
                lines.append(
                    f"| {int(row['K'])} | {row['sizing']} | "
                    f"{_fmt(row['sharpe'])} | {_fmt_pct(row['cagr'])} | "
                    f"{_fmt_pct(row['max_dd'])} | {row['turnover']:.3f} | "
                    f"{_fmt(row['d_sharpe_vs_eqw'])} | "
                    f"{_fmt(row['d_sharpe_vs_iv'])} | "
                    f"{_fmt_pct(row['d_cagr_vs_eqw'])} | {mark} |"
                )
        lines.append("")

    lines.append("## 4. Read\n")
    for r in results:
        if r["summary"].empty:
            lines.append(f"- **`{r['block']}`**: filter left no candidates.\n")
            continue
        best = r["summary"].sort_values("sharpe", ascending=False).iloc[0]
        any_pass = int(r["summary"]["pass"].sum())
        if any_pass > 0:
            best_pass = r["summary"][r["summary"]["pass"]] \
                .sort_values("sharpe", ascending=False).iloc[0]
            lines.append(
                f"- **`{r['block']}`**: {any_pass}/"
                f"{len(r['summary'])} ensemble variants pass. Best pass = "
                f"K={int(best_pass['K'])}/{best_pass['sizing']} "
                f"Sharpe {best_pass['sharpe']:+.3f}, "
                f"CAGR {_fmt_pct(best_pass['cagr'])}, "
                f"ΔSh vs eqw {best_pass['d_sharpe_vs_eqw']:+.3f}. "
                "Ready as the per-block α layer for Phase 12.\n"
            )
        else:
            lines.append(
                f"- **`{r['block']}`**: 0/{len(r['summary'])} pass. "
                f"Best raw = K={int(best['K'])}/{best['sizing']} "
                f"Sharpe {best['sharpe']:+.3f}, "
                f"ΔSh vs eqw {best['d_sharpe_vs_eqw']:+.3f}. "
                "Ensemble smoothing helped vs solo books but the "
                "block-native null still isn't cleared — try wider q "
                "or larger ε next.\n"
            )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {report_path}")


# ---------------------------------------------------------------------- #
# CLI + main
# ---------------------------------------------------------------------- #
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--q", type=float, default=Q_DEFAULT)
    p.add_argument("--min-absz", type=float, default=MIN_ABSZ,
                   help=f"|zstat| filter threshold (default {MIN_ABSZ})")
    p.add_argument("--max-turn", type=float, default=MAX_TURN,
                   help=f"solo-book turnover filter (default {MAX_TURN})")
    p.add_argument("--min-solo-sharpe", type=float,
                   default=float("-inf"),
                   help="solo 13.4 Sharpe floor for the filter "
                        "(default -inf = no filter)")
    p.add_argument("--blocks", type=str, default=None,
                   help="comma-separated blocks (default: broad_cn,sector_cn)")
    p.add_argument("--out-tag", type=str, default=None,
                   help="suffix on output dirs so a restricted-filter "
                        "re-run doesn't overwrite the canonical outputs. "
                        "E.g. --out-tag sector_solo20.")
    p.add_argument("--epsilon-grid", type=str,
                   default=f"{EPSILON}",
                   help="comma-separated ε values to sweep "
                        f"(default {EPSILON} = production single point)")
    p.add_argument("--start-date", type=str, default=None,
                   help="IS start date (YYYY-MM-DD) for metrics / nulls. "
                        "Use with matching --dedup-tag / --book-tag runs.")
    p.add_argument("--dedup-tag", type=str, default=None,
                   help="tag on within_block_dedup_v6 root for kept.csv")
    p.add_argument("--book-tag", type=str, default=None,
                   help="tag on within_block_book_v6 root for nulls + "
                        "solo turnover reference")
    return p.parse_args()


def main():
    args = _parse_args()

    tag = f"_{args.out_tag}" if args.out_tag else ""
    out_root = C.DATA_DIR / f"within_block_ensemble_v6{tag}"
    report_p = C.REPORTS_DIR / f"within_block_ensemble_v6{tag}_report.md"
    out_root.mkdir(parents=True, exist_ok=True)

    dedup_root = C.DATA_DIR / (
        f"within_block_dedup_v6{('_' + args.dedup_tag) if args.dedup_tag else ''}"
    )
    book_root = C.DATA_DIR / (
        f"within_block_book_v6{('_' + args.book_tag) if args.book_tag else ''}"
    )
    start_date = pd.Timestamp(args.start_date) if args.start_date else None

    blocks = tuple(x.strip() for x in args.blocks.split(",")) \
               if args.blocks else ("broad_cn", "sector_cn")

    data = _load_shared(C.DATA_DIR)
    print(f"shared: {len(data['codes'])} codes, {len(data['fwd_1w'])} bars")
    print(f"dedup_root={dedup_root}, book_root={book_root}, "
          f"start_date={start_date}")

    results = []
    for b in blocks:
        b_out = out_root / b
        b_out.mkdir(parents=True, exist_ok=True)
        eps_grid = tuple(float(x) for x in args.epsilon_grid.split(","))
        r = run_block(b, data, args.q, args.min_absz, args.max_turn,
                      args.min_solo_sharpe, K_GRID_BASE, eps_grid, b_out,
                      dedup_root=dedup_root, book_root=book_root,
                      start_date=start_date)
        results.append(r)

    write_report(results, args.min_absz, args.max_turn, args.q, report_p,
                 dedup_root=dedup_root)


if __name__ == "__main__":
    main()
