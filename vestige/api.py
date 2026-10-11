"""VESTIGE HTTP API + static app.

    python -m vestige.api --port 8100      # http://127.0.0.1:8100

Workspace isolation: every read is scoped to a workspace the demo user may access; evidence and
events from another workspace return 403 even when the id is known.
"""
from __future__ import annotations

import argparse
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent, db, incidentlab, memory
from .ingest import process_source

ROOT = db.ROOT
APP = ROOT / "app"
ALLOWED = {"demo": {"campus", "metro", "construction", "road", "case-1219", "bench-road", "bench-station"}}
USER = "demo"

app = FastAPI(title="VESTIGE")


@app.middleware("http")
async def no_stale_frontend(request, call_next):
    """The app is served as plain ES modules; stop browsers mixing cached old modules with new ones."""
    resp = await call_next(request)
    if not request.url.path.startswith("/media/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


def conn():
    return db.connect()


def guard(ws: str):
    if ws not in ALLOWED[USER]:
        raise HTTPException(403, f"no access to workspace {ws}")
    w = db.row(conn().execute("SELECT * FROM workspaces WHERE id=?", (ws,)).fetchone())
    if not w:
        raise HTTPException(404, "workspace not found")
    return w


# ---------- jobs ----------

def job_start(kind: str, target: str, fn) -> str:
    jid = "J-" + uuid.uuid4().hex[:8]
    c = conn()
    db.insert(c, "jobs", {"id": jid, "kind": kind, "target": target, "status": "running", "progress": 0.0,
                          "message": "queued", "created_ts": db.now(), "updated_ts": db.now()})
    c.commit()

    def progress(p, msg):
        cc = db.connect()
        cc.execute("UPDATE jobs SET progress=?, message=?, updated_ts=? WHERE id=?", (round(p, 3), msg, db.now(), jid))
        cc.commit()

    def runner():
        cc = db.connect()
        try:
            fn(cc, progress)
            cc.execute("UPDATE jobs SET status='done', progress=1, updated_ts=? WHERE id=?", (db.now(), jid))
        except Exception as e:  # surfaced to the UI, never swallowed
            cc.execute("UPDATE jobs SET status='failed', message=?, updated_ts=? WHERE id=?", (str(e)[:500], db.now(), jid))
        cc.commit()

    threading.Thread(target=runner, daemon=True).start()
    return jid


@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = db.row(conn().execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())
    if not j:
        raise HTTPException(404)
    return j


# ---------- workspaces & overview ----------

@app.get("/api/workspaces")
def workspaces():
    rows = db.rows(conn().execute("SELECT * FROM workspaces ORDER BY rowid"))
    return [w for w in rows if w["id"] in ALLOWED[USER]]


@app.get("/api/workspaces/{ws}/overview")
def overview(ws: str):
    w = guard(ws)
    c = conn()
    count = lambda t: c.execute(f"SELECT COUNT(*) FROM {t} WHERE workspace_id=?", (ws,)).fetchone()[0]  # noqa: E731
    by_status = {r[0]: r[1] for r in c.execute(
        "SELECT status, COUNT(*) FROM observations WHERE workspace_id=? GROUP BY status", (ws,))}
    # Inferred memories are derived at query time from INFERRED links, not stored as observations.
    by_status["INFERRED"] = c.execute("SELECT COUNT(*) FROM relations WHERE workspace_id=? AND status='INFERRED'",
                                      (ws,)).fetchone()[0]
    return {"workspace": w, "counts": {"sources": count("sources"), "objects": count("objects"),
                                       "tracks": count("tracks"), "observations": count("observations"),
                                       "events": count("events"), "evidence": count("evidence"),
                                       "relations": count("relations")},
            "observations_by_status": by_status,
            "events": memory.search_events(c, ws)[-8:][::-1],
            "objects": memory.search_objects(c, ws),
            "suggestions": SUGGESTIONS.get(w["kind"], [])}


SUGGESTIONS = {
    "campus": ["What happened to my bicycle?", "Where was my bike last seen?", "Show me everything near the underpass gate"],
    "metro": ["What happened before the emergency alert?", "Why was this incident flagged?", "Show me the evidence"],
    "construction": ["What safety alerts happened today?", "Why was the 07:58 alert flagged?",
                     "Show me everything at the pour area"],
    "case": ["How did the 19 December incident unfold?", "Which records support this sequence?",
             "Was the route missing from every camera?"],
    "road": ["Any erratic riding on the bridge?", "Why was the 08:12 alert flagged?", "What happened before it?"],
}


# ---------- memory ----------

@app.get("/api/workspaces/{ws}/objects")
def objects(ws: str, q: str = ""):
    guard(ws)
    return memory.search_objects(conn(), ws, q)


@app.get("/api/objects/{oid}/history")
def object_history(oid: str):
    o = memory.get_object(conn(), oid)
    if not o:
        raise HTTPException(404)
    guard(o["workspace_id"])
    return memory.get_object_history(conn(), oid)


@app.get("/api/workspaces/{ws}/tracks")
def tracks(ws: str, cls: str | None = None):
    guard(ws)
    sql = "SELECT id,source_id,cls,start_ts,end_ts,n_frames,object_id,path FROM tracks WHERE workspace_id=?"
    args = [ws]
    if cls:
        sql += " AND cls=?"
        args.append(cls)
    return db.rows(conn().execute(sql + " ORDER BY start_ts", args))


@app.get("/api/workspaces/{ws}/zones")
def zones(ws: str):
    guard(ws)
    return db.rows(conn().execute("SELECT * FROM zones WHERE workspace_id=?", (ws,)))


@app.get("/api/tracks/{tid}/observations")
def track_observations(tid: str):
    t = db.row(conn().execute("SELECT workspace_id FROM tracks WHERE id=?", (tid,)).fetchone())
    if not t:
        raise HTTPException(404)
    guard(t["workspace_id"])
    return memory.get_track_observations(conn(), tid)


@app.get("/api/workspaces/{ws}/relations")
def relations(ws: str):
    guard(ws)
    return db.rows(conn().execute("SELECT * FROM relations WHERE workspace_id=? ORDER BY created_ts", (ws,)))


@app.get("/api/workspaces/{ws}/events")
def events(ws: str, q: str = ""):
    guard(ws)
    return memory.search_events(conn(), ws, q)


@app.get("/api/events/{eid}/timeline")
def event_timeline(eid: str, before_s: float = 60):
    e = memory.get_event(conn(), eid)
    if not e:
        raise HTTPException(404)
    guard(e["workspace_id"])
    return memory.get_event_timeline(conn(), eid, before_s)


class Review(BaseModel):
    decision: str
    note: str = ""


@app.post("/api/events/{eid}/review")
def review(eid: str, body: Review):
    if body.decision not in ("confirmed", "rejected", "uncertain"):
        raise HTTPException(400, "decision must be confirmed|rejected|uncertain")
    c = conn()
    e = memory.get_event(c, eid)
    if not e:
        raise HTTPException(404)
    guard(e["workspace_id"])
    c.execute("UPDATE events SET status=? WHERE id=?", (body.decision, eid))
    db.audit(c, e["workspace_id"], USER, f"review:{body.decision}", eid, body.note)
    c.commit()
    return memory.get_event(c, eid)


@app.get("/api/evidence/{evid}")
def evidence(evid: str, ws: str | None = None):
    e = memory.get_evidence(conn(), evid)
    if not e:
        raise HTTPException(404)
    guard(e["workspace_id"])
    if ws and ws != e["workspace_id"]:
        raise HTTPException(403, "evidence belongs to another workspace")
    return e


@app.get("/api/workspaces/{ws}/coverage")
def coverage(ws: str):
    guard(ws)
    return memory.get_source_coverage(conn(), ws)


@app.get("/api/workspaces/{ws}/audit")
def audit_log(ws: str, limit: int = 50):
    guard(ws)
    return db.rows(conn().execute("SELECT * FROM audit WHERE workspace_id=? ORDER BY id DESC LIMIT ?", (ws, limit)))


# ---------- investigation ----------

class Question(BaseModel):
    question: str
    event_id: str | None = None
    context: str | None = None  # the site of the answer this question follows up on


@app.post("/api/workspaces/{ws}/ask")
def ask(ws: str, body: Question):
    guard(ws)
    if not body.question.strip():
        raise HTTPException(400, "empty question")
    if body.event_id:
        e = conn().execute("SELECT workspace_id FROM events WHERE id=?", (body.event_id,)).fetchone()
        if not e:
            raise HTTPException(404, "event not found")
        if e[0] != ws:
            raise HTTPException(403, "event belongs to another workspace")
    t = time.perf_counter()
    out = agent.ask(conn(), ws, body.question.strip(), body.event_id)
    out["latency_ms"] = round(1000 * (time.perf_counter() - t), 1)
    return out


# Sites a user sees as one product (benchmarks are engineering-only).
SITES = ["case-1219", "construction", "road", "campus", "metro"]


@app.post("/api/ask")
def ask_anywhere(body: Question):
    """One search box for every site the user may access: the event's own site, or the site the question is about."""
    q = body.question.strip()
    if not q:
        raise HTTPException(400, "empty question")
    c = conn()
    sites = [w for w in SITES if w in ALLOWED[USER]]
    if body.event_id:
        e = c.execute("SELECT workspace_id FROM events WHERE id=?", (body.event_id,)).fetchone()
        if not e:
            raise HTTPException(404, "event not found")
        guard(e[0])
        ws, how = e[0], "event"
    else:
        ws, how = agent.route(c, q, sites, prefer=body.context)
    t = time.perf_counter()
    out = agent.ask(c, ws, q, body.event_id)
    out["latency_ms"] = round(1000 * (time.perf_counter() - t), 1)
    out["routed_by"] = how
    return out


@app.get("/api/alerts")
def alerts():
    """Open alerts across every site, oldest first, with their evidence frame and place."""
    c = conn()
    out = []
    for w in [w for w in SITES if w in ALLOWED[USER]]:
        name = db.row(c.execute("SELECT name FROM workspaces WHERE id=?", (w,)).fetchone())
        for e in memory.search_events(c, w):
            if e["status"] != "open":
                continue
            ev = memory.get_evidence(c, e["evidence_id"]) if e.get("evidence_id") else None
            out.append({**e, "site": name["name"] if name else w, "img": (ev or {}).get("url"),
                        "place": ((ev or {}).get("source") or {}).get("name", "").split(" · ")[-1]})
    return sorted(out, key=lambda e: (SITES.index(e["workspace_id"]), e["ts_start"]))


@app.get("/api/suggestions")
def suggestions():
    c = conn()
    sites = []
    for w in SITES:
        r = db.row(c.execute("SELECT id, name, kind FROM workspaces WHERE id=?", (w,)).fetchone())
        if r:
            r["cameras"] = c.execute("SELECT COUNT(*) FROM sources WHERE workspace_id=? AND kind='camera'", (w,)).fetchone()[0]
            r["example"] = (SUGGESTIONS.get(r["kind"]) or [""])[0]
            sites.append(r)
    return {"examples": ["What happened to my bicycle?", "How did the 19 December incident unfold?",
                         "What safety alerts happened today?"], "sites": sites,
            "by_site": {w: SUGGESTIONS.get(w, []) for w in SITES}}


class CheckIn(BaseModel):
    object_id: str | None = None
    label: str = "my bicycle"
    description: str = ""
    zone_id: str
    lat: float | None = None
    lon: float | None = None


@app.post("/api/workspaces/{ws}/checkin")
def checkin(ws: str, body: CheckIn):
    """A user-recorded parking event. Stored as RECORDED with provenance 'user' — never as an observation."""
    guard(ws)
    c = conn()
    z = db.row(c.execute("SELECT * FROM zones WHERE id=? AND workspace_id=?", (body.zone_id, ws)).fetchone())
    if not z:
        raise HTTPException(400, "unknown zone")
    oid = body.object_id or ("OBJ-" + uuid.uuid4().hex[:6])
    existing = c.execute("SELECT workspace_id FROM objects WHERE id=?", (oid,)).fetchone()
    if existing and existing[0] != ws:
        raise HTTPException(403, "object belongs to another workspace")
    if not existing:
        db.insert(c, "objects", {"id": oid, "workspace_id": ws, "label": body.label, "cls": "bicycle",
                                 "description": body.description, "owner": "me", "provenance": "user",
                                 "created_ts": db.now()})
    obs_id = "O-checkin-" + uuid.uuid4().hex[:6]
    loc = f" ({body.lat:.5f}, {body.lon:.5f})" if body.lat is not None else ""
    db.insert(c, "observations", {"id": obs_id, "workspace_id": ws, "ts": db.now(), "kind": "checkin",
                                  "status": "RECORDED", "object_id": oid, "zone_id": z["id"], "provenance": "user",
                                  "detail": f"Owner check-in at {z['name']}{loc}"})
    db.audit(c, ws, USER, "checkin", oid, z["name"])
    c.commit()
    return {"object_id": oid, "observation_id": obs_id}


# ---------- sources ----------

@app.get("/api/workspaces/{ws}/sources")
def sources(ws: str):
    guard(ws)
    return memory.get_source_coverage(conn(), ws)["sources"]


@app.post("/api/workspaces/{ws}/sources")
async def upload_source(ws: str, name: str = Form(...), zone_id: str = Form(""), start_ts: str = Form(""),
                        authorized: bool = Form(False), file: UploadFile = File(...)):
    guard(ws)
    if not authorized:
        raise HTTPException(400, "confirm you are authorized to process this footage")
    suffix = Path(file.filename or "upload.mp4").suffix.lower()
    if suffix not in (".mp4", ".mov", ".webm", ".mkv", ".avi"):
        raise HTTPException(400, "unsupported video type")
    sid = "UP-" + uuid.uuid4().hex[:6].upper()
    dst = ROOT / "data" / "uploads" / f"{sid}{suffix}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    c = conn()
    db.insert(c, "sources", {"id": sid, "workspace_id": ws, "name": name, "kind": "camera", "zone_id": zone_id or None,
                             "media_path": str(dst.relative_to(ROOT)), "start_ts": start_ts or db.now(),
                             "status": "processing", "provenance": "user", "license": "uploaded by user (authorized)"})
    db.audit(c, ws, USER, "upload", sid, name)
    c.commit()
    src = db.row(c.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone())

    def work(cc, progress):
        try:
            process_source(cc, src, progress)
        except Exception as e:
            cc.execute("UPDATE sources SET status='failed', error=? WHERE id=?", (str(e)[:300], sid))
            cc.commit()
            raise

    return {"source_id": sid, "job_id": job_start("ingest", sid, work)}


# ---------- IncidentLab ----------

@app.get("/api/lab/options")
def lab_options():
    return {"perturbations": incidentlab.PERTURBATIONS, "mitigations": incidentlab.MITIGATIONS,
            "models": sorted(LAB_MODELS)}


LAB_MODELS = {"yolo11n.pt", "yolo11s.pt"}


def lab_scope_guard(c, ws: str, scope: dict):
    """Every evidence / event / source named in the scope must belong to the experiment's workspace."""
    checks = [("evidence", scope.get("evidence_ids") or []), ("events", [scope["event_id"]] if scope.get("event_id") else []),
              ("sources", (scope.get("source_ids") or []) + ([scope["source_id"]] if scope.get("source_id") else []))]
    for table, ids in checks:
        for i in ids:
            r = c.execute(f"SELECT workspace_id FROM {table} WHERE id=?", (i,)).fetchone()
            if not r:
                raise HTTPException(404, f"{table} {i} not found")
            if r[0] != ws:
                raise HTTPException(403, f"{table} {i} belongs to another workspace")


class LabRequest(BaseModel):
    workspace_id: str
    scope: dict
    perturbations: list[dict]
    mitigations: list[str] = ["none"]
    model: str = "yolo11n.pt"


@app.post("/api/lab/experiments")
def lab_create(body: LabRequest):
    guard(body.workspace_id)
    for p in body.perturbations:
        if p.get("name") not in incidentlab.PERTURBATIONS or p.get("level") not in (1, 2, 3):
            raise HTTPException(400, f"bad perturbation {p}")
    if body.model not in LAB_MODELS:
        raise HTTPException(400, f"model must be one of {sorted(LAB_MODELS)}")
    bad = [m for m in body.mitigations if m not in incidentlab.MITIGATIONS]
    if bad:
        raise HTTPException(400, f"unknown mitigation {bad}")
    if "none" not in body.mitigations:
        body.mitigations = ["none", *body.mitigations]  # always keep the baseline
    c = conn()
    lab_scope_guard(c, body.workspace_id, body.scope)
    xid = incidentlab.create(c, body.workspace_id, body.model_dump())
    jid = job_start("incidentlab", xid, lambda cc, progress: incidentlab.run(cc, xid, progress))
    return {"experiment_id": xid, "job_id": jid}


@app.get("/api/lab/experiments")
def lab_list(ws: str | None = None):
    c = conn()
    rows = db.rows(c.execute("SELECT id,workspace_id,created_ts,model,scope,status,summary,config,error FROM experiments "
                             "ORDER BY created_ts DESC"))
    return [r for r in rows if r["workspace_id"] in ALLOWED[USER] and (not ws or r["workspace_id"] == ws)]


@app.get("/api/lab/experiments/{xid}")
def lab_get(xid: str):
    c = conn()
    x = db.row(c.execute("SELECT * FROM experiments WHERE id=?", (xid,)).fetchone())
    if not x:
        raise HTTPException(404)
    guard(x["workspace_id"])
    x["results"] = db.rows(c.execute("SELECT * FROM experiment_results WHERE experiment_id=? ORDER BY id", (xid,)))
    return x


@app.get("/api/lab/experiments/{xid}/report.md", response_class=PlainTextResponse)
def lab_report(xid: str):
    x = db.row(conn().execute("SELECT workspace_id FROM experiments WHERE id=?", (xid,)).fetchone())
    if not x:
        raise HTTPException(404)
    guard(x["workspace_id"])
    return incidentlab.report_markdown(conn(), xid)


# ---------- metrics ----------

@app.get("/api/metrics")
def metrics():
    c = conn()
    t = time.perf_counter()
    agent.ask(c, "campus", "What happened to my bicycle?")
    q_ms = 1000 * (time.perf_counter() - t)
    return {"query_latency_ms": round(q_ms, 1),
            "store": {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for t in ("sources", "tracks", "observations", "events", "evidence", "relations", "experiments")},
            "measured_at": datetime.now().isoformat(timespec="seconds")}


# ---------- static ----------

MEDIA_ROOT = ROOT / "media"
LEGACY_MEDIA = {"metro": "metro", "road": "bench-road"}  # TRACE-era folders → owning workspace


@app.get("/media/{path:path}")
def media(path: str):
    """Media is served only after resolving which workspace owns it (same isolation as /api/evidence)."""
    f = (MEDIA_ROOT / path).resolve()
    if not f.is_relative_to(MEDIA_ROOT.resolve()) or not f.is_file():
        raise HTTPException(404)
    parts = f.relative_to(MEDIA_ROOT.resolve()).parts
    if parts[0] == "vestige" and len(parts) > 2 and parts[1] == "lab":
        x = conn().execute("SELECT workspace_id FROM experiments WHERE id=?", (parts[2],)).fetchone()
        if not x:
            raise HTTPException(404)
        guard(x[0])
    elif parts[0] == "vestige" and len(parts) > 2:
        guard(parts[1])
    elif parts[0] in LEGACY_MEDIA:
        guard(LEGACY_MEDIA[parts[0]])
    else:
        raise HTTPException(404)
    return FileResponse(f)


@app.get("/")
def index():
    """Serve the app with every module URL versioned by its file time, so browsers never mix old and new modules."""
    page = APP / "index.html"
    if page.exists():
        import json as _json
        import re as _re
        from fastapi.responses import HTMLResponse
        html = page.read_text()
        ver = {f"/{p.relative_to(APP).as_posix()}": f"/{p.relative_to(APP).as_posix()}?v={int(p.stat().st_mtime)}"
               for p in APP.rglob("*.js") if "vendor" not in p.parts}
        m = _re.search(r'<script type="importmap">\s*(\{.*?\})\s*</script>', html, _re.S)
        if m:
            imap = _json.loads(m.group(1))
            imap["imports"].update(ver)
            html = html.replace(m.group(1), _json.dumps(imap))
        html = html.replace('src="/app.js"', f'src="{ver.get("/app.js", "/app.js")}"')
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})
    return {"service": "VESTIGE", "try": ["/api/alerts", "POST /api/ask {\"question\": \"What happened to my bicycle?\"}"]}


app.mount("/", StaticFiles(directory=APP, check_dir=False), name="app")


def main():
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
