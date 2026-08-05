"""v6/leverage/tests_m1_sanity.py — M1 sanity checks.

Three checks the leverage engine will depend on. All run in <15s off cached
artifacts.

1. ``test_raw_sharpe_reproduces_finalist`` — metrics.raw_sharpe on the
   frozen finalist ``net_ret.csv`` matches the value in ``summary.csv``
   within 1 bp. Gates against subtle annualization / ddof mismatches.

2. ``test_excess_sharpe_invariance_under_leverage`` — with constant rf
   (0.02 ann → 0.02 × 7/365 per weekly bar) and a synthetic base return
   series, ``excess_sharpe(net_lev, rf)`` equals ``excess_sharpe(net_base,
   rf)`` for L ∈ {1.0, 1.35, 1.5, 2.0}. Verifies the identity in PLAN §8A.

3. ``test_weekly_accrual_matches_hand_calc`` — funding_curves.weekly_accrual
   on a constant GC007 series returns rate × 7 / 365 per bar within 1e-9.

Run
---
    python v6/leverage/tests_m1_sanity.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import _common_leverage as CL
import metrics as M
import funding_curves as FC


def test_raw_sharpe_reproduces_finalist() -> None:
    net = pd.read_csv(CL.FINALIST_DIR / "net_ret.csv",
                      index_col=0, parse_dates=True)["net_ret"]
    summ = pd.read_csv(CL.FINALIST_DIR / "summary.csv").iloc[0]

    # Match xs_engine_v6._windowize: split at IN_SAMPLE_END, take IS ∪ OOS
    # (frozen v6 report uses IS+OOS = the "full" window for sharpe_net).
    from _common_v6 import IN_SAMPLE_END, OOS_START, OOS_END
    is_net  = net[net.index <= IN_SAMPLE_END]
    oos_net = net[(net.index >= OOS_START) & (net.index <= OOS_END)]
    full = pd.concat([is_net, oos_net])

    # The finalist summary.csv `sharpe_net` field is IS-only per
    # block_two_layer_v6.run_variant → summarize_book. Verify IS.
    ours_is  = M.raw_sharpe(is_net)
    theirs_is = float(summ["sharpe_net"])
    diff_is = ours_is - theirs_is
    print(f"[raw_sharpe] IS  ours={ours_is:.6f}  frozen={theirs_is:.6f}  "
          f"diff={diff_is:+.2e}")
    assert abs(diff_is) < 1e-4, (
        f"raw_sharpe drift on IS: ours={ours_is}, frozen={theirs_is}"
    )
    print("  ✓ pass (< 1 bp)")


def test_excess_sharpe_invariance_under_leverage() -> None:
    rng = np.random.default_rng(2026_07_30)
    idx = pd.date_range("2020-01-03", periods=200, freq="W-FRI")
    r_base = pd.Series(rng.normal(0.001, 0.003, size=200), index=idx,
                       name="base")

    rf_ann = 0.02
    rf_period = pd.Series(rf_ann * 7 / 365, index=idx, name="rf")

    base_excess = M.excess_sharpe(r_base, rf_period)
    print(f"[invariance] base excess Sharpe = {base_excess:.6f}")

    for L in (1.0, 1.35, 1.5, 2.0):
        r_lev = L * r_base - (L - 1) * rf_period
        e_lev = M.excess_sharpe(r_lev, rf_period)
        diff = e_lev - base_excess
        print(f"  L={L:.2f}  excess Sharpe = {e_lev:.6f}  diff = {diff:+.2e}")
        assert abs(diff) < 1e-10, (
            f"excess Sharpe not invariant at L={L}: {e_lev} vs {base_excess}"
        )
    print("  ✓ pass (invariance holds to 1e-10)")


def test_weekly_accrual_matches_hand_calc() -> None:
    # Constant rate 2%/yr over 90 days, weekly bars: each bar should accrue
    # rate × 7 / 365 = 0.02 × 7/365 = 3.8356e-4.
    daily_idx = pd.date_range("2020-01-01", periods=90, freq="D")
    rate = pd.Series(0.02, index=daily_idx, name="const2pct")
    weekly_idx = pd.date_range("2020-01-03", periods=12, freq="W-FRI")
    accrual = FC.weekly_accrual(rate, weekly_idx)
    expected = 0.02 * 7 / 365
    # First bar has 0.0 (no prev), skip that.
    tail = accrual.iloc[1:]
    err = float((tail - expected).abs().max())
    print(f"[weekly_accrual] expected per-bar {expected:.6e}  "
          f"max err {err:.6e}")
    assert err < 1e-9, f"weekly_accrual mismatch: max err {err}"
    print("  ✓ pass (< 1e-9)")


# ---------------------------------------------------------------------- #
def main() -> None:
    print("=== M1 sanity checks ===\n")
    test_raw_sharpe_reproduces_finalist()
    print()
    test_excess_sharpe_invariance_under_leverage()
    print()
    test_weekly_accrual_matches_hand_calc()
    print("\n✓ all M1 sanity checks passed")


if __name__ == "__main__":
    main()
