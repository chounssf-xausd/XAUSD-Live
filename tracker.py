"""Follows each signal: pending -> open -> TP1 (SL to entry) -> TP2 / breakeven, or SL / expired."""
PENDING_MAX = 24   # 2 hours of 5m candles to reach the entry zone

CLOSED = {"sl", "tp2", "be", "expired"}


def new_trade(setup):
    return {
        "id": f"{setup['side']}-{setup['fvg_t']}",
        "side": setup["side"], "entry_top": setup["entry_top"], "entry_bottom": setup["entry_bottom"],
        "sl": setup["sl"], "tp1": setup["tp1"], "tp2": setup["tp2"],
        "created_t": setup["fvg_t"], "last_t": setup["fvg_t"], "status": "pending",
        "fill": None, "waited": 0, "result_r": None,
    }


def _r(t, price):
    risk = abs(t["sl"] - t["fill"])
    move = (t["fill"] - price) if t["side"] == "sell" else (price - t["fill"])
    return round(move / risk, 2) if risk else 0.0


def update(t, candles):
    """Feed candles newer than t['last_t']; returns list of event names."""
    events = []
    sell = t["side"] == "sell"
    for x in candles:
        if x.t <= t["last_t"] or t["status"] in CLOSED:
            continue
        t["last_t"] = x.t
        hit_sl = (x.h >= t["sl"]) if sell else (x.l <= t["sl"])
        hit_tp1 = (x.l <= t["tp1"]) if sell else (x.h >= t["tp1"])
        hit_tp2 = (x.l <= t["tp2"]) if sell else (x.h >= t["tp2"])
        if t["status"] == "pending":
            t["waited"] += 1
            touched = (x.h >= t["entry_bottom"]) if sell else (x.l <= t["entry_top"])
            if touched:
                t["fill"] = t["entry_bottom"] if sell else t["entry_top"]
                t["status"] = "open"
                events.append("filled")
            elif hit_tp1 or t["waited"] > PENDING_MAX:
                t["status"] = "expired"
                events.append("expired")
                continue
            else:
                continue
        if t["status"] == "open":
            if hit_sl:
                t["status"], t["result_r"] = "sl", -1.0
                events.append("sl")
            elif hit_tp1:
                t["status"] = "tp1"
                t["result_r"] = round(_r(t, t["tp1"]) / 2, 2)   # half closed at TP1
                events.append("tp1")
                if hit_tp2:
                    t["status"] = "tp2"
                    t["result_r"] = round((_r(t, t["tp1"]) + _r(t, t["tp2"])) / 2, 2)
                    events.append("tp2")
        elif t["status"] == "tp1":
            back_to_entry = (x.h >= t["fill"]) if sell else (x.l <= t["fill"])
            if back_to_entry:
                t["status"] = "be"
                events.append("be")
            elif hit_tp2:
                t["status"] = "tp2"
                t["result_r"] = round((_r(t, t["tp1"]) + _r(t, t["tp2"])) / 2, 2)
                events.append("tp2")
    return events


def stats(trades):
    done = [t for t in trades if t["status"] in ("sl", "tp1", "tp2", "be")]
    wins = sum(1 for t in done if t["status"] in ("tp1", "tp2", "be"))
    losses = sum(1 for t in done if t["status"] == "sl")
    total_r = round(sum(t["result_r"] or 0 for t in done), 2)
    rate = round(100 * wins / (wins + losses)) if wins + losses else None
    return {"wins": wins, "losses": losses, "win_rate": rate, "total_r": total_r,
            "expired": sum(1 for t in trades if t["status"] == "expired")}
