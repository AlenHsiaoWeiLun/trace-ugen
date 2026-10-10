"""VLM "second opinion" on fused incidents.

The always-on detector is cheap and context-blind: a platform fills up both when people flee
and when a train arrives. Only after fusion produces an incident does TRACE wake the VLM on
the same accelerator and ask one targeted yes/no question about the keyframe. The answer can
only *downgrade* incidents backed exclusively by camera rules; an alarm or a human radio
report is never overridden by the model. Every verdict is written to the audit log.
"""
from __future__ import annotations

from .schema import Incident

CHECKS = {
    "metro": {
        "question": "Look at this station camera image. Is a train stopped at the platform with passengers "
                    "getting on or off? Answer yes or no first, then give a short reason.",
        "kinds": {"crowd_surge", "sudden_dispersal"},
        "benign_title": "Crowd surge — likely routine train arrival",
        "benign_note": "train at platform with passengers boarding/alighting",
    },
    "road": {
        "question": "Look at the motorcycle in the center of this image. Is there an obstacle, pedestrian, "
                    "parked or stopped vehicle directly in front of it that it may be avoiding? Answer yes or no "
                    "first, then give a short reason.",
        "kinds": {"lateral_weaving"},
        "benign_title": "Lateral deviation — possible avoidance maneuver",
        "benign_note": "obstacle ahead may explain the lateral motion",
    },
}

DESCRIBE = {
    "metro": "Describe what the people in this station camera image are doing in one short factual sentence. "
             "Do not guess identities, emotions or intentions.",
    "road": "Describe the traffic around the motorcycle in the center of this image in one short factual "
            "sentence. Do not guess the rider's condition.",
}


def second_opinion(inc: Incident, vlm, keyframe_path: str) -> dict | None:
    """Ask the VLM a targeted question; downgrade camera-only incidents it explains away."""
    chk = CHECKS.get(inc.scenario)
    kinds = {s.kind for s in inc.signals}
    sources = {s.source for s in inc.signals}
    if not chk or not (kinds & chk["kinds"]) or sources != {"camera"}:
        return None
    answer = vlm.caption(keyframe_path, chk["question"])
    benign = answer.strip().lower().startswith("yes")
    ts = inc.end_ts.isoformat(timespec="seconds")
    verdict = {"question": chk["question"], "answer": answer, "benign": benign}
    if benign and inc.priority != "low":
        before = inc.priority
        inc.priority = "low"
        inc.title = chk["benign_title"]
        inc.audit.append({"ts": ts, "actor": "vlm", "action": f"second opinion: {chk['benign_note']} — "
                                                              f"priority {before} → low"})
    elif benign:
        inc.title = chk["benign_title"]
        inc.audit.append({"ts": ts, "actor": "vlm", "action": f"second opinion: {chk['benign_note']}"})
    else:
        inc.audit.append({"ts": ts, "actor": "vlm", "action": "second opinion: no benign explanation found"})
    return verdict
