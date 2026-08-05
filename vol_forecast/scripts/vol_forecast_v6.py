"""
v6/scripts/vol_forecast_v6.py
=============================
Phase 10.2 — block-pooled HAR-RV forecast pipeline (build stage).

Chains the three modules of the vol-forecast branch:

    vol_targets_v6.py       (rv_panel.parquet, coverage flag)
    vol_har_block_v6.py     (Gaussian rank, WLS HAR, denormalize)
        ↓
    vol_forecast_v6.py      (this file — driver + block partition)

Steps
-----
1. Load ragged RV panel + coverage flag; keep codes with ≥ 52w RV.
2. Load block tags from `data/universe_v6/catalogue_tagged.csv`, then
   map into three coarse groups::

        equity : broad_cn + sector_cn + smallcap_cn +
                 cross_border_dm + cross_border_hk
        bond   : bond_rates + bond_credit
        alt    : metals + commodity_other

3. Gaussian-rank normalize each ETF (52w causal window). Ragged-safe:
   ETFs with < 52w defined RV never enter the panel.
4. For each block, build the HAR long-panel and walk-forward WLS-fit
   with `equal_etf_weights`. Refit every 4w, min_train = 52w,
   lags = (1, 4, 13)w.
5. Denormalize per-ETF, then concatenate the three blocks' σ̂ into a
   single T×N wide panel (blocks stay disjoint so no double-writes).
6. Also persist a random-walk baseline forecast (σ̂_{t+1} = σ_t) — same
   IS discipline as v5's build_forecast_v5 for diff-ability.

Outputs (data/vol_forecast_v6/)
--------------------------------
    g_panel.parquet                        — normalized log σ, per ETF
    forecasts_har_block_gaussian_rank.parquet
                                             — combined per-block σ̂
    forecasts_rw.parquet                   — RW baseline log σ̂_{t+1}
                                             = log σ_t (level: σ_t)
    coefs_har_block_equity.parquet         — per-refit β + FE (equity)
    coefs_har_block_bond.parquet           — same, bond
    coefs_har_block_alt.parquet            — same, alt
    block_membership.csv                   — code → block used for HAR

Model is *not* applied to the portfolio here. See
`vol_forecast_quality_v6.py` for the forecast-quality comparison.

Run
---
    python v6/scripts/vol_forecast_v6.py
"""
from __future__ import annotations

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
import vol_har_block_v6 as H


OUT_DIR = C.DATA_DIR / "vol_forecast_v6"

# Aggregation of Phase-3 block tags into the three HAR blocks.
BLOCK_GROUPS: dict[str, tuple[str, ...]] = {
    "equity": ("broad_cn", "sector_cn", "smallcap_cn",
               "cross_border_dm", "cross_border_hk"),
    "bond":   ("bond_rates", "bond_credit"),
    "alt":    ("metals", "commodity_other"),
}


# ---------------------------------------------------------------------- #
# Loaders
# ---------------------------------------------------------------------- #
def _load_rv(data_dir: Path) -> pd.DataFrame:
    return pd.read_parquet(data_dir / "vol_forecast_v6" / "rv_panel.parquet")


def _load_coverage(data_dir: Path) -> pd.DataFrame:
    return pd.read_csv(data_dir / "vol_forecast_v6" / "rv_coverage.csv")


def _load_block_tag(data_dir: Path) -> pd.Series:
    cat = pd.read_csv(data_dir / "universe_v6" / "catalogue_tagged.csv")
    return cat.set_index("code")["current_block"]


def _partition_codes(codes: list[str], block_tag: pd.Series) -> dict[str, list[str]]:
    """code list per HAR block. Codes without a recognized tag are
    dropped (with a warning printed to stdout)."""
    tag = block_tag.reindex(codes)
    reverse = {}
    for group, members in BLOCK_GROUPS.items():
        for m in members:
            reverse[m] = group
    grouped: dict[str, list[str]] = {g: [] for g in BLOCK_GROUPS}
    unclassified: list[str] = []
    for c in codes:
        t = tag.get(c)
        g = reverse.get(t) if isinstance(t, str) else None
        if g is None:
            unclassified.append(c)
        else:
            grouped[g].append(c)
    if unclassified:
        print(f"  [warn] {len(unclassified)} codes had no block tag — "
              f"dropped from HAR training: {unclassified[:5]}"
              + (" ..." if len(unclassified) > 5 else ""))
    return grouped


# ---------------------------------------------------------------------- #
# Per-block fit
# ---------------------------------------------------------------------- #
def _fit_block(g_panel: pd.DataFrame,
               rv: pd.DataFrame,
               codes: list[str],
               block: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, int]:
    """Fit one block's HAR. Returns (sigma_hat_wide, norm_hat_wide,
    coefs, n_refits). `norm_hat_wide` is the raw y_hat_norm on the
    target-date grid — needed for percentile-space recalibration."""
    g_block  = g_panel[codes]
    panel = H.build_panel(g_block)
    if panel.empty:
        print(f"    {block:>6s}: no training rows — skipped")
        empty = pd.DataFrame(index=rv.index, columns=codes, dtype=float)
        return empty, empty.copy(), pd.DataFrame(), 0

    result = H.walk_forward_pooled_wls(
        panel,
        etf_order=codes,
        min_train_steps=H.MIN_TRAIN,
        refit_every=H.REFIT_EVERY,
        sample_weight_fn=H.equal_etf_weights,
    )
    sigma_hat = H.denormalize(result.predictions,
                              rv[codes], window=H.WINDOW)
    norm_hat  = H.preds_to_wide_target_norm(result.predictions, rv[codes])
    print(f"    {block:>6s}: {len(codes):3d} ETFs, "
          f"{len(panel):6,d} panel rows, "
          f"{result.n_refits} refits, "
          f"{int(sigma_hat.notna().to_numpy().sum()):6,d} σ̂ cells")
    return sigma_hat, norm_hat, result.coefs, result.n_refits


# ---------------------------------------------------------------------- #
# RW baseline (level-space σ̂_{t+1} = σ_t)
# ---------------------------------------------------------------------- #
def random_walk_forecast(rv: pd.DataFrame) -> pd.DataFrame:
    """σ̂_{t+1} = σ_t, evaluated at target-date t+1. Ragged-safe:
    per-ETF shift(1) preserves NaN gaps rather than materializing them.
    """
    return rv.copy().shift(1)


# ---------------------------------------------------------------------- #
# Top-level
# ---------------------------------------------------------------------- #
def run(data_dir: Path | None = None) -> None:
    data_dir = Path(data_dir) if data_dir else C.DATA_DIR
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("v6 BLOCK-POOLED HAR — Gaussian rank, weekly")
    print("=" * 78)

    rv       = _load_rv(data_dir)
    coverage = _load_coverage(data_dir)
    block_tag = _load_block_tag(data_dir)

    elig_codes = coverage.loc[coverage["eligible"], "code"].tolist()
    print(f"  eligible codes (≥ {H.MIN_TRAIN}w RV): "
          f"{len(elig_codes)} / {len(coverage)}")

    grouped = _partition_codes(elig_codes, block_tag)
    for g, codes in grouped.items():
        print(f"    {g:>6s} block: {len(codes)} ETFs")

    modeled_codes = [c for codes in grouped.values() for c in codes]
    rv_m = rv[modeled_codes]

    # Leakage guard on the first block-eligible code (use log_rv).
    log_rv0 = np.log(rv_m.iloc[:, 0].dropna().clip(lower=H.CLIP_LOWER))
    if len(log_rv0) > H.WINDOW + 5:
        H.leakage_test(log_rv0, H.WINDOW)
        print(f"    leakage test OK on {rv_m.columns[0]}")

    # ── (1) Gaussian rank ────────────────────────────────────────────────
    print("\n[1] Gaussian-rank normalization (52w causal)...")
    g_panel = H.build_normalized_panel(rv_m, window=H.WINDOW)
    g_panel.to_parquet(OUT_DIR / "g_panel.parquet")
    print(f"    wrote g_panel.parquet  shape={g_panel.shape}  "
          f"non-null obs={int(g_panel.notna().to_numpy().sum()):,}")

    # ── (2) Per-block HAR ────────────────────────────────────────────────
    print(f"\n[2] Per-block HAR (min_train={H.MIN_TRAIN}w, "
          f"refit_every={H.REFIT_EVERY}w, WLS: equal ETF footing)...")
    sigma_hat = pd.DataFrame(index=rv.index, columns=modeled_codes, dtype=float)
    norm_hat  = pd.DataFrame(index=rv.index, columns=modeled_codes, dtype=float)
    for block, codes in grouped.items():
        if not codes:
            continue
        sh, nh, coefs, _ = _fit_block(g_panel, rv, codes, block)
        sigma_hat.loc[sh.index, sh.columns] = sh
        norm_hat.loc[nh.index,  nh.columns] = nh
        coefs.to_parquet(OUT_DIR / f"coefs_har_block_{block}.parquet")

    log_sigma_hat = np.log(sigma_hat.clip(lower=H.CLIP_LOWER))
    log_sigma_hat.to_parquet(OUT_DIR / "forecasts_har_block_gaussian_rank.parquet")
    norm_hat.to_parquet(OUT_DIR / "forecasts_har_norm.parquet")
    print(f"    wrote forecasts_har_block_gaussian_rank.parquet  "
          f"σ̂ cells={int(log_sigma_hat.notna().to_numpy().sum()):,}")
    print(f"    wrote forecasts_har_norm.parquet  "
          f"y_hat_norm cells={int(norm_hat.notna().to_numpy().sum()):,}")

    # ── (3) RW baseline ──────────────────────────────────────────────────
    print("\n[3] RW baseline (σ̂_{t+1} = σ_t)...")
    rw = random_walk_forecast(rv_m)
    log_rw = np.log(rw.clip(lower=H.CLIP_LOWER))
    log_rw.to_parquet(OUT_DIR / "forecasts_rw.parquet")
    print(f"    wrote forecasts_rw.parquet  "
          f"non-null={int(log_rw.notna().to_numpy().sum()):,}")

    # ── (4) block membership audit ───────────────────────────────────────
    block_of = pd.Series({c: b for b, cs in grouped.items() for c in cs},
                         name="block").rename_axis("code")
    block_of.reset_index().to_csv(OUT_DIR / "block_membership.csv", index=False)
    print(f"\n    wrote block_membership.csv  ({len(block_of)} codes)")


if __name__ == "__main__":
    run()
