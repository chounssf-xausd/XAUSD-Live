"""Liquidity Sweep + MSS + FVG strategy (sell logic; buy is the mirror image)."""
import math
from dataclasses import replace
from .core import Candle, Pool, swings, killzone, CONTRACT_OZ

LOOKBACK_SWEEP = 24     # look for sweeps in the last 2 hours of 5m candles
MSS_WITHIN = 18         # MSS must follow the sweep within 90 minutes
SETUP_MAX_AGE = 36      # setup older than 3 hours (from MSS) is stale
MIN_SCORE = 60


def lot_size(balance, risk_pct, sl_dist):
    """Returns (lot, risk_dollars). 1 lot = 100 oz, rounded down to 0.01."""
    risk = balance * risk_pct / 100
    if sl_dist <= 0:
        return 0.0, risk
    lot = math.floor(risk / (sl_dist * CONTRACT_OZ) * 100 + 1e-9) / 100
    return lot, risk


def _mirror_candles(c):
    return [Candle(x.t, -x.o, -x.l, -x.h, -x.c, x.v) for x in c]


def _mirror_pools(pools):
    return [replace(p, price=-p.price, kind="low" if p.kind == "high" else "high") for p in pools]


def targets(entry_mid, sl, entry_low, pools, atr):
    """Sell frame: TP below entry. Returns (tp1, tp2, tp1_name, tp2_name)."""
    risk = sl - entry_mid
    lows = sorted([p for p in pools if p.kind == "low" and p.price < entry_low],
                  key=lambda p: -p.price)
    rr = lambda x: (entry_mid - x) / risk
    tp1, n1 = entry_mid - 2 * risk, "គោលដៅ 2R"
    for p in lows:
        if rr(p.price) >= 1.5:
            tp1, n1 = p.price, p.name
            break
    tp2, n2 = entry_mid - max(3.0, rr(tp1) + 1.5) * risk, "គោលដៅ R:R"
    for p in lows:
        if p.price < tp1 and rr(p.price) >= max(2.5, rr(tp1) + 0.8):
            tp2, n2 = p.price, p.name
            break
    return tp1, tp2, n1, n2


def _find_sell(c, pools, a, bias, news_block):
    n = len(c)
    if n < 40 or a <= 0:
        return None
    sw = swings(c)
    highs = [p for p in pools if p.kind == "high"]
    best = None
    for idx in range(max(30, n - LOOKBACK_SWEEP), n):
        for p in highs:
            if not (c[idx].h > p.price and c[idx].c < p.price):
                continue
            prior = c[max(0, idx - 24):idx]
            if prior and max(x.h for x in prior) >= p.price:
                continue                      # level already taken earlier
            lows_before = [s for s in sw if s.kind == "L" and s.i < idx]
            if not lows_before:
                continue
            ref = lows_before[-1].price
            mss = next((j for j in range(idx, min(n, idx + MSS_WITHIN + 1)) if c[j].c < ref), None)
            if mss is None or n - 1 - mss > SETUP_MAX_AGE:
                continue
            sweep_high = max(x.h for x in c[idx:mss + 1])
            fvg = None
            for k in range(idx + 2, min(n, mss + 3)):
                top, bot = c[k - 2].l, c[k].h
                if top - bot >= 0.05 * a and (fvg is None or top - bot > fvg[0] - fvg[1]):
                    fvg = (top, bot, k)
            if not fvg:
                continue
            top, bot, k = fvg
            if any(x.c > sweep_high for x in c[k + 1:]):
                continue                      # invalidated
            mid = (top + bot) / 2
            sl = max(sweep_high + 0.15 * a, mid + 0.5 * a)
            tp1, tp2, n1, n2 = targets(mid, sl, bot, pools, a)
            if any(x.l <= tp1 for x in c[k + 1:]):
                continue                      # already played out
            score = 40
            reasons = []
            if bias == "bear":
                score += 20
                reasons.append("ស្របនិន្នាការ 1H")
            else:
                reasons.append("ប្រឆាំងនិន្នាការ 1H (ប្រុងប្រយ័ត្ន)")
            if p.major:
                score += 15
            kz = killzone(c[mss].t)
            if kz:
                score += 10
                reasons.append(f"កើតក្នុង {kz} Killzone")
            if 0.2 * a <= top - bot <= 1.5 * a:
                score += 10
            if news_block:
                score -= 25
            cand = {
                "side": "sell", "entry_top": top, "entry_bottom": bot, "sl": sl,
                "tp1": tp1, "tp2": tp2, "tp1_name": n1, "tp2_name": n2,
                "rr1": (mid - tp1) / (sl - mid), "rr2": (mid - tp2) / (sl - mid),
                "swept": p.name, "swept_price": p.price,
                "sweep_t": c[idx].t, "mss_t": c[mss].t, "fvg_t": c[k].t, "mss_ref": ref,
                "score": max(0, min(100, score)), "reasons": reasons,
            }
            if best is None or (cand["sweep_t"], cand["score"]) >= (best["sweep_t"], best["score"]):
                best = cand
    return best


def _unmirror(s):
    s = dict(s)
    s["side"] = "buy"
    s["entry_top"], s["entry_bottom"] = -s["entry_bottom"], -s["entry_top"]
    for key in ("sl", "tp1", "tp2", "swept_price", "mss_ref"):
        s[key] = -s[key]
    return s


def find_setup(c, pools, a, bias, news_block=False):
    """Best current setup for either side, or None."""
    sell = _find_sell(c, pools, a, bias == "bear" and "bear" or "x", news_block)
    buy = _find_sell(_mirror_candles(c), _mirror_pools(pools), a,
                     "bear" if bias == "bull" else "x", news_block)
    if buy:
        buy = _unmirror(buy)
    found = [s for s in (sell, buy) if s]
    if not found:
        return None
    return max(found, key=lambda s: (s["mss_t"], s["score"]))


def watch_plan(side, price, pools, a):
    """Conditional plan: where a sweep would set up a trade (not a signal)."""
    if a <= 0:
        return None
    if side == "sell":
        above = sorted([p for p in pools if p.kind == "high" and p.price > price],
                       key=lambda p: (not p.major, p.price - price))
        if not above:
            return None
        lvl = above[0]
        top, bot = lvl.price, lvl.price - 0.35 * a
        mid = (top + bot) / 2
        sl = lvl.price + 1.0 * a
        tp1, tp2, n1, n2 = targets(mid, sl, bot, pools, a)
    else:
        mp = _mirror_pools(pools)
        plan = watch_plan("sell", -price, mp, a)
        if not plan:
            return None
        return {
            "side": "buy", "level": plan["level"], "level_price": -plan["level_price"],
            "entry_top": -plan["entry_bottom"], "entry_bottom": -plan["entry_top"],
            "sl": -plan["sl"], "tp1": -plan["tp1"], "tp2": -plan["tp2"],
            "tp1_name": plan["tp1_name"], "tp2_name": plan["tp2_name"],
            "rr1": plan["rr1"], "rr2": plan["rr2"],
        }
    return {
        "side": "sell", "level": lvl.name, "level_price": lvl.price,
        "entry_top": top, "entry_bottom": bot, "sl": sl, "tp1": tp1, "tp2": tp2,
        "tp1_name": n1, "tp2_name": n2,
        "rr1": (mid - tp1) / (sl - mid), "rr2": (mid - tp2) / (sl - mid),
    }
