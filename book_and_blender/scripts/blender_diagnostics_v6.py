"""
v6/scripts/blender_diagnostics_v6.py
====================================
Phase 11.2 diagnostics — is the aggressive-book Sharpe advantage in the
high-vol tail (that motivated the inverted schedule) real, or is it
just capturing 2020/2022 crisis-recovery periods?

Method
------
Uses the artifacts already written by ``oracle_blender_v6.py``:

    data/v6_static/oracle_blender/bar_solo_defensive.csv
    data/v6_static/oracle_blender/bar_solo_aggressive.csv
    data/v6_static/oracle_blender/lambdas.csv

Computes at each IS bar:

    spread_t = net_ret_agg[t] − net_ret_def[t]

then buckets it against three signals in parallel:

- **regime by causal σ pct** (matches the ``blend_causal`` gate)
- **regime by fwd_1w_rv pct** (matches ``blend_fwd_1w_rv`` — proper
  1-week RV oracle)
- **regime by fwd_4w_rv pct** (matches ``blend_fwd_4w_rv``)
- **future defensive-book return sign** at each bar (proxy for "market
  went up / went down next week")

Crisis strip
------------
Pre-registered crisis windows (before running the strip):

    covid    : 2020-02-01 → 2020-04-30
    y2022    : 2022-02-01 → 2022-05-31

Reports mean spread and Sharpe of both books with and without those
windows. If the "aggressive wins in high-vol" pattern is a real
regime effect, it should persist after stripping the crises. If it
collapses, the pattern is a crisis-recovery artifact.

Outputs
-------
    data/v6_static/oracle_blender/diag_regime_2x3.csv
    data/v6_static/oracle_blender/diag_crisis_strip.csv
    data/v6_static/oracle_blender/diag_binary_transitions.csv
    (all also printed to stdout)

Binary-transition section
-------------------------
For every blend variant (both ramp and binary), the script also
computes:

- Enter-defensive / exit-defensive events per year (λ transitions
  toward or away from 0).
- Total switch events per year and fraction of bars in the fully-
  defensive corner.
- Dwell time when defensive: mean / median / max consecutive-λ=0 run.
- Turnover at "transition bars" vs "non-transition bars." A
  transition bar is any bar where λ differs from the previous bar's
  λ (both hard and soft transitions). For binary variants this is
  every single λ change; for ramp variants it's every bar where the
  ramp moved at all.
- Cost from transitions (bps / yr), computed as turnover at
  transition bars × COST_PER_TRADE, annualized.
- Defensive-minus-aggressive return in high-vol weeks (bucketed by
  fwd_1w_rv percentile > 0.9 and fwd_4w_rv percentile > 0.9). Answers
  "how much do we save by being defensive in the actual high-vol
  weeks, and is that enough to offset the transition cost?"

Sample discipline
-----------------
IS-only per [[feedback-oos-discipline]]. Diagnostic table only —
does not affect any of the traded books. No parameter tuning; the
crisis windows are pre-registered above.

Run
---
    python v6/scripts/blender_diagnostics_v6.py
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


OUT_ROOT = C.DATA_DIR / "v6_static" / "oracle_blender"

# Pre-registered crisis windows — set BEFORE looking at the strip
# effect. Not tuned to the data.
CRISIS_WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("covid", "2020-02-01", "2020-04-30"),
    ("y2022", "2022-02-01", "2022-05-31"),
)


def _load_bar(label: str) -> pd.DataFrame:
    return pd.read_csv(OUT_ROOT / f"bar_{label}.csv",
                       index_col=0, parse_dates=True)


def _load_lambdas() -> pd.DataFrame:
    df = pd.read_csv(OUT_ROOT / "lambdas.csv", parse_dates=["date"])
    return df.set_index(["variant", "date"])


def _bucket_regime(pct: pd.Series) -> pd.Series:
    """Match the blender gates: low if pct < 0.3, high if pct > 0.9,
    else mid. Warmup NaN → NaN (excluded from bucket stats)."""
    out = pd.Series(pd.NA, index=pct.index, dtype="object")
    out[pct < 0.30] = "low"
    out[(pct >= 0.30) & (pct <= 0.90)] = "mid"
    out[pct > 0.90] = "high"
    return out


def _annualized_sharpe(x: pd.Series) -> float:
    x = x.dropna()
    if len(x) < 2 or x.std(ddof=1) == 0:
        return float("nan")
    return float(x.mean() / x.std(ddof=1) * np.sqrt(C.WEEKS_PER_YEAR))


def _run() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    # -------------------- load solo book returns --------------------
    d_def = _load_bar("solo_defensive")["net_ret"]
    d_agg = _load_bar("solo_aggressive")["net_ret"]
    idx   = d_def.index.intersection(d_agg.index)
    d_def, d_agg = d_def.loc[idx], d_agg.loc[idx]

    is_mask = idx <= C.IN_SAMPLE_END
    d_def, d_agg = d_def[is_mask], d_agg[is_mask]
    spread = (d_agg - d_def).rename("spread")

    # -------------------- load λ + score panels ---------------------
    lam_df = _load_lambdas()

    # Signals of interest: percentile from each vol_source.
    signals = {
        "causal":    "blend_causal",
        "fwd_1w_rv": "blend_fwd_1w_rv",
        "fwd_4w_rv": "blend_fwd_4w_rv",
    }
    pcts: dict[str, pd.Series] = {}
    for src, variant in signals.items():
        if variant not in lam_df.index.get_level_values("variant"):
            continue
        p = lam_df.xs(variant, level="variant")["score_pct"].reindex(spread.index)
        pcts[src] = p

    # Future-direction proxy: sign of defensive net_ret at bar t
    # (which is bar t → t+1 return, i.e., "market went up next week").
    fut_up = (d_def > 0).astype(int)   # 1 = up, 0 = down (ties = down)

    # -------------------- 2 × 3 diagnostic table ---------------------
    print(f"IS bars analyzed: {len(spread)}")
    print(f"solo_defensive Sharpe: {_annualized_sharpe(d_def):+.3f}")
    print(f"solo_aggressive Sharpe: {_annualized_sharpe(d_agg):+.3f}")
    print(f"mean spread (agg − def): {spread.mean()*100:+.4f}% / wk")
    print(f"annualized spread:       {spread.mean()*52*100:+.2f}% / yr")
    print()
    print(f'{"="*100}')
    print("Regime × future-return sign diagnostic")
    print("Cell content: mean(agg − def) %/wk   [n bars]")
    print(f'{"="*100}')

    rows_out = []
    for signal_name, pct in pcts.items():
        bucket = _bucket_regime(pct)
        print(f"\nSignal: {signal_name}")
        header = f'{"regime":>8s} | {"fut_up":>15s} | {"fut_down":>15s} | {"combined":>18s}'
        print(header)
        print("-" * len(header))
        for regime in ("low", "mid", "high"):
            m_reg = (bucket == regime).reindex(spread.index).fillna(False)
            row = {"signal": signal_name, "regime": regime}
            cells = []
            for direction_label, m_dir in (
                ("fut_up",   fut_up == 1),
                ("fut_down", fut_up == 0),
            ):
                m = m_reg & m_dir.reindex(spread.index).fillna(False)
                n = int(m.sum())
                mean_pct = (spread[m].mean() * 100) if n else float("nan")
                row[f"{direction_label}_mean_pct_wk"] = mean_pct
                row[f"{direction_label}_n"] = n
                cells.append(f"{mean_pct:+7.4f}  [n={n:>3d}]")
            # Combined (both directions in this regime)
            m_all = m_reg
            n_all = int(m_all.sum())
            mean_all = (spread[m_all].mean() * 100) if n_all else float("nan")
            row["combined_mean_pct_wk"] = mean_all
            row["combined_n"] = n_all
            cells.append(f"{mean_all:+7.4f}  [n={n_all:>3d}]")
            print(f'{regime:>8s} | {cells[0]:>15s} | {cells[1]:>15s} | {cells[2]:>18s}')
            rows_out.append(row)

    diag_df = pd.DataFrame(rows_out)
    diag_df.to_csv(OUT_ROOT / "diag_regime_2x3.csv", index=False)

    # -------------------- crisis strip -------------------------------
    print()
    print(f'{"="*100}')
    print("Crisis-strip diagnostic")
    print("=" * 100)

    strip_rows = []
    # Baseline (no strip)
    b_def_full = _annualized_sharpe(d_def)
    b_agg_full = _annualized_sharpe(d_agg)
    b_spread_full = spread.mean() * 100
    print(f'{"config":>32s}  {"n_bars":>7s}  {"def_S":>7s}  {"agg_S":>7s}  {"mean_spread%":>13s}')
    print("-" * 78)
    print(f'{"full IS (no strip)":>32s}  {len(spread):>7d}  '
          f'{b_def_full:>+7.3f}  {b_agg_full:>+7.3f}  {b_spread_full:>+13.4f}')
    strip_rows.append({
        "config": "full_IS_no_strip", "n_bars": len(spread),
        "def_sharpe": b_def_full, "agg_sharpe": b_agg_full,
        "mean_spread_pct_wk": b_spread_full,
    })

    # Strip each crisis separately, then together.
    for name, start_s, end_s in CRISIS_WINDOWS:
        start = pd.Timestamp(start_s)
        end   = pd.Timestamp(end_s)
        strip = ~((spread.index >= start) & (spread.index <= end))
        n = int(strip.sum())
        row = {
            "config":    f"strip_{name}",
            "n_bars":    n,
            "def_sharpe": _annualized_sharpe(d_def[strip]),
            "agg_sharpe": _annualized_sharpe(d_agg[strip]),
            "mean_spread_pct_wk": spread[strip].mean() * 100,
        }
        strip_rows.append(row)
        label = f'strip {name} ({start_s} → {end_s})'
        print(f'{label:>32s}  {n:>7d}  '
              f'{row["def_sharpe"]:>+7.3f}  {row["agg_sharpe"]:>+7.3f}  '
              f'{row["mean_spread_pct_wk"]:>+13.4f}')

    # Strip both
    strip_both = pd.Series(True, index=spread.index)
    for name, start_s, end_s in CRISIS_WINDOWS:
        s, e = pd.Timestamp(start_s), pd.Timestamp(end_s)
        strip_both &= ~((spread.index >= s) & (spread.index <= e))
    n = int(strip_both.sum())
    row = {
        "config":    "strip_all_crises",
        "n_bars":    n,
        "def_sharpe": _annualized_sharpe(d_def[strip_both]),
        "agg_sharpe": _annualized_sharpe(d_agg[strip_both]),
        "mean_spread_pct_wk": spread[strip_both].mean() * 100,
    }
    strip_rows.append(row)
    print(f'{"strip both":>32s}  {n:>7d}  '
          f'{row["def_sharpe"]:>+7.3f}  {row["agg_sharpe"]:>+7.3f}  '
          f'{row["mean_spread_pct_wk"]:>+13.4f}')

    # ALSO: within each crisis window, per-signal high-regime spread —
    # tests whether the "aggressive wins in high vol" pattern is
    # concentrated inside crisis periods.
    print()
    print("Within-crisis contribution to the 'agg wins in high-vol' pattern")
    print(f'{"signal":>12s}  {"regime":>7s}  {"in_crisis_n":>12s}  '
          f'{"in_crisis_spread%":>18s}  {"out_crisis_n":>12s}  {"out_crisis_spread%":>18s}')
    print("-" * 92)
    crisis_mask = pd.Series(False, index=spread.index)
    for _, start_s, end_s in CRISIS_WINDOWS:
        s, e = pd.Timestamp(start_s), pd.Timestamp(end_s)
        crisis_mask |= ((spread.index >= s) & (spread.index <= e))

    within_rows = []
    for signal_name, pct in pcts.items():
        bucket = _bucket_regime(pct).reindex(spread.index)
        for regime in ("low", "mid", "high"):
            m_reg = (bucket == regime).reindex(spread.index).fillna(False)
            # In-crisis
            m_in = m_reg & crisis_mask
            n_in = int(m_in.sum())
            sp_in = (spread[m_in].mean() * 100) if n_in else float("nan")
            # Out-of-crisis
            m_out = m_reg & (~crisis_mask)
            n_out = int(m_out.sum())
            sp_out = (spread[m_out].mean() * 100) if n_out else float("nan")
            within_rows.append({
                "signal": signal_name, "regime": regime,
                "in_crisis_n": n_in, "in_crisis_spread_pct_wk": sp_in,
                "out_crisis_n": n_out, "out_crisis_spread_pct_wk": sp_out,
            })
            print(f"{signal_name:>12s}  {regime:>7s}  {n_in:>12d}  "
                  f"{sp_in:>+18.4f}  {n_out:>12d}  {sp_out:>+18.4f}")

    # -------------------- binary-transition diagnostic ---------------
    print()
    print(f'{"="*100}')
    print("Binary-transition diagnostic — one row per blend variant")
    print("=" * 100)

    is_years = len(spread) / C.WEEKS_PER_YEAR
    cost_per_trade = 0.001   # 10 bp / side, matches DEFAULT_COST_PER_TRADE

    trans_rows = []
    # Every variant that has a λ series (both ramp and binary; excludes
    # solo books and best-fixed-λ, which have no per-bar λ record).
    variants = sorted(lam_df.index.get_level_values("variant").unique())
    header = (f'{"variant":>22s}  {"ent/yr":>7s}  {"exit/yr":>7s}  '
              f'{"switch/yr":>10s}  {"def_frac":>9s}  '
              f'{"dwell_mean":>11s}  {"dwell_max":>10s}  '
              f'{"turn_trans":>11s}  {"turn_other":>11s}  {"cost_trans_bps/yr":>18s}')
    print(header)
    print("-" * len(header))

    for variant in variants:
        lam_series = lam_df.xs(variant, level="variant")["lambda"]
        lam_is = lam_series.reindex(spread.index).astype(float)

        # A "transition" bar = λ differs from the previous λ. Use fillna
        # method="ffill" first so the first non-warmup bar doesn't count
        # as a transition due to a NaN→number step.
        prev = lam_is.shift(1)
        trans_mask = (lam_is != prev) & lam_is.notna() & prev.notna()

        # Enter / exit "defensive" (λ == 0 exactly).
        def_now  = lam_is == 0.0
        def_prev = prev   == 0.0
        enter = def_now & (~def_prev) & prev.notna()
        exit_ = (~def_now) & def_prev & lam_is.notna()

        # Dwell time: consecutive-λ==0 runs.
        # Method: for each bar, run_id = cumsum(def_now != prev of def_now)
        # so runs of same value share an id. Then group by id, count.
        # shift(fill_value=False) keeps the series bool-dtyped without
        # tripping the pandas ≥ 2.2 fillna-downcasting FutureWarning.
        def_change = def_now != def_now.shift(1, fill_value=False)
        run_id = def_change.cumsum()
        run_lens = def_now.groupby(run_id).sum()  # count of True per run
        def_runs = run_lens[run_lens > 0]         # only the defensive-runs
        dwell_mean = float(def_runs.mean()) if len(def_runs) else 0.0
        dwell_med  = float(def_runs.median()) if len(def_runs) else 0.0
        dwell_max  = int(def_runs.max()) if len(def_runs) else 0

        # Turnover: load the per-bar CSV and match to transition bars.
        try:
            bar_df = _load_bar(variant).reindex(spread.index)
        except FileNotFoundError:
            # Skip variants that don't have a per-bar CSV (shouldn't happen).
            continue
        turn = bar_df["turnover"]
        turn_trans = float(turn[trans_mask].mean()) if trans_mask.any() else float("nan")
        turn_other = float(turn[~trans_mask & turn.notna()].mean())
        # Cost from transitions only.
        cost_trans_total = float(turn[trans_mask].sum() * cost_per_trade)
        cost_trans_bps_yr = cost_trans_total / is_years * 1e4

        row = {
            "variant":         variant,
            "enter_per_yr":    float(enter.sum()) / is_years,
            "exit_per_yr":     float(exit_.sum()) / is_years,
            "switches_per_yr": float(trans_mask.sum()) / is_years,
            "defensive_frac":  float(def_now.mean()),
            "dwell_mean":      dwell_mean,
            "dwell_median":    dwell_med,
            "dwell_max":       dwell_max,
            "turn_trans_bar":  turn_trans,
            "turn_other_bar":  turn_other,
            "cost_trans_bps_per_yr": cost_trans_bps_yr,
        }
        trans_rows.append(row)
        print(f'{variant:>22s}  '
              f'{row["enter_per_yr"]:>7.2f}  '
              f'{row["exit_per_yr"]:>7.2f}  '
              f'{row["switches_per_yr"]:>10.2f}  '
              f'{row["defensive_frac"]:>9.1%}  '
              f'{row["dwell_mean"]:>11.2f}  '
              f'{row["dwell_max"]:>10d}  '
              f'{row["turn_trans_bar"]:>11.4f}  '
              f'{row["turn_other_bar"]:>11.4f}  '
              f'{row["cost_trans_bps_per_yr"]:>18.1f}')

    # -------------------- high-vol def-vs-agg summary ----------------
    # "Return of defensive minus aggressive in high-vol weeks" — the
    # explicit metric the user asked for. High vol defined by the
    # forward-RV signals at pct > 0.9.
    print()
    print("Defensive − aggressive return in high-vol weeks (net_ret_def − net_ret_agg)")
    print(f'{"signal":>12s}  {"n bars":>7s}  {"mean(def−agg) %/wk":>20s}  '
          f'{"annualized %":>13s}  {"share of IS":>13s}')
    print("-" * 76)

    high_rows = []
    for signal_name, pct in pcts.items():
        bucket = _bucket_regime(pct).reindex(spread.index)
        m_high = (bucket == "high")
        n_high = int(m_high.sum())
        # Convention: agg-def is what we already computed; def-agg is
        # the sign the user asked for.
        def_minus_agg = -spread          # net_ret_def − net_ret_agg per bar
        mean_def_minus_agg_pct = (def_minus_agg[m_high].mean() * 100) if n_high else float("nan")
        # Naive annualization: mean per-bar × WEEKS_PER_YEAR (not
        # compounded, matches the sizing-sweep convention).
        annual_pct = mean_def_minus_agg_pct * C.WEEKS_PER_YEAR
        share = n_high / len(spread) if len(spread) else 0
        high_rows.append({
            "signal":              signal_name,
            "n_high_vol_bars":     n_high,
            "mean_def_minus_agg_pct_wk": mean_def_minus_agg_pct,
            "annualized_pct":      annual_pct,
            "share_of_IS":         share,
        })
        print(f"{signal_name:>12s}  {n_high:>7d}  "
              f"{mean_def_minus_agg_pct:>+20.4f}  "
              f"{annual_pct:>+13.2f}  {share:>13.1%}")

    # Consolidate all binary/transition tables into diag_binary_transitions.csv
    trans_df = pd.DataFrame(trans_rows)
    high_df  = pd.DataFrame(high_rows)
    trans_df["section"] = "transitions_by_variant"
    high_df["section"]  = "def_minus_agg_high_vol"
    combined_bin = pd.concat([
        trans_df.reindex(columns=["section"] + [c for c in trans_df.columns if c != "section"]),
        high_df.reindex(columns=["section"] + [c for c in high_df.columns if c != "section"]),
    ], ignore_index=True)
    combined_bin.to_csv(OUT_ROOT / "diag_binary_transitions.csv", index=False)
    print(f'\nwrote {OUT_ROOT / "diag_binary_transitions.csv"}')

    strip_df = pd.DataFrame(strip_rows)
    within_df = pd.DataFrame(within_rows)
    # Persist both tables in one CSV using a section column so the file
    # stays flat.
    strip_df["section"]  = "strip_baseline"
    within_df["section"] = "within_crisis_by_regime"
    combined = pd.concat([
        strip_df.reindex(columns=["section"] + [c for c in strip_df.columns if c != "section"]),
        within_df.reindex(columns=["section"] + [c for c in within_df.columns if c != "section"]),
    ], ignore_index=True)
    combined.to_csv(OUT_ROOT / "diag_crisis_strip.csv", index=False)

    print()
    print(f'wrote {OUT_ROOT / "diag_regime_2x3.csv"}')
    print(f'wrote {OUT_ROOT / "diag_crisis_strip.csv"}')


if __name__ == "__main__":
    _run()
