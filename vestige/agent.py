"""Evidence-grounded investigation agent.

Planner → tools → answer. The planner maps a question to an intent and entities; tools are the
deterministic functions in `memory.py`; the answer is composed only from tool results, and every
sentence cites an evidence number [E#] that resolves to a stored frame, clip, transcript or record.

The planner is deterministic by default (documented fallback, no API key needed). An optional
local model (`VESTIGE_LLM=qwen`) is only allowed to *choose an intent from a fixed list* when the
rules are unsure; it never writes facts.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime

from . import db, memory

INTENTS = ("object_fate", "event_before", "event_why", "place", "evidence", "search")

OBJECT_WORDS = r"\b(bike|bicycle|scooter|backpack|bag|equipment|tool|object|b-\d+)\b"
PLACE_WORDS = r"\b(near|at|around|in)\s+(?P<place>[a-z0-9 ]{3,30})"


class Answer:
    def __init__(self, question: str, workspace_id: str):
        self.question, self.workspace_id = question, workspace_id
        self.sentences: list[str] = []
        self.citations: list[dict] = []
        self.timeline: list[dict] = []
        self.gaps: list[dict] = []
        self.tool_calls: list[dict] = []
        self.intent = None
        self.planner = "deterministic"
        self.subject = None
        self.headline = ""  # direct answer to the question asked, composed from the same tool results
        self.steps: list[dict] = []  # short structured timeline for the UI; `basis` holds the reasoning detail

    def step(self, ts, status, place, title, basis="", cite_tag=""):
        n = int(cite_tag[2:-1]) if cite_tag.startswith("[E") else None
        self.steps.append({"ts": ts, "status": status, "place": place, "title": title, "basis": basis, "n": n})

    def cite(self, evidence: dict | None, status: str, ts: str | None, label: str) -> str:
        if not evidence:
            return ""
        for c in self.citations:
            if c["evidence_id"] == evidence["id"]:
                return f"[E{c['n']}]"
        n = len(self.citations) + 1
        self.citations.append({"n": n, "evidence_id": evidence["id"], "status": status, "ts": ts or evidence["ts"],
                               "label": label, "kind": evidence["kind"], "url": evidence.get("url"),
                               "source": (evidence.get("source") or {}).get("name"),
                               "source_id": evidence["source_id"], "t_offset_s": evidence.get("t_offset_s"),
                               "proxy_url": evidence.get("proxy_url"), "caption": evidence.get("caption"),
                               "provenance": evidence.get("provenance")})
        return f"[E{n}]"

    def to_json(self) -> dict:
        return {"question": self.question, "workspace_id": self.workspace_id, "intent": self.intent,
                "planner": self.planner, "subject": self.subject, "headline": self.headline, "steps": self.steps,
                "answer": " ".join(self.sentences),
                "sentences": self.sentences, "citations": self.citations, "timeline": self.timeline,
                "gaps": self.gaps, "tool_calls": self.tool_calls}


def _call(ans: Answer, name: str, fn, *args, **kw):
    t = time.perf_counter()
    out = fn(*args, **kw)
    n = len(out) if isinstance(out, list) else (len(out.get("entries", out.get("observations", []))) if isinstance(out, dict) else 1)
    ans.tool_calls.append({"tool": name, "args": [a for a in args[1:] if isinstance(a, (str, int, float))] or kw or None,
                           "results": n, "ms": round(1000 * (time.perf_counter() - t), 2)})
    return out


def hhmm(ts: str | None) -> str:
    return ts[11:19] if ts else "?"


def plan(question: str, workspace_kind: str) -> tuple[str, dict]:
    q = question.lower()
    if re.search(r"\b(evidence|show me (the )?proof|source)\b", q) and not re.search(OBJECT_WORDS, q):
        return "evidence", {}
    if re.search(r"\bwhy\b.*\b(flag|alert|event|incident|warning)", q) or "why was" in q:
        return "event_why", {}
    if re.search(r"\b(before|lead(ing)? up|prior to)\b", q) or re.search(r"what happened (in|at) the (station|site)", q):
        return "event_before", {}
    if re.search(OBJECT_WORDS, q) or re.search(r"\b(where|who moved|last seen|my )\b", q):
        m = re.search(OBJECT_WORDS, q)
        return "object_fate", {"object": m.group(1) if m else ""}
    m = re.search(PLACE_WORDS, q)
    if m:
        return "place", {"place": m.group("place").strip(" ?.")}
    return "search", {"text": q}


def _llm_intent(question: str) -> str | None:
    """Optional: let a local model pick ONE intent label when rules fall back to plain search."""
    if os.environ.get("VESTIGE_LLM") != "qwen":
        return None
    try:
        from traceai.summarize import VLMCaptioner

        global _LLM
        _LLM = globals().get("_LLM") or VLMCaptioner()
        out = _LLM.chat("Classify the question into exactly one label from: " + ", ".join(INTENTS)
                        + f".\nQuestion: {question}\nLabel:", max_new_tokens=6).strip().lower()
        return next((i for i in INTENTS if i in out), None)
    except Exception:
        return None


def ask(conn, workspace_id: str, question: str, event_id: str | None = None) -> dict:
    ws = db.row(conn.execute("SELECT * FROM workspaces WHERE id=?", (workspace_id,)).fetchone())
    if not ws:
        raise KeyError(workspace_id)
    ans = Answer(question, workspace_id)
    ans.event_id = event_id
    intent, ents = plan(question, ws["kind"])
    if event_id and intent not in ("event_before", "event_why", "evidence"):
        intent = "event_before"
    if intent == "search":
        llm = _llm_intent(question)
        if llm and llm != "search":
            intent, ans.planner = llm, "qwen (intent only)"
    ans.intent = intent
    {"object_fate": _object_fate, "event_before": _event_before, "event_why": _event_why,
     "place": _place, "evidence": _event_before, "search": _search}[intent](conn, ws, ans, ents)
    db.audit(conn, workspace_id, "user", "ask", intent, question[:200])
    conn.commit()
    return ans.to_json()


def _object_fate(conn, ws, ans: Answer, ents):
    term = ents.get("object") or ""
    if term in ("bike",):
        term = "bicycle"
    objs = _call(ans, "search_objects", memory.search_objects, conn, ws["id"], "me") \
        if "my " in ans.question.lower() else []
    if not objs:
        objs = _call(ans, "search_objects", memory.search_objects, conn, ws["id"], term)
    if not objs:
        ans.sentences.append("No registered object in this workspace matches that description. "
                             "Register it (Memory → Record parking) or search observations instead.")
        return _search(conn, ws, ans, {"text": term})
    obj = objs[0]
    ans.subject = {"type": "object", "id": obj["id"], "label": obj["label"]}
    hist = _call(ans, "get_object_history", memory.get_object_history, conn, obj["id"])
    entries = hist["entries"]
    for e in entries:
        ans.timeline.append({"ts": e["ts"], "status": e["status"], "source": e["source"], "kind": e["kind"],
                             "detail": e["detail"], "evidence_id": e["evidence_id"], "via": e["via"]})
    ans.gaps = hist["gaps"]

    def ev(e):
        return _call(ans, "get_evidence", memory.get_evidence, conn, e["evidence_id"]) if e.get("evidence_id") else None

    rec = next((e for e in entries if e["status"] == "RECORDED"), None)
    direct = [e for e in entries if e["status"] in ("OBSERVED", "LAST_SEEN")]
    moved = next((e for e in direct if e["kind"] == "moved"), None)
    inferred = [e for e in entries if e["status"] == "INFERRED"]
    label = obj["description"] or obj["cls"]
    if rec:
        ans.sentences.append(f"You recorded your {label} at {rec['source'].split(' · ')[-1]} at {hhmm(rec['ts'])} "
                             f"(owner check-in{', staged demo record' if rec['provenance'] == 'staged' else ''}).")
        ans.step(rec["ts"], "RECORDED", rec["source"].split(" · ")[-1], "You parked it here",
                 "Owner check-in — your statement, not a camera observation"
                 + (" (staged demo record)." if rec["provenance"] == "staged" else "."))
    if direct:
        before = [e for e in direct if moved is None or e["ts"] <= moved["ts"]]
        first = before[0] if before else direct[0]
        c = ans.cite(ev(first), "OBSERVED", first["ts"], "seen at its position")
        ans.sentences.append(f"{first['source'].split(' · ')[0]} observed it in place at {hhmm(first['ts'])} {c}.")
        ans.step(first["ts"], "OBSERVED", first["source"].split(" · ")[-1], "Still in its parked position",
                 f"{first['source'].split(' · ')[0]}: {first['detail']}.", c)
    if moved:
        c = ans.cite(ev(moved), "OBSERVED", moved["ts"], "left its position")
        who = re.search(r"person #(\d+)", moved["detail"])
        ans.sentences.append(f"At {hhmm(moved['ts'])} it left its parked position"
                             + (f", handled by an unidentified person (track #{who.group(1)})" if who else "") + f" {c}.")
        ans.step(moved["ts"], "OBSERVED", moved["source"].split(" · ")[-1],
                 "Moved from its parked position" + (" by an unidentified person" if who else ""),
                 f"{moved['source'].split(' · ')[0]}: {moved['detail']}. Movement is not theft — a person handling a bike "
                 "can be the owner, staff or someone else.", c)
    seen_src = []
    for e in inferred:
        if e["source"] in seen_src:
            continue
        seen_src.append(e["source"])
        c = ans.cite(ev(e), "INFERRED", e["ts"], f"similar bicycle on {e['source'].split(' · ')[0]}")
        via = e.get("via") or {}
        ans.sentences.append(
            f"A visually similar {via.get('colours', ['', ''])[1] or ''} bicycle was observed on "
            f"{e['source'].split(' · ')[-1]} at {hhmm(e['ts'])} {c} — inferred from adjacent cameras, "
            f"{via.get('travel_s', '?'):.0f} s travel time and colour similarity {via.get('colour_similarity', 0):.2f}; "
            f"not a confirmed identity.".replace("  ", " "))
        ans.step(e["ts"], "INFERRED", e["source"].split(" · ")[-1], f"Similar {(via.get('colours') or ['', ''])[1]} bicycle appears".replace("  ", " "),
                 f"{via.get('topology', 'adjacent cameras')} · {via.get('travel_s', 0):.0f} s travel (allowed "
                 f"{(via.get('window_s') or [0, 0])[0]:.0f}–{(via.get('window_s') or [0, 0])[1]:.0f} s) · colour similarity "
                 f"{via.get('colour_similarity', 0):.2f} (threshold {via.get('threshold', 0.55)}). Not a confirmed identity.", c)
    if hist.get("rejected_links"):
        ans.sentences.append(f"{len(hist['rejected_links'])} other bicycle sighting(s) nearby were checked and "
                             f"not linked (colour or timing did not match).")
        rj = hist["rejected_links"]
        ans.step(None, "REJECTED", "", f"{len(rj)} other bicycle{'s' if len(rj) != 1 else ''} checked — not linked",
                 "; ".join(f"{r['b_id'].replace('T-', '')}: colour {' vs '.join(r['basis'].get('colours') or [])} "
                           f"({r['basis'].get('colour_similarity')})" for r in rj[:3]))
    for g in hist["gaps"]:
        ans.sentences.append(g["reason"] + " — what happened after that is unknown.")
        ans.step(g["ts_start"], "UNKNOWN", "", "No camera coverage after this point", g["reason"] + ".")
    if not direct and not inferred:
        ans.sentences.append("No camera has observed this object yet.")
        ans.headline = "No camera has observed it yet."
        return
    place = lambda e: e["source"].split(" · ")[-1]
    # the first sighting on the last camera reached — the same entry the story cites for that camera
    last_inf = next(e for e in inferred if e["source"] == inferred[-1]["source"]) if inferred else None
    tail = (f" A similar bicycle was later seen at {place(last_inf)} at {hhmm(last_inf['ts'])} "
            f"{ans.cite(ev(last_inf), 'INFERRED', last_inf['ts'], 'similar bicycle')} — identity not confirmed."
            if last_inf else "")
    unknown = " Where it is now is unknown." if hist["gaps"] else ""
    if re.search(r"\b(where|last seen)\b", ans.question.lower()) and direct:
        last = direct[-1]
        c = ans.cite(ev(last), last["status"], last["ts"], "last direct observation")
        ans.headline = f"Last seen directly at {place(last)} at {hhmm(last['ts'])} {c}.{tail}{unknown}"
    elif moved:
        who = " by an unidentified person" if re.search(r"person #\d+", moved["detail"]) else ""
        c = ans.cite(ev(moved), "OBSERVED", moved["ts"], "left its position")
        ans.headline = f"It left {place(moved)} at {hhmm(moved['ts'])}, moved{who} {c}.{tail}{unknown}"
    else:
        last = direct[-1] if direct else last_inf
        ans.headline = f"Last seen at {place(last)} at {hhmm(last['ts'])}.{tail if direct else ''}{unknown}"


def _pick_event(conn, ws, ans: Answer):
    if getattr(ans, "event_id", None):
        ev = _call(ans, "get_event", memory.get_event, conn, ans.event_id)
        if ev and ev["workspace_id"] == ws["id"]:
            return ev
    q = ans.question.lower()
    evs = _call(ans, "search_events", memory.search_events, conn, ws["id"])
    if not evs:
        return None
    words = [w for w in re.findall(r"[a-z]+", q) if len(w) > 3]
    def dur(e):
        return (datetime.fromisoformat(e["ts_end"]) - datetime.fromisoformat(e["ts_start"])).total_seconds()

    scored = sorted(evs, key=lambda e: (sum(w in (e["title"] + " " + e["kind"]).lower() for w in words),
                                        {"high": 2, "medium": 1}.get(e["priority"], 0), dur(e)), reverse=True)
    return scored[0]


def _event_before(conn, ws, ans: Answer, ents):
    ev = _pick_event(conn, ws, ans)
    if not ev:
        ans.sentences.append("There are no events in this workspace yet.")
        return
    ans.subject = {"type": "event", "id": ev["id"], "label": ev["title"]}
    tl = _call(ans, "get_event_timeline", memory.get_event_timeline, conn, ev["id"], 60.0)
    ans.gaps = tl["gaps"]
    ans.sentences.append(f"\"{ev['title']}\" ({ev['priority']} priority) spans {hhmm(ev['ts_start'])}–"
                         f"{hhmm(ev['ts_end'])}. In the 60 s before it and during it, the memory holds:")
    # Context = this event's own observations, plus other workspaces' alarms/reports/events in the window;
    # routine "enters view" sightings of uninvolved tracks are left out.
    obs = [o for o in tl["observations"] if o.get("role") != "context" or o["kind"] not in ("seen",)]
    for o in obs[:8]:
        e = _call(ans, "get_evidence", memory.get_evidence, conn, o["evidence_id"]) if o.get("evidence_id") else None
        c = ans.cite(e, o["status"], o["ts"], o["kind"])
        ans.timeline.append({"ts": o["ts"], "status": o["status"], "source": o["source"], "kind": o["kind"],
                             "detail": o["detail"], "evidence_id": o["evidence_id"], "role": o.get("role")})
        ans.sentences.append(f"{hhmm(o['ts'])} — {o['source'].split(' · ')[0]} ({o['status'].lower().replace('_', ' ')}): "
                             f"{o['detail']} {c}".rstrip())
        d = o["detail"]
        ans.step(o["ts"], o["status"], o["source"].split(" · ")[0], d[:1].upper() + d[1:],
                 f"{o['source']} · {o['kind']}" + (" · trigger" if o.get("role") == "trigger" else ""), c)
    for g in tl["gaps"]:
        ans.sentences.append(f"Evidence gap: {g['source']} — {g['reason']}.")
        ans.step(g["ts_start"], "UNKNOWN", g["source"].split(" · ")[0], "No recording for this window", g["reason"] + ".")
    if not ans.headline:
        srcs = sorted({o["source"].split(" · ")[0] for o in obs})
        gap = f" {', '.join(g['source'].split(' · ')[0] for g in tl['gaps'])} has no recording for that window." if tl["gaps"] else ""
        ans.headline = (f"{len(obs)} signals were recorded on {len(srcs)} source{'s' if len(srcs) != 1 else ''} "
                        f"({', '.join(srcs[:4])}) in the minute leading up to \"{ev['title']}\".{gap}")


def _event_why(conn, ws, ans: Answer, ents):
    ev = _pick_event(conn, ws, ans)
    if not ev:
        ans.sentences.append("There are no events in this workspace yet.")
        return
    ans.subject = {"type": "event", "id": ev["id"], "label": ev["title"]}
    m = ev.get("metrics") or {}
    e = _call(ans, "get_evidence", memory.get_evidence, conn, ev["evidence_id"]) if ev.get("evidence_id") else None
    c = ans.cite(e, "OBSERVED", ev["ts_start"], ev["title"])
    if ev["kind"] == "worker_vehicle_proximity":
        gap = m.get("min_gap_body_heights", 1)
        where = "overlapped the box of" if gap < 0.01 else f"came within {gap} body-heights of"
        ans.sentences.append(
            f"It was flagged because a worker {where} a {m.get('vehicle_class', 'vehicle')} for "
            f"{m.get('duration_s', '?')} s {c}. The rule fires below 0.35 body-heights for at least 1 s.")
        ans.step(ev["ts_start"], "OBSERVED", "", f"Worker {where} a {m.get('vehicle_class', 'vehicle')} for {m.get('duration_s', '?')} s",
                 "Rule: gap below 0.35 body-heights for at least 1 s, measured in the image (uncalibrated camera). "
                 "Proximity is not intent and not a collision prediction.", c)
        ans.headline = (f"A worker {where} a {m.get('vehicle_class', 'vehicle')} for {m.get('duration_s', '?')} s {c} — "
                        f"measured in the image, not as a real distance.")
        ans.sentences.append("This is image-space proximity from an uncalibrated camera, not a measured distance "
                             "or a collision prediction. Stress-test the event in IncidentLab to see how reliable "
                             "the detections behind it are.")
    elif ev["kind"] == "fused_incident":
        ans.sentences.append(f"TRACE fused {m.get('n_signals', '?')} signals into this incident (score "
                             f"{m.get('score', '?')}) {c}.")
        vlm = (m.get("vlm") or {}).get("second_opinion")
        ans.step(ev["ts_start"], "OBSERVED", "", f"{m.get('n_signals', '?')} signals fused into one incident",
                 f"Fusion score {m.get('score', '?')}; signals agree in zone and time window." +
                 (f" On-device VLM check: \"{vlm['question']}\" → \"{vlm['answer']}\"." if vlm else ""), c)
        ans.headline = f"{m.get('n_signals', '?')} independent signals agreed within one zone and time window {c}, so they were fused into one incident."
        if vlm:
            ans.sentences.append(f"The on-device VLM was asked: \"{vlm['question']}\" and answered \"{vlm['answer']}\".")
    else:
        ans.sentences.append(f"{ev['title']}: {ev['kind'].replace('_', ' ')} {c}.")
        ans.headline = f"{ev['title']} {c} — the rule behind it is shown below."
    n_rule = len(ans.steps)
    _event_before(conn, ws, ans, ents)
    # the trigger observation repeats the rule step (same evidence); keep the rule wording
    rule_ns = {s["n"] for s in ans.steps[:n_rule] if s["n"] is not None}
    ans.steps = ans.steps[:n_rule] + [s for s in ans.steps[n_rule:] if s["n"] is None or s["n"] not in rule_ns]


def _place(conn, ws, ans: Answer, ents):
    place = re.sub(r"^(the|a|an)\s+", "", ents["place"])
    zones = db.rows(conn.execute("SELECT * FROM zones WHERE workspace_id=? AND lower(name) LIKE ?",
                                 (ws["id"], f"%{place}%")))
    srcs = db.rows(conn.execute("SELECT * FROM sources WHERE workspace_id=? AND lower(name) LIKE ?",
                                (ws["id"], f"%{place}%")))
    obs = _call(ans, "search_observations", memory.search_observations, conn, ws["id"], "",
                [s["id"] for s in srcs] or None, [z["id"] for z in zones] or None) if (zones or srcs) else []
    if not obs:
        ans.sentences.append(f"No observations are stored for \"{place}\".")
        return
    ans.subject = {"type": "place", "label": place}
    ans.headline = f"{len(obs)} observations are stored near {place}, from {hhmm(obs[0]['ts'])} to {hhmm(obs[-1]['ts'])}."
    ans.sentences.append(f"{len(obs)} observations near {place}:")
    for o in obs[:8]:
        e = _call(ans, "get_evidence", memory.get_evidence, conn, o["evidence_id"]) if o.get("evidence_id") else None
        c = ans.cite(e, o["status"], o["ts"], o["kind"])
        ans.timeline.append({"ts": o["ts"], "status": o["status"], "source": o["source_id"], "kind": o["kind"],
                             "detail": o["detail"], "evidence_id": o["evidence_id"]})
        ans.sentences.append(f"{hhmm(o['ts'])} — {o['detail']} {c}")
        ans.step(o["ts"], o["status"], o.get("source_id") or "", o["detail"][:1].upper() + o["detail"][1:], o.get("kind", ""), c)


def _search(conn, ws, ans: Answer, ents):
    words = [w for w in re.findall(r"[a-z0-9]+", ents.get("text", "").lower()) if len(w) > 3]
    hits = []
    for w in words[:4]:
        hits += _call(ans, "search_observations", memory.search_observations, conn, ws["id"], w)
    uniq = {h["id"]: h for h in hits}
    if not uniq:
        ans.sentences.append("Nothing in this workspace's memory matches that question. Try asking about an "
                             "object, an event, or a place.")
        return
    ans.headline = f"{len(uniq)} stored observations match your question."
    ans.sentences.append(f"{len(uniq)} matching observations:")
    for o in sorted(uniq.values(), key=lambda o: o["ts"])[:6]:
        e = _call(ans, "get_evidence", memory.get_evidence, conn, o["evidence_id"]) if o.get("evidence_id") else None
        c = ans.cite(e, o["status"], o["ts"], o["kind"])
        ans.sentences.append(f"{hhmm(o['ts'])} — {o['detail']} {c}")
        ans.step(o["ts"], o["status"], o.get("source_id") or "", o["detail"][:1].upper() + o["detail"][1:], o.get("kind", ""), c)
