"""Turns candles + news into one JSON-ready analysis result."""
from .core import (atr, ema, liquidity_pools, killzone, market_open, utc, KH_OFFSET_H, HOUR)
from .strategy import find_setup, watch_plan, MIN_SCORE
from .news import news_block


def kh_time(ms):
    d = utc(ms + KH_OFFSET_H * HOUR)
    return d.strftime("%H:%M")


def analyze(c5, c1h, now_ms, news_events=None):
    news_events = news_events or []
    c5 = [x for x in c5 if market_open(x.t)]
    c1h = [x for x in c1h if market_open(x.t)]
    if not market_open(now_ms):
        return {"status": "CLOSED", "price": c5[-1].c if c5 else None,
                "headline": "ផ្សារមាសបិទ (ចុងសប្តាហ៍)",
                "summary": "ផ្សារនឹងបើកវិញថ្ងៃច័ន្ទ ម៉ោងប្រហែល 05:00 ព្រឹក (ម៉ោងកម្ពុជា)។",
                "checklist": [], "pools": [], "plans": {}, "setup": None, "bias": None}

    price = c5[-1].c
    a = atr(c5[-60:], 14)
    closes = [x.c for x in c1h]
    e = ema(closes, 50)
    ema50 = e[-1] if e else price
    bias = "bull" if closes and closes[-1] > ema50 else "bear"
    slope_ok = len(e) > 4 and ((e[-1] > e[-4]) == (bias == "bull"))
    kz = killzone(now_ms)
    block = news_block(news_events, now_ms)

    pools = liquidity_pools(c5, c1h, now_ms, a)
    setup = find_setup(c5, pools, a, bias, block is not None)
    signal = setup if setup and setup["score"] >= MIN_SCORE and not block else None

    plans = {s: watch_plan(s, price, pools, a) for s in ("sell", "buy")}

    bias_km = "ឡើង" if bias == "bull" else "ចុះ"
    checklist = [
        {"ok": slope_ok, "text": f"និន្នាការ 1H {bias_km} (EMA50 = {ema50:.2f})"
                                 + ("" if slope_ok else " — EMA មិនទាន់ស្របទិស")},
        {"ok": kz is not None, "text": f"ក្នុង {kz} Killzone" if kz else
            "នៅក្រៅ Killzone (London 14–17 / New York 19–22)"},
        {"ok": bool(setup), "text": f"Liquidity Sweep នៃ {setup['swept']}" if setup else
            "មិនទាន់មាន Liquidity Sweep"},
        {"ok": bool(setup), "text": "MSS (បំបែករចនាសម្ព័ន្ធ)" if setup else "មិនទាន់មាន MSS"},
        {"ok": bool(setup), "text": "មាន FVG សម្រាប់ចូល" if setup else "មិនទាន់មាន FVG"},
        {"ok": block is None, "text": "គ្មានព័ត៌មានធំក្នុងពេលឆាប់ៗ" if block is None else
            f"ព័ត៌មានធំ៖ {block['title']} ម៉ោង {kh_time(block['time_ms'])}"},
    ]

    if signal:
        side_km = "លក់" if signal["side"] == "sell" else "ទិញ"
        status = signal["side"].upper()
        headline = f"សញ្ញា{side_km} — ពិន្ទុ {signal['score']}/100"
        summary = (f"តម្លៃបានបោស liquidity នៅ {signal['swept']} ({signal['swept_price']:.2f}) "
                   f"បន្ទាប់មកមាន MSS និង FVG។ រង់ចាំតម្លៃត្រឡប់មកតំបន់ចូល "
                   f"{signal['entry_bottom']:.2f} – {signal['entry_top']:.2f}។")
    else:
        status = "WAIT"
        headline = "រង់ចាំ — មិនទាន់មាន setup ពេញលេញ"
        if block:
            summary = f"មានព័ត៌មានធំ ({block['title']}) — កុំចូលពាណិជ្ជកម្មនៅពេលនេះ។"
        elif setup:
            summary = (f"មាន setup {setup['side'].upper()} តែពិន្ទុទាប ({setup['score']}/100) "
                       "ដូច្នេះមិនទាន់ផ្ញើសញ្ញា។")
        else:
            summary = ("រង់ចាំតម្លៃបោស liquidity (PDH/PDL/Asian/Equal) "
                       "ហើយមាន MSS និង FVG សិន។")

    return {
        "status": status, "price": price, "atr": a, "headline": headline, "summary": summary,
        "bias": {"dir": bias, "ema50": ema50, "slope_ok": slope_ok},
        "killzone": kz, "setup": signal, "weak_setup": setup if setup and not signal else None,
        "plans": plans, "checklist": checklist,
        "pools": [p.to_dict() for p in sorted(pools, key=lambda p: -p.price)],
        "news_block": block,
    }
