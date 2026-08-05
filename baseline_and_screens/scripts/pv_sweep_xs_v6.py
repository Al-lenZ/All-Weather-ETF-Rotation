"""
v6/scripts/pv_sweep_xs_v6.py
============================
Phase 7 — cross-sectional PV factor sweep on the v6 pool.

For every PV factor in ``REGISTRY['price_volume'] ∩ common_factors_v6``:

  1. Build weekly α on the W-FRI grid, membership-masked.
  2. Stage-1 expanding-z per name (min_periods = 26).
  3. Stage-2 per-bar CS Gaussian rank.
  4. IS-only per-bar Spearman IC vs ỹ = ``ranked_risk_adj_label`` (Phase 6).
  5. Per-bar N_valid → ragged ``ic_summary(ic, n_per_bar=N_t)``:
        primary   : zstat, mean_ic_w, mean_N
        auxiliary : mean_ic_52w, min_ic_52w, max_ic_52w, pct_pos_52w
        legacy    : mean, std, tstat, pct_pos, n_bars
     Plus diagnostic ``prec@q`` top + bottom at q = 0.10.

Gate (design §6, plan §7.1)
---------------------------
    |zstat| ≥ 2.0   AND   n_bars ≥ MIN_COVERAGE

Both polarities are kept — a factor with zstat = −3 is a real signal
entered with its sign flipped, and stage-2 |ρ| dedup catches
anti-correlated pairs automatically (Pearson is sign-agnostic).

OOS discipline
--------------
Screen is IS-only. Bars > ``C.IN_SAMPLE_END`` never enter the IC series,
the gate, the dedup, or the CSV. The OOS surface stays sealed until
Phase 8 downstream consumers open it.

Pre-registered v1 survivor callout (plan §7.2)
---------------------------------------------
The report always shows the v4 v1 IS-survivor set's v6 zstats /
auxiliary rolling stats in a labeled table, regardless of whether they
clear the gate. Answers "does v6's larger N confirm the v4 survivors."

Outputs
-------
    data/pv_sweep_xs_v6.csv         full sweep, ranked by |zstat| desc
    data/pv_sweep_xs_v6_dedup.csv   gate-passing subset after |ρ| ≤ 0.5 dedup
    reports/pv_sweep_xs_v6_report.md

Run
---
    python v6/scripts/pv_sweep_xs_v6.py
    python v6/scripts/pv_sweep_xs_v6.py --dedup-threshold 0.3
"""
from __future__ import annotations

import argparse
import time
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
MIN_COVERAGE     = 100     # min IS bars with a defined Spearman IC
DEDUP_DEFAULT    = 0.5     # |ρ| ≤ this in stage-2 stacked-panel dedup
Z_STAT_GATE      = 2.0
PRECISION_Q      = 0.10    # diagnostic-only prec@q

# The v4 v1 IS-survivor set (design §6, IMPLEMENTATION_PLAN §7.2). Frozen.
V1_SURVIVORS: tuple[str, ...] = (
    "wq_023", "wq_046", "alpha_071", "wq_081", "wq_048", "alpha_028",
    "alpha_104", "alpha_036", "wq_061", "wq_068", "wq_012", "wq_008",
    "wq_059",
)


# ---------------------------------------------------------------------- #
# Inputs
# ---------------------------------------------------------------------- #
def _load_inputs(data_dir: Path) -> dict:
    """Load MEMBERSHIP + label ỹ + factor caches. Restrict codes to the
    ever-admitted union (same convention as ``xs_screen_v6``)."""
    mem = pd.read_parquet(data_dir / "universe_v6" / "membership.parquet")
    codes = list(mem.columns[mem.any(axis=0)])
    mem = mem[codes].astype(bool)

    y = pd.read_parquet(data_dir / "panels_v6" / "label_ranked_risk_adj.parquet")[codes]

    caches = C.load_caches_v6("1d", codes)
    common = set(C.common_factors_v6(caches))
    if not common:
        raise RuntimeError("no common factors in v6 cache — build Phase 4 first")

    pv_all = set(REGISTRY.list_factors("price_volume"))
    pv_names = sorted(pv_all & common)
    if not pv_names:
        raise RuntimeError("no PV factors in v6 cache-common intersection")

    return {
        "membership": mem,
        "codes":      codes,
        "label":      y,
        "caches":     caches,
        "pv_names":   pv_names,
        "pv_total":   len(pv_all),
        "common_n":   len(common),
    }


def _weekly_alpha(caches: dict, factor: str,
                  rebal: pd.DatetimeIndex,
                  codes: list[str]) -> pd.DataFrame:
    """Reindex each cache's factor Series directly to the W-FRI grid.
    Same pattern as ``xs_screen_v6._weekly_alpha`` — skip the daily-union
    intermediate that ``build_alpha_panel_v6`` would build.
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
# Per-factor screen
# ---------------------------------------------------------------------- #
def _factor_row(name: str, data: dict, is_idx: pd.DatetimeIndex
                ) -> tuple[dict | None, pd.DataFrame | None]:
    """Return (summary row, stage-2 panel) for one factor. Stage-2 is
    membership-masked, IS-only, kept in memory for the dedup step.
    Returns (None, None) if fewer than MIN_COVERAGE IS bars have a defined IC.
    """
    mem   = data["membership"]
    codes = data["codes"]
    y     = data["label"]
    rebal = mem.index

    A = _weekly_alpha(data["caches"], name, rebal, codes)
    if A.shape[1] < 2 or A.notna().to_numpy().sum() == 0:
        return None, None

    A  = C.apply_membership(A, mem)
    A1 = C.expanding_z(A)
    A2 = C.cs_gaussian_rank(A1)

    A2_is = A2.loc[is_idx]
    y_is  = y.loc[is_idx]

    ic = C.per_bar_spearman(A2_is, y_is)
    if int(ic.notna().sum()) < MIN_COVERAGE:
        return None, None

    N_t = C.per_bar_n_valid(A2_is, y_is, membership=mem)
    s   = C.ic_summary(ic, n_per_bar=N_t)

    p_top = C.precision_at_q(A2_is, y_is, q=PRECISION_Q,
                             side="top",    membership=mem)
    p_bot = C.precision_at_q(A2_is, y_is, q=PRECISION_Q,
                             side="bottom", membership=mem)

    row = {
        "factor":      name,
        # legacy IC stats (unweighted, kept for continuity)
        "n_bars":      int(s["n_bars"]),
        "mean_ic":     float(s["mean"]),
        "std_ic":      float(s["std"]),
        "tstat_ic":    float(s["tstat"]),
        "pct_pos":     float(s["pct_pos"]),
        # primary ragged-panel metric (design §5.2) — this is the gate
        "zstat":       float(s["zstat"]),
        "mean_ic_w":   float(s["mean_ic_w"]),
        "mean_N":      float(s["mean_N"]),
        # auxiliary rolling-52w rank IC (design §5.2)
        "mean_ic_52w": float(s["mean_ic_52w"]),
        "min_ic_52w":  float(s["min_ic_52w"]),
        "max_ic_52w":  float(s["max_ic_52w"]),
        "pct_pos_52w": float(s["pct_pos_52w"]),
        # diagnostic precision@q at q = PRECISION_Q
        f"prec_top_q{int(PRECISION_Q*100):02d}":
            float(p_top.dropna().mean())    if p_top.notna().any() else np.nan,
        f"prec_bot_q{int(PRECISION_Q*100):02d}":
            float(p_bot.dropna().mean())    if p_bot.notna().any() else np.nan,
    }
    return row, A2_is


def _gate(row: pd.Series) -> bool:
    return (
        np.isfinite(row["zstat"]) and abs(row["zstat"]) >= Z_STAT_GATE
        and int(row["n_bars"]) >= MIN_COVERAGE
    )


# ---------------------------------------------------------------------- #
# Dedup on stage-2 stacked (T·N) IS panels
# ---------------------------------------------------------------------- #
def _stacked_is_panels(stage2: dict[str, pd.DataFrame],
                       is_idx: pd.DatetimeIndex,
                       codes: list[str]) -> pd.DataFrame:
    cols = {}
    for name, panel in stage2.items():
        cols[name] = panel.reindex(index=is_idx, columns=codes).stack(future_stack=True)
    return pd.DataFrame(cols)


def _greedy_dedup(order: list[str],
                  corr_abs: pd.DataFrame,
                  threshold: float
                  ) -> tuple[list[str], dict[str, tuple[str, float]]]:
    """Walk in ``order``; keep f if |ρ(f, rep)| ≤ threshold vs every kept rep."""
    keep: list[str] = []
    drop_map: dict[str, tuple[str, float]] = {}
    for f in order:
        if f not in corr_abs.index:
            continue
        conflict = None
        for rep in keep:
            if rep not in corr_abs.columns:
                continue
            c = float(corr_abs.at[f, rep])
            if c > threshold:
                conflict = (rep, c)
                break
        if conflict is None:
            keep.append(f)
        else:
            drop_map[f] = conflict
    return keep, drop_map


# ---------------------------------------------------------------------- #
# Report
# ---------------------------------------------------------------------- #
PREC_TOP_COL = f"prec_top_q{int(PRECISION_Q*100):02d}"
PREC_BOT_COL = f"prec_bot_q{int(PRECISION_Q*100):02d}"


def _fmt_row(r: pd.Series) -> str:
    return (
        f"| {r['factor']:<20s} | {int(r['n_bars']):>4d} | "
        f"{r['mean_ic']:+.4f} | {r['zstat']:+.2f} | "
        f"{r['mean_ic_w']:+.4f} | {r['mean_N']:5.1f} | "
        f"{r['pct_pos']*100:5.1f}% | "
        f"{r['mean_ic_52w']:+.3f} | {r['pct_pos_52w']*100:5.1f}% | "
        f"{r[PREC_TOP_COL]:.3f} | {r[PREC_BOT_COL]:.3f} |"
    )


_HEADER = (
    "| factor | n | mean_ic | zstat | mean_ic_w | mean_N | pct_pos | "
    "mean_ic_52w | pct_pos_52w | prec@top10% | prec@bot10% |"
)
_ALIGN = (
    "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
)


def _write_report(full: pd.DataFrame, passed: pd.DataFrame,
                  dedup: pd.DataFrame,
                  drop_map: dict[str, tuple[str, float]],
                  survivor_rows: pd.DataFrame,
                  threshold: float,
                  is_start: pd.Timestamp, is_end: pd.Timestamp,
                  n_bars_is: int, n_pv: int, pv_total: int,
                  reports_dir: Path) -> str:
    lines: list[str] = []
    lines.append("# Phase 7 — PV factor XS-IC sweep (v6 pool, IS only)\n")
    lines.append(
        "Screens every PV factor in the registry against the ranked risk-adjusted "
        "label ỹ (per-bar CS Gaussian rank of `fwd_1w / σ_causal_26w` from "
        "`panels_v6/label_ranked_risk_adj.parquet`).\n"
    )
    lines.append(f"**Universe**: v6, ragged W-FRI membership panel  ")
    lines.append(f"**Factor pool**: {n_pv} PV factors "
                 f"(REGISTRY['price_volume'] ∩ v6 cache-common; "
                 f"registry total = {pv_total})  ")
    lines.append(f"**Feature transform**: membership mask → stage-1 expanding-z "
                 f"(min_periods = {C.Z_MIN_PERIODS}) → stage-2 per-bar CS Gaussian rank  ")
    lines.append(f"**IS window**: {is_start.date()} → {is_end.date()}  "
                 f"({n_bars_is} weekly bars, W-FRI). OOS is sealed for this sweep.  ")
    lines.append(f"**Primary metric**: `zstat` = mean(ic·√(N−1)) · √T "
                 f"(design §5.2, ragged-aware).  ")
    lines.append(f"**Auxiliary**: `mean_ic_w` (N-weighted mean IC), `mean_N`, "
                 f"and rolling 52w rank-IC summaries `mean_ic_52w` / `pct_pos_52w`.  ")
    lines.append(f"**Diagnostic**: prec@q at q = {PRECISION_Q:.2f} "
                 f"(K_t = ⌈q · N_t⌉ ≈ {int(round(PRECISION_Q * 85))} at mean_N ≈ 85).  ")
    lines.append(f"**Gate**: |zstat| ≥ {Z_STAT_GATE:.1f} and n_bars ≥ {MIN_COVERAGE}. "
                 f"Both polarities kept (sign captured downstream).  ")
    lines.append(f"**Dedup**: greedy on stage-2 stacked (T·N) IS panels, "
                 f"|ρ| ≤ {threshold}. Walk order = |zstat| desc.\n")

    # ---- section 1: top 30 raw ----
    lines.append("## 1. Top-30 raw ranking by |zstat|\n")
    disp = full.reindex(
        columns=["factor", "n_bars", "mean_ic", "zstat", "mean_ic_w", "mean_N",
                 "pct_pos", "mean_ic_52w", "pct_pos_52w",
                 PREC_TOP_COL, PREC_BOT_COL]
    ).copy()
    disp = (disp.assign(_k=disp["zstat"].abs())
                .sort_values("_k", ascending=False)
                .drop(columns=["_k"])
                .reset_index(drop=True))
    lines.append(_HEADER)
    lines.append(_ALIGN)
    for _, r in disp.head(30).iterrows():
        lines.append(_fmt_row(r))

    # ---- section 2: gate-passing ----
    lines.append(f"\n## 2. Gate-passing candidates ({len(passed)})\n")
    lines.append(f"|zstat| ≥ {Z_STAT_GATE:.1f} and n_bars ≥ {MIN_COVERAGE}.  ")
    lines.append(f"Random baseline prec@q = {PRECISION_Q:.2f} "
                 f"(diagnostic only, not gated).\n")
    if len(passed):
        lines.append(_HEADER)
        lines.append(_ALIGN)
        for _, r in passed.iterrows():
            lines.append(_fmt_row(r))
    else:
        lines.append("_(no factor clears the gate)_")

    # ---- section 3: dedup shortlist ----
    lines.append(f"\n## 3. Dedup shortlist  (|ρ| ≤ {threshold} on stage-2 IS)  — "
                 f"{len(dedup)} of {len(passed)} kept\n")
    if len(dedup):
        lines.append(_HEADER)
        lines.append(_ALIGN)
        for _, r in dedup.iterrows():
            lines.append(_fmt_row(r))
    if drop_map:
        lines.append(f"\nDropped in dedup ({len(drop_map)}) — pairs at |ρ| > "
                     f"{threshold}:\n")
        lines.append("| dropped | vs representative | |ρ| |")
        lines.append("|---|---|---:|")
        for f, (rep, rho) in sorted(drop_map.items()):
            lines.append(f"| {f} | {rep} | {rho:.3f} |")

    # ---- section 4: v1 survivor callout ----
    lines.append(f"\n## 4. v1 IS survivors — v6 zstat cross-check (pre-registered)\n")
    lines.append(
        "Hard-coded v1 IS-survivor set (design §6). Shown regardless of "
        "whether they clear the v6 gate — the point is to see whether v6's "
        f"larger N (mean ≈ 85 vs v4's 15) confirms the v4 survivors more "
        "decisively or fails to.\n"
    )
    if len(survivor_rows):
        lines.append(_HEADER)
        lines.append(_ALIGN)
        for _, r in survivor_rows.iterrows():
            lines.append(_fmt_row(r))
        missing = sorted(set(V1_SURVIVORS) - set(survivor_rows["factor"]))
        if missing:
            lines.append(f"\n_Not present in v6 cache-common: {', '.join(missing)}_")
    else:
        lines.append("_No v1 survivors found in the v6 sweep output._")

    # ---- files ----
    lines.append("\n## 5. Files\n")
    lines.append("- per-factor summary : `data/pv_sweep_xs_v6.csv`")
    lines.append("- dedup shortlist    : `data/pv_sweep_xs_v6_dedup.csv`")

    txt = "\n".join(lines)
    reports_dir.mkdir(parents=True, exist_ok=True)
    p = reports_dir / "pv_sweep_xs_v6_report.md"
    p.write_text(txt)
    return str(p)


# ---------------------------------------------------------------------- #
# Driver
# ---------------------------------------------------------------------- #
def run(data_dir: Path | None = None,
        reports_dir: Path | None = None,
        dedup_threshold: float = DEDUP_DEFAULT) -> None:
    data_dir    = Path(data_dir)    if data_dir    else C.DATA_DIR
    reports_dir = Path(reports_dir) if reports_dir else C.REPORTS_DIR

    data_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    data = _load_inputs(data_dir)
    rebal = data["membership"].index
    is_idx = rebal[rebal <= C.IN_SAMPLE_END]

    print("=" * 78)
    print(f"Phase 7 PV sweep — v6 pool   "
          f"IS end = {C.IN_SAMPLE_END.date()}   "
          f"N_codes = {len(data['codes'])}   "
          f"dedup |ρ| ≤ {dedup_threshold}")
    print("=" * 78)
    print(f"PV factors: {len(data['pv_names'])} in cache-common "
          f"(registry total {data['pv_total']}, cache-common total {data['common_n']})")
    print(f"IS bars: {len(is_idx)}   ({is_idx.min().date()} → {is_idx.max().date()})")

    t0 = time.time()
    rows: list[dict] = []
    stage2: dict[str, pd.DataFrame] = {}
    skipped = 0
    for i, name in enumerate(data["pv_names"]):
        if i and i % 40 == 0:
            print(f"  ... {i}/{len(data['pv_names'])}   ({time.time() - t0:.1f}s)")
        row, panel = _factor_row(name, data, is_idx)
        if row is None:
            skipped += 1
            continue
        rows.append(row)
        stage2[name] = panel
    print(f"summary built: {len(rows)} kept, {skipped} skipped for coverage "
          f"({time.time() - t0:.1f}s)")

    full = pd.DataFrame(rows)
    full = (full.assign(_k=full["zstat"].abs())
                .sort_values("_k", ascending=False)
                .drop(columns=["_k"])
                .reset_index(drop=True))
    full_csv = data_dir / "pv_sweep_xs_v6.csv"
    full.to_csv(full_csv, index=False)
    print(f"wrote {full_csv}  ({len(full)} rows)")

    # ---- gate ----
    mask = full.apply(_gate, axis=1)
    passed = (full[mask]
                 .assign(_k=full[mask]["zstat"].abs())
                 .sort_values("_k", ascending=False)
                 .drop(columns=["_k"])
                 .reset_index(drop=True))
    print(f"gate-passing (|zstat| ≥ {Z_STAT_GATE}, n ≥ {MIN_COVERAGE}): {len(passed)}")

    # ---- dedup ----
    if len(passed) == 0:
        dedup = passed.copy()
        drop_map: dict[str, tuple[str, float]] = {}
    else:
        print("stacking stage-2 IS panels for dedup corr...")
        t1 = time.time()
        flat = _stacked_is_panels(
            {n: stage2[n] for n in passed["factor"]}, is_idx, data["codes"]
        )
        corr_abs = flat.corr().abs().fillna(0.0)
        print(f"corr matrix: {corr_abs.shape}   ({time.time() - t1:.1f}s)")
        keep, drop_map = _greedy_dedup(
            passed["factor"].tolist(), corr_abs, dedup_threshold
        )
        dedup = (passed[passed["factor"].isin(keep)]
                    .set_index("factor").loc[keep].reset_index())

    dedup_csv = data_dir / "pv_sweep_xs_v6_dedup.csv"
    dedup.to_csv(dedup_csv, index=False)
    print(f"wrote {dedup_csv}  ({len(dedup)} rows)")

    # ---- v1 survivor callout ----
    survivor_rows = (full[full["factor"].isin(V1_SURVIVORS)]
                        .set_index("factor")
                        .reindex([f for f in V1_SURVIVORS if f in set(full['factor'])])
                        .reset_index())

    report_path = _write_report(
        full, passed, dedup, drop_map, survivor_rows,
        dedup_threshold, is_idx.min(), is_idx.max(),
        len(is_idx), len(data["pv_names"]), data["pv_total"], reports_dir
    )
    print(f"wrote {report_path}")

    # ---- console preview ----
    print("\n" + "=" * 78)
    print(f"TOP-15 RAW  (|zstat|, {len(full)} factors)")
    print("=" * 78)
    print(full.head(15)[
        ["factor", "n_bars", "mean_ic", "zstat", "mean_ic_w", "mean_N",
         "pct_pos", "mean_ic_52w", "pct_pos_52w",
         PREC_TOP_COL, PREC_BOT_COL]
    ].to_string(index=False,
                formatters={"mean_ic":     lambda v: f"{v:+.4f}",
                            "zstat":       lambda v: f"{v:+.2f}",
                            "mean_ic_w":   lambda v: f"{v:+.4f}",
                            "mean_N":      lambda v: f"{v:.1f}",
                            "pct_pos":     lambda v: f"{v*100:5.1f}%",
                            "mean_ic_52w": lambda v: f"{v:+.3f}",
                            "pct_pos_52w": lambda v: f"{v*100:5.1f}%",
                            PREC_TOP_COL:  lambda v: f"{v:.3f}",
                            PREC_BOT_COL:  lambda v: f"{v:.3f}"}))
    print("\n" + "=" * 78)
    print(f"DEDUP SHORTLIST  ({len(dedup)} factors)")
    print("=" * 78)
    if len(dedup):
        print(dedup[
            ["factor", "n_bars", "mean_ic", "zstat", "mean_ic_w",
             "mean_ic_52w", "pct_pos_52w"]
        ].to_string(index=False,
                    formatters={"mean_ic":     lambda v: f"{v:+.4f}",
                                "zstat":       lambda v: f"{v:+.2f}",
                                "mean_ic_w":   lambda v: f"{v:+.4f}",
                                "mean_ic_52w": lambda v: f"{v:+.3f}",
                                "pct_pos_52w": lambda v: f"{v*100:5.1f}%"}))
    else:
        print("(none)")
    print("=" * 78)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir",     type=Path, default=None)
    ap.add_argument("--reports-dir",  type=Path, default=None)
    ap.add_argument("--dedup-threshold", type=float, default=DEDUP_DEFAULT,
                    help=f"|ρ| threshold for stage-2 dedup (default {DEDUP_DEFAULT})")
    args = ap.parse_args()
    run(args.data_dir, args.reports_dir, args.dedup_threshold)


if __name__ == "__main__":
    main()
