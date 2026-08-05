"""
v6/scripts/within_block_ic_v6.py
================================
Phase 13.2 — within-block IC screen on the v6 pool.

For every factor in ``common_factors_v6`` (all six REGISTRY families;
471–472 factors on the current cache) × every block in
``catalogue_tagged.csv`` (9 blocks), compute per-bar Spearman IC over
that block's admitted members and aggregate with the ragged-N z-stat
(Phase 5.2 convention). Both polarities kept; a zstat of −3 is a signal
whose sign flips at trading time.

The screen answers *only* one question: does any factor rank names
correctly *within a single block*? Pool-level IC (`pv_sweep_xs_v6`) is
dominated by between-block rotation on this pool (see
`project_block_neutral_ic`, `bond_attribution_v6.md`); the within-block
screen is the gate for whether a two-layer (block-budget × per-block-α)
architecture is worth building at all.

Companion diagnostics:
  - `block_xs_census_v6.md` reads the per-block cross-section widths.
    Blocks with mean_N_b < 5 are ``thin`` — their IC is still computed
    but a passing zstat is directional, not measured.
  - `block_neutral_ic_v6.md` is a per-cell demeaning diagnostic on the
    dedup survivors. This screen is *broader*: every registered factor,
    per-block IC in isolation, not within-block demeaning.

Feature transform (matches `pv_sweep_xs_v6` up to stage-1):
  A       ← per-code W-FRI reindex of the factor cache column
  A       ← membership-masked (global mask, not per-block)
  A1      ← stage-1 expanding z per name (min_periods = 26)
  For each block b:
    A_b   ← A1.where(code in block b)
    y_b   ← label.where(code in block b)
    ic_b  ← per-bar Spearman(A_b, y_b, min_valid=5)
    row   ← ic_summary(ic_b, N_b) — zstat, mean_ic_w, mean_N_b, n_bars

Stage-2 CS Gaussian rank is *not* applied — Spearman IC is
rank-invariant per bar, so any monotone-per-bar transform of A gives the
same per-bar IC. Skipping stage-2 saves compute; results match a
stage-2 pipeline exactly.

Gate for "trustworthy" survivor rows:
    |zstat| ≥ 2.0   AND   n_bars ≥ MIN_COVERAGE

Thin blocks contribute rows in the long CSV even if they miss the gate
— per user, screen everything and flag interpretation downstream.

IS-only (bars ≤ ``C.IN_SAMPLE_END``). Feedback-oos-discipline.

Outputs
-------
    data/within_block_ic_v6/all_factors.csv         # long form
    data/within_block_ic_v6/survivors.csv           # gate passers
    data/within_block_ic_v6/topk_per_block.csv      # per-block top-K by |zstat|
    reports/within_block_ic_v6_report.md

Run
---
    python v6/scripts/within_block_ic_v6.py
    python v6/scripts/within_block_ic_v6.py --top-k 15
    python v6/scripts/within_block_ic_v6.py --categories daily,price_volume
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
from factors.registry import REGISTRY


# ---------------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------------- #
MIN_COVERAGE  = 100    # min IS bars with a defined per-block IC
MIN_VALID_ROW = 5      # min per-bar members to admit that bar's IC
Z_STAT_GATE   = 2.0
TOP_K_DEFAULT = 10
OUT_DIR       = C.DATA_DIR / "within_block_ic_v6"
CENSUS_PATH   = C.DATA_DIR / "block_xs_census_v6" / "summary.csv"


# ---------------------------------------------------------------------- #
# Inputs
# ---------------------------------------------------------------------- #
def _load_inputs(data_dir: Path, categories: tuple[str, ...] | None) -> dict:
    mem = pd.read_parquet(data_dir / "universe_v6" / "membership.parquet")
    codes = list(mem.columns[mem.any(axis=0)])
    mem = mem[codes].astype(bool)

    y = pd.read_parquet(
        data_dir / "panels_v6" / "label_ranked_risk_adj.parquet"
    )[codes]

    cat = pd.read_csv(data_dir / "universe_v6" / "catalogue_tagged.csv")
    block_tag = cat.set_index("code")["current_block"].reindex(codes) \
                   .fillna("UNTAGGED")

    caches = C.load_caches_v6("1d", codes)
    common = set(C.common_factors_v6(caches))
    if not common:
        raise RuntimeError("no common factors in v6 cache — build Phase 4 first")

    if categories is None:
        cats = tuple(REGISTRY.get_categories())
    else:
        cats = categories
    factor_names: list[str] = []
    reg_total = 0
    for c in cats:
        cat_facs = set(REGISTRY.list_factors(c))
        reg_total += len(cat_facs)
        factor_names.extend(sorted(cat_facs & common))
    factor_names = sorted(set(factor_names))
    if not factor_names:
        raise RuntimeError(
            f"no factors intersect cache for categories={cats}"
        )

    # Ordered list of blocks: sector counts descending on IS
    blocks = sorted(block_tag.unique().tolist())

    return {
        "membership":   mem,
        "codes":        codes,
        "label":        y,
        "block_tag":    block_tag,
        "blocks":       blocks,
        "caches":       caches,
        "factor_names": factor_names,
        "reg_total":    reg_total,
        "common_n":     len(common),
        "categories":   cats,
    }


def _load_census() -> pd.DataFrame | None:
    if not CENSUS_PATH.exists():
        return None
    return pd.read_csv(CENSUS_PATH).set_index("block")


# ---------------------------------------------------------------------- #
# α builder (same convention as pv_sweep_xs_v6._weekly_alpha)
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


# ---------------------------------------------------------------------- #
# One (factor × block) row
# ---------------------------------------------------------------------- #
def _block_row(factor: str, block: str,
               A1: pd.DataFrame,
               y: pd.DataFrame,
               block_mask_cols: pd.Index,
               is_idx: pd.DatetimeIndex) -> dict | None:
    """Per-bar Spearman IC of A1 vs y over ``block_mask_cols`` on IS bars.

    Returns None if no IS bar produces a defined IC. Rows returned are
    triaged downstream by (|zstat| ≥ 2, n_bars ≥ MIN_COVERAGE); every
    non-null row is kept in the long CSV regardless of the gate.
    """
    A_b = A1.loc[:, block_mask_cols]
    y_b = y.loc[:, block_mask_cols]
    A_is = A_b.loc[is_idx]
    y_is = y_b.loc[is_idx]

    ic = C.per_bar_spearman(A_is, y_is, min_valid=MIN_VALID_ROW)
    if int(ic.notna().sum()) == 0:
        return None
    N_t = C.per_bar_n_valid(A_is, y_is)
    s = C.ic_summary(ic, n_per_bar=N_t)
    if int(s["n_bars"]) == 0:
        return None

    zstat = float(s.get("zstat", np.nan))
    return {
        "factor":       factor,
        "block":        block,
        "n_bars":       int(s["n_bars"]),
        "mean_ic":      float(s["mean"]),
        "std_ic":       float(s["std"]) if pd.notna(s["std"]) else np.nan,
        "tstat":        float(s["tstat"]) if pd.notna(s["tstat"]) else np.nan,
        "zstat":        zstat,
        "mean_ic_w":    float(s.get("mean_ic_w", np.nan)),
        "mean_N_b":     float(s.get("mean_N", np.nan)),
        "pct_pos":      float(s["pct_pos"]),
        "mean_ic_52w":  float(s.get("mean_ic_52w", np.nan)),
        "pct_pos_52w": float(s.get("pct_pos_52w", np.nan)),
        "polarity":     "raw" if zstat >= 0 else "rev",
    }


# ---------------------------------------------------------------------- #
# Sweep
# ---------------------------------------------------------------------- #
def sweep(data: dict,
          block_filter: tuple[str, ...] | None = None,
          start_date: pd.Timestamp | None = None) -> pd.DataFrame:
    mem   = data["membership"]
    codes = data["codes"]
    y     = data["label"]
    tag   = data["block_tag"]
    blocks = [b for b in data["blocks"]
              if (block_filter is None or b in block_filter)]
    rebal = mem.index
    is_idx = rebal[rebal <= C.IN_SAMPLE_END]
    if start_date is not None:
        is_idx = is_idx[is_idx >= start_date]

    # Per-block column indexers (order-stable)
    block_cols: dict[str, pd.Index] = {}
    for b in blocks:
        cols_b = pd.Index([c for c in codes if tag.get(c) == b])
        if len(cols_b) == 0:
            print(f"  [{b}] 0 codes tagged — skipping block")
            continue
        block_cols[b] = cols_b

    print(f"blocks in sweep: {list(block_cols.keys())}")
    print(f"factors in sweep: {len(data['factor_names'])}")
    print(f"IS bars: {len(is_idx)}   (total {len(rebal)})")

    rows: list[dict] = []
    t0 = time.time()
    for i, f in enumerate(data["factor_names"], start=1):
        A = _weekly_alpha(data["caches"], f, rebal, codes)
        if A.shape[1] < 2 or int(A.notna().to_numpy().sum()) == 0:
            continue
        A = C.apply_membership(A, mem)
        A1 = C.expanding_z(A)
        for b, cols_b in block_cols.items():
            row = _block_row(f, b, A1, y, cols_b, is_idx)
            if row is not None:
                rows.append(row)
        if i % 25 == 0 or i == len(data["factor_names"]):
            dt = time.time() - t0
            rate = i / dt
            eta = (len(data["factor_names"]) - i) / rate
            print(f"  [{i:>4d}/{len(data['factor_names'])}] "
                  f"{f:<24s}  elapsed={dt:6.1f}s  eta={eta:6.1f}s  "
                  f"rows={len(rows)}")

    df = pd.DataFrame(rows)
    df["abs_zstat"] = df["zstat"].abs()
    return df


# ---------------------------------------------------------------------- #
# Post-sweep tables
# ---------------------------------------------------------------------- #
def survivors(long: pd.DataFrame) -> pd.DataFrame:
    keep = (long["abs_zstat"] >= Z_STAT_GATE) & (long["n_bars"] >= MIN_COVERAGE)
    out = long.loc[keep].copy()
    return out.sort_values(["block", "abs_zstat"],
                           ascending=[True, False]).reset_index(drop=True)


def topk_per_block(long: pd.DataFrame, k: int) -> pd.DataFrame:
    return (long.sort_values(["block", "abs_zstat"],
                             ascending=[True, False])
                .groupby("block", group_keys=False)
                .head(k)
                .reset_index(drop=True))


# ---------------------------------------------------------------------- #
# Report
# ---------------------------------------------------------------------- #
def _fmt(x, digits=3):
    return f"{x:+.{digits}f}" if pd.notna(x) else "  —"

def _fmt_int(x):
    return f"{int(x)}" if pd.notna(x) else "—"


def write_report(long: pd.DataFrame,
                 surv: pd.DataFrame,
                 topk: pd.DataFrame,
                 data: dict,
                 census: pd.DataFrame | None,
                 report_path: Path,
                 k: int) -> None:
    is_end = C.IN_SAMPLE_END.date()
    lines: list[str] = []
    lines.append("# Phase 13.2 — within-block IC screen (v6 pool, IS only)\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    lines.append(
        f"Screen scope: {len(data['factor_names'])} factors "
        f"(REGISTRY {'/'.join(data['categories'])}, "
        f"intersected with the v6 cache-common set of {data['common_n']}) × "
        f"{long['block'].nunique()} blocks. "
        f"IS window: bars ≤ {is_end}. Cost is not paid here (IC only). "
        f"Gate for a *trustworthy* survivor: |zstat| ≥ {Z_STAT_GATE} AND "
        f"n_bars ≥ {MIN_COVERAGE}. Thin blocks stay in the sweep — "
        "per-block top-K in §3 gives a directional read even when the "
        "gate isn't hit.\n\n"
        "Method note: stage-1 expanding-z per name (min_periods = 26), "
        "then per-bar Spearman IC restricted to block members "
        f"(min_valid = {MIN_VALID_ROW}). No stage-2 CS Gaussian rank — "
        "Spearman IC is rank-invariant per bar, so skipping it gives "
        "identical per-block IC at a fraction of the compute.\n\n"
    )

    # ---- §1 headline: survivor counts per block ----
    lines.append("## 1. Survivor counts per block\n")
    per_block_all = long.groupby("block").size().rename("n_rows")
    per_block_surv = surv.groupby("block").size().rename("n_survivors")
    tbl = pd.concat([per_block_all, per_block_surv], axis=1).fillna(0)
    tbl["n_survivors"] = tbl["n_survivors"].astype(int)
    if census is not None:
        tbl = tbl.join(census[["mean_N", "flag_thin"]], how="left")
    tbl = tbl.sort_values("n_survivors", ascending=False)
    if census is not None:
        lines.append("| block | mean N_b | thin? | rows evaluated | "
                     f"survivors (|z|≥{Z_STAT_GATE}, n≥{MIN_COVERAGE}) |")
        lines.append("|:---|---:|:---:|---:|---:|")
        for b, r in tbl.iterrows():
            thin = "**thin**" if bool(r.get("flag_thin", False)) else ""
            mean_N = r.get("mean_N", float("nan"))
            lines.append(
                f"| {b} | {_fmt(mean_N, 1)} | {thin} | "
                f"{int(r['n_rows'])} | {int(r['n_survivors'])} |"
            )
    else:
        lines.append("| block | rows evaluated | "
                     f"survivors (|z|≥{Z_STAT_GATE}, n≥{MIN_COVERAGE}) |")
        lines.append("|:---|---:|---:|")
        for b, r in tbl.iterrows():
            lines.append(f"| {b} | {int(r['n_rows'])} | "
                         f"{int(r['n_survivors'])} |")
    lines.append("")

    # ---- §2 survivors, sorted by |zstat| per block ----
    lines.append("## 2. Trustworthy survivors — |zstat| ≥ "
                 f"{Z_STAT_GATE}, n_bars ≥ {MIN_COVERAGE}\n")
    if surv.empty:
        lines.append("*No factor × block pair clears the gate.*\n")
    else:
        for b in sorted(surv["block"].unique()):
            sub = surv[surv["block"] == b]
            lines.append(f"### `{b}`  ({len(sub)} survivor{'' if len(sub)==1 else 's'})\n")
            lines.append("| factor | polarity | n | mean N_b | zstat | "
                         "mean_ic | mean_ic_w | pct_pos | mean_ic_52w |")
            lines.append("|:---|:---:|---:|---:|---:|---:|---:|---:|---:|")
            for _, r in sub.iterrows():
                lines.append(
                    f"| {r['factor']} | {r['polarity']} | "
                    f"{int(r['n_bars'])} | {_fmt(r['mean_N_b'], 1)} | "
                    f"{_fmt(r['zstat'], 2)} | {_fmt(r['mean_ic'], 4)} | "
                    f"{_fmt(r['mean_ic_w'], 4)} | "
                    f"{r['pct_pos']*100:5.1f}% | "
                    f"{_fmt(r['mean_ic_52w'], 3)} |"
                )
            lines.append("")

    # ---- §3 top-K per block regardless of gate ----
    lines.append(f"## 3. Top-{k} per block by |zstat| (directional; "
                 "no coverage gate)\n")
    lines.append(
        "Included for thin blocks where the n_bars gate cannot be met. "
        "**Do not** treat these as tradable signals — read them as "
        "\"factors worth eyeballing for a block-native diagnostic.\"\n\n"
    )
    for b in sorted(topk["block"].unique()):
        sub = topk[topk["block"] == b]
        lines.append(f"### `{b}`\n")
        lines.append("| factor | polarity | n | mean N_b | zstat | "
                     "mean_ic | pct_pos |")
        lines.append("|:---|:---:|---:|---:|---:|---:|---:|")
        for _, r in sub.iterrows():
            lines.append(
                f"| {r['factor']} | {r['polarity']} | "
                f"{int(r['n_bars'])} | {_fmt(r['mean_N_b'], 1)} | "
                f"{_fmt(r['zstat'], 2)} | {_fmt(r['mean_ic'], 4)} | "
                f"{r['pct_pos']*100:5.1f}% |"
            )
        lines.append("")

    # ---- §4 next-step read ----
    lines.append("## 4. Read for 13.3 / 13.4\n")
    if surv.empty:
        lines.append(
            "- No (factor, block) pair passes the trustworthy gate on IS. "
            "Before closing Phase 13, sanity-check the top-K in §3 for a "
            "block-native signal that the pool-level pipeline was masking. "
            "If nothing survives interpretation, the pass rule for Phase "
            "13.4 has no candidates — the two-layer architecture buys "
            "nothing over a T2/T4-style block-β book, and Phase 12 becomes "
            "\"budget-only\" mode.\n"
        )
    else:
        for b in sorted(surv["block"].unique()):
            sub = surv[surv["block"] == b]
            best = sub.iloc[0]
            lines.append(
                f"- **`{b}`**: {len(sub)} survivor(s); top by |zstat| = "
                f"`{best['factor']}` (polarity={best['polarity']}, "
                f"zstat={best['zstat']:+.2f}, n={int(best['n_bars'])}). "
                "Candidates for 13.3 within-block popularity + 13.4 "
                "isolated book vs eqw null.\n"
            )
    lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {report_path}")


# ---------------------------------------------------------------------- #
# CLI
# ---------------------------------------------------------------------- #
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--top-k", type=int, default=TOP_K_DEFAULT,
                   help="per-block top-K to display in §3 (default 10)")
    p.add_argument("--categories", type=str, default=None,
                   help="comma-separated REGISTRY categories to restrict to "
                        "(default: all six families = 472 factors)")
    p.add_argument("--blocks", type=str, default=None,
                   help="comma-separated block names to restrict the "
                        "sweep to (default: all 9)")
    p.add_argument("--start-date", type=str, default=None,
                   help="IS start date (YYYY-MM-DD) — restricts the IS "
                        "window; end stays at C.IN_SAMPLE_END. Use for "
                        "partial-window diagnostics like cross_border_hk "
                        "2021+ (per project-within-block-ic caveat).")
    p.add_argument("--out-tag", type=str, default=None,
                   help="suffix for output paths so a partial-window / "
                        "restricted-block re-run doesn't overwrite the "
                        "canonical outputs. E.g. --out-tag hk_2021 → "
                        "data/within_block_ic_v6_hk_2021/, reports/"
                        "within_block_ic_v6_hk_2021_report.md.")
    return p.parse_args()


def main():
    args = _parse_args()
    cats = tuple(x.strip() for x in args.categories.split(",")) \
             if args.categories else None
    block_filter = tuple(x.strip() for x in args.blocks.split(",")) \
                     if args.blocks else None
    start_date = pd.Timestamp(args.start_date) if args.start_date else None

    tag = f"_{args.out_tag}" if args.out_tag else ""
    out_dir = C.DATA_DIR / f"within_block_ic_v6{tag}"
    report_p = C.REPORTS_DIR / f"within_block_ic_v6{tag}_report.md"
    out_dir.mkdir(parents=True, exist_ok=True)

    data = _load_inputs(C.DATA_DIR, cats)
    print(f"factors: {len(data['factor_names'])} "
          f"(of {data['reg_total']} in categories={list(data['categories'])}, "
          f"common cache = {data['common_n']})")
    if block_filter is not None:
        print(f"blocks filter: {list(block_filter)}")
    if start_date is not None:
        print(f"IS start filter: {start_date.date()}")

    long = sweep(data, block_filter=block_filter, start_date=start_date)
    long.to_csv(out_dir / "all_factors.csv", index=False)
    print(f"\nwrote {out_dir / 'all_factors.csv'}  ({len(long)} rows)")

    surv = survivors(long)
    surv.to_csv(out_dir / "survivors.csv", index=False)
    print(f"wrote {out_dir / 'survivors.csv'}  ({len(surv)} survivors)")

    topk = topk_per_block(long, args.top_k)
    topk.to_csv(out_dir / "topk_per_block.csv", index=False)
    print(f"wrote {out_dir / 'topk_per_block.csv'}  "
          f"({args.top_k} per block)")

    census = _load_census()
    write_report(long, surv, topk, data, census, report_p, args.top_k)

    # stdout summary
    print("\nsurvivors per block:")
    print(surv.groupby("block").size().sort_values(ascending=False).to_string())


if __name__ == "__main__":
    main()
