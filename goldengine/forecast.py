"""Forecast stage — a transparent, prior-specified baseline model (v1).

This produces the thing the whole project exists for: a next-day call on USD gold
— direction, an expected %-move band, and a confidence — WITH its reasoning tagged
to specific real signals.

Design honesty (non-negotiable):
  * Weights are PRIOR-SPECIFIED from the reference case study's causal logic
    (Treasury liquidity buybacks -> lower long yields -> lower opportunity cost of
    holding gold -> bullish; price momentum; FOMC events raise uncertainty). They
    are NOT fitted to the sample — fitting weights on ~20 days then reporting the
    fit as accuracy would be overfitting dressed as skill. Because the weights are
    fixed in advance, backtest.py can evaluate this model truly out-of-sample.
  * Confidence levels are attached to factor CONFIGURATIONS in advance; the
    backtest then measures whether e.g. 0.62 calls actually hit ~62% (calibration).
  * Magnitude is a band derived from recent realized volatility — never a false
    point estimate.

This is a BASELINE, explicitly labeled as such. Beating it — or even confirming it
clears a coin flip — is an empirical question answered by backtest.py, not asserted.
"""

import datetime as _dt
import statistics as _stats
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

# ---- prior-specified weights (fixed in advance; see module docstring) ----
W_MOMENTUM = 1.0        # sign of 3-day trend
W_BUYBACK = 0.6         # a recent Treasury liquidity-support buyback tilts bullish
CONF_SLOPE = 0.16       # confidence rises with |score|, capped
CONF_MAX = 0.66         # hard cap — a baseline never claims high certainty
W_FOMC = 0.8            # v2: FOMC rate decision as a DIRECTIONAL signal
MOMENTUM_LOOKBACK = 3   # trading days
VOL_LOOKBACK = 10       # trading days for the realized-vol magnitude band
_SCORE_MAX = W_MOMENTUM + W_FOMC + W_BUYBACK  # nominal max |score| for strength scaling


@dataclass(frozen=True)
class Forecast:
    as_of: str                  # cutoff / lock instant (UTC ISO)
    target_date: str            # the trading day being predicted
    horizon_days: int           # 1 = next session, 5 = ~one week
    direction: str              # "up" | "down"
    prob_up: float              # model probability that the close rises
    confidence: float           # max(prob_up, 1-prob_up), as a fraction
    magnitude_low_pct: Optional[float]   # expected |move| band, low
    magnitude_high_pct: Optional[float]  # expected |move| band, high
    reasoning: List[str] = field(default_factory=list)
    factors: Dict[str, object] = field(default_factory=dict)

    def as_dict(self):
        return asdict(self)


def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def make_forecast(closes: List[float], dates: List[str], signals: List[dict],
                  cutoff_iso: str, target_date: str, horizon_days: int = 1,
                  momentum_lookback: int = MOMENTUM_LOOKBACK,
                  conf_cap: float = CONF_MAX, vol_scale: float = 1.0,
                  use_content: bool = True) -> Forecast:
    """Forecast the sign/size of the close move over `horizon_days` from prior data.

    `closes`/`dates` are the gold closes THROUGH the decision day (already
    leak-trimmed by the caller). `signals` are dicts with `tag` and `published_at`,
    already filtered to publish-before-cutoff by the caller (leakcheck.enforce_cutoff).

    Horizon knobs make the longer-horizon call honestly humbler, not falsely bolder:
    a longer `momentum_lookback` (the week's trend), a lower `conf_cap` (more
    uncertainty over 5 days), and a `vol_scale` (~sqrt(h)) that WIDENS the expected
    move band. Direction skill is not assumed to improve with horizon — the backtest
    decides that.
    """
    reasoning, factors = [], {}
    span = "week" if horizon_days >= 5 else ("next session" if horizon_days == 1
                                             else f"{horizon_days} sessions")

    # --- Feature 1: price momentum (trend-following prior) ---
    momentum_sign = 0
    if len(closes) > momentum_lookback:
        prev, past = closes[-1], closes[-1 - momentum_lookback]
        mom_pct = (prev - past) / past * 100 if past else 0.0
        momentum_sign = _sign(mom_pct)
        factors["momentum_pct"] = round(mom_pct, 3)
        if momentum_sign:
            reasoning.append(
                f"Gold has been {'rising' if momentum_sign > 0 else 'falling'} over the last "
                f"{momentum_lookback} days ({mom_pct:+.2f}%), and trends often continue")
    else:
        factors["momentum_pct"] = None

    # --- Feature 2: recent Treasury liquidity buyback (bullish tilt) ---
    cutoff = _parse(cutoff_iso)
    window_start = cutoff - _dt.timedelta(days=4)  # ~1 trading session, weekend-safe

    def _most_recent(pred):
        best = None
        for s in signals:
            if pred(s):
                when = _parse(s["published_at"])
                if window_start <= when < cutoff and (best is None or when > best[0]):
                    best = (when, s)
        return best[1] if best else None

    # buyback tilt is scaled by size vs. the recent norm (v2 content) — a
    # bigger-than-usual operation is a stronger bullish signal.
    buyback = _most_recent(lambda s: s.get("tag") == "treasury_buyback")
    buyback_tilt = 0.0
    factors["recent_buyback"] = bool(buyback)
    if buyback:
        factor = 1.0
        if use_content:
            sizes = [s["magnitude_usd"] for s in signals
                     if s.get("tag") == "treasury_buyback" and s.get("magnitude_usd")]
            sz = buyback.get("magnitude_usd")
            if sizes and sz:
                factor = max(0.5, min(1.5, sz / _stats.median(sizes)))
        buyback_tilt = W_BUYBACK * factor
        factors["buyback_size_factor"] = round(factor, 2)
        note = (f"a {'bigger' if factor > 1.08 else 'smaller' if factor < 0.92 else 'normal'}"
                f"{'-than-usual' if factor < 0.92 or factor > 1.08 else ''}-sized one" if use_content else "one")
        reasoning.append(
            f"The U.S. Treasury bought back bonds last session ({buyback['title']}), " + note
            + " — this tends to push long-term interest rates down, which usually lifts gold")

    # --- Feature 3: recent FOMC decision (v2: DIRECTIONAL from rate change) ---
    fomc = _most_recent(lambda s: s.get("tag", "").startswith("fomc"))
    fomc_tilt = 0.0
    factors["recent_fomc"] = bool(fomc)
    if fomc:
        bps = fomc.get("rate_change_bps")
        if use_content and bps is not None:
            if bps < 0:
                fomc_tilt = W_FOMC          # cut -> dovish -> bullish gold
                reasoning.append(f"The Fed cut interest rates ({abs(bps):.0f} basis points) at its "
                                 "last meeting — lower rates usually lift gold")
            elif bps > 0:
                fomc_tilt = -W_FOMC         # hike -> hawkish -> bearish gold
                reasoning.append(f"The Fed raised interest rates ({bps:.0f} basis points) at its "
                                 "last meeting — higher rates usually weigh on gold")
            else:
                reasoning.append("The Fed left interest rates unchanged at its last meeting "
                                 "— no clear push either way")
            factors["fomc_rate_change_bps"] = bps
        else:
            reasoning.append(f"The Fed recently released meeting notes ({fomc['title']}) "
                             "— a source of uncertainty")

    # --- Combine (prior-specified weights) ---
    score = W_MOMENTUM * momentum_sign + fomc_tilt + buyback_tilt
    factors["score"] = round(score, 3)

    if score > 0:
        direction = "up"
    elif score < 0:
        direction = "down"
    else:  # tie -> fall back to the most recent daily move
        last_move = (closes[-1] - closes[-2]) if len(closes) >= 2 else 0.0
        direction = "up" if last_move >= 0 else "down"
        reasoning.append("No clear signal either way — going with yesterday's direction")

    strength = min(abs(score), _SCORE_MAX) / _SCORE_MAX
    confidence = round(max(0.51, min(conf_cap, 0.5 + CONF_SLOPE * strength)), 2)
    prob_up = confidence if direction == "up" else round(1 - confidence, 2)

    # --- Magnitude band from realized volatility (never a false point) ---
    # For a multi-day horizon the band scales ~sqrt(h): uncertainty compounds.
    lo = hi = None
    if len(closes) > VOL_LOOKBACK:
        rets = [abs((closes[i] - closes[i - 1]) / closes[i - 1] * 100)
                for i in range(len(closes) - VOL_LOOKBACK, len(closes))]
        rets.sort()
        lo = round(_stats.quantiles(rets, n=4)[0] * vol_scale, 2)
        hi = round(_stats.quantiles(rets, n=4)[2] * vol_scale, 2)
        period = "in a week" if horizon_days >= 5 else "in a day"
        reasoning.append(f"Lately gold has typically moved about {lo:.2f}–{hi:.2f}% {period} "
                         "(based on its recent ups and downs)")

    return Forecast(
        as_of=cutoff_iso, target_date=target_date, horizon_days=horizon_days,
        direction=direction, prob_up=prob_up, confidence=confidence,
        magnitude_low_pct=lo, magnitude_high_pct=hi,
        reasoning=reasoning, factors=factors,
    )


def _parse(ts: str) -> _dt.datetime:
    t = ts.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    dt = _dt.datetime.fromisoformat(t)
    return dt if dt.tzinfo else dt.replace(tzinfo=_dt.timezone.utc)
