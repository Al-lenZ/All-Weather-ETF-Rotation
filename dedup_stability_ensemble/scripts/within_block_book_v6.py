"""
v6/scripts/within_block_book_v6.py
==================================
Phase 13.4 — within-block isolated book vs block-native nulls.

For each 13.2b kept factor × each block × each sizing kernel
(1/σ, eqw), build a top-⌈q·N_b(t)⌉ book restricted to the block's
members. Compare to two block-native null books:

    eqw_null    — hold every eligible name in the block, weight = 1/N_b.
    invvol_null — hold every eligible name, weight ∝ 1/σ_causal.
                  (The block-scoped analog of `T2_bond_invvol` from
                  `bond_attribution_v6`.)

The eqw null is the "no signal, no sizing" baseline; the 1/σ null is
"no signal but keep sizing". A factor whose top-K book beats both on
Sharpe with CAGR ≥ eqw null is doing real within-block selection
after cost.

Method
------
Selection uses `hysteresis_engine_v6.build_hysteresis_weights` with
`ε = 0.20`, `rule = "replace"` (production long_q20 finalist config).
- **Sizing = 1/σ**  → pass the real `sigma_causal_26w` panel.
- **Sizing = eqw**  → pass a constant σ = 1 panel. In `_leg_weights`
  this makes `inv_row` uniform, so `Σw = 1` renormalization gives
  equal weights on the held set. Verified: the eligibility mask
  requires σ > 0 which the constant panel satisfies; the ranking
  layer still uses the real factor, unchanged.

Blocks use `BLOCK_MERGES = {smallcap_cn → broad_cn}` at load. Cost 10
bp/side (`E.DEFAULT_COST_PER_TRADE`). IS-only (bars ≤
`C.IN_SAMPLE_END`); OOS stays sealed (feedback-oos-discipline).

Pass rule (per user 2026-07-22): a factor book (any sizing) passes iff

    IS Sharpe > MAX(Sharpe(eqw_null), Sharpe(invvol_null))
    IS CAGR  ≥ CAGR(eqw_null)

Both nulls are on the same block, same window, same cost.

Outputs
-------
    data/within_block_book_v6/{block}/summary.csv
    data/within_block_book_v6/{block}/nulls.csv
    data/within_block_book_v6/{block}/{factor}_{sizing}_net_ret.csv
    reports/within_block_book_v6_report.md

Run
---
    python v6/scripts/within_block_book_v6.py
    python v6/scripts/within_block_book_v6.py --blocks broad_cn
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
BLOCK_MERGES = {"smallcap_cn": "broad_cn"}    # per user 2026-07-22
Q_DEFAULT    = 0.20
EPSILON      = 0.20
RULE         = "replace"
COST         = E.DEFAULT_COST_PER_TRADE
OUT_DIR      = C.DATA_DIR / "within_block_book_v6"
DEDUP_ROOT   = C.DATA_DIR / "within_block_dedup_v6"


# ---------------------------------------------------------------------- #
# Loaders
# ---------------------------------------------------------------------- #
def _load_shared(data_dir: Path) -> dict:
    mem = pd.read_parquet(data_dir / "universe_v6" / "membership.parquet")
    codes = list(mem.columns[mem.any(axis=0)])
    mem = mem[codes].astype(bool)
    fwd   = pd.read_parquet(data_dir / "panels_v6" / "fwd_1w.parquet")[codes]
    sigma = pd.read_parquet(data_dir / "panels_v6" / "sigma_causal_26w.parquet")[codes]

    cat = pd.read_csv(data_dir / "universe_v6" / "catalogue_tagged.csv")
    block_tag = cat.set_index("code")["current_block"].reindex(codes) \
                   .fillna("UNTAGGED").replace(BLOCK_MERGES)

    caches = C.load_caches_v6("1d", codes)
    return {"membership": mem, "codes": codes, "fwd_1w": fwd,
            "sigma": sigma, "block_tag": block_tag, "caches": caches}


def _load_kept(block: str) -> pd.DataFrame:
    p = DEDUP_ROOT / block / "kept.csv"
    if not p.exists():
        raise FileNotFoundError(
            f"missing 13.2b kept.csv at {p}; run within_block_dedup_v6.py"
        )
    return pd.read_csv(p)


# ---------------------------------------------------------------------- #
# Metrics
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


# ---------------------------------------------------------------------- #
# Null builders
# ---------------------------------------------------------------------- #
def _restrict_to_block(panel: pd.DataFrame, cols: pd.Index) -> pd.DataFrame:
    keep = [c for c in cols if c in panel.columns]
    return panel[keep]


def build_eqw_null(mem_b: pd.DataFrame, sigma_b: pd.DataFrame
                   ) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Hold every eligible name in the block, weight = 1/N_b."""
    eligible = mem_b & sigma_b.notna() & (sigma_b > 0.0)
    N_t = eligible.sum(axis=1).astype(int).rename("N_t")
    W = eligible.astype(float).div(N_t.replace(0, np.nan), axis=0).fillna(0.0)
    return W, N_t, N_t.rename("K_t")


def build_invvol_null(mem_b: pd.DataFrame, sigma_b: pd.DataFrame
                      ) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Hold every eligible name, weight ∝ 1/σ."""
    eligible = mem_b & sigma_b.notna() & (sigma_b > 0.0)
    inv = (1.0 / sigma_b).where(eligible, 0.0)
    row = inv.sum(axis=1).replace(0.0, np.nan)
    W = inv.div(row, axis=0).fillna(0.0)
    N_t = eligible.sum(axis=1).astype(int).rename("N_t")
    return W, N_t, N_t.rename("K_t")


# ---------------------------------------------------------------------- #
# Per-block runner
# ---------------------------------------------------------------------- #
def _polarized_alpha(A: pd.DataFrame, polarity: str) -> pd.DataFrame:
    return A if polarity == "raw" else -A


def run_block(block: str, kept: pd.DataFrame, data: dict,
              q: float, out_dir: Path,
              start_date: pd.Timestamp | None = None) -> dict:
    mem     = data["membership"]
    fwd     = data["fwd_1w"]
    sigma   = data["sigma"]
    tag     = data["block_tag"]
    codes   = data["codes"]

    # Post-merge block codes
    block_codes = pd.Index([c for c in codes if tag.get(c) == block])
    if len(block_codes) == 0:
        return {"block": block, "summary": pd.DataFrame(),
                "nulls": pd.DataFrame()}

    mem_b   = mem[block_codes]
    fwd_b   = fwd[block_codes]
    sigma_b = sigma[block_codes]
    sigma_eqw = pd.DataFrame(1.0, index=sigma_b.index,
                             columns=sigma_b.columns).where(mem_b, np.nan)

    is_end = C.IN_SAMPLE_END
    is_mask = mem_b.index <= is_end
    if start_date is not None:
        is_mask = is_mask & (mem_b.index >= start_date)
    n_is = int(is_mask.sum())
    n_names = int(mem_b.any(axis=0).sum())
    mean_Nb = float(mem_b.loc[is_mask].sum(axis=1).mean())
    print(f"[{block}] {n_names} codes ever, mean_N_b={mean_Nb:.1f}, "
          f"IS bars={n_is} (start={start_date}), q={q}, ε={EPSILON}, "
          f"cost={COST}")

    # ---------- nulls ----------
    null_rows = []
    for null_name, builder, sig_used in (
        ("eqw_null",    build_eqw_null,    sigma_b),
        ("invvol_null", build_invvol_null, sigma_b),
    ):
        Wn, Nn, Kn = builder(mem_b, sig_used)
        rn = E.run_book(Wn, fwd_b, cost_per_trade=COST, N_t=Nn, K_t=Kn)
        is_net = _is_slice(rn.net_ret, start_date=start_date)
        m = _window_metrics(is_net)
        m.update({"book": null_name,
                  "turnover": _turnover(Wn, start_date=start_date)})
        null_rows.append(m)
        rn.net_ret.to_frame("net_ret").to_csv(out_dir / f"{null_name}_net_ret.csv")
    nulls = pd.DataFrame(null_rows)
    nulls.to_csv(out_dir / "nulls.csv", index=False)

    eqw_sharpe    = float(nulls.loc[nulls["book"] == "eqw_null",    "sharpe"].iloc[0])
    invvol_sharpe = float(nulls.loc[nulls["book"] == "invvol_null", "sharpe"].iloc[0])
    eqw_cagr      = float(nulls.loc[nulls["book"] == "eqw_null",    "cagr"].iloc[0])
    invvol_cagr   = float(nulls.loc[nulls["book"] == "invvol_null", "cagr"].iloc[0])
    print(f"[{block}] eqw_null    Sharpe={eqw_sharpe:+.3f} CAGR={eqw_cagr*100:+.2f}%")
    print(f"[{block}] invvol_null Sharpe={invvol_sharpe:+.3f} CAGR={invvol_cagr*100:+.2f}%")

    hurdle_sharpe = max(eqw_sharpe, invvol_sharpe)

    # ---------- per-factor books ----------
    rebal = mem.index
    rows = []
    t0 = time.time()
    for i, r in kept.iterrows():
        f = r["factor"]; pol = r["polarity"]
        A = _weekly_alpha(data["caches"], f, rebal, codes)
        if A.shape[1] < 2:
            continue
        A = C.apply_membership(A, mem)
        A1 = C.expanding_z(A)
        A_score = _polarized_alpha(A1, pol)[block_codes]

        for sizing_name, sigma_used in (
            ("invvol", sigma_b),
            ("eqw",    sigma_eqw),
        ):
            W, N_t, K_t = H.build_hysteresis_weights(
                A_score, sigma_used, mem_b, q=q, mode="long",
                epsilon=EPSILON, rule=RULE,
            )
            res = E.run_book(W, fwd_b, cost_per_trade=COST,
                             N_t=N_t, K_t=K_t)
            is_net = _is_slice(res.net_ret, start_date=start_date)
            m = _window_metrics(is_net)
            turn = _turnover(W, start_date=start_date)
            passed = (
                np.isfinite(m["sharpe"])
                and m["sharpe"] > hurdle_sharpe
                and m["cagr"] >= eqw_cagr
            )
            rows.append({
                "factor":    f,
                "polarity":  pol,
                "sizing":    sizing_name,
                "zstat":     float(r["zstat"]),
                "sharpe":    m["sharpe"],
                "cagr":      m["cagr"],
                "max_dd":    m["max_dd"],
                "ann_vol":   m["ann_vol"],
                "turnover":  turn,
                "d_sharpe_vs_eqw":    m["sharpe"] - eqw_sharpe,
                "d_sharpe_vs_invvol": m["sharpe"] - invvol_sharpe,
                "d_cagr_vs_eqw":      m["cagr"]   - eqw_cagr,
                "pass":               bool(passed),
            })
            # Persist per-book net returns
            res.net_ret.to_frame("net_ret").to_csv(
                out_dir / f"{f}_{sizing_name}_net_ret.csv"
            )
        if (i + 1) % 5 == 0 or i == len(kept) - 1:
            dt = time.time() - t0
            print(f"  [{i + 1:>3d}/{len(kept)}] {f:<24s} "
                  f"elapsed={dt:5.1f}s")

    df = pd.DataFrame(rows).sort_values(
        ["sizing", "sharpe"], ascending=[True, False]
    ).reset_index(drop=True)
    df.to_csv(out_dir / "summary.csv", index=False)
    return {"block": block, "summary": df, "nulls": nulls,
            "hurdle_sharpe": hurdle_sharpe,
            "eqw_sharpe": eqw_sharpe, "eqw_cagr": eqw_cagr,
            "invvol_sharpe": invvol_sharpe, "invvol_cagr": invvol_cagr,
            "mean_Nb": mean_Nb}


# ---------------------------------------------------------------------- #
# Report
# ---------------------------------------------------------------------- #
def _fmt(x, digits=3):
    return f"{x:+.{digits}f}" if pd.notna(x) else "   —"


def _fmt_pct(x, digits=2):
    return f"{x*100:+.{digits}f}%" if pd.notna(x) else "     —"


def write_report(results: list[dict], q: float,
                 report_path: Path) -> None:
    lines: list[str] = []
    lines.append("# Phase 13.4 — within-block isolated book "
                 "(v6 pool, IS)\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    lines.append(
        f"Applied `BLOCK_MERGES = {{smallcap_cn → broad_cn}}` at load. "
        f"q = {q}, ε = {EPSILON} (replace rule), cost {COST*10000:.0f} bp/side. "
        f"IS bars ≤ {C.IN_SAMPLE_END.date()}. Two sizings per factor "
        "(1/σ, eqw). Two per-block nulls (eqw hold-all, 1/σ hold-all).\n\n"
        "**Pass rule** (user, 2026-07-22): IS Sharpe > max(eqw_null "
        "Sharpe, invvol_null Sharpe) AND IS CAGR ≥ eqw_null CAGR. "
        "Both nulls on the same block, same window, same cost. "
        "A pass means the factor is producing net-of-cost selection "
        "value beyond block β + sizing.\n\n"
    )

    # ---- §1 nulls per block ----
    lines.append("## 1. Per-block nulls\n")
    lines.append("| block | null | Sharpe | CAGR | max DD | ann vol | turnover |")
    lines.append("|:---|:---|---:|---:|---:|---:|---:|")
    for r in results:
        for _, row in r["nulls"].iterrows():
            lines.append(
                f"| {r['block']} | {row['book']} | "
                f"{_fmt(row['sharpe'])} | {_fmt_pct(row['cagr'])} | "
                f"{_fmt_pct(row['max_dd'])} | {_fmt_pct(row['ann_vol'])} | "
                f"{row['turnover']:.3f} |"
            )
    lines.append("")

    # ---- §2 pass counts ----
    lines.append("## 2. Pass counts per block × sizing\n")
    lines.append("| block | sizing | tested | passed | best-factor Sharpe |")
    lines.append("|:---|:---:|---:|---:|---:|")
    for r in results:
        for sizing in ("invvol", "eqw"):
            sub = r["summary"][r["summary"]["sizing"] == sizing]
            n = len(sub)
            p = int(sub["pass"].sum()) if n > 0 else 0
            best = float(sub["sharpe"].max()) if n > 0 else np.nan
            lines.append(f"| {r['block']} | {sizing} | {n} | {p} | "
                         f"{_fmt(best)} |")
    lines.append("")

    # ---- §3 per-block per-sizing tables ----
    for r in results:
        block = r["block"]
        for sizing in ("invvol", "eqw"):
            sub = r["summary"][r["summary"]["sizing"] == sizing].copy()
            if sub.empty:
                continue
            passed_only = sub[sub["pass"]]
            lines.append(f"## 3. `{block}` — sizing = **{sizing}** "
                         f"({len(passed_only)} pass / {len(sub)} total)\n")
            lines.append(
                f"Hurdle Sharpe = max(eqw={r['eqw_sharpe']:+.3f}, "
                f"invvol={r['invvol_sharpe']:+.3f}) = "
                f"{r['hurdle_sharpe']:+.3f}; "
                f"CAGR floor = eqw {_fmt_pct(r['eqw_cagr'])}.\n\n"
            )
            lines.append("| factor | pol | zstat | Sharpe | CAGR | max DD | "
                         "turnover | ΔSh vs eqw | ΔSh vs 1/σ | ΔCAGR vs eqw | pass |")
            lines.append("|:---|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|")
            for _, row in sub.iterrows():
                mark = "✓" if row["pass"] else ""
                lines.append(
                    f"| {row['factor']} | {row['polarity']} | "
                    f"{_fmt(row['zstat'], 2)} | "
                    f"{_fmt(row['sharpe'])} | {_fmt_pct(row['cagr'])} | "
                    f"{_fmt_pct(row['max_dd'])} | "
                    f"{row['turnover']:.3f} | "
                    f"{_fmt(row['d_sharpe_vs_eqw'])} | "
                    f"{_fmt(row['d_sharpe_vs_invvol'])} | "
                    f"{_fmt_pct(row['d_cagr_vs_eqw'])} | {mark} |"
                )
            lines.append("")

    # ---- §4 read ----
    lines.append("## 4. Read for next steps\n")
    for r in results:
        for sizing in ("invvol", "eqw"):
            sub = r["summary"][r["summary"]["sizing"] == sizing]
            if sub.empty:
                continue
            p = int(sub["pass"].sum())
            if p > 0:
                best = sub[sub["pass"]].sort_values("sharpe",
                                                    ascending=False).iloc[0]
                lines.append(
                    f"- **`{r['block']}` × {sizing}**: {p} pass. Top by "
                    f"Sharpe: `{best['factor']}` (pol={best['polarity']}, "
                    f"Sharpe {best['sharpe']:+.3f}, "
                    f"CAGR {_fmt_pct(best['cagr'])}, "
                    f"ΔSh vs eqw {best['d_sharpe_vs_eqw']:+.3f}). "
                    "Candidate for the per-block α layer under Phase 12.\n"
                )
            else:
                lines.append(
                    f"- **`{r['block']}` × {sizing}**: 0 pass. IC survived, "
                    "but net-of-cost selection value doesn't clear the "
                    "block-native null hurdle. Consider lower-turnover "
                    "variants (higher ε, wider q) before ruling out the "
                    "block × sizing combo.\n"
                )
    lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {report_path}")


# ---------------------------------------------------------------------- #
# CLI + main
# ---------------------------------------------------------------------- #
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--q", type=float, default=Q_DEFAULT,
                   help=f"top-q for basket selection (default {Q_DEFAULT})")
    p.add_argument("--blocks", type=str, default=None,
                   help="comma-separated blocks (default: broad_cn,sector_cn)")
    p.add_argument("--start-date", type=str, default=None,
                   help="IS start date (YYYY-MM-DD) — nulls + solo "
                        "books restrict to [start_date, IN_SAMPLE_END].")
    p.add_argument("--out-tag", type=str, default=None,
                   help="suffix for output paths so a partial-window / "
                        "restricted-block re-run doesn't overwrite the "
                        "canonical outputs.")
    p.add_argument("--dedup-tag", type=str, default=None,
                   help="tag suffix on within_block_dedup_v6 root when "
                        "loading kept.csv (matches --out-tag from the "
                        "corresponding dedup run).")
    return p.parse_args()


def _load_kept_tagged(block: str, dedup_tag: str | None) -> pd.DataFrame:
    root = (C.DATA_DIR /
            f"within_block_dedup_v6{('_' + dedup_tag) if dedup_tag else ''}")
    p = root / block / "kept.csv"
    if not p.exists():
        raise FileNotFoundError(
            f"missing 13.2b kept.csv at {p}; "
            "run within_block_dedup_v6.py first"
        )
    return pd.read_csv(p)


def main():
    args = _parse_args()

    tag = f"_{args.out_tag}" if args.out_tag else ""
    out_root = C.DATA_DIR / f"within_block_book_v6{tag}"
    report_p = C.REPORTS_DIR / f"within_block_book_v6{tag}_report.md"
    out_root.mkdir(parents=True, exist_ok=True)
    start_date = pd.Timestamp(args.start_date) if args.start_date else None

    blocks = tuple(x.strip() for x in args.blocks.split(",")) \
               if args.blocks else ("broad_cn", "sector_cn")

    data = _load_shared(C.DATA_DIR)
    print(f"shared: {len(data['codes'])} codes, "
          f"{len(data['fwd_1w'])} bars, "
          f"factor_cache={len(data['caches'])} codes")

    results = []
    for b in blocks:
        kept = _load_kept_tagged(b, args.dedup_tag)
        b_out = out_root / b
        b_out.mkdir(parents=True, exist_ok=True)
        r = run_block(b, kept, data, args.q, b_out, start_date=start_date)
        results.append(r)
        s = r["summary"]
        pass_iv = int(s[s["sizing"] == "invvol"]["pass"].sum())
        pass_eq = int(s[s["sizing"] == "eqw"]["pass"].sum())
        print(f"[{b}] pass counts: invvol={pass_iv}, eqw={pass_eq}")

    write_report(results, args.q, report_p)


if __name__ == "__main__":
    main()
