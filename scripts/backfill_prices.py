#!/usr/bin/env python3
"""Backfill the price leg over a bounded historical date range -> CSV.

HISTORICAL codepath. Kept separate from the live codepath on purpose (Section
6.2): a leak/correctness fix here must never silently apply to live, and vice
versa. This script owns its own range handling and CSV assembly; it shares only
the pure fetchers in goldengine.sources.

Usage:
    python scripts/backfill_prices.py --start 2026-06-01 --end 2026-08-21
    python scripts/backfill_prices.py --start 2026-06-01 --end 2026-08-21 \
        --out data/prices_backfill.csv
"""

import argparse
import csv
import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goldengine.errors import PipelineError  # noqa: E402
from goldengine.prices import assemble_price_rows  # noqa: E402
from goldengine.sources import yahoo  # noqa: E402

_FIELDS = [
    "date",
    "usd_gold_close",
    "usd_gold_change_pct",
    "usd_gold_instrument",
    "usd_gold_source",
    "mcx_inr_gold_close",
    "mcx_inr_gold_change_pct",
    "mcx_inr_gold_null_reason",
    "usd_inr_rate",
    "usd_inr_source",
    "usd_gold_inr_equiv",
    "usd_gold_inr_equiv_is_derived",
    "usd_gold_inr_equiv_note",
]


def _valid_iso(s: str) -> str:
    try:
        _dt.date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an ISO date (YYYY-MM-DD): {s!r}")
    return s


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", required=True, type=_valid_iso)
    ap.add_argument("--end", required=True, type=_valid_iso)
    ap.add_argument("--out", default="data/prices_backfill.csv")
    args = ap.parse_args()

    if args.start > args.end:
        print(f"ERROR: start {args.start} is after end {args.end}", file=sys.stderr)
        return 2

    # Fail visibly: if any source is unavailable, stop and report — never write a
    # partial/faked CSV that looks complete.
    try:
        gold = yahoo.fetch_usd_gold(args.start, args.end)
        usd_inr = yahoo.fetch_usd_inr(args.start, args.end)
    except PipelineError as exc:
        print(f"PIPELINE FAILURE — backfill aborted, nothing written.\n  {exc}",
              file=sys.stderr)
        return 1

    rows = assemble_price_rows(gold, usd_inr)
    if not rows:
        print("PIPELINE FAILURE — no gold trading days in range; nothing written.",
              file=sys.stderr)
        return 1

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_dict())

    print(f"OK — {len(rows)} rows -> {out_path}")
    print(f"  gold:    {gold.source}  ({gold.instrument}, {gold.unit})")
    print(f"  usd/inr: {usd_inr.source}  ({usd_inr.instrument}, {usd_inr.unit})")
    print(f"  range:   {rows[0].date} .. {rows[-1].date}")
    print(f"  fetched: gold {gold.fetched_at} | usd/inr {usd_inr.fetched_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
