"""Cross-camera association without identity recognition.

Two tracks on different cameras are linked as the *same object candidate* only if all three
independent constraints hold: the cameras are adjacent in the site topology, the time between
leaving one view and entering the next fits the configured travel window, and their colour
signatures are similar. A link is always INFERRED (never OBSERVED); failed checks are stored as
REJECTED with the reason, so the investigator sees why something was *not* linked.
"""
from __future__ import annotations

from datetime import datetime

from . import db
from .ingest import colour_name, similarity

SIM_THRESHOLD = 0.55


def associate_workspace(conn, workspace_id: str, classes=("bicycle",)) -> list[dict]:
    out = []
    edges = db.rows(conn.execute("SELECT * FROM topology WHERE workspace_id=?", (workspace_id,)))
    for e in edges:
        a_tracks = db.rows(conn.execute(
            f"SELECT * FROM tracks WHERE source_id=? AND cls IN ({','.join('?' * len(classes))})",
            (e["a_source"], *classes)))
        b_tracks = db.rows(conn.execute(
            f"SELECT * FROM tracks WHERE source_id=? AND cls IN ({','.join('?' * len(classes))})",
            (e["b_source"], *classes)))
        for a in a_tracks:
            for b in b_tracks:
                if a["cls"] != b["cls"]:
                    continue
                gap_s = (datetime.fromisoformat(b["start_ts"]) - datetime.fromisoformat(a["end_ts"])).total_seconds()
                sim = similarity(a["appearance"], b["appearance"])
                time_ok = e["min_travel_s"] <= gap_s <= e["max_travel_s"]
                sim_ok = sim is not None and sim >= SIM_THRESHOLD
                status = "INFERRED" if (time_ok and sim_ok) else "REJECTED"
                reasons = []
                if not time_ok:
                    reasons.append(f"travel time {gap_s:.0f} s outside {e['min_travel_s']:.0f}–{e['max_travel_s']:.0f} s")
                if not sim_ok:
                    reasons.append("colour signature too different" if sim is not None else "no colour signature")
                basis = {"topology": f"{e['a_source']} → {e['b_source']} adjacent",
                         "travel_s": round(gap_s, 1), "window_s": [e["min_travel_s"], e["max_travel_s"]],
                         "colour_similarity": None if sim is None else round(sim, 3),
                         "threshold": SIM_THRESHOLD,
                         "colours": [colour_name(a["appearance"]), colour_name(b["appearance"])],
                         "reasons": reasons, "identity": "not established — appearance and timing only"}
                rid = f"R-{a['id']}->{b['id']}"
                db.insert(conn, "relations", {"id": rid, "workspace_id": workspace_id, "kind": "same_object_candidate",
                                              "a_id": a["id"], "b_id": b["id"], "status": status, "basis": basis,
                                              "created_ts": db.now()})
                out.append({"id": rid, "status": status, **basis})
    conn.commit()
    return out


def chain_from(conn, track_id: str) -> list[dict]:
    """Follow INFERRED same-object links forward from a track (no cycles)."""
    chain, seen, cur = [], {track_id}, track_id
    while True:
        r = db.row(conn.execute(
            "SELECT * FROM relations WHERE a_id=? AND kind='same_object_candidate' AND status='INFERRED' "
            "ORDER BY json_extract(basis,'$.colour_similarity') DESC LIMIT 1", (cur,)).fetchone())
        if not r or r["b_id"] in seen:
            return chain
        chain.append(r)
        seen.add(r["b_id"])
        cur = r["b_id"]
