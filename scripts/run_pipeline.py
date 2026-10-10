"""Run the TRACE pipeline over a scenario config and write data/run_<scenario>.json.

    python scripts/run_pipeline.py configs/metro_demo.yaml
    python scripts/run_pipeline.py configs/road_demo.yaml --vlm

Pass 1 runs detection + tracking + rules per camera and records tracked boxes per frame.
Radio clips are transcribed, scripted detector alarms are added, and all signals are
fused. Pass 2 re-reads only the frames around each incident to cut masked evidence clips.
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import count
from pathlib import Path

import cv2
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from traceai.evidence import ClipWriter, draw, mask_people  # noqa: E402
from traceai.fusion import FusionEngine, ZoneGraph  # noqa: E402
from traceai.perception import COCO_NAMES, StageTimer, Tracker, make_detector  # noqa: E402
from traceai.rules import CameraContext, MetroRules, Obs, RoadRules  # noqa: E402
from traceai.schema import Signal  # noqa: E402
from traceai.speech import radio_signal  # noqa: E402
from traceai.summarize import VLMCaptioner, template_summary  # noqa: E402
from traceai.verify import DESCRIBE, second_opinion  # noqa: E402


SOP = yaml.safe_load((ROOT / "configs" / "sop.yaml").read_text())


def device_name() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return f"cuda ({torch.cuda.get_device_name(0)})"
        if torch.backends.mps.is_available():
            chip = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                                  text=True).stdout.strip()
            return f"mps ({chip})"
    except Exception:
        pass
    return f"cpu ({platform.processor() or platform.machine()})"


def process_camera(cam: dict, cfg: dict, det_cfg: dict, t0: datetime, ids, timer: StageTimer):
    probe = cv2.VideoCapture(str(ROOT / cam["video"]))
    fps = probe.get(cv2.CAP_PROP_FPS) or 30.0
    W, H = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH)), int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT))
    probe.release()
    stride = max(1, int(round(fps / det_cfg.get("process_fps", 15))))
    max_s = cam.get("max_seconds", 1e9)
    start_s = cam.get("start_seconds", 0.0)
    cap = open_at(str(ROOT / cam["video"]), int(start_s * fps))
    scenario = cfg["scenario"]
    classes = [0] if scenario == "metro" else [1, 2, 3, 5, 7]
    detector = make_detector(det_cfg.get("backend", "ultralytics"), weights=det_cfg.get("weights", "yolo11n.pt"),
                             device=det_cfg.get("device"), imgsz=det_cfg.get("imgsz", 960),
                             conf=det_cfg.get("conf", 0.3), classes=classes, hef=det_cfg.get("hef"))
    tracker = Tracker(frame_rate=fps / stride)
    ctx = CameraContext(cam["sensor"], cam["zone"], scenario, t0 + timedelta(seconds=cam.get("offset_s", 0)),
                        cam["video"], fps)
    rule_kw = {**cfg.get("rules", {}), **cam.get("rules", {})}
    rules = MetroRules(ctx, ids, **rule_kw) if scenario == "metro" else RoadRules(ctx, ids, frame_size=(W, H),
                                                                                  **rule_kw)
    boxes: dict[int, list] = {}
    signals: list[Signal] = []
    frame_idx = int(start_s * fps)
    n_proc = 0
    while True:
        ok, frame = cap.read()
        if not ok or (frame_idx / fps - start_s) > max_s:
            break
        if (frame_idx - int(start_s * fps)) % stride == 0:
            t = frame_idx / fps - start_s
            with timer("detect"):
                dets = detector.detect(frame)
            with timer("track"):
                tracks = tracker.update(dets, frame)
            boxes[frame_idx] = tracks
            obs = [(d.track_id, Obs(t, (d.xyxy[0] + d.xyxy[2]) / 2, (d.xyxy[1] + d.xyxy[3]) / 2,
                                    d.xyxy[2] - d.xyxy[0], d.xyxy[3] - d.xyxy[1], d.name, d.conf, frame_idx))
                   for d in tracks]
            with timer("rules"):
                signals += rules.update(t, frame_idx, obs)
            n_proc += 1
        frame_idx += 1
    if isinstance(rules, RoadRules):
        signals += rules.close()
    cap.release()
    print(f"  {cam['sensor']}: {n_proc} frames, {len(signals)} signals, detector={detector.name}")
    meta = {"fps": fps, "size": (W, H), "boxes": boxes, "detector": detector.name, "start_s": start_s,
            "finished": getattr(rules, "finished", []), "counts": getattr(rules, "count_series", [])}
    return signals, meta


def open_at(path: str, frame: int):
    """Open a video positioned at `frame` by decoding forward (exact even for WebM/VFR)."""
    cap = cv2.VideoCapture(path)
    for _ in range(max(0, frame)):
        if not cap.grab():
            break
    return cap


def nearest_boxes(boxes: dict[int, list], f: int):
    if not boxes:
        return []
    k = min(boxes, key=lambda x: abs(x - f))
    return boxes[k]


def render_evidence(inc, cams: dict, metas: dict, media: Path, scenario: str):
    cam_sigs = [s for s in inc.signals if s.source == "camera" and s.video]
    if not cam_sigs:
        return None, None
    primary = max(cam_sigs, key=lambda s: s.confidence)
    meta = metas[primary.sensor]
    fps = meta["fps"]
    hot = {int(primary.features["track_id"])} if "track_id" in primary.features else set()
    f0 = max(int(meta["start_s"] * fps), primary.frame - int(3.0 * fps))
    f1 = primary.frame + int(3.0 * fps)
    cap = open_at(str(ROOT / primary.video), f0)
    clip_path = media / f"{inc.id}.mp4"
    W, H = meta["size"]
    writer = ClipWriter(clip_path, fps, (W, H))
    trails: dict[int, list] = defaultdict(list)
    keyframe = frame = None
    label = f"{primary.sensor} | zone {primary.zone} | {primary.kind}"
    for f in range(f0, f1 + 1):
        ok, frame = cap.read()
        if not ok:
            break
        dets = nearest_boxes(meta["boxes"], f)
        for d in dets:
            if d.track_id in hot or scenario == "road":
                trails[d.track_id].append(((d.xyxy[0] + d.xyxy[2]) / 2, (d.xyxy[1] + d.xyxy[3]) / 2))
        frame = mask_people(frame, [d.xyxy for d in dets if d.name == "person"])
        if f == primary.frame:
            # The VLM sees the masked frame without overlays: drawn boxes measurably hurt its answers.
            vlm_view = frame
            boxes = [d.xyxy for d in dets if d.track_id in hot]
            if scenario == "road" and boxes:  # crop around the flagged vehicle so "the center" is unambiguous
                x1, y1, x2, y2 = boxes[0]
                side = int(max(4 * (x2 - x1), 4 * (y2 - y1), 336))
                cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
                fh, fw = frame.shape[:2]
                side = min(side, fw, fh)
                left = min(max(0, cx - side // 2), fw - side)
                top = min(max(0, cy - side // 2), fh - side)
                vlm_view = frame[top:top + side, left:left + side]
            cv2.imwrite(str(media / f"{inc.id}_vlm.jpg"), vlm_view, [cv2.IMWRITE_JPEG_QUALITY, 90])
        frame = draw(frame, dets, hot, label, {k: v for k, v in trails.items() if k in hot})
        writer.write(frame)
        if f == primary.frame:
            keyframe = frame.copy()
    writer.close()
    cap.release()
    if keyframe is None:
        keyframe = frame
    if keyframe is None:
        return None, None
    kf_path = media / f"{inc.id}.jpg"
    cv2.imwrite(str(kf_path), cv2.resize(keyframe, (960, int(960 * H / W))), [cv2.IMWRITE_JPEG_QUALITY, 85])
    for s in cam_sigs:
        cap = open_at(str(ROOT / s.video), s.frame)
        ok, fr = cap.read()
        cap.release()
        if ok:
            dets = nearest_boxes(metas[s.sensor]["boxes"], s.frame)
            fr = draw(mask_people(fr, [d.xyxy for d in dets if d.name == "person"]), dets,
                      {int(s.features["track_id"])} if "track_id" in s.features else set())
            p = media / f"{s.id}.jpg"
            cv2.imwrite(str(p), cv2.resize(fr, (480, int(480 * H / W))), [cv2.IMWRITE_JPEG_QUALITY, 80])
            s.thumb = f"/media/{media.name}/{p.name}"
    return f"/media/{media.name}/{kf_path.name}", f"/media/{media.name}/{clip_path.name}"


def scene_checks(signals, cfg, metas, graph, t0, ids) -> list[Signal]:
    """Camera-on-demand: when a non-visual alarm fires, snapshot cameras in the same or adjacent zone."""
    out = []
    for s in [x for x in signals if x.source != "camera"]:
        for cam in cfg["cameras"]:
            if graph.hops(cam["zone"], s.zone, 1) > 1:
                continue
            m = metas[cam["sensor"]]
            t_local = (s.ts - t0).total_seconds() - cam.get("offset_s", 0) + m["start_s"]
            f = int(t_local * m["fps"])
            if not m["boxes"] or not min(m["boxes"]) <= f <= max(m["boxes"]):
                continue
            n = sum(1 for d in nearest_boxes(m["boxes"], f) if d.name == "person")
            out.append(Signal(id=next(ids), source="camera", sensor=cam["sensor"], zone=cam["zone"],
                              ts=s.ts + timedelta(seconds=0.5), kind="scene_check", confidence=0.35,
                              detail=f"{n} people visible when {s.sensor} fired", scenario=cfg["scenario"],
                              video=cam["video"], frame=f))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--vlm", action="store_true", help="add a SmolVLM keyframe description to summaries")
    ap.add_argument("--vlm-hef", help="use Qwen2-VL-2B on the UGen300 instead of SmolVLM")
    ap.add_argument("--min-priority", default="low", choices=["low", "medium", "high"])
    a = ap.parse_args()
    cfg = yaml.safe_load(Path(a.config).read_text())
    scenario = cfg["scenario"]
    t0 = datetime.fromisoformat(cfg["start_time"])
    det_cfg = cfg.get("detector", {})
    ids = (f"SIG-{scenario[0].upper()}{i:04d}" for i in count(1))
    timer = StageTimer()
    wall = time.perf_counter()

    print(f"[{scenario}] perception")
    signals, metas = [], {}
    for cam in cfg["cameras"]:
        sigs, meta = process_camera(cam, cfg, det_cfg, t0, ids, timer)
        signals += sigs
        metas[cam["sensor"]] = meta
    for d in cfg.get("detectors", []):
        signals.append(Signal(id=next(ids), source="detector", sensor=d["sensor"], zone=d["zone"],
                              ts=t0 + timedelta(seconds=d["at_s"]), kind="detector_alarm",
                              confidence=d.get("confidence", 0.7), detail=d.get("detail", ""), scenario=scenario))
    asr_cfg = cfg.get("asr", {})
    asr = asr_cfg.get("model", "tiny.en")
    transcriber = None
    if asr_cfg.get("backend") == "hailo":
        from traceai.hailo import HailoWhisper

        transcriber = HailoWhisper(asr_cfg["hef"]).transcribe
        asr = asr_cfg["hef"].rsplit("/", 1)[-1]
    for r in cfg.get("radio", []):
        with timer("asr"):
            s = radio_signal(str(ROOT / r["audio"]), next(ids), r["sensor"], t0, r["at_s"],
                             cfg.get("zone_keywords", {}), r.get("zone", "A"), asr, transcriber)
        s.scenario = scenario
        print(f"  {r['sensor']}: \"{s.transcript}\" -> zone {s.zone}, conf {s.confidence}")
        signals.append(s)

    fz = cfg.get("fusion", {})
    graph = ZoneGraph.from_pairs(cfg["site"].get("adjacency", []))
    snaps = scene_checks(signals, cfg, metas, graph, t0, ids)
    signals += snaps
    print(f"[{scenario}] fusion of {len(signals)} signals ({len(snaps)} on-demand camera snapshots)")
    with timer("fusion"):
        incidents = FusionEngine(graph, window_s=fz.get("window_s", 30), max_hops=fz.get("max_hops", 1),
                                 max_duration_s=fz.get("max_duration_s", 180),
                                 scenario=scenario, id_prefix=f"INC-{scenario[0].upper()}").run(signals)
    order = {"low": 0, "medium": 1, "high": 2}
    incidents = [i for i in incidents if order[i.priority] >= order[a.min_priority]]

    media = ROOT / "media" / scenario
    if media.exists():
        shutil.rmtree(media)  # evidence from previous runs would be orphaned
    media.mkdir(parents=True)
    if a.vlm_hef:
        from traceai.hailo import HailoVLMCaptioner

        vlm = HailoVLMCaptioner(a.vlm_hef)
    else:
        vlm = VLMCaptioner() if a.vlm else None
    for inc in incidents:
        with timer("evidence"):
            inc.keyframe, inc.clip = render_evidence(inc, cfg["cameras"], metas, media, scenario)
        if vlm and inc.keyframe:
            clean = media / f"{inc.id}_vlm.jpg"
            kf = str(clean if clean.exists() else ROOT / inc.keyframe.lstrip("/"))
            t_v = time.perf_counter()
            with timer("vlm"):
                verdict = second_opinion(inc, vlm, kf)
                desc = vlm.caption(kf, DESCRIBE[scenario])
            inc.vlm = {"model": vlm.model_id.split("/")[-1], "description": desc, "second_opinion": verdict,
                       "ms": round(1000 * (time.perf_counter() - t_v))}
            print(f"  VLM {inc.id}: {desc!r} | second opinion: {verdict and verdict['answer']!r}")
        inc.summary = template_summary(inc)
        sops = SOP.get(scenario, {})
        inc.sop = sops.get(inc.title, sops.get("default", []))
        if inc.vlm:
            inc.summary += f' Scene check ({inc.vlm["model"]}): "{inc.vlm["description"]}"'
    stages = timer.report()
    per_frame = stages.get("detect", 0) + stages.get("track", 0) + stages.get("rules", 0)
    out = []
    for inc in incidents:
        inc.latency_ms = round(per_frame + stages.get("fusion", 0), 1)
        d = inc.to_json()
        d["release_s"] = round((inc.end_ts - t0).total_seconds(), 1)
        out.append(d)
    det_name = next(iter(metas.values()))["detector"] if metas else "-"
    run = {
        "scenario": scenario,
        "site": cfg["site"],
        "raw_signals": len(signals),
        "pipeline": {
            "device": device_name(),
            "detector": det_name,
            "fps": round(1000 / per_frame, 1) if per_frame else None,
            "asr": f"whisper {asr}" if cfg.get("radio") else None,
            "vlm": vlm.model_id if vlm else None,
            "target": "ASUS UGen300 / Hailo-10H",
            "frames_off_box": 0,
            "retention_h": 24,
            "stage_ms": {k: round(v, 2) for k, v in stages.items()},
            "wall_s": round(time.perf_counter() - wall, 1),
        },
        "incidents": out,
        "signals": [s.to_json() | {"incident": next((i.id for i in incidents if s in i.signals), None)}
                    for s in sorted(signals, key=lambda s: s.ts)],
    }
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / f"run_{scenario}.json").write_text(json.dumps(run, indent=2, default=str))
    tracks = [{"track_id": tid, "features": f} for m in metas.values() for tid, _, f in m["finished"]]
    if tracks:
        (ROOT / "data" / f"tracks_{scenario}.json").write_text(json.dumps(tracks, indent=1))
    print(f"[{scenario}] {len(signals)} signals -> {len(incidents)} incidents; stage ms {run['pipeline']['stage_ms']}")
    for i in out:
        print(f"  {i['id']} {i['priority']:6s} {i['score']:.2f} {i['title']} zones={i['zones']} n={i['n_signals']}")


if __name__ == "__main__":
    main()
