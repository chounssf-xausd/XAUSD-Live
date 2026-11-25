"""Candles, indicators and liquidity levels."""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

MIN = 60_000
HOUR = 60 * MIN
DAY = 24 * HOUR

KH_OFFSET_H = 7                     # Cambodia = UTC+7
ASIA_UTC = (0, 6)                   # Asian session 07:00-13:00 Cambodia
KILLZONES_UTC = {"London": (7, 10), "New York": (12, 15)}   # 14-17 / 19-22 Cambodia
CONTRACT_OZ = 100                   # 1 lot XAUUSD = 100 oz


@dataclass
class Candle:
    t: int      # open time, ms UTC
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0


@dataclass
class Swing:
    i: int
    price: float
    kind: str   # "H" or "L"


@dataclass
class Pool:
    name: str
    price: float
    kind: str   # "high" (buy-side liquidity above) or "low"
    major: bool

    def to_dict(self):
        return asdict(self)


def utc(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def day_start(ms):
    return ms - ms % DAY


def market_open(ms):
    """Spot gold trades Sun 22:00 UTC -> Fri 22:00 UTC (approx.)."""
    d = utc(ms)
    wd = d.weekday()            # Mon=0 ... Sun=6
    if wd == 5:
        return False
    if wd == 4 and d.hour >= 22:
        return False
    if wd == 6 and d.hour < 22:
        return False
    return True


def killzone(ms):
    h = utc(ms).hour
    for name, (a, b) in KILLZONES_UTC.items():
        if a <= h < b:
            return name
    return None


def ema(values, n):
    if not values:
        return []
    k = 2 / (n + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def atr(candles, n=14):
    if len(candles) < 2:
        return 0.0
    trs = []
    for prev, cur in zip(candles, candles[1:]):
        trs.append(max(cur.h - cur.l, abs(cur.h - prev.c), abs(cur.l - prev.c)))
    a = sum(trs[:n]) / min(n, len(trs))
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def swings(c, left=2, right=2):
    out = []
    for i in range(left, len(c) - right):
        if all(c[i].h > c[j].h for j in range(i - left, i)) and \
           all(c[i].h >= c[j].h for j in range(i + 1, i + right + 1)):
            out.append(Swing(i, c[i].h, "H"))
        if all(c[i].l < c[j].l for j in range(i - left, i)) and \
           all(c[i].l <= c[j].l for j in range(i + 1, i + right + 1)):
            out.append(Swing(i, c[i].l, "L"))
    return out


def prev_day_levels(c1h, now_ms):
    """High/low of the last full trading day before today (UTC), skipping weekends."""
    today = day_start(now_ms)
    days = sorted({day_start(x.t) for x in c1h
                   if x.t < today and utc(x.t).weekday() < 5})
    if not days:
        return None
    d = days[-1]
    bars = [x for x in c1h if d <= x.t < d + DAY]
    return max(x.h for x in bars), min(x.l for x in bars)


def asian_range(c5, now_ms):
    start = day_start(now_ms) + ASIA_UTC[0] * HOUR
    end = day_start(now_ms) + ASIA_UTC[1] * HOUR
    bars = [x for x in c5 if start <= x.t < end]
    if len(bars) < 12:
        return None
    return max(x.h for x in bars), min(x.l for x in bars)


def equal_levels(c, sw, tol):
    """Two swing highs (lows) within tol that price has not taken since."""
    out = []
    for kind in ("H", "L"):
        pts = [s for s in sw if s.kind == kind][-8:]
        for a in range(len(pts)):
            for b in range(a + 1, len(pts)):
                if abs(pts[a].price - pts[b].price) > tol or pts[b].i - pts[a].i < 3:
                    continue
                after = c[pts[b].i + 1:]
                if kind == "H":
                    lvl = max(pts[a].price, pts[b].price)
                    if after and max(x.h for x in after) > lvl:
                        continue
                else:
                    lvl = min(pts[a].price, pts[b].price)
                    if after and min(x.l for x in after) < lvl:
                        continue
                if all(k != kind or abs(lvl - o) > tol for k, o in out):
                    out.append((kind, lvl))
    return out


def liquidity_pools(c5, c1h, now_ms, a):
    pools = []
    pd = prev_day_levels(c1h, now_ms)
    if pd:
        pools += [Pool("PDH", pd[0], "high", True), Pool("PDL", pd[1], "low", True)]
    ar = asian_range(c5, now_ms)
    if ar:
        pools += [Pool("Asian High", ar[0], "high", True), Pool("Asian Low", ar[1], "low", True)]
    sw = swings(c5)
    for kind, lvl in equal_levels(c5, sw, max(0.1 * a, 0.3)):
        pools.append(Pool("Equal Highs" if kind == "H" else "Equal Lows", lvl,
                          "high" if kind == "H" else "low", True))
    for kind, name, pk in (("H", "Swing High", "high"), ("L", "Swing Low", "low")):
        for s in [s for s in sw if s.kind == kind][-3:]:
            pools.append(Pool(name, s.price, pk, False))
    return pools
