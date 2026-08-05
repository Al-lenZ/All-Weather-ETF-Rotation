"""v6/leverage/run_matrix.py — run a batch of cells sequentially.

Round A (per PLAN §6): 4 cells forming the {base RB, EW RB} × {no-lev,
book-lev GC007} factorial. Reuses one loaded ``shared`` bundle across the
four cells so the α-score cache in ``block_two_layer_v6.build_alpha_scores``
gets hit exactly once.

CLI
---
    python -m leverage.run_matrix --round A
    python -m leverage.run_matrix --cells A_base_nolev_raw A_base_nolev
"""
from __future__ import annotations

import argparse
from pathlib import Path

import _common_leverage as CL
# --- v6/common sys.path bootstrap ---
import sys as _v6_sys
from pathlib import Path as _V6Path
_v6_p = _V6Path(__file__).resolve().parent
while _v6_p.name != "v6" and _v6_p.parent != _v6_p:
    _v6_p = _v6_p.parent
_v6_sys.path.insert(0, str(_v6_p / "common"))
del _v6_p
# --------------------------------------
import block_composite_v6 as BC
import run_cell as RC


ROUND_A = ("A_base_nolev", "A_ew_nolev", "A_base_lev", "A_ew_lev")

ROUND_B = (
    "B_base_lev_DR007",  "B_ew_lev_DR007",
    "B_base_lev_static", "B_ew_lev_static",
    "B_base_bondleg_lev", "B_ew_bondleg_lev",
)

# Round C — non-α blocks compressed to representative sets (post-hoc,
# PLAN §11 log 2026-07-31).
ROUND_C = (
    "C_base_reps_nolev", "C_ew_reps_nolev",
    "C_base_reps_lev",   "C_ew_reps_lev",
    "C_base_reps_lev_DR007", "C_ew_reps_lev_DR007",
)

# Round D — higher-cap experiment on the rep-set book (σ*=6.4 %, cap 5.0).
# Post-hoc, PLAN §11 log 2026-07-31.
ROUND_D = (
    "D_base_reps_lev",       "D_ew_reps_lev",
    "D_base_reps_lev_DR007", "D_ew_reps_lev_DR007",
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run leverage cells in batch.")
    p.add_argument("--round", choices=["A", "B", "C", "D"], help="run a pre-defined round")
    p.add_argument("--cells", nargs="+",
                   help="explicit cell list (overrides --round)")
    p.add_argument("--out-root", type=str, default=None)
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    if args.cells:
        cells = tuple(args.cells)
    elif args.round == "A":
        cells = ROUND_A
    elif args.round == "B":
        cells = ROUND_B
    elif args.round == "C":
        cells = ROUND_C
    elif args.round == "D":
        cells = ROUND_D
    else:
        raise SystemExit("must pass --round A|B or --cells CELL_ID [...]")

    out_root = Path(args.out_root) if args.out_root else CL.LEV_DIR
    shared = BC.load_shared()
    print(f"shared: {len(shared['codes'])} codes, "
          f"{len(shared['fwd_1w'])} bars\n")

    results: dict[str, dict] = {}
    for cell in cells:
        print(f"\n===== running {cell} =====")
        bundle = RC.run_cell(cell, shared=shared, out_root=out_root)
        s = bundle["summary"]
        for _, row in s.iterrows():
            print(f"  [{row['window']:6s}] "
                  f"Sh={row['sharpe_net']:+.3f}  "
                  f"excSh={row['excess_sharpe_net']:+.3f}  "
                  f"CAGR={row['cagr_net']*100:+.2f}%  "
                  f"DD={row['max_dd']*100:+.2f}%  "
                  f"L̄={row['mean_L']:.3f}  "
                  f"cap%={row['pct_at_cap']*100:.1f}  "
                  f"floor%={row['pct_at_floor']*100:.1f}  "
                  f"fdrag={row['funding_drag_bp_yr']:+.1f}bp/y  "
                  f"cshcarry={row['cash_carry_bp_yr']:+.1f}bp/y  "
                  f"n={int(row['n_bars'])}")
        results[cell] = bundle
    print(f"\nwrote {len(results)} cells under {out_root}")


if __name__ == "__main__":
    main()
