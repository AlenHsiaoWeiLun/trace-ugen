"""Charts for the deck (SVG, dark surface). python scripts/make_charts.py"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "deck" / "charts"
OUT.mkdir(parents=True, exist_ok=True)
SURF, INK, MUTED, GRID = "#10222c", "#e6f1f4", "#8aa5b0", "#1c3542"
TRUE_C, FALSE_C = "#1f9e90", "#d0782a"
plt.rcParams.update({"font.family": "Helvetica Neue", "font.size": 15, "text.color": INK,
                     "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED})


def style(ax):
    ax.set_facecolor(SURF)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.grid(axis="y", color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)


def alert_storm():
    ws = [10, 15, 20, 30, 45, 60]
    agg = {w: json.loads((ROOT / f"results/alert_storm_w{w}.json").read_text())["aggregate"] for w in ws}
    hi = [agg[w]["high_cards"]["mean"] for w in ws]
    fa = [agg[w]["false_high_cards"]["mean"] for w in ws]
    tr = [h - f for h, f in zip(hi, fa)]
    rec = [100 * agg[w]["incident_recall"]["mean"] for w in ws]
    x = range(len(ws))
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.6), facecolor=SURF)
    style(a1)
    a1.bar(x, tr, width=0.56, color=TRUE_C, label="cards containing a real incident", edgecolor=SURF, linewidth=2)
    a1.bar(x, fa, bottom=tr, width=0.56, color=FALSE_C, label="false high-priority cards",
           edgecolor=SURF, linewidth=2)
    for i, (h, f) in enumerate(zip(hi, fa)):
        a1.text(i, h + 0.35, f"{h:.1f}", ha="center", color=INK, fontsize=14)
    a1.set_xticks(list(x), [f"{w}s" for w in ws])
    a1.set_xlabel("fusion time window")
    a1.set_title("High-priority cards per hour  (raw input: 409 alerts/h)", color=INK, loc="left", fontsize=16, pad=12)
    a1.legend(frameon=False, loc="upper left", labelcolor=MUTED, fontsize=13)
    a1.set_ylim(0, 18.5)
    style(a2)
    a2.plot(list(x), rec, color=TRUE_C, linewidth=2.5, marker="o", markersize=9,
            markeredgecolor=SURF, markeredgewidth=2)
    for i, r in enumerate(rec):
        a2.text(i, r + 1.6, f"{r:.0f}%", ha="center", color=INK, fontsize=14)
    a2.set_xticks(list(x), [f"{w}s" for w in ws])
    a2.set_ylim(70, 104)
    a2.set_xlabel("fusion time window")
    a2.set_title("Injected incidents surfaced as high priority", color=INK, loc="left", fontsize=16, pad=12)
    fig.tight_layout(w_pad=4)
    fig.savefig(OUT / "alert_storm.svg", facecolor=SURF)
    fig.savefig(OUT / "alert_storm.png", facecolor=SURF, dpi=160)


if __name__ == "__main__":
    alert_storm()


def road_tracks():
    tracks = json.loads((ROOT / "data/tracks_road.json").read_text())
    std = sorted(t["features"]["lateral_std_w"] for t in tracks)
    sw = [t["features"]["swings"] for t in tracks]
    flagged = [t for t in tracks if t["features"]["swings"] >= 3 and t["features"]["lateral_std_w"] >= 0.25]
    fig, ax = plt.subplots(figsize=(7.2, 4.4), facecolor=SURF)
    style(ax)
    xs = [t["features"]["lateral_std_w"] for t in tracks]
    ys = [t["features"]["swings"] + (hash(t["track_id"]) % 7 - 3) * 0.04 for t in tracks]
    ax.scatter(xs, ys, s=70, color=TRUE_C, edgecolor=SURF, linewidth=1.5, label="normal track", zorder=3)
    for t in flagged:
        ax.scatter([t["features"]["lateral_std_w"]], [t["features"]["swings"]], s=140, color=FALSE_C,
                   edgecolor=SURF, linewidth=2, zorder=4, label="flagged for review")
        ax.annotate(f"track {int(t['track_id'])}", (t["features"]["lateral_std_w"], t["features"]["swings"]),
                    xytext=(-90, -6), textcoords="offset points", color=INK, fontsize=13)
    ax.axvline(0.25, color=MUTED, linewidth=1, linestyle=(0, (4, 4)))
    ax.axhline(3, color=MUTED, linewidth=1, linestyle=(0, (4, 4)))
    ax.text(0.255, 0.2, "flag zone: ≥3 swings and\n≥0.25 vehicle-widths std", color=MUTED, fontsize=12)
    ax.set_xlabel("lateral deviation (std, vehicle widths)")
    ax.set_ylabel("lateral swings per track")
    ax.set_title(f"{len(tracks)} real scooter tracks, Taipei Bridge footage", color=INK, loc="left", fontsize=15, pad=10)
    ax.legend(frameon=False, labelcolor=MUTED, fontsize=12, loc="upper left")
    fig.tight_layout()
    fig.savefig(OUT / "road_tracks.svg", facecolor=SURF)
    fig.savefig(OUT / "road_tracks.png", facecolor=SURF, dpi=160)


if __name__ == "__main__":
    road_tracks()
