#!/usr/bin/env python3
"""EDGE-CHECK experiment (isolated — does not touch the live model).

Pre-registered hypothesis: gold's real daily drivers are the 10-year Treasury
yield and the US dollar. We test two DISTINCT things and report the gap:

  (1) Contemporaneous — does gold move OPPOSITE to same-day yield/dollar moves?
      (validates the causal logic; expected: yes, fairly strong)
  (2) Predictive/leak-safe — does YESTERDAY's yield/dollar move predict TOMORROW's
      gold direction? (the actual edge question; expected: little to none)

A real relationship that is NOT predictable is the honest signature of an
efficient market — the whole project's thesis. One pre-registered test, then we
accept the result: no fishing for the one signal that happens to look good.
"""

import datetime as _dt
import json
import statistics as _stats
import urllib.parse
import urllib.request

S, E = "2025-08-21", "2026-08-21"


def fetch(sym):
    p1 = int(_dt.datetime.fromisoformat(S + "T00:00:00").replace(tzinfo=_dt.timezone.utc).timestamp())
    p2 = int((_dt.datetime.fromisoformat(E + "T00:00:00").replace(tzinfo=_dt.timezone.utc) + _dt.timedelta(days=1)).timestamp())
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(sym)
           + f"?period1={p1}&period2={p2}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 gold-engine/exp"})
    d = json.load(urllib.request.urlopen(req, timeout=25))
    r = d["chart"]["result"][0]
    out = {}
    for ts, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]):
        if c is not None:
            out[_dt.datetime.fromtimestamp(ts, _dt.timezone.utc).strftime("%Y-%m-%d")] = float(c)
    return out


def sign(x):
    return 1 if x > 0 else (-1 if x < 0 else 0)


def pearson(xs, ys):  # statistics.correlation is 3.10+; we're on 3.9
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


def main():
    gold = fetch("GC=F")
    tnx = fetch("^TNX")     # 10-year Treasury yield (nominal), percent
    dxy = fetch("DX-Y.NYB")  # US dollar index
    dates = sorted(set(gold) & set(tnx) & set(dxy))
    print(f"aligned trading days: {len(dates)}  ({dates[0]} … {dates[-1]})\n")

    # daily changes
    g_ret, y_chg, d_ret = {}, {}, {}
    for i in range(1, len(dates)):
        a, b = dates[i - 1], dates[i]
        g_ret[b] = (gold[b] - gold[a]) / gold[a] * 100
        y_chg[b] = tnx[b] - tnx[a]                      # yield change, pct points
        d_ret[b] = (dxy[b] - dxy[a]) / dxy[a] * 100
    days = dates[1:]

    # ---- (1) CONTEMPORANEOUS: does gold move opposite to yields / dollar same day? ----
    def agree_opposite(x):  # fraction of days gold moved opposite to driver
        n = [d for d in days if x[d] != 0 and g_ret[d] != 0]
        return sum(1 for d in n if sign(g_ret[d]) != sign(x[d])) / len(n), len(n)

    ay, ny = agree_opposite(y_chg)
    ad, nd = agree_opposite(d_ret)
    cor_y = pearson([g_ret[d] for d in days], [y_chg[d] for d in days])
    cor_d = pearson([g_ret[d] for d in days], [d_ret[d] for d in days])
    print("(1) SAME-DAY relationship (is the causal logic real?)")
    print(f"    gold vs 10y yield : corr {cor_y:+.2f} | gold moved opposite on {ay:.0%} of {ny} days")
    print(f"    gold vs US dollar : corr {cor_d:+.2f} | gold moved opposite on {ad:.0%} of {nd} days")
    print("    (theory: both negative / >50% opposite → relationship is real)\n")

    # ---- (2) PREDICTIVE (leak-safe): yesterday's driver move → tomorrow's gold ----
    # prior rule: bullish if yesterday yields fell and/or dollar fell.
    def backtest(use_mom, use_drivers):
        hits = n = ups = 0
        for i in range(4, len(days)):
            d = days[i]
            prevd = days[i - 1]                     # yesterday (known before today)
            score = 0.0
            if use_mom:
                m = (gold[days[i - 1]] - gold[days[i - 4]])
                score += 1.0 * sign(m)
            if use_drivers:
                score += -0.8 * sign(y_chg[prevd])   # yields fell yesterday -> bullish
                score += -0.6 * sign(d_ret[prevd])   # dollar fell yesterday -> bullish
            pred = "up" if score >= 0 else "down"
            actual = "up" if g_ret[d] >= 0 else "down"
            hits += pred == actual
            ups += actual == "up"
            n += 1
        base = max(ups, n - ups) / n
        return hits / n, base, n

    print("(2) NEXT-DAY prediction (is it an EDGE?) — leak-safe, yesterday → tomorrow")
    for label, mom, drv in [("momentum only", True, False),
                            ("drivers only (yields+dollar)", False, True),
                            ("momentum + drivers", True, True)]:
        hit, base, n = backtest(mom, drv)
        print(f"    {label:<30} hit {hit:.1%}  vs always-up {base:.1%}  edge {hit-base:+.1%}  (N={n})")
    print("\n    Reminder: a strong SAME-DAY link with NO next-day edge = efficient market.")


if __name__ == "__main__":
    main()
