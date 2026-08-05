"""
v6/scripts/bond_attribution_v6.py
=================================
PnL-level attribution for the v6 bond-tilt finding
(see reports/block_neutral_ic_v6.md + memory
[[project-block-neutral-ic]] for the signal-level test).

Question. The block-neutral IC diagnostic showed that on long cells the
ensemble α's IC lives almost entirely in *between-block* rotation
(bonds vs. the rest). We want the same story on the PnL side and want
to know:

  a. How much of the baseline book's PnL is "own the universe, vol-scaled"?
     → build T1: at every rebal, hold every eligible member of the pool
       with weight ∝ 1/σ_causal (no ranking).
  b. How much is "own the bonds, vol-scaled"?
     → build T2: same, but restricted to codes in
       {bond_rates, bond_credit}.
  c. How much comes from *sizing* within bonds (as opposed to bond
     composition alone)?
     → build T3: equal weight on all bond codes; compare T3 vs T2.

Anchors. Two static-ensemble books (`long_q05`, `long_q20`) from
``data/v6_static/{cell}/ensemble_{net_ret.csv, weights.parquet}``.
long_q05 is the most concentrated / most alpha-driven (K̄ ≈ 4), long_q20
is the finalist basket size (K̄ ≈ 17). Comparing both isolates the
"concentration matters" vs "restriction matters" axes.

Regressions. IS-only OLS ``B ~ α + β · T2`` for each baseline B ∈
{long_q05, long_q20}. Reports β, R², annualized α, and residual Sharpe.
A high R² with residual Sharpe near zero says the baseline *is* T2 up
to noise — i.e. the ensemble is not doing meaningful within-bond
selection, and the alpha's value lives in *which block to own*.

All numbers IS-only (bars ≤ IN_SAMPLE_END) — v6 discipline while
exploring. Cost = 10 bp/side across the board.

Outputs
-------
    data/bond_attribution_v6/{T1,T2,T3}/{weights.parquet,net_ret.csv,summary.csv}
    reports/bond_attribution_v6.md

Run
---
    python v6/scripts/bond_attribution_v6.py
"""
from __future__ import annotations

from dataclasses import asdict
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
import sizing_sweep_v6 as SS


BOND_BLOCKS   = ("bond_rates", "bond_credit")
EQUITY_BLOCKS = ("sector_cn", "broad_cn", "cross_border_hk",
                 "cross_border_dm", "smallcap_cn")
COST          = E.DEFAULT_COST_PER_TRADE
BASELINES     = ("long_q05", "long_q20")
OUT_ROOT      = C.DATA_DIR / "bond_attribution_v6"


# ---------------------------------------------------------------------- #
# Inputs
# ---------------------------------------------------------------------- #
def _load_shared(data_dir: Path) -> dict:
    mem = pd.read_parquet(data_dir / "universe_v6" / "membership.parquet")
    codes = list(mem.columns[mem.any(axis=0)])
    mem = mem[codes].astype(bool)
    fwd   = pd.read_parquet(data_dir / "panels_v6" / "fwd_1w.parquet")[codes]
    sigma = pd.read_parquet(data_dir / "panels_v6" / "sigma_causal_26w.parquet")[codes]
    block_tag = SS._load_block_tag(data_dir)
    return {"membership": mem, "codes": codes,
            "fwd_1w": fwd, "sigma": sigma, "block_tag": block_tag}


def _load_baseline(data_dir: Path, cell: str) -> dict:
    d = data_dir / "v6_static" / cell
    W = pd.read_parquet(d / "ensemble_weights.parquet")
    net = pd.read_csv(d / "ensemble_net_ret.csv", parse_dates=[0], index_col=0)
    net = net.iloc[:, 0]
    net.name = cell
    return {"weights": W, "net_ret": net}


# ---------------------------------------------------------------------- #
# Weight builders — no alpha, sizing-only
# ---------------------------------------------------------------------- #
def _eligible_universe(sigma: pd.DataFrame, mem: pd.DataFrame) -> pd.DataFrame:
    """(σ defined and > 0) AND membership."""
    return sigma.notna() & (sigma > 0) & mem.astype(bool)


def _restrict_to_blocks(eligible: pd.DataFrame,
                        block_tag: pd.Series,
                        blocks: tuple[str, ...]) -> pd.DataFrame:
    keep_codes = block_tag[block_tag.isin(blocks)].index
    mask = eligible.columns.isin(keep_codes)
    out = eligible.copy()
    out.loc[:, ~mask] = False
    return out


def build_universe_invvol(shared: dict) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """T1 — at each rebal hold every eligible member, weight ∝ 1/σ."""
    sigma = shared["sigma"]; mem = shared["membership"]
    eligible = _eligible_universe(sigma, mem)
    inv_sig  = (1.0 / sigma).where(eligible, 0.0)
    row_sum  = inv_sig.sum(axis=1).replace(0.0, np.nan)
    W = inv_sig.div(row_sum, axis=0).fillna(0.0)
    N_t = eligible.sum(axis=1).astype(int).rename("N_t")
    K_t = N_t.rename("K_t")
    return W, N_t, K_t


def build_bond_invvol(shared: dict) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """T2 — restrict eligible set to bond blocks, weight ∝ 1/σ."""
    sigma = shared["sigma"]; mem = shared["membership"]
    eligible = _restrict_to_blocks(_eligible_universe(sigma, mem),
                                   shared["block_tag"], BOND_BLOCKS)
    inv_sig  = (1.0 / sigma).where(eligible, 0.0)
    row_sum  = inv_sig.sum(axis=1).replace(0.0, np.nan)
    W = inv_sig.div(row_sum, axis=0).fillna(0.0)
    N_t = eligible.sum(axis=1).astype(int).rename("N_t")
    K_t = N_t.rename("K_t")
    return W, N_t, K_t


def build_equity_invvol(shared: dict) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """T4 — restrict eligible set to equity blocks, weight ∝ 1/σ.

    Analog of T2 but for the equity side (sector_cn, broad_cn,
    cross_border_hk, cross_border_dm, smallcap_cn). Used as the equity-β
    leg in the bivariate decomposition ``B ~ α + β_bond·T2 + β_eq·T4``
    that isolates within-block selection value from block β exposure.
    """
    sigma = shared["sigma"]; mem = shared["membership"]
    eligible = _restrict_to_blocks(_eligible_universe(sigma, mem),
                                   shared["block_tag"], EQUITY_BLOCKS)
    inv_sig  = (1.0 / sigma).where(eligible, 0.0)
    row_sum  = inv_sig.sum(axis=1).replace(0.0, np.nan)
    W = inv_sig.div(row_sum, axis=0).fillna(0.0)
    N_t = eligible.sum(axis=1).astype(int).rename("N_t")
    K_t = N_t.rename("K_t")
    return W, N_t, K_t


def build_bond_eqw(shared: dict) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """T3 — restrict eligible set to bond blocks, weight = 1/N.

    Uses membership only (drops the σ>0 filter) so eligible naming is
    the same as T2 in practice; on the bond side σ is defined once the
    26w warmup is past. Names with σ NaN early on will also be missing
    fwd, which the engine treats as 0 return — safe.
    """
    mem = shared["membership"]
    keep = shared["block_tag"].isin(BOND_BLOCKS)
    keep_codes = keep[keep].index
    eligible = mem.copy().astype(bool)
    drop = ~eligible.columns.isin(keep_codes)
    eligible.loc[:, drop] = False
    N_t = eligible.sum(axis=1).astype(int).rename("N_t")
    denom = N_t.replace(0, np.nan).astype(float)
    W = eligible.astype(float).div(denom, axis=0).fillna(0.0)
    return W, N_t, N_t.rename("K_t")


# ---------------------------------------------------------------------- #
# Metrics
# ---------------------------------------------------------------------- #
def _is_slice(s: pd.Series) -> pd.Series:
    return s[s.index <= C.IN_SAMPLE_END]


def _window_metrics(net: pd.Series) -> dict:
    n = int(len(net))
    if n < 2:
        return {"sharpe": np.nan, "cumret": np.nan, "cagr": np.nan,
                "max_dd": np.nan, "ann_vol": np.nan, "n_bars": n}
    ann_vol = float(net.std(ddof=1)) * np.sqrt(C.WEEKS_PER_YEAR)
    ann_ret = float(net.mean()) * C.WEEKS_PER_YEAR
    sharpe  = (ann_ret / ann_vol) if ann_vol > 0 else np.nan
    cumret  = float(net.sum())
    n_yrs   = max(n / C.WEEKS_PER_YEAR, 1e-3)
    cagr    = max(1.0 + cumret, 1e-9) ** (1.0 / n_yrs) - 1.0
    nav     = 1.0 + net.cumsum()
    max_dd  = float(((nav - nav.cummax()) / nav.cummax()).min())
    return {"sharpe": sharpe, "cumret": cumret, "cagr": cagr,
            "max_dd": max_dd, "ann_vol": ann_vol, "n_bars": n}


def _per_year_table(net: pd.Series) -> pd.DataFrame:
    """Per-calendar-year IS stats: return (sum), Sharpe, max drawdown."""
    s = _is_slice(net).copy()
    if s.empty:
        return pd.DataFrame(columns=["year", "ret", "sharpe", "max_dd", "bars"])
    df = s.to_frame("r")
    df["year"] = df.index.year
    rows = []
    for y, g in df.groupby("year"):
        r = g["r"]
        rows.append({
            "year":   int(y),
            "ret":    float(r.sum()),
            "sharpe": float(r.mean() / r.std(ddof=1) * np.sqrt(C.WEEKS_PER_YEAR))
                        if r.std(ddof=1) > 0 else np.nan,
            "max_dd": float(((1 + r.cumsum()) - (1 + r.cumsum()).cummax()).min()),
            "bars":   int(len(r)),
        })
    return pd.DataFrame(rows)


def _block_allocation(W: pd.DataFrame, block_tag: pd.Series) -> pd.Series:
    """Mean IS share of book weight per block (per-bar normalized).

    Bars with row_sum == 0 (book flat that bar — e.g. early bars before
    the α ensemble warms up) are dropped from the mean so the reported
    per-block shares sum to 1.0 across the invested bars.
    """
    is_W = W.loc[W.index <= C.IN_SAMPLE_END]
    abs_W = is_W.abs()
    row_sum = abs_W.sum(axis=1)
    active = row_sum > 0
    if not active.any():
        blocks = block_tag.reindex(is_W.columns).fillna("UNTAGGED").unique()
        return pd.Series(0.0, index=blocks)
    abs_W = abs_W.loc[active]
    share = abs_W.div(row_sum.loc[active], axis=0)
    tag = block_tag.reindex(share.columns).fillna("UNTAGGED")
    return share.T.groupby(tag).sum().T.mean(axis=0)


def _turnover_avg(W: pd.DataFrame) -> float:
    """IS mean turnover (Σ |ΔW| per bar)."""
    is_W = W.loc[W.index <= C.IN_SAMPLE_END]
    return float(is_W.diff().abs().sum(axis=1).fillna(0.0).mean())


# ---------------------------------------------------------------------- #
# Regression (IS-only)
# ---------------------------------------------------------------------- #
def _regress_IS(y: pd.Series, x: pd.Series) -> dict:
    """OLS y = α + β x on aligned IS bars.

    Returns beta, alpha per-bar, alpha annualized, R², residual Sharpe,
    residual mean, residual std, n. `alpha_annualized = alpha_per_bar *
    WEEKS_PER_YEAR`; `residual_sharpe = mean(resid)/std(resid) * √52`
    (mean(resid) equals alpha_per_bar by OLS, so this is just the alpha
    t-stat rescaled to Sharpe units).
    """
    idx = _is_slice(y).index.intersection(_is_slice(x).index)
    yv = y.loc[idx].to_numpy(dtype=float)
    xv = x.loc[idx].to_numpy(dtype=float)
    m = np.isfinite(yv) & np.isfinite(xv)
    yv = yv[m]; xv = xv[m]
    n = int(len(yv))
    if n < 4:
        return {"n": n, "beta": np.nan, "alpha": np.nan,
                "alpha_ann": np.nan, "r2": np.nan,
                "resid_sharpe": np.nan}
    x_mean = xv.mean(); y_mean = yv.mean()
    dx = xv - x_mean; dy = yv - y_mean
    denom = float((dx * dx).sum())
    if denom <= 0:
        return {"n": n, "beta": np.nan, "alpha": np.nan,
                "alpha_ann": np.nan, "r2": np.nan,
                "resid_sharpe": np.nan}
    beta  = float((dx * dy).sum() / denom)
    alpha = float(y_mean - beta * x_mean)
    yhat  = alpha + beta * xv
    resid = yv - yhat
    ss_res = float((resid * resid).sum())
    ss_tot = float((dy * dy).sum())
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else np.nan
    # Sharpe of the β-hedged series `y − β x` (mean = α, std = std(resid)).
    # Not `y − ŷ = y − α − β x`, whose mean is 0 by OLS construction.
    hedged = yv - beta * xv
    h_std  = float(hedged.std(ddof=1))
    resid_sharpe = (hedged.mean() / h_std * np.sqrt(C.WEEKS_PER_YEAR)) \
                    if h_std > 0 else np.nan
    return {"n": n, "beta": beta, "alpha": alpha,
            "alpha_ann": alpha * C.WEEKS_PER_YEAR,
            "r2": r2, "resid_sharpe": float(resid_sharpe)}


def _regress_IS_bivar(y: pd.Series,
                      x_bond: pd.Series,
                      x_eq: pd.Series) -> dict:
    """OLS y = α + β_bond·x_bond + β_eq·x_eq on aligned IS bars.

    Bivariate decomposition of the baseline into a bond-β leg (T2) and
    an equity-β leg (T4). The β-hedged Sharpe is
    ``mean(y − β_bond·x_bond − β_eq·x_eq) / std(same) · √52`` and equals
    the annualized-α t-stat in Sharpe units. Residual Sharpe should
    shrink noticeably from the univariate-vs-T2 fit once the missing
    equity β is absorbed.
    """
    idx = _is_slice(y).index \
            .intersection(_is_slice(x_bond).index) \
            .intersection(_is_slice(x_eq).index)
    yv = y.loc[idx].to_numpy(dtype=float)
    xb = x_bond.loc[idx].to_numpy(dtype=float)
    xe = x_eq.loc[idx].to_numpy(dtype=float)
    m = np.isfinite(yv) & np.isfinite(xb) & np.isfinite(xe)
    yv = yv[m]; xb = xb[m]; xe = xe[m]
    n = int(len(yv))
    if n < 4:
        return {"n": n, "beta_bond": np.nan, "beta_eq": np.nan,
                "alpha": np.nan, "alpha_ann": np.nan,
                "r2": np.nan, "resid_sharpe": np.nan}
    X = np.column_stack([np.ones(n), xb, xe])
    coef, *_ = np.linalg.lstsq(X, yv, rcond=None)
    alpha, beta_bond, beta_eq = float(coef[0]), float(coef[1]), float(coef[2])
    yhat  = X @ coef
    resid = yv - yhat
    ss_res = float((resid * resid).sum())
    ss_tot = float(((yv - yv.mean()) ** 2).sum())
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else np.nan
    hedged = yv - beta_bond * xb - beta_eq * xe
    h_std  = float(hedged.std(ddof=1))
    resid_sharpe = (hedged.mean() / h_std * np.sqrt(C.WEEKS_PER_YEAR)) \
                    if h_std > 0 else np.nan
    return {"n": n, "beta_bond": beta_bond, "beta_eq": beta_eq,
            "alpha": alpha, "alpha_ann": alpha * C.WEEKS_PER_YEAR,
            "r2": r2, "resid_sharpe": float(resid_sharpe)}


# ---------------------------------------------------------------------- #
# Book runner
# ---------------------------------------------------------------------- #
def _run_and_save(name: str, W: pd.DataFrame, N_t: pd.Series, K_t: pd.Series,
                  shared: dict) -> dict:
    res = E.run_book(W, shared["fwd_1w"], cost_per_trade=COST,
                     N_t=N_t, K_t=K_t)
    is_net = _is_slice(res.net_ret)
    summ = _window_metrics(is_net)
    block_alloc = _block_allocation(W, shared["block_tag"])
    out = OUT_ROOT / name
    out.mkdir(parents=True, exist_ok=True)
    W.to_parquet(out / "weights.parquet")
    res.net_ret.to_frame("net_ret").to_csv(out / "net_ret.csv")
    row = {"book": name, **summ,
           "avg_turnover": _turnover_avg(W),
           "mean_N": float(N_t.loc[N_t.index <= C.IN_SAMPLE_END].mean()),
           "mean_K": float(K_t.loc[K_t.index <= C.IN_SAMPLE_END].mean())}
    pd.DataFrame([row]).to_csv(out / "summary.csv", index=False)
    return {"name": name, "net_ret": res.net_ret, "weights": W,
            "summary": row, "block_alloc": block_alloc}


# ---------------------------------------------------------------------- #
# Report
# ---------------------------------------------------------------------- #
def _fmt_pct(x, digits=2):
    return f"{x*100:+.{digits}f}%" if pd.notna(x) else "     —"

def _fmt(x, digits=3):
    return f"{x:+.{digits}f}" if pd.notna(x) else "  —"


def _write_report(books: dict, per_year: dict, corr: pd.DataFrame,
                  regs: list[dict], bivar_regs: list[dict],
                  report_path: Path) -> None:
    ALL_BOOKS = ("long_q05", "long_q20", "T1_universe_invvol",
                 "T2_bond_invvol", "T3_bond_eqw", "T4_equity_invvol")
    lines: list[str] = []
    lines.append("# v6 static — bond-tilt PnL attribution (IS window)\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    lines.append(
        "Companion to `block_neutral_ic_v6.md`. Signal-side showed the "
        "long-book ensemble α's IC is between-block (bonds vs. rest); this "
        "asks whether that shows up in PnL.\n\n"
        "**Books.** All cost 10 bp/side, static rebalance to target each "
        f"W-FRI bar, IS = bars ≤ {C.IN_SAMPLE_END.date()}.\n"
        "- **long_q05, long_q20** — the static ensemble baselines from "
        "`v6_static/{cell}/ensemble_net_ret.csv`; α-ranked, top-⌈q·N_t⌉, "
        "inv_vol sized. Anchors.\n"
        "- **T1 universe_invvol** — no ranking: every eligible member "
        "weighted ∝ 1/σ_causal.\n"
        "- **T2 bond_invvol** — restrict eligible set to "
        f"blocks {BOND_BLOCKS}, weight ∝ 1/σ.\n"
        "- **T3 bond_eqw** — same restriction, weight = 1/N.\n"
        "- **T4 equity_invvol** — restrict eligible set to equity "
        f"blocks {EQUITY_BLOCKS}, weight ∝ 1/σ. Equity-β leg for "
        "the bivariate decomp in §6.\n\n"
    )

    # ---- Section 1: headline IS summary ----
    lines.append("## 1. IS headline\n")
    lines.append("| book | Sharpe | CAGR | max DD | ann vol | avg turnover | "
                 "mean N | mean K |")
    lines.append("|:---|---:|---:|---:|---:|---:|---:|---:|")
    for name in ALL_BOOKS:
        b = books[name]
        s = b["summary"]
        lines.append(
            f"| {name} | {_fmt(s['sharpe'])} | {_fmt_pct(s['cagr'])} | "
            f"{_fmt_pct(s['max_dd'])} | {_fmt_pct(s['ann_vol'])} | "
            f"{s['avg_turnover']:.3f} | "
            f"{s['mean_N']:.1f} | {s['mean_K']:.1f} |"
        )
    lines.append("")

    # ---- Section 2: block allocation ----
    lines.append("## 2. IS mean block allocation (share of book by block)\n")
    all_blocks = sorted({b for name in books
                         for b in books[name]["block_alloc"].index})
    lines.append("| book | " + " | ".join(all_blocks) + " |")
    lines.append("|:---|" + "|".join(["---:"] * len(all_blocks)) + "|")
    for name in ALL_BOOKS:
        row = books[name]["block_alloc"]
        cells = []
        for blk in all_blocks:
            v = row.get(blk, 0.0)
            cells.append(f"{v*100:5.1f}%" if v > 0 else "   —")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines.append("")

    # ---- Section 3: per-year tables ----
    lines.append("## 3. Per-calendar-year IS stats\n")
    for stat, label in [("ret", "return (sum of weekly net)"),
                        ("sharpe", "Sharpe"),
                        ("max_dd", "max drawdown")]:
        lines.append(f"### {label}\n")
        cols = ALL_BOOKS
        years = sorted(set().union(*(set(per_year[c]["year"]) for c in cols)))
        lines.append("| year | " + " | ".join(cols) + " |")
        lines.append("|:---:|" + "|".join(["---:"] * len(cols)) + "|")
        for y in years:
            row = [f"| {y}"]
            for c in cols:
                py = per_year[c]
                v = py.loc[py["year"] == y, stat]
                if len(v) == 0:
                    row.append(" — ")
                else:
                    x = float(v.iloc[0])
                    if stat == "sharpe":
                        row.append(f" {_fmt(x)} ")
                    else:
                        row.append(f" {_fmt_pct(x)} ")
            lines.append(" | ".join(row) + " |")
        lines.append("")

    # ---- Section 4: IS correlation matrix ----
    lines.append("## 4. IS weekly-net-return correlation\n")
    lines.append("| | " + " | ".join(corr.columns) + " |")
    lines.append("|:---|" + "|".join(["---:"] * len(corr.columns)) + "|")
    for i in corr.index:
        row = [f"| {i}"]
        for c in corr.columns:
            row.append(f" {corr.loc[i, c]:+.3f} ")
        lines.append(" | ".join(row) + " |")
    lines.append("")

    # ---- Section 5: univariate OLS regressions ----
    lines.append("## 5. OLS regression: baseline ~ α + β · X, IS (univariate)\n")
    lines.append("β near 1 with R² ≈ 1 and residual Sharpe ≈ 0 means the "
                 "baseline is X up to noise (no within-block selection value "
                 "beyond block composition + inv-vol sizing). long_q05 is a "
                 "clean single-block book (bonds), so its T2 fit reads "
                 "directly; long_q20 mixes bond + equity blocks and is "
                 "*misspecified* by any single regressor — see §6 for the "
                 "bivariate decomposition.\n\n")
    lines.append("| baseline | n | β | R² | α (ann) | resid Sharpe |")
    lines.append("|:---|---:|---:|---:|---:|---:|")
    for r in regs:
        lines.append(
            f"| {r['name']} | {r['n']} | {_fmt(r['beta'])} | "
            f"{_fmt(r['r2'])} | {_fmt_pct(r['alpha_ann'])} | "
            f"{_fmt(r['resid_sharpe'])} |"
        )
    lines.append("")

    # ---- Section 6: bivariate OLS ~ α + β_bond·T2 + β_eq·T4 ----
    lines.append("## 6. OLS regression: baseline ~ α + β_bond · T2 + β_eq · T4, IS\n")
    lines.append(
        "The bivariate decomposition. T2 and T4 span the "
        "bond-block-β and equity-block-β legs of the pool; anything the "
        "baseline earns beyond a linear combination of them is *within-"
        "block* selection value. Compare α(ann) and residual Sharpe here "
        "vs. the univariate rows in §5: if the baseline is holding a slice "
        "of equity β that a T2-only regression can't see, the residual "
        "shrinks once T4 is added.\n\n"
    )
    lines.append("| baseline | n | β_bond | β_eq | R² | α (ann) | resid Sharpe |")
    lines.append("|:---|---:|---:|---:|---:|---:|---:|")
    for r in bivar_regs:
        lines.append(
            f"| {r['name']} | {r['n']} | {_fmt(r['beta_bond'])} | "
            f"{_fmt(r['beta_eq'])} | {_fmt(r['r2'])} | "
            f"{_fmt_pct(r['alpha_ann'])} | {_fmt(r['resid_sharpe'])} |"
        )
    lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {report_path}")


# ---------------------------------------------------------------------- #
# Main
# ---------------------------------------------------------------------- #
def main():
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    shared = _load_shared(C.DATA_DIR)
    print(f"loaded shared: {len(shared['codes'])} codes, "
          f"{len(shared['fwd_1w'])} W-FRI bars")

    # Baselines
    baselines: dict = {}
    for cell in BASELINES:
        b = _load_baseline(C.DATA_DIR, cell)
        row = _window_metrics(_is_slice(b["net_ret"]))
        row["avg_turnover"] = _turnover_avg(b["weights"])
        # baseline weights use the alpha book's eligibility, so mean N/K
        # approximates from non-zero counts per bar
        nz = (b["weights"].loc[b["weights"].index <= C.IN_SAMPLE_END]
                              .ne(0.0).sum(axis=1))
        row["mean_K"] = float(nz.mean())
        row["mean_N"] = float(shared["membership"]
                              .loc[shared["membership"].index <= C.IN_SAMPLE_END]
                              .sum(axis=1).mean())
        baselines[cell] = {"name": cell, "net_ret": b["net_ret"],
                           "weights": b["weights"],
                           "summary": {"book": cell, **row},
                           "block_alloc": _block_allocation(b["weights"],
                                                            shared["block_tag"])}
        s = row
        print(f"  {cell}:  IS Sharpe={s['sharpe']:+.3f}  "
              f"CAGR={s['cagr']*100:+.2f}%  DD={s['max_dd']*100:+.2f}%")

    # Tests
    W1, N1, K1 = build_universe_invvol(shared)
    W2, N2, K2 = build_bond_invvol(shared)
    W3, N3, K3 = build_bond_eqw(shared)
    W4, N4, K4 = build_equity_invvol(shared)
    tests = {
        "T1_universe_invvol": _run_and_save("T1_universe_invvol", W1, N1, K1, shared),
        "T2_bond_invvol":     _run_and_save("T2_bond_invvol",     W2, N2, K2, shared),
        "T3_bond_eqw":        _run_and_save("T3_bond_eqw",        W3, N3, K3, shared),
        "T4_equity_invvol":   _run_and_save("T4_equity_invvol",   W4, N4, K4, shared),
    }
    for name, b in tests.items():
        s = b["summary"]
        print(f"  {name}:  IS Sharpe={s['sharpe']:+.3f}  "
              f"CAGR={s['cagr']*100:+.2f}%  DD={s['max_dd']*100:+.2f}%  "
              f"turnover={s['avg_turnover']:.3f}  mean_N={s['mean_N']:.1f}")

    books = {**baselines, **tests}

    # Per-year
    per_year = {name: _per_year_table(b["net_ret"]) for name, b in books.items()}

    # Correlation of IS weekly nets
    aligned = pd.DataFrame({name: _is_slice(b["net_ret"])
                            for name, b in books.items()})
    corr = aligned.corr()

    # Regressions: each baseline ~ T2
    T2_net = tests["T2_bond_invvol"]["net_ret"]
    T4_net = tests["T4_equity_invvol"]["net_ret"]
    regs = []
    for cell in BASELINES:
        r = _regress_IS(baselines[cell]["net_ret"], T2_net)
        r["name"] = cell
        regs.append(r)
    # Also: baseline ~ T1 (own the universe), for context
    T1_net = tests["T1_universe_invvol"]["net_ret"]
    for cell in BASELINES:
        r = _regress_IS(baselines[cell]["net_ret"], T1_net)
        r["name"] = f"{cell}  (~ T1 universe_invvol)"
        regs.append(r)
    # Also: baseline ~ T4 (equity_invvol) univariate, for symmetry with T2
    for cell in BASELINES:
        r = _regress_IS(baselines[cell]["net_ret"], T4_net)
        r["name"] = f"{cell}  (~ T4 equity_invvol)"
        regs.append(r)

    # Bivariate: baseline ~ α + β_bond·T2 + β_eq·T4 — the clean decomp
    bivar_regs = []
    for cell in BASELINES:
        r = _regress_IS_bivar(baselines[cell]["net_ret"], T2_net, T4_net)
        r["name"] = cell
        bivar_regs.append(r)

    _write_report(books, per_year, corr, regs, bivar_regs,
                  C.REPORTS_DIR / "bond_attribution_v6.md")

    # Print regression summary to stdout too
    print("\nOLS  IS-only  (univariate):")
    for r in regs:
        print(f"  {r['name']:38s}  β={r['beta']:+.3f}  R²={r['r2']:+.3f}  "
              f"α(ann)={r['alpha_ann']*100:+.2f}%  "
              f"resid Sharpe={r['resid_sharpe']:+.3f}")
    print("\nOLS  IS-only  (bivariate  ~ α + β_bond·T2 + β_eq·T4):")
    for r in bivar_regs:
        print(f"  {r['name']:38s}  β_bond={r['beta_bond']:+.3f}  "
              f"β_eq={r['beta_eq']:+.3f}  R²={r['r2']:+.3f}  "
              f"α(ann)={r['alpha_ann']*100:+.2f}%  "
              f"resid Sharpe={r['resid_sharpe']:+.3f}")


if __name__ == "__main__":
    main()
