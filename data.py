"""Price data. PAXG (gold token) candles, shifted to spot XAUUSD level."""
import time
from core import Candle

BINANCE = ["https://data-api.binance.vision/api/v3/klines",   # public mirror, works from US servers
           "https://api.binance.com/api/v3/klines"]
OKX = "https://www.okx.com/api/v5/market/candles"
SWISSQUOTE = "https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/XAU/USD"
UA = {"User-Agent": "Mozilla/5.0 GoldLive"}


def _binance(session, interval, limit):
    last = None
    for url in BINANCE:
        try:
            r = session.get(url, params={"symbol": "PAXGUSDT", "interval": interval, "limit": limit},
                            timeout=15, headers=UA)
            r.raise_for_status()
            now = time.time() * 1000
            return [Candle(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]))
                    for k in r.json() if int(k[6]) < now]           # closed candles only
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def _okx(session, interval, limit):
    bar = {"5m": "5m", "1h": "1H"}[interval]
    r = session.get(OKX, params={"instId": "PAXG-USDT", "bar": bar, "limit": min(limit, 300)},
                    timeout=15, headers=UA)
    r.raise_for_status()
    rows = r.json().get("data", [])
    return [Candle(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]))
            for k in reversed(rows) if len(k) < 9 or k[8] == "1"]


def fetch_candles(session, interval, limit):
    """Returns (candles, source_name). Raises if every source fails."""
    errors = []
    for name, fn in (("Binance PAXG", _binance), ("OKX PAXG", _okx)):
        try:
            c = fn(session, interval, limit)
            if len(c) >= 50:
                return c, name
            errors.append(f"{name}: too few candles")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
    raise RuntimeError("; ".join(errors))


def fetch_spot(session):
    """Spot XAU/USD mid price from Swissquote, or None."""
    try:
        r = session.get(SWISSQUOTE, timeout=10, headers=UA)
        r.raise_for_status()
        p = r.json()[0]["spreadProfilePrices"][0]
        return (float(p["bid"]) + float(p["ask"])) / 2
    except Exception:  # noqa: BLE001
        return None


def shift(candles, offset):
    return [Candle(x.t, x.o + offset, x.h + offset, x.l + offset, x.c + offset, x.v) for x in candles]


def spot_offset(spot, paxg_last, previous=0.0):
    """Difference spot - PAXG. Ignore crazy values; smooth with the previous offset."""
    if spot is None:
        return previous, False
    off = spot - paxg_last
    if abs(off) > 0.02 * paxg_last:
        return previous, False
    return (off if previous == 0 else 0.7 * off + 0.3 * previous), True
