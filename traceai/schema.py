"""Core data types shared by every TRACE stage.

A *Signal* is one observation from one sensor (a camera rule firing, a fixed detector
alarm, a transcribed staff radio call). An *Incident* is TRACE's unit of work for a human
operator: a group of signals that are close in time and space, with evidence attached.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

SOURCES = ("camera", "detector", "radio")
DECISIONS = ("confirmed", "dismissed", "escalated")


def iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


@dataclass
class Signal:
    id: str
    source: str  # camera | detector | radio
    sensor: str  # CAM-03, DET-B2, RADIO-1 ...
    zone: str
    ts: datetime
    kind: str  # crowd_surge, person_down, lateral_weaving, staff_report ...
    confidence: float
    detail: str = ""
    scenario: str = "metro"
    thumb: str | None = None
    transcript: str | None = None
    features: dict[str, float] = field(default_factory=dict)
    # Optional pointer back into the source video, used to cut evidence clips.
    video: str | None = None
    frame: int | None = None
    bbox: list[float] | None = None

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["ts"] = iso(self.ts)
        return d


@dataclass
class Incident:
    id: str
    scenario: str
    signals: list[Signal] = field(default_factory=list)
    title: str = ""
    summary: str = ""
    score: float = 0.0
    priority: str = "low"
    status: str = "pending"
    keyframe: str | None = None
    clip: str | None = None
    review: dict[str, Any] = field(
        default_factory=lambda: {"decision": None, "reviewer": None, "note": None, "ts": None}
    )
    audit: list[dict[str, str]] = field(default_factory=list)
    latency_ms: float | None = None
    vlm: dict[str, Any] | None = None
    sop: list[str] = field(default_factory=list)

    @property
    def start_ts(self) -> datetime:
        return min(s.ts for s in self.signals)

    @property
    def end_ts(self) -> datetime:
        return max(s.ts for s in self.signals)

    @property
    def zones(self) -> list[str]:
        return sorted({s.zone for s in self.signals})

    @property
    def sensors(self) -> list[str]:
        seen: list[str] = []
        for s in sorted(self.signals, key=lambda s: s.ts):
            if s.sensor not in seen:
                seen.append(s.sensor)
        return seen

    @property
    def features(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for s in self.signals:
            out.update(s.features)
        return out

    def duration(self) -> timedelta:
        return self.end_ts - self.start_ts

    def summary_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scenario": self.scenario,
            "title": self.title,
            "status": self.status,
            "priority": self.priority,
            "score": round(self.score, 3),
            "start_ts": iso(self.start_ts),
            "end_ts": iso(self.end_ts),
            "zones": self.zones,
            "sensors": self.sensors,
            "n_signals": len(self.signals),
            "keyframe": self.keyframe,
        }

    def to_json(self) -> dict[str, Any]:
        d = self.summary_json()
        d.update(
            summary=self.summary,
            clip=self.clip,
            signals=[
                {k: v for k, v in s.to_json().items() if k not in ("video", "frame", "bbox", "scenario")}
                for s in sorted(self.signals, key=lambda s: s.ts)
            ],
            features={k: round(v, 3) for k, v in self.features.items()},
            review=self.review,
            audit=self.audit,
            latency_ms=self.latency_ms,
            vlm=self.vlm,
            sop=self.sop,
        )
        return d
