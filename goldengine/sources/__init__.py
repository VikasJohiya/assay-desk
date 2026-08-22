"""Pure, low-level data fetchers.

Each function here takes an EXPLICIT bounded date range and returns real,
sourced observations keyed by date. They contain no cutoff/leak logic and no
assembly logic — that lives in the consuming scripts (backfill vs live), which
are kept separate on purpose (Section 6.2: separate codepaths).

Every observation returned carries its own provenance so downstream code can
enforce point-in-time cutoffs and cite the source inline.
"""

__all__ = ["fed", "fed_history", "fred", "treasury", "yahoo"]
