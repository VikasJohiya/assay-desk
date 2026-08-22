"""Backtest harness — evaluate the forecast model out-of-sample, leak-safe.

For each trading day t in the window (once enough history exists), it forecasts
the sign of that day's close move using ONLY data published/observed before day t
(price closes through t-1, signals via enforce_cutoff at t's 00:00Z), then scores
the call against what actually happened. It reports the numbers as they fall — a
small-sample hit rate near 50% is a real, honest result, not a failure to hide.

Two metrics, kept separate (Section 6.3):
  * calibration — do the stated confidences match realized hit rates?
  * directional accuracy vs a coin flip / majority class — the seed of the
    (much harder, still-unproven) tradeable-accuracy question.
"""

import datetime as _dt
from dataclasses import dataclass, field
from typing import Dict, List

from .forecast import make_forecast
from .leakcheck import enforce_cutoff
from .signal import Signal


@dataclass
class DayResult:
    target_date: str
    direction: str
    confidence: float
    prob_up: float
    actual_pct: float
    actual_dir: str
    hit: bool


@dataclass
class BacktestReport:
    n: int
    hits: int
    hit_rate: float
    brier: float
    majority_class: str
    majority_rate: float          # baseline: always predict the more common class
    edge_vs_majority: float       # hit_rate - majority_rate
    calibration: List[Dict]       # per confidence bucket: predicted vs realized
    horizon_days: int = 1
    n_effective: int = 0          # independent windows ≈ n/horizon (overlap-adjusted)
    days: List[DayResult] = field(default_factory=list)

    def as_dict(self):
        return {
            "n": self.n, "hits": self.hits, "hit_rate": self.hit_rate,
            "brier": self.brier, "majority_class": self.majority_class,
            "majority_rate": self.majority_rate, "edge_vs_majority": self.edge_vs_majority,
            "calibration": self.calibration, "horizon_days": self.horizon_days,
            "n_effective": self.n_effective,
            "days": [d.__dict__ for d in self.days],
        }


def _to_signal_dicts(signals: List[Signal]) -> List[dict]:
    return [s.as_dict() if isinstance(s, Signal) else dict(s) for s in signals]


def run_backtest(price_rows: List[dict], signals: List[dict], horizon: int = 1,
                 **fkwargs) -> BacktestReport:
    """price_rows: schema rows (date, usd_gold_close, usd_gold_change_pct), sorted.
    signals: list of Signal-like dicts with tag/published_at.
    horizon: prediction horizon in trading days (1 = next session, 5 = ~week).
    fkwargs: forwarded to make_forecast (momentum_lookback, conf_cap, vol_scale)."""
    rows = [r for r in price_rows if r.get("usd_gold_close") is not None]
    rows.sort(key=lambda r: r["date"])
    closes = [r["usd_gold_close"] for r in rows]
    dates = [r["date"] for r in rows]

    lookback = fkwargs.get("momentum_lookback", 3)
    start = lookback + 1
    days: List[DayResult] = []
    # Decide after close of day i; predict sign(close[i+h] - close[i]).
    for i in range(start, len(rows) - horizon):
        base, future = closes[i], closes[i + horizon]
        actual_pct = (future - base) / base * 100 if base else None
        if actual_pct is None:
            continue
        target_date = dates[i + horizon]
        decision_day = _dt.date.fromisoformat(dates[i]) + _dt.timedelta(days=1)
        cutoff = f"{decision_day.isoformat()}T00:00:00Z"
        # leak-safe signal set: only what published strictly before the decision cutoff
        usable = enforce_cutoff(_as_signals(signals), cutoff).included
        fc = make_forecast(closes[:i + 1], dates[:i + 1],
                           [s.as_dict() for s in usable], cutoff, target_date,
                           horizon_days=horizon, **fkwargs)
        actual_dir = "up" if actual_pct >= 0 else "down"
        days.append(DayResult(
            target_date=target_date, direction=fc.direction, confidence=fc.confidence,
            prob_up=fc.prob_up, actual_pct=round(actual_pct, 3), actual_dir=actual_dir,
            hit=(fc.direction == actual_dir),
        ))

    n = len(days)
    hits = sum(d.hit for d in days)
    hit_rate = round(hits / n, 4) if n else 0.0
    brier = round(sum((d.prob_up - (1 if d.actual_dir == "up" else 0)) ** 2
                      for d in days) / n, 4) if n else 0.0

    ups = sum(1 for d in days if d.actual_dir == "up")
    downs = n - ups
    majority_class = "up" if ups >= downs else "down"
    majority_rate = round(max(ups, downs) / n, 4) if n else 0.0

    calibration = _calibration(days)

    return BacktestReport(
        n=n, hits=hits, hit_rate=hit_rate, brier=brier,
        majority_class=majority_class, majority_rate=majority_rate,
        edge_vs_majority=round(hit_rate - majority_rate, 4),
        calibration=calibration, horizon_days=horizon,
        n_effective=max(1, n // horizon) if n else 0,  # overlap-adjusted
        days=days,
    )


def _calibration(days: List[DayResult]) -> List[Dict]:
    buckets: Dict[float, List[DayResult]] = {}
    for d in days:
        buckets.setdefault(d.confidence, []).append(d)
    out = []
    for conf in sorted(buckets):
        grp = buckets[conf]
        realized = sum(g.hit for g in grp) / len(grp)
        out.append({"stated_confidence": conf, "n": len(grp),
                    "realized_hit_rate": round(realized, 4)})
    return out


class _S:
    """Lightweight Signal-like wrapper so enforce_cutoff (which reads .published_at)
    works on plain dicts."""
    __slots__ = ("_d",)

    def __init__(self, d):
        self._d = d

    def __getattr__(self, k):
        return self._d[k]

    def as_dict(self):
        return dict(self._d)


def _as_signals(signals):
    return [s if hasattr(s, "published_at") else _S(s) for s in signals]
