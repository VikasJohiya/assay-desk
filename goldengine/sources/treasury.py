"""U.S. Treasury buyback-operations fetcher (US, High tier).

Source: Fiscal Data API `accounting/od/buybacks_operations` — official, JSON,
queryable by date. This is the dataset behind the reference case study's driver:
`operation_type = "Liquidity Support"` buybacks with a per-operation redemption
cap (the "$4B/operation" figure). Each operation carries a real intraday close
time (operation_close_time_est), so we build a precise UTC publish timestamp for
leak-safe cutoffs — converting Eastern time with DST awareness, not a fixed guess.

Scope note: this captures buyback OPERATIONS (with amounts + times). The separate
forward PROGRAM announcement (e.g. "we will double buybacks effective <date>") is
a Treasury press release with no clean feed; it is a documented gap, not faked.
"""

import datetime as _dt
import json

from .._http import HttpError, curl_get
from ..errors import NoObservationError, SourceUnavailableError
from ..signal import Signal, SignalSet

_API = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
        "/v1/accounting/od/buybacks_operations")
_SOURCE = "Treasury:buybacks"

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - fallback if tz database is unavailable
    _ET = None


def _to_utc_iso(op_date: str, close_time_est: str) -> str:
    """Combine operation_date + close time (e.g. '02:00 PM') into a UTC ISO stamp.

    Uses America/New_York (correct EST/EDT offset) when available; otherwise falls
    back to a fixed EDT (-4) offset, which is correct for the summer sample window.
    """
    d = _dt.date.fromisoformat(op_date)
    t = None
    for fmt in ("%I:%M %p", "%H:%M"):
        try:
            t = _dt.datetime.strptime(close_time_est.strip(), fmt).time()
            break
        except (ValueError, AttributeError):
            continue
    if t is None:  # no usable time -> conservative: end-of-ET-day
        t = _dt.time(23, 59)
    naive = _dt.datetime.combine(d, t)
    if _ET is not None:
        aware = naive.replace(tzinfo=_ET)
    else:
        aware = naive.replace(tzinfo=_dt.timezone(_dt.timedelta(hours=-4)))
    return aware.astimezone(_dt.timezone.utc).isoformat(timespec="seconds")


def _amt(row: dict, key: str):
    v = row.get(key)
    if v in (None, "", "null"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _title(row: dict) -> str:
    op = row.get("operation_type") or "buyback"
    bucket = row.get("maturity_bucket") or ""
    cap = _amt(row, "max_par_amt_redeemed")
    accepted = _amt(row, "total_par_amt_accepted")
    parts = [f"Treasury {op} buyback"]
    if bucket:
        parts.append(f"({bucket})")
    tail = []
    if accepted is not None:
        tail.append(f"${accepted / 1e9:.2f}B accepted")
    if cap is not None:
        tail.append(f"${cap / 1e9:.1f}B cap")
    if tail:
        parts.append("— " + ", ".join(tail))
    return " ".join(parts)


def fetch_buyback_operations(start: str, end: str, timeout: int = 25) -> SignalSet:
    """Fetch buyback operations with operation_date in [start, end] (ISO)."""
    url = (f"{_API}?sort=-operation_date"
           f"&filter=operation_date:gte:{start},operation_date:lte:{end}"
           f"&page%5Bsize%5D=100")
    try:
        raw = curl_get(url, timeout=timeout)
    except HttpError as exc:
        raise SourceUnavailableError("Treasury", f"buybacks: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SourceUnavailableError("Treasury", "buybacks: non-JSON response") from exc

    rows = payload.get("data")
    if rows is None:
        raise SourceUnavailableError("Treasury", "buybacks: missing data array")

    fetched_at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    signals = []
    for row in rows:
        op_date = row.get("operation_date")
        if not op_date:
            continue
        published_at = _to_utc_iso(op_date, row.get("operation_close_time_est") or "")
        signals.append(Signal(
            country="US",
            source=_SOURCE,
            category="Debt Management",
            tag="treasury_buyback",
            title=_title(row),
            url=("https://www.treasurydirect.gov/GA-FI/FedInvest/buybacks "
                 f"[op {op_date}]"),
            published_at=published_at,
            published_date=op_date,
            confidence_discount=False,  # US is High tier
            fetched_at=fetched_at,
            magnitude_usd=_amt(row, "total_par_amt_accepted"),  # content: size
        ))

    if not signals:
        raise NoObservationError("Treasury", f"buybacks: none in [{start},{end}]")

    signals.sort(key=lambda s: s.published_at)
    return SignalSet(country="US", source=_SOURCE, fetched_at=fetched_at,
                     url=url, signals=signals)
