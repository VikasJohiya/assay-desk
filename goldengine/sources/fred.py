"""FRED (Federal Reserve Bank of St. Louis) fetcher — official, timestamped.

Phase-1 use: USD/INR daily reference rate (series DEXINUS). Uses the public
fredgraph CSV endpoint, which needs no API key. Official provenance makes this
the leak-safe backbone for the currency leg of the rupee outcome variable.
"""

import datetime as _dt

from .._http import HttpError, curl_get
from ..errors import NoObservationError, SourceUnavailableError
from ..observation import SeriesResult

_FREDGRAPH_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# Series we understand, with their exact instrument + unit labels.
_SERIES = {
    "DEXINUS": ("India / U.S. Foreign Exchange Rate (daily)", "INR per USD"),
    "DFII10": ("10-Year Treasury inflation-indexed (real) yield", "percent"),
}


def fetch_series(series_id: str, start: str, end: str, timeout: int = 20) -> SeriesResult:
    """Fetch one FRED series over [start, end] (inclusive, ISO dates).

    Raises SourceUnavailableError on transport/parse failure (incl. an HTML
    error page instead of CSV) and NoObservationError if the range is empty.
    """
    if series_id not in _SERIES:
        raise SourceUnavailableError("FRED", f"unmapped series_id {series_id!r}")
    instrument, unit = _SERIES[series_id]

    url = f"{_FREDGRAPH_CSV}?id={series_id}&cosd={start}&coed={end}"
    # curl transport: urllib stalls against FRED from this host (see _http.py).
    try:
        raw = curl_get(url, timeout=timeout)
    except HttpError as exc:
        raise SourceUnavailableError("FRED", f"{series_id}: {exc}") from exc

    # Guardrail: detect an HTML challenge/error page masquerading as a 200.
    head = raw.lstrip()[:200].lower()
    if head.startswith("<") or "<html" in head or "<!doctype" in head:
        raise SourceUnavailableError("FRED", f"{series_id}: HTML response, not CSV")

    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if not lines or "," not in lines[0]:
        raise SourceUnavailableError("FRED", f"{series_id}: unexpected CSV header")

    observations = {}
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        date_str, value_str = parts[0].strip(), parts[1].strip()
        # Defensive: FRED intermittently ignores cosd/coed and returns full
        # history. Trim to the requested window so the fetcher's contract holds.
        if date_str < start or date_str > end:
            continue
        if value_str in ("", "."):  # FRED marks missing values with "."
            continue
        try:
            observations[date_str] = float(value_str)
        except ValueError:
            continue

    if not observations:
        raise NoObservationError("FRED", f"{series_id}: no values in [{start},{end}]")

    return SeriesResult(
        source=f"FRED:{series_id}",
        instrument=instrument,
        unit=unit,
        fetched_at=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        url=url,
        observations=observations,
    )


def fetch_usd_inr(start: str, end: str, timeout: int = 20) -> SeriesResult:
    """USD/INR daily reference rate over [start, end]."""
    return fetch_series("DEXINUS", start, end, timeout=timeout)
