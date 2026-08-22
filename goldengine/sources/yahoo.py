"""Yahoo Finance chart-API fetcher (no key) for the USD gold leg.

Phase-1 instrument: GC=F = COMEX front-month gold futures daily close, in USD/oz.
This is the best keyless real instrument available. It is FUTURES, not spot —
there is a real basis vs. XAU spot (~tens of USD in contango) — so it is labeled
exactly as futures everywhere and never presented as "spot". A true-spot upgrade
would use a keyed metals API and is deliberately deferred (Section 8, step 6).
"""

import datetime as _dt
import json
import urllib.error
import urllib.request

from ..errors import NoObservationError, SourceUnavailableError
from ..observation import SeriesResult

_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"

# symbol -> (instrument label, unit)
_SYMBOLS = {
    "GC=F": ("COMEX front-month gold futures close", "USD/oz"),
    "USDINR=X": ("USD/INR spot FX rate", "INR per USD"),
    "^TNX": ("10-year US Treasury yield", "percent"),
}


def fetch_symbol(symbol: str, start: str, end: str, timeout: int = 20) -> SeriesResult:
    """Fetch daily closes for `symbol` over [start, end] (inclusive, ISO dates).

    Yahoo's chart API takes epoch bounds; we convert the ISO range and pad `end`
    by one day so the final trading day is included. Raises SourceUnavailableError
    on transport/parse failure and NoObservationError on an empty window.
    """
    if symbol not in _SYMBOLS:
        raise SourceUnavailableError("Yahoo", f"unmapped symbol {symbol!r}")
    instrument, unit = _SYMBOLS[symbol]

    p1 = int(_dt.datetime.fromisoformat(start).replace(tzinfo=_dt.timezone.utc).timestamp())
    # +1 day so the close on `end` is inside the half-open [p1, p2) window.
    end_dt = _dt.datetime.fromisoformat(end).replace(tzinfo=_dt.timezone.utc)
    p2 = int((end_dt + _dt.timedelta(days=1)).timestamp())

    url = f"{_CHART}{symbol}?period1={p1}&period2={p2}&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 gold-engine/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceUnavailableError("Yahoo", f"{symbol}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SourceUnavailableError("Yahoo", f"{symbol}: non-JSON response") from exc

    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise SourceUnavailableError("Yahoo", f"{symbol}: {chart['error']}")
    results = chart.get("result")
    if not results:
        raise SourceUnavailableError("Yahoo", f"{symbol}: empty result set")

    result = results[0]
    timestamps = result.get("timestamp") or []
    try:
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SourceUnavailableError("Yahoo", f"{symbol}: missing close series") from exc

    observations = {}
    for ts, close in zip(timestamps, closes):
        if close is None:  # Yahoo nulls out non-trading gaps; skip, never zero-fill
            continue
        date_str = _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).strftime("%Y-%m-%d")
        observations[date_str] = float(close)

    if not observations:
        raise NoObservationError("Yahoo", f"{symbol}: no closes in [{start},{end}]")

    return SeriesResult(
        source=f"Yahoo:{symbol}",
        instrument=instrument,
        unit=unit,
        fetched_at=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        url=url,
        observations=observations,
    )


def fetch_usd_gold(start: str, end: str, timeout: int = 20) -> SeriesResult:
    """USD gold daily close (COMEX front-month futures) over [start, end]."""
    return fetch_symbol("GC=F", start, end, timeout=timeout)


def fetch_usd_inr(start: str, end: str, timeout: int = 20) -> SeriesResult:
    """USD/INR spot FX daily close over [start, end].

    Default USD/INR source: reliable and keyless from this host, on the same
    transport as the gold leg. goldengine.sources.fred.fetch_usd_inr is the
    higher-provenance (official reference rate) alternative, kept for when FRED
    is reachable; the pipeline uses one deterministic source, never silent
    failover between them.
    """
    return fetch_symbol("USDINR=X", start, end, timeout=timeout)
