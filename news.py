"""USD economic calendar (ForexFactory weekly feed, free, no key)."""
from datetime import datetime

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
MIN = 60_000


def parse_ff(raw):
    out = []
    for e in raw or []:
        if e.get("country") != "USD" or e.get("impact") not in ("High", "Medium"):
            continue
        try:
            t = int(datetime.fromisoformat(e["date"]).timestamp() * 1000)
        except (KeyError, ValueError):
            continue
        out.append({"title": e.get("title", ""), "time_ms": t, "impact": e["impact"],
                    "forecast": e.get("forecast") or "", "previous": e.get("previous") or ""})
    return sorted(out, key=lambda x: x["time_ms"])


def fetch_news(session):
    r = session.get(FF_URL, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return parse_ff(r.json())


def news_block(events, now_ms, before=30, after=15):
    """High-impact USD event from 30 min before to 15 min after now."""
    for e in events:
        if e["impact"] == "High" and -after * MIN <= e["time_ms"] - now_ms <= before * MIN:
            return e
    return None


def upcoming(events, now_ms, hours=24):
    return [e for e in events if 0 <= e["time_ms"] - now_ms <= hours * 60 * MIN]
