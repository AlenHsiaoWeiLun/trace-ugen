"""IncidentLab pilot: how stable are detections under controlled image corruptions?

Reference = YOLO detections on the clean frame (conf >= 0.5). This measures *consistency with
the clean frame*, not accuracy against human labels; occlusion is graded only on boxes it hides.

    python scripts/incidentlab_pilot.py --out results/incidentlab_pilot.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent.parent
CLIPS = {
    "station": ["pexels_37737804.mp4", "pexels_34647618.mp4", "pexels_35767994.mp4"],
    "road": ["bridge_06.webm", "bridge_07.webm", "pexels_4740223.mp4"],
}
CLASSES = {"station": [0], "road": [1, 2, 3, 5, 7]}


def low_light(img, rng):
    return np.clip(((img / 255.0) ** 2.2) * 0.35 * 255 + rng.normal(0, 4, img.shape), 0, 255).astype(np.uint8)


def motion_blur(img, rng, k=17):
    kern = np.zeros((k, k), np.float32)
    kern[k // 2, :] = 1.0 / k
    return cv2.filter2D(img, -1, kern)


def noise(img, rng):
    return np.clip(img + rng.normal(0, 28, img.shape), 0, 255).astype(np.uint8)


def low_res(img, rng):
    h, w = img.shape[:2]
    small = cv2.resize(img, (w // 4, h // 4), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def occlude(img, rng, boxes):
    """Grey patch over the lower 40% of half the reference boxes; returns image + ids of occluded boxes."""
    out = img.copy()
    hidden = []
    for i, (x1, y1, x2, y2) in enumerate(boxes):
        if rng.random() < 0.5:
            y0 = int(y1 + 0.6 * (y2 - y1))
            out[y0:int(y2), int(x1):int(x2)] = 114
            hidden.append(i)
    return out, hidden


CORRUPTIONS = {"low_light": low_light, "motion_blur": motion_blur, "noise": noise, "low_res": low_res}


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter + 1e-9)


def matched(ref, pred, thr=0.5):
    used, hits = set(), []
    for i, r in enumerate(ref):
        best, bj = 0, None
        for j, p in enumerate(pred):
            if j in used or p[4] != r[4]:
                continue
            v = iou(r, p)
            if v > best:
                best, bj = v, j
        if best >= thr:
            used.add(bj)
            hits.append(i)
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=8, help="frames per clip")
    ap.add_argument("--out", default="results/incidentlab_pilot.json")
    a = ap.parse_args()
    model = YOLO(str(ROOT / "models/yolo11n.pt"))
    rng = np.random.default_rng(7)
    stats = {}
    examples = []

    def det(img, cls):
        r = model.predict(img, imgsz=960, conf=0.25, classes=cls, verbose=False)[0].boxes
        return [(*map(float, b), int(c)) for b, c in zip(r.xyxy.cpu().numpy(), r.cls.cpu().numpy())]

    for domain, clips in CLIPS.items():
        cls = CLASSES[domain]
        for clip in clips:
            cap = cv2.VideoCapture(str(ROOT / "data/videos" / clip))
            n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            for idx in np.linspace(n * 0.1, n * 0.9, a.frames).astype(int):
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
                ok, img = cap.read()
                if not ok:
                    continue
                r = model.predict(img, imgsz=960, conf=0.5, classes=cls, verbose=False)[0].boxes
                ref = [(*map(float, b), int(c)) for b, c in zip(r.xyxy.cpu().numpy(), r.cls.cpu().numpy())]
                if not ref:
                    continue
                for name, fn in CORRUPTIONS.items():
                    hits = matched(ref, det(fn(img, rng), cls))
                    s = stats.setdefault(domain, {}).setdefault(name, [0, 0])
                    s[0] += len(hits)
                    s[1] += len(ref)
                occ, hidden = occlude(img, rng, [b[:4] for b in ref])
                if hidden:
                    hits = set(matched(ref, det(occ, cls)))
                    s = stats[domain].setdefault("occlusion", [0, 0])
                    s[0] += sum(1 for i in hidden if i in hits)
                    s[1] += len(hidden)
                if len(examples) < 1 and domain == "station" and len(ref) >= 6:
                    examples.append((clip, int(idx)))
            cap.release()
    result = {d: {k: {"recalled": v[0], "reference": v[1], "rate": round(v[0] / v[1], 3)} for k, v in s.items()}
              for d, s in stats.items()}
    out = {"method": "reference = YOLO11n detections on clean frame (conf>=0.5); recall at IoU>=0.5 after "
                     "corruption (conf>=0.25); occlusion graded on hidden boxes only; not human ground truth",
           "model": "yolo11n.pt @960", "frames_per_clip": a.frames, "results": result, "example": examples}
    Path(a.out).parent.mkdir(exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=2))
    for d, s in result.items():
        print(d, {k: f"{v['rate']:.0%} ({v['recalled']}/{v['reference']})" for k, v in s.items()})


if __name__ == "__main__":
    main()
