"""
v6/scripts/block_neutral_ic_v6.py
=================================
Diagnostic (DESIGN §8) — where does each factor's IC live?

For a (mode, q) cell's surviving dedup set (and the ensemble α that
``xs_screen_v6`` builds from it), compute per-bar Spearman IC vs the
ranked risk-adj label ỹ two ways:

  (raw)          — standard per-bar rank IC across all valid names in
                   the row (matches ``C.per_bar_spearman``).
  (block-neutral)— per bar, restrict to the valid intersection, rank α
                   and ỹ, subtract the within-``BLOCK_TAG`` mean from
                   each rank vector, then Pearson-correlate the
                   residuals. Isolates the *within-block* cross-section.

Interpretation. If raw IC is positive but block-neutral IC collapses to
zero, the factor's signal lives in *picking blocks* (e.g. rotating into
the bond block when bonds are the highest-Sharpe basket) and not in
*picking within blocks*. The v4pool had no within-block cross-section
to measure — v6's ragged multi-block pool makes this measurable.

Between-block component is reported alongside as a sanity check: per-bar
Pearson correlation of block-mean(rank_α) vs block-mean(rank_ỹ),
weighted by block size, so raw ≈ within + between decomposes cleanly at
the intuitive level.

Outputs
-------
    reports/block_neutral_ic_v6.md
    (also prints per-cell tables to stdout)

Run
---
    python v6/scripts/block_neutral_ic_v6.py                     # long_q20 only
    python v6/scripts/block_neutral_ic_v6.py --cells all         # every cell
    python v6/scripts/block_neutral_ic_v6.py --mode long --q 0.05
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata

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
import xs_screen_v6 as S


DEFAULT_CELL   = ("long", 0.20)
MIN_VALID_ROW  = 5     # per-bar min names across the row to score IC
MIN_PER_BLOCK  = 2     # per-block min names to keep that block in the demean


# ---------------------------------------------------------------------- #
# Inputs
# ---------------------------------------------------------------------- #
def _load_label(data_dir: Path, codes: list[str]) -> pd.DataFrame:
    return pd.read_parquet(
        data_dir / "panels_v6" / "label_ranked_risk_adj.parquet"
    )[codes]


def _load_block_tag(data_dir: Path) -> pd.Series:
    cat = pd.read_csv(data_dir / "universe_v6" / "catalogue_tagged.csv")
    return cat.set_index("code")["current_block"]


# ---------------------------------------------------------------------- #
# Per-bar IC — raw + block-neutral + between-block
# ---------------------------------------------------------------------- #
def _row_ics(a: np.ndarray, b: np.ndarray, blk: np.ndarray
             ) -> tuple[float, float, float, int, int]:
    """One bar's IC triple.

    Returns (ic_raw, ic_within, ic_between, n_valid, n_within).
    NaN entries are dropped upfront; ranks are computed on the intersection.
    """
    both = np.isfinite(a) & np.isfinite(b)
    n_valid = int(both.sum())
    if n_valid < MIN_VALID_ROW:
        return (np.nan, np.nan, np.nan, n_valid, 0)

    ra = rankdata(a[both], method="average").astype(float)
    rb = rankdata(b[both], method="average").astype(float)
    blk_v = blk[both]

    # Raw IC = Pearson on the row-ranks (= Spearman IC in this row)
    if ra.std() == 0.0 or rb.std() == 0.0:
        ic_raw = np.nan
    else:
        ic_raw = float(np.corrcoef(ra, rb)[0, 1])

    # Within-block demean; keep only blocks with >= MIN_PER_BLOCK names
    keep = np.zeros_like(ra, dtype=bool)
    ra_res = ra.copy()
    rb_res = rb.copy()
    uniq = np.unique(blk_v)
    # Store per-block means + sizes for the between-block IC
    means_a = []
    means_b = []
    sizes   = []
    for u in uniq:
        m = (blk_v == u)
        k = int(m.sum())
        if k == 0:
            continue
        ma = ra[m].mean()
        mb = rb[m].mean()
        means_a.append(ma); means_b.append(mb); sizes.append(k)
        if k >= MIN_PER_BLOCK:
            keep |= m
            ra_res[m] = ra[m] - ma
            rb_res[m] = rb[m] - mb

    n_within = int(keep.sum())
    if n_within < MIN_VALID_ROW:
        ic_within = np.nan
    else:
        ra_w = ra_res[keep]; rb_w = rb_res[keep]
        if ra_w.std() == 0.0 or rb_w.std() == 0.0:
            ic_within = np.nan
        else:
            ic_within = float(np.corrcoef(ra_w, rb_w)[0, 1])

    # Between-block IC: correlation across blocks of block-mean ranks,
    # weighted by block size. Skip if fewer than 2 blocks.
    if len(means_a) < 2:
        ic_between = np.nan
    else:
        MA = np.asarray(means_a); MB = np.asarray(means_b)
        W  = np.asarray(sizes, dtype=float)
        w  = W / W.sum()
        mu_a = (w * MA).sum(); mu_b = (w * MB).sum()
        da = MA - mu_a; db = MB - mu_b
        va = (w * da * da).sum(); vb = (w * db * db).sum()
        cov = (w * da * db).sum()
        if va <= 0 or vb <= 0:
            ic_between = np.nan
        else:
            ic_between = float(cov / np.sqrt(va * vb))

    return (ic_raw, ic_within, ic_between, n_valid, n_within)


def per_bar_ic_triple(alpha: pd.DataFrame,
                      target: pd.DataFrame,
                      block_tag: pd.Series,
                      membership: pd.DataFrame | None = None,
                      ) -> pd.DataFrame:
    """Per-bar (ic_raw, ic_within, ic_between, n_valid, n_within) table."""
    idx  = alpha.index.intersection(target.index)
    cols = alpha.columns.intersection(target.columns)
    A = alpha.loc[idx, cols]
    B = target.loc[idx, cols]
    if membership is not None:
        M = (membership.reindex(index=idx, columns=cols)
                       .astype("boolean").fillna(False))
        A = A.where(M); B = B.where(M)
    blk = block_tag.reindex(cols).fillna("UNTAGGED").to_numpy()

    T = len(idx)
    ic_raw   = np.full(T, np.nan)
    ic_wit   = np.full(T, np.nan)
    ic_bet   = np.full(T, np.nan)
    n_val    = np.zeros(T, dtype=int)
    n_wit    = np.zeros(T, dtype=int)
    Aa = A.to_numpy(); Bb = B.to_numpy()
    for i in range(T):
        (ic_raw[i], ic_wit[i], ic_bet[i], n_val[i], n_wit[i]
         ) = _row_ics(Aa[i], Bb[i], blk)
    return pd.DataFrame({
        "ic_raw":   ic_raw,
        "ic_within": ic_wit,
        "ic_between": ic_bet,
        "n_valid":   n_val,
        "n_within":  n_wit,
    }, index=idx)


# ---------------------------------------------------------------------- #
# IS summary (IS-only: v6 discipline while diagnostics are exploratory)
# ---------------------------------------------------------------------- #
def _is_summary(bars: pd.DataFrame) -> dict:
    """Aggregate a per-bar IC-triple table on the IS window."""
    idx = bars.index
    m = (idx <= C.IN_SAMPLE_END)
    B = bars.loc[m]
    def _agg(col: str, n_col: str) -> dict:
        s = B[col].dropna()
        n = int(len(s))
        if n == 0:
            return {"mean": np.nan, "zstat": np.nan,
                    "pct_pos": np.nan, "n_bars": 0, "mean_N": np.nan}
        # Ragged zstat with per-bar N (Phase 5.2 convention)
        N_t = B[n_col].reindex(s.index).astype(float)
        v = N_t > 1.0
        if v.any():
            ic_v = s[v]; N_v = N_t[v]
            z_t = ic_v * np.sqrt(N_v - 1.0)
            zstat = float(z_t.mean() * np.sqrt(len(z_t)))
            mean_N = float(N_v.mean())
        else:
            zstat = np.nan; mean_N = np.nan
        return {"mean": float(s.mean()), "zstat": zstat,
                "pct_pos": float((s > 0).mean()),
                "n_bars": n, "mean_N": mean_N}
    return {
        "raw":     _agg("ic_raw",   "n_valid"),
        "within":  _agg("ic_within","n_within"),
        "between": _agg("ic_between","n_valid"),
    }


# ---------------------------------------------------------------------- #
# Cell driver
# ---------------------------------------------------------------------- #
def diagnose_cell(mode: str, q: float, data: dict,
                  label: pd.DataFrame, block_tag: pd.Series
                  ) -> dict:
    cell_dir = S._cell_dir(mode, q)
    dedup_p  = cell_dir / "dedup.csv"
    if not dedup_p.exists() or dedup_p.stat().st_size == 0:
        print(f"[{S._cell_tag(mode, q)}] no dedup.csv — skipping")
        return {"mode": mode, "q": q, "rows": []}
    dedup = pd.read_csv(dedup_p)
    if dedup.empty:
        print(f"[{S._cell_tag(mode, q)}] empty dedup — skipping")
        return {"mode": mode, "q": q, "rows": []}

    print("=" * 78)
    print(f"BLOCK-NEUTRAL IC  cell={S._cell_tag(mode, q)}   "
          f"kept={len(dedup)}  blocks={block_tag.dropna().nunique()}")
    print("=" * 78)

    codes = data["codes"]
    rebal = data["fwd_1w"].index
    mem   = data["membership"]

    rows = []
    for _, r in dedup.iterrows():
        A = S._weekly_alpha(data["caches"], r["base"], rebal, codes,
                            daily_index=data["daily_index"])
        if r["polarity"] == "rev":
            A = -A
        A = C.apply_membership(A, mem)
        bars = per_bar_ic_triple(A, label, block_tag, membership=mem)
        summ = _is_summary(bars)
        rows.append({
            "factor":     r["factor"],
            "raw_mean":   summ["raw"]["mean"],
            "raw_zstat":  summ["raw"]["zstat"],
            "raw_pctpos": summ["raw"]["pct_pos"],
            "wit_mean":   summ["within"]["mean"],
            "wit_zstat":  summ["within"]["zstat"],
            "wit_pctpos": summ["within"]["pct_pos"],
            "bet_mean":   summ["between"]["mean"],
            "bet_zstat":  summ["between"]["zstat"],
            "mean_N":     summ["raw"]["mean_N"],
            "mean_N_wit": summ["within"]["mean_N"],
        })

    # Ensemble α (row-z of raw α, mean across factors — the v6 convention)
    alpha_ens = S.build_ensemble_alpha(dedup, data)
    bars_ens  = per_bar_ic_triple(alpha_ens, label, block_tag, membership=mem)
    summ_ens  = _is_summary(bars_ens)
    rows.append({
        "factor":     "*ensemble*",
        "raw_mean":   summ_ens["raw"]["mean"],
        "raw_zstat":  summ_ens["raw"]["zstat"],
        "raw_pctpos": summ_ens["raw"]["pct_pos"],
        "wit_mean":   summ_ens["within"]["mean"],
        "wit_zstat":  summ_ens["within"]["zstat"],
        "wit_pctpos": summ_ens["within"]["pct_pos"],
        "bet_mean":   summ_ens["between"]["mean"],
        "bet_zstat":  summ_ens["between"]["zstat"],
        "mean_N":     summ_ens["raw"]["mean_N"],
        "mean_N_wit": summ_ens["within"]["mean_N"],
    })

    df = pd.DataFrame(rows)
    _print_table(df)
    return {"mode": mode, "q": q, "rows": rows,
            "n_blocks": int(block_tag.dropna().nunique())}


def _print_table(df: pd.DataFrame) -> None:
    show = df[["factor", "raw_mean", "raw_zstat", "raw_pctpos",
               "wit_mean", "wit_zstat", "wit_pctpos",
               "bet_mean", "bet_zstat", "mean_N", "mean_N_wit"]].copy()
    fmt = {"raw_mean":   lambda x: f"{x:+.4f}",
           "raw_zstat":  lambda x: f"{x:+6.2f}",
           "raw_pctpos": lambda x: f"{x:.2f}",
           "wit_mean":   lambda x: f"{x:+.4f}",
           "wit_zstat":  lambda x: f"{x:+6.2f}",
           "wit_pctpos": lambda x: f"{x:.2f}",
           "bet_mean":   lambda x: f"{x:+.4f}",
           "bet_zstat":  lambda x: f"{x:+6.2f}",
           "mean_N":     lambda x: f"{x:5.1f}",
           "mean_N_wit": lambda x: f"{x:5.1f}"}
    print(show.to_string(index=False, formatters=fmt))


# ---------------------------------------------------------------------- #
# Report
# ---------------------------------------------------------------------- #
def _write_report(cell_results: list[dict], report_path: Path) -> None:
    lines: list[str] = []
    lines.append("# v6 static — block-neutral IC diagnostic (DESIGN §8)\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    lines.append(
        "IC vs ranked risk-adj label ỹ, IS window (bars ≤ "
        f"{C.IN_SAMPLE_END.date()}).\n\n"
        "- **raw** — per-bar Spearman IC across all valid names.\n"
        "- **within** — per-bar Pearson IC after subtracting the per-`BLOCK_TAG` "
        "mean from both the α-rank and ỹ-rank vectors. Blocks with fewer than "
        f"{MIN_PER_BLOCK} valid names in a bar are dropped.\n"
        "- **between** — per-bar size-weighted Pearson IC of block-mean ranks. "
        "Positive between + near-zero within = pure sector rotation; positive "
        "within = relative-value information.\n"
        "- zstat uses the ragged √(N−1) aggregation from `C.ic_summary` "
        "(N = row size for raw/between; block-neutral N for within).\n\n"
    )
    header = ("| cell | factor | raw mean | raw z | raw pos% | "
              "within mean | within z | within pos% | "
              "between mean | between z | mean N | within N |")
    sep    = ("|:---:|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    lines.append(header)
    lines.append(sep)
    for res in cell_results:
        tag = f"{res['mode']}_q{int(round(res['q']*100)):02d}"
        for r in res["rows"]:
            lines.append(
                f"| {tag} | {r['factor']} | "
                f"{r['raw_mean']:+.4f} | {r['raw_zstat']:+.2f} | "
                f"{r['raw_pctpos']:.2f} | "
                f"{r['wit_mean']:+.4f} | {r['wit_zstat']:+.2f} | "
                f"{r['wit_pctpos']:.2f} | "
                f"{r['bet_mean']:+.4f} | {r['bet_zstat']:+.2f} | "
                f"{r['mean_N']:.1f} | {r['mean_N_wit']:.1f} |"
            )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {report_path}")


# ---------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", choices=("default", "all"), default="default")
    ap.add_argument("--mode",  choices=S.MODES)
    ap.add_argument("--q",     type=float)
    args = ap.parse_args()

    data      = S._load_inputs(C.DATA_DIR)
    label     = _load_label(C.DATA_DIR, data["codes"])
    block_tag = _load_block_tag(C.DATA_DIR)

    if args.mode and args.q:
        cells = [(args.mode, args.q)]
    elif args.cells == "all":
        cells = [(m, q) for m in S.MODES for q in S.QS]
    else:
        cells = [DEFAULT_CELL]

    results = [diagnose_cell(m, q, data, label, block_tag) for m, q in cells]
    results = [r for r in results if r.get("rows")]
    _write_report(results, C.REPORTS_DIR / "block_neutral_ic_v6.md")


if __name__ == "__main__":
    main()
