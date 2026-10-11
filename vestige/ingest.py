"""Video source → tracks, observations, evidence and events in World Memory.

One pass per source: detection (Ultralytics on a laptop, HailoRT on the UGen300 — same
`traceai.perception` interface) + ByteTrack, then per-workspace rules that turn tracks into
events. Every stored frame is privacy-masked (head regions blurred). A browser-playable proxy of
the processed stream is written so investigators never need the raw footage.
"""
from __future__ import annotations

import os

import hashlib
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from traceai.evidence import mask_people
from traceai.perception import COCO_NAMES, Tracker, make_detector

from . import db

ROOT = db.ROOT
MEDIA = ROOT / "media" / "vestige"
# IncidentLab measured YOLO11s keeping +29 pp more detections under occlusion and +33 pp under blur than YOLO11n
# (results/incidentlab_bench-road_*.md). Switching ingestion to it changed box geometry enough to drop the campus
# cross-camera colour similarity from 0.59 to 0.46 (links rejected), so the demo memory stays on YOLO11n until the
# colour signature is made hue-shift tolerant. Set VESTIGE_MODEL=yolo11s to try it.
DEFAULT_MODEL = os.environ.get("VESTIGE_MODEL", "yolo11n")
GOLD = (59, 163, 224)      # BGR of #E0A33B
IVORY = (218, 230, 236)

CLASSES = {
    "campus": [0, 1],
    "construction": [0, 2, 5, 7],
    "metro": [0],
    "road": [1, 2, 3, 5, 7],
}
VEHICLES = {"car", "bus", "truck"}


@dataclass
class TrackAcc:
    tid: int
    obs: list = field(default_factory=list)   # (t, frame_idx, x1, y1, x2, y2, conf)
    cls_votes: dict = field(default_factory=lambda: defaultdict(int))
    best: tuple | None = None                  # (area, frame_idx, t, bbox)
    hist_sum: np.ndarray | None = None         # running sum of per-frame colour signatures
    hist_n: int = 0
    merged: list = field(default_factory=list)  # tracklet ids stitched into this track

    @property
    def hist(self):
        return None if self.hist_sum is None else self.hist_sum / self.hist_n

    @property
    def cls(self) -> str:
        return max(self.cls_votes, key=self.cls_votes.get)


def appearance(frame: np.ndarray, box) -> np.ndarray | None:
    """Hue histogram of saturated pixels in the box (colour signature, no identity features)."""
    x1, y1, x2, y2 = (int(max(0, v)) for v in box)
    crop = frame[y1:y2, x1:x2]
    if crop.size < 400:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = ((hsv[..., 1] > 90) & (hsv[..., 2] > 50)).astype(np.uint8)
    if mask.sum() < 60:
        return None
    h = cv2.calcHist([hsv], [0], mask, [18], [0, 180]).flatten()
    return h / (h.sum() + 1e-9)


def colour_name(hist) -> str:
    if hist is None:
        return "low saturation"
    names = ["red", "orange", "yellow", "yellow-green", "green", "green", "teal", "cyan", "cyan",
             "blue", "blue", "blue", "violet", "purple", "magenta", "pink", "red", "red"]
    return names[int(np.argmax(hist))]


def similarity(a, b) -> float | None:
    if a is None or b is None:
        return None
    return float(np.minimum(np.asarray(a), np.asarray(b)).sum())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def save_frame(frame, path: Path, dets, highlight: set[int], label: str | None = None, width: int = 960):
    img = mask_people(frame.copy(), [d.xyxy for d in dets if d.name == "person"])
    for d in dets:
        x1, y1, x2, y2 = map(int, d.xyxy)
        hot = d.track_id in highlight
        cv2.rectangle(img, (x1, y1), (x2, y2), GOLD if hot else IVORY, 4 if hot else 2, cv2.LINE_AA)
        if hot:
            cv2.putText(img, f"{d.name} #{d.track_id}", (x1, max(24, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.9, GOLD, 2, cv2.LINE_AA)
    if label:
        cv2.putText(img, label, (24, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.0, IVORY, 2, cv2.LINE_AA)
    h, w = img.shape[:2]
    img = cv2.resize(img, (width, int(h * width / w)))
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 86])


def stitch(accs: dict[int, TrackAcc], fps: float, per_frame: dict, max_gap_s: float = 2.5,
           max_jump: float = 2.0) -> dict[int, TrackAcc]:
    """Merge tracklets the tracker split (occlusion, fast motion, pose change).

    A tracklet B continues A if both have the same class, B starts within `max_gap_s` after A ends,
    and B's first box centre lies within `max_jump` of A's last box size. Detection boxes are
    relabelled so evidence frames highlight the stitched track.
    """
    order = sorted(accs.values(), key=lambda a: a.obs[0][0])
    alive: list[TrackAcc] = []
    remap: dict[int, int] = {}
    for b in order:
        best, best_d = None, None
        for a in alive:
            if a.cls != b.cls or b.obs[0][0] < a.obs[-1][0] - 0.25 or b.obs[0][0] - a.obs[-1][0] > max_gap_s:
                continue
            la, fb = a.obs[-1], b.obs[0]
            size = max(la[4] - la[2], la[5] - la[3], 1)
            d = np.hypot((la[2] + la[4]) / 2 - (fb[2] + fb[4]) / 2, (la[3] + la[5]) / 2 - (fb[3] + fb[5]) / 2) / size
            if d <= max_jump and (best_d is None or d < best_d):
                best, best_d = a, d
        if best is None:
            alive.append(b)
            continue
        best.obs += b.obs
        for k, v in b.cls_votes.items():
            best.cls_votes[k] += v
        if b.best and (best.best is None or b.best[0] > best.best[0]):
            best.best = b.best
        if b.hist_sum is not None:
            best.hist_sum = b.hist_sum if best.hist_sum is None else best.hist_sum + b.hist_sum
            best.hist_n += b.hist_n
        best.merged.append(b.tid)
        remap[b.tid] = best.tid
    for dets in per_frame.values():
        for d in dets:
            while d.track_id in remap:
                d.track_id = remap[d.track_id]
    return {a.tid: a for a in alive}


def process_source(conn, src: dict, progress=None, detector_cfg: dict | None = None) -> dict:
    """Run perception on one video source and write tracks/observations/evidence/events."""
    ws = db.row(conn.execute("SELECT * FROM workspaces WHERE id=?", (src["workspace_id"],)).fetchone())
    kind = ws["kind"]
    cfg = {"weights": str(ROOT / f"models/{DEFAULT_MODEL}.pt"), "imgsz": 960, "conf": 0.3, "process_fps": 10}
    cfg.update(detector_cfg or {})
    video = ROOT / src["media_path"]
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    stride = max(1, round(fps / cfg["process_fps"]))
    detector = make_detector(cfg.get("backend", "ultralytics"), weights=cfg["weights"], imgsz=cfg["imgsz"],
                             conf=cfg["conf"], classes=CLASSES[kind], hef=cfg.get("hef"))
    tracker = Tracker(frame_rate=fps / stride)
    t0 = datetime.fromisoformat(src["start_ts"])
    out_dir = MEDIA / src["workspace_id"] / src["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    proxy_tmp = out_dir / "proxy.tmp.avi"
    pw = 1280
    ph = int(H * pw / W) // 2 * 2
    writer = cv2.VideoWriter(str(proxy_tmp), cv2.VideoWriter_fourcc(*"MJPG"), fps / stride, (pw, ph))
    accs: dict[int, TrackAcc] = {}
    per_frame: dict[int, list] = {}
    f = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if f % stride == 0:
            t = f / fps
            tracks = tracker.update(detector.detect(frame), frame)
            per_frame[f] = tracks
            for d in tracks:
                a = accs.setdefault(d.track_id, TrackAcc(d.track_id))
                x1, y1, x2, y2 = d.xyxy
                a.obs.append((t, f, x1, y1, x2, y2, d.conf))
                a.cls_votes[d.name] += 1
                area = (x2 - x1) * (y2 - y1)
                if a.best is None or area > a.best[0]:
                    a.best = (area, f, t, d.xyxy)
                if d.name == "bicycle" or d.name in VEHICLES:
                    h = appearance(frame, d.xyxy)
                    if h is not None:
                        a.hist_sum = h if a.hist_sum is None else a.hist_sum + h
                        a.hist_n += 1
            vis = mask_people(frame.copy(), [d.xyxy for d in tracks if d.name == "person"])
            for d in tracks:
                x1, y1, x2, y2 = map(int, d.xyxy)
                col = GOLD if d.name != "person" else IVORY
                cv2.rectangle(vis, (x1, y1), (x2, y2), col, 3, cv2.LINE_AA)
                cv2.putText(vis, f"{d.name} #{d.track_id}", (x1, max(24, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                            0.8, col, 2, cv2.LINE_AA)
            writer.write(cv2.resize(vis, (pw, ph)))
            if progress and f % (stride * 10) == 0:
                progress(0.85 * f / n_total, f"frame {f}/{n_total}")
        f += 1
    cap.release()
    writer.release()
    proxy = out_dir / "proxy.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(proxy_tmp), "-c:v", "libx264", "-pix_fmt",
                    "yuv420p", "-crf", "24", "-preset", "veryfast", "-movflags", "+faststart", str(proxy)],
                   check=True)
    proxy_tmp.unlink(missing_ok=True)
    duration = f / fps
    conn.execute("UPDATE sources SET fps=?, duration_s=?, width=?, height=? WHERE id=?",
                 (fps, duration, W, H, src["id"]))

    def ts(t: float) -> str:
        return (t0 + timedelta(seconds=t)).isoformat(timespec="seconds")

    def frame_at(fi: int):
        c2 = cv2.VideoCapture(str(video))
        for _ in range(fi):
            if not c2.grab():
                break
        ok, img = c2.read()
        c2.release()
        return img if ok else None

    ev_n = [0]

    def evidence(fi: int, highlight: set[int], label: str, caption: str) -> str:
        ev_n[0] += 1
        eid = f"E-{src['id']}-{ev_n[0]:03d}"
        img = frame_at(fi)
        if img is None:
            return ""
        p = out_dir / f"{eid}.jpg"
        save_frame(img, p, per_frame.get(fi, []), highlight, label)
        db.insert(conn, "evidence", {
            "id": eid, "workspace_id": src["workspace_id"], "source_id": src["id"], "kind": "frame",
            "path": str(p.relative_to(ROOT)), "ts": ts(fi / fps), "frame_idx": fi, "t_offset_s": round(fi / fps, 2),
            "sha256": sha(p), "provenance": src["provenance"], "caption": caption, "created_ts": db.now()})
        return eid

    model = f"{Path(cfg['weights']).stem} + ByteTrack + stitching"
    n_raw = len([a for a in accs.values() if len(a.obs) >= 5])
    accs = stitch(accs, fps, per_frame)
    kept = {tid: a for tid, a in accs.items() if len(a.obs) >= 5}
    stats = {"tracks": len(kept), "tracklets_before_stitching": n_raw, "observations": 0, "events": 0}
    for tid, a in kept.items():
        track_id = f"T-{src['id']}-{tid}"
        first, last = a.obs[0], a.obs[-1]
        db.insert(conn, "tracks", {
            "id": track_id, "workspace_id": src["workspace_id"], "source_id": src["id"], "cls": a.cls,
            "start_ts": ts(first[0]), "end_ts": ts(last[0]), "n_frames": len(a.obs),
            "appearance": a.hist.tolist() if a.hist is not None else None,
            "path": [[round(o[0], 2), round((o[2] + o[4]) / 2 / W, 4), round((o[3] + o[5]) / 2 / H, 4),
                      round((o[4] - o[2]) / W, 4), round((o[5] - o[3]) / H, 4)] for o in a.obs],
            "model": model})
        if a.cls in ("bicycle",) or a.cls in VEHICLES or kind != "metro":
            fi = a.best[1]
            eid = evidence(fi, {tid}, f"{src['name']} · {ts(a.best[2])[11:]}",
                           f"{a.cls} #{tid} seen on {src['name']}")
            for status, o in (("OBSERVED", first), ("LAST_SEEN", last)):
                oid = f"O-{track_id}-{'a' if status == 'OBSERVED' else 'z'}"
                db.insert(conn, "observations", {
                    "id": oid, "workspace_id": src["workspace_id"], "source_id": src["id"], "ts": ts(o[0]),
                    "kind": "seen", "status": status, "track_id": track_id, "zone_id": src["zone_id"],
                    "bbox": [round(v, 1) for v in o[2:6]], "frame_idx": o[1], "evidence_id": eid,
                    "model": model, "confidence": round(float(o[6]), 3), "provenance": src["provenance"],
                    "detail": f"{a.cls} #{tid} {'enters view' if status == 'OBSERVED' else 'last in view'}"
                              f" · colour {colour_name(a.hist)}"})
                stats["observations"] += 1

    rules = {"campus": _rules_campus, "construction": _rules_construction}.get(kind)
    if rules:
        stats["events"] += rules(conn, src, kept, per_frame, fps, W, H, ts, evidence, model)
    conn.execute("UPDATE sources SET status='processed', error=NULL WHERE id=?", (src["id"],))
    conn.commit()
    if progress:
        progress(1.0, f"{stats['tracks']} tracks, {stats['observations']} observations, {stats['events']} events")
    return stats


def _rules_campus(conn, src, kept, per_frame, fps, W, H, ts, evidence, model) -> int:
    """A bicycle has left its position when it moves more than 1.5 of its own widths, or when its box
    no longer overlaps its first position (IoU < 0.2) for at least one second — the second test
    handles large, close-up objects. The person whose box overlaps the bicycle while it moves is
    recorded as having moved it (OBSERVED, pseudonymous)."""
    n = 0
    bikes = {tid: a for tid, a in kept.items() if a.cls == "bicycle"}
    people = {tid: a for tid, a in kept.items() if a.cls == "person"}
    found = []
    for tid, a in bikes.items():
        cx = np.array([(o[2] + o[4]) / 2 for o in a.obs])
        cy = np.array([(o[3] + o[5]) / 2 for o in a.obs])
        wd = np.median([o[4] - o[2] for o in a.obs])
        disp = np.hypot(cx - cx[0], cy - cy[0]) / max(wd, 1)
        b0 = a.obs[0][2:6]

        def iou(b):
            ix = max(0, min(b0[2], b[2]) - max(b0[0], b[0]))
            iy = max(0, min(b0[3], b[3]) - max(b0[1], b[1]))
            inter = ix * iy
            return inter / ((b0[2] - b0[0]) * (b0[3] - b0[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter + 1e-9)

        off = np.array([iou(o[2:6]) < 0.2 for o in a.obs])
        need = max(1, int(round(fps / max(1, round(fps / 10)))))  # ~1 s of processed frames
        sustained = [i for i in range(len(off)) if off[i:i + need].all() and len(off[i:i + need]) == need]
        moved = np.where(disp > 1.5)[0]
        if sustained:
            moved = np.array(sorted(set(moved.tolist()) | {sustained[0]}))
        # Handled-and-moved: cumulative path of the box centre (not net displacement) passes one
        # bicycle width while a person's box overlaps it — catches lifting a bike off a rack.
        k = 5
        sx = np.convolve(cx, np.ones(k) / k, mode="same") if len(cx) > k else cx
        sy = np.convolve(cy, np.ones(k) / k, mode="same") if len(cy) > k else cy
        path = np.concatenate([[0], np.cumsum(np.hypot(np.diff(sx), np.diff(sy)))]) / max(wd, 1)
        person_frames = {}
        for pid, p in people.items():
            for q in p.obs:
                person_frames.setdefault(q[1], []).append(q)

        def touched(o):
            return any(not (q[4] < o[2] or o[4] < q[2] or q[5] < o[3] or o[5] < q[3])
                       for q in person_frames.get(o[1], []))

        handled = [i for i, o in enumerate(a.obs) if path[i] >= 1.0 and touched(o)]
        if handled:
            moved = np.array(sorted(set(moved.tolist()) | {handled[0]}))
        if not len(moved):
            continue
        i = int(moved[0])
        t_move, f_move = a.obs[i][0], a.obs[i][1]
        movers = []
        for pid, p in people.items():
            frames = {o[1]: o for o in p.obs}
            overlap = 0
            for o in a.obs[max(0, i - 15): i + 15]:
                q = frames.get(o[1])
                if q and not (q[4] < o[2] or o[4] < q[2] or q[5] < o[3] or o[5] < q[3]):
                    overlap += 1
            if overlap >= 3:
                movers.append(pid)
        found.append((t_move, f_move, tid, i, movers, disp, path))
    zone = db.row(conn.execute("SELECT * FROM zones WHERE id=?", (src["zone_id"],)).fetchone())
    parking = bool(zone and zone["kind"] == "parking")
    # Collapse tracklets of one bicycle moving at the same time into a single event.
    groups: list[list] = []
    for item in sorted(found):
        if groups and item[0] - groups[-1][0][0] <= 10:
            groups[-1].append(item)
        else:
            groups.append([item])
    for g in groups:
        t_move, f_move, tid, i, movers, disp, path = g[0]
        tids = [x[2] for x in g]
        movers = sorted({m for x in g for m in x[4]})
        a = bikes[tid]
        track_id = f"T-{src['id']}-{tid}"
        verb = "leaves its parked position" if parking else "moves with a person"
        eid = evidence(f_move, {*tids, *movers}, f"{src['name']} · {ts(t_move)[11:]}",
                       f"bicycle #{tid} {verb}" + (f" — person #{movers[0]}" if movers else ""))
        for x in g:
            oid = f"O-T-{src['id']}-{x[2]}-moved"
            db.insert(conn, "observations", {
                "id": oid, "workspace_id": src["workspace_id"], "source_id": src["id"], "ts": ts(x[0]),
                "kind": "moved" if parking else "in_motion", "status": "OBSERVED",
                "track_id": f"T-{src['id']}-{x[2]}", "zone_id": src["zone_id"],
                "bbox": [round(v, 1) for v in bikes[x[2]].obs[x[3]][2:6]], "frame_idx": x[1], "evidence_id": eid,
                "model": model, "provenance": src["provenance"],
                "detail": f"bicycle #{x[2]} {verb}"
                          + (f"; handled by person #{movers[0]} (pseudonymous)" if movers else "")})
        if not parking:
            continue
        evt = f"EV-{src['id']}-move-{tid}"
        db.insert(conn, "events", {
            "id": evt, "workspace_id": src["workspace_id"], "kind": "object_moved",
            "title": "Bicycle left its parked position", "ts_start": ts(a.obs[0][0]), "ts_end": ts(t_move),
            "priority": "medium", "summary": "", "provenance": src["provenance"], "model": model,
            "metrics": {"displacement_widths": round(float(disp.max()), 2),
                        "path_widths": round(float(path.max()), 2), "movers": movers, "tracklets": tids},
            "evidence_id": eid, "zone_id": src["zone_id"]})
        for x in g:
            conn.execute("INSERT OR REPLACE INTO event_links VALUES (?,?,?)",
                         (evt, f"O-T-{src['id']}-{x[2]}-moved", "trigger"))
            conn.execute("INSERT OR REPLACE INTO event_links VALUES (?,?,?)",
                         (evt, f"O-T-{src['id']}-{x[2]}-a", "before"))
        for pid in movers:
            db.insert(conn, "relations", {
                "id": f"R-{evt}-{pid}", "workspace_id": src["workspace_id"], "kind": "moved_by",
                "a_id": track_id, "b_id": f"T-{src['id']}-{pid}", "status": "OBSERVED",
                "basis": {"overlap_frames": True, "note": "boxes overlap while the bicycle moves"},
                "created_ts": db.now()})
        n += 1
    return n


def _rules_construction(conn, src, kept, per_frame, fps, W, H, ts, evidence, model) -> int:
    """Worker–vehicle proximity in image space: gap between person and vehicle boxes, normalised
    by the person's height. Uncalibrated — this is not a metric distance."""
    n = 0
    hits: dict[tuple, list] = defaultdict(list)
    heavy = {"truck", "bus"}  # parked cars are not site machinery

    def inside(p, v):
        ix = max(0, min(p[2], v[2]) - max(p[0], v[0]))
        iy = max(0, min(p[3], v[3]) - max(p[1], v[1]))
        return ix * iy / max((p[2] - p[0]) * (p[3] - p[1]), 1) > 0.8

    for fi, dets in sorted(per_frame.items()):
        persons = [d for d in dets if d.name == "person"]
        vehicles = [d for d in dets if d.name in heavy]
        for p in persons:
            ph = p.xyxy[3] - p.xyxy[1]
            for v in vehicles:
                if inside(p.xyxy, v.xyxy):
                    continue  # the operator in the cab
                dx = max(v.xyxy[0] - p.xyxy[2], p.xyxy[0] - v.xyxy[2], 0)
                dy = max(v.xyxy[1] - p.xyxy[3], p.xyxy[1] - v.xyxy[3], 0)
                gap = float(np.hypot(dx, dy)) / max(ph, 1)
                if gap < 0.35:
                    hits[(p.track_id, v.track_id)].append((fi, gap))
    # One event per worker: keep the vehicle they came closest to.
    best_pair: dict[int, tuple] = {}
    for (pid, vid), hs in hits.items():
        g = min(h[1] for h in hs)
        if pid not in best_pair or g < best_pair[pid][1]:
            best_pair[pid] = ((pid, vid), g)
    hits = {pair: hits[pair] for pair, _ in best_pair.values()}
    for (pid, vid), hs in hits.items():
        if pid not in kept or vid not in kept:
            continue
        dur = (hs[-1][0] - hs[0][0]) / fps
        if dur < 1.0:
            continue
        f_min, g_min = min(hs, key=lambda h: h[1])
        vcls = kept[vid].cls
        eid = evidence(f_min, {pid, vid}, f"{src['name']} · {ts(f_min / fps)[11:]} · proximity",
                       f"person #{pid} " + ("overlapping" if g_min < 0.01 else f"within {g_min:.2f} body-heights of")
                       + f" {vcls} #{vid} in the image")
        oid = f"O-{src['id']}-prox-{pid}-{vid}"
        db.insert(conn, "observations", {
            "id": oid, "workspace_id": src["workspace_id"], "source_id": src["id"], "ts": ts(hs[0][0] / fps),
            "kind": "proximity", "status": "OBSERVED", "track_id": f"T-{src['id']}-{pid}",
            "zone_id": src["zone_id"], "frame_idx": f_min, "evidence_id": eid, "model": model,
            "provenance": src["provenance"],
            "detail": f"worker #{pid} " + ("overlapping" if g_min < 0.01 else f"within {g_min:.2f} body-heights of")
                      + f" {vcls} #{vid} for {dur:.1f} s (image-space, uncalibrated)"})
        evt = f"EV-{src['id']}-prox-{pid}-{vid}"
        db.insert(conn, "events", {
            "id": evt, "workspace_id": src["workspace_id"], "kind": "worker_vehicle_proximity",
            "title": f"Worker in {vcls} hazard zone", "ts_start": ts(hs[0][0] / fps), "ts_end": ts(hs[-1][0] / fps),
            "priority": "high" if g_min < 0.1 else "medium", "summary": "", "provenance": src["provenance"],
            "model": model, "metrics": {"min_gap_body_heights": round(g_min, 3), "duration_s": round(dur, 1),
                                        "vehicle_class": vcls},
            "evidence_id": eid, "zone_id": src["zone_id"]})
        conn.execute("INSERT OR REPLACE INTO event_links VALUES (?,?,?)", (evt, oid, "trigger"))
        for tid in (pid, vid):
            o = f"O-T-{src['id']}-{tid}-a"
            if conn.execute("SELECT 1 FROM observations WHERE id=?", (o,)).fetchone():
                conn.execute("INSERT OR REPLACE INTO event_links VALUES (?,?,?)", (evt, o, "context"))
        n += 1
    return n
