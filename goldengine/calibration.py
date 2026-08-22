"""Confidence recalibration — the honest core of the calibration loop.

The model states a confidence (e.g. 60%). Whether that number is *honest* is an
empirical question: do 60% calls actually come true ~60% of the time? We answer
it from the graded track record and correct the confidence accordingly.

Method: a one-parameter shrink toward 50/50,
    p_honest = 0.5 + k * (p_raw - 0.5),
with k chosen to best match realized outcomes (least squares on graded history):
    k = sum(u*y) / sum(u*u),   u = p_raw-0.5,  y = actual_up-0.5,  clamped to [0,1].

k = 1 -> the stated confidence is trustworthy as-is.
k = 0 -> it carries no information; honest confidence is 50% (a coin flip).

Fit on PAST graded calls, applied to FUTURE ones — never the same day twice, so
this is a genuine correction, not hindsight. With no edge, k collapses toward 0,
and the desk honestly reports "~50% sure" instead of a falsely confident number.
"""

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Calibration:
    k: float            # shrink factor in [0,1]
    n: int              # graded calls it was fit on

    def honest_prob_up(self, raw_prob_up: float) -> float:
        return 0.5 + self.k * (raw_prob_up - 0.5)

    def honest_confidence(self, raw_prob_up: float) -> float:
        p = self.honest_prob_up(raw_prob_up)
        return round(max(p, 1 - p), 3)


def fit(graded: List[dict]) -> Calibration:
    """graded: entries with `prob_up` (float) and `actual_dir` ('up'/'down')."""
    num = den = 0.0
    n = 0
    for g in graded:
        if g.get("actual_dir") is None or g.get("prob_up") is None:
            continue
        u = g["prob_up"] - 0.5
        y = (1.0 if g["actual_dir"] == "up" else 0.0) - 0.5
        num += u * y
        den += u * u
        n += 1
    k = (num / den) if den else 0.0
    return Calibration(k=round(max(0.0, min(1.0, k)), 3), n=n)
