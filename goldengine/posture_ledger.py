"""Posture ledger — record the entry posture each day and grade it over its own
horizon, so we can learn whether the posture's read actually held up.

The posture is a DETERMINISTIC function of price history (trailing-year valuation
percentile + horizon), so this is recomputed from the full series each build —
reproducible, never hand-edited. Backfilled over ~20 years, it doubles as an
out-of-sample check on the posture itself: did "don't chase" (high-valuation)
days really make worse entries than "reasonable to accumulate" days, over the
horizon the posture actually speaks to?

Ratio-based (forward *returns*), so it is basis-invariant — INR and USD series
give the same grading, exactly as the posture itself does.
"""

from typing import Dict, List, Sequence

_LABELS = {
    "timing": "Timing barely matters here",
    "dont_chase": "Near its 12-month high (context)",
    "accumulate": "Reasonable to accumulate",
}

# The date prospective recording began. Rows on/after this are our OWN go-forward
# reads — the genuine out-of-sample test, graded against real movement as they
# mature. Earlier rows are BACKFILL (deterministically reconstructed history).
# Stable constant so the boundary never moves; do not reset it on later builds.
GO_LIVE_DATE = "2026-08-24"


def posture_tone(valuation_pct: float, horizon_days: int) -> str:
    """Same rule the dashboard uses: ~1-month = timing-agnostic; near the top of
    the last-year range = don't chase; otherwise reasonable to accumulate."""
    if horizon_days <= 21:
        return "timing"
    if valuation_pct >= 0.85:
        return "dont_chase"
    return "accumulate"


def _valuation_at(closes: Sequence[float], i: int, trailing: int) -> float:
    cur = closes[i]
    win = closes[i - trailing + 1: i + 1]
    return sum(1 for w in win if w <= cur) / len(win)


def _median(xs: List[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def build(closes: Sequence[float], dates: Sequence[str],
          horizons: Sequence[int] = (63, 126, 252),
          primary: int = 126, trailing: int = 252, recent: int = 180) -> Dict:
    """Grade the posture on every day with a full trailing year AND enough
    forward data. Returns per-horizon summaries (grouped by posture tone) plus a
    recent daily log for the primary horizon.
    """
    n = len(closes)

    summary: Dict[str, Dict] = {}
    for H in horizons:
        buckets: Dict[str, List[float]] = {}
        for i in range(trailing - 1, n - H):
            tone = posture_tone(_valuation_at(closes, i, trailing), H)
            buckets.setdefault(tone, []).append(closes[i + H] / closes[i] - 1)
        hz = {}
        for tone, rets in buckets.items():
            pos = sum(1 for r in rets if r > 0)
            hz[tone] = {
                "label": _LABELS[tone],
                "n": len(rets),
                "pct_positive": round(pos / len(rets), 3),
                "median_fwd_pct": round(_median(rets) * 100, 2),
            }
        summary[f"{H // 21}-month"] = hz

    # Recent daily log (primary horizon), most-recent first. Each row captures the
    # posture stand AS IT WOULD HAVE BEEN SHOWN that day — the tone plus the
    # downside/median/upside band from windows completed by then (no look-ahead).
    # When the horizon matures, we grade where the ACTUAL return landed: inside the
    # stated band? above or below the median? So today's read gets a real report
    # card in `primary` trading days, and joins the aggregate below.
    rows = []
    for i in range(max(trailing - 1, n - recent), n):
        val = _valuation_at(closes, i, trailing)
        row = {
            "date": dates[i],
            "price": round(closes[i], 2),
            "valuation_pct": round(val, 3),
            "posture": posture_tone(val, primary),
            "phase": "live" if dates[i] >= GO_LIVE_DATE else "backfill",
        }
        hist = [closes[j + primary] / closes[j] - 1 for j in range(0, i - primary + 1)]
        if hist:  # the band the desk would have shown that day
            hs = sorted(hist)
            row["band_downside_pct"] = round(hs[int(0.10 * len(hs))] * 100, 2)
            row["band_median_pct"] = round(_median(hist) * 100, 2)
            row["band_upside_pct"] = round(hs[int(0.90 * len(hs))] * 100, 2)
        if i + primary < n:  # matured → grade against what actually happened
            fwd = closes[i + primary] / closes[i] - 1
            row["fwd_return_pct"] = round(fwd * 100, 2)
            row["positive"] = fwd > 0
            if hist:
                row["within_band"] = row["band_downside_pct"] <= fwd * 100 <= row["band_upside_pct"]
                row["vs_median"] = "above" if fwd * 100 >= row["band_median_pct"] else "below"
        rows.append(row)
    rows.reverse()

    # Prospective ("live") grading — ONLY rows recorded on/after go-live, graded
    # as they mature. This is the real out-of-sample test of our own reads; it is
    # empty until they reach their horizon, then fills in, separate from backfill.
    live_summary = {}
    for H in horizons:
        buckets: Dict[str, List[float]] = {}
        for i in range(trailing - 1, n - H):
            if dates[i] < GO_LIVE_DATE:
                continue
            tone = posture_tone(_valuation_at(closes, i, trailing), H)
            buckets.setdefault(tone, []).append(closes[i + H] / closes[i] - 1)
        hz = {}
        for tone, rets in buckets.items():
            pos = sum(1 for r in rets if r > 0)
            hz[tone] = {
                "label": _LABELS[tone], "n": len(rets),
                "pct_positive": round(pos / len(rets), 3),
                "median_fwd_pct": round(_median(rets) * 100, 2),
            }
        if hz:
            live_summary[f"{H // 21}-month"] = hz
    live_recorded = sum(1 for d in dates if d >= GO_LIVE_DATE)
    live_matured = sum(1 for i in range(n) if dates[i] >= GO_LIVE_DATE and i + primary < n)

    return {
        "primary_horizon": f"{primary // 21}-month",
        "note": "ratio-based (forward returns) → basis-invariant; posture recomputed from history each build",
        "go_live_date": GO_LIVE_DATE,
        "summary": summary,               # full history (backfill + live)
        "live": {                         # our OWN prospective reads, graded as they mature
            "recorded_days": live_recorded,
            "matured_days": live_matured,
            "summary": live_summary,
        },
        "recent": rows,                   # each tagged phase: "live" | "backfill"
    }
