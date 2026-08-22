#!/usr/bin/env python3
"""Live price pull — latest available close, with an EXPLICIT failure state.

LIVE codepath. Separate from backfill on purpose (Section 6.2). It pulls a short
trailing window and reports the most recent complete trading day. On any source
failure it prints a machine-readable PIPELINE_FAILURE line and exits non-zero —
it NEVER emits a stale, cached, or fabricated close dressed as real.

Emits one JSON object to stdout so a dashboard can consume it directly:
  status = "ok"       -> a real, sourced latest close (with provenance + fetch time)
  status = "failure"  -> reason string; dashboard must show the failure, not a stale value

Usage:
    python scripts/live_prices.py
    python scripts/live_prices.py --lookback-days 7
"""

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goldengine.errors import PipelineError  # noqa: E402
from goldengine.prices import assemble_price_rows  # noqa: E402
from goldengine.sources import yahoo  # noqa: E402


def _emit(obj) -> None:
    print(json.dumps(obj, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lookback-days", type=int, default=7,
                    help="trailing window to find the latest complete close")
    args = ap.parse_args()

    now = _dt.datetime.now(_dt.timezone.utc)
    end = now.date().isoformat()
    start = (now.date() - _dt.timedelta(days=max(1, args.lookback_days))).isoformat()

    try:
        gold = yahoo.fetch_usd_gold(start, end)
        usd_inr = yahoo.fetch_usd_inr(start, end)
    except PipelineError as exc:
        _emit({
            "status": "failure",
            "reason": str(exc),
            "checked_at": now.isoformat(timespec="seconds"),
            "note": "prediction unavailable — pipeline failure; do not show a stale value",
        })
        return 1

    rows = assemble_price_rows(gold, usd_inr)
    if not rows:
        _emit({
            "status": "failure",
            "reason": "no gold trading days in lookback window",
            "checked_at": now.isoformat(timespec="seconds"),
        })
        return 1

    latest = rows[-1]
    _emit({
        "status": "ok",
        "as_of_date": latest.date,
        "checked_at": now.isoformat(timespec="seconds"),
        "usd_gold": {
            "close": latest.usd_gold_close,
            "change_pct": latest.usd_gold_change_pct,
            "instrument": latest.usd_gold_instrument,
            "source": latest.usd_gold_source,
            "fetched_at": gold.fetched_at,
        },
        "usd_inr": {
            "rate": latest.usd_inr_rate,
            "source": latest.usd_inr_source,
            "fetched_at": usd_inr.fetched_at,
        },
        "usd_gold_inr_equiv": {
            "value": latest.usd_gold_inr_equiv,
            "is_derived": latest.usd_gold_inr_equiv_is_derived,
            "note": latest.usd_gold_inr_equiv_note,
        },
        "mcx_inr_gold_close": {
            "value": latest.mcx_inr_gold_close,
            "null_reason": latest.mcx_inr_gold_null_reason,
        },
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
