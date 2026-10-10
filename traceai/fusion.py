"""Spatio-temporal alert fusion.

Signals arrive in time order. A signal joins every *open* incident whose last signal is
within `window_s` seconds and whose anchor zone (where it started) is within `max_hops`
zones on the site graph; if it bridges several incidents they are merged. Anchoring and a
`max_duration_s` cap stop single-linkage chaining, where background noise would otherwise
glue unrelated alarms across the whole station into one giant incident. Each incident is scored with a noisy-OR over its
sensors (one vote per sensor, so a chattering camera cannot inflate the score) and a
corroboration factor that rewards independent source types (camera + detector + radio).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from itertools import count

from .schema import Incident, Signal

CRITICAL_KINDS = {"person_down", "wrong_way"}

TITLES = {
    "metro": [
        ("person_down", "Person down"),
        ("sudden_dispersal", "Sudden crowd dispersal"),
        ("crowd_surge", "Crowd density surge"),
        ("detector_alarm", "Detector alarm"),
        ("staff_report", "Staff radio report"),
    ],
    "road": [
        ("wrong_way", "Wrong-way vehicle"),
        ("lateral_weaving", "Repeated lateral deviation"),
        ("speed_outlier", "Speed outlier"),
    ],
}


@dataclass
class ZoneGraph:
    adjacency: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def from_pairs(cls, pairs: list[list[str]]) -> "ZoneGraph":
        g = cls()
        for a, b in pairs:
            g.adjacency.setdefault(a, set()).add(b)
            g.adjacency.setdefault(b, set()).add(a)
        return g

    def hops(self, a: str, b: str, limit: int = 3) -> int:
        if a == b:
            return 0
        seen, queue = {a}, deque([(a, 0)])
        while queue:
            node, d = queue.popleft()
            if d >= limit:
                continue
            for nxt in self.adjacency.get(node, ()):
                if nxt == b:
                    return d + 1
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append((nxt, d + 1))
        return limit + 1


def score_incident(inc: Incident, floor: float = 0.3) -> float:
    """Noisy-OR over sensors; confidence below `floor` is treated as no evidence."""
    best: dict[str, float] = {}
    for s in inc.signals:
        best[s.sensor] = max(best.get(s.sensor, 0.0), s.confidence)
    miss = 1.0
    for c in best.values():
        miss *= 1.0 - max(0.0, (c - floor) / (1.0 - floor))
    # Snapshots pulled on demand are context, not independent corroboration.
    n_sources = len({s.source for s in inc.signals if s.kind != "scene_check"})
    corroboration = min(1.0, 0.7 + 0.15 * (n_sources - 1))
    return (1.0 - miss) * corroboration


def priority_of(inc: Incident) -> str:
    kinds = {s.kind for s in inc.signals}
    n_sensors = len(inc.sensors)
    if inc.score >= 0.8 and (n_sensors >= 2 or kinds & CRITICAL_KINDS):
        return "high"
    # A confident human report corroborated by an independent machine sensor is always high.
    human = any(s.kind == "staff_report" and s.confidence >= 0.8 for s in inc.signals)
    machine = any(s.source in ("detector", "camera") and s.kind != "scene_check" for s in inc.signals)
    if human and machine:
        return "high"
    if inc.score >= 0.55 or kinds & CRITICAL_KINDS:
        return "medium"
    return "low"


def title_of(inc: Incident) -> str:
    kinds = {s.kind for s in inc.signals}
    if (inc.scenario == "metro" and kinds & {"crowd_surge", "sudden_dispersal"}
            and len(inc.zones) >= 2 and len(inc.sensors) >= 2):
        return "Possible multi-zone disturbance"
    if {"staff_report", "detector_alarm"} <= kinds:
        return "Alarm corroborated by staff report"
    for kind, title in TITLES.get(inc.scenario, []):
        if kind in kinds:
            return title
    return "Unclassified event"


class FusionEngine:
    def __init__(self, graph: ZoneGraph, window_s: float = 30.0, max_hops: int = 1,
                 max_duration_s: float = 180.0, scenario: str = "metro", id_prefix: str = "INC"):
        self.graph = graph
        self.window_s = window_s
        self.max_duration_s = max_duration_s
        self.max_hops = max_hops
        self.scenario = scenario
        self._ids = count(1)
        self.id_prefix = id_prefix
        self.open: list[Incident] = []
        self.closed: list[Incident] = []

    def _new_id(self) -> str:
        return f"{self.id_prefix}-{next(self._ids):04d}"

    def _close_stale(self, now) -> None:
        still = []
        for inc in self.open:
            if (now - inc.end_ts).total_seconds() > self.window_s:
                self.closed.append(inc)
            else:
                still.append(inc)
        self.open = still

    def _matches(self, inc: Incident, sig: Signal) -> bool:
        if (sig.ts - inc.end_ts).total_seconds() > self.window_s:
            return False
        if (sig.ts - inc.start_ts).total_seconds() > self.max_duration_s:
            return False
        track = sig.features.get("track_id")
        if track is not None and any(s.features.get("track_id") == track and s.sensor == sig.sensor
                                     for s in inc.signals):
            return True
        anchor = inc.signals[0].zone
        return self.graph.hops(anchor, sig.zone, self.max_hops) <= self.max_hops

    def add(self, sig: Signal) -> Incident:
        self._close_stale(sig.ts)
        hits = [inc for inc in self.open if self._matches(inc, sig)]
        if not hits:
            inc = Incident(id=self._new_id(), scenario=self.scenario)
            inc.audit.append({"ts": sig.ts.isoformat(timespec="seconds"), "actor": "system",
                              "action": f"opened by {sig.sensor} {sig.kind}"})
            self.open.append(inc)
        else:
            inc = hits[0]
            for other in hits[1:]:
                inc.signals.extend(other.signals)
                inc.audit.append({"ts": sig.ts.isoformat(timespec="seconds"), "actor": "system",
                                  "action": f"merged {other.id} (bridged by {sig.sensor})"})
                self.open.remove(other)
        inc.signals.append(sig)
        inc.score = score_incident(inc)
        inc.priority = priority_of(inc)
        inc.title = title_of(inc)
        return inc

    def run(self, signals: list[Signal]) -> list[Incident]:
        for s in sorted(signals, key=lambda s: s.ts):
            self.add(s)
        return self.flush()

    def flush(self) -> list[Incident]:
        self.closed.extend(self.open)
        self.open = []
        out = sorted(self.closed, key=lambda i: i.start_ts)
        for inc in out:
            inc.audit.append({"ts": inc.end_ts.isoformat(timespec="seconds"), "actor": "system",
                              "action": f"incident created from {len(inc.signals)} signals, "
                                        f"{len(inc.sensors)} sensors, score {inc.score:.2f}"})
        return out


def pairwise_f1(pred: dict[str, str], truth: dict[str, str]) -> dict[str, float]:
    """Pairwise clustering precision/recall/F1 over signal ids (truth '' = noise singleton)."""
    ids = sorted(truth)
    tp = fp = fn = 0
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            same_pred = pred[a] == pred[b]
            same_true = truth[a] != "" and truth[a] == truth[b]
            tp += same_pred and same_true
            fp += same_pred and not same_true
            fn += same_true and not same_pred
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": p, "recall": r, "f1": f}
