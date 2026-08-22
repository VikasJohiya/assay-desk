#!/usr/bin/env python3
"""Backfill US signals (Fed press releases) over a bounded range -> CSV.

HISTORICAL codepath (separate from any live signal path, Section 6.2). Produces
a normalized per-signal table (many rows per day); the day-level us_signals[]
list is later built by joining this on `published_date`.

Optionally applies a leak cutoff and reports what it WITHHOLD (never silently):
    --cutoff 2026-08-20T00:00:00Z
means "only signals published strictly before this instant are usable"; anything
at/after is written to a separate *_excluded.csv and summarized to stderr.

Usage:
    python scripts/backfill_signals_us.py --start 2026-06-01 --end 2026-08-21
    python scripts/backfill_signals_us.py --start 2026-08-01 --end 2026-08-21 \
        --cutoff 2026-08-20T00:00:00Z
"""

import argparse
import csv
import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goldengine.errors import PipelineError  # noqa: E402
from goldengine.leakcheck import enforce_cutoff  # noqa: E402
from goldengine.sources import fed  # noqa: E402

_FIELDS = ["published_date", "published_at", "country", "source", "category",
           "tag", "title", "url", "confidence_discount"]


def _valid_iso_date(s: str) -> str:
    try:
        _dt.date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an ISO date (YYYY-MM-DD): {s!r}")
    return s


def _write(path: Path, signals) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_FIELDS)
        w.writeheader()
        for s in signals:
            d = s.as_dict()
            w.writerow({k: d[k] for k in _FIELDS})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", required=True, type=_valid_iso_date)
    ap.add_argument("--end", required=True, type=_valid_iso_date)
    ap.add_argument("--out", default="data/us_signals_backfill.csv")
    ap.add_argument("--cutoff", default=None,
                    help="ISO instant; withhold signals published at/after it")
    args = ap.parse_args()

    if args.start > args.end:
        print(f"ERROR: start {args.start} after end {args.end}", file=sys.stderr)
        return 2

    try:
        sigset = fed.fetch_press_releases(args.start, args.end)
    except PipelineError as exc:
        print(f"PIPELINE FAILURE — signal backfill aborted, nothing written.\n  {exc}",
              file=sys.stderr)
        return 1

    signals = sigset.signals
    out_path = Path(args.out)

    if args.cutoff:
        result = enforce_cutoff(signals, args.cutoff)
        _write(out_path, result.included)
        excl_path = out_path.with_name(out_path.stem + "_excluded.csv")
        _write(excl_path, result.excluded)
        print(f"OK — leak cutoff applied. {result.summary}")
        print(f"  included -> {out_path}")
        print(f"  excluded -> {excl_path}  (WITHHELD as leak risk, not dropped)")
        if result.excluded:
            print("  withheld:", file=sys.stderr)
            for s in result.excluded:
                print(f"    {s.published_at}  [{s.tag}]  {s.title[:70]}", file=sys.stderr)
    else:
        _write(out_path, signals)
        print(f"OK — {len(signals)} signals -> {out_path}  (no cutoff applied)")

    mono = [s for s in signals if s.category == "Monetary Policy"]
    print(f"  source:  {sigset.source}")
    print(f"  range:   {args.start} .. {args.end}")
    print(f"  total:   {len(signals)} signals | {len(mono)} monetary-policy")
    print(f"  fetched: {sigset.fetched_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
