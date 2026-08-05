"""
v6/scripts/block_risk_budget_v6.py
==================================
Phase 12 layer-1 — block-level risk budgeting + 10-month trend gate,
tested standalone (**no α layer inside blocks**).

Purpose. The user's Phase 12 spec (see IMPLEMENTATION_PLAN.md, frozen
2026-07-22) puts the top-of-stack decision on *how much of the book each
block earns*, driven by:

  1. A policy risk-contribution budget across four block groups
     (equity 55 %, bond_rates 20 %, bond_credit 10 %, commodity 15 %).
  2. A trend-gate overlay: below the 10-month MA of the block's own
     price index, the block's risk share rolls to cash (not
     redistributed to on-trend blocks).
  3. Estimator: rolling 52 W covariance across block sub-portfolios,
     Schäfer-Strimmer 2005 target-D shrinkage toward diag(S) (preserves
     per-block variance; only correlations get shrunk toward 0).

This branch tests the *first layer only*, i.e. what happens if we drop
the alpha selection layer entirely and just do block-level risk
budgeting with block-internal sizing (eqw or invvol) on the members.
Compares against the v6 anchors (solo defensive from Phase 11.2, T1/T2
bond books from `bond_attribution_v6`).

Two intra-block sizings × two budget solvers = 4 variants per run:

  intra_sizing ∈ {eqw, invvol}                     (Phase 12 open knob)
  budget       ∈ {naive, lw_erc}                   (naive = w ∝ √p / σ_b;
                                                    lw_erc = ERC on
                                                    shrunk-cov target-D)

Both are run because user requested parallel reports on all four cells;
per-block hysteresis and q=0.20/0.10 alpha overlays are deferred to
later branches (see IMPLEMENTATION_PLAN.md §Phase 12).

Weighting rule when trend gate is OFF for a block (per user
2026-07-22): released mass → cash, other blocks' weights unchanged.
`Σ w_b = 1` when all blocks ON; ON blocks may drift on realized RC%
vs policy when others are gated OFF (spec's "±10 pp soft float"
language; reported as diagnostic).

Windows:
  cov window       : 52 W
  trend MA window  : 43 W (≈ 10 months × 52/12)
  warmup           : max(52, 43) = 52 W; book flat before that.

Cost 10 bp/side, IS-only summaries (bars ≤ IN_SAMPLE_END). OOS stays
sealed per [[feedback-oos-discipline]].

Outputs
-------
    data/block_risk_budget_v6/{sizing}_{budget}/{
        w_group.parquet, w_name.parquet,
        net_ret.csv, summary.csv,
        trend_gate.parquet, realized_rc.parquet
    }
    reports/block_risk_budget_v6_report.md

Run
---
    python v6/scripts/block_risk_budget_v6.py
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.optimize import minimize

import _common_v6 as C
import xs_engine_v6 as E
import block_composite_v6 as BC


# ---------------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------------- #
POLICY_SHARES: dict[str, float] = {
    "equity":      0.55,
    "bond_rates":  0.20,
    "bond_credit": 0.10,
    "commodity":   0.15,
}
GROUPS = BC.GROUP_ORDER          # canonical order for arrays

WINDOW_COV   = 52     # weekly bars for rolling cov / std estimator
WINDOW_MA    = 43     # weekly bars ≈ 10 months for trend MA
WARMUP_BARS  = max(WINDOW_COV, WINDOW_MA)
COV_MIN_OBS  = 26     # min non-NaN obs per group in the cov window to
                      # include that group in the budget solve

COST         = E.DEFAULT_COST_PER_TRADE
OUT_ROOT     = C.DATA_DIR / "block_risk_budget_v6"

BUDGET_METHODS = ("naive", "lw_erc")


# ---------------------------------------------------------------------- #
# Ledoit-Wolf shrinkage — closed form, small N
# ---------------------------------------------------------------------- #
def ledoit_wolf_cov(R: np.ndarray) -> tuple[np.ndarray, float]:
    """Shrink sample cov toward its own diagonal (Schäfer & Strimmer 2005
    target-D). Preserves per-asset variance, shrinks only off-diagonal
    covariances (equivalently, correlations) toward zero.

    Chosen over LW's Tr(S)/N · I because on this pool the four block
    variances span an order of magnitude (equity σ ~17 %, bond ~2 %,
    commodity ~12 %); an equal-variance target pulls bond variance up
    ~30× and equity down, which biases the risk-budget solver against
    equity (misreads it as no more risky than bonds under high
    shrinkage). Preserving diag(S) keeps the per-block risk estimate
    honest and only regularizes the noisy off-diagonal terms.

    Optimal shrinkage intensity for target F = diag(S)
    (Schäfer & Strimmer 2005, eq. 7 — target D):

        α* = Σ_{i≠j} Var̂(s_ij) / Σ_{i≠j} s_ij²

    with Var̂(s_ij) = (1/T²) Σ_t (Xc[t,i]·Xc[t,j] − s_ij)². Diagonal
    contributions drop out of both sums (s_ii = f_ii by construction),
    so the diagonal is untouched regardless of α.

    R : T×N array of returns; NaN rows dropped (pairwise-complete cov
    is a can of worms on N=4). Returns (Sigma_shrunk, α ∈ [0, 1]).
    """
    R = np.asarray(R, dtype=float)
    mask = np.all(np.isfinite(R), axis=1)
    R = R[mask]
    T, N = R.shape
    if T < 2:
        return np.eye(N), 1.0
    Xc = R - R.mean(axis=0, keepdims=True)
    S  = (Xc.T @ Xc) / (T - 1)
    F  = np.diag(np.diag(S))                     # target-D

    # Off-diagonal variance estimates; diagonal set to 0 so it drops
    # out of the sums below.
    pi_bar = np.zeros((N, N), dtype=float)
    for i in range(N):
        for j in range(N):
            if i == j:
                continue
            pi_bar[i, j] = np.mean((Xc[:, i] * Xc[:, j] - S[i, j]) ** 2)
    pi_off = float(pi_bar.sum())
    d_off  = float(((S - F) ** 2).sum())          # = Σ_{i≠j} s_ij²
    if d_off <= 0.0:
        alpha = 1.0
    else:
        alpha = max(0.0, min(1.0, (pi_off / T) / d_off))
    return (1.0 - alpha) * S + alpha * F, alpha


# ---------------------------------------------------------------------- #
# Budget solvers
# ---------------------------------------------------------------------- #
def solve_naive(cov: np.ndarray, target_shares: np.ndarray) -> np.ndarray:
    """Closed-form ERC under diagonal cov.

    Under diagonal Σ, block b's risk contribution is RC_b = w_b² σ_b².
    Requiring RC_b ∝ target_b gives w_b² σ_b² = c · target_b, i.e.

        w_b ∝ √target_b / σ_b

    (NOT w_b ∝ target_b / σ_b — that variant delivers RC_b ∝ target_b²
    and was a bug in the first draft of this module, caught 2026-07-22
    when the no-trend §3 diagnostic showed realized RC = policy²/Σpolicy²
    instead of policy on the naive solver.)
    """
    sigma_b = np.sqrt(np.maximum(np.diag(cov), 1e-16))
    p = np.asarray(target_shares, dtype=float)
    raw = np.sqrt(np.maximum(p, 0.0)) / sigma_b
    s = float(raw.sum())
    return raw / s if s > 0 else np.zeros_like(raw)


def solve_lw_erc(cov: np.ndarray, target_shares: np.ndarray) -> np.ndarray:
    """Policy-weighted risk-parity via log-barrier convex program.

        min_w  0.5 · w' Σ w  −  Σ_b p_b · log(w_b)      s.t. w > 0

    FOC → w_b · (Σw)_b = p_b · const, i.e. RC%_b = p_b. Solution scaled
    to Σ w = 1.
    """
    p = np.asarray(target_shares, dtype=float)
    p = p / p.sum()
    B = len(p)

    def obj(w: np.ndarray) -> float:
        var = float(w @ cov @ w)
        w_safe = np.maximum(w, 1e-14)
        return 0.5 * var - float(np.dot(p, np.log(w_safe)))

    def grad(w: np.ndarray) -> np.ndarray:
        return cov @ w - p / np.maximum(w, 1e-14)

    # naive as warm-start — cheap and already in the right neighborhood
    w0 = solve_naive(cov, p)
    if not np.all(w0 > 0):
        w0 = np.full(B, 1.0 / B)
    res = minimize(obj, w0, jac=grad, method="L-BFGS-B",
                   bounds=[(1e-8, None)] * B,
                   options={"maxiter": 200, "ftol": 1e-12, "gtol": 1e-10})
    w = np.asarray(res.x, dtype=float)
    s = float(w.sum())
    return w / s if s > 0 else np.zeros_like(w)


def realized_rc_shares(w: np.ndarray, cov: np.ndarray) -> np.ndarray:
    """Realized risk-contribution shares (sum to 1) given weights + cov."""
    w = np.asarray(w, dtype=float)
    port_var = float(w @ cov @ w)
    if port_var <= 0:
        return np.zeros_like(w)
    return (w * (cov @ w)) / port_var


# ---------------------------------------------------------------------- #
# Trend gate — causal 10-month MA of the block's own composite NAV
# ---------------------------------------------------------------------- #
def compute_trend_gate(nav: pd.DataFrame,
                       window: int = WINDOW_MA) -> pd.DataFrame:
    """Per (t, group) boolean: 1 iff causal_nav_g[t] > MA_window(causal_nav_g)[t].

    NAV built by ``block_composite_v6`` is forward-return-based: NAV[t]
    incorporates R[t] = fwd_1w[t] which is not yet known at rebal bar t.
    Shift by one bar to make the trend signal strictly causal (weights
    set at t depend only on NAV[t-1] and earlier).

    Bars with NaN NAV (group flat / warmup) return NaN — treat NaN as
    "gate ON" downstream so the group is included whenever it has a
    valid composite return, even if the trend indicator is still
    warming up.
    """
    causal_nav = nav.shift(1)
    ma = causal_nav.rolling(window, min_periods=window).mean()
    gate = (causal_nav > ma)
    # Preserve NaN in warmup / flat bars — cast to nullable boolean.
    return gate.where(causal_nav.notna() & ma.notna())


# ---------------------------------------------------------------------- #
# Rolling budget builder
# ---------------------------------------------------------------------- #
def build_block_weights(R: pd.DataFrame,
                        trend_gate: pd.DataFrame,
                        budget_method: str,
                        policy_shares: dict[str, float],
                        window_cov: int = WINDOW_COV,
                        cov_min_obs: int = COV_MIN_OBS,
                        ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Per-bar block weights + realized RC% + effective cov diagnostics.

    Parameters
    ----------
    R : T×G weekly return panel of block composites.
    trend_gate : T×G boolean; None / NaN treated as ON.
    budget_method : "naive" or "lw_erc".
    policy_shares : dict group → policy risk share.

    Returns
    -------
    W_group : T×G block weight panel (Σ w ≤ 1; cash = 1 − Σ w).
    RC_pct  : T×G realized RC-share panel among invested blocks
              (NaN when book flat that bar).
    diag    : T-index frame with `port_vol_est`, `n_active_groups`,
              `lw_alpha` (mean shrinkage across bars for lw_erc,
              NaN for naive).
    """
    if budget_method not in BUDGET_METHODS:
        raise ValueError(f"budget_method must be {BUDGET_METHODS}, got {budget_method!r}")
    groups = list(R.columns)
    p_vec = np.array([policy_shares[g] for g in groups], dtype=float)

    T = len(R)
    G = len(groups)
    W = np.zeros((T, G), dtype=float)
    RC = np.full((T, G), np.nan, dtype=float)
    port_vol = np.full(T, np.nan, dtype=float)
    n_act = np.zeros(T, dtype=int)
    lw_a = np.full(T, np.nan, dtype=float)

    R_arr = R.to_numpy(dtype=float)
    gate_arr = trend_gate.to_numpy() if trend_gate is not None else None

    for t in range(T):
        if t < WARMUP_BARS:
            continue
        # Causal window: [t-window_cov, t) — 52 bars strictly before t.
        w_lo = max(0, t - window_cov)
        Rw = R_arr[w_lo:t, :]                              # (≤52, G)
        # Per-group observation count in window
        obs = np.sum(np.isfinite(Rw), axis=0)
        include = obs >= cov_min_obs
        if not include.any():
            continue
        Rw_use = Rw[:, include]
        # Drop rows with any NaN in the included subset for cov estimation
        row_ok = np.all(np.isfinite(Rw_use), axis=1)
        if int(row_ok.sum()) < cov_min_obs:
            # Fallback: per-column std (diagonal only) — mirrors naive
            # solver's behavior when full-rank cov isn't available.
            std_col = np.nanstd(Rw_use, axis=0, ddof=1)
            cov_use = np.diag(std_col ** 2)
            alpha = np.nan
        else:
            R_use = Rw_use[row_ok, :]
            if budget_method == "naive":
                std_col = R_use.std(axis=0, ddof=1)
                cov_use = np.diag(std_col ** 2)
                alpha = np.nan
            else:
                cov_use, alpha = ledoit_wolf_cov(R_use)
        # Solve
        if budget_method == "naive":
            w_use = solve_naive(cov_use, p_vec[include])
        else:
            w_use = solve_lw_erc(cov_use, p_vec[include])

        # Expand back to full G
        w_full = np.zeros(G, dtype=float)
        w_full[include] = w_use

        # Apply trend gate — OFF -> 0, released mass to cash
        if gate_arr is not None:
            gate_t = gate_arr[t]
            for gi in range(G):
                g_ok = gate_t[gi]
                # Treat NaN as ON (warmup fallback)
                if g_ok is False:                          # explicit False
                    w_full[gi] = 0.0

        W[t, :] = w_full

        # Diagnostics — realized RC% using the estimated cov (on the
        # included subset) and the applied weights (restricted to same
        # subset). Bars where sum(w)==0 leave RC NaN.
        if w_full.sum() > 0:
            w_sub = w_full[include]
            pv = float(w_sub @ cov_use @ w_sub)
            if pv > 0:
                rc_sub = (w_sub * (cov_use @ w_sub)) / pv
                # Renormalize by total-weight-share to stay comparable
                # across bars when cash is present (RC% shown is of the
                # invested part).
                rc_full = np.full(G, np.nan, dtype=float)
                rc_full[include] = rc_sub
                RC[t, :] = rc_full
                port_vol[t] = float(np.sqrt(pv) * np.sqrt(C.WEEKS_PER_YEAR))
        n_act[t] = int((w_full > 0).sum())
        lw_a[t]  = alpha

    idx = R.index
    W_df  = pd.DataFrame(W, index=idx, columns=groups)
    RC_df = pd.DataFrame(RC, index=idx, columns=groups)
    diag  = pd.DataFrame({
        "port_vol_est":     port_vol,
        "n_active_groups":  n_act,
        "lw_alpha":         lw_a,
    }, index=idx)
    return W_df, RC_df, diag


# ---------------------------------------------------------------------- #
# Aggregate to name-level weights + backtest
# ---------------------------------------------------------------------- #
def aggregate_to_names(W_group: pd.DataFrame,
                       within: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """W_name[t, i] = W_group[t, g(i)] × W_within_g(i)[t, i].

    Groups are disjoint (each code in at most one group), so no summation
    across groups is needed at the name level. Concatenate the per-group
    frames column-wise and reindex to a common name index.
    """
    frames = []
    for g in W_group.columns:
        Wg = within[g]
        if Wg.shape[1] == 0:
            continue
        scale = W_group[g].reindex(Wg.index).fillna(0.0)
        frames.append(Wg.mul(scale, axis=0))
    if not frames:
        return pd.DataFrame(index=W_group.index)
    W_name = pd.concat(frames, axis=1)
    return W_name


# ---------------------------------------------------------------------- #
# One-variant runner
# ---------------------------------------------------------------------- #
def _fmt(x, d=3): return f"{x:+.{d}f}" if pd.notna(x) else "   —"
def _fmt_pct(x, d=2): return f"{x*100:+.{d}f}%" if pd.notna(x) else "     —"


def run_variant(shared: dict,
                intra_sizing: str,
                budget_method: str,
                use_trend: bool = True,
                policy_shares: dict[str, float] = POLICY_SHARES) -> dict:
    """Build → solve → gate → aggregate → backtest → return everything."""
    composites = BC.build_composites(shared, sizings=(intra_sizing,))[intra_sizing]
    R    = composites["returns"][list(GROUPS)]
    NAV  = composites["nav"][list(GROUPS)]
    within = composites["weights"]

    trend = compute_trend_gate(NAV) if use_trend else pd.DataFrame(True, index=R.index,
                                                                    columns=R.columns)

    W_group, RC_pct, diag = build_block_weights(
        R, trend, budget_method, policy_shares,
    )

    W_name = aggregate_to_names(W_group, within)
    fwd    = shared["fwd_1w"].reindex(columns=W_name.columns).fillna(0.0)

    # N_t / K_t = per-bar count of non-zero name weights, for the summary
    K_t = (W_name.abs() > 0).sum(axis=1).astype(int)
    res = E.run_book(W_name, fwd, cost_per_trade=COST,
                     N_t=K_t.rename("N_t"), K_t=K_t.rename("K_t"))
    summ = E.summarize_book(res)

    # Cash share = 1 - Σ w_group
    cash = (1.0 - W_group.sum(axis=1)).clip(lower=0.0)

    return {"intra_sizing": intra_sizing, "budget": budget_method,
            "R_group": R, "NAV_group": NAV, "trend_gate": trend,
            "W_group": W_group, "RC_pct": RC_pct, "diag": diag,
            "W_name": W_name, "cash": cash,
            "res": res, "summary": summ}


# ---------------------------------------------------------------------- #
# Persistence
# ---------------------------------------------------------------------- #
def persist_variant(bundle: dict, out_root: Path = OUT_ROOT) -> Path:
    tag = f"{bundle['intra_sizing']}_{bundle['budget']}"
    d = out_root / tag
    d.mkdir(parents=True, exist_ok=True)
    bundle["W_group"].to_parquet(d / "w_group.parquet")
    bundle["W_name"].to_parquet(d / "w_name.parquet")
    bundle["res"].net_ret.to_frame("net_ret").to_csv(d / "net_ret.csv")
    bundle["trend_gate"].to_parquet(d / "trend_gate.parquet")
    bundle["RC_pct"].to_parquet(d / "realized_rc.parquet")
    bundle["diag"].to_csv(d / "diag.csv")
    # summary CSV — one row
    s = bundle["summary"]
    pd.DataFrame([{
        "intra_sizing": bundle["intra_sizing"],
        "budget":       bundle["budget"],
        "is_sharpe":    s.is_sharpe,   "oos_sharpe":  s.oos_sharpe,
        "is_cagr":      s.is_cagr,     "oos_cagr":    s.oos_cagr,
        "is_max_dd":    s.is_max_dd,   "oos_max_dd":  s.oos_max_dd,
        "annual_vol":   s.annual_vol,  "avg_turnover": s.avg_turnover,
        "mean_K":       s.mean_K,      "is_bars":     s.is_bars,
    }]).to_csv(d / "summary.csv", index=False)
    return d


# ---------------------------------------------------------------------- #
# Report
# ---------------------------------------------------------------------- #
def _is_slice(s: pd.Series) -> pd.Series:
    return s[s.index <= C.IN_SAMPLE_END]


def _per_year(net: pd.Series) -> pd.DataFrame:
    s = _is_slice(net).copy()
    if s.empty:
        return pd.DataFrame(columns=["year", "ret", "sharpe", "max_dd"])
    df = s.to_frame("r"); df["year"] = df.index.year
    rows = []
    for y, g in df.groupby("year"):
        r = g["r"]
        rows.append({
            "year":   int(y),
            "ret":    float(r.sum()),
            "sharpe": float(r.mean() / r.std(ddof=1) * np.sqrt(C.WEEKS_PER_YEAR))
                        if r.std(ddof=1) > 0 else np.nan,
            "max_dd": float(((1 + r.cumsum()) - (1 + r.cumsum()).cummax()).min()),
        })
    return pd.DataFrame(rows)


def _trend_diag(gate: pd.DataFrame) -> pd.DataFrame:
    """Per-group %ON among post-warmup bars (excluding NaN)."""
    rows = []
    for g in gate.columns:
        s = gate[g].dropna()
        if s.empty:
            rows.append({"group": g, "n_bars": 0, "pct_on": np.nan,
                         "n_switches": 0})
        else:
            switches = int((s.astype(int).diff().abs() > 0).sum())
            rows.append({"group": g, "n_bars": int(len(s)),
                         "pct_on": float(s.mean()),
                         "n_switches": switches})
    return pd.DataFrame(rows)


def _mean_realized_rc(rc: pd.DataFrame) -> pd.Series:
    """Mean realized RC-share across IS bars where the book is invested."""
    is_rc = rc.loc[rc.index <= C.IN_SAMPLE_END]
    mask = is_rc.notna().any(axis=1)
    return is_rc.loc[mask].mean(axis=0)


def _all_on_realized_rc(rc: pd.DataFrame, gate: pd.DataFrame) -> pd.Series:
    """RC-share averaged over IS bars where **every** group is trend-ON.

    Isolates the solver's delivered RC from the gate-averaging drag —
    when all four blocks are ON, no cross-block renormalization happens
    and the number is what the risk-budget solver actually targets.
    """
    is_end = C.IN_SAMPLE_END
    idx = rc.index[rc.index <= is_end]
    all_on = gate.reindex(idx).fillna(True).all(axis=1)
    if not bool(all_on.any()):
        return pd.Series(np.nan, index=rc.columns)
    return rc.loc[idx].loc[all_on].mean(axis=0)


def write_report(variants: list[dict], anchors: dict, report_path: Path) -> None:
    lines: list[str] = []
    lines.append("# Phase 12 layer-1 — block risk budgeting + trend gate "
                 "(standalone, no α)\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    lines.append(
        "Standalone contribution of the *first layer* on the v6 pool: "
        "block-level risk budgeting with the frozen Phase 12 policy shares, "
        "10-month MA trend gate → cash, no within-block α selection "
        "(block-internal eqw or invvol on all eligible members).\n\n"
        f"Cost {COST*10000:.0f} bp/side. IS = bars ≤ {C.IN_SAMPLE_END.date()}. "
        f"Cov window {WINDOW_COV}w; trend MA {WINDOW_MA}w. Warmup "
        f"{WARMUP_BARS} bars (book flat).\n\n"
        "**Policy risk shares** (Phase 12 spec, frozen 2026-07-22):\n"
        f"- equity (broad_cn + sector_cn + cross_border_dm + cross_border_hk, "
        f"smallcap merged): {POLICY_SHARES['equity']*100:.0f} %\n"
        f"- bond_rates : {POLICY_SHARES['bond_rates']*100:.0f} %\n"
        f"- bond_credit: {POLICY_SHARES['bond_credit']*100:.0f} %\n"
        f"- commodity (metals + commodity_other): "
        f"{POLICY_SHARES['commodity']*100:.0f} %\n\n"
        "Two intra-block sizings × two budget solvers → 4 variants. Per user "
        "2026-07-22, intra-block sizing (eqw vs invvol) and block-level "
        "hysteresis are open knobs — this branch reports both intra choices "
        "in parallel and leaves hysteresis for a follow-up.\n\n"
        "*Solvers.* `naive` = **w_b ∝ √policy_b / σ_b** (closed-form ERC "
        "under diagonal cov; delivers RC_b ∝ policy_b exactly when Σ is "
        "diagonal). `lw_erc` = policy-weighted risk parity via log-barrier "
        "on the shrunk 4×4 cov; **shrinkage target = diag(S)** "
        "(Schäfer & Strimmer 2005 target-D), which preserves per-block "
        "variance and only regularizes off-diagonal terms — avoids the "
        "distortion an equal-variance target (Tr(S)/N · I) would inflict "
        "on this pool where block σ spans an order of magnitude.\n\n"
        "*Trend gate.* Per group, 1 iff causal composite NAV > 43-week MA "
        "of the same. OFF → block weight 0, released mass to cash (no "
        "redistribution to on-trend blocks).\n\n"
    )

    # --- §1: headline ---------------------------------------------------
    lines.append("## 1. IS headline\n")
    lines.append("| variant | IS Sharpe | IS CAGR | IS max DD | IS ann vol | "
                 "avg turnover | mean K | cash share |")
    lines.append("|:---|---:|---:|---:|---:|---:|---:|---:|")
    for v in variants:
        s = v["summary"]
        tag = f"{v['intra_sizing']} × {v['budget']}"
        cash_share = float(_is_slice(v["cash"]).mean())
        lines.append(
            f"| {tag} | {_fmt(s.is_sharpe)} | {_fmt_pct(s.is_cagr)} | "
            f"{_fmt_pct(s.is_max_dd)} | {_fmt_pct(s.annual_vol)} | "
            f"{s.avg_turnover:.3f} | {s.mean_K:.1f} | "
            f"{cash_share*100:.1f}% |"
        )
    lines.append("")

    # --- §2: anchors ---------------------------------------------------
    lines.append("## 2. Comparison anchors (from prior work)\n")
    lines.append("| anchor | IS Sharpe | IS CAGR | IS max DD | source |")
    lines.append("|:---|---:|---:|---:|:---|")
    for name, a in anchors.items():
        if not isinstance(a, dict):
            continue                       # skip raw return-series entries
        lines.append(
            f"| {name} | {_fmt(a['sharpe'])} | {_fmt_pct(a['cagr'])} | "
            f"{_fmt_pct(a['max_dd'])} | {a['source']} |"
        )
    lines.append("")

    # --- §3: mean realized RC% + trend on% ------------------------------
    lines.append("## 3. Mean realized RC-share (IS)\n")
    lines.append(
        "Two views. **§3a** takes the mean over IS bars where *every* "
        "block group is trend-ON — no cross-block renormalization, so "
        "the number is what the risk-budget solver actually delivers. "
        "**§3b** averages over all invested IS bars (including bars where "
        "some groups are gated OFF): remaining ON blocks' RC%s "
        "renormalize to 1 each bar, so equity RC gets diluted below "
        "policy on bars where equity is OFF. §3a is the direct check on "
        "the solver; §3b shows what the book looks like in practice.\n\n"
    )

    lines.append("### 3a. Solver-delivered RC (bars where all 4 groups ON)\n")
    lines.append("| variant | " + " | ".join(GROUPS) + " | n bars |")
    lines.append("|:---|" + "|".join(["---:"] * len(GROUPS)) + "|---:|")
    row = ["**policy**"] + [f"**{POLICY_SHARES[g]*100:5.1f}%**" for g in GROUPS] + ["—"]
    lines.append("| " + " | ".join(row) + " |")
    for v in variants:
        rc_on = _all_on_realized_rc(v["RC_pct"], v["trend_gate"])
        gate = v["trend_gate"].loc[v["trend_gate"].index <= C.IN_SAMPLE_END]
        n_all_on = int(gate.fillna(True).all(axis=1).sum())
        cells = [f"{v['intra_sizing']} × {v['budget']}"]
        for g in GROUPS:
            val = rc_on.get(g, np.nan)
            cells.append(f"{val*100:5.1f}%" if pd.notna(val) else "  —")
        cells.append(str(n_all_on))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("### 3b. Mean RC over all invested IS bars (gate-averaged)\n")
    lines.append("| variant | " + " | ".join(GROUPS) + " |")
    lines.append("|:---|" + "|".join(["---:"] * len(GROUPS)) + "|")
    row = ["policy"] + [f"{POLICY_SHARES[g]*100:5.1f}%" for g in GROUPS]
    lines.append("| " + " | ".join(row) + " |")
    for v in variants:
        rc = _mean_realized_rc(v["RC_pct"])
        cells = [f"{v['intra_sizing']} × {v['budget']}"]
        for g in GROUPS:
            val = rc.get(g, np.nan)
            cells.append(f"{val*100:5.1f}%" if pd.notna(val) else "  —")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## 4. Trend-gate % ON per group (IS, post-warmup)\n")
    lines.append("| variant | " + " | ".join(GROUPS) +
                 " | mean n_switches |")
    lines.append("|:---|" + "|".join(["---:"] * len(GROUPS)) +
                 "|---:|")
    for v in variants:
        td = _trend_diag(v["trend_gate"].loc[v["trend_gate"].index <= C.IN_SAMPLE_END])
        cells = [f"{v['intra_sizing']} × {v['budget']}"]
        for g in GROUPS:
            row = td[td["group"] == g]
            if row.empty:
                cells.append("  —")
            else:
                cells.append(f"{float(row['pct_on'].iloc[0])*100:5.1f}%")
        cells.append(f"{td['n_switches'].mean():.1f}")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    # --- §5: per-year returns ------------------------------------------
    lines.append("## 5. Per-calendar-year IS return (sum of weekly net)\n")
    per_years = {f"{v['intra_sizing']} × {v['budget']}":
                 _per_year(v["res"].net_ret) for v in variants}
    years = sorted({int(y) for df in per_years.values() for y in df["year"]})
    cols = list(per_years.keys())
    lines.append("| year | " + " | ".join(cols) + " |")
    lines.append("|:---:|" + "|".join(["---:"] * len(cols)) + "|")
    for y in years:
        row = [f"| {y}"]
        for c in cols:
            py = per_years[c]
            v = py.loc[py["year"] == y, "ret"]
            row.append(_fmt_pct(float(v.iloc[0])) if len(v) else "     —")
        lines.append(" | ".join(row) + " |")
    lines.append("")

    # --- §6: correlation of the 4 variants + solo defensive ------------
    lines.append("## 6. IS weekly-return correlation across variants\n")
    ret_frame = pd.DataFrame({f"{v['intra_sizing']}×{v['budget']}":
                              _is_slice(v["res"].net_ret) for v in variants})
    if "solo_defensive_net" in anchors:
        ret_frame["solo_defensive"] = _is_slice(anchors["solo_defensive_net"])
    corr = ret_frame.corr()
    lines.append("| | " + " | ".join(corr.columns) + " |")
    lines.append("|:---|" + "|".join(["---:"] * len(corr.columns)) + "|")
    for i in corr.index:
        row = [f"| {i}"]
        for c in corr.columns:
            row.append(f" {corr.loc[i, c]:+.3f} ")
        lines.append(" | ".join(row) + " |")
    lines.append("")

    lines.append("## 7. Read\n")
    lines.append(
        "Standalone layer-1 numbers say how much of the v6 book value the "
        "risk-budget + trend gate alone earns before any within-block α "
        "layer is added. Compare against:\n"
        "- **solo defensive** (Phase 11.2 finalist) — the current production "
        "  book, which selects top-⌈0.20 · N_t⌉ α names pool-wide with 1/σ "
        "  sizing and no explicit block budget.\n"
        "- **T2 bond_invvol** — the highest IS-Sharpe passive slice of the "
        "  pool (bond blocks, inv-vol), i.e. what the alpha stack is "
        "  competing with on Sharpe.\n"
        "- **T1 universe_invvol** — hold everything, inv-vol; the "
        "  all-in passive benchmark.\n\n"
        "**Open knobs (deferred, per user 2026-07-22):**\n"
        "- intra-block sizing (eqw vs invvol) reported in parallel here; "
        "  choose in a follow-up branch once layer-1 semantics are locked.\n"
        "- block-level hysteresis (ε) not applied — trend gate flips are "
        "  raw. Sweep ε ∈ {0, 0.10, 0.20, 0.30} in a follow-up.\n"
        "- q = 0.20 / 0.10 within-block α overlays are Phase 13 territory "
        "  and get their own parallel branch.\n"
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {report_path}")


# ---------------------------------------------------------------------- #
# Anchor loaders
# ---------------------------------------------------------------------- #
def load_anchors(data_dir: Path = C.DATA_DIR) -> dict:
    """Pull IS Sharpe/CAGR/DD for the v6 comparison points."""
    out = {}
    # Solo defensive (Phase 11.2 finalist) — long_q20 replace ε=0.20 inv_vol
    solo = data_dir / "v6_static" / "long_q20" / "ensemble_net_ret.csv"
    if solo.exists():
        s = pd.read_csv(solo, parse_dates=[0], index_col=0).iloc[:, 0]
        out["solo_defensive_net"] = s
        is_s = s.loc[s.index <= C.IN_SAMPLE_END]
        av = float(is_s.std(ddof=1)) * np.sqrt(C.WEEKS_PER_YEAR)
        ar = float(is_s.mean()) * C.WEEKS_PER_YEAR
        cum = float(is_s.sum()); nav = 1 + is_s.cumsum()
        out["solo_defensive"] = {
            "sharpe": ar / av if av > 0 else np.nan,
            "cagr":   max(1 + cum, 1e-9) ** (1 / max(len(is_s) / C.WEEKS_PER_YEAR, 1e-3)) - 1,
            "max_dd": float(((nav - nav.cummax()) / nav.cummax()).min()),
            "source": "v6_static/long_q20/ensemble_net_ret.csv (Phase 11.2)",
        }
    # bond_attribution T1 / T2 / T3
    for tag, label, source in (
        ("T1_universe_invvol", "T1_universe_invvol", "bond_attribution_v6"),
        ("T2_bond_invvol",     "T2_bond_invvol",     "bond_attribution_v6"),
        ("T3_bond_eqw",        "T3_bond_eqw",        "bond_attribution_v6"),
        ("T4_equity_invvol",   "T4_equity_invvol",   "bond_attribution_v6"),
    ):
        p = data_dir / "bond_attribution_v6" / tag / "summary.csv"
        if p.exists():
            df = pd.read_csv(p)
            r = df.iloc[0]
            out[label] = {
                "sharpe": float(r.get("sharpe", np.nan)),
                "cagr":   float(r.get("cagr",   np.nan)),
                "max_dd": float(r.get("max_dd", np.nan)),
                "source": source,
            }
    return out


# ---------------------------------------------------------------------- #
# CLI
# ---------------------------------------------------------------------- #
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sizings", type=str, default="eqw,invvol",
                   help="comma-separated intra-block sizings (subset of "
                        "{eqw, invvol}); default runs both")
    p.add_argument("--budgets", type=str, default="naive,lw_erc",
                   help="comma-separated budget methods (subset of "
                        "{naive, lw_erc}); default runs both")
    p.add_argument("--no-trend", action="store_true",
                   help="disable the 10-mo MA trend gate (all groups ON)")
    p.add_argument("--out-tag", type=str, default=None,
                   help="suffix on output dir + report file")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    sizings = tuple(x.strip() for x in args.sizings.split(",") if x.strip())
    budgets = tuple(x.strip() for x in args.budgets.split(",") if x.strip())
    tag_suffix = f"_{args.out_tag}" if args.out_tag else ""
    out_root = C.DATA_DIR / f"block_risk_budget_v6{tag_suffix}"
    report_p = C.REPORTS_DIR / f"block_risk_budget_v6{tag_suffix}_report.md"
    out_root.mkdir(parents=True, exist_ok=True)

    shared = BC.load_shared()
    print(f"shared: {len(shared['codes'])} codes, "
          f"{len(shared['fwd_1w'])} bars\n")

    variants: list[dict] = []
    for sz in sizings:
        for bd in budgets:
            print(f"--- variant  intra_sizing={sz}  budget={bd}  "
                  f"trend={'on' if not args.no_trend else 'off'} ---")
            bundle = run_variant(shared, intra_sizing=sz, budget_method=bd,
                                 use_trend=not args.no_trend)
            persist_variant(bundle, out_root=out_root)
            s = bundle["summary"]
            print(f"  IS Sharpe={s.is_sharpe:+.3f} "
                  f"CAGR={s.is_cagr*100:+.2f}% "
                  f"DD={s.is_max_dd*100:+.2f}% "
                  f"vol={s.annual_vol*100:+.2f}% "
                  f"turn={s.avg_turnover:.3f} "
                  f"K̄={s.mean_K:.1f}\n")
            variants.append(bundle)

    anchors = load_anchors()
    write_report(variants, anchors, report_p)


if __name__ == "__main__":
    main()
