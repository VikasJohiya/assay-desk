"""Historical Fed FOMC events from the official FOMC calendar (US, High tier).

The press-release RSS (goldengine.sources.fed) only reaches back ~weeks. For a
full-year backtest we need FOMC events across the year, so this parses the
authoritative FOMC calendar page, which enumerates every meeting with links to
its Statement and Minutes plus the minutes' RELEASE date.

Two event types per meeting, each with a leak-safe original-publish timestamp:
  * fomc_statement — released 2:00 PM ET on the meeting's final day (the date in
    the monetary/minutes URL).
  * fomc_minutes  — released ~3 weeks later, at 2:00 PM ET on the date the
    calendar explicitly labels "Released <Month DD, YYYY>". The minutes URL is
    named by the MEETING date, not the release date — using that would be a leak,
    so we deliberately timestamp minutes by their stated release date instead.

One page fetch covers the whole history; no per-release requests.
"""

import datetime as _dt
import re

from .._http import HttpError, curl_get
from ..errors import NoObservationError, SourceUnavailableError
from ..signal import Signal, SignalSet

_CAL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
_SOURCE = "Fed:fomc_calendar"

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = None


def _et_2pm_utc(d: _dt.date) -> str:
    """2:00 PM ET on `d` as a UTC ISO stamp — the standard FOMC release time."""
    naive = _dt.datetime.combine(d, _dt.time(14, 0))
    aware = naive.replace(tzinfo=_ET) if _ET is not None \
        else naive.replace(tzinfo=_dt.timezone(_dt.timedelta(hours=-4)))
    return aware.astimezone(_dt.timezone.utc).isoformat(timespec="seconds")


def _mk(tag: str, title: str, url: str, published: str,
        rate_change_bps=None) -> Signal:
    return Signal(
        country="US", source=_SOURCE, category="Monetary Policy", tag=tag,
        title=title, url=url, published_at=published,
        published_date=published[:10], confidence_discount=False,
        fetched_at=_FETCHED[0], rate_change_bps=rate_change_bps,
    )


def _fraction_bps(text: str) -> float:
    """Parse the move size, e.g. 'by 1/4 percentage point' -> 25 bps. Default 25."""
    m = re.search(r"by\s+(\d+)/(\d+)\s+percentage point", text)
    if m:
        return round(int(m.group(1)) / int(m.group(2)) * 100, 1)
    m = re.search(r"by\s+(\d+(?:\.\d+)?)\s+percentage point", text)
    if m:
        return round(float(m.group(1)) * 100, 1)
    return 25.0


def _decision_from_statement(mtg: str, timeout: int):
    """Read the actual decision from that meeting's FOMC statement text.

    Uses the reliable Fed site (not FRED). Returns bps (<0 cut, >0 hike, 0 hold),
    or None if the page is unreachable/unparseable — v2 then treats that meeting's
    FOMC as non-directional (graceful, no fabrication, no leak)."""
    url = f"https://www.federalreserve.gov/newsevents/pressreleases/monetary{mtg}a.htm"
    try:
        raw = curl_get(url, timeout=timeout)
    except HttpError:
        return None
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw))
    m = re.search(r"decided to (\w+) the target range", text)
    if not m:
        return None
    verb = m.group(1).lower()
    if verb in ("lower", "reduce", "decrease"):
        return -_fraction_bps(text)          # cut -> dovish -> bullish gold
    if verb in ("raise", "increase"):
        return _fraction_bps(text)           # hike -> hawkish -> bearish gold
    return 0.0                                # maintain/keep -> hold


def _rate_decisions(meeting_dates, start, end, timeout):
    """Map in-window meeting date -> decision bps, read from each statement."""
    out = {}
    for md in meeting_dates:
        try:
            d = _dt.datetime.strptime(md, "%Y%m%d").date().isoformat()
        except ValueError:
            continue
        if start <= d <= end:
            bps = _decision_from_statement(md, timeout)
            if bps is not None:
                out[md] = bps
    return out


_FETCHED = [""]  # set per fetch; keeps _mk simple


def fetch_fomc_events(start: str, end: str, timeout: int = 25) -> SignalSet:
    """FOMC statement + minutes events with published_date in [start, end] (ISO)."""
    try:
        html = curl_get(_CAL, timeout=timeout)
    except HttpError as exc:
        raise SourceUnavailableError("Fed", f"fomc_calendar: {exc}") from exc
    if "fomcminutes" not in html:
        raise SourceUnavailableError("Fed", "fomc_calendar: unexpected page content")

    _FETCHED[0] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

    # meeting date (URL) -> minutes release date (from the "Released ..." label)
    meetings = {}
    for m in re.finditer(r"fomcminutes(\d{8})\.htm", html):
        mtg = m.group(1)
        if mtg in meetings:
            continue
        tail = html[m.end():m.end() + 400]
        rel = re.search(r"Released\s+([A-Z][a-z]+ \d{1,2}, \d{4})", tail)
        meetings[mtg] = rel.group(1) if rel else None

    decisions = _rate_decisions(list(meetings.keys()), start, end, timeout)

    def _decision_phrase(bps):
        if bps is None:
            return ""
        if bps < 0:
            return f" — cut {abs(bps):.0f}bps (dovish)"
        if bps > 0:
            return f" — hike {bps:.0f}bps (hawkish)"
        return " — held rates (neutral)"

    signals = []
    for mtg, rel_label in meetings.items():
        try:
            mtg_date = _dt.datetime.strptime(mtg, "%Y%m%d").date()
        except ValueError:
            continue
        pretty = mtg_date.strftime("%b %d, %Y")
        bps = decisions.get(mtg)

        # Statement: 2:00 PM ET on the meeting's final day; carries the decision.
        stmt_at = _et_2pm_utc(mtg_date)
        if start <= stmt_at[:10] <= end:
            signals.append(_mk(
                "fomc_statement",
                f"FOMC statement (meeting {pretty}){_decision_phrase(bps)}",
                f"https://www.federalreserve.gov/newsevents/pressreleases/monetary{mtg}a.htm",
                stmt_at, rate_change_bps=bps))

        # Minutes: 2:00 PM ET on the stated RELEASE date (never the meeting date).
        if rel_label:
            try:
                rel_date = _dt.datetime.strptime(rel_label, "%B %d, %Y").date()
            except ValueError:
                rel_date = None
            if rel_date:
                min_at = _et_2pm_utc(rel_date)
                if start <= min_at[:10] <= end:
                    signals.append(_mk(
                        "fomc_minutes", f"Minutes of the FOMC, meeting {pretty}",
                        f"https://www.federalreserve.gov/monetarypolicy/fomcminutes{mtg}.htm",
                        min_at))

    if not signals:
        raise NoObservationError("Fed", f"fomc_calendar: no FOMC events in [{start},{end}]")

    signals.sort(key=lambda s: s.published_at)
    return SignalSet(country="US", source=_SOURCE, fetched_at=_FETCHED[0],
                     url=_CAL, signals=signals)
