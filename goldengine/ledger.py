"""Prediction ledger — the memory of the closed loop.

Each forecast is written here ONCE, locked, before its outcome is known. Later,
when the target day's close exists, the entry is GRADED (the outcome is appended
— the prediction itself is never edited). This immutability is what makes the
track record honest: you can only fairly score a call that was frozen in advance.

Persisted as JSON so predictions accumulate across days (the live loop appends;
the historical replay seeds it). A prediction is keyed by (target_date, horizon):
re-locking the same slot is refused, so a genuine forward record can't be
silently rewritten.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Prediction:
    target_date: str            # the day being predicted
    horizon: int                # 1 = next session, 5 = ~week
    made_at: str                # when it was locked (UTC ISO)
    cutoff: str                 # data cutoff used
    direction: str              # "up" | "down"
    confidence: float           # raw model confidence
    prob_up: float              # raw model P(up)
    mag_low: Optional[float]
    mag_high: Optional[float]
    reasoning: List[str] = field(default_factory=list)
    # --- outcome (appended at grading; None until then) ---
    actual_pct: Optional[float] = None
    actual_dir: Optional[str] = None
    hit: Optional[bool] = None
    graded_at: Optional[str] = None

    @property
    def key(self):
        return (self.target_date, self.horizon)

    @property
    def graded(self) -> bool:
        return self.actual_dir is not None


class Ledger:
    def __init__(self, preds: Optional[List[Prediction]] = None):
        self._by_key: Dict[tuple, Prediction] = {}
        for p in (preds or []):
            self._by_key[p.key] = p

    # ---- persistence ----
    @classmethod
    def load(cls, path) -> "Ledger":
        p = Path(path)
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text())
        return cls([Prediction(**e) for e in raw])

    def save(self, path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps([asdict(p) for p in self.sorted()], indent=2))

    # ---- mutation ----
    def lock(self, pred: Prediction, overwrite: bool = False) -> bool:
        """Record a prediction. Refuses to overwrite an existing locked slot
        (unless overwrite=True, used only by the deterministic replay)."""
        if pred.key in self._by_key and not overwrite:
            return False
        self._by_key[pred.key] = pred
        return True

    def grade(self, closes_by_date: Dict[str, float]) -> int:
        """Fill outcomes for any ungraded prediction whose target close is known.
        Needs the close on target_date AND the prior trading day's close to form
        the % move. Returns how many were newly graded."""
        dates = sorted(closes_by_date)
        idx = {d: i for i, d in enumerate(dates)}
        graded = 0
        for p in self._by_key.values():
            if p.graded or p.target_date not in idx:
                continue
            i = idx[p.target_date]
            if i == 0:
                continue
            base = closes_by_date[dates[i - 1]]
            close = closes_by_date[p.target_date]
            if base in (None, 0) or close is None:
                continue
            pct = (close - base) / base * 100
            p.actual_pct = round(pct, 3)
            p.actual_dir = "up" if pct >= 0 else "down"
            p.hit = (p.direction == p.actual_dir)
            graded += 1
        return graded

    # ---- reads ----
    def sorted(self) -> List[Prediction]:
        return sorted(self._by_key.values(), key=lambda p: (p.target_date, p.horizon))

    def graded_entries(self, horizon: int = 1) -> List[Prediction]:
        return [p for p in self.sorted() if p.horizon == horizon and p.graded]

    def as_dicts(self) -> List[dict]:
        return [asdict(p) for p in self.sorted()]
