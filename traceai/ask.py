""""Ask the station": natural-language questions over the recent event log.

The model only sees TRACE's structured log (incident ids, times, zones, measured details,
transcripts) — never raw video and never identities — and must cite ids. On the UGen300 this
runs a 1.5B LLM from the Hailo GenAI zoo; on a laptop it reuses the Qwen2-VL-2B text decoder.
If no model is available, a keyword retriever returns the matching log lines instead.
"""
from __future__ import annotations

import re
import time

SYSTEM = ("You are TRACE, an assistant for a metro station duty officer. Answer the question in one or two "
          "plain English sentences using ONLY the event log. Do not copy log lines. End each sentence with the "
          "ids it relies on in square brackets. If the log does not contain the answer, say so. Never guess "
          "identities or intentions.")

EXAMPLE = ("EXAMPLE LOG:\n[INC-X-0009] 09:10:02-09:10:20 metro zones A (Concourse) priority medium status pending: "
           "Crowd density surge\n  [SIG-X0031] 09:10:02 CAM-01 zone A (Concourse) crowd_surge: people count 5 -> 12\n"
           "EXAMPLE QUESTION: Anything at the concourse?\n"
           "EXAMPLE ANSWER: Yes, at 09:10 CAM-01 saw the crowd on the Concourse grow from 5 to 12 people, still "
           "pending review [INC-X-0009][SIG-X0031].")


def event_log(incidents: list[dict], zone_names: dict[str, str] | None = None, limit: int = 40) -> str:
    zn = zone_names or {}

    def z(code: str) -> str:
        return f"{code} ({zn[code]})" if code in zn else code

    lines = []
    for i in sorted(incidents, key=lambda i: i["start_ts"])[-limit:]:
        lines.append(f"[{i['id']}] {i['start_ts'][11:19]}-{i['end_ts'][11:19]} {i['scenario']} zones "
                     f"{', '.join(z(c) for c in i['zones'])} priority {i['priority']} status {i['status']}: "
                     f"{i['title']}")
        for s in i.get("signals", []):
            what = f'"{s["transcript"]}"' if s.get("transcript") else s.get("detail", "")
            lines.append(f"  [{s['id']}] {s['ts'][11:19]} {s['sensor']} zone {z(s['zone'])} {s['kind']}: {what}")
    return "\n".join(lines)


STOP = {"anything", "near", "what", "happened", "was", "were", "the", "any", "there", "did", "who", "how",
        "about", "tell", "show", "with", "from", "this", "that", "have", "has", "been", "reported"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1 and w not in STOP}


def retrieve(question: str, incidents: list[dict], zone_names: dict[str, str] | None = None, k: int = 2):
    """Rank incidents by word overlap between the question and their signals (zone names included)."""
    zn = zone_names or {}
    q = _words(question)
    # "exit c" / "platform 1" style references: match zone names as phrases too
    phrases = {code for code, name in zn.items() if name.lower() in question.lower()}
    scored = []
    for inc in incidents:
        hits = []
        for sg in inc.get("signals", []):
            text = " ".join([sg["kind"].replace("_", " "), sg.get("detail") or "", sg.get("transcript") or "",
                             zn.get(sg["zone"], "")])
            score = len(q & _words(text)) + 2 * (sg["zone"] in phrases)
            if score:
                hits.append((score, sg))
        title_score = len(q & _words(inc["title"]))
        total = sum(h[0] for h in hits) + title_score
        if total:
            scored.append((total, inc, [h[1] for h in sorted(hits, key=lambda h: -h[0])][:3]))
    if phrases:  # an exact zone reference ("platform 1") outranks loose word overlap
        scored = [x for x in scored if any(sg["zone"] in phrases for sg in x[2])] or scored
    scored.sort(key=lambda x: -x[0])
    return [(inc, sigs) for _, inc, sigs in scored[:k]]


def keyword_answer(question: str, log: str) -> str:
    words = {w for w in re.findall(r"[a-z0-9-]+", question.lower()) if len(w) > 2}
    hits = [l.strip() for l in log.splitlines() if words & set(re.findall(r"[a-z0-9-]+", l.lower()))]
    return "Matching log entries: " + (" | ".join(hits[:4]) if hits else "none.")


class Asker:
    def __init__(self, llm=None):
        self.llm = llm

    def ask(self, question: str, incidents: list[dict], zone_names: dict[str, str] | None = None) -> dict:
        t = time.perf_counter()
        hits = retrieve(question, incidents, zone_names)
        if not hits:
            return {"answer": "Nothing in the recent event log matches that question.", "citations": [],
                    "model": "retriever", "ms": round(1000 * (time.perf_counter() - t))}
        log = event_log([inc for inc, _ in hits], zone_names)
        cites = []
        for inc, sigs in hits:
            cites += [inc["id"]] + [sg["id"] for sg in sigs]
        if self.llm is not None:
            prompt = f"{SYSTEM}\n\n{EXAMPLE}\n\nEVENT LOG:\n{log}\n\nQUESTION: {question}\nANSWER:"
            answer = re.sub(r"\s*\[[^\]]*\]", "", self.llm.chat(prompt, max_new_tokens=70)).strip()
            model = self.llm.model_id.split("/")[-1]
        else:
            answer, model = keyword_answer(question, log), "keyword retriever"
        # Citations come from retrieval, not from the model, so they are always real ids.
        answer += " " + "".join(f"[{c}]" for c in cites)
        return {"answer": answer, "citations": cites, "model": model, "ms": round(1000 * (time.perf_counter() - t))}
