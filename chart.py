"""Candlestick picture with liquidity levels and the trade plan."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                     # noqa: E402
from matplotlib.patches import Rectangle            # noqa: E402

BG, GRID, INK = "#1c1712", "#2e261d", "#e9dcc2"
UP, DOWN, GOLD = "#3fb68b", "#e05a4f", "#d9a441"


def render(candles, result, path, n=96):
    c = candles[-n:]
    if not c:
        return None
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=110)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    for i, x in enumerate(c):
        col = UP if x.c >= x.o else DOWN
        ax.vlines(i, x.l, x.h, color=col, linewidth=0.8)
        ax.add_patch(Rectangle((i - 0.35, min(x.o, x.c)), 0.7, max(abs(x.c - x.o), 0.01),
                               color=col))
    lo = min(x.l for x in c)
    hi = max(x.h for x in c)
    span = hi - lo
    right = len(c) + 6

    labeled = []

    def line(y, label, color, style="--"):
        if lo - span * 0.6 <= y <= hi + span * 0.6:
            ax.hlines(y, 0, right, colors=color, linestyles=style, linewidth=0.9, alpha=0.85)
            if all(abs(y - z) > span * 0.035 for z in labeled):
                labeled.append(y)
                ax.text(right + 0.5, y, f"{label} {y:.2f}", color=color, fontsize=7.5, va="center")

    s = result.get("setup")
    if s:
        ax.add_patch(Rectangle((len(c) - 12, s["entry_bottom"]), right - (len(c) - 12),
                               s["entry_top"] - s["entry_bottom"], color=GOLD, alpha=0.25))
        line(s["entry_top"], "Entry", GOLD, "-")
        line(s["sl"], "SL", DOWN, "-")
        line(s["tp1"], "TP1", UP, "-")
        line(s["tp2"], "TP2", UP, "-")
    for p in sorted(result.get("pools", []), key=lambda p: not p["major"]):
        line(p["price"], p["name"], "#8f7b5c" if not p["major"] else "#b99a62", ":")
    ax.axhline(c[-1].c, color=INK, linewidth=0.6, alpha=0.5)
    ax.set_xlim(-1, right + 12)
    ax.tick_params(colors=INK, labelsize=8)
    ax.set_xticks([])
    for sp in ax.spines.values():
        sp.set_color(GRID)
    ax.grid(color=GRID, linewidth=0.5)
    ax.yaxis.tick_right()
    title = f"XAUUSD 5m  {result['status']}  {c[-1].c:.2f}"
    ax.set_title(title, color=INK, fontsize=11, loc="left")
    fig.tight_layout()
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    return path
