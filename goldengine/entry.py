"""Entry / horizon read — the investor tool's honest core.

Timing gold has been shown unreliable (see scripts/validate_entry_signal.py), so
this deliberately does NOT emit a market-timing buy/sell signal. It reports the
ROBUST facts that survived 20 years of testing:

  * horizon odds   — over the past ~20y, what share of H-month windows ended
                     positive, and the median move (describes the past, not a
                     forecast);
  * downside band  — the worst-decile forward return over H (the drawdown you
                     might have to sit through);
  * valuation      — where today's price sits vs. the last year (CONTEXT only;
                     a weak predictor — momentum, if anything, not mean-reversion);
  * real-yield tilt— falling/rising 10y real yield (macro CONTEXT; not a reliable
                     timing signal in our tests).

The posture is assembled from these in the UI. It is a decision-support context,
never an instruction — the buy/sell trigger stays with the user.
"""

from typing import Dict, List, Optional

HORIZONS = {"1-month": 21, "3-month": 63, "6-month": 126, "12-month": 252}


def _pct_pos(xs):
    return sum(1 for x in xs if x > 0) / len(xs)


def _median(xs):
    s = sorted(xs); n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _pctile(xs, q):
    s = sorted(xs)
    return s[max(0, min(len(s) - 1, int(q * len(s))))]


def compute_entry(closes: List[float], dates: List[str]) -> Dict:
    """closes/dates: one long daily price history (sorted), in whatever currency
    unit the caller wants displayed (USD/oz, or INR/10g). Odds/downside are ratio
    based, so the horizon stats are unit-free; only as_of_price carries the unit."""
    n = len(closes)
    cur = closes[-1]
    win = closes[-252:] if n >= 252 else closes
    valuation_pct = sum(1 for w in win if w <= cur) / len(win)  # 0..1 (1 = dear vs last yr)
    ma200 = sum(closes[-200:]) / min(200, n)
    above_ma200_pct = (cur / ma200 - 1) * 100

    horizons = {}
    for name, H in HORIZONS.items():
        if n - H < 30:
            continue
        rets = [closes[i + H] / closes[i] - 1 for i in range(0, n - H)]
        horizons[name] = {
            "days": H,
            "n": len(rets),
            "independent": max(1, n // H),
            "pos_pct": round(_pct_pos(rets), 4),
            "median_pct": round(_median(rets) * 100, 2),
            "downside_p10_pct": round(_pctile(rets, 0.10) * 100, 2),
            "upside_p90_pct": round(_pctile(rets, 0.90) * 100, 2),
        }

    return {
        "as_of_price": round(cur, 2),
        "history_years": round(n / 252, 1),
        "valuation_pct": round(valuation_pct, 3),   # percentile vs trailing 1y
        "above_ma200_pct": round(above_ma200_pct, 2),
        "horizons": horizons,
    }


def real_yield_3m_change(real_yield: List[Optional[float]]) -> Optional[float]:
    """3-month change in the 10y real yield (context only). Robust to leading
    gaps: needs only the two endpoints (~3 months apart) to be present."""
    if not real_yield or len(real_yield) <= 64:
        return None
    now, prior = real_yield[-1], real_yield[-64]
    if now is None or prior is None:
        return None
    return round(now - prior, 2)
