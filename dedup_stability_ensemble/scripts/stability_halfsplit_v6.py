"""
v6/scripts/stability_halfsplit_v6.py
====================================
Phase 8.1 — half-split IC stability check on the Phase 7 dedup shortlist.

For each factor in ``data/pv_sweep_xs_v6_dedup.csv``:

  1. Rebuild membership-masked stage-1 (expanding-z) → stage-2 (CS Gaussian rank).
  2. Split the valid IS ỹ bars down the middle by bar index into h1, h2.
  3. Per-bar Spearman IC on each half + full IS. Aggregate with the ragged
     ``ic_summary(ic, n_per_bar=N_t)`` → primary metric ``zstat``.
  4. Stability pass:
       - sign(mean_ic_h1) == sign(mean_ic_h2) == sign(mean_ic_full)     AND
       - |zstat_h1| ≥ HALF_ZSTAT_GATE  AND  |zstat_h2| ≥ HALF_ZSTAT_GATE

The half gate is 1.5 (default). Rationale: under a constant true-IC null
alternative, splitting T bars in half reduces the expected zstat by √0.5
≈ 0.707, so the full 2.0 gate maps to ≈ 1.41 per half. Rounded up to 1.5
for a small margin. Matches v4pool's "positive-ish per half" philosophy
in ragged-z space (v4 used |tstat| ≥ 1.0 which is not directly
translatable to zstat).

Design §9 gate (plan §8): if ≥ 1 factor passes both stability tests
here, Phase 8 proceeds to eqw / ridge. If nothing passes, stop and
write a post-mortem — do not tune the gate to rescue.

Outputs
-------
    data/stability_halfsplit_v6.csv       one row per shortlist factor
    reports/stability_halfsplit_v6_report.md

Run
---
    python v6/scripts/stability_halfsplit_v6.py
"""
from __future__ import annotations

import argparse
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


HALF_ZSTAT_GATE = 1.5


# ---------------------------------------------------------------------- #
# Inputs
# ---------------------------------------------------------------------- #
def _load_inputs(data_dir: Path) -> dict:
    mem = pd.read_parquet(data_dir / "universe_v6" / "membership.parquet")
    codes = list(mem.columns[mem.any(axis=0)])
    mem = mem[codes].astype(bool)

    y = pd.read_parquet(data_dir / "panels_v6" / "label_ranked_risk_adj.parquet")[codes]

    dedup_csv = data_dir / "pv_sweep_xs_v6_dedup.csv"
    if not dedup_csv.exists():
        raise SystemExit(f"missing {dedup_csv} — run pv_sweep_xs_v6.py first")
    dedup = pd.read_csv(dedup_csv)

    caches = C.load_caches_v6("1d", codes)
    return {"membership": mem, "codes": codes, "label": y,
            "caches": caches, "dedup": dedup}


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
# Per-factor stability
# ---------------------------------------------------------------------- #
def _summarize_half(ic: pd.Series, n_per_bar: pd.Series,
                    sign_full: int) -> dict:
    """Ragged ic_summary on one half. Returns primary zstat + legacy IC stats
    plus per-half pass flags."""
    s = C.ic_summary(ic, n_per_bar=n_per_bar)
    ok_sign  = (np.isfinite(s["mean"])
                and int(np.sign(s["mean"])) == sign_full)
    ok_zstat = (np.isfinite(s["zstat"])
                and abs(s["zstat"]) >= HALF_ZSTAT_GATE)
    s["ok_sign"]  = bool(ok_sign)
    s["ok_zstat"] = bool(ok_zstat)
    return s


def _factor_row(name: str, data: dict,
                valid_bars: pd.DatetimeIndex,
                h1_bars: pd.DatetimeIndex,
                h2_bars: pd.DatetimeIndex) -> dict:
    mem   = data["membership"]
    codes = data["codes"]
    y     = data["label"]
    rebal = mem.index

    A = _weekly_alpha(data["caches"], name, rebal, codes)
    A = C.apply_membership(A, mem)
    A2 = C.cs_gaussian_rank(C.expanding_z(A))

    # Full valid IS window
    ic_full = C.per_bar_spearman(A2.loc[valid_bars], y.loc[valid_bars])
    N_full  = C.per_bar_n_valid(A2.loc[valid_bars], y.loc[valid_bars],
                                membership=mem)
    s_full = C.ic_summary(ic_full, n_per_bar=N_full)
    sign_full = (int(np.sign(s_full["mean"]))
                 if np.isfinite(s_full["mean"]) and s_full["mean"] != 0 else 0)

    # Two halves — same transform, only the bar slice changes
    ic_h1 = C.per_bar_spearman(A2.loc[h1_bars], y.loc[h1_bars])
    N_h1  = C.per_bar_n_valid(A2.loc[h1_bars], y.loc[h1_bars], membership=mem)
    ic_h2 = C.per_bar_spearman(A2.loc[h2_bars], y.loc[h2_bars])
    N_h2  = C.per_bar_n_valid(A2.loc[h2_bars], y.loc[h2_bars], membership=mem)

    s_h1 = _summarize_half(ic_h1, N_h1, sign_full)
    s_h2 = _summarize_half(ic_h2, N_h2, sign_full)

    pass_stability = (s_h1["ok_sign"] and s_h2["ok_sign"]
                      and s_h1["ok_zstat"] and s_h2["ok_zstat"])

    return {
        "factor":     name,
        # Full IS window
        "n_full":     int(s_full["n_bars"]),
        "mean_full":  float(s_full["mean"]),
        "zstat_full": float(s_full["zstat"]),
        "mean_N_full": float(s_full["mean_N"]),
        # h1
        "n_h1":       int(s_h1["n_bars"]),
        "mean_h1":    float(s_h1["mean"]),
        "zstat_h1":   float(s_h1["zstat"]),
        "mean_N_h1":  float(s_h1["mean_N"]),
        # h2
        "n_h2":       int(s_h2["n_bars"]),
        "mean_h2":    float(s_h2["mean"]),
        "zstat_h2":   float(s_h2["zstat"]),
        "mean_N_h2":  float(s_h2["mean_N"]),
        # Pass flags
        "sign_ok":    bool(s_h1["ok_sign"] and s_h2["ok_sign"]),
        "zstat_ok":   bool(s_h1["ok_zstat"] and s_h2["ok_zstat"]),
        "pass":       bool(pass_stability),
    }


# ---------------------------------------------------------------------- #
# Report
# ---------------------------------------------------------------------- #
def _fmt_ic(v: float) -> str:
    return "n/a" if not np.isfinite(v) else f"{v:+.4f}"


def _fmt_z(v: float) -> str:
    return "n/a" if not np.isfinite(v) else f"{v:+.2f}"


def _write_report(out: pd.DataFrame,
                  valid_bars: pd.DatetimeIndex,
                  h1_bars: pd.DatetimeIndex,
                  h2_bars: pd.DatetimeIndex,
                  reports_dir: Path) -> str:
    n_pass = int(out["pass"].sum())
    n_tot  = int(len(out))
    lines: list[str] = []
    lines.append("# Phase 8.1 — half-split IC stability (v6)\n")
    lines.append(
        f"Splits the {len(valid_bars)}-bar valid IS ỹ window in half by bar "
        f"index and recomputes per-bar Spearman IC + ragged zstat on each "
        f"half, for the {n_tot} factors in "
        f"`data/pv_sweep_xs_v6_dedup.csv`.\n"
    )
    lines.append(
        f"**Stability pass rule**: sign matches full on both halves AND "
        f"`|zstat_hK| ≥ {HALF_ZSTAT_GATE:.1f}` on both halves. The zstat gate "
        f"is softened from the full 2.0 screening gate because splitting T "
        f"in half reduces the expected zstat by √0.5 ≈ 0.71 under a "
        f"constant-IC null alternative (2.0 · √0.5 ≈ 1.41; rounded up to "
        f"{HALF_ZSTAT_GATE:.1f} for a small margin).\n"
    )
    lines.append(
        f"**Halves**: "
        f"h1 = {h1_bars.min().date()} → {h1_bars.max().date()} "
        f"({len(h1_bars)} bars), "
        f"h2 = {h2_bars.min().date()} → {h2_bars.max().date()} "
        f"({len(h2_bars)} bars).\n"
    )

    lines.append("\n## Per-factor half-split IC\n")
    lines.append("| factor | n_full | mean_full | z_full | mean_h1 | z_h1 | "
                 "mean_h2 | z_h2 | sign_ok | z_ok | pass |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|:-:|:-:|:-:|")
    for _, r in out.iterrows():
        lines.append(
            f"| {r['factor']} | {int(r['n_full'])} | "
            f"{_fmt_ic(r['mean_full'])} | {_fmt_z(r['zstat_full'])} | "
            f"{_fmt_ic(r['mean_h1'])} | {_fmt_z(r['zstat_h1'])} | "
            f"{_fmt_ic(r['mean_h2'])} | {_fmt_z(r['zstat_h2'])} | "
            f"{'✓' if r['sign_ok'] else '✗'} | "
            f"{'✓' if r['zstat_ok'] else '✗'} | "
            f"{'**PASS**' if r['pass'] else 'FAIL'} |"
        )

    passers = out[out["pass"]]["factor"].tolist()
    lines.append(f"\n**Survivors ({n_pass}/{n_tot})**: "
                 f"{', '.join(passers) if passers else '(none)'}\n")

    # Design §9 Phase 8 gate reminder
    lines.append("\n## Phase 8 gate\n")
    lines.append(
        "Design §9 requires ≥ 1 factor at |zstat| ≥ 2 surviving half-split "
        "stability. "
    )
    if n_pass >= 1:
        lines.append(f"**Gate passes** ({n_pass} survivor{'s' if n_pass != 1 else ''}). "
                     "Phase 8.2 (eqw baseline) and downstream may proceed.")
    else:
        lines.append("**Gate FAILS.** Do not tune the gate to rescue. "
                     "Write a post-mortem to `reports/postmortem_pv_sweep_v6.md` "
                     "and escalate before rerunning any Phase 8 or 9 step.")

    lines.append("\n## Files\n")
    lines.append("- per-factor per-half : `data/stability_halfsplit_v6.csv`")

    reports_dir.mkdir(parents=True, exist_ok=True)
    p = reports_dir / "stability_halfsplit_v6_report.md"
    p.write_text("\n".join(lines))
    return str(p)


# ---------------------------------------------------------------------- #
# Driver
# ---------------------------------------------------------------------- #
def run(data_dir: Path | None = None,
        reports_dir: Path | None = None) -> None:
    data_dir    = Path(data_dir)    if data_dir    else C.DATA_DIR
    reports_dir = Path(reports_dir) if reports_dir else C.REPORTS_DIR

    data = _load_inputs(data_dir)
    factors = data["dedup"]["factor"].tolist()
    rebal = data["membership"].index
    is_idx = rebal[rebal <= C.IN_SAMPLE_END]

    # Restrict to IS bars where ỹ has any finite entry (matches sweep n_bars).
    y_is = data["label"].loc[is_idx].dropna(how="all")
    valid_bars = y_is.index
    n = len(valid_bars)
    mid = n // 2
    h1_bars = valid_bars[:mid]
    h2_bars = valid_bars[mid:]

    print("=" * 78)
    print(f"Phase 8.1 half-split stability — {len(factors)} shortlist factors")
    print(f"IS end = {C.IN_SAMPLE_END.date()}   "
          f"per-half gate: sign matches full AND |zstat| ≥ {HALF_ZSTAT_GATE}")
    print("=" * 78)
    print(f"valid IS ỹ bars: {n}   "
          f"h1: {h1_bars.min().date()} → {h1_bars.max().date()}  ({len(h1_bars)})   "
          f"h2: {h2_bars.min().date()} → {h2_bars.max().date()}  ({len(h2_bars)})")

    rows = [_factor_row(f, data, valid_bars, h1_bars, h2_bars) for f in factors]
    out = pd.DataFrame(rows)
    csv_p = data_dir / "stability_halfsplit_v6.csv"
    out.to_csv(csv_p, index=False)

    # Console preview
    print("\n" + "=" * 78)
    print("Per-factor half-split")
    print("=" * 78)
    disp = out.copy()
    for c in ["mean_full", "mean_h1", "mean_h2"]:
        disp[c] = disp[c].map(_fmt_ic)
    for c in ["zstat_full", "zstat_h1", "zstat_h2"]:
        disp[c] = disp[c].map(_fmt_z)
    print(disp[[
        "factor", "mean_full", "zstat_full",
        "mean_h1", "zstat_h1", "mean_h2", "zstat_h2",
        "sign_ok", "zstat_ok", "pass",
    ]].to_string(index=False))

    report_p = _write_report(out, valid_bars, h1_bars, h2_bars, reports_dir)
    print(f"\nwrote {csv_p}")
    print(f"wrote {report_p}")

    n_pass = int(out["pass"].sum())
    print(f"\nPhase 8 gate: {n_pass}/{len(out)} pass "
          f"({'OK, proceed to 8.2' if n_pass >= 1 else 'FAIL, write postmortem'})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir",    type=Path, default=None)
    ap.add_argument("--reports-dir", type=Path, default=None)
    args = ap.parse_args()
    run(args.data_dir, args.reports_dir)


if __name__ == "__main__":
    main()
