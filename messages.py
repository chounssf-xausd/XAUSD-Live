"""Khmer Telegram messages (HTML)."""
from html import escape
from analyze import kh_time
from strategy import lot_size

SIDE = {"sell": "🔴 លក់ (SELL)", "buy": "🟢 ទិញ (BUY)"}
STATUS = {"SELL": "🔴 លក់", "BUY": "🟢 ទិញ", "WAIT": "🟡 រង់ចាំ", "CLOSED": "⚪ ផ្សារបិទ"}


def f(x):
    return f"{x:,.2f}"


def _levels(s, balance, risk_pct):
    mid = (s["entry_top"] + s["entry_bottom"]) / 2
    lot, risk = lot_size(balance, risk_pct, abs(s["sl"] - mid))
    dist = abs(s["sl"] - mid)
    lot_txt = (f"{lot:.2f} lot" if lot >= 0.01 else
               f"តិចជាង 0.01 lot — បើប្រើ 0.01 lot នឹងប្រថុយ ${dist:,.2f}")
    return (f"📍 ចូល៖ <b>{f(s['entry_bottom'])} – {f(s['entry_top'])}</b>\n"
            f"🛑 SL៖ <b>{f(s['sl'])}</b> (ចម្ងាយ {abs(s['sl'] - mid):.2f})\n"
            f"🎯 TP1៖ <b>{f(s['tp1'])}</b> R:R 1:{s['rr1']:.1f} ({escape(s['tp1_name'])})\n"
            f"🎯 TP2៖ <b>{f(s['tp2'])}</b> R:R 1:{s['rr2']:.1f} ({escape(s['tp2_name'])})\n"
            f"💰 ហានិភ័យ ${risk:,.2f} → <b>{lot_txt}</b>")


def signal(result, balance, risk_pct):
    s = result["setup"]
    why = "\n".join(f"• {escape(r)}" for r in s["reasons"])
    return (f"<b>⚡ សញ្ញាថ្មី៖ {SIDE[s['side']]} XAUUSD</b>\n"
            f"ពិន្ទុ {s['score']}/100 — តម្លៃឥឡូវ {f(result['price'])}\n\n"
            f"{_levels(s, balance, risk_pct)}\n\n"
            f"<b>មូលហេតុ</b>\n• បោស liquidity {escape(s['swept'])} ({f(s['swept_price'])})\n"
            f"• MSS បំបែក {f(s['mss_ref'])} • មាន FVG\n{why}\n\n"
            "⏳ ដាក់ Limit order ក្នុងតំបន់ចូល។ បើតម្លៃមិនមកក្នុង 2 ម៉ោង សញ្ញានឹងផុតកំណត់។")


EVENT_TEXT = {
    "filled": "✅ តម្លៃចូលដល់តំបន់ចូលហើយ — ការជួញដូរបានបើក",
    "tp1": "🎯 ប៉ះ TP1 ហើយ! បិទពាក់កណ្តាល ហើយផ្លាស់ SL ទៅចំណុចចូល",
    "tp2": "🏆 ប៉ះ TP2 ហើយ! ការជួញដូរបញ្ចប់ដោយចំណេញ",
    "be": "↩️ តម្លៃត្រឡប់មកចំណុចចូលវិញ — បិទនៅចំណុចចូល (មិនខាត)",
    "sl": "🛑 ប៉ះ SL — ខាត 1R។ កុំតាមសងសឹកផ្សារ រង់ចាំ setup បន្ទាប់",
    "expired": "⌛ សញ្ញាផុតកំណត់ — តម្លៃមិនបានមកតំបន់ចូល។ លុប Limit order ចោល",
}


def event(trade, ev, price):
    return (f"<b>{SIDE[trade['side']]}</b> ({f(trade['entry_bottom'])} – {f(trade['entry_top'])})\n"
            f"{EVENT_TEXT[ev]}\nតម្លៃឥឡូវ {f(price)}")


def status(result, stats, balance, risk_pct, offset_ok):
    lines = [f"<b>{STATUS[result['status']]} — XAUUSD {f(result['price']) if result['price'] else ''}</b>",
             escape(result["headline"]), escape(result["summary"]), ""]
    for item in result.get("checklist", []):
        lines.append(("✅ " if item["ok"] else "▫️ ") + escape(item["text"]))
    if result.get("setup"):
        lines += ["", _levels(result["setup"], balance, risk_pct)]
    else:
        for side, p in (result.get("plans") or {}).items():
            if p:
                lines += ["", f"<b>ផែនការរង់ចាំ {SIDE[side]}</b> បើតម្លៃបោស {escape(p['level'])} "
                              f"({f(p['level_price'])})",
                          f"ចូល {f(p['entry_bottom'])} – {f(p['entry_top'])} • SL {f(p['sl'])} "
                          f"• TP1 {f(p['tp1'])} • TP2 {f(p['tp2'])}"]
    if stats and stats["wins"] + stats["losses"]:
        lines += ["", f"📈 លទ្ធផលសញ្ញា៖ ឈ្នះ {stats['wins']} ចាញ់ {stats['losses']} "
                      f"({stats['win_rate']}%) សរុប {stats['total_r']:+.1f}R"]
    if not offset_ok:
        lines.append("\n⚠️ មិនអាចយកតម្លៃ spot បាន — តម្លៃអាចខុសពី OANDA ពីរបីដុល្លារ")
    return "\n".join(lines)


def daily(result, upcoming, stats, balance, risk_pct, offset_ok):
    news = "\n".join(
        f"• {kh_time(e['time_ms'])} {'🔴' if e['impact'] == 'High' else '🟠'} {escape(e['title'])}"
        for e in upcoming[:8]) or "• គ្មានព័ត៌មាន USD សំខាន់ទេ"
    return ("<b>☀️ អរុណសួស្តី! សង្ខេបមាសថ្ងៃនេះ</b>\n\n"
            + status(result, stats, balance, risk_pct, offset_ok)
            + f"\n\n<b>📰 ព័ត៌មាន USD ក្នុង 24 ម៉ោង (ម៉ោងកម្ពុជា)</b>\n{news}")


WELCOME = ("<b>សួស្តី! ខ្ញុំជា Gold Live Bot 🟡</b>\n\n"
           "ខ្ញុំវិភាគមាស XAUUSD រៀងរាល់ ~5 នាទី ហើយផ្ញើសារមកអ្នកតែពេល៖\n"
           "• មានសញ្ញាទិញ/លក់ថ្មី\n• សញ្ញាប៉ះ TP ឬ SL\n• សង្ខេបរៀងរាល់ព្រឹក ម៉ោង 7\n\n"
           "ពាក្យបញ្ជា៖\n/status — ស្ថានភាពឥឡូវ\n/balance 1000 — កំណត់ទុន ($)\n"
           "/risk 1 — កំណត់ហានិភ័យ (%)\n\n"
           "ចុចប៊ូតុងខាងក្រោមដើម្បីបើកទំព័រ Gold Live។\n\n"
           "⚠️ នេះគ្រាន់តែជាជំនួយវិភាគ មិនមែនការធានាថាឈ្នះទេ។")

HELP = WELCOME
PRIVATE = "សូមទោស Bot នេះជាកម្មសិទ្ធិផ្ទាល់ខ្លួន។"
LATE = "ℹ️ Bot ឆ្លើយតាមរង្វង់វិភាគ (~5–20 នាទីម្តង) ដូច្នេះចម្លើយអាចយឺតបន្តិច។"
