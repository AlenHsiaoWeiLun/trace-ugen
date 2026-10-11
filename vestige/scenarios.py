"""Reproducible demo workspaces built from openly licensed footage.

    python -m vestige.scenarios          # rebuild data/vestige.db from scratch (runs real perception)

Staged inputs are labelled `provenance='staged'`: the owner's parking check-in, the scripted
alarm/radio of the metro replay and the "recording unavailable" window. Everything derived from
video is produced by the perception pipeline at build time.
"""
from __future__ import annotations

import json
import shutil
import sys
import time

from . import db
from .associate import associate_workspace
from .ingest import process_source

PEXELS = "Pexels License"

WORKSPACES = [
    {"id": "campus", "name": "Campus", "kind": "campus",
     "description": "Bicycle parking and paths — stitched from public footage (Pexels)."},
    {"id": "metro", "name": "Metro station", "kind": "metro",
     "description": "Virtual station replay from the TRACE engine (stock clips, scripted alarm and radio)."},
    {"id": "construction", "name": "Construction site", "kind": "construction",
     "description": "Construction-site footage (Pexels). Not a WanZe site."},
    {"id": "road", "name": "Taipei Bridge road", "kind": "road",
     "description": "Taipei Bridge approach — TRACE road replay on public footage (Wikimedia Commons, Pexels)."},
]

CAMPUS = {
    "zones": [
        {"id": "P3", "name": "Parking P3", "kind": "parking", "x": 0.06, "y": 0.18, "w": 0.26, "h": 0.30},
        {"id": "P5", "name": "Parking P5", "kind": "parking", "x": 0.06, "y": 0.60, "w": 0.26, "h": 0.26},
        {"id": "W1", "name": "Riverside path", "kind": "path", "x": 0.40, "y": 0.34, "w": 0.24, "h": 0.30},
        {"id": "G2", "name": "Underpass gate", "kind": "exit", "x": 0.72, "y": 0.34, "w": 0.22, "h": 0.30},
    ],
    "sources": [
        {"id": "CAM-P3", "name": "CAM-P3 · Parking P3", "zone_id": "P3", "media": "pexels_4649964.mp4",
         "start": "2026-10-07T13:40:50", "map": (0.19, 0.33)},
        {"id": "CAM-P5", "name": "CAM-P5 · Parking P5", "zone_id": "P5", "media": "pexels_8405570.mp4",
         "start": "2026-10-07T13:39:20", "map": (0.19, 0.73)},
        {"id": "CAM-W1", "name": "CAM-W1 · Riverside path", "zone_id": "W1", "media": "pexels_4649966.mp4",
         "start": "2026-10-07T13:41:40", "map": (0.52, 0.49)},
        {"id": "CAM-G2", "name": "CAM-G2 · Underpass gate", "zone_id": "G2", "media": "pexels_4650158.mp4",
         "start": "2026-10-07T13:43:05", "map": (0.83, 0.49)},
    ],
    "topology": [("CAM-P3", "CAM-W1", 15, 240), ("CAM-P5", "CAM-W1", 15, 240), ("CAM-W1", "CAM-G2", 15, 240)],
}

CONSTRUCTION = {
    "zones": [
        {"id": "S1", "name": "Pour area", "kind": "hazard", "x": 0.08, "y": 0.2, "w": 0.4, "h": 0.6},
        {"id": "S2", "name": "Haul road", "kind": "hazard", "x": 0.54, "y": 0.2, "w": 0.4, "h": 0.6},
    ],
    "sources": [
        {"id": "CAM-S1", "name": "CAM-S1 · Pour area", "zone_id": "S1", "media": "pexels_32268405.mp4",
         "start": "2026-10-08T07:58:10", "map": (0.28, 0.5)},
        {"id": "CAM-S2", "name": "CAM-S2 · Haul road", "zone_id": "S2", "media": "pexels_28795446.mp4",
         "start": "2026-10-08T08:03:40", "map": (0.74, 0.5)},
    ],
    "topology": [],
}


def _workspace(conn, ws):
    db.insert(conn, "workspaces", {**ws, "retention_days": 30, "created_ts": db.now()})


def _cameras(conn, ws_id, spec):
    for z in spec["zones"]:
        db.insert(conn, "zones", {**z, "workspace_id": ws_id})
    for s in spec["sources"]:
        db.insert(conn, "sources", {
            "id": s["id"], "workspace_id": ws_id, "name": s["name"], "kind": "camera", "zone_id": s["zone_id"],
            "media_path": f"data/videos/{s['media']}", "start_ts": s["start"], "status": "registered",
            "provenance": "public-footage", "license": PEXELS, "map_x": s["map"][0], "map_y": s["map"][1],
            "notes": f"Pexels clip {s['media'].split('_')[1].split('.')[0]}; timestamps assigned for the demo"})
    for a, b, lo, hi in spec["topology"]:
        db.insert(conn, "topology", {"workspace_id": ws_id, "a_source": a, "b_source": b,
                                     "min_travel_s": lo, "max_travel_s": hi})


def build_campus(conn, log=print):
    _cameras(conn, "campus", CAMPUS)
    for s in CAMPUS["sources"]:
        src = db.row(conn.execute("SELECT * FROM sources WHERE id=?", (s["id"],)).fetchone())
        t = time.time()
        stats = process_source(conn, src)
        log(f"  {s['id']}: {stats} ({time.time() - t:.0f}s)")
    rels = associate_workspace(conn, "campus")
    log(f"  associations: {[(r['id'], r['status'], r['colour_similarity']) for r in rels]}")
    # The owner's bicycle: registered by a (staged) check-in, then bound to the bicycle track seen at
    # the recorded parking position on CAM-P3.
    # All bicycle tracklets of the parking-position move event on CAM-P3 belong to the owner's bike.
    ev = db.row(conn.execute("SELECT * FROM events WHERE id LIKE 'EV-CAM-P3-move-%' ORDER BY ts_end LIMIT 1").fetchone())
    tids = [f"T-CAM-P3-{t}" for t in (ev["metrics"]["tracklets"] if ev else [])]
    bike = db.row(conn.execute("SELECT * FROM tracks WHERE id=?", (tids[0],)).fetchone()) if tids else None
    db.insert(conn, "objects", {
        "id": "B-17", "workspace_id": "campus", "label": "B-17 · my bicycle", "cls": "bicycle",
        "description": "red road bike", "owner": "me", "appearance": bike["appearance"] if bike else None,
        "provenance": "user", "created_ts": "2026-10-07T08:52:00"})
    db.insert(conn, "observations", {
        "id": "O-B17-checkin", "workspace_id": "campus", "source_id": "CAM-P3", "ts": "2026-10-07T08:52:00",
        "kind": "checkin", "status": "RECORDED", "object_id": "B-17", "zone_id": "P3", "provenance": "staged",
        "detail": "Owner check-in: parked at Parking P3 (user-recorded, staged for the demo)"})
    for t in tids:
        conn.execute("UPDATE tracks SET object_id='B-17' WHERE id=?", (t,))
        db.insert(conn, "relations", {
            "id": f"R-B17-bind-{t}", "workspace_id": "campus", "kind": "object_binding", "a_id": "B-17",
            "b_id": t, "status": "OBSERVED", "created_ts": db.now(),
            "basis": {"note": "bicycle at the owner's recorded parking position on CAM-P3"
                              + ("; tracker split it into tracklets" if len(tids) > 1 else "")}})
    conn.commit()


def build_construction(conn, log=print):
    _cameras(conn, "construction", CONSTRUCTION)
    for s in CONSTRUCTION["sources"]:
        src = db.row(conn.execute("SELECT * FROM sources WHERE id=?", (s["id"],)).fetchone())
        t = time.time()
        stats = process_source(conn, src)
        log(f"  {s['id']}: {stats} ({time.time() - t:.0f}s)")


def import_metro(conn, log=print):
    """Bring the TRACE engine's fused metro run into World Memory."""
    run = json.loads((db.ROOT / "data/run_metro.json").read_text())
    for z in run["site"]["zones"]:
        db.insert(conn, "zones", {"id": f"M-{z['id']}", "workspace_id": "metro", "name": z["name"], "kind": "area",
                                  "x": z["x"], "y": z["y"], "w": z["w"], "h": z["h"]})
    src_kind = {"CAM": "camera", "DET": "detector", "RAD": "radio"}
    seen = {}
    for s in run["signals"]:
        seen.setdefault(s["sensor"], s)
    for sensor, s in seen.items():
        z = next((z for z in run["site"]["zones"] if z["id"] == s["zone"]), None)
        db.insert(conn, "sources", {
            "id": sensor, "workspace_id": "metro", "name": f"{sensor} · zone {s['zone']}",
            "kind": src_kind[sensor[:3]], "zone_id": f"M-{s['zone']}", "start_ts": run["incidents"][0]["start_ts"],
            "status": "processed", "provenance": "public-footage" if sensor.startswith("CAM") else "staged",
            "license": PEXELS if sensor.startswith("CAM") else "scripted input",
            "map_x": (z["x"] + z["w"] / 2) if z else 0.5, "map_y": (z["y"] + z["h"] / 2) if z else 0.5,
            "recording_available": 0 if sensor == "CAM-05" else 1,
            "notes": "TRACE replay" + ("; recording host unavailable after 17:36:10 (staged)" if sensor == "CAM-05" else "")})
    status_of = {"camera": "OBSERVED", "detector": "RECORDED", "radio": "RECORDED"}
    for inc in run["incidents"]:
        ev_id = f"EV-{inc['id']}"
        kf = inc.get("keyframe")
        eid = None
        if kf:
            eid = f"E-{inc['id']}"
            dst = db.ROOT / "media/vestige/metro" / f"{inc['id']}.jpg"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(db.ROOT / kf.lstrip("/"), dst)
            db.insert(conn, "evidence", {
                "id": eid, "workspace_id": "metro", "source_id": inc["sensors"][0] if inc["sensors"][0].startswith("CAM")
                else next((x for x in inc["sensors"] if x.startswith("CAM")), inc["sensors"][0]),
                "kind": "frame", "path": str(dst.relative_to(db.ROOT)), "ts": inc["start_ts"], "provenance": "public-footage",
                "caption": inc["title"], "created_ts": db.now()})
            if inc.get("clip"):
                clip = db.ROOT / "media/vestige/metro" / f"{inc['id']}.mp4"
                shutil.copy(db.ROOT / inc["clip"].lstrip("/"), clip)
        db.insert(conn, "events", {
            "id": ev_id, "workspace_id": "metro", "kind": "fused_incident", "title": inc["title"],
            "ts_start": inc["start_ts"], "ts_end": inc["end_ts"], "priority": inc["priority"],
            "summary": inc["summary"], "provenance": "derived", "model": "TRACE fusion + Qwen2-VL-2B",
            "metrics": {"score": inc["score"], "n_signals": inc["n_signals"], "vlm": inc.get("vlm"),
                        "sop": inc.get("sop")}, "evidence_id": eid, "zone_id": f"M-{inc['zones'][0]}"})
        for s in inc["signals"]:
            kind = src_kind[s["sensor"][:3]]
            oid = f"O-{s['id']}"
            seid = None
            if s.get("thumb"):
                seid = f"E-{s['id']}"
                dst = db.ROOT / "media/vestige/metro" / f"{s['id']}.jpg"
                shutil.copy(db.ROOT / s["thumb"].lstrip("/"), dst)
                db.insert(conn, "evidence", {"id": seid, "workspace_id": "metro", "source_id": s["sensor"],
                                             "kind": "frame", "path": str(dst.relative_to(db.ROOT)), "ts": s["ts"],
                                             "provenance": "public-footage", "caption": s["detail"],
                                             "created_ts": db.now()})
            elif kind != "camera":
                seid = f"E-{s['id']}"
                db.insert(conn, "evidence", {"id": seid, "workspace_id": "metro", "source_id": s["sensor"],
                                             "kind": "transcript" if kind == "radio" else "record", "ts": s["ts"],
                                             "provenance": "staged", "caption": s.get("transcript") or s["detail"],
                                             "created_ts": db.now()})
            db.insert(conn, "observations", {
                "id": oid, "workspace_id": "metro", "source_id": s["sensor"], "ts": s["ts"], "kind": s["kind"],
                "status": status_of[kind], "zone_id": f"M-{s['zone']}", "evidence_id": seid,
                "model": "TRACE rules" if kind == "camera" else ("whisper tiny.en" if kind == "radio" else "alarm I/O"),
                "confidence": s["confidence"], "provenance": "staged" if kind != "camera" else "public-footage",
                "detail": (f'"{s["transcript"]}"' if s.get("transcript") else s["detail"])})
            conn.execute("INSERT OR REPLACE INTO event_links VALUES (?,?,?)", (ev_id, oid, "signal"))
    db.insert(conn, "gaps", {"id": "GAP-CAM05", "workspace_id": "metro", "source_id": "CAM-05",
                             "ts_start": "2026-10-10T17:36:10", "ts_end": "2026-10-10T17:40:00",
                             "reason": "Recording host unavailable — live view only, no replay (staged to mirror a "
                                       "real failure mode)", "provenance": "staged"})
    conn.commit()
    log(f"  metro: {len(run['incidents'])} incidents, {len(run['signals'])} signals imported")


def import_road(conn, log=print):
    """Bring the TRACE road replay (erratic-riding detection) into World Memory as its own site."""
    run = json.loads((db.ROOT / "data/run_road.json").read_text())
    out = db.ROOT / "media/vestige/road"
    out.mkdir(parents=True, exist_ok=True)
    for z in run["site"]["zones"]:
        db.insert(conn, "zones", {"id": f"R-{z['id']}", "workspace_id": "road", "name": z["name"], "kind": "lane",
                                  "x": z["x"], "y": z["y"], "w": z["w"], "h": z["h"]})
        for cam in z.get("cameras", []):
            db.insert(conn, "sources", {
                "id": cam, "workspace_id": "road", "name": f"{cam} · {z['name']}", "kind": "camera",
                "zone_id": f"R-{z['id']}", "start_ts": run["incidents"][0]["start_ts"] if run["incidents"] else db.now(),
                "status": "processed", "provenance": "public-footage",
                "license": PEXELS if cam == "CAM-R3" else "CC BY-SA 4.0 (Tze Chiang Hao, Wikimedia)",
                "map_x": z["x"] + z["w"] / 2, "map_y": z["y"] + z["h"] / 2, "recording_available": 1,
                "notes": "TRACE road replay"})
    for inc in run["incidents"]:
        eid = None
        if inc.get("keyframe"):
            eid = f"E-{inc['id']}"
            dst = out / f"{inc['id']}.jpg"
            shutil.copy(db.ROOT / inc["keyframe"].lstrip("/"), dst)
            if inc.get("clip"):
                shutil.copy(db.ROOT / inc["clip"].lstrip("/"), out / f"{inc['id']}.mp4")
            db.insert(conn, "evidence", {"id": eid, "workspace_id": "road", "source_id": inc["sensors"][0], "kind": "frame",
                                         "path": str(dst.relative_to(db.ROOT)), "ts": inc["start_ts"],
                                         "provenance": "public-footage", "caption": inc["title"], "created_ts": db.now()})
        sig = inc["signals"][0] if inc["signals"] else {}
        f = sig.get("features") or {}
        db.insert(conn, "events", {
            "id": f"EV-{inc['id']}", "workspace_id": "road", "kind": "lateral_weaving", "title": "Rider weaving across the lane",
            "ts_start": inc["start_ts"], "ts_end": inc["end_ts"], "priority": inc["priority"], "summary": inc["summary"],
            "provenance": "derived", "model": "YOLO11n + ByteTrack + TRACE trajectory rules",
            "metrics": {"swings": int(f.get("swings", 0)), "lateral_std_widths": round(f.get("lateral_std_w", 0), 2),
                        "duration_s": round(f.get("duration_s", 0), 1), "score": inc["score"], "vlm": inc.get("vlm"),
                        "sop": inc.get("sop")},
            "evidence_id": eid, "zone_id": f"R-{inc['zones'][0]}"})
        for sg in inc["signals"]:
            seid = None
            if sg.get("thumb"):
                seid = f"E-{sg['id']}"
                dst = out / f"{sg['id']}.jpg"
                shutil.copy(db.ROOT / sg["thumb"].lstrip("/"), dst)
                db.insert(conn, "evidence", {"id": seid, "workspace_id": "road", "source_id": sg["sensor"], "kind": "frame",
                                             "path": str(dst.relative_to(db.ROOT)), "ts": sg["ts"],
                                             "provenance": "public-footage", "caption": sg["detail"], "created_ts": db.now()})
            oid = f"O-{sg['id']}"
            db.insert(conn, "observations", {
                "id": oid, "workspace_id": "road", "source_id": sg["sensor"], "ts": sg["ts"], "kind": sg["kind"],
                "status": "OBSERVED", "zone_id": f"R-{sg['zone']}", "evidence_id": seid, "model": "TRACE trajectory rules",
                "confidence": sg["confidence"], "provenance": "public-footage", "detail": sg["detail"]})
            conn.execute("INSERT OR REPLACE INTO event_links VALUES (?,?,?)", (f"EV-{inc['id']}", oid, "trigger"))
    conn.commit()
    log(f"  road: {len(run['incidents'])} incidents imported")


def import_case(conn, log=print):
    """The 19 Dec 2025 Taipei Main / Zhongshan case: a retrospective built only from published records.

    Every fact is an official record (or a labelled secondary report) with its source, page and a short quote.
    No original CCTV was obtained, so nothing is stored as a camera observation.
    """
    case = json.loads((db.ROOT / "data/case_1219.json").read_text())
    w = case["workspace"]
    _workspace(conn, w)
    src = {s["id"]: s for s in case["sources"]}
    for s in case["sources"]:
        db.insert(conn, "sources", {"id": f"DOC-{s['id']}", "workspace_id": w["id"], "name": f"{s['id']} · {s['publisher']}",
                                    "kind": "document", "status": "processed", "recording_available": 0,
                                    "provenance": "news-report" if s["kind"] == "news_report" else "official-record",
                                    "license": "public document, short quotation", "notes": s["title"]})
    for p in case["places"]:
        db.insert(conn, "zones", {"id": f"C-{p['id']}", "workspace_id": w["id"], "name": p["name"], "kind": "place",
                                  "x": p["x"], "y": p["y"], "w": 0.08, "h": 0.08})

    def evidence(eid, item, ts):
        s = src[item["source"]]
        db.insert(conn, "evidence", {
            "id": eid, "workspace_id": w["id"], "source_id": f"DOC-{s['id']}", "kind": "document", "ts": ts,
            "provenance": "news-report" if s["kind"] == "news_report" else "official-record", "caption": item["text"],
            "created_ts": db.now(),
            "meta": {"source": s["id"], "title": s["title"], "title_zh": s["title_zh"], "publisher": s["publisher"],
                     "date": s["date"], "date_note": s["date_note"], "locator": item["locator"], "url": s["url"],
                     "excerpt": item["excerpt"], "record_type": s["kind"], "precision": item.get("precision", "n/a")}})

    for t in case["timeline"]:
        eid = f"E-1219-{t['id']}"
        evidence(eid, t, t["ts"])
        db.insert(conn, "observations", {
            "id": f"O-1219-{t['id']}", "workspace_id": w["id"], "source_id": f"DOC-{t['source']}", "ts": t["ts"],
            "kind": src[t["source"]]["kind"], "status": "OFFICIAL", "zone_id": f"C-{t['place']}", "evidence_id": eid,
            "model": "published record", "provenance": "official-record", "detail": t["text"]})
    for c in case["coverage"]:
        evidence(f"E-1219-{c['id']}", c, None)
    db.insert(conn, "gaps", {"id": "GAP-1219-CCTV", "workspace_id": w["id"], "source_id": None,
                             "ts_start": "2025-12-19T16:58:00", "ts_end": "2025-12-19T18:51:00",
                             "reason": "Original CCTV was not provided to VESTIGE; this case makes no visual claims",
                             "provenance": "derived"})
    conn.commit()
    log(f"  case-1219: {len(case['timeline'])} official records, {len(case['coverage'])} coverage statements")


BENCHMARK = [  # public clips used only as IncidentLab test sets, not as scenario evidence
    ("BENCH-ROAD-1", "Taipei Bridge scooters 06", "bridge_06.webm", "CC BY-SA 4.0 (Tze Chiang Hao, Wikimedia)"),
    ("BENCH-ROAD-2", "Taipei Bridge scooters 07", "bridge_07.webm", "CC BY-SA 4.0 (Tze Chiang Hao, Wikimedia)"),
    ("BENCH-ROAD-3", "Taiwan street scooters", "pexels_4740223.mp4", PEXELS),
    ("BENCH-STATION-1", "Station platform crowd", "pexels_37737804.mp4", PEXELS),
    ("BENCH-STATION-2", "Station concourse crowd", "pexels_34647618.mp4", PEXELS),
]


def build_benchmark(conn):
    db.insert(conn, "workspaces", {"id": "bench-road", "name": "Benchmark · road", "kind": "road",
                                   "description": "Public clips for IncidentLab only", "created_ts": db.now()})
    db.insert(conn, "workspaces", {"id": "bench-station", "name": "Benchmark · station", "kind": "metro",
                                   "description": "Public clips for IncidentLab only", "created_ts": db.now()})
    for sid, name, media, lic in BENCHMARK:
        db.insert(conn, "sources", {"id": sid, "workspace_id": "bench-road" if "ROAD" in sid else "bench-station",
                                    "name": name, "kind": "camera", "media_path": f"data/videos/{media}",
                                    "status": "benchmark", "provenance": "public-footage", "license": lic,
                                    "notes": "IncidentLab test set"})
    conn.commit()


def preflight():
    """Check all inputs before resetting an existing memory database."""
    videos = {s["media"] for spec in (CAMPUS, CONSTRUCTION) for s in spec["sources"]}
    videos.update(media for _, _, media, _ in BENCHMARK)
    replays = [db.ROOT / "data/run_metro.json", db.ROOT / "data/run_road.json"]
    if not (db.ROOT / "data/case_1219.json").exists():
        raise FileNotFoundError("Demo inputs missing: data/case_1219.json. Restore tracked case data with git.")
    needed = [db.ROOT / "data/videos" / name for name in sorted(videos)] + replays
    for replay in [r for r in replays if r.exists()]:
        run = json.loads(replay.read_text())
        for inc in run["incidents"]:
            needed.extend(db.ROOT / inc[k].lstrip("/") for k in ("keyframe", "clip") if inc.get(k))
            needed.extend(db.ROOT / s["thumb"].lstrip("/") for s in inc["signals"] if s.get("thumb"))
    missing = [str(p.relative_to(db.ROOT)) for p in needed if not p.is_file() or not p.stat().st_size]
    if missing:
        raise FileNotFoundError("Demo inputs missing: " + ", ".join(missing)
                                + ". Run bash scripts/download_media.sh for footage; restore tracked replay assets with git.")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required to create playable evidence clips. Install it and add it to PATH.")


def build(log=print):
    preflight()
    conn = db.reset()
    for ws in WORKSPACES:
        _workspace(conn, ws)
    log("campus"); build_campus(conn, log)
    log("construction"); build_construction(conn, log)
    log("metro"); import_metro(conn, log)
    log("road"); import_road(conn, log)
    log("case"); import_case(conn, log)
    build_benchmark(conn)
    db.audit(conn, None, "system", "demo build", "all workspaces")
    conn.commit()
    return conn


if __name__ == "__main__":
    build()
    sys.exit(0)
