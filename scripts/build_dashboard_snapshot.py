#!/usr/bin/env python3
"""Assemble ONE real, provenance-stamped JSON snapshot for the dashboard.

Every number in the dashboard comes from here — pulled live from the connectors,
never hand-typed — so the UI cannot drift into "casual data dressed as real"
(Section 6). Not-yet-built stages (forecast, calibration, tradeable accuracy) are
emitted as explicit PENDING objects with honest status text, never fake values.

Usage:
    python scripts/build_dashboard_snapshot.py --start 2026-07-22 --end 2026-08-21
    python scripts/build_dashboard_snapshot.py            # defaults to last 30 days
"""

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from goldengine.backtest import run_backtest  # noqa: E402
from goldengine.calibration import fit as fit_cal  # noqa: E402
from goldengine.entry import compute_entry, real_yield_3m_change  # noqa: E402
from goldengine.errors import PipelineError  # noqa: E402
from goldengine.forecast import make_forecast  # noqa: E402
from goldengine.leakcheck import enforce_cutoff  # noqa: E402
from goldengine.ledger import Ledger, Prediction  # noqa: E402
from goldengine.prices import assemble_price_rows  # noqa: E402
from goldengine.sources import fed_history, fred, treasury, yahoo  # noqa: E402


def _next_business_day(iso: str) -> str:
    return _add_business_days(iso, 1)


def _add_business_days(iso: str, n: int) -> str:
    d = _dt.date.fromisoformat(iso)
    added = 0
    while added < n:
        d += _dt.timedelta(days=1)
        if d.weekday() < 5:  # Mon–Fri
            added += 1
    return d.isoformat()

DISCLAIMER = (
    "Decision-support tool, not financial advice. Forecasts come from a transparent "
    "model (content-v2) with prior-specified weights, not fitted, evaluated "
    "out-of-sample over a full year — every number is computed and measured, never "
    "invented. Reading signal content (FOMC rate decisions, buyback size) barely "
    "moved accuracy and still does NOT beat a naive always-up baseline on either "
    "horizon: public policy is priced in. The value here is transparent reasoning, "
    "not a validated market-beating edge. Do not act on it as a trading signal."
)


def _try(source_name, fn):
    """Run a fetch, returning (result, error_str). Failures are surfaced, not hidden."""
    try:
        return fn(), None
    except PipelineError as exc:
        return None, str(exc)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    today = _dt.date.today()  # track the real day; --end can override for reproducibility
    # Full-year window so the backtest has a real N (dozens of independent weeks).
    ap.add_argument("--start", default=(today - _dt.timedelta(days=365)).isoformat())
    ap.add_argument("--end", default=today.isoformat())
    ap.add_argument("--leak-window-days", type=int, default=45,
                    help="recent slice shown in the interactive leak-guard timeline")
    ap.add_argument("--out", default="data/dashboard_snapshot.json")
    args = ap.parse_args()

    start, end = args.start, args.end
    leak_start = (_dt.date.fromisoformat(end) - _dt.timedelta(days=args.leak_window_days)).isoformat()
    generated_at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

    # --- Prices (outcome variables) ---
    gold, gold_err = _try("gold", lambda: yahoo.fetch_usd_gold(start, end))
    usd_inr, inr_err = _try("usd_inr", lambda: yahoo.fetch_usd_inr(start, end))
    price_rows, price_provenance = [], {}
    if gold and usd_inr:
        price_rows = [r.as_dict() for r in assemble_price_rows(gold, usd_inr)]
        price_provenance = {
            "usd_gold": {"source": gold.source, "instrument": gold.instrument,
                         "unit": gold.unit, "fetched_at": gold.fetched_at},
            "usd_inr": {"source": usd_inr.source, "instrument": usd_inr.instrument,
                        "unit": usd_inr.unit, "fetched_at": usd_inr.fetched_at},
        }

    # --- US signals (Fed FOMC events + Treasury buybacks) ---
    # Fed source: full-year FOMC calendar (statements + minutes), not the
    # recent-only RSS, so the FOMC feature covers the whole backtest window.
    fed_set, fed_err = _try("fed", lambda: fed_history.fetch_fomc_events(start, end))
    tsy_set, tsy_err = _try("treasury", lambda: treasury.fetch_buyback_operations(start, end))
    us_signals = []
    for s in (fed_set.signals if fed_set else []):
        us_signals.append(s)
    for s in (tsy_set.signals if tsy_set else []):
        us_signals.append(s)
    us_signals.sort(key=lambda s: s.published_at)

    # --- Leak cutoff demo: recent slice only, so the timeline stays legible.
    # (The backtest below still uses the FULL-year signal set.)
    display_signals = [s for s in us_signals if s.published_date >= leak_start]
    cutoff = f"{end}T00:00:00Z"
    cut = enforce_cutoff(display_signals, cutoff)
    def _sig(s, status):
        d = s.as_dict()
        d["leak_status"] = status
        return d
    signals_out = ([_sig(s, "input") for s in cut.included]
                   + [_sig(s, "withheld") for s in cut.excluded])
    signals_out.sort(key=lambda d: d["published_at"])

    # --- Latest real close (the primary surface's factual anchor) ---
    latest = price_rows[-1] if price_rows else None

    # --- Investor ENTRY tool: ~20y horizon odds + downside + valuation context ---
    # Robust facts (timing disproven), so this powers the posture — never a buy/sell call.
    # Computed in BOTH USD/oz and INR/10g, since a rupee investor's real returns
    # differ (rupee depreciation adds to INR-gold returns).
    entry = None
    GRAMS_PER_OZ = 31.1034768
    long_start = (_dt.date.fromisoformat(end) - _dt.timedelta(days=365 * 20)).isoformat()
    lg_gold, _ = _try("gold20y", lambda: yahoo.fetch_usd_gold(long_start, end))
    # Context series on Yahoo (fast/reliable) — FRED is too flaky for the daily build.
    inr_set, _ = _try("usd_inr_hist", lambda: yahoo.fetch_usd_inr(long_start, end))
    tnx_set, _ = _try("yield10y", lambda: yahoo.fetch_symbol("^TNX", long_start, end))

    def _ffill(obs, dates):
        out, last = [], None
        for d in dates:
            if d in obs:
                last = obs[d]
            out.append(last)
        return out

    if lg_gold:
        ldates = sorted(lg_gold.observations)
        usd_closes = [lg_gold.observations[d] for d in ldates]
        entry = {"default_basis": "INR", "default_horizon": "6-month",
                 "USD": compute_entry(usd_closes, ldates)}
        entry["USD"]["unit"] = "USD/oz"
        # INR/10g basis over whatever span USD/INR history covers (>=5y required)
        if inr_set:
            rate = _ffill(inr_set.observations, ldates)
            first = next((i for i, r in enumerate(rate) if r is not None), None)
            if first is not None and (len(ldates) - first) >= 252 * 5:
                idates = ldates[first:]
                inr_closes = [usd_closes[first + j] * rate[first + j] / GRAMS_PER_OZ * 10
                              for j in range(len(idates))]
                entry["INR"] = compute_entry(inr_closes, idates)
                entry["INR"]["unit"] = "INR/10g"
        if "INR" not in entry:
            entry["default_basis"] = "USD"  # fall back if USD/INR history unavailable
        # 10-year Treasury yield: macro CONTEXT only (nominal; not a timing signal)
        entry["yield_10y_3m_chg"] = real_yield_3m_change(
            _ffill(tnx_set.observations, ldates)) if tnx_set else None

    # --- LIVE forecasts (next session + ~1 week) + out-of-sample backtests ---
    live_forecast = None
    live_forecast_week = None
    backtest = None
    backtest_week = None
    backtest_v1 = None  # content OFF, for the "did reading content help?" comparison
    scoreboard = None
    calibration = None
    # Weekly knobs: longer trend lookback, lower confidence cap, √5-widened band.
    WEEK = dict(horizon=5, momentum_lookback=5, conf_cap=0.60, vol_scale=5 ** 0.5)
    if price_rows:
        closes = [r["usd_gold_close"] for r in price_rows if r["usd_gold_close"] is not None]
        dates = [r["date"] for r in price_rows if r["usd_gold_close"] is not None]
        # Forecast is LOCKED at generation time, using only signals published before it.
        usable = [s.as_dict() for s in enforce_cutoff(us_signals, generated_at).included]
        sig_dicts = [s.as_dict() for s in us_signals]

        live_forecast = make_forecast(
            closes, dates, usable, generated_at, _next_business_day(dates[-1])
        ).as_dict()
        bt_report = run_backtest(price_rows, sig_dicts)                    # v2 (content)
        backtest = bt_report.as_dict()
        backtest_v1 = run_backtest(price_rows, sig_dicts,
                                   use_content=False).as_dict()           # presence only

        live_forecast_week = make_forecast(
            closes, dates, usable, generated_at, _add_business_days(dates[-1], 5),
            horizon_days=5, momentum_lookback=WEEK["momentum_lookback"],
            conf_cap=WEEK["conf_cap"], vol_scale=WEEK["vol_scale"],
        ).as_dict()
        btw_report = run_backtest(
            price_rows, sig_dicts, horizon=5, momentum_lookback=WEEK["momentum_lookback"],
            conf_cap=WEEK["conf_cap"], vol_scale=WEEK["vol_scale"],
        )
        backtest_week = btw_report.as_dict()

        # ---- Closed loop: ledger (locked→graded) + confidence recalibration ----
        led = Ledger()
        for r in [dict(**d.__dict__, horizon=1) for d in bt_report.days] + \
                 [dict(**d.__dict__, horizon=5) for d in btw_report.days]:
            led.lock(Prediction(
                target_date=r["target_date"], horizon=r["horizon"], made_at="", cutoff="",
                direction=r["direction"], confidence=r["confidence"], prob_up=r["prob_up"],
                mag_low=None, mag_high=None, actual_pct=r["actual_pct"],
                actual_dir=r["actual_dir"], hit=r["hit"], graded_at=""), overwrite=True)
        led.save(str(ROOT / "data" / "prediction_ledger.json"))

        cal = fit_cal([{"prob_up": p.prob_up, "actual_dir": p.actual_dir}
                       for p in led.graded_entries(1)])
        cal_week = fit_cal([{"prob_up": p.prob_up, "actual_dir": p.actual_dir}
                            for p in led.graded_entries(5)])
        # honest (recalibrated) confidence on the live calls
        live_forecast["honest_confidence"] = cal.honest_confidence(live_forecast["prob_up"])
        live_forecast_week["honest_confidence"] = cal_week.honest_confidence(live_forecast_week["prob_up"])

        graded = led.graded_entries(1)
        last = graded[-1] if graded else None
        run_hits = sum(1 for p in graded if p.hit)
        scoreboard = {
            "last_graded": None if last is None else {
                "target_date": last.target_date, "direction": last.direction,
                "confidence": last.confidence,
                "honest_confidence": cal.honest_confidence(last.prob_up),
                "actual_dir": last.actual_dir, "actual_pct": last.actual_pct, "hit": last.hit},
            "running": {"hits": run_hits, "n": len(graded),
                        "rate": round(run_hits / len(graded), 4) if graded else 0.0},
        }
        calibration = {
            "k": cal.k, "n": cal.n,
            "examples": [{"raw": c, "honest": round(cal.honest_confidence(c), 3)}
                         for c in (0.54, 0.60, 0.66)],
        }

    snapshot = {
        "meta": {
            "generated_at": generated_at,
            "window": {"start": start, "end": end},
            "leak_window": {"start": leak_start, "end": end},
            # last actual TRADING day (not the calendar end — avoids implying weekend data)
            "as_of_date": latest["date"] if latest else end,
            "forecast_cutoff": cutoff,
            "phase": "Phase 1 — ingestion pipeline (prices + US signals)",
            "disclaimer": DISCLAIMER,
        },
        "pipeline_status": {
            "prices": {"ok": bool(price_rows), "error": price_err(gold_err, inr_err)},
            "fed_signals": {"ok": bool(fed_set), "error": fed_err},
            "treasury_signals": {"ok": bool(tsy_set), "error": tsy_err},
        },
        "latest_price": latest,
        "price_provenance": price_provenance,
        "entry": entry,
        "prices": price_rows,
        "signals": signals_out,
        "live_forecast": live_forecast,
        "live_forecast_week": live_forecast_week,
        "backtest": backtest,
        "backtest_week": backtest_week,
        "backtest_v1": backtest_v1,
        "scoreboard": scoreboard,
        "calibration": calibration,
        "model": {
            "name": "content-v2",
            "label": "Transparent model · reads signal content · prior-specified weights",
            "factors": ["3-day price momentum",
                        "FOMC rate decision (cut=dovish/bullish, hike=hawkish/bearish)",
                        "Treasury buyback, scaled by size vs. recent norm"],
            "caveat": "v2 reads what signals SAY (rate decision, buyback size), not just "
                      "that they fired. Weights are prior-specified, not fitted, so the "
                      "backtest is out-of-sample. Reading content barely moved accuracy and "
                      "still does not beat a naive baseline — public policy is priced in. "
                      "The value is transparent reasoning, not a market-beating edge.",
        },
        "leak_demo": {
            "cutoff": cutoff,
            "included": len(cut.included),
            "withheld": len(cut.excluded),
            "rule": "a signal informs the forecast only if published strictly before the cutoff",
        },
        "coverage": {
            "US": {"prices": bool(price_rows), "Fed": bool(fed_set),
                   "Treasury_buybacks": bool(tsy_set),
                   "BLS_BEA": False, "note": "BLS/BEA + Treasury press-release program announcements pending"},
            "India": {"usd_inr": bool(price_rows), "RBI": False, "CBIC": False, "MCX": False,
                      "note": "USD/INR live; RBI/CBIC/MCX signal connectors pending; MCX gold close has no free feed"},
            "China": {"PBoC": False, "SGE": False,
                      "note": "pending; China signals carry a mandatory confidence discount when built"},
        },
        "pending_stages": {
            "forecast": {"status": "pending",
                         "reason": "no trained forecasting model yet (brief Phase 3-4)",
                         "when": "after a leak-free historical backtest over dozens+ of days"},
            "calibration": {"status": "not_measurable_yet",
                            "reason": "needs the backtest sample; a single day is an anecdote, not a test",
                            "definition": "do 70%-confidence calls come true ~70% of the time?"},
            "tradeable_accuracy": {"status": "not_proven",
                                   "reason": "separate, higher bar than calibration; requires beating market efficiency, validated by real statistical backtest",
                                   "warning": "never implied by calibration progress"},
        },
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, indent=2))
    print(f"OK — snapshot -> {out_path}")
    print(f"  prices: {len(price_rows)} rows | US signals: {len(us_signals)} "
          f"({len(cut.included)} input / {len(cut.excluded)} withheld @ cutoff)")
    print(f"  pipeline: prices={bool(price_rows)} fed={bool(fed_set)} treasury={bool(tsy_set)}")
    return 0


def price_err(gold_err, inr_err):
    errs = [e for e in (gold_err, inr_err) if e]
    return "; ".join(errs) if errs else None


if __name__ == "__main__":
    raise SystemExit(main())
