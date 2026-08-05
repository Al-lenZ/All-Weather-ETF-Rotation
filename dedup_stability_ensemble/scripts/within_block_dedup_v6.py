"""
v6/scripts/within_block_dedup_v6.py
===================================
Phase 13.2b — within-block Pearson-|ρ| dedup.

The 13.2 screen returned 127 broad_cn + 94 sector_cn survivors at
|zstat| ≥ 2, n_bars ≥ 100, but many are known near-duplicates (e.g.
``macd_12_26`` and ``macd_signal_12_26`` are the same factor with a
different smoothing knob; alpha_179 ↔ alpha_180 give identical
per-bar rank vectors up to tie-breaking). Running 13.3's within-block
holdings popularity on the raw list would repeat the same portfolio
analysis 5-10× per family.

Method (mirrors `pv_sweep_xs_v6._greedy_dedup` at the within-block scope):
  1. Load the 13.2 survivors CSV. Restrict to blocks with survivors.
  2. For each block:
     a. Rebuild stage-1 expanding-z panels for every surviving
        factor over the IS window.
     b. Restrict columns to the block's admitted-ever codes and stack
        (T × N_b, membership-masked).
     c. Pearson |ρ| matrix across stacked panels — sign-agnostic, so
        raw ↔ rev anti-correlated pairs collapse to one.
     d. Greedy walk in descending |zstat|: keep the factor if its |ρ|
        with every already-kept representative is ≤ threshold
        (default 0.5, matching pv_sweep).
  3. Emit a per-block `kept.csv` (order-stable by |zstat|) and a
     `drop_map.csv` (dropped → representative + |ρ|).

IS-only. Same threshold as the pool-level screen so the two are
apples-to-apples.

Outputs
-------
    data/within_block_dedup_v6/{block}/kept.csv
    data/within_block_dedup_v6/{block}/drop_map.csv
    reports/within_block_dedup_v6_report.md

Run
---
    python v6/scripts/within_block_dedup_v6.py
    python v6/scripts/within_block_dedup_v6.py --threshold 0.4
    python v6/scripts/within_block_dedup_v6.py --blocks broad_cn
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
from within_block_ic_v6 import (
    _weekly_alpha, _load_inputs, OUT_DIR as IC_OUT_DIR,
)


DEDUP_DEFAULT = 0.5
OUT_DIR       = C.DATA_DIR / "within_block_dedup_v6"


# ---------------------------------------------------------------------- #
# Panel builder — stage-1 z, block-restricted, IS-only, stacked
# ---------------------------------------------------------------------- #
def _stacked_stage1_is(factors: list[str],
                       data: dict,
                       block_codes: pd.Index,
                       is_idx: pd.DatetimeIndex) -> pd.DataFrame:
    """Return a DataFrame indexed by (t, code) with one column per
    factor, values = stage-1 expanding-z on the block's codes only.

    Membership mask is applied so NaN encodes "code not admitted at
    bar t"; those cells are dropped by the pairwise-|ρ| computation.
    """
    mem    = data["membership"]
    codes  = data["codes"]
    rebal  = mem.index

    stacked_cols = {}
    for f in factors:
        A = _weekly_alpha(data["caches"], f, rebal, codes)
        if A.shape[1] < 2:
            continue
        A = C.apply_membership(A, mem)
        A1 = C.expanding_z(A)
        panel = A1.reindex(index=is_idx, columns=block_codes)
        stacked_cols[f] = panel.stack(future_stack=True)
    if not stacked_cols:
        return pd.DataFrame()
    return pd.DataFrame(stacked_cols)


def _abs_corr(panels: pd.DataFrame, min_periods: int = 100) -> pd.DataFrame:
    """Pairwise |ρ|, columns aligned."""
    return panels.corr(min_periods=min_periods).abs().fillna(0.0)


# ---------------------------------------------------------------------- #
# Greedy dedup
# ---------------------------------------------------------------------- #
def _greedy_dedup(order: list[str],
                  corr_abs: pd.DataFrame,
                  threshold: float
                  ) -> tuple[list[str], dict[str, tuple[str, float]]]:
    keep: list[str] = []
    drop_map: dict[str, tuple[str, float]] = {}
    for f in order:
        if f not in corr_abs.index:
            drop_map[f] = ("<panel_missing>", np.nan)
            continue
        conflict = None
        for rep in keep:
            if rep not in corr_abs.columns:
                continue
            c = float(corr_abs.at[f, rep])
            if np.isfinite(c) and c > threshold:
                conflict = (rep, c)
                break
        if conflict is None:
            keep.append(f)
        else:
            drop_map[f] = conflict
    return keep, drop_map


# ---------------------------------------------------------------------- #
# Per-block runner
# ---------------------------------------------------------------------- #
def dedup_block(block: str, sub_survivors: pd.DataFrame,
                data: dict, threshold: float,
                start_date: pd.Timestamp | None = None) -> dict:
    """Sub_survivors: 13.2 survivors filtered to this block, sorted by
    |zstat| desc. Returns dict with kept + drop_map + panel size.

    ``start_date`` restricts the IS window used for |ρ|. Also relaxes
    ``min_periods`` in the correlation calc if the window is short so
    partial-window diagnostics (e.g. cross_border_hk 2021+) can dedup.
    """
    tag = data["block_tag"]
    codes = data["codes"]
    block_codes = pd.Index([c for c in codes if tag.get(c) == block])
    if len(block_codes) == 0:
        return {"block": block, "kept": pd.DataFrame(),
                "drop_map": pd.DataFrame(), "n_codes": 0,
                "n_input": 0, "n_kept": 0}

    factors = sub_survivors["factor"].tolist()
    is_idx = data["membership"].index
    is_idx = is_idx[is_idx <= C.IN_SAMPLE_END]
    if start_date is not None:
        is_idx = is_idx[is_idx >= start_date]
    min_periods = min(100, max(30, int(0.4 * len(is_idx))))

    print(f"[{block}] building {len(factors)} stage-1 panels "
          f"× {len(block_codes)} codes × {len(is_idx)} IS bars "
          f"(min_periods for |ρ| = {min_periods}) ...")
    t0 = time.time()
    panels = _stacked_stage1_is(factors, data, block_codes, is_idx)
    print(f"[{block}]   panel shape = {panels.shape}   "
          f"elapsed {time.time() - t0:.1f}s")

    if panels.empty:
        return {"block": block, "kept": pd.DataFrame(),
                "drop_map": pd.DataFrame(), "n_codes": int(len(block_codes)),
                "n_input": len(factors), "n_kept": 0}

    corr = _abs_corr(panels, min_periods=min_periods)
    order = sub_survivors["factor"].tolist()
    kept, drop_map = _greedy_dedup(order, corr, threshold)

    kept_df = sub_survivors[sub_survivors["factor"].isin(kept)].copy()
    kept_df["kept_rank"] = kept_df["factor"].map({f: i + 1
                                                  for i, f in enumerate(kept)})
    kept_df = kept_df.sort_values("kept_rank")

    drop_rows = []
    for f, (rep, rho) in drop_map.items():
        z = float(sub_survivors.loc[sub_survivors["factor"] == f,
                                    "zstat"].iloc[0])
        drop_rows.append({"factor": f, "kept_by": rep,
                          "rho_abs": rho, "zstat": z})
    drop_df = pd.DataFrame(drop_rows)
    if not drop_df.empty:
        drop_df = drop_df.sort_values(["kept_by", "rho_abs"],
                                      ascending=[True, False])

    return {"block": block, "kept": kept_df, "drop_map": drop_df,
            "n_codes": int(len(block_codes)),
            "n_input": len(factors), "n_kept": len(kept)}


# ---------------------------------------------------------------------- #
# Report
# ---------------------------------------------------------------------- #
def _fmt(x, digits=2):
    return f"{x:+.{digits}f}" if pd.notna(x) else "  —"


def write_report(results: list[dict], threshold: float,
                 report_path: Path) -> None:
    lines: list[str] = []
    lines.append("# Phase 13.2b — within-block ρ-dedup (v6 pool, IS)\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    lines.append(
        f"Threshold: |ρ| ≤ {threshold} on IS stage-1-z panels stacked "
        f"across each block's admitted-ever codes (matches "
        "`pv_sweep_xs_v6`'s pool-level dedup at the within-block scope). "
        "Greedy walk in descending |zstat| — kept if |ρ| with every "
        "already-kept representative is under threshold; else dropped "
        "and mapped to its conflicting representative.\n\n"
    )

    lines.append("## 1. Survivor counts\n")
    lines.append("| block | codes tagged | 13.2 survivors | kept after dedup |")
    lines.append("|:---|---:|---:|---:|")
    for r in results:
        lines.append(f"| {r['block']} | {r['n_codes']} | "
                     f"{r['n_input']} | **{r['n_kept']}** |")
    lines.append("")

    for r in results:
        block = r["block"]
        lines.append(f"## 2. `{block}` — kept survivors "
                     f"({r['n_kept']} of {r['n_input']})\n")
        if r["kept"].empty:
            lines.append("*Nothing kept.*\n")
            continue
        lines.append("| # | factor | polarity | zstat | n | mean_ic | "
                     "mean_ic_w | pct_pos |")
        lines.append("|---:|:---|:---:|---:|---:|---:|---:|---:|")
        for _, row in r["kept"].iterrows():
            lines.append(
                f"| {int(row['kept_rank'])} | {row['factor']} | "
                f"{row['polarity']} | {_fmt(row['zstat'], 2)} | "
                f"{int(row['n_bars'])} | {_fmt(row['mean_ic'], 4)} | "
                f"{_fmt(row['mean_ic_w'], 4)} | "
                f"{row['pct_pos']*100:5.1f}% |"
            )
        lines.append("")

        drops = r["drop_map"]
        if drops is not None and not drops.empty:
            lines.append(f"### `{block}` — top drops (first 20 by |ρ|)\n")
            lines.append("| dropped factor | absorbed by | |ρ| | dropped zstat |")
            lines.append("|:---|:---|---:|---:|")
            for _, row in drops.head(20).iterrows():
                lines.append(
                    f"| {row['factor']} | {row['kept_by']} | "
                    f"{_fmt(row['rho_abs'], 3)} | "
                    f"{_fmt(row['zstat'], 2)} |"
                )
            lines.append("")

    lines.append("## 3. Read for 13.3\n")
    total_kept = sum(r["n_kept"] for r in results)
    lines.append(
        f"Down from {sum(r['n_input'] for r in results)} raw survivors to "
        f"{total_kept} after |ρ| ≤ {threshold} dedup. Holdings popularity "
        "in 13.3 runs against this reduced list — same treatment as "
        "`pv_sweep_xs_v6_dedup.csv` at the pool level.\n"
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {report_path}")


# ---------------------------------------------------------------------- #
# Main
# ---------------------------------------------------------------------- #
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--threshold", type=float, default=DEDUP_DEFAULT,
                   help=f"|ρ| threshold for dedup (default {DEDUP_DEFAULT})")
    p.add_argument("--blocks", type=str, default=None,
                   help="comma-separated blocks to dedup "
                        "(default: every block with 13.2 survivors)")
    p.add_argument("--survivors-path", type=str,
                   default=str(IC_OUT_DIR / "survivors.csv"),
                   help="13.2 survivors CSV to consume")
    p.add_argument("--start-date", type=str, default=None,
                   help="IS start date (YYYY-MM-DD) for the |ρ| panel. "
                        "Use for partial-window diagnostics like cbHK 2021+.")
    p.add_argument("--out-tag", type=str, default=None,
                   help="suffix for output paths so a partial-window "
                        "re-run doesn't overwrite canonical outputs.")
    return p.parse_args()


def main():
    args = _parse_args()

    tag = f"_{args.out_tag}" if args.out_tag else ""
    out_root = C.DATA_DIR / f"within_block_dedup_v6{tag}"
    report_p = C.REPORTS_DIR / f"within_block_dedup_v6{tag}_report.md"
    out_root.mkdir(parents=True, exist_ok=True)
    start_date = pd.Timestamp(args.start_date) if args.start_date else None

    survivors_path = Path(args.survivors_path)
    if not survivors_path.exists():
        raise FileNotFoundError(
            f"missing 13.2 survivors CSV at {survivors_path}; "
            "run within_block_ic_v6.py first"
        )
    surv = pd.read_csv(survivors_path)
    print(f"loaded 13.2 survivors: {len(surv)} rows across "
          f"{surv['block'].nunique()} blocks")

    blocks_all = sorted(surv["block"].unique().tolist())
    if args.blocks:
        keep = tuple(x.strip() for x in args.blocks.split(","))
        blocks = [b for b in blocks_all if b in keep]
    else:
        blocks = blocks_all
    if not blocks:
        raise RuntimeError(f"no matching blocks; available: {blocks_all}")
    print(f"dedup blocks: {blocks}")

    data = _load_inputs(C.DATA_DIR, None)

    results: list[dict] = []
    for b in blocks:
        sub = surv[surv["block"] == b].sort_values(
            "abs_zstat", ascending=False, key=lambda s: s.abs()
        ) if "abs_zstat" in surv.columns else \
              surv[surv["block"] == b].assign(
                  _abs=lambda d: d["zstat"].abs()
              ).sort_values("_abs", ascending=False).drop(columns=["_abs"])
        r = dedup_block(b, sub.reset_index(drop=True), data,
                        args.threshold, start_date=start_date)
        results.append(r)

        block_out = out_root / b
        block_out.mkdir(parents=True, exist_ok=True)
        r["kept"].to_csv(block_out / "kept.csv", index=False)
        if not r["drop_map"].empty:
            r["drop_map"].to_csv(block_out / "drop_map.csv", index=False)
        print(f"[{b}] kept {r['n_kept']} / {r['n_input']}  "
              f"→ {block_out}")

    write_report(results, args.threshold, report_p)


if __name__ == "__main__":
    main()
