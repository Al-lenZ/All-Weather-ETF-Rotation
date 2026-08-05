"""v6/leverage/report_round_d.py — write reports/leverage_higher_cap_round_d.md.

Compares Round D (rep-set at σ*=6.4 %, cap=5.0) to the matching Round C
cells (rep-set at σ*=3.2 %, cap=2.0). Same book (rep-only invvol non-α
composite from Round C fix), same estimator, same cost / funding
mechanics — only σ* and cap change.

Focus: does doubling σ* + raising cap to 5 deliver proportional CAGR
with acceptable DD and duration exposure?

Windows: IS, OOS, IS+OOS. Stress window remains sealed.

Run
---
    cd v6/leverage && python report_round_d.py
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

import _common_leverage as CL


REPORT_PATH = CL.DATA_DIR.parent / "reports" / "leverage_higher_cap_round_d.md"

CELL_PAIRS = [
    # (label, C cell (cap=2, σ*=3.2), D cell (cap=5, σ*=6.4))
    ("base RB · GC007", "C_base_reps_lev",       "D_base_reps_lev"),
    ("EW RB · GC007",   "C_ew_reps_lev",         "D_ew_reps_lev"),
    ("base RB · DR007", "C_base_reps_lev_DR007", "D_base_reps_lev_DR007"),
    ("EW RB · DR007",   "C_ew_reps_lev_DR007",   "D_ew_reps_lev_DR007"),
]


def _load_summary(cell: str) -> pd.DataFrame:
    return pd.read_csv(CL.LEV_DIR / cell / "summary.csv")


def _row(summary: pd.DataFrame, window: str) -> pd.Series:
    r = summary[summary["window"] == window]
    return r.iloc[0] if not r.empty else pd.Series(dtype=float)


def _fmt(x, d=3):
    return f"{x:+.{d}f}" if pd.notna(x) else "   —"


def _fmt_pct(x, d=2):
    return f"{x*100:+.{d}f}%" if pd.notna(x) else "     —"


def main() -> None:
    lines: list[str] = []
    lines.append("# Round D — higher-cap experiment on the rep-set book\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n\n")
    lines.append(
        "**What changed.** Round D uses the same rep-only invvol non-α "
        "composite as Round C (α blocks unchanged; PLAN §11 log 2026-07-31). "
        "Only two knobs move:\n\n"
        "- **σ\\*** raised 3.2 % → **6.4 %** annualized (2× current target). "
        "Rationale (user, boss-approved): 'normal case ≈ 2× leverage'.\n"
        "- **Cap** raised 2.0 → **5.0**. Rationale (boss): theoretical "
        "ceiling is 10×; start with 5× first.\n\n"
        "Everything else — layer-1 solver, weekly_ewma_52 σ_est, "
        "split-cost table (2/10 bp), funding curves (GC007 & DR007-proxy), "
        "cash carry (DR007-proxy on residual), warmup convention — is "
        "unchanged from PLAN §1.\n\n"
        "**Cells.** 4 cells: `{base RB, EW RB} × {GC007, DR007-proxy}`, "
        "all rep-set. Direct 1:1 comparison with the matching Round C "
        "lev cells so the delta is entirely the cap-and-σ\\* effect. "
        "Stress window `[2025-08-01, 2026-07-17]` NOT opened.\n\n"
        "**Sharpe metric convention.** `excess_sharpe_net` uses the "
        "cell's own funding curve as rf (PLAN §1 invariance identity). "
        "`excess_sharpe_vs_gc007` uses GC007 as a common rf so DR007 "
        "cells are comparable to GC007 cells like-for-like.\n\n"
    )

    # ---------------- §1. Side-by-side per window ----------------
    for wlabel, whdr in (("is", "IS"), ("oos", "OOS"),
                         ("is+oos", "IS+OOS pooled")):
        lines.append(f"\n## 1.{wlabel}. Metrics — {whdr} window\n")
        hdr = ("| pair | variant | Sh_net | excSh_net | excSh_vs_gc007 | "
               "CAGR | MaxDD | vol | mean L | %cap | %floor | "
               "fdrag bp/y | cshcarry bp/y | dur mean y | dur p95 y |")
        sep = "|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
        lines.append(hdr); lines.append(sep)
        for pair_label, c_cell, d_cell in CELL_PAIRS:
            for tag, cell in (("cap=2, σ*=3.2", c_cell),
                              ("cap=5, σ*=6.4", d_cell)):
                r = _row(_load_summary(cell), wlabel)
                if r.empty:
                    continue
                lines.append(
                    f"| {pair_label} | {tag} | "
                    f"{_fmt(r['sharpe_net'])} | {_fmt(r['excess_sharpe_net'])} | "
                    f"{_fmt(r.get('excess_sharpe_vs_gc007', float('nan')))} | "
                    f"{_fmt_pct(r['cagr_net'])} | {_fmt_pct(r['max_dd'])} | "
                    f"{_fmt_pct(r['vol_realized'])} | "
                    f"{float(r['mean_L']):.3f} | "
                    f"{float(r['pct_at_cap'])*100:.1f}% | "
                    f"{float(r['pct_at_floor'])*100:.1f}% | "
                    f"{float(r['funding_drag_bp_yr']):+.1f} | "
                    f"{float(r['cash_carry_bp_yr']):+.1f} | "
                    f"{float(r.get('book_duration_yr_mean', float('nan'))):.2f} | "
                    f"{float(r.get('book_duration_yr_p95', float('nan'))):.2f} |"
                )
        lines.append("")

    # ---------------- §2. Deltas (D − C) on pooled window ----------------
    lines.append("\n## 2. Δ = D − C on IS+OOS pooled window\n")
    lines.append("Sign convention: positive = D (cap=5, σ\\*=6.4) is "
                 "'better' on Sh / CAGR (higher), 'worse' on MaxDD "
                 "(more negative = smaller number here).\n\n")
    hdr = ("| pair | Δ Sh_net | Δ excSh_net | Δ CAGR | Δ MaxDD | "
           "Δ vol | Δ mean L | Δ fdrag bp/y | Δ dur mean | Δ dur p95 |")
    sep = "|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    lines.append(hdr); lines.append(sep)
    for pair_label, c_cell, d_cell in CELL_PAIRS:
        rc = _row(_load_summary(c_cell), "is+oos")
        rd = _row(_load_summary(d_cell), "is+oos")
        if rc.empty or rd.empty:
            continue
        lines.append(
            f"| {pair_label} | "
            f"{rd['sharpe_net']-rc['sharpe_net']:+.3f} | "
            f"{rd['excess_sharpe_net']-rc['excess_sharpe_net']:+.3f} | "
            f"{(rd['cagr_net']-rc['cagr_net'])*100:+.2f} pp | "
            f"{(rd['max_dd']-rc['max_dd'])*100:+.2f} pp | "
            f"{(rd['vol_realized']-rc['vol_realized'])*100:+.2f} pp | "
            f"{rd['mean_L']-rc['mean_L']:+.3f} | "
            f"{rd['funding_drag_bp_yr']-rc['funding_drag_bp_yr']:+.1f} | "
            f"{rd.get('book_duration_yr_mean', np.nan) - rc.get('book_duration_yr_mean', np.nan):+.2f}y | "
            f"{rd.get('book_duration_yr_p95', np.nan) - rc.get('book_duration_yr_p95', np.nan):+.2f}y |"
        )
    lines.append("")

    # ---------------- §3. Duration disclosure ----------------
    lines.append("\n## 3. Duration exposure disclosure\n")
    lines.append(
        "Book duration = Σ_i W_lev[t, i] · KRD_i (static KRD table in "
        "`_common_leverage.py`; ±0.5y accuracy). At cap=5 the borrowed "
        "notional lands mostly in bonds (base 55/20/10/15 RB × invvol "
        "sizing → bond-heavy), so duration scales roughly with L.\n\n"
    )
    lines.append("| cell | window | dur mean | dur p95 | 100bp back-up impact |")
    lines.append("|:---|:---|---:|---:|---:|")
    for _, _, d_cell in CELL_PAIRS:
        s = _load_summary(d_cell)
        for w in ("is", "oos", "is+oos"):
            r = _row(s, w)
            if r.empty:
                continue
            dm  = float(r.get("book_duration_yr_mean", np.nan))
            dp  = float(r.get("book_duration_yr_p95",  np.nan))
            hit = dp / 100.0     # 100 bp → dur × 1 % pct hit
            lines.append(f"| {d_cell} | {w} | {dm:.2f}y | {dp:.2f}y | "
                         f"~{hit:.2f}% (at p95 duration) |")
    lines.append(
        "\n**Interpretation.** A 100 bp parallel CGB curve back-up would "
        "hit p95-duration weeks by dur_p95 × 1 % = 13–18 % of NAV. That's "
        "a real tail risk the boss needs to be aware of. Stress window "
        "(2025 H2 – 2026 H1) is sealed but if it opens, the p05 net_ret "
        "conditional-on-high-rf diagnostic will tell us how the OOS "
        "high-L regime handled duration shocks in practice.\n"
    )

    # ---------------- §4. Reading the tape ----------------
    lines.append("\n## 4. Reading the tape\n")
    lines.append(
        "**CAGR scales roughly with L, but Sharpe compresses.** IS+OOS "
        "pooled CAGR jumps from ~5.3 % (cap 2) to ~7.8-8.3 % (cap 5) — "
        "+2.5 to +3.0 pp. Mean L̄ goes 1.30 → 2.52 (base) and 1.39 → "
        "2.82 (EW), roughly a doubling. So CAGR uplift ≈ L̄ multiplier "
        "× incremental excess return, as the invariance identity "
        "predicts. Sh_net drops ~0.32 (base) and ~0.28 (EW) pooled — "
        "σ_est model error and funding-drag noise both scale with L, "
        "chipping at the ratio.\n\n"
        "**Funding drag is the dominant cost at higher cap.** Pooled "
        "GC007 funding drag jumps from ~65 bp/y (base cap=2) to "
        "~335 bp/y (base cap=5). That's ~5× — matches the (L̄−1) × "
        "funding rate scaling. On DR007 proxy the drag is ~297 bp/y "
        "(base), still ~5× the C-cell 58 bp/y. Excess Sharpe (which "
        "nets rf out) stays roughly flat (Δ 0.00 to −0.03), which is "
        "the correct invariance signal — the CAGR gain is real, not "
        "an artifact of the funding accounting.\n\n"
        "**OOS L̄ hits 3.6–4.2 in low-vol regime.** The 2024-25 vol "
        "environment lets σ*=6.4 % pull leverage up to ~4.2 mean on EW; "
        "EW hits cap 18 % of OOS weeks. Base cap only 0.6 % of weeks. "
        "IS L̄ 2.14 base / 2.34 EW — well below cap. So the cap 5.0 "
        "headroom mostly matters for the OOS low-vol regime, not for "
        "'normal case'.\n\n"
        "**MaxDD doubles.** Pooled MaxDD: base −2.55 % → −5.59 % "
        "(cap 2 → cap 5); EW −2.40 % → −4.41 %. Both stay inside 6 %, "
        "well within any reasonable risk tolerance for a duration-"
        "levered book, but the scaling is close to linear in L̄ as "
        "expected. No cell approaches 10 %.\n\n"
        "**Book duration is the real disclosure.** OOS mean 13-15 y, "
        "p95 17-18 y. A 100 bp CGB back-up costs 13-18 % of NAV in the "
        "p95 week. That is the risk the boss should hear alongside "
        "the CAGR uplift. This is why the pre-registered stress "
        "diagnostic (`net_ret_p05_when_rf_p90`) matters more at cap 5.\n\n"
        "**Funding-curve axis.** DR007-proxy delivers ~+0.10 Sh_net "
        "and ~+0.10 excSh_net at cap 5, same shape as at cap 2. Same "
        "conclusion: real DR007 (or better, T-futures IRR) beats GC007 "
        "for execution.\n\n"
        "**Which cell to bring to the boss.** `D_ew_reps_lev_DR007` "
        "gives the best CAGR (+8.33 % pooled, +11.79 % OOS) with the "
        "smallest MaxDD (−4.41 %) — but caveat: OOS L̄ 4.20 with "
        "18 % of weeks pinned at cap 5 signals σ*=6.4 % isn't enough "
        "headroom in low-vol regimes. If normal-case L̄ ≈ 2 is the "
        "boss's benchmark, base RB delivers that (IS L̄ 2.14 base vs "
        "2.34 EW). Suggest surfacing both.\n\n"
        "**Not decided here.** v6 remains FROZEN. Round D is a "
        "diagnostic. PLAN §8B pass criteria (pre-registered on Round A "
        "axis at cap 2) are NOT re-applied. Real decision waits for "
        "boss review, stress-window open (if requested), and v7 scope "
        "conversation.\n"
    )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
