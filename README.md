# Gold Prediction & Calibration Engine — Phase 1 pipeline

Scripted ingestion pipeline (Section 8, Step 2 of the project brief). Phase-1
country scope: **US, China, India**. Built so far:

- **Price connector** — the outcome-variable leg every schema row depends on.
- **US signal connectors** — Fed press releases + Treasury buyback operations,
  plus the leak-prevention cutoff primitive.
- **Forecast + backtest** — a transparent baseline model and an out-of-sample,
  leak-safe backtest for a next-session and a ~1-week horizon.
- **Closed loop** — a prediction ledger (`ledger.py`) that locks each call and
  grades it the next session, plus confidence recalibration (`calibration.py`).

## Source of record — surfaces & writers (read before adding another)

To avoid the multi-source-of-truth drift this project already hit once:

- **Authoritative surface:** the public GitHub Pages site — https://vikasjohiya.github.io/assay-desk/ . This is the only surface anyone should open day-to-day.
- **Writers (exactly two, same schema):**
  - `daily.yml` — full rebuild (`build_dashboard_snapshot.py` → `build_dashboard.py`), Tue–Sat mornings IST; commits refreshed data + deploys.
  - `intraday.yml` — live-price patch (`update_live_price.py`), every 15 min in market hours; deploys, no data commit.
- **Deprecated:** the private Claude artifact. It does **not** auto-update and must not be treated as "the dashboard." Retire, don't feed.
- **Rule:** a new writer/surface must arrive with a *retirement or a reconciliation* — never additively. The price panel renders **one** layout in all states (≈MCX premium always applied); market-open glow is computed **client-side at view time**, not baked at build.

## Investor entry tool (the current lead) & the timing verdict

The dashboard now **leads with a long-horizon accumulation tool**, not a predictor.
You pick a holding horizon (1/3/6/12mo) and it shows, from ~20 years of history:
historical odds (% of windows positive), the median move, and the **downside**
(worst-decile) — plus where the price sits vs. its last year as **context only**.
It never emits a buy/sell trigger, and every term has a plain-language definition
(the "How to read this" modal). `goldengine/entry.py` computes it;
`scripts/validate_entry_signal.py` holds the test behind it.

**The timing verdict (important, and it refuted the original hypothesis):** a
pre-registered test over 20 years found that "buy when yields fall and gold isn't
stretched" was **worse** than buying anytime at every horizon (−8 to −24pts of
hit-rate); the opposite (momentum / buying strength) did better but is
regime-specific and thin-sampled. Conclusion: **gold timing is not a reliable
edge at any horizon.** What survives is robust and honest: longer holds have had
better odds (1mo 56% → 12mo 68% positive) with bounded downside — a case for
patient accumulation + DCA discipline, not timing. The old daily/weekly forecast
+ closed-loop are kept **below**, relabeled as the experiment that proves why the
tool offers odds+context instead of a daily call.

## Closed loop & calibration

Each forecast is locked in `data/prediction_ledger.json` before its outcome is
known, then graded when the target close exists (immutable: outcomes are appended,
predictions never edited). From the graded record, `calibration.py` fits a
one-parameter shrink `p_honest = 0.5 + k·(p_raw − 0.5)`, fit on past calls and
applied forward. Over the full year **k ≈ 0.31** — the model's confidence carries
only mild information, so a raw "60% sure" is honestly ~53%, a raw 66% ~55%. The
dashboard shows the last graded call, the running record (~51%), and this
raw→honest correction. NOTE this delivers the *calibration* finish line (honest
confidence), not directional edge — the two stay separate. Edge check (real yields
+ dollar) confirmed no next-day edge; see `scripts/experiment_yields_dollar.py`.

Still to come: BLS/BEA (US), RBI/CBIC/MCX (India), PBoC/SGE (China); and model
v2 (signal *content*: FOMC tone, buyback surprise) — see finding below.

## Forecast model & backtest (honest status)

`goldengine/forecast.py` produces a next-day / next-week call (direction, an
expected %-move band, confidence) from **prior-specified** weights — momentum +
recent Treasury liquidity buyback (bullish) + FOMC-uncertainty. Weights are fixed
in advance from the case-study causal logic and **not fitted** to the sample, so
`goldengine/backtest.py` evaluates it **truly out-of-sample** (predict each day
using only earlier data; leak cutoff via `enforce_cutoff`).

**Result over a full year (build_dashboard_snapshot.py default window):**

| Horizon | N (independent) | Hit rate | Naive always-up baseline | Edge |
|---|---|---|---|---|
| Next session | 247 | 50.2% | 57.5% | **−7.3%** |
| ~1 week | 241 (48 weeks) | 52.3% | 58.1% | **−5.8%** |

The baseline has **no demonstrated edge** on either horizon and is
**overconfident** (66%-confidence calls realize ~56%). A small-window run had made
the weekly look strong (75%); with 48 real weeks it collapses to a coin flip —
which is exactly why N matters.

### Model v2 — reading signal content (`use_content=True`, the default)

v2 reads what signals *say*, not just that they fired:
- **FOMC rate decision** parsed from the actual statement text (`fed_history`):
  cut → dovish → bullish gold; hike → hawkish → bearish; hold → neutral. This is
  the rigorous form of "hawkish/dovish tone" — the decision itself, not fragile
  keyword sentiment on boilerplate.
- **Treasury buyback** tilt scaled by the operation's size vs. the recent median
  (bigger-than-usual = stronger bullish).

**Result (full year, out-of-sample):** reading content moved daily accuracy
**50.2% → 51.0%** and weekly **52.3% → 51.9%** — a fraction of a point, still well
below the naive baseline. This is the project's central thesis confirmed with data
(§2): **public policy is priced in within seconds; a scraper + reader does not
out-trade the desks.** v2's value is richer, honest *reasoning* (it now cites the
actual rate decision and buyback size), not a market-beating edge. `backtest_v1`
(content off) is kept in the snapshot so the dashboard can show the delta.

Signal coverage: prices, Treasury buybacks, and **Fed FOMC events all span the
full backtest year**. Fed history comes from `goldengine/sources/fed_history.py`,
which parses the official FOMC calendar for every meeting's Statement (2:00 PM ET
on the meeting's final day) and Minutes (2:00 PM ET on the calendar's stated
RELEASE date — ~3 weeks after the meeting). Timestamping minutes by their release
date, not the meeting date embedded in their URL, is the key leak-safety step.
The recent-only press-release RSS (`sources/fed.py`) is retained as a
complementary feed for non-FOMC releases.

Stdlib only — no `pip install` required. Python 3.9+.

## Layout

```
goldengine/
  errors.py            explicit failure types (fail visibly, never fake)
  observation.py       SeriesResult value object (carries provenance)
  signal.py            Signal / SignalSet value objects (carry publish timestamp)
  leakcheck.py         enforce_cutoff — pure, shared, auditable leak primitive
  _http.py             urllib + curl transports (curl for hosts urllib stalls on)
  prices.py            assembly: align series -> schema-aligned PriceRow
  sources/
    yahoo.py           USD gold (GC=F futures) + USD/INR (USDINR=X)  [DEFAULT]
    fred.py            USD/INR (DEXINUS) — official alternative, see note below
    fed.py             US signals — Federal Reserve press-release RSS (recent only)
    fed_history.py     US signals — FOMC calendar (statements + minutes, full year)
scripts/
  backfill_prices.py       HISTORICAL: price range -> CSV
  live_prices.py           LIVE: latest close -> JSON (or visible failure)
  backfill_signals_us.py   HISTORICAL: US signals -> CSV (+ optional leak cutoff)
data/
  prices_backfill.csv        generated
  us_signals_backfill.csv    generated (+ *_excluded.csv when a cutoff is applied)
```

## Run

```bash
python3 scripts/backfill_prices.py --start 2026-06-01 --end 2026-08-21
python3 scripts/live_prices.py --lookback-days 7
python3 scripts/backfill_signals_us.py --start 2026-08-01 --end 2026-08-21
# with a leak cutoff (only signals published strictly before the instant are kept):
python3 scripts/backfill_signals_us.py --start 2026-08-01 --end 2026-08-21 \
    --cutoff 2026-08-20T00:00:00Z
```

## Sources chosen (Phase 1, keyless) & why

| Schema field | Source | Instrument (exact) | Notes |
|---|---|---|---|
| `usd_gold_close` | Yahoo `GC=F` | **COMEX front-month gold futures close**, USD/oz | Best keyless real instrument. **Futures, not spot** — real basis vs. XAU spot (tens of USD). Labeled as futures everywhere; never called "spot". |
| `usd_inr_rate` | Yahoo `USDINR=X` | USD/INR spot FX, INR per USD | Reliable + keyless on the same transport as gold. |
| `mcx_inr_gold_close` | — | — | **Always `null`** (`null_reason: no-free-MCX-feed`). No free/reliable MCX feed exists; not faked. |
| `usd_gold_inr_equiv` | derived | `usd_gold_close × usd_inr_rate` | **Clearly flagged `is_derived: true`.** A rupee view — explicitly **not** a real MCX/exchange close. |

### Why not FRED for USD/INR (kept, not deleted)
FRED `DEXINUS` is the higher-provenance USD/INR (official reference rate) and
`goldengine/sources/fred.py` still implements it. It was **not** made the default
because FRED's `fredgraph` endpoint is unreliable under programmatic access from
this host — it alternates between ~6s responses and multi-second stalls / HTTP-2
stream resets, succeeding roughly half the time. A daily pipeline needs a
dependable source. The two sources are **never** wired as silent failover (that
would mask an outage); the scripts use one deterministic source. To prefer FRED
when it is reachable, swap `yahoo.fetch_usd_inr` for `fred.fetch_usd_inr` in the
scripts.

## US signals chosen (Phase 1) & why

| Schema field | Source | What it captures | Leak-safety |
|---|---|---|---|
| `us_signals[]` | Federal Reserve "Press Release - All Releases" RSS | FOMC minutes/statements + all Fed press releases | Each item's `<pubDate>` is the **original publish timestamp** to the minute (FOMC minutes = 18:00 GMT / 2:00 PM ET), machine-readable — ideal for hard-cutoff enforcement. |

Every item is tagged from its native `<category>`; monetary-policy items get a
finer tag (`fomc_minutes`, `fomc_statement`, `beige_book`, …). Administrative
items (enforcement actions, banking orders) are tagged and kept, **not silently
dropped** — downstream decides relevance.

### The leak cutoff (`goldengine/leakcheck.py`)
`enforce_cutoff(signals, cutoff)` is the one place point-in-time discipline is
applied: a signal may inform a forecast only if its publish timestamp is
**strictly before** the cutoff. It returns BOTH included and excluded signals so
withholding is always auditable. It **fails safe** — a signal whose timestamp
cannot be parsed is excluded, never optimistically admitted. Worked example
(matches the reference case study): forecasting Aug 20 with a cutoff of
`2026-08-20T00:00:00Z` **includes** the Aug 19 18:00 FOMC minutes and **withholds**
every Aug 20 release to `*_excluded.csv`.

### Fed RSS coverage limit (flagged, not a bug)
The RSS feed carries only recent releases (~last few months), which covers the
Phase-1 ~60-day window. Deeper history needs the Fed's dated archive pages — a
later addition. Treasury has no clean RSS (checked: 302/404), so the next US
source (buyback/issuance announcements, auctions) comes via the Fiscal Data /
TreasuryDirect API.

### Deferred (per brief, Section 8 step 6)
True XAU **spot** gold and a real MCX/INR close both require keyed/paid data
channels — deliberately deferred. When added, `usd_gold_close` should move to a
spot instrument (relabel), and `mcx_inr_gold_close` gets a real feed (its
`null_reason` goes away).

## Integrity guardrails honored

- **Fail visibly (§6.2):** any source down / HTML-challenge / empty payload raises
  a `PipelineError`. Backfill aborts and writes nothing; live emits
  `{"status":"failure", ...}` and exits non-zero. Never a stale/cached/template
  value dressed as real. (The "prediction unavailable — pipeline failure" state.)
- **Separate codepaths (§6.2):** backfill and live own their own range/cutoff and
  assembly logic; they share only the pure fetchers, not data plumbing.
- **No fabrication:** missing counterpart value → explicit null (e.g. Yahoo nulls
  USD/INR on some days → `inr_equiv` is null, **no carry-forward, no interpolation**).
  Day-over-day change is null when the prior trading day is unknown.
- **Per-value provenance:** every value carries `source`, exact `instrument`, and a
  `fetched_at` UTC timestamp — ready for the inline source citation the UI requires.
- **China confidence discount** is a schema concern for the *signal* connectors
  (not yet built); the price leg is US-market-priced and source-labeled.

## Known honest limitations (not bugs)

- `usd_gold_close` is **futures**, carrying a real basis vs. spot. Visible in the
  Aug 20 sample: futures +0.6% vs. the brief's spot −1.05% — expected divergence.
- Yahoo USD/INR has occasional single-day gaps (nulls); those rows honestly carry
  null USD/INR and null `inr_equiv` rather than a filled-in guess.
- MCX/INR gold is absent in Phase 1 by design (no free source).
