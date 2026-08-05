"""
v6/scripts/split_px_v6.py
=========================
Phase 4.2 — split the long-form price panel into per-code parquets that the
factor library can consume.

Reads
-----
    data/universe_v6/px_daily.parquet     (long: date, code, open, high, low,
                                           close, volume, amount)
    data/universe_v6/membership.parquet   (W-FRI × code, bool)

Writes
------
    data/px_daily/{code_underscore}.parquet   (index=date, cols=open, high,
                                                low, close, volume,
                                                total_turnover)

Notes
-----
- Only ever-admitted codes (`membership.any(axis=0)`) are split by default —
  never-admitted names have no downstream consumer (design §4, plan §4.1).
  Pass ``--all-codes`` to split the full catalogue instead.
- ``amount`` is renamed to ``total_turnover`` to match the factor library's
  column contract (see factors/daily/*, factors/sentiment/*).
- ``vwap`` and ``returns`` are NOT precomputed — the factor library computes
  vwap internally where it needs it, and no factor reads a ``returns``
  column directly.
- Filenames replace ``.`` with ``_`` so we mirror the root ``_bootstrap`` /
  ``etf_io`` convention (``159915_XSHE.parquet``, not ``159915.XSHE.parquet``).
- Skips writing if the destination file exists AND its mtime is newer than
  the source parquet's mtime; ``--force`` overrides.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import List

import pandas as pd

_HERE = Path(__file__).resolve()
DEFAULT_SRC = _HERE.parents[2] / "data" / "universe_v6"
DEFAULT_DST = _HERE.parents[2] / "data" / "px_daily"

FACTOR_COLS = ("open", "high", "low", "close", "volume", "total_turnover")


def code_to_filename(code: str) -> str:
    """`159007.XSHE` → `159007_XSHE.parquet` (matches root _bootstrap)."""
    return code.replace(".", "_") + ".parquet"


def resolve_codes(src: Path, all_codes: bool) -> List[str]:
    if all_codes:
        cat = pd.read_csv(src / "catalogue.csv")
        return cat["code"].tolist()
    mem_path = src / "membership.parquet"
    if not mem_path.exists():
        raise FileNotFoundError(
            f"{mem_path} missing — run Phase 3 first, or pass --all-codes")
    mem = pd.read_parquet(mem_path)
    return list(mem.columns[mem.any(axis=0)])


def split(src: Path, dst: Path, codes: List[str], force: bool) -> dict:
    dst.mkdir(parents=True, exist_ok=True)
    src_px = src / "px_daily.parquet"
    src_mtime = src_px.stat().st_mtime

    t0 = time.time()
    print(f"[split_px_v6] loading {src_px} ...")
    px = pd.read_parquet(src_px)
    print(f"[split_px_v6]   {len(px):,} rows, {px['code'].nunique()} codes, "
          f"{time.time()-t0:.1f}s")

    px = px.rename(columns={"amount": "total_turnover"})
    missing_cols = [c for c in FACTOR_COLS if c not in px.columns]
    if missing_cols:
        raise ValueError(f"px_daily missing required columns: {missing_cols}")

    codes_set = set(codes)
    n_written, n_skipped, n_no_data = 0, 0, 0
    per_code_rows = {}

    for code, group in px.groupby("code", sort=False):
        if code not in codes_set:
            continue
        out = dst / code_to_filename(code)
        if (not force) and out.exists() and out.stat().st_mtime >= src_mtime:
            n_skipped += 1
            per_code_rows[code] = len(group)
            continue

        frame = (group
                 .drop(columns=["code"])
                 .sort_values("date")
                 .set_index("date")
                 [list(FACTOR_COLS)])
        if frame.empty:
            n_no_data += 1
            continue
        frame.to_parquet(out)
        n_written += 1
        per_code_rows[code] = len(frame)

    covered = set(per_code_rows.keys())
    missing = [c for c in codes if c not in covered]
    print(f"[split_px_v6] wrote={n_written} skipped_up_to_date={n_skipped} "
          f"no_data={n_no_data} missing_from_source={len(missing)}")
    if missing:
        print(f"[split_px_v6]   codes with no rows in px_daily.parquet: "
              f"{missing[:20]}{' …' if len(missing) > 20 else ''}")
    return {"written": n_written, "skipped": n_skipped,
            "no_data": n_no_data, "missing": missing,
            "per_code_rows": per_code_rows}


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 4.2 price splitter")
    ap.add_argument("--src-dir", default=str(DEFAULT_SRC),
                    help=f"input dir (default: {DEFAULT_SRC})")
    ap.add_argument("--dst-dir", default=str(DEFAULT_DST),
                    help=f"output dir (default: {DEFAULT_DST})")
    ap.add_argument("--all-codes", action="store_true",
                    help="split every catalogue code, not just members")
    ap.add_argument("--force", action="store_true",
                    help="rewrite files even if up-to-date by mtime")
    args = ap.parse_args()

    src, dst = Path(args.src_dir), Path(args.dst_dir)
    codes = resolve_codes(src, args.all_codes)
    print(f"[split_px_v6] target: {len(codes)} codes → {dst}")
    split(src, dst, codes, args.force)


if __name__ == "__main__":
    main()
