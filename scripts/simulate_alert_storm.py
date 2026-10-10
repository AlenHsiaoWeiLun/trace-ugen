"""Synthetic alert-storm benchmark for the fusion engine.

A 16-zone station graph with 32 cameras, 16 fixed detectors and 4 staff radios produces
one hour of background alarms (nuisance triggers, single-camera noise) plus a few injected
ground-truth incidents that spread across neighbouring zones and source types. We measure
how many cards an operator would have to look at with and without TRACE, and how well the
fusion recovers the true incidents.

This is a *synthetic* benchmark of the fusion logic only; Stage II replaces it with replayed
alarm logs and recorded video on the UGen300.

    python scripts/simulate_alert_storm.py --seeds 20
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from datetime import datetime, timedelta
from pathlib import Path

from traceai.fusion import FusionEngine, ZoneGraph, pairwise_f1
from traceai.schema import Signal

ROWS, COLS = 4, 4
ZONES = [f"{chr(65 + r)}{c + 1}" for r in range(ROWS) for c in range(COLS)]


def station_graph() -> ZoneGraph:
    pairs = []
    for r in range(ROWS):
        for c in range(COLS):
            z = f"{chr(65 + r)}{c + 1}"
            if c + 1 < COLS:
                pairs.append([z, f"{chr(65 + r)}{c + 2}"])
            if r + 1 < ROWS:
                pairs.append([z, f"{chr(66 + r)}{c + 1}"])
    return ZoneGraph.from_pairs(pairs)


def simulate(seed: int, minutes: int = 60, noise_per_min: float = 6.0, n_incidents: int = 6):
    rng = random.Random(seed)
    g = station_graph()
    t0 = datetime(2026, 10, 10, 17, 0, 0)
    cams = {z: [f"CAM-{z}-{i}" for i in (1, 2)] for z in ZONES}
    dets = {z: f"DET-{z}" for z in ZONES}
    radios = [f"RADIO-{i}" for i in range(1, 5)]
    signals, truth, n = [], {}, 0

    def add(sec, zone, source, sensor, kind, conf, label):
        nonlocal n
        n += 1
        sid = f"S{n:05d}"
        signals.append(Signal(id=sid, source=source, sensor=sensor, zone=zone,
                              ts=t0 + timedelta(seconds=sec), kind=kind, confidence=round(conf, 2)))
        truth[sid] = label

    # Background: Poisson nuisance alarms, mostly weak, occasionally a confident false trigger.
    t = 0.0
    while True:
        t += rng.expovariate(noise_per_min / 60)
        if t > minutes * 60:
            break
        z = rng.choice(ZONES)
        r = rng.random()
        if r < 0.65:
            add(t, z, "camera", rng.choice(cams[z]), rng.choice(["crowd_surge", "sudden_dispersal"]),
                rng.uniform(0.25, 0.6), "")
        elif r < 0.95:
            add(t, z, "detector", dets[z], "detector_alarm", rng.uniform(0.3, 0.7), "")
        else:
            add(t, z, "radio", rng.choice(radios), "staff_report", rng.uniform(0.4, 0.7), "")

    # Ground-truth incidents: a burst that propagates to neighbours over ~10-60 s.
    starts = sorted(rng.uniform(120, minutes * 60 - 120) for _ in range(n_incidents))
    for k, start in enumerate(starts):
        label = f"GT{k}"
        z0 = rng.choice(ZONES)
        zones = [z0] + rng.sample(sorted(g.adjacency[z0]), k=min(2, len(g.adjacency[z0])))
        for _ in range(rng.randint(4, 9)):
            z = rng.choice(zones)
            dt = rng.uniform(0, 45)
            src = rng.choices(["camera", "detector"], weights=[0.6, 0.4])[0]
            if src == "camera":
                add(start + dt, z, src, rng.choice(cams[z]), rng.choice(["crowd_surge", "sudden_dispersal"]),
                    rng.uniform(0.55, 0.9), label)
            else:
                add(start + dt, z, src, dets[z], "detector_alarm", rng.uniform(0.6, 0.9), label)
        if rng.random() < 0.7:
            add(start + rng.uniform(8, 40), rng.choice(zones), "radio", rng.choice(radios), "staff_report",
                rng.uniform(0.7, 0.9), label)
    return g, signals, truth


def sensor_dedup(signals, window_s: float):
    """Baseline a conventional VMS offers: collapse repeats from the same sensor within a window."""
    cards, last = [], {}
    for s in sorted(signals, key=lambda s: s.ts):
        prev = last.get(s.sensor)
        if prev is not None and (s.ts - prev[-1].ts).total_seconds() <= window_s:
            prev.append(s)
        else:
            last[s.sensor] = [s]
            cards.append(last[s.sensor])
    return cards


def evaluate(seed: int, window_s: float, max_hops: int) -> dict:
    g, signals, truth = simulate(seed)
    incidents = FusionEngine(g, window_s=window_s, max_hops=max_hops).run(signals)
    pred = {s.id: inc.id for inc in incidents for s in inc.signals}
    surfaced = [i for i in incidents if i.priority == "high"]
    medium = [i for i in incidents if i.priority == "medium"]
    gt_labels = sorted({v for v in truth.values() if v})
    hit = 0
    for lab in gt_labels:
        members = {sid for sid, v in truth.items() if v == lab}
        if any(len(members & {s.id for s in inc.signals}) >= len(members) / 2 for inc in surfaced):
            hit += 1
    dedup = sensor_dedup(signals, window_s)
    gt_dedup_hit = sum(1 for lab in gt_labels if any(any(truth[s.id] == lab for s in c) for c in dedup))
    false_cards = sum(1 for inc in surfaced
                      if not any(truth[s.id] for s in inc.signals))
    return {
        "signals": len(signals),
        "incidents": len(incidents),
        "high_cards": len(surfaced),
        "medium_cards": len(medium),
        "high_card_reduction": 1 - len(surfaced) / len(signals),
        "dedup_cards": len(dedup),
        "dedup_recall": gt_dedup_hit / len(gt_labels),
        "gt_incidents": len(gt_labels),
        "incident_recall": hit / len(gt_labels),
        "false_high_cards": false_cards,
        **{f"pairwise_{k}": v for k, v in pairwise_f1(pred, truth).items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--window", type=float, default=30.0)
    ap.add_argument("--hops", type=int, default=1)
    ap.add_argument("--out", default="results/alert_storm.json")
    a = ap.parse_args()
    runs = [evaluate(s, a.window, a.hops) for s in range(a.seeds)]
    keys = runs[0].keys()
    agg = {k: {"mean": statistics.mean(r[k] for r in runs), "std": statistics.pstdev(r[k] for r in runs)}
           for k in keys}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"config": vars(a), "aggregate": agg, "runs": runs}, indent=2))
    print(f"{a.seeds} seeds, window={a.window}s hops={a.hops}")
    for k in keys:
        print(f"  {k:22s} {agg[k]['mean']:8.3f} ± {agg[k]['std']:.3f}")


if __name__ == "__main__":
    main()
