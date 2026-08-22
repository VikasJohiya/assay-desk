#!/usr/bin/env python3
"""Does 'good entry' beat buying anytime — and does it depend on horizon?

Pre-registered, leak-safe test over ~20 years. Conditions are known at day t
(valuation vs. the last year, and whether real yields are falling); the outcome
is the forward return over horizon H. We compare FAVOURABLE vs UNFAVOURABLE vs
just-buy-ANYTIME (the drift baseline), at 1 / 3 / 6 / 12 months, and also report
the DOWNSIDE (worst-decile forward return) so a horizon can be matched to how
much drawdown one can sit through.

Honest read of the result is the point — including how many INDEPENDENT windows
each horizon really has (≈ total_days / H).
"""

import datetime as _dt
import json
import subprocess
import urllib.parse
import urllib.request

HORIZONS = {"1-month": 21, "3-month": 63, "6-month": 126, "12-month": 252}


def yf(sym):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote(sym) + "?range=20y&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.load(urllib.request.urlopen(req, timeout=30))
    r = d["chart"]["result"][0]
    out = {}
    for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]):
        if c is not None:
            out[_dt.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")] = float(c)
    return out


def fred(series):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd=2005-01-01"
    out = subprocess.run(["curl", "-sS", "--http1.1", "--max-time", "30", url],
                         capture_output=True, text=True).stdout
    d = {}
    for line in out.splitlines():
        p = line.split(",")
        if len(p) == 2 and p[0][:1].isdigit() and p[1] not in ("", "."):
            d[p[0]] = float(p[1])
    return d


def pct_pos(xs):
    return sum(1 for x in xs if x > 0) / len(xs)


def median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def pctile(xs, q):
    s = sorted(xs)
    return s[max(0, min(len(s) - 1, int(q * len(s))))]


def main():
    gold = yf("GC=F")
    ry = fred("DFII10")               # 10-year real (TIPS) yield
    dates = sorted(set(gold) & set(ry))
    closes = [gold[d] for d in dates]
    ryv = [ry[d] for d in dates]
    n = len(dates)
    print(f"aligned days: {n}  ({dates[0]} .. {dates[-1]})  [~20y]\n")

    def stats(rets):
        return (len(rets), pct_pos(rets) * 100, median(rets) * 100, pctile(rets, 0.10) * 100)

    hdr = f"{'horizon':<9} {'condition':<16} {'N':>5} {'%pos':>6} {'median':>8} {'downside(p10)':>13}"
    for name, H in HORIZONS.items():
        buckets = {"anytime": [], "favourable": [], "unfavourable": []}
        for i in range(252, n - H):
            price = closes[i]
            win = closes[i - 251:i + 1]
            valuation_pct = sum(1 for w in win if w <= price) / len(win)  # 1=dear vs last yr
            ry_chg_3m = ryv[i] - ryv[i - 63]                             # <0 = yields falling
            fwd = closes[i + H] / price - 1
            buckets["anytime"].append(fwd)
            if ry_chg_3m < 0 and valuation_pct < 0.75:
                buckets["favourable"].append(fwd)
            elif ry_chg_3m > 0 and valuation_pct >= 0.75:
                buckets["unfavourable"].append(fwd)
        indep = (n - 252) // H
        print(hdr if name == "1-month" else "")
        for cond in ("anytime", "favourable", "unfavourable"):
            N, pp, md, dn = stats(buckets[cond])
            print(f"{name:<9} {cond:<16} {N:>5} {pp:>5.0f}% {md:>+7.1f}% {dn:>+12.1f}%")
        base = pct_pos(buckets["anytime"]) * 100
        fav = pct_pos(buckets["favourable"]) * 100
        print(f"          -> favourable lifts %pos by {fav-base:+.0f} pts vs anytime "
              f"| ~{indep} independent {name} windows\n")


if __name__ == "__main__":
    main()
