"""Shared value objects carried between fetchers and the assembly scripts."""

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class SeriesResult:
    """A real, sourced daily series over a bounded date range.

    `observations` maps an ISO date string (YYYY-MM-DD) -> value. Only dates the
    source actually reported appear; gaps (weekends, holidays, unpublished days)
    are absent, never zero-filled or interpolated.
    """

    source: str            # exact provenance label, e.g. "FRED:DEXINUS"
    instrument: str        # exact instrument, e.g. "COMEX front-month gold futures close"
    unit: str              # e.g. "USD/oz", "INR per USD"
    fetched_at: str        # UTC ISO timestamp of when this fetch ran
    url: str               # the exact request URL, for audit
    observations: Dict[str, float] = field(default_factory=dict)

    def value_on(self, date: str):
        return self.observations.get(date)
