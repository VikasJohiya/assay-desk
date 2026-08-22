"""Federal Reserve press-release fetcher (US, High tier).

Source: the official "Press Release - All Releases" RSS feed. Each item carries
a <pubDate> = the original publish timestamp (e.g. FOMC minutes at 18:00 GMT =
2:00 PM ET, the real release time), which is exactly the machine-readable,
leak-safe timestamp the signal schema needs. <category> gives a native tag we
normalize; monetary-policy items are the gold-relevant ones, administrative
items (enforcement, banking orders) are tagged too and left for downstream to
filter rather than silently dropped here.

Note: the RSS feed carries only recent releases (roughly the last few months),
which covers the Phase-1 ~60-day window. Deeper history needs the Fed's dated
archive pages — a later addition, flagged in the README.
"""

import datetime as _dt
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from .._http import HttpError, curl_get
from ..errors import NoObservationError, SourceUnavailableError
from ..signal import Signal, SignalSet

_FEED = "https://www.federalreserve.gov/feeds/press_all.xml"
_SOURCE = "Fed:press_all"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


def _tag_for(category: str, title: str) -> str:
    """Normalized tag. Monetary-policy items get a finer, gold-relevant tag."""
    if category == "Monetary Policy":
        t = title.lower()
        if "minutes of the federal open market committee" in t:
            return "fomc_minutes"
        if "fomc" in t and "statement" in t:
            return "fomc_statement"
        if "federal open market committee" in t and "longer-run goals" in t:
            return "fomc_framework"
        if "beige book" in t:
            return "beige_book"
        return "monetary_policy_other"
    return _slug(category)  # e.g. "enforcement_actions", "orders_on_banking_applications"


def fetch_press_releases(start: str, end: str, timeout: int = 25) -> SignalSet:
    """Fetch Fed press releases with a published_date in [start, end] (ISO).

    Range-filters by publish DATE (windowing); the cutoff-time leak check is a
    separate step (goldengine.leakcheck). Raises SourceUnavailableError on
    transport/parse failure and NoObservationError on an empty window.
    """
    try:
        raw = curl_get(_FEED, timeout=timeout)
    except HttpError as exc:
        raise SourceUnavailableError("Fed", f"press_all: {exc}") from exc

    raw = raw.lstrip("﻿").lstrip()
    if not raw.startswith("<"):
        raise SourceUnavailableError("Fed", "press_all: non-XML response")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SourceUnavailableError("Fed", f"press_all: XML parse error: {exc}") from exc

    fetched_at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    signals = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        category = (item.findtext("category") or "").strip()
        pub_raw = (item.findtext("pubDate") or "").strip()
        if not pub_raw:
            continue  # no timestamp -> unusable for leak-safe forecasting; skip
        try:
            pub_dt = parsedate_to_datetime(pub_raw).astimezone(_dt.timezone.utc)
        except (TypeError, ValueError):
            continue
        pub_date = pub_dt.strftime("%Y-%m-%d")
        if pub_date < start or pub_date > end:
            continue

        signals.append(Signal(
            country="US",
            source=_SOURCE,
            category=category,
            tag=_tag_for(category, title),
            title=title,
            url=link,
            published_at=pub_dt.isoformat(timespec="seconds"),
            published_date=pub_date,
            confidence_discount=False,  # US is High tier
            fetched_at=fetched_at,
        ))

    if not signals:
        raise NoObservationError("Fed", f"press_all: no releases in [{start},{end}]")

    signals.sort(key=lambda s: s.published_at)
    return SignalSet(country="US", source=_SOURCE, fetched_at=fetched_at,
                     url=_FEED, signals=signals)
