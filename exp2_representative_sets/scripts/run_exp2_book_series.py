"""
scripts/run_exp2_book_series.py
================================
Re-run the exp2 (adaptive-K representative sets) finalist book once and
persist the per-bar net_ret / gross_ret / turnover series to CSV, so the
two_layer_report_cn builder can plot NAV / DD / turnover figures for the
`hold_all` vs `replicated_adaptive` comparison without re-running the
whole exp2 pipeline (which also does a diagnostic K sweep).

Reads the already-persisted `clusters_yearly.csv` + `reps_yearly.csv`
under `data/exp2_representative_sets_v6/` (produced by
exp2_representative_sets_v6.py) so no clustering is re-computed.

Outputs (under `data/exp2_representative_sets_v6/`):
    hold_all_net_ret.csv        — same series as block_two_layer_v6/q20_eps030/net_ret.csv
    hold_all_gross_ret.csv
    hold_all_turnover.csv
    replicated_net_ret.csv
    replicated_gross_ret.csv
    replicated_turnover.csv
"""
from __future__ import annotations

from pathlib import Path

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
import block_composite_v6 as BC
import block_two_layer_v6 as TL

import exp2_representative_sets_v6 as EXP2


OUT_ROOT = C.DATA_DIR / "exp2_representative_sets_v6"


def _save_series(s: pd.Series, path: Path, col: str) -> None:
    df = s.rename(col).to_frame()
    df.index.name = "date"
    df.to_csv(path)


def main() -> None:
    print("[load] shared panel + alpha scores")
    shared = BC.load_shared()
    alpha_scores = TL.build_alpha_scores(shared)

    print("[load] persisted adaptive-K clusters + reps")
    clusters = pd.read_csv(OUT_ROOT / "clusters_yearly.csv")
    reps     = pd.read_csv(OUT_ROOT / "reps_yearly.csv")
    reps_yearly: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for b in EXP2.NON_ALPHA_BLOCKS:
        cb = clusters[clusters["block"] == b]
        rb = reps[reps["block"] == b]
        if not cb.empty:
            reps_yearly[b] = (cb, rb)

    print("[run] hold_all (Q_FIN, EPS_FIN)")
    hold_summ, hold_res = EXP2._run_holdall(shared, alpha_scores)
    print(f"  hold_all IS Sh={hold_summ.is_sharpe:+.3f}  OOS Sh={hold_summ.oos_sharpe:+.3f}")

    print("[run] replicated_adaptive (Q_FIN, EPS_FIN)")
    rep_summ, rep_res = EXP2.run_book_with_reps(
        shared, alpha_scores, reps_yearly,
        q=EXP2.Q_FIN, epsilon=EXP2.EPS_FIN,
    )
    print(f"  replicated IS Sh={rep_summ.is_sharpe:+.3f}  OOS Sh={rep_summ.oos_sharpe:+.3f}")

    print("[save] time series")
    _save_series(hold_res.net_ret,  OUT_ROOT / "hold_all_net_ret.csv",       "net_ret")
    _save_series(hold_res.port_ret, OUT_ROOT / "hold_all_gross_ret.csv",     "gross_ret")
    _save_series(hold_res.turnover, OUT_ROOT / "hold_all_turnover.csv",      "turnover")
    _save_series(rep_res.net_ret,   OUT_ROOT / "replicated_net_ret.csv",     "net_ret")
    _save_series(rep_res.port_ret,  OUT_ROOT / "replicated_gross_ret.csv",   "gross_ret")
    _save_series(rep_res.turnover,  OUT_ROOT / "replicated_turnover.csv",    "turnover")
    print(f"wrote to {OUT_ROOT}")


if __name__ == "__main__":
    main()
