"""Per-camera rules that turn tracks into Signals.

Everything here runs on the host CPU on top of detector + tracker output, which is the
part that runs on the accelerator. Distances are normalised by the object's own bounding
box size ("body heights" for people, "vehicle widths" for vehicles) so the rules survive
different camera heights and zoom levels without per-camera calibration.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from .schema import Signal


@dataclass
class Obs:
    t: float  # seconds since video start
    cx: float
    cy: float
    w: float
    h: float
    cls: str
    conf: float
    frame: int


@dataclass
class CameraContext:
    sensor: str
    zone: str
    scenario: str
    t0: datetime
    video: str
    fps: float


def _smooth(x: np.ndarray, k: int = 5) -> np.ndarray:
    if len(x) < k:
        return x
    pad = k // 2
    xp = np.pad(x, (pad, pad), mode="edge")
    return np.convolve(xp, np.ones(k) / k, mode="valid")


class _Base:
    def __init__(self, ctx: CameraContext, ids):
        self.ctx = ctx
        self.ids = ids
        self.tracks: dict[int, list[Obs]] = defaultdict(list)
        self.last_fired: dict[tuple, float] = {}

    def _fire(self, t: float, kind: str, conf: float, detail: str, frame: int,
              key=None, cooldown: float = 10.0, bbox=None, features=None) -> Signal | None:
        k = (kind, key)
        if t - self.last_fired.get(k, -1e9) < cooldown:
            return None
        self.last_fired[k] = t
        return Signal(id=next(self.ids), source="camera", sensor=self.ctx.sensor, zone=self.ctx.zone,
                      ts=self.ctx.t0 + timedelta(seconds=t), kind=kind, confidence=float(round(conf, 3)),
                      detail=detail, scenario=self.ctx.scenario, video=self.ctx.video, frame=frame,
                      bbox=bbox, features=features or {})


class MetroRules(_Base):
    """Crowd surge, sudden dispersal (many people running) and person-down."""

    def __init__(self, ctx: CameraContext, ids, surge_window: float = 6.0, surge_ratio: float = 1.8,
                 surge_min_delta: int = 5, run_speed: float = 1.6, run_min_people: int = 3,
                 down_aspect: float = 1.25, down_hold: float = 1.5):
        super().__init__(ctx, ids)
        self.counts: deque[tuple[float, int]] = deque()
        self.surge_window, self.surge_ratio, self.surge_min_delta = surge_window, surge_ratio, surge_min_delta
        self.run_speed, self.run_min_people = run_speed, run_min_people
        self.down_aspect, self.down_hold = down_aspect, down_hold
        self.count_series: list[tuple[float, int]] = []

    def update(self, t: float, frame: int, people: list[tuple[int, Obs]]) -> list[Signal]:
        out: list[Signal] = []
        for tid, o in people:
            self.tracks[tid].append(o)
        n = len(people)
        self.count_series.append((t, n))
        self.counts.append((t, n))
        while self.counts and t - self.counts[0][0] > self.surge_window + 1:
            self.counts.popleft()

        # Crowd surge: 1 s median count vs a baseline median from 2-6 s earlier. Medians absorb
        # detector flicker; the warm-up skips ByteTrack's track-activation ramp at stream start.
        recent = [c for tt, c in self.counts if t - tt <= 1.0]
        older = [c for tt, c in self.counts if 2.0 <= t - tt <= self.surge_window]
        if t >= self.surge_window and recent and older:
            cur, base = float(np.median(recent)), float(np.median(older))
            if cur - base >= self.surge_min_delta and cur >= self.surge_ratio * max(base, 1):
                conf = min(0.95, 0.5 + 0.05 * (cur - base))
                s = self._fire(t, "crowd_surge", conf, f"people count {base:.0f} -> {cur:.0f} within {self.surge_window:.0f} s",
                               frame, features={"people_before": base, "people_after": cur})
                out += [s] if s else []

        # Sudden dispersal: several tracks moving faster than ~running speed at once.
        runners = []
        for tid, o in people:
            hist = [h for h in self.tracks[tid] if t - h.t <= 1.0]
            if len(hist) >= 5 and hist[-1].t - hist[0].t > 0.4:
                dist = np.hypot(hist[-1].cx - hist[0].cx, hist[-1].cy - hist[0].cy)
                speed = dist / np.median([h.h for h in hist]) / (hist[-1].t - hist[0].t)
                if speed >= self.run_speed:
                    runners.append((tid, speed))
        if len(runners) >= self.run_min_people:
            conf = min(0.95, 0.45 + 0.08 * len(runners))
            s = self._fire(t, "sudden_dispersal", conf,
                           f"{len(runners)} people moving > {self.run_speed:.1f} body-heights/s", frame,
                           features={"runners": len(runners)})
            out += [s] if s else []

        # Person down: a track that was upright now lies wide for > down_hold seconds.
        for tid, o in people:
            hist = self.tracks[tid]
            if len(hist) < 10:
                continue
            was_upright = any(h.t < t - self.down_hold and h.w / h.h < 0.8 for h in hist)
            lying = [h for h in hist if t - h.t <= self.down_hold]
            if was_upright and lying and lying[-1].t - lying[0].t >= self.down_hold * 0.9 \
                    and all(h.w / h.h >= self.down_aspect for h in lying):
                s = self._fire(t, "person_down", 0.8, f"track {tid} aspect {o.w / o.h:.2f} for {self.down_hold:.1f} s",
                               frame, key=tid, cooldown=30,
                               bbox=[o.cx - o.w / 2, o.cy - o.h / 2, o.cx + o.w / 2, o.cy + o.h / 2],
                               features={"track_id": tid})
                out += [s] if s else []
        return out


def trajectory_features(track: list[Obs], flow: np.ndarray | None = None) -> dict[str, float]:
    """Lateral-motion features of one vehicle track.

    Positions are projected onto the travel direction (`flow`, or the track's own principal
    axis) and its normal; a quadratic fit of lateral offset vs progress removes lane
    curvature and perspective drift, and the residual is measured in vehicle widths.
    """
    t = np.array([o.t for o in track])
    p = np.stack([_smooth(np.array([o.cx for o in track])), _smooth(np.array([o.cy for o in track]))], axis=1)
    width = float(np.median([min(o.w, o.h) for o in track]))
    disp = p[-1] - p[0]
    if flow is None or not np.isfinite(flow).all():
        c = p - p.mean(0)
        flow = np.linalg.svd(c, full_matrices=False)[2][0]
        if flow @ disp < 0:
            flow = -flow
    flow = flow / (np.linalg.norm(flow) + 1e-9)
    normal = np.array([-flow[1], flow[0]])
    s = p @ flow
    lat = p @ normal
    deg = 2 if len(s) >= 12 and np.ptp(s) > 1e-6 else 0
    coef = np.polyfit(s, lat, deg) if deg else [lat.mean()]
    resid = (lat - np.polyval(coef, s)) / max(width, 1.0)

    # Count swings with hysteresis of +-0.2 vehicle widths.
    swings, state = 0, 0
    for r in resid:
        if r > 0.2 and state <= 0:
            swings += state != 0
            state = 1
        elif r < -0.2 and state >= 0:
            swings += state != 0
            state = -1
    duration = float(t[-1] - t[0])
    lateral_std = float(resid.std())
    return {
        "duration_s": duration,
        "lateral_std_w": lateral_std,
        "swings": float(swings),
        "weaving_index": float(swings * lateral_std),
        "speed_wps": float(np.linalg.norm(disp) / max(width, 1.0) / max(duration, 1e-3)),
        "heading_dot_flow": float((disp / (np.linalg.norm(disp) + 1e-9)) @ flow),
        "displacement_w": float(np.linalg.norm(disp) / max(width, 1.0)),
    }


class RoadRules(_Base):
    """Lateral weaving, wrong-way and speed outliers, evaluated when a track ends."""

    VEHICLES = {"motorcycle", "car", "bus", "truck", "bicycle"}

    def __init__(self, ctx: CameraContext, ids, grid: int = 6, min_duration: float = 2.0,
                 min_points: int = 20, weave_swings: int = 3, weave_std: float = 0.3,
                 frame_size: tuple[int, int] = (1920, 1080), flow: list[float] | None = None):
        super().__init__(ctx, ids)
        # Optional configured lane direction (image coords) so wrong-way works from the first track.
        self.prior_flow = np.array(flow, float) / np.linalg.norm(flow) if flow else None
        self.grid, self.min_duration, self.min_points = grid, min_duration, min_points
        self.weave_swings, self.weave_std = weave_swings, weave_std
        self.frame_size = frame_size
        self.last_seen: dict[int, float] = {}
        self.flow_votes: dict[tuple[int, int], list[np.ndarray]] = defaultdict(list)
        self.finished: list[tuple[int, list[Obs], dict[str, float]]] = []

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        W, H = self.frame_size
        def clamp(v: float) -> int:
            return max(0, min(self.grid - 1, int(v * self.grid)))

        return clamp(x / W), clamp(y / H)

    def _local_flow(self, track: list[Obs]) -> np.ndarray | None:
        mid = track[len(track) // 2]
        votes = self.flow_votes.get(self._cell(mid.cx, mid.cy), [])
        if len(votes) < 5:
            return self.prior_flow
        v = np.median(np.stack(votes), axis=0)
        return v if np.linalg.norm(v) > 0.3 else None

    def update(self, t: float, frame: int, vehicles: list[tuple[int, Obs]]) -> list[Signal]:
        for tid, o in vehicles:
            self.tracks[tid].append(o)
            self.last_seen[tid] = t
        ended = [tid for tid, last in self.last_seen.items() if t - last > 1.0]
        out: list[Signal] = []
        for tid in ended:
            del self.last_seen[tid]
            out += self._finish(tid, self.tracks.pop(tid))
        return out

    def close(self) -> list[Signal]:
        out: list[Signal] = []
        for tid in list(self.last_seen):
            out += self._finish(tid, self.tracks.pop(tid))
        self.last_seen.clear()
        return out

    def _finish(self, tid: int, track: list[Obs]) -> list[Signal]:
        if len(track) < self.min_points or track[-1].t - track[0].t < self.min_duration:
            return []
        flow = self._local_flow(track)
        f = trajectory_features(track, flow)
        f["track_id"] = float(tid)
        if f["displacement_w"] > 2:
            d = np.array([track[-1].cx - track[0].cx, track[-1].cy - track[0].cy])
            self.flow_votes[self._cell(track[len(track) // 2].cx, track[len(track) // 2].cy)].append(
                d / (np.linalg.norm(d) + 1e-9))
        prev_speeds = [g["speed_wps"] for _, _, g in self.finished[-60:]]
        self.finished.append((tid, track, f))
        last = track[-1]
        bbox = [last.cx - last.w / 2, last.cy - last.h / 2, last.cx + last.w / 2, last.cy + last.h / 2]
        mid = track[len(track) // 2]
        out: list[Signal] = []
        cls = max(set(o.cls for o in track), key=[o.cls for o in track].count)
        if f["swings"] >= self.weave_swings and f["lateral_std_w"] >= self.weave_std:
            conf = min(0.95, 0.4 + 0.08 * f["swings"] + 0.3 * f["lateral_std_w"])
            s = self._fire(mid.t, "lateral_weaving", conf,
                           f"{cls} track {tid}: {int(f['swings'])} lateral swings, "
                           f"std {f['lateral_std_w']:.2f} vehicle widths over {f['duration_s']:.1f} s",
                           mid.frame, key=tid, cooldown=0, bbox=bbox, features=f)
            out += [s] if s else []
        if flow is not None and f["heading_dot_flow"] < -0.6 and f["displacement_w"] > 3:
            s = self._fire(mid.t, "wrong_way", 0.85,
                           f"{cls} track {tid} moving against local traffic flow "
                           f"(cos={f['heading_dot_flow']:.2f})", mid.frame, key=tid, cooldown=0, bbox=bbox,
                           features=f)
            out += [s] if s else []
        speeds = prev_speeds
        if len(speeds) >= 15:
            med = float(np.median(speeds))
            mad = float(np.median(np.abs(np.array(speeds) - med))) + 1e-6
            if f["speed_wps"] > med + 4 * 1.4826 * mad and f["speed_wps"] > 1.8 * med:
                s = self._fire(mid.t, "speed_outlier", 0.5,
                               f"{cls} track {tid} at {f['speed_wps']:.1f} widths/s vs median {med:.1f}",
                               mid.frame, key=tid, cooldown=0, bbox=bbox, features=f)
                out += [s] if s else []
        return out
