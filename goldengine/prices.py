"""Assemble sourced series into schema-aligned price rows (Section 5).

This is the assembly layer, kept separate from the pure fetchers. It aligns the
USD gold series and the USD/INR series by date and produces one PriceRow per
gold trading day. It never fabricates: a missing counterpart value yields an
explicit null with a reason, day-over-day change is null when the prior trading
day is unknown, and the MCX field is always null (no free source) with a stated
reason. A clearly-labeled DERIVED rupee-equivalent is provided separately so the
rupee view exists without masquerading as a real MCX close.
"""

from dataclasses import asdict, dataclass
from typing import List, Optional

from .observation import SeriesResult

# Why mcx_inr_gold_close is null in Phase 1. Surfaced in every row so the gap is
# visible, never silently blank.
MCX_NULL_REASON = "no-free-MCX-feed"


@dataclass
class PriceRow:
    date: str

    # --- USD gold leg (Section 5) ---
    usd_gold_close: Optional[float]
    usd_gold_change_pct: Optional[float]
    usd_gold_instrument: str          # exact instrument label (futures, not spot)
    usd_gold_source: str

    # --- MCX / rupee leg (Section 5) ---
    mcx_inr_gold_close: Optional[float]      # always None in Phase 1
    mcx_inr_gold_change_pct: Optional[float]  # always None in Phase 1
    mcx_inr_gold_null_reason: Optional[str]

    # --- USD/INR (structural component of the rupee outcome) ---
    usd_inr_rate: Optional[float]
    usd_inr_source: Optional[str]

    # --- DERIVED, clearly labeled: NOT a real MCX close ---
    usd_gold_inr_equiv: Optional[float]       # usd_gold_close * usd_inr_rate
    usd_gold_inr_equiv_is_derived: bool
    usd_gold_inr_equiv_note: Optional[str]

    def as_dict(self):
        return asdict(self)


def _pct_change(curr: Optional[float], prev: Optional[float]) -> Optional[float]:
    if curr is None or prev is None or prev == 0:
        return None
    return round((curr - prev) / prev * 100.0, 4)


def assemble_price_rows(gold: SeriesResult, usd_inr: SeriesResult) -> List[PriceRow]:
    """Build one row per gold trading day, aligned to USD/INR by exact date.

    Day-over-day change uses the previous available gold trading day; the first
    day in the window has no prior and gets a null change (not fabricated).
    """
    gold_dates = sorted(gold.observations)
    rows: List[PriceRow] = []
    prev_gold: Optional[float] = None

    for date in gold_dates:
        g_close = gold.observations[date]
        inr = usd_inr.value_on(date)  # exact-date match only; no carry-forward

        equiv = None
        equiv_note = None
        if inr is not None:
            equiv = round(g_close * inr, 2)
            equiv_note = (
                f"DERIVED = {gold.instrument} x {usd_inr.instrument}; "
                "not a real MCX/exchange close"
            )
        else:
            equiv_note = "no same-date USD/INR observation; equiv not computed"

        rows.append(
            PriceRow(
                date=date,
                usd_gold_close=round(g_close, 2),
                usd_gold_change_pct=_pct_change(g_close, prev_gold),
                usd_gold_instrument=gold.instrument,
                usd_gold_source=gold.source,
                mcx_inr_gold_close=None,
                mcx_inr_gold_change_pct=None,
                mcx_inr_gold_null_reason=MCX_NULL_REASON,
                usd_inr_rate=round(inr, 4) if inr is not None else None,
                usd_inr_source=usd_inr.source if inr is not None else None,
                usd_gold_inr_equiv=equiv,
                usd_gold_inr_equiv_is_derived=True,
                usd_gold_inr_equiv_note=equiv_note,
            )
        )
        prev_gold = g_close

    return rows
