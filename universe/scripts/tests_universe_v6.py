"""
v6/scripts/tests_universe_v6.py
===============================
Synthetic-panel unit tests for universe_v6.build_membership.

Runs the plan step 1.4 checks:
  (a) a name below the floor never enters,
  (b) a name that crosses the entry floor then drifts into
      [floor_exit, floor_enter) stays in,
  (c) a challenger with < 25% higher ADV does NOT dethrone the incumbent,
  (d) a name delisted mid-panel exits at delist_date, not later.

Run:
    python v6/scripts/tests_universe_v6.py
"""
from __future__ import annotations

import sys
from pathlib import Path
_HERE = Path(__file__).resolve()

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
import universe_v6 as U


# ---------------------------------------------------------------------- #
# Test helpers
# ---------------------------------------------------------------------- #
def _synthetic_catalogue(entries):
    """entries: list of tuples (code, underlying_index, list_date, delist_date, block, name_en)."""
    rows = []
    for c, ix, ld, dd, blk, en in entries:
        rows.append({
            "code": c,
            "underlying_index": ix,
            "list_date": pd.Timestamp(ld),
            "delist_date": pd.Timestamp(dd) if dd else pd.NaT,
            "block": blk,
            "name_en": en,
        })
    df = pd.DataFrame(rows)
    df["list_date"] = pd.to_datetime(df["list_date"])
    df["delist_date"] = pd.to_datetime(df["delist_date"])
    return df


def _constant_panel(daily_idx, codes, value):
    return pd.DataFrame(value, index=daily_idx, columns=codes, dtype=float)


def _weekly_fridays(start, end):
    return pd.date_range(start=start, end=end, freq="W-FRI")


# ---------------------------------------------------------------------- #
def test_below_floor_never_enters():
    """(a) A name whose ADV always sits below ADV_FLOOR_ENTER never enters."""
    daily = pd.date_range("2018-06-01", "2021-12-31", freq="B")
    rebal = _weekly_fridays(daily.min(), daily.max())

    cat = _synthetic_catalogue([
        # eligible: high ADV, seasoned early
        ("A", "IX_A", "2018-01-01", None, "broad_cn", "A"),
        # under floor: ADV = 10m, well below 50m enter
        ("B", "IX_B", "2018-01-01", None, "broad_cn", "B"),
    ])
    codes = cat["code"].tolist()

    px  = _constant_panel(daily, codes, 100.0)
    amt = pd.concat([
        pd.Series(1e9, index=daily, name="A"),   # 1B amount, clears everything
        pd.Series(1e7, index=daily, name="B"),   # 10m, below 50m enter
    ], axis=1)
    aum = _constant_panel(daily, codes, 1e9)     # AUM clears floor for both

    membership, changes = U.build_membership(cat, px, amt, aum, rebal)
    assert not membership["B"].any(), "B should never enter (ADV below floor)"
    assert membership["A"].tail(50).any(), "A should be admitted after seasoning + warmup"


def test_hysteresis_between_exit_and_enter():
    """(b) A name that crosses the entry floor then drifts into (exit, enter) stays in."""
    daily = pd.date_range("2018-06-01", "2022-06-30", freq="B")
    rebal = _weekly_fridays(daily.min(), daily.max())

    cat = _synthetic_catalogue([
        ("A", "IX_A", "2018-01-01", None, "broad_cn", "A"),
        ("H", "IX_H", "2018-01-01", None, "broad_cn", "H"),
    ])
    codes = cat["code"].tolist()
    px  = _constant_panel(daily, codes, 100.0)

    # H starts at 100m (above 50m enter), then drops to 40m (between 25m exit
    # and 50m enter) after 2020-01-01. Should STAY in per hysteresis.
    amt_H = pd.Series(1e8, index=daily, name="H")
    amt_H.loc["2020-01-01":] = 4e7
    amt_A = pd.Series(1e9, index=daily, name="A")
    amt = pd.concat([amt_A, amt_H], axis=1)
    aum = _constant_panel(daily, codes, 1e9)

    membership, _ = U.build_membership(cat, px, amt, aum, rebal)
    # After the drop, H should still be a member (hysteresis)
    after = membership.loc[membership.index >= "2020-06-01", "H"]
    assert after.any(), "H should stay in after ADV drift to [exit, enter)"


def test_dedup_25pct_margin_holds():
    """(c) A challenger with < 25% higher ADV does NOT dethrone the incumbent."""
    daily = pd.date_range("2018-06-01", "2022-06-30", freq="B")
    rebal = _weekly_fridays(daily.min(), daily.max())

    cat = _synthetic_catalogue([
        ("INC", "IX_SAME", "2018-01-01", None, "broad_cn", "incumbent"),
        ("CH",  "IX_SAME", "2018-01-01", None, "broad_cn", "challenger"),
        ("X",   "IX_X",    "2018-01-01", None, "broad_cn", "other"),  # third to make percentile stable
    ])
    codes = cat["code"].tolist()
    px  = _constant_panel(daily, codes, 100.0)

    # INC starts high (100m) so it wins on cold start; CH starts lower
    # (80m). Then CH rises to 108m (only 8% margin) → INC must hold. From
    # 2020-06-01, CH jumps to 140m (40% margin) → CH takes over.
    amt_inc = pd.Series(1e8, index=daily, name="INC")
    amt_ch  = pd.Series(0.8e8, index=daily, name="CH")
    amt_ch.loc["2019-01-01":"2020-05-31"] = 1.08e8   # 8% > INC, insufficient
    amt_ch.loc["2020-06-01":]              = 1.4e8   # 40% > INC, dethrones
    amt_x   = pd.Series(2e9, index=daily, name="X")
    amt = pd.concat([amt_inc, amt_ch, amt_x], axis=1)
    aum = _constant_panel(daily, codes, 1e9)

    membership, _ = U.build_membership(cat, px, amt, aum, rebal)
    # Sample a date where the margin is < 25% — INC should be the representative
    early = membership.loc["2019-09-01":"2020-05-01", ["INC", "CH"]]
    # INC should hold representative status for most of that window
    inc_share = early["INC"].mean()
    ch_share  = early["CH"].mean()
    assert inc_share > 0.9, f"INC lost representative status too early: inc={inc_share:.2f} ch={ch_share:.2f}"

    # After 2020-06-01 with 40% margin, CH takes over
    late = membership.loc["2020-09-01":"2021-06-30", ["INC", "CH"]]
    assert late["CH"].mean() > 0.5, \
        f"CH should dominate after >25% ADV lead: inc={late['INC'].mean():.2f} ch={late['CH'].mean():.2f}"


def test_delist_removes_at_delist_date():
    """(d) A name delisted mid-panel exits at delist_date, not later."""
    daily = pd.date_range("2018-06-01", "2022-06-30", freq="B")
    rebal = _weekly_fridays(daily.min(), daily.max())

    delist = "2020-06-15"
    cat = _synthetic_catalogue([
        ("A", "IX_A", "2018-01-01", None, "broad_cn", "A"),
        ("D", "IX_D", "2018-01-01", delist, "broad_cn", "delisted"),
    ])
    codes = cat["code"].tolist()
    px  = _constant_panel(daily, codes, 100.0)
    amt = _constant_panel(daily, codes, 1e9)   # both easily clear ADV
    aum = _constant_panel(daily, codes, 1e9)

    membership, changes = U.build_membership(cat, px, amt, aum, rebal)
    # After delist_date, D must be False on every subsequent weekly bar
    post = membership.loc[membership.index >= delist, "D"]
    assert not post.any(), f"D should be out on/after delist_date; found {int(post.sum())} True bars"
    # Before delist_date, D was in
    pre_windowed = membership.loc[(membership.index >= "2019-06-01") &
                                  (membership.index <  delist), "D"]
    assert pre_windowed.any(), "D should have been in prior to delist"


# ---------------------------------------------------------------------- #
def main():
    tests = [
        test_below_floor_never_enters,
        test_hysteresis_between_exit_and_enter,
        test_dedup_25pct_margin_holds,
        test_delist_removes_at_delist_date,
    ]
    n_pass = 0
    n_fail = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            n_pass += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            n_fail += 1
        except Exception as e:
            print(f"  ERR   {fn.__name__}: {type(e).__name__}: {e}")
            n_fail += 1
    print(f"\n{n_pass}/{len(tests)} passed")
    if n_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
