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
from collections import defaultdict
import time
from datetime import datetime

from . import db, memory

INTENTS = ("case_reconstruct", "case_sources", "case_coverage", "object_fate", "events_list", "event_before", "event_why", "place", "evidence", "search")

OBJECT_WORDS = r"\b(bike|bicycle|backpack|bag|equipment|tool|object|b-\d+)\b"
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
        self.lanes = None  # optional parallel record lanes (case studies: reconstruction vs operations log)
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
                               "provenance": evidence.get("provenance"), "meta": evidence.get("meta")})
        return f"[E{n}]"

    def to_json(self) -> dict:
        return {"question": self.question, "workspace_id": self.workspace_id, "intent": self.intent,
                "planner": self.planner, "subject": self.subject, "headline": self.headline, "steps": self.steps,
                "lanes": self.lanes,
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
    if workspace_kind == "case":  # retrospective case studies answer from published records only
        if re.search(r"\b(cameras?|cctv|footage|recordings?|recorders?|replay|nvr|missing|gaps?|see|saw|model)\b", q):
            return "case_coverage", {}
        if re.search(r"\b(which|what) (records?|sources?|documents?)\b|\bsupport|\bsources?\b|\bcite", q):
            return "case_sources", {}
        return "case_reconstruct", {}
    if re.search(r"\b(evidence|show me (the )?proof|source)\b", q) and not re.search(OBJECT_WORDS, q):
        return "evidence", {}
    if re.search(r"\b(which|what|any|how many|list|all)\b.*\b(alerts?|events?|incidents?|warnings?)\b", q) and not re.search(r"\b(why|before)\b", q):
        return "events_list", {}
    if re.search(r"\bwhy\b.*\b(flag|alert|event|incident|warning)", q) or "why was" in q:
        return "event_why", {}
    if re.search(r"\b(before|lead(ing)? up|prior to)\b", q) or re.search(r"what happened (in|at) the (station|site)", q):
        return "event_before", {}
    if re.search(r"\b(weav\w*|swerv\w*|erratic|drunk|impaired)\b", q):
        return "events_list", {}
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


# Which place a question is about, when the user hasn't picked one. Keyword evidence first; if nothing matches,
# every candidate workspace is asked and the answer with the most cited evidence wins.
ROUTE_WORDS = {
    "campus": r"\b(bikes?|bicycles?|racks?|parking|parked|underpass|riverside|stolen|my)\b",
    "road": r"\b(road|bridge|traffic|driv\w*|riders?|motorcycles?|scooters?|weav\w*|swerv\w*|drunk|impaired|lanes?|erratic)\b",
    "metro": r"\b(metro|station|platform|trains?|intercom|radio|passengers?|commuters?|exit|emergency alert|alarm)\b",
    "construction": r"\b(construction|site|workers?|trucks?|mixer|crane|excavator|pour|haul|safety|hazard|helmet|machinery)\b",
    "case": r"(taipei main|zhongshan|eslite|nanxi|december|\b1219\b|12/19|19 dec|reconstruct|unfold|records support|which records|every camera|route missing)",
}


def route(conn, question: str, candidates: list[str], prefer: str | None = None) -> tuple[str, str]:
    q = question.lower()
    kinds = {r["id"]: r["kind"] for r in conn.execute(
        "SELECT id, kind FROM workspaces WHERE id IN (%s)" % ",".join("?" * len(candidates)), candidates)}
    scores = {w: len(re.findall(ROUTE_WORDS.get(kinds.get(w, ""), r"$^"), q)) for w in candidates}
    t = re.search(r"\b(\d{1,2}):(\d{2})", q)
    if t:  # a clock time names the site that has an alert at that minute
        hm = f"{int(t.group(1)):02d}:{t.group(2)}"
        for w in candidates:
            if conn.execute("SELECT 1 FROM events WHERE workspace_id=? AND substr(ts_start, 12, 5)=?", (w, hm)).fetchone():
                scores[w] += 3
    best = max(scores.values()) if scores else 0
    top = [w for w in candidates if scores[w] == best]
    if best > 0 and len(top) == 1:
        return top[0], "keywords"
    if prefer in candidates and (best == 0 or prefer in top):  # a follow-up stays with the answer it follows
        return prefer, "context"
    tried = []
    for w in (top if best > 0 else candidates):
        a = ask(conn, w, question, audit=False)
        tried.append((len(a["citations"]) + (1 if a.get("headline") else 0), w))
    return max(tried)[1], "best evidence"


def ask(conn, workspace_id: str, question: str, event_id: str | None = None, audit: bool = True) -> dict:
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
     "place": _place, "evidence": _event_before, "search": _search, "events_list": _events_list,
     "case_reconstruct": _case_reconstruct, "case_sources": _case_sources, "case_coverage": _case_coverage}[intent](conn, ws, ans, ents)
    if audit:
        db.audit(conn, workspace_id, "user", "ask", intent, question[:200])
        conn.commit()
    out = ans.to_json()
    out["workspace"] = {"id": ws["id"], "name": ws["name"], "kind": ws["kind"]}
    return out


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


def _case_records(conn, ws, ans: Answer):
    obs = _call(ans, "search_observations", memory.search_observations, conn, ws["id"], "")
    obs = sorted([o for o in obs if o["status"] == "OFFICIAL"], key=lambda o: (o["ts"], o["id"]))
    zones = {z["id"]: z["name"] for z in db.rows(conn.execute("SELECT id, name FROM zones WHERE workspace_id=?", (ws["id"],)))}
    out = []
    for o in obs:
        e = _call(ans, "get_evidence", memory.get_evidence, conn, o["evidence_id"])
        out.append((o, e, zones.get(o["zone_id"], "")))
    return out


def _doc_step(ans: Answer, o, e, place):
    m = e.get("meta") or {}
    c = ans.cite(e, "OFFICIAL", o["ts"], o["detail"])
    ans.step(o["ts"], "OFFICIAL", place, o["detail"], f"{m.get('publisher')} · {m.get('locator')} — “{m.get('excerpt')}”", c)
    ans.steps[-1].update({"precision": m.get("precision"), "source": m.get("source"), "record_type": m.get("record_type")})
    return c


def _case_reconstruct(conn, ws, ans: Answer, ents):
    ans.subject = {"type": "case", "id": ws["id"], "label": ws["name"]}
    recs = _case_records(conn, ws, ans)
    by = {o["id"].split("-")[-1]: (o, e, p) for o, e, p in recs}
    cites = {k: _doc_step(ans, *by[k]) for k in sorted(by)}
    ans.gaps = db.rows(conn.execute("SELECT * FROM gaps WHERE workspace_id=?", (ws["id"],)))
    ans.headline = (f"In the prosecutors' reconstruction, the incident moved from B1 below Exit M7 at Taipei Main Station, from about "
                    f"17:22 {cites['T02']}, to the crossing outside Zhongshan Station at about 18:38 {cites['T09']}. "
                    f"Taipei Metro's log records the response: a fire alarm at 17:24 {cites['T03']}, and trains passing Taipei Main "
                    f"without stopping from 17:32 to 17:42 {cites['T05']}.")
    ans.sentences.append(ans.headline)
    ans.sentences.append("Every statement comes from a published record; original CCTV was not provided, so nothing here is a model observation.")


def _case_sources(conn, ws, ans: Answer, ents):
    ans.subject = {"type": "case", "id": ws["id"], "label": ws["name"]}
    recs = _case_records(conn, ws, ans)
    lanes = {"official_reconstruction": [], "ops": []}
    for o, e, p in recs:
        c = _doc_step(ans, o, e, p)
        m = e.get("meta") or {}
        lane = "official_reconstruction" if m.get("record_type") == "official_reconstruction" else "ops"
        lanes[lane].append({"ts": o["ts"], "text": o["detail"], "n": int(c[2:-1]), "precision": m.get("precision"),
                            "source": m.get("source"), "place": p})
    ans.lanes = [{"name": "Prosecutors' reconstruction", "meta": "S1 · Taipei District Prosecutors Office · published 15 Jan 2026",
                  "items": lanes["official_reconstruction"]},
                 {"name": "Taipei Metro operations record", "meta": "S2 log dated 19 Dec 2025 · S3 statement of 22 Dec 2025",
                  "items": lanes["ops"]}]
    first = lanes["official_reconstruction"][1] if len(lanes["official_reconstruction"]) > 1 else None
    alarm = next((i for i in lanes["ops"] if i["ts"].endswith("17:24:00")), None)
    ans.headline = ("Two kinds of record, kept separate: the prosecutors' reconstruction, published on 15 January 2026, times the incident"
                    + (f" [E{first['n']}]" if first else "") + "; Taipei Metro's operations record times the response"
                    + (f" [E{alarm['n']}]" if alarm else "") + ". About 17:22 and 17:24 describe different actions, so they are not merged.")
    ans.sentences.append(ans.headline)


def _case_coverage(conn, ws, ans: Answer, ents):
    ans.subject = {"type": "case", "id": ws["id"], "label": ws["name"]}
    ev = {k: _call(ans, "get_evidence", memory.get_evidence, conn, f"E-1219-{k}") for k in ("C1", "C2", "C3", "C4")}
    c1 = ans.cite(ev["C1"], "OFFICIAL", None, ev["C1"]["caption"])
    c2 = ans.cite(ev["C2"], "OFFICIAL", None, ev["C2"]["caption"])
    for k, status, title in [("C1", "OFFICIAL", "One B2 recorder showed live images but could not replay"),
                             ("C2", "OFFICIAL", "Three other B2 recorders covered the route without a break"),
                             ("C3", "OFFICIAL", "41 fire detectors triggered across zones")]:
        m = ev[k]["meta"]
        ans.step(None, status, "Taipei Main", title, f"{m['publisher']} · {m['date']} · {m['locator']} — “{m['excerpt']}”",
                 ans.cite(ev[k], status, None, title))
    gap = db.row(conn.execute("SELECT * FROM gaps WHERE workspace_id=?", (ws["id"],)).fetchone())
    ans.gaps = [gap] if gap else []
    ans.step(None, "UNKNOWN", "VESTIGE", "Original CCTV not provided — no visual claims about this case", gap["reason"] + "." if gap else "")
    m = ev["C4"]["meta"]
    ans.step(None, "NEWS", "Investigation", "Investigators reviewed more than 3,000 cameras",
             f"{m['publisher']} · {m['date']} — “{m['excerpt']}”", ans.cite(ev["C4"], "NEWS", None, "secondary report"))
    ans.headline = (f"No. Taipei Metro says no camera failed: one recorder on the route at B2 could show live images but not replay them "
                    f"{c1}, and the other three B2 recorders covered the route without a break {c2}. VESTIGE was not given the original "
                    "footage, so it makes no visual claims about this case.")
    ans.sentences.append(ans.headline)


def _events_list(conn, ws, ans: Answer, ents):
    evs = _call(ans, "search_events", memory.search_events, conn, ws["id"])
    if not evs:
        ans.headline = "No alerts have been raised in this workspace."
        ans.sentences.append(ans.headline)
        return
    evs = sorted(evs, key=lambda e: e["ts_start"])
    ans.subject = {"type": "events", "label": f"{len(evs)} alerts"}
    tags = []
    for e in evs:
        ev = _call(ans, "get_evidence", memory.get_evidence, conn, e["evidence_id"]) if e.get("evidence_id") else None
        c = ans.cite(ev, "OBSERVED", e["ts_start"], e["title"])
        src = (ev or {}).get("source") or {}
        place = (src.get("name") or "").split(" · ")[-1]
        dur = (e.get("metrics") or {}).get("duration_s")
        tags.append(f"{hhmm(e['ts_start'])}{f' ({dur:.0f} s)' if isinstance(dur, (int, float)) else ''} {c}")
        ans.sentences.append(f"{hhmm(e['ts_start'])} — {e['title']} ({e['priority']}) {c}")
        ans.step(e["ts_start"], "OBSERVED", place, e["title"] + (f" · {dur:.0f} s" if isinstance(dur, (int, float)) else ""),
                 f"{e['priority'].capitalize()} priority · {'needs review' if e['status'] == 'open' else e['status']}.", c)
        ans.steps[-1]["event_id"] = e["id"]
        ans.timeline.append({"ts": e["ts_start"], "status": "OBSERVED", "source": place, "kind": e["kind"],
                             "detail": e["title"], "evidence_id": e.get("evidence_id"), "event_id": e["id"]})
    open_n = sum(e["status"] == "open" for e in evs)
    longest = max(evs, key=lambda e: (e.get("metrics") or {}).get("duration_s") or 0)
    lc = ans.cite(memory.get_evidence(conn, longest["evidence_id"]) if longest.get("evidence_id") else None,
                  "OBSERVED", longest["ts_start"], longest["title"])
    ld = (longest.get("metrics") or {}).get("duration_s")
    review = (" It still needs review." if open_n == len(evs) == 1 else
              f" {'All ' + str(open_n) if open_n == len(evs) else open_n} still need review." if open_n else " All reviewed.")
    if all(e["kind"] == "lateral_weaving" for e in evs):
        ans.headline = (f"{len(evs)} rider{'s' if len(evs) != 1 else ''} weaving across the lane — "
                        f"{(longest.get('metrics') or {}).get('swings', '?')} sideways swings in {ld} s at {hhmm(longest['ts_start'])} {lc}. "
                        "The cause is not inferred." + review)
    elif all(e["kind"] == "worker_vehicle_proximity" for e in evs):
        ans.headline = (f"{len(evs)} worker–truck overlap alert{'s' if len(evs) != 1 else ''}"
                        + (f" — the longest lasted {ld:.0f} s, at {hhmm(longest['ts_start'])} {lc}." if ld else f" {lc}.") + review)
    else:
        ans.headline = f"{len(evs)} alert{'s' if len(evs) != 1 else ''} so far; the first at {hhmm(evs[0]['ts_start'])}.{review}"


def _pick_event(conn, ws, ans: Answer):
    if getattr(ans, "event_id", None):
        ev = _call(ans, "get_event", memory.get_event, conn, ans.event_id)
        if ev and ev["workspace_id"] == ws["id"]:
            return ev
    q = ans.question.lower()
    evs = _call(ans, "search_events", memory.search_events, conn, ws["id"])
    if not evs:
        return None
    t = re.search(r"\b(\d{1,2}):(\d{2})", q)
    if t:
        hm = f"{int(t.group(1)):02d}:{t.group(2)}"
        at = [e for e in evs if e["ts_start"][11:16] == hm]
        if at:
            evs = at
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
        title, basis = _plain(o["detail"])
        ans.step(o["ts"], o["status"], o["source"].split(" · ")[0], title, basis, c)
    for g in tl["gaps"]:
        ans.sentences.append(f"Evidence gap: {g['source']} — {g['reason']}.")
        ans.step(g["ts_start"], "UNKNOWN", g["source"].split(" · ")[0], "No recording for this window", g["reason"] + ".")
    if not ans.headline:
        words = {"detector_alarm": ("an alarm", "alarms"), "staff_report": ("a staff radio call", "staff radio calls"),
                 "scene_check": ("a camera check", "camera checks"), "proximity": ("a worker–truck proximity", "worker–truck proximities"),
                 "moved": ("a movement", "movements"), "seen": ("a sighting", "sightings")}
        kinds = defaultdict(int)
        for o in obs:
            kinds[o["kind"]] += 1
        parts = [words.get(k, (k.replace("_", " "), k.replace("_", " ") + "s"))[n != 1] if n == 1 else
                 f"{n} {words.get(k, (k, k + 's'))[1]}" for k, n in kinds.items()]
        listed = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1] if parts else "nothing"
        gap = (f" {', '.join(g['source'].split(' · ')[0] for g in tl['gaps'])} has no recording for that minute."
               if tl["gaps"] else "")
        ans.headline = f"In the minute before \"{ev['title']}\": {listed}.{gap}"


def _plain(detail: str) -> tuple[str, str]:
    """Short human title for an observation; track ids and measurement caveats move to the basis."""
    m = re.match(r"[Ww]orker #(\d+) (overlapping|within [\d.]+ body-heights of) (\w+) #(\d+) for ([\d.]+) s", detail)
    if m:
        verb = "overlaps" if m.group(2) == "overlapping" else "comes close to"
        return (f"Worker {verb} a {m.group(3)} for {float(m.group(5)):.0f} s",
                f"Worker #{m.group(1)} and {m.group(3)} #{m.group(4)} · measured in the image (uncalibrated camera).")
    m = re.match(r"(\d+) people visible when (\S+) fired", detail)
    if m:
        return f"{m.group(1)} people on camera", f"Counted when {m.group(2)} fired."
    m = re.match(r"(\w+) track (\d+): (\d+) lateral swings, std ([\d.]+) vehicle widths over ([\d.]+) s", detail)
    if m:
        return (f"{m.group(1).capitalize()} swings sideways {m.group(3)} times in {float(m.group(5)):.0f} s",
                f"{m.group(1)} track #{m.group(2)} · lateral spread {m.group(4)} vehicle widths · cause not inferred.")
    if detail.startswith('"'):
        return "Staff radio call", detail
    return detail[:1].upper() + detail[1:], ""


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
        ans.headline = (f"Flagged because a worker {where} a {m.get('vehicle_class', 'vehicle')} for "
                        f"{m.get('duration_s', '?')} s {c}. Measured in the image, not as a real distance.")
        ans.sentences.append("This is image-space proximity from an uncalibrated camera, not a measured distance "
                             "or a collision prediction. Stress-test the event in IncidentLab to see how reliable "
                             "the detections behind it are.")
    elif ev["kind"] == "fused_incident":
        ans.sentences.append(f"TRACE fused {m.get('n_signals', '?')} signals into this incident (score "
                             f"{m.get('score', '?')}) {c}.")
        vlm = (m.get("vlm") or {}).get("second_opinion")
        ans.headline = f"Flagged because {m.get('n_signals', '?')} separate signals pointed to the same place and time {c}."
        if vlm:
            ans.sentences.append(f"The on-device VLM was asked: \"{vlm['question']}\" and answered \"{vlm['answer']}\".")
    elif ev["kind"] == "lateral_weaving":
        ans.headline = (f"Flagged because a motorcycle swung sideways {m.get('swings', '?')} times in {m.get('duration_s', '?')} s "
                        f"{c}. The cause is not inferred.")
        ans.sentences.append(ans.headline)
    else:
        ans.sentences.append(f"{ev['title']}: {ev['kind'].replace('_', ' ')} {c}.")
        ans.headline = (f"Flagged because a parked bicycle left its position {c}. Movement alone is not theft."
                        if ev["kind"] == "object_moved" else f"{ev['title']} {c}.")
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
    name = (zones[0]["name"] if zones else srcs[0]["name"].split(" · ")[-1])
    # who/what was there: distinct tracks by class (pseudonymous counts, no identities)
    tids = sorted({o["track_id"] for o in obs if o.get("track_id")})
    cls = db.rows(conn.execute("SELECT cls, COUNT(*) AS n FROM tracks WHERE id IN (%s) GROUP BY cls" % ",".join("?" * len(tids)), tids)) if tids else []
    noun = {"person": ("person", "people"), "bicycle": ("bicycle", "bicycles"), "truck": ("truck", "trucks"),
            "car": ("car", "cars"), "bus": ("bus", "buses"), "motorcycle": ("motorcycle", "motorcycles")}
    counts = ", ".join(f"{r['n']} {noun.get(r['cls'], (r['cls'], r['cls'] + 's'))[r['n'] != 1]}" for r in sorted(cls, key=lambda r: -r["n"]))
    src_ids = {o["source_id"] for o in obs}
    evs = [e for e in _call(ans, "search_events", memory.search_events, conn, ws["id"])
           if e.get("evidence_id") and (memory.get_evidence(conn, e["evidence_id"]) or {}).get("source_id") in src_ids]
    ans.headline = (f"At {name} between {hhmm(obs[0]['ts'])} and {hhmm(obs[-1]['ts'])}: {counts or 'activity'} on camera"
                    + (f", and {len(evs)} alert{'s' if len(evs) != 1 else ''}." if evs else ", no alerts."))
    ans.sentences.append(ans.headline)
    for e in sorted(evs, key=lambda e: e["ts_start"]):
        ev = _call(ans, "get_evidence", memory.get_evidence, conn, e["evidence_id"])
        c = ans.cite(ev, "OBSERVED", e["ts_start"], e["title"])
        dur = (e.get("metrics") or {}).get("duration_s")
        ans.step(e["ts_start"], "OBSERVED", name, e["title"] + (f" · {dur:.0f} s" if isinstance(dur, (int, float)) else ""),
                 f"{e['priority'].capitalize()} priority alert.", c)
        ans.steps[-1]["event_id"] = e["id"]
    seen = set()
    for o in obs:
        if len(ans.steps) >= 6:
            break
        if o.get("track_id") in seen or o["kind"] not in ("seen", "moved"):
            continue
        seen.add(o.get("track_id"))
        e = _call(ans, "get_evidence", memory.get_evidence, conn, o["evidence_id"]) if o.get("evidence_id") else None
        c = ans.cite(e, o["status"], o["ts"], o["kind"])
        title, basis = _plain(re.sub(r" · colour .*$", "", o["detail"]).replace("person", "Person"))
        ans.step(o["ts"], o["status"], name, title, basis or o["detail"], c)
        ans.timeline.append({"ts": o["ts"], "status": o["status"], "source": o["source_id"], "kind": o["kind"],
                             "detail": o["detail"], "evidence_id": o["evidence_id"]})


def _search(conn, ws, ans: Answer, ents):
    words = [w for w in re.findall(r"[a-z0-9]+", ents.get("text", "").lower()) if len(w) > 3]
    hits = []
    for w in words[:4]:
        hits += _call(ans, "search_observations", memory.search_observations, conn, ws["id"], w)
    uniq = {h["id"]: h for h in hits}
    if not uniq:
        ans.sentences.append("Nothing in this workspace's memory matches that question. Try asking about an "
                             "object, an event, or a place.")
        ans.headline = "I couldn't find that in what the cameras recorded. Try asking about an object, a place or an alert."
        return
    ans.headline = f"{len(uniq)} stored observations match your question."
    ans.sentences.append(f"{len(uniq)} matching observations:")
    for o in sorted(uniq.values(), key=lambda o: o["ts"])[:6]:
        e = _call(ans, "get_evidence", memory.get_evidence, conn, o["evidence_id"]) if o.get("evidence_id") else None
        c = ans.cite(e, o["status"], o["ts"], o["kind"])
        ans.sentences.append(f"{hhmm(o['ts'])} — {o['detail']} {c}")
        ans.step(o["ts"], o["status"], o.get("source_id") or "", o["detail"][:1].upper() + o["detail"][1:], o.get("kind", ""), c)
