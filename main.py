"""One analysis round. GitHub runs this every ~5 minutes."""
import json
import os
import time
import traceback
from datetime import datetime, timezone

import requests

from analyzer import data as D
from analyzer.analyze import analyze, kh_time
from analyzer.core import KH_OFFSET_H, HOUR, utc
from analyzer.news import fetch_news, upcoming
from analyzer.tracker import new_trade, update, stats, CLOSED
from bot import messages as M
from bot.chart import render
from bot.telegram import Telegram

DEFAULT_STATE = {"owner": None, "offset_id": 0, "trades": [], "seen": [], "last_daily": None,
                 "balance": 1000.0, "risk_pct": 1.0, "price_offset": 0.0, "fail_count": 0}


def pages_url():
    repo = os.environ.get("GITHUB_REPOSITORY", "owner/gold-live")
    owner, name = repo.split("/")
    owner = owner.lower()
    if name.lower() == f"{owner}.github.io":
        return f"https://{owner}.github.io/"
    return f"https://{owner}.github.io/{name}/"


def load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return {**default, **json.load(fh)} if isinstance(default, dict) else json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return json.loads(json.dumps(default))


def save(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def handle_updates(tg, state, url):
    """Reads new chat messages. Returns set of owner requests like {'status'}."""
    wants = set()
    for u in tg.updates(state["offset_id"] + 1 if state["offset_id"] else 0):
        state["offset_id"] = u["update_id"]
        msg = u.get("message") or {}
        chat = (msg.get("chat") or {}).get("id")
        text = (msg.get("text") or "").strip()
        if not chat or not text.startswith("/"):
            continue
        cmd, *args = text.split()
        cmd = cmd.split("@")[0].lower()
        if state["owner"] is None and cmd == "/start":
            state["owner"] = chat
            tg.commands()
            try:
                tg.menu_button(chat, url)
            except Exception:  # noqa: BLE001
                pass
            tg.send(chat, M.WELCOME, button_url=url)
            wants.add("status")
            continue
        if chat != state["owner"]:
            tg.send(chat, M.PRIVATE)
            continue
        if cmd in ("/start", "/help"):
            tg.send(chat, M.HELP, button_url=url)
        elif cmd == "/status":
            wants.add("status")
        elif cmd in ("/balance", "/risk"):
            key = "balance" if cmd == "/balance" else "risk_pct"
            try:
                val = float(args[0].replace("$", "").replace("%", "").replace(",", ""))
                limit = 10_000_000 if key == "balance" else 10
                if not 0 < val <= limit:
                    raise ValueError
                state[key] = val
                tg.send(chat, f"✅ បានកំណត់ {'ទុន $' if key == 'balance' else 'ហានិភ័យ '}"
                              f"{val:g}{'%' if key == 'risk_pct' else ''}")
            except (IndexError, ValueError):
                tg.send(chat, "សូមវាយដូចនេះ៖ /balance 1000 ឬ /risk 1")
    return wants


def run(store, token, now_ms=None, session=None, tg=None, fetch=None):
    now_ms = now_ms or int(time.time() * 1000)
    session = session or requests.Session()
    os.makedirs(store, exist_ok=True)
    state = load(os.path.join(store, "state.json"), DEFAULT_STATE)
    url = pages_url()
    tg = tg or (Telegram(token, session) if token else None)

    wants = set()
    if tg:
        try:
            wants = handle_updates(tg, state, url)
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    fetch = fetch or {
        "c5": lambda: D.fetch_candles(session, "5m", 600),
        "c1h": lambda: D.fetch_candles(session, "1h", 300),
        "spot": lambda: D.fetch_spot(session),
        "news": lambda: fetch_news(session),
    }
    generated = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).isoformat()
    try:
        c5, source = fetch["c5"]()
        c1h, _ = fetch["c1h"]()
    except Exception as e:  # noqa: BLE001
        state["fail_count"] += 1
        save(os.path.join(store, "latest.json"),
             {"error": f"មិនអាចយកទិន្នន័យតម្លៃបាន៖ {e}", "generated": generated,
              "generated_ms": now_ms})
        if tg and state["owner"] and state["fail_count"] == 3:
            tg.send(state["owner"], "⚠️ មិនអាចយកតម្លៃមាសបាន 3 ដងជាប់គ្នា។ Bot នឹងព្យាយាមម្តងទៀត។")
        save(os.path.join(store, "state.json"), state)
        return None
    state["fail_count"] = 0

    offset, offset_ok = D.spot_offset(fetch["spot"](), c5[-1].c, state["price_offset"])
    state["price_offset"] = offset
    c5, c1h = D.shift(c5, offset), D.shift(c1h, offset)
    try:
        news = fetch["news"]()
    except Exception:  # noqa: BLE001
        news = []

    result = analyze(c5, c1h, now_ms, news)

    # follow open trades
    msgs = []
    for t in state["trades"]:
        if t["status"] not in CLOSED:
            for ev in update(t, c5):
                msgs.append(M.event(t, ev, result["price"]))

    # new signal (once per setup)
    chart_path = os.path.join(store, "chart.png")
    s = result.get("setup")
    new_signal = False
    if s:
        tid = f"{s['side']}-{s['fvg_t']}"
        if tid not in state["seen"]:
            state["seen"] = (state["seen"] + [tid])[-200:]
            trade = new_trade(s)
            update(trade, [x for x in c5 if x.t > trade["created_t"]])
            if trade["status"] in ("pending", "open"):
                state["trades"].append(trade)
                new_signal = True
    state["trades"] = state["trades"][-100:]
    st = stats(state["trades"])

    try:
        render(c5, result, chart_path)
    except Exception:  # noqa: BLE001
        traceback.print_exc()

    if tg and state["owner"]:
        owner, bal, risk = state["owner"], state["balance"], state["risk_pct"]
        try:
            if new_signal:
                tg.photo(owner, chart_path, f"⚡ {M.SIDE[s['side']]} XAUUSD", button_url=url)
                tg.send(owner, M.signal(result, bal, risk))
            for m in msgs:
                tg.send(owner, m)
            kh = utc(now_ms + KH_OFFSET_H * HOUR)
            today = kh.strftime("%Y-%m-%d")
            if kh.hour >= 7 and state["last_daily"] != today and result["status"] != "CLOSED":
                state["last_daily"] = today
                tg.photo(owner, chart_path, "☀️ សង្ខេបមាសថ្ងៃនេះ", button_url=url)
                tg.send(owner, M.daily(result, upcoming(news, now_ms), st, bal, risk, offset_ok))
            elif "status" in wants:
                tg.photo(owner, chart_path, f"{M.STATUS[result['status']]} XAUUSD", button_url=url)
                tg.send(owner, M.status(result, st, bal, risk, offset_ok) + "\n\n" + M.LATE)
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    latest = {**result, "generated": generated, "generated_ms": now_ms,
              "updated_kh": kh_time(now_ms), "source": source, "offset": round(offset, 2),
              "offset_ok": offset_ok, "news": upcoming(news, now_ms, 48),
              "candles": [[x.t, x.o, x.h, x.l, x.c] for x in c5[-120:]],
              "balance": state["balance"], "risk_pct": state["risk_pct"]}
    save(os.path.join(store, "latest.json"), latest)
    save(os.path.join(store, "history.json"),
         {"stats": st, "trades": list(reversed(state["trades"][-40:]))})
    save(os.path.join(store, "state.json"), state)
    return latest


if __name__ == "__main__":
    run(os.environ.get("STORE_DIR", "store"), os.environ.get("TELEGRAM_BOT_TOKEN"))
