"""Signal value objects — the tagged policy/data events feeding us_signals[] etc.

A Signal is one dated event from an official source, carrying the ONE field the
whole leak-prevention discipline hangs on: `published_at`, the original publish
timestamp (Section 6.1). Everything downstream — cutoff enforcement, inline
source citation, delta scoring — reads these fields, so they are exact and
sourced, never inferred.
"""

from dataclasses import asdict, dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class Signal:
    country: str            # "US" | "IN" | "CN"
    source: str             # exact provenance, e.g. "Fed:press_all"
    category: str           # source-native category, e.g. "Monetary Policy"
    tag: str                # normalized tag we assign, e.g. "fomc_minutes"
    title: str
    url: str
    published_at: str       # ISO-8601 UTC — original publish timestamp (cutoff key)
    published_date: str     # YYYY-MM-DD (UTC) convenience for day joins
    confidence_discount: bool  # True only where the source tier is discounted (China)
    fetched_at: str         # UTC ISO timestamp of the fetch
    # --- optional CONTENT (model v2): what the signal says, not just that it fired ---
    magnitude_usd: Optional[float] = None    # e.g. buyback amount accepted (USD)
    rate_change_bps: Optional[float] = None  # FOMC decision: <0 cut (dovish), >0 hike

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class SignalSet:
    """A batch of signals from one source over a bounded range, with provenance."""

    country: str
    source: str
    fetched_at: str
    url: str                # the exact feed/request URL, for audit
    signals: List[Signal] = field(default_factory=list)
