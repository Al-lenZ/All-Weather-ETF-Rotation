"""
v6/scripts/tests_sizing_v6.py
=============================
Unit tests for the sizing sandbox in ``hysteresis_engine_v6_sizing``
and the two-book blender in ``two_book_blender_v6``.

Coverage — sizing kernel
------------------------
1. ``inv_vol`` reproduces ``hysteresis_engine_v6.build_hysteresis_weights``
   bit-for-bit on the production long_q20 replace-ε=0.20 cell.
2. ``rank_prop`` on a synthetic bar with H=4 held names and strictly
   monotone α yields weights (4, 3, 2, 1)/10 in α-rank order.
3. ``rank_prop`` LS-mode leg signs and per-leg normalization.

Coverage — blender
------------------
4. ``lambda_schedule`` returns 1 below the lower gate, 0 above the
   upper gate, and the correct linear interpolant between them
   (continuous at both boundaries).
5. ``score_to_percentile`` respects causal expanding-window semantics:
   the value at bar t depends only on bars ≤ t; ``min_history`` bars
   before the first non-NaN percentile.
6. ``blend_weights`` produces a strict convex combination of two W
   panels — Σ per bar preserved when both legs sum to 1, no signal
   leak from cells that are zero in both panels.

Run
---
    python v6/scripts/tests_sizing_v6.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))

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
import hysteresis_engine_v6_sizing as HS
import two_book_blender_v6 as B


CELL_MODE    = "long"
CELL_Q       = 0.20
CELL_RULE    = "replace"
CELL_EPSILON = 0.20


# ---------------------------------------------------------------------- #
# 1. inv_vol reproduction on the production control point
# ---------------------------------------------------------------------- #
def _load_shared() -> dict:
    data_dir = C.DATA_DIR
    mem = pd.read_parquet(data_dir / "universe_v6" / "membership.parquet")
    codes = list(mem.columns[mem.any(axis=0)])
    mem   = mem[codes].astype(bool)
    fwd   = pd.read_parquet(data_dir / "panels_v6" / "fwd_1w.parquet")[codes]
    sigma = pd.read_parquet(data_dir / "panels_v6" / "sigma_causal_26w.parquet")[codes]
    cell  = f"{CELL_MODE}_q{int(round(CELL_Q * 100)):02d}"
    alpha = pd.read_parquet(data_dir / "v6_static" / cell / "ensemble_alpha.parquet")
    return {"membership": mem, "sigma": sigma, "fwd_1w": fwd, "alpha": alpha}


def test_inv_vol_reproduces_hysteresis_baseline() -> None:
    shared = _load_shared()
    W_ref, _, _ = H.build_hysteresis_weights(
        shared["alpha"], shared["sigma"], shared["membership"],
        q=CELL_Q, mode=CELL_MODE, epsilon=CELL_EPSILON, rule=CELL_RULE,
    )
    W_new, _, _ = HS.build_hysteresis_weights_sized(
        shared["alpha"], shared["sigma"], shared["membership"],
        q=CELL_Q, mode=CELL_MODE, epsilon=CELL_EPSILON, rule=CELL_RULE,
        sizing="inv_vol",
    )
    diff = (W_new - W_ref).abs().to_numpy().max()
    assert diff < 1e-12, (
        f"inv_vol path diverged from hysteresis_engine_v6 baseline: "
        f"max |ΔW| = {diff:.3g}"
    )
    print(f"  [OK] inv_vol reproduces hysteresis baseline (max |ΔW| = {diff:.2e})")


# ---------------------------------------------------------------------- #
# 2. rank_prop shape on a monotone-α held set
# ---------------------------------------------------------------------- #
def test_rank_prop_monotone_alpha_shape() -> None:
    # H=4 held names, α strictly monotone-decreasing. Under
    # local-rank convention: r = (1, 2, 3, 4)  →  p = (4, 3, 2, 1),
    # Σp = 10, w = (0.4, 0.3, 0.2, 0.1).
    alpha_row = np.array([1.5, 0.7, -0.1, -1.2, np.nan, np.nan])
    held_idx  = np.array([0, 1, 2, 3])
    w = HS._leg_weights_rank_prop(alpha_row, held_idx, target_sum=+1.0)

    expected = np.array([0.4, 0.3, 0.2, 0.1, 0.0, 0.0])
    err = np.abs(w - expected).max()
    assert err < 1e-15, f"rank_prop monotone shape wrong: max |Δw| = {err:.3g}"
    assert abs(w.sum() - 1.0) < 1e-15, f"rank_prop not normalized: Σw = {w.sum()}"
    print(f"  [OK] rank_prop monotone-α → (0.4, 0.3, 0.2, 0.1)")


def test_alpha_prop_shape_and_normalization() -> None:
    # α_held = [4.0, 2.0, 1.0, 0.0], H = 4.
    # min = 0, rng = 4, eps = max(4/4, 1e-12) = 1.0.
    # p = [4, 2, 1, 0] - 0 + 1 = [5, 3, 2, 1]; Σp = 11.
    # w = [5/11, 3/11, 2/11, 1/11]; sum = 1.
    alpha_row = np.array([4.0, 2.0, 1.0, 0.0, np.nan])
    held_idx  = np.array([0, 1, 2, 3])
    w = HS._leg_weights_alpha_prop(alpha_row, held_idx, target_sum=+1.0)
    exp = np.array([5/11, 3/11, 2/11, 1/11, 0.0])
    err = np.abs(w - exp).max()
    assert err < 1e-15, f"alpha_prop level shape: max |Δw| = {err:.3g}"
    assert abs(w.sum() - 1.0) < 1e-15, f"alpha_prop Σw ≠ 1: {w.sum()}"
    print("  [OK] alpha_prop monotone α → v4pool p/Σp formula matches")


def test_alpha_prop_negative_alpha_shift() -> None:
    # Row-z-ish α in v6: half of values can be negative. Min-shift keeps
    # all p ≥ ε > 0 so weights are always non-negative and sum to 1.
    alpha_row = np.array([1.5, 0.3, -0.4, -1.2])
    held_idx  = np.array([0, 1, 2, 3])
    w = HS._leg_weights_alpha_prop(alpha_row, held_idx, target_sum=+1.0)
    # Expected: rng = 2.7, eps = 2.7/4 = 0.675.
    # p = [1.5, 0.3, -0.4, -1.2] - (-1.2) + 0.675
    #   = [2.7, 1.5, 0.8, 0.0] + 0.675
    #   = [3.375, 2.175, 1.475, 0.675]
    # Σp = 7.7; w = p / 7.7.
    exp = np.array([3.375, 2.175, 1.475, 0.675]) / 7.7
    err = np.abs(w - exp).max()
    assert err < 1e-14, f"alpha_prop negative-α shift: max |Δw| = {err:.3g}"
    assert (w >= 0).all(), "alpha_prop must have non-negative weights"
    print("  [OK] alpha_prop handles negative α via min-shift + ε floor")


def test_sigma_trailing_percentile_basic() -> None:
    # 4-bar column of σ = [1, 2, 3, 4] with window=3.
    # At t=2 (3-bar window [1,2,3]): p = count(≤ 3) / 3 = 3/3 = 1.0.
    # At t=3 (window [2,3,4]): p = count(≤ 4) / 3 = 3/3 = 1.0.
    # Before t=2: NaN (window not full).
    sigma = pd.DataFrame({"A": [0.01, 0.02, 0.03, 0.04, 0.02]},
                         index=pd.date_range("2020-01-03", periods=5, freq="W-FRI"))
    p = HS._sigma_trailing_percentile(sigma, window=3)
    # Monotone-up first 4 bars: current is always the max → pct = 1.0.
    assert pd.isna(p.iloc[0, 0])
    assert pd.isna(p.iloc[1, 0])
    assert abs(p.iloc[2, 0] - 1.0) < 1e-15
    assert abs(p.iloc[3, 0] - 1.0) < 1e-15
    # At t=4, σ=0.02 in window [0.03, 0.04, 0.02]. count(≤0.02) = 1
    # (just itself) → 1/3.
    assert abs(p.iloc[4, 0] - 1/3) < 1e-15
    print("  [OK] _sigma_trailing_percentile monotone + mid-window case")


def test_sigma_trailing_percentile_nan_handling() -> None:
    # Insufficient defined bars → NaN percentile.
    sigma = pd.DataFrame({"A": [np.nan, np.nan, 0.02, 0.03, 0.04, 0.02]},
                         index=pd.date_range("2020-01-03", periods=6, freq="W-FRI"))
    p = HS._sigma_trailing_percentile(sigma, window=3)
    # At t=2, window [NaN, NaN, 0.02] has only 1 defined → NaN.
    # At t=3, window [NaN, 0.02, 0.03] has 2 defined < window=3 → NaN.
    # At t=4, window [0.02, 0.03, 0.04] has 3 defined → 1.0.
    # At t=5, window [0.03, 0.04, 0.02] has 3 defined → 1/3.
    assert pd.isna(p.iloc[2, 0])
    assert pd.isna(p.iloc[3, 0])
    assert abs(p.iloc[4, 0] - 1.0) < 1e-15
    assert abs(p.iloc[5, 0] - 1/3) < 1e-15
    print("  [OK] _sigma_trailing_percentile: partial window → NaN")


def test_inv_vol_pctl_multiplier_bounds() -> None:
    # β = ln(2). At p=0.5 → mult = exp(0) = 1 (no adjustment).
    # At p=0.0 → mult = exp(ln(2) · 0.5) = √2 ≈ 1.4142.
    # At p=1.0 → mult = exp(ln(2) · -0.5) = 1/√2 ≈ 0.7071.
    # Build a 3-bar σ panel that's monotone increasing → pct at t=2 is 1.0.
    sigma = pd.DataFrame({"A": [0.02, 0.03, 0.04]},
                         index=pd.date_range("2020-01-03", periods=3, freq="W-FRI"))
    eligible = pd.DataFrame(True, index=sigma.index, columns=sigma.columns)
    v = HS._sizing_kernel(sigma, eligible, "inv_vol_pctl")
    # Bar 0, 1: percentile NaN → mult = 1.0 → v = 1/σ.
    assert abs(v.iloc[0, 0] - 1.0 / 0.02) < 1e-12, f"bar0: {v.iloc[0, 0]}"
    assert abs(v.iloc[1, 0] - 1.0 / 0.03) < 1e-12, f"bar1: {v.iloc[1, 0]}"
    # Bar 2 (WINDOW=26 default → NaN because window=26 not met → mult=1.0).
    # Wait — default window is 26 here; with only 3 bars all pct are NaN.
    # So mult = 1.0 on all three bars.
    assert abs(v.iloc[2, 0] - 1.0 / 0.04) < 1e-12, f"bar2: {v.iloc[2, 0]}"
    print("  [OK] inv_vol_pctl degrades to inv_vol on warmup (pct NaN → mult=1.0)")


def test_inv_vol_pctl_multiplier_full_window() -> None:
    # 30-bar σ series with a clear regime: first 26 bars flat at 0.03,
    # then bar 26+: 0.02 (below history), 0.04 (above history), etc.
    T = 30
    vals = np.full(T, 0.03)
    vals[26] = 0.02   # lower than history → pct should be low
    vals[27] = 0.04   # higher than history → pct should be high
    vals[28] = 0.03   # tied with history → pct depends on ties
    sigma = pd.DataFrame({"A": vals},
                         index=pd.date_range("2020-01-03", periods=T, freq="W-FRI"))
    eligible = pd.DataFrame(True, index=sigma.index, columns=sigma.columns)
    v = HS._sizing_kernel(sigma, eligible, "inv_vol_pctl")
    beta = np.log(2.0)

    # Bar 25 (first full-window bar): all σ = 0.03 uniformly → pct = 1.0
    # (all values ≤ current). mult = exp(β · -0.5) = 1/√2.
    exp_mult_25 = np.exp(beta * -0.5)
    assert abs(v.iloc[25, 0] - (1.0 / 0.03) * exp_mult_25) < 1e-10, \
        f"bar25 multiplier off: {v.iloc[25, 0]} vs {(1.0/0.03) * exp_mult_25}"

    # Bar 26: σ=0.02, window includes 25 bars at 0.03 + 0.02 itself.
    # count(≤ 0.02) = 1 (self). pct = 1/26 ≈ 0.0385.
    # mult = exp(ln(2) · (0.5 - 0.0385)) = exp(0.3197) ≈ 1.377
    p26 = 1/26
    exp_mult_26 = np.exp(beta * (0.5 - p26))
    assert abs(v.iloc[26, 0] - (1.0 / 0.02) * exp_mult_26) < 1e-10, \
        f"bar26 low-vol upweight off"

    # Sanity: bar 25 (all-history-tied) mult ≈ 0.707; bar 26 (lower than history) mult ≈ 1.38.
    assert exp_mult_25 < 1.0 < exp_mult_26, "boundary sanity: p=1 down, p<0.5 up"
    print("  [OK] inv_vol_pctl multiplier: low-vol regime → upweight, high-vol → downweight")


def test_alpha_prop_equal_alpha_falls_back_to_equal_weight() -> None:
    # rng = 0 → eps = 1e-12; p = [ε, ε, ε] → w = [1/H, 1/H, 1/H].
    alpha_row = np.array([0.5, 0.5, 0.5])
    held_idx  = np.array([0, 1, 2])
    w = HS._leg_weights_alpha_prop(alpha_row, held_idx, target_sum=+1.0)
    exp = np.array([1/3, 1/3, 1/3])
    err = np.abs(w - exp).max()
    assert err < 1e-15, f"alpha_prop equal-α: max |Δw| = {err:.3g}"
    print("  [OK] alpha_prop equal-α → equal weights (ε floor guards Σp>0)")


def test_rank_prop_ls_leg_signs_and_norms() -> None:
    # LS mode: long leg target_sum=+0.5, short leg target_sum=-0.5.
    # H=3 for each leg, so p = (3, 2, 1), Σp = 6, per-name w =
    # ±0.5·(3, 2, 1)/6 = ±(0.25, 0.1666.., 0.0833..).
    alpha_row = np.array([2.0, 1.0, 0.0, -1.0, -2.0])
    long_idx  = np.array([0, 1, 2])
    short_idx = np.array([2, 3, 4])   # (2 shared for shape test; ignore overlap here)

    w_long  = HS._leg_weights_rank_prop(alpha_row, long_idx, target_sum=+0.5)
    w_short = HS._leg_weights_rank_prop(alpha_row, short_idx, target_sum=-0.5)

    exp_long_pos = np.array([0.25, 1/6.0, 1/12.0])
    err_long = np.abs(w_long[long_idx] - exp_long_pos).max()
    assert err_long < 1e-15, f"long leg wrong: {err_long:.3g}"
    assert abs(w_long.sum() - 0.5) < 1e-15
    # Short leg: α on short_idx is (0.0, -1.0, -2.0) → rank (1, 2, 3) →
    # p = (3, 2, 1), Σ|w| = 0.5, signs all negative.
    exp_short_pos = np.array([-0.25, -1/6.0, -1/12.0])
    err_short = np.abs(w_short[short_idx] - exp_short_pos).max()
    assert err_short < 1e-15, f"short leg wrong: {err_short:.3g}"
    assert abs(w_short.sum() + 0.5) < 1e-15
    print("  [OK] rank_prop LS leg signs + norms")


# ---------------------------------------------------------------------- #
# 4. lambda_schedule boundary + interior correctness
# ---------------------------------------------------------------------- #
def test_lambda_schedule_boundaries_and_interior() -> None:
    # Below lower gate → 1; above upper gate → 0.
    # Interior: λ = (0.9 − p) / 0.6. At p=0.3 → 1; p=0.9 → 0; p=0.6 → 0.5.
    # Warmup (NaN) → warmup_lambda, defaults to 0.5.
    pct = pd.Series([0.0, 0.29, 0.30, 0.45, 0.60, 0.75, 0.90, 0.91, 1.0, np.nan],
                    index=pd.RangeIndex(10))
    lam = B.lambda_schedule(pct, lower_gate=0.30, upper_gate=0.90,
                            warmup_lambda=0.5)
    exp = np.array([1.0, 1.0, 1.0, 0.75, 0.5, 0.25, 0.0, 0.0, 0.0, 0.5])
    err = np.abs(lam.to_numpy() - exp).max()
    assert err < 1e-15, f"lambda_schedule mismatch: max |Δλ| = {err:.3g}"
    print("  [OK] lambda_schedule boundaries + interior + neutral warmup")


def test_hold_through_transient_nan() -> None:
    # Warmup NaN preserved; transient NaN post-first-valid gets ffilled.
    x = pd.Series([np.nan, np.nan, 0.4, 0.6, np.nan, np.nan, 0.7, np.nan],
                  index=pd.RangeIndex(8))
    y = B.hold_through_transient_nan(x)
    # Bars 0..1: warmup, stay NaN.
    assert y.iloc[0:2].isna().all(), "warmup must stay NaN"
    # Bar 2: 0.4 (first valid). Bar 3: 0.6. Bars 4-5: ffilled from 0.6.
    # Bar 6: 0.7. Bar 7: ffilled from 0.7.
    assert y.iloc[2] == 0.4
    assert y.iloc[3] == 0.6
    assert y.iloc[4] == 0.6, "transient NaN → hold last valid"
    assert y.iloc[5] == 0.6
    assert y.iloc[6] == 0.7
    assert y.iloc[7] == 0.7
    print("  [OK] hold_through_transient_nan: warmup preserved, transient NaN ffilled")


def test_binary_lambda_schedule() -> None:
    # λ = 0 above 0.9, λ = 1 at or below, warmup = 0.5.
    # Boundary check: pct = 0.9 exactly → λ = 1 (at_or_below, strict >).
    pct = pd.Series([0.0, 0.30, 0.60, 0.90, 0.9001, 0.95, 1.0, np.nan],
                    index=pd.RangeIndex(8))
    lam = B.binary_lambda_schedule(pct, upper_gate=0.90, warmup_lambda=0.5)
    exp = np.array([1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.5])
    err = np.abs(lam.to_numpy() - exp).max()
    assert err < 1e-15, f"binary_lambda_schedule mismatch: max |Δ| = {err:.3g}"
    print("  [OK] binary_lambda_schedule: hard cutoff at 0.9, boundary → λ=1")


def test_lambda_schedule_symmetric_warmup() -> None:
    # Symmetric warmup: naive and inverted MUST return the same λ on
    # NaN bars regardless of invert flag. Interior stays mirrored.
    pct = pd.Series([0.0, 0.29, 0.30, 0.45, 0.60, 0.75, 0.90, 0.91, 1.0, np.nan],
                    index=pd.RangeIndex(10))
    warmup = 0.5
    lam_norm = B.lambda_schedule(pct, warmup_lambda=warmup, invert=False)
    lam_inv  = B.lambda_schedule(pct, warmup_lambda=warmup, invert=True)
    # Warmup bar (index 9): both directions get the same value.
    assert lam_norm.iloc[-1] == warmup, "naive warmup"
    assert lam_inv.iloc[-1]  == warmup, "inverted warmup — must match naive"
    # Non-NaN: λ_inv = 1 − λ_norm (mirror across midline).
    mask = pct.notna()
    err = np.abs(lam_inv[mask].to_numpy() - (1.0 - lam_norm[mask].to_numpy())).max()
    assert err < 1e-15, f"invert mismatch on non-warmup: max |Δ| = {err:.3g}"
    # Sanity check with a different warmup value.
    lam2 = B.lambda_schedule(pct, warmup_lambda=0.25, invert=True)
    assert lam2.iloc[-1] == 0.25
    print("  [OK] lambda_schedule symmetric warmup (both directions same on NaN)")


# ---------------------------------------------------------------------- #
# 5. score_to_percentile — causal expanding rank
# ---------------------------------------------------------------------- #
def test_score_to_percentile_is_causal() -> None:
    # Monotone-increasing score: after warmup, each new bar sets a new
    # max → percentile = 1.0. min_history=10 means first non-NaN at t=9
    # (window has 10 obs).
    n = 40
    score = pd.Series(np.arange(n, dtype=float), index=pd.RangeIndex(n),
                      name="equity_score_causal")
    pct = B.score_to_percentile(score, min_history=10)
    # First 9 bars (0..8) → NaN (window < 10). Bar 9 is the first with
    # a defined percentile.
    assert pct.iloc[:9].isna().all(), "warmup bars must be NaN"
    # Bar 9..end: each new value is the max so far → percentile = 1.
    assert (pct.iloc[9:] == 1.0).all(), "monotone-max score should map to 1.0"
    # Causal check: mutating score[t+1] doesn't change pct[t].
    score_altered = score.copy()
    score_altered.iloc[20] = -999
    pct_altered = B.score_to_percentile(score_altered, min_history=10)
    # Compare the first 20 rows (which precede the mutation).
    same = (pct.iloc[:20].fillna(-1) == pct_altered.iloc[:20].fillna(-1))
    assert same.all(), (
        "past percentiles must not change when a future score changes")
    print("  [OK] score_to_percentile is causal + honors min_history")


def test_score_to_percentile_uniform_case() -> None:
    # Score = [0, 1, 2, ..., 99]. At bar 99, x=99 is the max → rank 100
    # of 100 → pct = 1.0. At bar 50, x=50 is the max so far → 1.0. So
    # the monotone increase makes pct always 1.0 after warmup — same
    # as above test. Add a shuffled case for coverage: score = np.arange
    # reversed → at each t, x[t] is the min of its history → pct = 1/n_t
    # (except at t = min_history where n_t = min_history+1).
    n = 40
    score = pd.Series(np.arange(n, 0, -1, dtype=float),
                      index=pd.RangeIndex(n),
                      name="equity_score_causal")
    pct = B.score_to_percentile(score, min_history=10)
    # After warmup: bar t has x = n - t; window has n_t = t + 1 values;
    # x is the min of the window → count(<=x) = 1 → pct = 1 / n_t.
    # min_history=10 → first defined pct at t=9 (window of 10).
    for t in range(9, n):
        exp = 1.0 / (t + 1)
        assert abs(pct.iloc[t] - exp) < 1e-15, (
            f"bar {t}: expected pct={exp:.6f}, got {pct.iloc[t]:.6f}")
    print("  [OK] score_to_percentile reversed-monotone case (min → 1/n)")


# ---------------------------------------------------------------------- #
# 5b. equity_risk_score_raw — oracle sources use *forward* RV correctly
# ---------------------------------------------------------------------- #
def test_equity_score_fwd_1w_rv_uses_next_bar() -> None:
    # Synthetic: 8 W-FRI bars, 2 equity codes with monotone-increasing RV.
    # At bar t, fwd_1w_rv score = mean of RV[t+1] across the 2 codes.
    idx = pd.date_range("2019-01-04", periods=8, freq="W-FRI")
    codes = ["A_eq", "B_eq"]
    sigma = pd.DataFrame(0.03, index=idx, columns=codes)     # placeholder
    rv    = pd.DataFrame(np.arange(1, 9)[:, None] * np.array([[1.0, 2.0]]),
                         index=idx, columns=codes)           # 8×2, [1,2],[2,4],[3,6],...
    mem   = pd.DataFrame(True, index=idx, columns=codes)
    block_tag = pd.Series({"A_eq": "broad_cn", "B_eq": "sector_cn"})

    score = B.equity_risk_score_raw(
        sigma, mem, block_tag, vol_source="fwd_1w_rv", rv_panel=rv)

    # score[t] = mean(RV[t+1]) = mean of row t+1 in rv.
    for t in range(len(idx) - 1):
        exp = (rv.iloc[t + 1, 0] + rv.iloc[t + 1, 1]) / 2.0
        assert abs(score.iloc[t] - exp) < 1e-12, (
            f"bar {t}: expected {exp}, got {score.iloc[t]}")
    # Last bar: no t+1 → NaN.
    assert pd.isna(score.iloc[-1]), "last bar should be NaN (no fwd RV)"
    print("  [OK] equity_score fwd_1w_rv uses RV[t+1] (not shifted trailing σ)")


def test_equity_score_fwd_4w_rv_uses_next_four_bars() -> None:
    # 10 bars; RV = [1, 2, 3, ..., 10]. At bar t, fwd_4w_rv =
    # mean(RV[t+1..t+4]).
    idx = pd.date_range("2019-01-04", periods=10, freq="W-FRI")
    codes = ["A_eq"]
    sigma = pd.DataFrame(0.03, index=idx, columns=codes)
    rv    = pd.DataFrame(np.arange(1, 11, dtype=float)[:, None],
                         index=idx, columns=codes)
    mem   = pd.DataFrame(True, index=idx, columns=codes)
    block_tag = pd.Series({"A_eq": "broad_cn"})

    score = B.equity_risk_score_raw(
        sigma, mem, block_tag, vol_source="fwd_4w_rv", rv_panel=rv)

    # score[0] = mean(RV[1..4]) = mean(2, 3, 4, 5) = 3.5
    # score[1] = mean(3, 4, 5, 6) = 4.5
    # score[5] = mean(7, 8, 9, 10) = 8.5
    # score[6] = mean(8, 9, 10, NaN) [with nan_mean] = 9.0
    # score[9] = all NaN → NaN
    assert abs(score.iloc[0] - 3.5) < 1e-12, f"bar 0: {score.iloc[0]}"
    assert abs(score.iloc[1] - 4.5) < 1e-12, f"bar 1: {score.iloc[1]}"
    assert abs(score.iloc[5] - 8.5) < 1e-12, f"bar 5: {score.iloc[5]}"
    assert abs(score.iloc[6] - 9.0) < 1e-12, f"bar 6: {score.iloc[6]}"
    assert pd.isna(score.iloc[-1]), "last bar should be NaN"
    print("  [OK] equity_score fwd_4w_rv is truly forward (mean of RV[t+1..t+4])")


# ---------------------------------------------------------------------- #
# 6. blend_weights — convex combination
# ---------------------------------------------------------------------- #
def test_blend_weights_convex_combination() -> None:
    idx = pd.RangeIndex(5)
    cols = list("ABCD")
    # Aggressive: mass on A only. Defensive: mass on D only. Each row
    # sums to 1 on both.
    W_agg = pd.DataFrame([[1, 0, 0, 0]] * 5, index=idx, columns=cols, dtype=float)
    W_def = pd.DataFrame([[0, 0, 0, 1]] * 5, index=idx, columns=cols, dtype=float)
    lam   = pd.Series([1.0, 0.75, 0.5, 0.25, 0.0], index=idx)
    W_blend = B.blend_weights(W_agg, W_def, lam)
    # Row sums preserved.
    assert np.allclose(W_blend.sum(axis=1).to_numpy(), 1.0), "row sums must be 1"
    # A column tracks λ; D column tracks 1−λ; B,C stay 0.
    assert np.allclose(W_blend["A"].to_numpy(), lam.to_numpy())
    assert np.allclose(W_blend["D"].to_numpy(), 1.0 - lam.to_numpy())
    assert (W_blend[["B", "C"]] == 0.0).all().all()
    print("  [OK] blend_weights convex-combo (row sums preserved, λ tracks A col)")


# ---------------------------------------------------------------------- #
# Driver
# ---------------------------------------------------------------------- #
def main() -> None:
    print("tests_sizing_v6:")
    test_inv_vol_reproduces_hysteresis_baseline()
    test_rank_prop_monotone_alpha_shape()
    test_alpha_prop_shape_and_normalization()
    test_alpha_prop_negative_alpha_shift()
    test_sigma_trailing_percentile_basic()
    test_sigma_trailing_percentile_nan_handling()
    test_inv_vol_pctl_multiplier_bounds()
    test_inv_vol_pctl_multiplier_full_window()
    test_alpha_prop_equal_alpha_falls_back_to_equal_weight()
    test_rank_prop_ls_leg_signs_and_norms()
    test_lambda_schedule_boundaries_and_interior()
    test_binary_lambda_schedule()
    test_lambda_schedule_symmetric_warmup()
    test_score_to_percentile_is_causal()
    test_score_to_percentile_uniform_case()
    test_hold_through_transient_nan()
    test_equity_score_fwd_1w_rv_uses_next_bar()
    test_equity_score_fwd_4w_rv_uses_next_four_bars()
    test_blend_weights_convex_combination()
    print("all tests passed.")


if __name__ == "__main__":
    main()
