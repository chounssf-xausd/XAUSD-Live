import math
import os
import tempfile
import unittest
from datetime import datetime, timezone

from analyzer.core import Candle, ema, atr, prev_day_levels, asian_range, market_open, HOUR, MIN
from analyzer.strategy import lot_size, find_setup
from analyzer.analyze import analyze
from analyzer.tracker import new_trade, update, stats
from analyzer.news import news_block, parse_ff
from analyzer.data import spot_offset

NOW = int(datetime(2026, 11, 25, 9, 0, tzinfo=timezone.utc).timestamp() * 1000)   # Wed, London
TUE = int(datetime(2026, 11, 24, tzinfo=timezone.utc).timestamp() * 1000)
WED = TUE + 24 * HOUR

# crafted end of day: dip (swing low 3564), rally, sweep of PDH 3580, displacement down
CRAFT = [
    (3566.0, 3568.0, 3565.0, 3567.0), (3567.0, 3568.0, 3565.5, 3566.0), (3566.0, 3566.5, 3564.0, 3565.0),
    (3565.0, 3567.5, 3564.8, 3567.0), (3567.0, 3570.0, 3566.5, 3569.5), (3569.5, 3573.0, 3569.0, 3572.5),
    (3572.5, 3576.0, 3572.0, 3575.5), (3575.5, 3578.5, 3575.0, 3578.0),
    (3578.0, 3581.5, 3577.5, 3578.5),   # sweep: wick above 3580, close back below
    (3578.5, 3579.0, 3575.0, 3575.5),
    (3575.5, 3576.0, 3563.0, 3563.5),   # MSS: close below 3564
    (3563.5, 3566.5, 3561.5, 3562.5),   # FVG: 3575.0 > 3566.5
    (3562.5, 3564.0, 3561.0, 3563.0),
]


def build_c5():
    out = []
    end = NOW - len(CRAFT) * 5 * MIN
    t, i = TUE, 0
    while t < end:
        p = 3561 + 5 * math.sin(i / 6)
        out.append(Candle(t, p, p + 1.5, p - 1.5, p + 0.2))
        t += 5 * MIN
        i += 1
    for o, h, l, c in CRAFT:
        out.append(Candle(t, o, h, l, c))
        t += 5 * MIN
    return out


def build_c1h():
    out = []
    start = WED + 9 * HOUR - 300 * HOUR
    for k in range(300):
        t = start + k * HOUR
        if TUE <= t < WED:
            h = 3580.0 if t == TUE + 10 * HOUR else 3570.0
            l = 3540.0 if t == TUE + 15 * HOUR else 3555.0
            out.append(Candle(t, 3560, h, l, 3560))
        elif t >= WED:
            out.append(Candle(t, 3565, 3570, 3560, 3565))
        else:
            p = 3700 - k * 0.5
            out.append(Candle(t, p, p + 1, p - 1, p))
    return out


class Basics(unittest.TestCase):
    def test_ema_constant(self):
        self.assertAlmostEqual(ema([5.0] * 10, 3)[-1], 5.0)

    def test_atr_positive(self):
        self.assertGreater(atr(build_c5()[-60:]), 0)

    def test_lot_matches_v3_example(self):
        lot, risk = lot_size(1000, 1, 4.21)
        self.assertEqual((lot, risk), (0.02, 10.0))

    def test_prev_day_skips_weekend(self):
        mon = int(datetime(2026, 11, 23, 9, tzinfo=timezone.utc).timestamp() * 1000)
        fri = mon - 3 * 24 * HOUR
        sun = mon - 24 * HOUR
        bars = [Candle(fri + 5 * HOUR, 1, 10, 1, 5), Candle(sun + 23 * HOUR, 1, 99, 0, 5)]
        self.assertEqual(prev_day_levels(bars, mon), (10, 1))

    def test_prev_day_levels(self):
        self.assertEqual(prev_day_levels(build_c1h(), NOW), (3580.0, 3540.0))

    def test_asian_range_exists(self):
        self.assertIsNotNone(asian_range(build_c5(), NOW))

    def test_weekend_closed(self):
        sat = int(datetime(2026, 11, 28, 12, tzinfo=timezone.utc).timestamp() * 1000)
        self.assertFalse(market_open(sat))
        self.assertTrue(market_open(NOW))
        self.assertEqual(analyze(build_c5(), build_c1h(), sat)["status"], "CLOSED")

    def test_spot_offset(self):
        self.assertEqual(spot_offset(None, 3600, 1.5), (1.5, False))
        self.assertEqual(spot_offset(3590, 3600, 0.0), (-10, True))
        self.assertEqual(spot_offset(5000, 3600, 2.0), (2.0, False))


class Strategy(unittest.TestCase):
    def test_sell_setup_found(self):
        r = analyze(build_c5(), build_c1h(), NOW)
        s = r["setup"]
        self.assertIsNotNone(s, r)
        self.assertEqual(r["status"], "SELL")
        self.assertEqual(s["side"], "sell")
        self.assertEqual(s["swept"], "PDH")
        self.assertEqual((s["entry_top"], s["entry_bottom"]), (3575.0, 3566.5))
        self.assertGreater(s["sl"], 3581.5)
        self.assertLess(s["tp1"], s["entry_bottom"])
        self.assertLess(s["tp2"], s["tp1"])
        self.assertGreaterEqual(s["rr1"], 1.5)
        self.assertGreaterEqual(s["score"], 60)

    def test_buy_is_mirror(self):
        flip = lambda c: [Candle(x.t, 7200 - x.o, 7200 - x.l, 7200 - x.h, 7200 - x.c) for x in c]
        r = analyze(flip(build_c5()), flip(build_c1h()), NOW)
        s = r["setup"]
        self.assertIsNotNone(s)
        self.assertEqual(s["side"], "buy")
        self.assertEqual(s["swept"], "PDL")
        self.assertAlmostEqual(s["entry_bottom"], 7200 - 3575.0)
        self.assertLess(s["sl"], s["entry_bottom"])
        self.assertGreater(s["tp1"], s["entry_top"])

    def test_news_blocks_signal(self):
        ev = [{"title": "CPI", "time_ms": NOW + 10 * MIN, "impact": "High", "forecast": "", "previous": ""}]
        r = analyze(build_c5(), build_c1h(), NOW, ev)
        self.assertEqual(r["status"], "WAIT")
        self.assertIsNone(r["setup"])

    def test_no_setup_in_quiet_market(self):
        c5 = build_c5()[:-len(CRAFT)]
        r = analyze(c5, build_c1h(), NOW - len(CRAFT) * 5 * MIN)
        self.assertEqual(r["status"], "WAIT")
        self.assertTrue(r["plans"]["sell"] and r["plans"]["buy"])


def T(i, o, h, l, c):
    return Candle(1000 + i, o, h, l, c)


class Tracker(unittest.TestCase):
    def setUp(self):
        self.t = new_trade({"side": "sell", "entry_top": 105, "entry_bottom": 100, "sl": 110,
                            "tp1": 90, "tp2": 80, "fvg_t": 1000})

    def test_fill_then_sl_first_when_both(self):
        ev = update(self.t, [T(1, 98, 101, 97, 99), T(2, 99, 111, 89, 95)])
        self.assertEqual(ev, ["filled", "sl"])
        self.assertEqual(self.t["result_r"], -1.0)

    def test_tp1_then_breakeven(self):
        ev = update(self.t, [T(1, 98, 101, 97, 99), T(2, 99, 99, 89, 92), T(3, 92, 100.5, 91, 100)])
        self.assertEqual(ev, ["filled", "tp1", "be"])
        self.assertEqual(stats([self.t])["wins"], 1)

    def test_tp2(self):
        ev = update(self.t, [T(1, 98, 101, 97, 99), T(2, 99, 99, 89, 92), T(3, 92, 93, 79, 80)])
        self.assertEqual(ev[-1], "tp2")
        self.assertEqual(self.t["result_r"], 1.5)

    def test_expired_if_never_filled(self):
        ev = update(self.t, [T(i, 95, 96, 94, 95) for i in range(1, 30)])
        self.assertEqual(ev, ["expired"])

    def test_old_candles_ignored(self):
        update(self.t, [T(1, 98, 101, 97, 99)])
        self.assertEqual(update(self.t, [T(1, 98, 101, 97, 99)]), [])


class News(unittest.TestCase):
    def test_parse_and_block(self):
        raw = [{"title": "Non-Farm Payrolls", "country": "USD", "date": "2026-11-25T04:20:00-05:00",
                "impact": "High"}, {"title": "x", "country": "EUR", "date": "2026-11-25T04:00:00-05:00",
                                    "impact": "High"}]
        ev = parse_ff(raw)
        self.assertEqual(len(ev), 1)
        self.assertIsNotNone(news_block(ev, NOW))          # 09:20 UTC is 20 min away
        self.assertIsNone(news_block(ev, NOW - 2 * HOUR))


class FakeTG:
    def __init__(self, updates):
        self.u, self.sent = updates, []

    def updates(self, offset):
        u, self.u = self.u, []
        return u

    def send(self, chat, text, button_url=None):
        self.sent.append((chat, text))

    def photo(self, chat, path, caption, button_url=None):
        self.sent.append((chat, "PHOTO " + caption))

    def menu_button(self, chat, url):
        pass

    def commands(self):
        pass


def msg(uid, chat, text):
    return {"update_id": uid, "message": {"chat": {"id": chat}, "text": text}}


class MainRun(unittest.TestCase):
    def fetch(self):
        return {"c5": lambda: (build_c5(), "test"), "c1h": lambda: (build_c1h(), "test"),
                "spot": lambda: None, "news": lambda: []}

    def test_owner_signal_once_and_stranger_refused(self):
        import main
        d = tempfile.mkdtemp()
        tg = FakeTG([msg(1, 111, "/start"), msg(2, 222, "/start")])
        out = main.run(d, "x", now_ms=NOW, tg=tg, fetch=self.fetch())
        self.assertEqual(out["status"], "SELL")
        owner_msgs = [t for c, t in tg.sent if c == 111]
        self.assertTrue(any("សញ្ញាថ្មី" in t for t in owner_msgs))
        self.assertTrue(any(c == 222 and "កម្មសិទ្ធិ" in t for c, t in tg.sent))
        state = main.load(os.path.join(d, "state.json"), main.DEFAULT_STATE)
        self.assertEqual(state["owner"], 111)
        tg2 = FakeTG([])
        main.run(d, "x", now_ms=NOW + 60_000, tg=tg2, fetch=self.fetch())
        self.assertFalse(any("សញ្ញាថ្មី" in t for _, t in tg2.sent))
        self.assertTrue(os.path.exists(os.path.join(d, "chart.png")))

    def test_balance_command(self):
        import main
        d = tempfile.mkdtemp()
        tg = FakeTG([msg(1, 5, "/start"), msg(2, 5, "/balance 2500"), msg(3, 5, "/risk abc")])
        main.run(d, "x", now_ms=NOW, tg=tg, fetch=self.fetch())
        state = main.load(os.path.join(d, "state.json"), main.DEFAULT_STATE)
        self.assertEqual(state["balance"], 2500.0)
        self.assertTrue(any("/balance 1000" in t for _, t in tg.sent))

    def test_data_failure_does_not_crash(self):
        import main
        d = tempfile.mkdtemp()

        def boom():
            raise RuntimeError("down")
        f = self.fetch()
        f["c5"] = boom
        self.assertIsNone(main.run(d, None, now_ms=NOW, tg=None, fetch=f))
        self.assertIn("error", main.load(os.path.join(d, "latest.json"), {}))


if __name__ == "__main__":
    unittest.main()
