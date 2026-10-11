"""IncidentLab: controlled stress tests of the perception behind stored events.

Metric — Detection Retention Rate: of the detections the model makes on the clean frame
(confidence ≥ 0.5, the *reference*), the share it still makes after a perturbation (IoU ≥ 0.5,
same class, confidence ≥ 0.25). The reference is the model's own clean output, NOT human ground
truth, so this measures robustness, not accuracy. Occlusion is graded only on the boxes it hides;
"new" counts confident detections absent from the reference (a proxy for spurious detections).

Mitigations are test-time only (no retraining) and are always compared with the unmitigated
baseline on the same frames:
    enhance  — corruption-aware preprocessing (CLAHE + gamma, denoising, unsharp masking)
    hires    — inference at 1280 px instead of 960 px
    tta      — Ultralytics test-time augmentation (flips + scales)
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import cv2
import numpy as np

from traceai.evidence import mask_people

from . import db
from .ingest import CLASSES

ROOT = db.ROOT
OUT = ROOT / "media" / "vestige" / "lab"

PERTURBATIONS = {
    "low_light": {"label": "Low light", "levels": {1: 0.5, 2: 0.35, 3: 0.2}, "unit": "brightness gain"},
    "blur": {"label": "Motion blur", "levels": {1: 9, 2: 17, 3: 29}, "unit": "kernel px"},
    "noise": {"label": "Sensor noise", "levels": {1: 15, 2: 28, 3: 45}, "unit": "σ"},
    "low_res": {"label": "Low resolution", "levels": {1: 2, 2: 4, 3: 6}, "unit": "downscale ×"},
    "occlusion": {"label": "Partial occlusion", "levels": {1: 0.25, 2: 0.4, 3: 0.6}, "unit": "box share hidden"},
    "scale": {"label": "Distance (scale)", "levels": {1: 0.75, 2: 0.5, 3: 0.35}, "unit": "image scale"},
}
MITIGATIONS = {
    "none": "Baseline",
    "enhance": "Corruption-aware enhancement",
    "hires": "Higher inference resolution (1280 px)",
    "tta": "Test-time augmentation",
    "large": "Larger model (YOLO11s)",
}

_models: dict[str, object] = {}


def model(weights: str):
    if weights not in _models:
        from ultralytics import YOLO

        _models[weights] = YOLO(str(ROOT / "models" / weights))
    return _models[weights]


# ---------- perturbations (pure functions, seeded) ----------

def perturb(img, name: str, level: int, ref_boxes, rng):
    v = PERTURBATIONS[name]["levels"][level]
    boxes = [list(b) for b in ref_boxes]
    hidden = list(range(len(boxes)))
    if name == "low_light":
        out = np.clip(((img / 255.0) ** 2.2) * v * 255 + rng.normal(0, 3, img.shape), 0, 255).astype(np.uint8)
    elif name == "blur":
        k = np.zeros((v, v), np.float32)
        k[v // 2, :] = 1.0 / v
        out = cv2.filter2D(img, -1, k)
    elif name == "noise":
        out = np.clip(img + rng.normal(0, v, img.shape), 0, 255).astype(np.uint8)
    elif name == "low_res":
        h, w = img.shape[:2]
        out = cv2.resize(cv2.resize(img, (w // v, h // v), interpolation=cv2.INTER_AREA), (w, h))
    elif name == "occlusion":
        out = img.copy()
        hidden = []
        for i, (x1, y1, x2, y2, *_rest) in enumerate(boxes):
            if rng.random() < 0.5:
                y0 = int(y2 - v * (y2 - y1))
                out[y0:int(y2), int(x1):int(x2)] = 114
                hidden.append(i)
    elif name == "scale":
        h, w = img.shape[:2]
        sw, sh = int(w * v), int(h * v)
        out = np.full_like(img, 114)
        ox, oy = (w - sw) // 2, (h - sh) // 2
        out[oy:oy + sh, ox:ox + sw] = cv2.resize(img, (sw, sh), interpolation=cv2.INTER_AREA)
        boxes = [[x1 * v + ox, y1 * v + oy, x2 * v + ox, y2 * v + oy, *r] for x1, y1, x2, y2, *r in boxes]
    else:
        raise KeyError(name)
    return out, boxes, hidden


def enhance(img, name: str):
    if name == "low_light":
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        lab[..., 0] = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(lab[..., 0])
        out = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        lut = np.array([((i / 255.0) ** (1 / 1.8)) * 255 for i in range(256)], np.uint8)
        return cv2.LUT(out, lut)
    if name == "noise":
        h, w = img.shape[:2]
        s = 1280 / w if w > 1280 else 1.0
        small = cv2.resize(img, (int(w * s), int(h * s))) if s < 1 else img
        den = cv2.fastNlMeansDenoisingColored(small, None, 10, 10, 7, 21)
        return cv2.resize(den, (w, h)) if s < 1 else den
    if name in ("blur", "low_res"):
        g = cv2.GaussianBlur(img, (0, 0), 3)
        return cv2.addWeighted(img, 1.8, g, -0.8, 0)
    return img


# ---------- detection & grading ----------

def detect(weights, img, classes, conf, imgsz=960, augment=False):
    t = time.perf_counter()
    r = model(weights).predict(img, imgsz=imgsz, conf=conf, classes=classes, augment=augment, verbose=False)[0].boxes
    ms = 1000 * (time.perf_counter() - t)
    return [(*map(float, b), float(c), int(k)) for b, c, k in
            zip(r.xyxy.cpu().numpy(), r.conf.cpu().numpy(), r.cls.cpu().numpy())], ms


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter + 1e-9)


def match(ref, pred, thr=0.5):
    used, kept = set(), []
    for i, r in enumerate(ref):
        best, bj = 0.0, None
        for j, p in enumerate(pred):
            if j in used or p[5] != r[5]:
                continue
            v = iou(r, p)
            if v > best:
                best, bj = v, j
        if best >= thr:
            used.add(bj)
            kept.append(i)
    new = [j for j, p in enumerate(pred) if j not in used and p[4] >= 0.5]
    return kept, new


def draw(img, ref, pred, kept, hidden, new, width=960):
    out = mask_people(img.copy(), [r[:4] for r in ref if r[5] == 0])
    for i, r in enumerate(ref):
        x1, y1, x2, y2 = map(int, r[:4])
        if i not in hidden:
            continue
        ok = i in kept
        col = (218, 230, 236) if ok else (64, 76, 230)  # ivory kept / red missed
        cv2.rectangle(out, (x1, y1), (x2, y2), col, 3 if ok else 4, cv2.LINE_AA)
    for j in new:
        x1, y1, x2, y2 = map(int, pred[j][:4])
        cv2.rectangle(out, (x1, y1), (x2, y2), (200, 170, 40), 2, cv2.LINE_AA)
    h, w = out.shape[:2]
    return cv2.resize(out, (width, int(h * width / w)))


# ---------- experiments ----------

def frames_for(conn, workspace_id: str, scope: dict) -> list[dict]:
    if scope.get("evidence_ids"):
        ev = db.rows(conn.execute("SELECT * FROM evidence WHERE id IN (%s)" % ",".join("?" * len(scope["evidence_ids"])),
                                  scope["evidence_ids"]))
    elif scope.get("event_id"):
        ev = db.rows(conn.execute(
            "SELECT DISTINCT e.* FROM evidence e JOIN observations o ON o.evidence_id=e.id "
            "JOIN event_links l ON l.observation_id=o.id WHERE l.event_id=?", (scope["event_id"],)))
        evt = db.row(conn.execute("SELECT * FROM events WHERE id=?", (scope["event_id"],)).fetchone())
        if not ev and evt and evt.get("evidence_id"):
            ev = db.rows(conn.execute("SELECT * FROM evidence WHERE id=?", (evt["evidence_id"],)))
    else:
        ev = []
    frames = []
    for e in ev:
        src = db.row(conn.execute("SELECT * FROM sources WHERE id=?", (e["source_id"],)).fetchone())
        if src and src.get("media_path") and e.get("frame_idx") is not None:
            frames.append({"ref": e["id"], "video": src["media_path"], "frame_idx": e["frame_idx"]})
    src_ids = scope.get("source_ids") or ([scope["source_id"]] if scope.get("source_id") else [])
    for sid in src_ids:
        src = db.row(conn.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone())
        if not src or not src.get("media_path"):
            continue
        cap = cv2.VideoCapture(str(ROOT / src["media_path"]))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        k = int(scope.get("frames_per_source", 8))
        for fi in np.linspace(n * 0.08, n * 0.92, k).astype(int):
            frames.append({"ref": f"{sid}@{fi}", "video": src["media_path"], "frame_idx": int(fi)})
    seen, uniq = set(), []
    for f in frames:
        key = (f["video"], f["frame_idx"])
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    return uniq


def read_frame(video: str, fi: int):
    cap = cv2.VideoCapture(str(ROOT / video))
    for _ in range(fi):
        if not cap.grab():
            break
    ok, img = cap.read()
    cap.release()
    return img if ok else None


def create(conn, workspace_id: str, config: dict) -> str:
    eid = "X-" + uuid.uuid4().hex[:8]
    cfg = {"perturbations": [{"name": "occlusion", "level": 2}], "mitigations": ["none", "enhance"],
           "model": "yolo11n.pt", "seed": 7, **config}
    db.insert(conn, "experiments", {"id": eid, "workspace_id": workspace_id, "created_ts": db.now(),
                                    "model": cfg["model"], "scope": json.dumps(cfg.get("scope", {})),
                                    "config": cfg, "status": "queued"})
    conn.commit()
    return eid


def run(conn, experiment_id: str, progress=None) -> dict:
    exp = db.row(conn.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone())
    cfg = exp["config"]
    ws = db.row(conn.execute("SELECT * FROM workspaces WHERE id=?", (exp["workspace_id"],)).fetchone())
    classes = CLASSES[ws["kind"]]
    frames = frames_for(conn, exp["workspace_id"], cfg.get("scope", {}))
    if not frames:
        conn.execute("UPDATE experiments SET status='failed', error=? WHERE id=?",
                     ("no frames: the selected scope has no video evidence", experiment_id))
        conn.commit()
        return {"status": "failed"}
    conn.execute("UPDATE experiments SET status='running' WHERE id=?", (experiment_id,))
    conn.commit()
    out_dir = OUT / experiment_id
    out_dir.mkdir(parents=True, exist_ok=True)
    rng_master = np.random.default_rng(cfg["seed"])
    weights = cfg["model"]
    total = len(frames) * len(cfg["perturbations"]) * len(cfg["mitigations"])
    done = 0
    agg: dict[tuple, list] = {}
    for fi_n, fr in enumerate(frames):
        img = read_frame(fr["video"], fr["frame_idx"])
        if img is None:
            continue
        ref, ref_ms = detect(weights, img, classes, conf=0.5)
        if not ref:
            continue
        for p in cfg["perturbations"]:
            seed = int(rng_master.integers(1 << 30))
            pimg, pref, hidden = perturb(img, p["name"], p["level"], ref, np.random.default_rng(seed))
            graded = hidden if p["name"] == "occlusion" else list(range(len(pref)))
            if not graded:
                continue
            for mit in cfg["mitigations"]:
                x = enhance(pimg, p["name"]) if mit == "enhance" else pimg
                pred, ms = detect("yolo11s.pt" if mit == "large" else weights, x, classes, conf=0.25,
                                  imgsz=1280 if mit == "hires" else 960, augment=(mit == "tta"))
                kept, new = match(pref, pred)
                kept_g = [i for i in kept if i in graded]
                rid = f"{experiment_id}-{fi_n:02d}-{p['name']}{p['level']}-{mit}"
                orig_path = pert_path = None
                if fi_n < 3:  # visual comparison for the first frames
                    orig_path = out_dir / f"{fi_n:02d}_orig.jpg"
                    if not orig_path.exists():
                        cv2.imwrite(str(orig_path), draw(img, ref, ref, list(range(len(ref))), list(range(len(ref))), []),
                                    [cv2.IMWRITE_JPEG_QUALITY, 85])
                    pert_path = out_dir / f"{fi_n:02d}_{p['name']}{p['level']}_{mit}.jpg"
                    cv2.imwrite(str(pert_path), draw(x, pref, pred, kept, graded, new), [cv2.IMWRITE_JPEG_QUALITY, 85])
                db.insert(conn, "experiment_results", {
                    "id": rid, "experiment_id": experiment_id, "frame_ref": fr["ref"], "perturbation": p["name"],
                    "params": {"level": p["level"], "value": PERTURBATIONS[p["name"]]["levels"][p["level"]]},
                    "mitigation": mit, "n_ref": len(graded), "n_kept": len(kept_g), "n_new": len(new),
                    "latency_ms": round(ms, 1),
                    "details": {"ref_boxes": len(ref), "seed": seed, "video": fr["video"], "frame_idx": fr["frame_idx"],
                                "missed": [i for i in graded if i not in kept]},
                    "original_path": str(orig_path.relative_to(ROOT)) if orig_path else None,
                    "perturbed_path": str(pert_path.relative_to(ROOT)) if pert_path else None})
                a = agg.setdefault((p["name"], p["level"], mit), [0, 0, 0, 0.0, 0])
                a[0] += len(kept_g); a[1] += len(graded); a[2] += len(new); a[3] += ms; a[4] += 1
                done += 1
                if progress:
                    progress(done / total, f"{p['name']} L{p['level']} · {MITIGATIONS[mit]}")
        conn.commit()
    summary = summarize(agg, len(frames))
    conn.execute("UPDATE experiments SET status='done', summary=? WHERE id=?", (json.dumps(summary), experiment_id))
    db.audit(conn, exp["workspace_id"], "system", "incidentlab run", experiment_id,
             f"{len(frames)} frames, {len(agg)} cells")
    conn.commit()
    return summary


def summarize(agg, n_frames) -> dict:
    cells = []
    for (name, level, mit), (k, n, new, ms, runs) in sorted(agg.items()):
        cells.append({"perturbation": name, "label": PERTURBATIONS[name]["label"], "level": level, "mitigation": mit,
                      "mitigation_label": MITIGATIONS[mit], "kept": k, "reference": n,
                      "retention": round(k / n, 4) if n else None, "new_per_frame": round(new / max(runs, 1), 2),
                      "latency_ms": round(ms / max(runs, 1), 1)})
    best = {}
    for c in cells:
        key = (c["perturbation"], c["level"])
        base = next((x for x in cells if (x["perturbation"], x["level"]) == key and x["mitigation"] == "none"), None)
        if c["mitigation"] != "none" and base and c["retention"] is not None and base["retention"] is not None:
            c["delta"] = round(c["retention"] - base["retention"], 4)
            c["new_delta"] = round(c["new_per_frame"] - base["new_per_frame"], 2)
            if c["delta"] > 0 and (key not in best or c["delta"] > best[key]["delta"]):
                best[key] = c
    return {"metric": "detection_retention_rate", "frames": n_frames, "cells": cells,
            "best_mitigation": {f"{k[0]}:{k[1]}": {"mitigation": v["mitigation"], "delta": v["delta"]}
                                for k, v in best.items()},
            "method": "Reference = model detections on the clean frame (conf ≥ 0.5). Retention = share of reference "
                      "boxes re-detected after perturbation (IoU ≥ 0.5, same class, conf ≥ 0.25). Not human ground "
                      "truth. Occlusion graded on hidden boxes only."}


def report_markdown(conn, experiment_id: str) -> str:
    exp = db.row(conn.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone())
    s = exp["summary"] or {}
    lines = [f"# IncidentLab report {experiment_id}", "",
             f"- Workspace: {exp['workspace_id']}  ·  Model: {exp['model']}  ·  Created: {exp['created_ts']}",
             f"- Scope: {exp['scope']}  ·  Frames: {s.get('frames')}", f"- Method: {s.get('method')}", "",
             "| Perturbation | Level | Mitigation | Retained / reference | Retention | Δ vs baseline | New / frame | ms |",
             "|---|---|---|---|---|---|---|---|"]
    for c in s.get("cells", []):
        r = "—" if c["retention"] is None else f"{c['retention']:.0%}"
        d = "" if "delta" not in c else f"{c['delta']:+.0%}"
        lines.append(f"| {c['label']} | {c['level']} | {c['mitigation_label']} | {c['kept']}/{c['reference']} | {r} | {d} "
                     f"| {c['new_per_frame']} | {c['latency_ms']} |")
    return "\n".join(lines) + "\n"
