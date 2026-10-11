"""End-to-end tests against the demo World Memory (built by `python -m vestige.scenarios`)."""
import re
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import shutil

from vestige import agent, db, memory
from vestige.api import app

client = TestClient(app)
pytestmark = pytest.mark.skipif(not db.DB_PATH.exists(), reason="run python -m vestige.scenarios first")


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Tests write (check-ins, reviews); run them on a copy so the demo memory stays clean."""
    copy = tmp_path / "vestige.db"
    src = db.connect()
    src.execute("PRAGMA wal_checkpoint(FULL)")
    shutil.copy(db.DB_PATH, copy)
    monkeypatch.setattr(db, "DB_PATH", copy)
    yield
    conns = getattr(db._local, "conns", {})
    if str(copy) in conns:
        conns.pop(str(copy)).close()


def test_object_history_states_and_order():
    h = memory.get_object_history(db.connect(), "B-17")
    states = [e["status"] for e in h["entries"]]
    assert states[0] == "RECORDED"
    assert "OBSERVED" in states and "INFERRED" in states
    ts = [e["ts"] for e in h["entries"]]
    assert ts == sorted(ts)
    # inferred entries always carry the basis of the link
    assert all(e["via"] for e in h["entries"] if e["status"] == "INFERRED")
    assert h["gaps"] and "No authorized camera" in h["gaps"][0]["reason"]


def test_inferred_links_respect_travel_window_and_colour():
    c = db.connect()
    for r in db.rows(c.execute("SELECT * FROM relations WHERE kind='same_object_candidate'")):
        b = r["basis"]
        ok = b["window_s"][0] <= b["travel_s"] <= b["window_s"][1] and (b["colour_similarity"] or 0) >= b["threshold"]
        assert (r["status"] == "INFERRED") == ok


def test_answer_citations_resolve_to_stored_evidence():
    c = db.connect()
    a = agent.ask(c, "campus", "What happened to my bicycle?")
    cited = {int(n) for n in re.findall(r"\[E(\d+)\]", a["answer"])}
    assert cited == {x["n"] for x in a["citations"]}
    for x in a["citations"]:
        e = memory.get_evidence(c, x["evidence_id"])
        assert e and e["workspace_id"] == "campus"
    assert "not a confirmed identity" in a["answer"]
    assert "unknown" in a["answer"].lower()


def test_answer_contains_no_unstored_timestamps():
    c = db.connect()
    a = agent.ask(c, "metro", "What happened before the emergency alert?")
    stored = {r[0][11:19] for r in c.execute("SELECT ts FROM observations WHERE workspace_id='metro'")}
    stored |= {r[0][11:19] for r in c.execute("SELECT ts_start FROM events WHERE workspace_id='metro'")}
    stored |= {r[0][11:19] for r in c.execute("SELECT ts_end FROM events WHERE workspace_id='metro'")}
    for t in re.findall(r"\b\d\d:\d\d:\d\d\b", a["answer"]):
        assert t in stored


def test_missing_recording_is_reported_not_filled():
    c = db.connect()
    ev = memory.search_events(c, "metro")[0]
    tl = memory.get_event_timeline(c, ev["id"])
    assert any(g["source_id"] == "CAM-05" for g in tl["gaps"])


def test_workspace_isolation_on_evidence_and_unknown_workspace():
    c = db.connect()
    eid = c.execute("SELECT id FROM evidence WHERE workspace_id='campus' LIMIT 1").fetchone()[0]
    assert client.get(f"/api/evidence/{eid}?ws=metro").status_code == 403
    assert client.get("/api/workspaces/secret/overview").status_code == 403


def test_cross_workspace_ids_are_rejected():
    c = db.connect()
    metro_ev = c.execute("SELECT id FROM events WHERE workspace_id='metro' LIMIT 1").fetchone()[0]
    campus_src = c.execute("SELECT id FROM sources WHERE workspace_id='campus' LIMIT 1").fetchone()[0]
    campus_obj = c.execute("SELECT id FROM objects WHERE workspace_id='campus' LIMIT 1").fetchone()[0]
    zone = c.execute("SELECT id FROM zones WHERE workspace_id='construction' LIMIT 1").fetchone()[0]
    assert client.post("/api/workspaces/construction/ask",
                       json={"question": "Why was this flagged?", "event_id": metro_ev}).status_code == 403
    assert client.post("/api/workspaces/construction/checkin",
                       json={"object_id": campus_obj, "zone_id": zone}).status_code == 403
    lab = {"workspace_id": "construction", "perturbations": [{"name": "blur", "level": 2}]}
    assert client.post("/api/lab/experiments", json={**lab, "scope": {"source_ids": [campus_src]}}).status_code == 403
    assert client.post("/api/lab/experiments", json={**lab, "scope": {"event_id": metro_ev}}).status_code == 403
    assert client.post("/api/lab/experiments", json={**lab, "scope": {}, "model": "../../etc/x.pt"}).status_code == 400
    assert client.post("/api/lab/experiments", json={**lab, "scope": {}, "mitigations": ["rm"]}).status_code == 400


def test_media_is_served_through_workspace_guard(monkeypatch):
    from vestige import api
    c = db.connect()
    path = c.execute("SELECT path FROM evidence WHERE workspace_id='campus' AND path LIKE 'media/%' LIMIT 1").fetchone()[0]
    assert client.get("/" + path).status_code == 200
    assert client.get("/media/../vestige/db.py").status_code == 404
    monkeypatch.setitem(api.ALLOWED, "demo", api.ALLOWED["demo"] - {"campus"})
    assert client.get("/" + path).status_code == 403


def test_ask_endpoint_and_event_scoped_question():
    c = db.connect()
    ev = memory.search_events(c, "construction")[0]
    r = client.post("/api/workspaces/construction/ask", json={"question": "Why was this flagged?", "event_id": ev["id"]})
    assert r.status_code == 200
    body = r.json()
    assert body["subject"]["id"] == ev["id"]
    assert "uncalibrated" in body["answer"] or ev["kind"] != "worker_vehicle_proximity"


def test_checkin_is_recorded_not_observed():
    r = client.post("/api/workspaces/campus/checkin", json={"zone_id": "P5", "label": "test bike"})
    assert r.status_code == 200
    o = db.row(db.connect().execute("SELECT * FROM observations WHERE id=?", (r.json()["observation_id"],)).fetchone())
    assert o["status"] == "RECORDED" and o["provenance"] == "user"


def test_review_is_audited():
    c = db.connect()
    ev = memory.search_events(c, "campus")[0]
    r = client.post(f"/api/events/{ev['id']}/review", json={"decision": "uncertain", "note": "test"})
    assert r.status_code == 200
    a = c.execute("SELECT action FROM audit WHERE target=? ORDER BY id DESC LIMIT 1", (ev["id"],)).fetchone()
    assert a[0] == "review:uncertain"
    client.post(f"/api/events/{ev['id']}/review", json={"decision": "confirmed"})
    assert client.post(f"/api/events/{ev['id']}/review", json={"decision": "guilty"}).status_code == 400


def test_upload_requires_authorization():
    r = client.post("/api/workspaces/campus/sources", data={"name": "x", "authorized": "false"},
                    files={"file": ("a.mp4", b"0000", "video/mp4")})
    assert r.status_code == 400


_uploaded: list[str] = []


def request_cleanup(sid: str):
    _uploaded.append(sid)


@pytest.fixture(autouse=True)
def remove_uploaded_media():
    """The upload test writes real files; remove them so the demo tree stays clean."""
    yield
    while _uploaded:
        sid = _uploaded.pop()
        for f in (db.ROOT / "data" / "uploads").glob(f"{sid}.*"):
            f.unlink()
        shutil.rmtree(db.ROOT / "media" / "vestige" / "construction" / sid, ignore_errors=True)


def test_upload_ingest_ask_flow():
    """Upload video → background detection job → observations persisted → question answered with evidence."""
    import time

    clip = db.ROOT / "data/videos/pexels_28795446.mp4"
    if not clip.exists():
        pytest.skip("demo footage not downloaded")
    with clip.open("rb") as f:
        r = client.post("/api/workspaces/construction/sources",
                        data={"name": "Upload test", "authorized": "true", "start_ts": "2026-10-08T09:00:00"},
                        files={"file": ("site.mp4", f, "video/mp4")})
    assert r.status_code == 200, r.text
    sid, jid = r.json()["source_id"], r.json()["job_id"]
    request_cleanup(sid)
    for _ in range(240):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.5)
    assert j["status"] == "done", j
    c = db.connect()
    n = c.execute("SELECT COUNT(*) FROM observations WHERE source_id=?", (sid,)).fetchone()[0]
    assert n > 0
    ev = c.execute("SELECT id FROM evidence WHERE source_id=? LIMIT 1", (sid,)).fetchone()
    assert ev and client.get(f"/api/evidence/{ev[0]}").status_code == 200
    a = client.post("/api/workspaces/construction/ask", json={"question": "Show me everything near the upload test"}).json()
    assert a["intent"] in ("place", "search")


def test_headline_and_steps_only_cite_stored_evidence():
    import re
    c = db.connect()
    for ws, q in [("campus", "What happened to my bicycle?"), ("campus", "Where was my bike last seen?"),
                  ("metro", "Why was this alert flagged?"), ("construction", "Why was this construction safety event flagged?")]:
        a = agent.ask(c, ws, q)
        ns = {x["n"] for x in a["citations"]}
        assert a["headline"], q
        assert {int(n) for n in re.findall(r"\[E(\d+)\]", a["headline"])} <= ns
        assert all(s["n"] is None or s["n"] in ns for s in a["steps"])
    last = agent.ask(c, "campus", "Where was my bike last seen?")["headline"]
    assert last.startswith("Last seen directly") and "not confirmed" in last and "unknown" in last


def test_one_search_box_routes_to_the_right_site():
    cases = {"What safety alerts happened today?": "construction", "What happened to my bicycle?": "campus",
             "What happened before the platform alarm?": "metro", "Why was the 07:58 alert flagged?": "construction",
             "Any erratic riding on the bridge?": "road"}
    for q, ws in cases.items():
        r = client.post("/api/ask", json={"question": q})
        assert r.status_code == 200 and r.json()["workspace"]["id"] == ws, q
    ev = db.connect().execute("SELECT id FROM events WHERE workspace_id='metro' LIMIT 1").fetchone()[0]
    assert client.post("/api/ask", json={"question": "Why was this flagged?", "event_id": ev}).json()["workspace"]["id"] == "metro"
    alerts = client.get("/api/alerts").json()
    assert alerts and all(a["status"] == "open" for a in alerts) and alerts[0]["workspace_id"] == "construction"


def test_road_alert_does_not_guess_the_cause():
    a = client.post("/api/ask", json={"question": "Why was the 08:12 alert flagged?"}).json()
    assert a["workspace"]["id"] == "road" and "not inferred" in a["headline"]
    assert not any(w in a["headline"].lower() for w in ("drunk", "intoxicated"))
