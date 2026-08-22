"""Leak-prevention primitive (Section 6.1) — pure, shared, auditable.

`enforce_cutoff` is the single point where point-in-time discipline is applied:
a signal may inform a forecast only if its ORIGINAL publish timestamp is strictly
before the forecast's data cutoff. It returns BOTH the included and the excluded
signals, so an exclusion is always visible and auditable — never a silent drop.

Both codepaths (backfill and live) call this explicitly with their own cutoff.
It lives here, once and well-tested, rather than being reimplemented inside each
fetcher — where a leak fix could be silently skipped. Fetchers do no cutoff logic.
"""

import datetime as _dt
from dataclasses import dataclass
from typing import List

from .signal import Signal


@dataclass(frozen=True)
class CutoffResult:
    cutoff: str                 # the ISO cutoff applied
    included: List[Signal]      # published strictly before cutoff — usable as input
    excluded: List[Signal]      # published at/after cutoff — withheld (leak risk)

    @property
    def summary(self) -> str:
        return (f"cutoff {self.cutoff}: {len(self.included)} included, "
                f"{len(self.excluded)} excluded")


def _parse(ts: str) -> _dt.datetime:
    # Python 3.9's fromisoformat rejects a trailing "Z"; normalize it to +00:00.
    normalized = ts.strip()
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    dt = _dt.datetime.fromisoformat(normalized)
    if dt.tzinfo is None:  # treat naive as UTC; never guess a local zone
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt


def enforce_cutoff(signals: List[Signal], cutoff_iso: str) -> CutoffResult:
    """Split `signals` by whether they published strictly before `cutoff_iso`.

    Strict inequality: a signal published exactly at the cutoff instant is
    EXCLUDED. When a signal's timestamp cannot be parsed it is excluded and
    surfaced (fail safe — an unverifiable timestamp is treated as a leak risk,
    never optimistically admitted).
    """
    cutoff = _parse(cutoff_iso)
    included, excluded = [], []
    for s in signals:
        try:
            when = _parse(s.published_at)
        except (ValueError, TypeError):
            excluded.append(s)
            continue
        (included if when < cutoff else excluded).append(s)
    return CutoffResult(cutoff=cutoff.isoformat(), included=included, excluded=excluded)
