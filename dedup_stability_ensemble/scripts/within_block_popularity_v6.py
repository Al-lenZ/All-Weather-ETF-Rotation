"""
v6/scripts/within_block_popularity_v6.py
========================================
Phase 13.3 — within-block holdings popularity for the 13.2b kept
factor set.

Question the report answers, per (factor, block): if you built a top-q
book on just this block using this factor, does the top-q rotate
across members, or does it collapse to a fixed 3-4 name portfolio?
Rationale (user 2026-07-22): the risk-adjusted label rewards low-σ
names in the tails, so downside-risk factors (var5_60, cvar5_60,
kurt-family) can pass 13.2 by simply overweighting a bank / utility
ETF core every week. The popularity check separates "the factor
picks a moving set" from "the factor is an inv-vol dressing."

Method (per (factor, block)):
  1. Membership + block filter, applying BLOCK_MERGES = {smallcap_cn:
     broad_cn} at load — smallcap ETFs get evaluated inside broad_cn.
  2. Build stage-1 expanding-z of the factor, membership-mask, restrict
     to block members. Apply polarity from 13.2b's kept.csv so ranking
     is always ascending in "expected return."
  3. At each IS bar t, pick top-K_t = ⌈q · N_b(t)⌉, q = 0.20 (matches
     production long_q20 finalist).
  4. Also build the 1/σ null selection: same K_t, but pick by lowest
     σ_causal_26w (no factor input). This is what "own the low-vol
     names in this block" looks like — the sector_cn analog of
     `T2_bond_invvol` at the block level.
  5. Metrics per (factor, block):
       - **presence share** per name = fraction of eligible bars picked.
       - **effective N** = 1 / Σ p_i² across the block's eligible names.
         Lower ⇒ book collapses to a small core.
       - **Jaccard vs 1/σ null** per bar (|picked ∩ σ_pick| / |picked ∪
         σ_pick|), then averaged. > 0.7 = the factor's top-K is
         essentially the 1/σ null; < 0.5 = genuine rotation.
       - **turnover** = mean_t 0.5 · Σ_i |1_picked_t XOR 1_picked_{t-1}|
                            / K_t.
  6. Verdict:
       - `INV_VOL_LIKE`   — Jaccard_null > 0.7 AND eff_N within 20 %
         of the 1/σ null. Not adding rotation on top of σ.
       - `ROTATIONAL`     — Jaccard_null < 0.5 AND turnover ≥ 0.15.
       - `MIXED`          — everything in between.

IS-only. No cost, no book — pure selection diagnostic.

Outputs
-------
    data/within_block_popularity_v6/{block}/summary.csv
    data/within_block_popularity_v6/{block}/{factor}.csv    (per-name detail)
    data/within_block_popularity_v6/{block}/inv_vol_null_names.csv
    reports/within_block_popularity_v6_report.md

Run
---
    python v6/scripts/within_block_popularity_v6.py
    python v6/scripts/within_block_popularity_v6.py --q 0.30
    python v6/scripts/within_block_popularity_v6.py --blocks sector_cn
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
from within_block_ic_v6 import _weekly_alpha


# ---------------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------------- #
BLOCK_MERGES = {"smallcap_cn": "broad_cn"}   # per user 2026-07-22
Q_DEFAULT    = 0.20                          # matches production long_q20
INVVOL_JACC_HIGH = 0.70
INVVOL_JACC_LOW  = 0.50
INVVOL_EFFN_TOL  = 0.20                      # within ±20 % of 1/σ eff_N
ROTATION_TURN    = 0.15
OUT_DIR       = C.DATA_DIR / "within_block_popularity_v6"
DEDUP_ROOT    = C.DATA_DIR / "within_block_dedup_v6"
TOP_N_REPORT  = 10


# ---------------------------------------------------------------------- #
# Inputs
# ---------------------------------------------------------------------- #
def _load_inputs(data_dir: Path) -> dict:
    mem = pd.read_parquet(data_dir / "universe_v6" / "membership.parquet")
    codes = list(mem.columns[mem.any(axis=0)])
    mem = mem[codes].astype(bool)

    cat = pd.read_csv(data_dir / "universe_v6" / "catalogue_tagged.csv")
    block_tag = cat.set_index("code")["current_block"].reindex(codes) \
                   .fillna("UNTAGGED").replace(BLOCK_MERGES)
    name_en = cat.set_index("code").get("name_en")
    if name_en is not None:
        name_en = name_en.reindex(codes)

    sigma = pd.read_parquet(
        data_dir / "panels_v6" / "sigma_causal_26w.parquet"
    )[codes]

    caches = C.load_caches_v6("1d", codes)

    return {"membership": mem, "codes": codes, "block_tag": block_tag,
            "name_en": name_en, "sigma": sigma, "caches": caches}


def _load_kept(block: str) -> pd.DataFrame:
    p = DEDUP_ROOT / block / "kept.csv"
    if not p.exists():
        raise FileNotFoundError(
            f"missing 13.2b kept.csv at {p}; "
            "run within_block_dedup_v6.py first"
        )
    return pd.read_csv(p)


# ---------------------------------------------------------------------- #
# Selection engine
# ---------------------------------------------------------------------- #
def _top_k_per_bar(score: pd.DataFrame, N_b: pd.Series,
                   q: float, ascending: bool = False) -> pd.DataFrame:
    """Row-wise top-⌈q·N_b(t)⌉ by score (higher = better if
    ascending=False). Returns bool DataFrame of same shape."""
    K_t = np.ceil(q * N_b.astype(float)).astype("Int64")
    K_t = K_t.where(K_t.notna(), 0).astype(int)
    K_t = K_t.clip(lower=0)

    picked = pd.DataFrame(False, index=score.index, columns=score.columns)
    S = score.to_numpy(dtype=float)
    for i in range(S.shape[0]):
        k = int(K_t.iloc[i])
        row = S[i]
        m = np.isfinite(row)
        n_valid = int(m.sum())
        if k == 0 or n_valid == 0:
            continue
        k = min(k, n_valid)
        if ascending:
            # lowest k
            idx = np.argpartition(np.where(m, row, np.inf), k - 1)[:k]
        else:
            # highest k
            idx = np.argpartition(np.where(m, -row, np.inf), k - 1)[:k]
        picked.iloc[i, idx] = True
    return picked


def _selection_metrics(picked: pd.DataFrame,
                       block_eligible: pd.DataFrame,
                       K_t: pd.Series) -> dict:
    """Given a bool selection panel restricted to a block, compute the
    popularity metrics. ``block_eligible`` is bool: name is in the
    block AND admitted at bar t (used to divide presence share).
    ``K_t`` is the per-bar target basket size.
    """
    bars = picked.index
    codes = picked.columns

    # presence share per name (fraction of eligible bars picked)
    pk = picked.astype(int).sum(axis=0)
    el = block_eligible.astype(int).sum(axis=0)
    presence = (pk / el.replace(0, np.nan)).fillna(0.0)

    # Effective N based on presence share (normalized to sum to 1
    # across names to give a proper HHI reading)
    p = presence.astype(float)
    if p.sum() > 0:
        pn = p / p.sum()
        eff_N = 1.0 / float((pn ** 2).sum()) if (pn ** 2).sum() > 0 else np.nan
    else:
        eff_N = np.nan

    # turnover: per-bar |ΔW|/2 where W is 0/1 divided by K_t
    diff = picked.astype(int).diff().abs()
    diff.iloc[0] = 0
    turnover_per_bar = diff.sum(axis=1) / (2.0 * K_t.astype(float))
    turnover_per_bar = turnover_per_bar.replace([np.inf, -np.inf], np.nan)
    mean_turn = float(turnover_per_bar.dropna().mean())

    # mean per-bar K actually held
    mean_K = float(picked.astype(int).sum(axis=1).mean())

    return {
        "presence":  presence,
        "eff_N":     eff_N,
        "turnover":  mean_turn,
        "mean_K":    mean_K,
    }


def _jaccard_series(a: pd.DataFrame, b: pd.DataFrame) -> pd.Series:
    """Per-bar Jaccard between two bool selection panels."""
    A = a.astype(int); B = b.astype(int)
    inter = (A * B).sum(axis=1)
    union = ((A + B) > 0).astype(int).sum(axis=1)
    out = inter.astype(float) / union.replace(0, np.nan).astype(float)
    return out


# ---------------------------------------------------------------------- #
# Per-block runner
# ---------------------------------------------------------------------- #
def _polarity_score(A1: pd.DataFrame, polarity: str) -> pd.DataFrame:
    """Return the score to pick top-K on. Higher = better after
    polarity is applied, so we always take highest."""
    return A1 if polarity == "raw" else -A1


def _restrict_to_block(panel: pd.DataFrame,
                       mem: pd.DataFrame,
                       block_codes: pd.Index) -> tuple[pd.DataFrame,
                                                       pd.DataFrame]:
    cols = [c for c in block_codes if c in panel.columns]
    P = panel.loc[:, cols]
    M = mem.loc[:, cols]
    P = P.where(M)
    return P, M


def run_block(block: str,
              kept: pd.DataFrame,
              data: dict,
              q: float,
              out_dir: Path) -> pd.DataFrame:
    mem       = data["membership"]
    sigma     = data["sigma"]
    tag       = data["block_tag"]
    codes     = data["codes"]
    name_en   = data["name_en"]

    rebal  = mem.index
    is_idx = rebal[rebal <= C.IN_SAMPLE_END]

    # Block-tagged codes (post-BLOCK_MERGES)
    block_codes = pd.Index([c for c in codes if tag.get(c) == block])
    if len(block_codes) == 0:
        print(f"[{block}] no codes tagged — skipping")
        return pd.DataFrame()

    # Per-bar eligibility and N_b(t)
    mem_is = mem.loc[is_idx, block_codes]
    N_b = mem_is.sum(axis=1).astype(int)
    K_t = np.ceil(q * N_b.astype(float)).astype(int)

    # ---- 1/σ null selection ----
    print(f"[{block}] {len(block_codes)} block codes  "
          f"mean_N_b={float(N_b.mean()):.1f}  bars={len(is_idx)}  "
          f"q={q}  mean_K_t={float(K_t.mean()):.2f}")
    sigma_b, mem_b = _restrict_to_block(sigma.loc[is_idx], mem_is,
                                        block_codes)
    # Score for 1/σ null is -σ (highest score = lowest σ = smallest risk),
    # equivalent to picking ascending by σ.
    null_score = -sigma_b
    null_pick = _top_k_per_bar(null_score, N_b, q, ascending=False)
    null_pick = null_pick & mem_b  # respect membership
    null_metrics = _selection_metrics(null_pick, mem_b, K_t.reindex(is_idx))
    # Save null names
    null_names_df = pd.DataFrame({
        "code": null_metrics["presence"].index,
        "block": block,
        "name_en": (name_en.reindex(null_metrics["presence"].index).values
                    if name_en is not None else None),
        "presence_share": null_metrics["presence"].values,
    }).sort_values("presence_share", ascending=False)
    null_names_df.to_csv(out_dir / "inv_vol_null_names.csv", index=False)

    # ---- per-factor loop ----
    summary_rows = []
    t0 = time.time()
    for i, r in kept.iterrows():
        f = r["factor"]; pol = r["polarity"]
        A = _weekly_alpha(data["caches"], f, rebal, codes)
        if A.shape[1] < 2:
            continue
        A = C.apply_membership(A, mem)
        A1 = C.expanding_z(A)
        score = _polarity_score(A1, pol)
        score_b, _mem_b = _restrict_to_block(score.loc[is_idx], mem_is,
                                             block_codes)

        pick = _top_k_per_bar(score_b, N_b, q, ascending=False)
        pick = pick & mem_b
        m = _selection_metrics(pick, mem_b, K_t.reindex(is_idx))

        jacc = _jaccard_series(pick, null_pick).dropna()
        mean_jacc = float(jacc.mean()) if len(jacc) > 0 else np.nan

        # Verdict
        eff_ok = np.isfinite(m["eff_N"]) and np.isfinite(null_metrics["eff_N"])
        eff_near = (eff_ok and
                    abs(m["eff_N"] - null_metrics["eff_N"]) /
                        max(null_metrics["eff_N"], 1e-9) <= INVVOL_EFFN_TOL)
        if (mean_jacc >= INVVOL_JACC_HIGH) and eff_near:
            verdict = "INV_VOL_LIKE"
        elif (mean_jacc <= INVVOL_JACC_LOW) and (m["turnover"] >= ROTATION_TURN):
            verdict = "ROTATIONAL"
        else:
            verdict = "MIXED"

        # Top-N most popular names for this factor
        top = m["presence"].sort_values(ascending=False).head(TOP_N_REPORT)
        top_names = "; ".join(
            f"{c}({m['presence'][c]*100:.0f}%)"
            for c in top.index if m["presence"][c] > 0.0
        )

        row = {
            "factor":       f,
            "polarity":     pol,
            "zstat":        float(r["zstat"]),
            "mean_K":       m["mean_K"],
            "eff_N":        m["eff_N"],
            "eff_N_null":   null_metrics["eff_N"],
            "eff_N_ratio":  (m["eff_N"] / null_metrics["eff_N"]
                             if np.isfinite(m["eff_N"]) and
                                np.isfinite(null_metrics["eff_N"])
                                and null_metrics["eff_N"] > 0 else np.nan),
            "jaccard_null": mean_jacc,
            "turnover":     m["turnover"],
            "verdict":      verdict,
            "top_names":    top_names,
        }
        summary_rows.append(row)

        # Per-factor detail CSV
        detail = pd.DataFrame({
            "code": m["presence"].index,
            "block": block,
            "name_en": (name_en.reindex(m["presence"].index).values
                        if name_en is not None else None),
            "presence_share": m["presence"].values,
        }).sort_values("presence_share", ascending=False)
        detail.to_csv(out_dir / f"{f}.csv", index=False)

        if (i + 1) % 5 == 0 or i == len(kept) - 1:
            print(f"  [{i + 1:>3d}/{len(kept)}]  {f:<24s} "
                  f"eff_N={m['eff_N']:5.2f}  jacc={mean_jacc:.2f}  "
                  f"turn={m['turnover']:.2f}  → {verdict}")

    df = pd.DataFrame(summary_rows)
    df = df.sort_values("zstat", key=lambda s: s.abs(), ascending=False) \
           .reset_index(drop=True)
    df.to_csv(out_dir / "summary.csv", index=False)
    print(f"[{block}] wrote {out_dir / 'summary.csv'}  "
          f"({len(df)} factors, elapsed {time.time() - t0:.1f}s)")
    return df


# ---------------------------------------------------------------------- #
# Report
# ---------------------------------------------------------------------- #
def _fmt(x, digits=2):
    return f"{x:.{digits}f}" if pd.notna(x) else "—"


def write_report(results: dict[str, pd.DataFrame],
                 null_summaries: dict[str, dict],
                 report_path: Path, q: float) -> None:
    lines: list[str] = []
    lines.append("# Phase 13.3 — within-block holdings popularity (v6 pool, IS)\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    lines.append(
        "Applied `BLOCK_MERGES = {smallcap_cn → broad_cn}` at load. "
        f"Top-⌈q·N_b(t)⌉ selection with q = {q} (matches production "
        "long_q20 finalist). IS-only; no cost, no PnL — pure selection "
        "diagnostic.\n\n"
        "**Verdict thresholds.**\n"
        f"- `INV_VOL_LIKE`: mean Jaccard vs 1/σ null ≥ {INVVOL_JACC_HIGH} "
        f"AND effective N within ±{INVVOL_EFFN_TOL*100:.0f}% of the "
        "1/σ null's eff_N. Reading: the factor's top-K is essentially "
        "the low-σ core; it's an inv-vol dressing.\n"
        f"- `ROTATIONAL`:   mean Jaccard vs 1/σ null ≤ {INVVOL_JACC_LOW} "
        f"AND per-bar turnover ≥ {ROTATION_TURN}. Reading: the top-K "
        "meaningfully rotates across the block; the factor is doing "
        "actual selection.\n"
        "- `MIXED`:        everything in between.\n\n"
        "**Read.** Sector_cn's 13.2 top rows (var5_60, cvar5_60, kurt-family) "
        "are downside-risk factors; if the ranked risk-adjusted label "
        "rewards low-σ names in the tails, we should expect them to "
        "collapse to a bank / utility core (`INV_VOL_LIKE`). If most "
        "sector_cn 13.2b survivors carry that verdict, 13.2c "
        "(raw-label re-screen using block-internal rank(fwd)) opens.\n\n"
    )

    # ---- §1 verdict counts ----
    lines.append("## 1. Verdict counts per block\n")
    lines.append("| block | ROTATIONAL | MIXED | INV_VOL_LIKE | total |")
    lines.append("|:---|---:|---:|---:|---:|")
    for b, df in results.items():
        if df.empty:
            lines.append(f"| {b} | 0 | 0 | 0 | 0 |")
            continue
        vc = df["verdict"].value_counts()
        lines.append(
            f"| {b} | {int(vc.get('ROTATIONAL', 0))} | "
            f"{int(vc.get('MIXED', 0))} | "
            f"{int(vc.get('INV_VOL_LIKE', 0))} | {len(df)} |"
        )
    lines.append("")

    # ---- §2 per-block factor tables ----
    for b, df in results.items():
        null_eff = null_summaries[b]["eff_N"]
        null_names = null_summaries[b]["top_names"]
        lines.append(f"## 2. `{b}` — factor popularity summary\n")
        lines.append(
            f"1/σ null on this block: **eff_N = {_fmt(null_eff, 2)}**, "
            f"top-{TOP_N_REPORT} names → {null_names}\n\n"
        )
        if df.empty:
            lines.append("*No survivor factors.*\n")
            continue
        lines.append("| factor | pol | zstat | mean_K | eff_N | "
                     "eff_N/null | jaccard_null | turnover | verdict |")
        lines.append("|:---|:---:|---:|---:|---:|---:|---:|---:|:---|")
        for _, r in df.iterrows():
            lines.append(
                f"| {r['factor']} | {r['polarity']} | "
                f"{_fmt(r['zstat'], 2)} | "
                f"{_fmt(r['mean_K'], 1)} | "
                f"{_fmt(r['eff_N'], 2)} | "
                f"{_fmt(r['eff_N_ratio'], 2)} | "
                f"{_fmt(r['jaccard_null'], 3)} | "
                f"{_fmt(r['turnover'], 3)} | "
                f"`{r['verdict']}` |"
            )
        lines.append("")

        # top names sample for the 5 most-rotational and 5 most-inv-vol
        rot = df[df["verdict"] == "ROTATIONAL"].head(5)
        inv = df[df["verdict"] == "INV_VOL_LIKE"].head(5)
        if not rot.empty:
            lines.append(f"### `{b}` — top ROTATIONAL factors: which names get "
                         "picked most?\n")
            for _, r in rot.iterrows():
                lines.append(f"- **{r['factor']}** ({r['polarity']}, "
                             f"jacc={r['jaccard_null']:.2f}, "
                             f"turn={r['turnover']:.2f}): {r['top_names']}")
            lines.append("")
        if not inv.empty:
            lines.append(f"### `{b}` — top INV_VOL_LIKE factors: which names get "
                         "picked most?\n")
            for _, r in inv.iterrows():
                lines.append(f"- **{r['factor']}** ({r['polarity']}, "
                             f"jacc={r['jaccard_null']:.2f}, "
                             f"turn={r['turnover']:.2f}): {r['top_names']}")
            lines.append("")

    # ---- §3 read for 13.2c / 13.4 ----
    lines.append("## 3. Read for 13.2c / 13.4\n")
    for b, df in results.items():
        if df.empty:
            continue
        vc = df["verdict"].value_counts()
        rot_n = int(vc.get("ROTATIONAL", 0))
        inv_n = int(vc.get("INV_VOL_LIKE", 0))
        mix_n = int(vc.get("MIXED", 0))
        share_inv = inv_n / max(len(df), 1)
        share_rot = rot_n / max(len(df), 1)
        lines.append(
            f"- **`{b}`**: ROTATIONAL {rot_n} ({share_rot*100:.0f}%), "
            f"MIXED {mix_n}, INV_VOL_LIKE {inv_n} ({share_inv*100:.0f}%). "
            + (
                "Majority-inv-vol — recommend opening 13.2c raw-label "
                "re-screen; the current 13.2 rankings may be selecting σ, "
                "not signal.\n"
                if share_inv >= 0.5
                else
                "Enough ROTATIONAL factors to advance to 13.4 book "
                "construction against the block-eqw null.\n"
            )
        )

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
    return p.parse_args()


def main():
    args = _parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    blocks = tuple(x.strip() for x in args.blocks.split(",")) \
               if args.blocks else ("broad_cn", "sector_cn")
    print(f"blocks: {list(blocks)}   q={args.q}")

    data = _load_inputs(C.DATA_DIR)

    results: dict[str, pd.DataFrame] = {}
    null_summaries: dict[str, dict] = {}
    for b in blocks:
        kept = _load_kept(b)
        b_out = OUT_DIR / b
        b_out.mkdir(parents=True, exist_ok=True)
        df = run_block(b, kept, data, args.q, b_out)
        results[b] = df

        # Load null names to include in report
        null_df = pd.read_csv(b_out / "inv_vol_null_names.csv")
        # Use eff_N from a fresh recompute of the same null (already
        # computed in run_block; re-derive here for the report)
        p = null_df["presence_share"].astype(float)
        if p.sum() > 0:
            pn = p / p.sum()
            eff = 1.0 / float((pn ** 2).sum())
        else:
            eff = np.nan
        top = null_df.head(TOP_N_REPORT)
        top_names = "; ".join(
            f"{r['code']}({r['presence_share']*100:.0f}%)"
            for _, r in top.iterrows() if r["presence_share"] > 0
        )
        null_summaries[b] = {"eff_N": eff, "top_names": top_names}

    write_report(results, null_summaries,
                 C.REPORTS_DIR / "within_block_popularity_v6_report.md",
                 args.q)


if __name__ == "__main__":
    main()
