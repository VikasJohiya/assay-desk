#!/usr/bin/env python3
"""Lightweight INTRADAY price refresh — the fast cadence.

Fetches only the live gold + USD/INR quotes, patches a `live` block into the
existing snapshot, and rebuilds dashboard.html. It does NOT rerun the 20-year
history, backtest or calibration (that's the daily job) — so it's cheap enough
to run every ~30 min through Indian market hours (MCX 09:00–23:30 IST).

The rupee number here is an HONEST ESTIMATE: international gold (GC=F, ~23h
Globex) × USD/INR. It omits India's import duty + local premium, so it tracks
the direction/size of the Indian move but is NOT the exact MCX print — and it is
labeled exactly that way in the UI. Fail-visible: any fetch error exits non-zero
and leaves the last good snapshot untouched.

Usage:
    python scripts/update_live_price.py
"""

import datetime as _dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))  # so we can reuse build_dashboard.main()

from goldengine.errors import PipelineError  # noqa: E402
from goldengine.sources import yahoo  # noqa: E402

SNAPSHOT = ROOT / "data" / "dashboard_snapshot.json"
GRAMS_PER_OZ = 31.1034768  # 1 troy ounce

# India landed-cost premium of MCX over the international × FX estimate — import
# customs duty + cess + local dealer premium (+ minor 995-vs-999 purity and
# contract-carry). This is MODELED, not a live MCX feed: it is calibrated once to
# a real MCX observation so the offset is grounded and the staleness is visible.
# Recalibrate when the gap to a real MCX quote drifts materially (duty changes).
INDIA_PREMIUM_PCT = 13.1
PREMIUM_CALIBRATED_ON = "2026-08-24"
PREMIUM_ANCHOR = {  # the real MCX observation this factor was fitted to
    "mcx_10g": 163277, "estimate_10g": 144335,
    "ref": "MCX Gold Oct-2026 (moneycontrol), 24 Aug 2026 ~10:23 IST",
}


def main() -> int:
    if not SNAPSHOT.exists():
        print("ERROR: snapshot missing — run build_dashboard_snapshot.py first",
              file=sys.stderr)
        return 1
    try:
        gold = yahoo.fetch_live_quote("GC=F")
        fx = yahoo.fetch_live_quote("USDINR=X")
    except PipelineError as exc:
        print(f"ERROR: live fetch failed, snapshot left untouched — {exc}", file=sys.stderr)
        return 2

    g, rate = gold["price"], fx["price"]
    prev = gold["previous_close"]
    live = {
        "gold_usd_oz": round(g, 2),
        "gold_usd_oz_prev": prev,
        "gold_usd_change_pct": (round((g / prev - 1) * 100, 2) if prev else None),
        "usd_inr": round(rate, 4),
        "gold_usd_10g": round(g / GRAMS_PER_OZ * 10, 2),
        "gold_inr_10g_est": round(g * rate / GRAMS_PER_OZ * 10),
        # Modeled ≈ MCX: estimate + calibrated India duty/premium (see constants).
        "mcx_adj_10g": round(g * rate / GRAMS_PER_OZ * 10 * (1 + INDIA_PREMIUM_PCT / 100)),
        "india_premium_pct": INDIA_PREMIUM_PCT,
        "premium_calibrated_on": PREMIUM_CALIBRATED_ON,
        "premium_anchor": PREMIUM_ANCHOR,
        "gold_market_time": gold["market_time"],
        "fx_market_time": fx["market_time"],
        "fetched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "source": "Yahoo:GC=F × Yahoo:USDINR=X",
        "is_estimate": True,
        "note": "international gold × USD/INR — not the MCX print (omits duty + local premium)",
    }

    data = json.loads(SNAPSHOT.read_text())
    data["live"] = live
    SNAPSHOT.write_text(json.dumps(data, indent=2))

    # Rebuild the HTML view from the patched snapshot.
    import build_dashboard  # noqa: E402  (scripts/ added to sys.path above)
    rc = build_dashboard.main()
    if rc == 0:
        print(f"OK — live estimate: ${live['gold_usd_oz']}/oz → "
              f"₹{live['gold_inr_10g_est']:,}/10g  ·  ≈ MCX ₹{live['mcx_adj_10g']:,}/10g "
              f"(+{INDIA_PREMIUM_PCT}%)  (gold @ {live['gold_market_time']})")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
