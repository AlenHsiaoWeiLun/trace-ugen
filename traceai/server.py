"""Operator console backend.

Serves incidents produced by `scripts/run_pipeline.py` (data/run_<scenario>.json). With
`--replay` incidents are released on the wall clock in the order they were created, so a
recorded run plays back like a live feed.

    python -m traceai.server --replay --speed 1.0
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
DATA, MEDIA, WEB = ROOT / "data", ROOT / "media", ROOT / "web"


class Question(BaseModel):
    question: str


class Review(BaseModel):
    decision: str
    note: str = ""
    reviewer: str = "operator-1"


class Store:
    def __init__(self, replay: bool = False, speed: float = 1.0, lead_s: float = 3.0, demo: bool = False):
        self.runs: dict[str, dict] = {}
        for p in sorted(DATA.glob("run_*.json")):
            run = json.loads(p.read_text())
            self.runs[run["scenario"]] = run
        self.incidents = {i["id"]: i for run in self.runs.values() for i in run["incidents"]}
        self.replay, self.speed, self.lead_s = replay, speed, lead_s
        self.t_start = time.time()
        # Demo mode: incidents appear only when released via /api/demo/release (for recordings).
        self.demo, self.released = demo, set()

    def _released(self, inc: dict) -> bool:
        if self.demo:
            return inc["id"] in self.released
        if not self.replay:
            return True
        return (time.time() - self.t_start) * self.speed + self.lead_s >= inc.get("release_s", 0)

    def visible(self) -> list[dict]:
        return [i for i in self.incidents.values() if self._released(i)]


app = FastAPI(title="TRACE console")
store: Store | None = None


def get_store() -> Store:
    global store
    if store is None:
        store = Store()
    return store


def _summary(i: dict) -> dict:
    keys = ("id", "scenario", "title", "status", "priority", "score", "start_ts", "end_ts", "zones", "sensors",
            "n_signals", "keyframe")
    return {k: i.get(k) for k in keys}


@app.get("/api/incidents")
def list_incidents(scenario: str | None = None, status: str | None = None):
    items = [i for i in get_store().visible()
             if (not scenario or i["scenario"] == scenario) and (not status or i["status"] == status)]
    items.sort(key=lambda i: i.get("release_s", 0), reverse=True)
    return [_summary(i) for i in items]


@app.get("/api/incidents/{iid}")
def get_incident(iid: str):
    i = get_store().incidents.get(iid)
    if not i or not get_store()._released(i):
        raise HTTPException(404)
    return i


@app.post("/api/incidents/{iid}/review")
def review(iid: str, body: Review):
    if body.decision not in ("confirmed", "dismissed", "escalated"):
        raise HTTPException(400, "decision must be confirmed|dismissed|escalated")
    i = get_store().incidents.get(iid)
    if not i:
        raise HTTPException(404)
    now = datetime.now().isoformat(timespec="seconds")
    i["status"] = body.decision
    i["review"] = {"decision": body.decision, "reviewer": body.reviewer, "note": body.note, "ts": now}
    i.setdefault("audit", []).append({"ts": now, "actor": body.reviewer,
                                      "action": f"{body.decision}" + (f": {body.note}" if body.note else "")})
    DATA.mkdir(exist_ok=True)
    (DATA / "reviews.jsonl").open("a").write(json.dumps({"id": iid, **i["review"]}) + "\n")
    return i


@app.get("/api/stats")
def stats():
    s = get_store()
    vis = s.visible()
    n_sig = sum(i["n_signals"] for i in vis)
    raw = sum(r.get("raw_signals", 0) for r in s.runs.values()) if not s.replay else n_sig
    by_status = {k: sum(1 for i in vis if i["status"] == k) for k in ("pending", "confirmed", "dismissed", "escalated")}
    pipeline = next(iter(s.runs.values()), {}).get("pipeline", {})
    return {
        "signals_total": max(raw, n_sig),
        "incidents_total": len(vis),
        "alert_reduction": round(1 - len(vis) / max(n_sig, 1), 3),
        "by_status": by_status,
        "by_scenario": {k: sum(1 for i in vis if i["scenario"] == k) for k in s.runs},
        "pipeline": pipeline,
    }


_asker = None


@app.post("/api/ask")
def ask(body: Question):
    global _asker
    if _asker is None:
        from .ask import Asker

        llm = None
        if os.environ.get("TRACE_LLM", "1") != "0":
            try:
                from .summarize import VLMCaptioner

                llm = VLMCaptioner()
            except Exception as e:  # model not downloaded / no memory: fall back to retrieval
                print(f"[ask] LLM unavailable ({e}); using keyword retriever")
        _asker = Asker(llm)
    s = get_store()
    zone_names = {z["id"]: z["name"] for run in s.runs.values() for z in run["site"]["zones"]}
    return _asker.ask(body.question, s.visible(), zone_names)


@app.post("/api/demo/release/{iid}")
def demo_release(iid: str):
    s = get_store()
    if not s.demo or iid not in s.incidents:
        raise HTTPException(404)
    s.released.add(iid)
    return {"released": sorted(s.released)}


@app.post("/api/demo/reset")
def demo_reset():
    s = get_store()
    if not s.demo:
        raise HTTPException(404)
    s.released.clear()
    for i in s.incidents.values():
        i["status"] = "pending"
        i["review"] = {"decision": None, "reviewer": None, "note": None, "ts": None}
        i["audit"] = [a for a in i.get("audit", []) if a.get("actor") in ("system", "vlm")]
    return {"ok": True}


@app.get("/api/site")
def site(scenario: str = "metro"):
    run = get_store().runs.get(scenario)
    if not run:
        raise HTTPException(404)
    return run["site"]


app.mount("/media", StaticFiles(directory=MEDIA, check_dir=False), name="media")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--replay", action="store_true", help="release incidents on the wall clock")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--demo", action="store_true", help="incidents appear only via /api/demo/release")
    a = ap.parse_args()
    global store
    store = Store(replay=a.replay, speed=a.speed, demo=a.demo)
    MEDIA.mkdir(exist_ok=True)
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
