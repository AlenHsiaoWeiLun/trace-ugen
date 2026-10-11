"""World Memory tools: the only way the investigation agent (or anyone) reads facts.

Each function is deterministic and returns rows straight from the store, so timestamps, places,
frames and relations in an answer can always be traced back to a database row.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import db
from .associate import chain_from

STATUS_ORDER = {"RECORDED": 0, "OBSERVED": 1, "LAST_SEEN": 2, "INFERRED": 3, "UNKNOWN": 4}


def _src_names(conn, ws):
    return {r["id"]: r["name"] for r in conn.execute("SELECT id,name FROM sources WHERE workspace_id=?", (ws,))}


def search_objects(conn, workspace_id: str, query: str = "") -> list[dict]:
    q = f"%{query.lower()}%"
    return db.rows(conn.execute(
        "SELECT * FROM objects WHERE workspace_id=? AND (lower(label) LIKE ? OR lower(cls) LIKE ? OR "
        "lower(description) LIKE ? OR lower(owner) LIKE ?) ORDER BY created_ts", (workspace_id, q, q, q, q)))


def get_object(conn, object_id: str) -> dict | None:
    return db.row(conn.execute("SELECT * FROM objects WHERE id=?", (object_id,)).fetchone())


def get_object_history(conn, object_id: str) -> dict:
    """Recorded check-ins, direct observations of the object's track, inferred cross-camera
    sightings, movement events, and the explicit gap after the last sighting."""
    obj = get_object(conn, object_id)
    if not obj:
        return {"object": None, "entries": [], "gaps": []}
    ws = obj["workspace_id"]
    names = _src_names(conn, ws)
    entries = []
    for o in db.rows(conn.execute("SELECT * FROM observations WHERE object_id=? ORDER BY ts", (object_id,))):
        entries.append({**o, "source": names.get(o["source_id"], o["source_id"]), "via": None})
    base_tracks = [r["id"] for r in conn.execute("SELECT id FROM tracks WHERE object_id=? ORDER BY start_ts",
                                                 (object_id,))]
    linked = []
    for t in base_tracks:
        for r in chain_from(conn, t):
            linked.append((r["b_id"], r))
    for tid in base_tracks:
        for o in db.rows(conn.execute("SELECT * FROM observations WHERE track_id=? ORDER BY ts", (tid,))):
            entries.append({**o, "source": names.get(o["source_id"], o["source_id"]), "via": None})
    for tid, rel in linked:
        for o in db.rows(conn.execute("SELECT * FROM observations WHERE track_id=? ORDER BY ts", (tid,))):
            # A sighting reached through an inferred link is itself inferred.
            entries.append({**o, "status": "INFERRED", "source": names.get(o["source_id"], o["source_id"]),
                            "via": {"relation_id": rel["id"], **rel["basis"]}})
    entries.sort(key=lambda e: (e["ts"], STATUS_ORDER.get(e["status"], 9)))
    # Deduplicate the first/last pair when a track was seen only briefly.
    seen, uniq = set(), []
    for e in entries:
        if e["id"] not in seen:
            seen.add(e["id"])
            uniq.append(e)
    gaps = coverage_after(conn, ws, uniq[-1]["source_id"], uniq[-1]["ts"]) if uniq else []
    events = db.rows(conn.execute(
        "SELECT e.* FROM events e JOIN event_links l ON l.event_id=e.id JOIN observations o ON o.id=l.observation_id "
        "WHERE o.track_id IN (%s) GROUP BY e.id ORDER BY e.ts_end" % ",".join("?" * max(1, len(base_tracks))),
        base_tracks or [""]))
    rejected = db.rows(conn.execute(
        "SELECT * FROM relations WHERE status='REJECTED' AND kind='same_object_candidate' AND a_id IN (%s)"
        % ",".join("?" * max(1, len(base_tracks + [t for t, _ in linked]))),
        (base_tracks + [t for t, _ in linked]) or [""]))
    return {"object": obj, "entries": uniq, "events": events, "gaps": gaps, "rejected_links": rejected}


def coverage_after(conn, workspace_id: str, source_id: str, ts: str) -> list[dict]:
    """Which authorized cameras could have seen the object next, and did they?"""
    names = _src_names(conn, workspace_id)
    nxt = db.rows(conn.execute("SELECT * FROM topology WHERE workspace_id=? AND a_source=?", (workspace_id, source_id)))
    gaps = []
    for g in db.rows(conn.execute("SELECT * FROM gaps WHERE workspace_id=? AND (source_id=? OR source_id IS NULL)",
                                  (workspace_id, source_id))):
        gaps.append({**g, "source": names.get(g["source_id"], "route")})
    if not nxt:
        gaps.append({"id": f"GAP-after-{source_id}", "source_id": None, "source": "route", "ts_start": ts,
                     "ts_end": None, "reason": f"No authorized camera covers the route beyond {names.get(source_id, source_id)}",
                     "provenance": "derived"})
    return gaps


def search_events(conn, workspace_id: str, query: str = "", since: str | None = None, until: str | None = None,
                  kind: str | None = None) -> list[dict]:
    sql = "SELECT * FROM events WHERE workspace_id=?"
    args: list = [workspace_id]
    if query:
        sql += " AND (lower(title) LIKE ? OR lower(kind) LIKE ? OR lower(summary) LIKE ?)"
        args += [f"%{query.lower()}%"] * 3
    if since:
        sql += " AND ts_end >= ?"
        args.append(since)
    if until:
        sql += " AND ts_start <= ?"
        args.append(until)
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    return db.rows(conn.execute(sql + " ORDER BY ts_start", args))


def get_event(conn, event_id: str) -> dict | None:
    return db.row(conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone())


def get_event_timeline(conn, event_id: str, before_s: float = 60.0) -> dict:
    """The event's own observations plus everything else in the workspace in the window before it."""
    ev = get_event(conn, event_id)
    if not ev:
        return {"event": None, "observations": [], "gaps": []}
    ws = ev["workspace_id"]
    names = _src_names(conn, ws)
    t_end = ev["ts_end"]
    t_from = (datetime.fromisoformat(ev["ts_start"]) - timedelta(seconds=before_s)).isoformat(timespec="seconds")
    linked = {r["observation_id"]: r["role"] for r in conn.execute(
        "SELECT * FROM event_links WHERE event_id=?", (event_id,))}
    obs = db.rows(conn.execute("SELECT * FROM observations WHERE workspace_id=? AND ts BETWEEN ? AND ? ORDER BY ts",
                               (ws, t_from, t_end)))
    obs += [o for o in db.rows(conn.execute(
        "SELECT * FROM observations WHERE id IN (%s)" % ",".join("?" * max(1, len(linked))), list(linked) or [""]))
        if o["id"] not in {x["id"] for x in obs}]
    for o in obs:
        o["source"] = names.get(o["source_id"], o["source_id"])
        o["role"] = linked.get(o["id"], "context")
    obs.sort(key=lambda o: o["ts"])
    gaps = db.rows(conn.execute(
        "SELECT * FROM gaps WHERE workspace_id=? AND (ts_end IS NULL OR ts_end >= ?) AND ts_start <= ?",
        (ws, t_from, t_end)))
    for g in gaps:
        g["source"] = names.get(g["source_id"], "route")
    return {"event": ev, "window": [t_from, t_end], "observations": obs, "gaps": gaps}


def get_evidence(conn, evidence_id: str) -> dict | None:
    e = db.row(conn.execute("SELECT * FROM evidence WHERE id=?", (evidence_id,)).fetchone())
    if e:
        s = db.row(conn.execute("SELECT id,name,kind,media_path,recording_available,provenance FROM sources WHERE id=?",
                                (e["source_id"],)).fetchone())
        e["source"] = s
        e["url"] = "/" + e["path"] if e["path"] else None
        proxy = db.ROOT / "media/vestige" / e["workspace_id"] / e["source_id"] / "proxy.mp4"
        clip = db.ROOT / "media/vestige" / e["workspace_id"] / f"{e['id'][2:]}.mp4"
        e["proxy_url"] = "/" + str(proxy.relative_to(db.ROOT)) if proxy.exists() else None
        e["clip_url"] = "/" + str(clip.relative_to(db.ROOT)) if clip.exists() else None
    return e


def get_source_coverage(conn, workspace_id: str) -> dict:
    sources = db.rows(conn.execute("SELECT * FROM sources WHERE workspace_id=? ORDER BY start_ts", (workspace_id,)))
    for s in sources:
        if s["start_ts"] and s["duration_s"]:
            s["end_ts"] = (datetime.fromisoformat(s["start_ts"]) + timedelta(seconds=s["duration_s"])).isoformat(
                timespec="seconds")
    return {"sources": sources,
            "topology": db.rows(conn.execute("SELECT * FROM topology WHERE workspace_id=?", (workspace_id,))),
            "gaps": db.rows(conn.execute("SELECT * FROM gaps WHERE workspace_id=?", (workspace_id,)))}


def get_track_observations(conn, track_id: str) -> list[dict]:
    return db.rows(conn.execute("SELECT * FROM observations WHERE track_id=? ORDER BY ts", (track_id,)))


def get_related_observations(conn, observation_id: str, window_s: float = 30.0) -> list[dict]:
    o = db.row(conn.execute("SELECT * FROM observations WHERE id=?", (observation_id,)).fetchone())
    if not o:
        return []
    t = datetime.fromisoformat(o["ts"])
    a = (t - timedelta(seconds=window_s)).isoformat(timespec="seconds")
    b = (t + timedelta(seconds=window_s)).isoformat(timespec="seconds")
    return db.rows(conn.execute(
        "SELECT * FROM observations WHERE workspace_id=? AND ts BETWEEN ? AND ? AND id<>? ORDER BY ts",
        (o["workspace_id"], a, b, observation_id)))


def search_observations(conn, workspace_id: str, text: str = "", source_ids: list[str] | None = None,
                        zone_ids: list[str] | None = None) -> list[dict]:
    sql = "SELECT * FROM observations WHERE workspace_id=?"
    args: list = [workspace_id]
    if text:
        sql += " AND lower(detail) LIKE ?"
        args.append(f"%{text.lower()}%")
    if source_ids:
        sql += " AND source_id IN (%s)" % ",".join("?" * len(source_ids))
        args += source_ids
    if zone_ids:
        sql += " AND zone_id IN (%s)" % ",".join("?" * len(zone_ids))
        args += zone_ids
    return db.rows(conn.execute(sql + " ORDER BY ts", args))
