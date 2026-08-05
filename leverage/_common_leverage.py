"""v6/leverage/_common_leverage.py — locked constants for the leverage experiment.

Every number here is a §1 locked decision in ``leverage/PLAN.md``. Tuning any
of these post-signoff invalidates the OOS/stress evidence (see PLAN Non-goals).
"""
from __future__ import annotations

# --- path preamble: expose v6/scripts, v5 helpers, repo root ------------
import sys
from pathlib import Path
_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[2]
sys.path.insert(0, str(_HERE.parents[1] / "scripts"))
sys.path.insert(0, str(_REPO))
# ------------------------------------------------------------------------

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
from _common_v6 import (                                           # noqa: E402
    IN_SAMPLE_END, OOS_START, OOS_END, WEEKS_PER_YEAR, DATA_DIR,
)

# --- leverage knobs (locked) --------------------------------------------
CAP                = 2.0
SIGMA_STAR         = 0.032            # book-level, annualized
SIGMA_STAR_BONDLEG = 0.015            # sanity cell only

POLICY_SHARES_BASE = {"equity": 0.55, "bond_rates": 0.20,
                      "bond_credit": 0.10, "commodity": 0.15}
POLICY_SHARES_EW   = {"equity": 0.25, "bond_rates": 0.25,
                      "bond_credit": 0.25, "commodity": 0.25}

# stress window — opened once for the finalist only
STRESS_START = pd.Timestamp("2025-08-01")
STRESS_END   = pd.Timestamp("2026-07-17")

# transaction cost table (bps per side) — §四.D4 fix
COST_BOND_BP    = 2
COST_NONBOND_BP = 10

# σ_est diagnostic (M0-B) settings
SIGMA_EST_HORIZON_WEEKS  = 4          # forward-realized horizon for truth
SIGMA_EST_DAILY_HALFLIFE = 30         # days, for old M1 daily EWMA
SIGMA_EST_WEEKLY_HALFLIFE = 26        # weeks, for new M1 weekly EWMA
SIGMA_EST_DAILY_WINDOW   = 60         # days, for M2a-style rolling std
SIGMA_EST_NW_LAGS        = 4          # Bartlett lags for HAC
SIGMA_EST_NW_WINDOW      = 52         # weeks

# I/O layout
LEV_DIR              = DATA_DIR / "leverage"
LEV_FUNDING_DIR      = LEV_DIR / "_funding"
LEV_SIGMA_EST_DIR    = LEV_DIR / "_sigma_est_diag"

# baseline finalist (frozen)
FINALIST_DIR = DATA_DIR / "block_two_layer_v6" / "q20_eps030"

# --- static KRD table (PLAN §3 & §7) -----------------------------------
# Approximate key-rate-duration in years for every bond ETF that enters the
# finalist universe's bond_rates or bond_credit blocks. Real KRD is time-
# varying (curve steepening / issuance); PLAN §9 accepts ±0.5 yr error as
# adequate for the disclosure purpose. Values derived from fund-family
# tenor descriptors (10y / 5y / 30y CGB, mid-tenor policy bank, credit
# WAM). Anything not explicitly listed falls back to KRD_DEFAULT_BY_BLOCK.
KRD_DEFAULT_BY_BLOCK: dict[str, float] = {
    "bond_rates":  5.5,       # 中期国债 / 政金 assumption
    "bond_credit": 3.5,       # 信用债 avg WAM
}
KRD_OVERRIDES: dict[str, float] = {
    # rates — long-tenor gov / policy-bank
    "511090.XSHG": 20.0,      # 30年国债 ETF
    "511130.XSHG":  8.0,      # 十年期国债
    "511260.XSHG":  8.0,      # 十年期国债 (华夏)
    "511270.XSHG":  8.0,      # 十年期国开
    # rates — mid tenor
    "511010.XSHG":  5.5,      # 5年期国债
    "511020.XSHG":  4.5,      # 综合债
    "511060.XSHG":  4.5,      # 上证5年地方债
    "511100.XSHG":  4.5,      # 政金
    "511160.XSHG":  4.5,      # 国债
    "511520.XSHG":  4.5,      # 5年地方债
    "511580.XSHG":  4.5,      # 综合债
    "159972.XSHE":  5.0,      # 中期国债 SZ
    # rates — short tenor (Shenzhen 159*)
    "159649.XSHE":  3.0,
    "159650.XSHE":  3.0,
    "159651.XSHE":  3.0,
    "159816.XSHE":  3.0,
    # credit — leave defaults except any known-long ones
}


__all__ = [
    "CAP", "SIGMA_STAR", "SIGMA_STAR_BONDLEG",
    "POLICY_SHARES_BASE", "POLICY_SHARES_EW",
    "STRESS_START", "STRESS_END",
    "COST_BOND_BP", "COST_NONBOND_BP",
    "SIGMA_EST_HORIZON_WEEKS", "SIGMA_EST_DAILY_HALFLIFE",
    "SIGMA_EST_WEEKLY_HALFLIFE", "SIGMA_EST_DAILY_WINDOW",
    "SIGMA_EST_NW_LAGS", "SIGMA_EST_NW_WINDOW",
    "LEV_DIR", "LEV_FUNDING_DIR", "LEV_SIGMA_EST_DIR", "FINALIST_DIR",
    "IN_SAMPLE_END", "OOS_START", "OOS_END", "WEEKS_PER_YEAR", "DATA_DIR",
]
