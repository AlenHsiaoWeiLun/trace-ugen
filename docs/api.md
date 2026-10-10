# TRACE console API

The FastAPI server (`traceai/server.py`) serves the operator console from `web/` and the
following JSON endpoints. All timestamps are ISO-8601 strings in local time.

## `GET /api/incidents?scenario=metro|road&status=pending|confirmed|dismissed|escalated`

Returns a list of incident summaries, newest first:

```json
[
  {
    "id": "INC-0007",
    "scenario": "metro",
    "title": "Possible multi-zone disturbance",
    "status": "pending",
    "priority": "high",
    "score": 0.86,
    "start_ts": "2026-10-10T17:36:08",
    "end_ts": "2026-10-10T17:36:41",
    "zones": ["B", "C"],
    "sensors": ["CAM-03", "CAM-07", "RADIO-1"],
    "n_signals": 5,
    "keyframe": "/media/metro/INC-0007.jpg"
  }
]
```

## `GET /api/incidents/{id}`

Full incident:

```json
{
  "id": "INC-0007",
  "scenario": "metro",
  "title": "Possible multi-zone disturbance",
  "status": "pending",
  "priority": "high",
  "score": 0.86,
  "start_ts": "...", "end_ts": "...",
  "zones": ["B", "C"],
  "sensors": ["CAM-03", "CAM-07", "RADIO-1"],
  "summary": "Crowd density in zone B rose 3.1x within 6 s, followed by rapid dispersal toward zone C. A staff radio report 9 s later mentions ...",
  "keyframe": "/media/metro/INC-0007.jpg",
  "clip": "/media/metro/INC-0007.mp4",
  "signals": [
    {
      "id": "SIG-0031",
      "source": "camera",
      "sensor": "CAM-03",
      "zone": "B",
      "ts": "2026-10-10T17:36:08",
      "kind": "crowd_surge",
      "confidence": 0.81,
      "detail": "people count 6 -> 19 in 6.0 s",
      "thumb": "/media/metro/SIG-0031.jpg",
      "transcript": null
    },
    {
      "id": "SIG-0034",
      "source": "radio",
      "sensor": "RADIO-1",
      "zone": "C",
      "ts": "2026-10-10T17:36:17",
      "kind": "staff_report",
      "confidence": 0.9,
      "detail": "keywords: crowd, running, platform two",
      "thumb": null,
      "transcript": "Control, this is platform two, people are running toward exit C."
    }
  ],
  "features": {"weaving_index": 2.4, "lateral_std_px": 31.0},
  "review": {"decision": null, "reviewer": null, "note": null, "ts": null},
  "audit": [{"ts": "...", "actor": "system", "action": "incident created from 3 signals"}],
  "latency_ms": 812
}
```

`source` is one of `camera | detector | radio`. `features` is optional (road incidents
carry trajectory features). `clip`, `thumb`, `transcript` may be null.

## `POST /api/incidents/{id}/review`

Body: `{"decision": "confirmed|dismissed|escalated", "note": "free text", "reviewer": "operator-1"}`.
Returns the updated full incident (status set to the decision, review filled, audit appended).

## `GET /api/stats`

```json
{
  "signals_total": 57,
  "incidents_total": 9,
  "alert_reduction": 0.84,
  "by_status": {"pending": 6, "confirmed": 2, "dismissed": 1, "escalated": 0},
  "by_scenario": {"metro": 5, "road": 4},
  "pipeline": {"device": "cpu (Apple M4 Pro)", "detector": "yolo11n", "fps": 31.5,
               "asr": "whisper tiny.en", "target": "ASUS UGen300 / Hailo-10H"}
}
```

## `GET /api/site?scenario=metro|road`

Schematic layout used for the mini-map:

```json
{
  "name": "Demo Station",
  "zones": [{"id": "A", "name": "Concourse", "x": 0.05, "y": 0.1, "w": 0.4, "h": 0.35, "cameras": ["CAM-01"]}],
  "adjacency": [["A", "B"]]
}
```

Coordinates are fractions of the map box (0–1).

## Static

- `/media/...` serves evidence (jpg keyframes, mp4 clips).
- `/` serves `web/index.html`.

## Additions (v2)

Full incident objects also carry:

```json
{
  "summary": "... +0s DET-B2 (zone B): fixed detector alarm — platform emergency intercom pressed [SIG-M0002]; ...",
  "sop": ["Open the linked camera clips ...", "Call back the reporting staff member ..."],
  "vlm": {
    "model": "Qwen2-VL-2B-Instruct",
    "description": "Passengers are walking along the platform next to a stopped train.",
    "second_opinion": {"question": "...", "answer": "Yes, a train is stopped ...", "benign": true},
    "ms": 2140
  }
}
```

- `summary` contains signal citations in square brackets (`[SIG-M0002]`); render them as chips that
  scroll to / highlight the matching timeline row.
- `vlm` may be null. `second_opinion` may be null (only asked for camera-only incidents). When
  `benign` is true the audit log contains a `vlm` entry describing the downgrade.
- `signals[].kind` may be `scene_check`: a camera snapshot pulled automatically when a non-visual
  alarm fired (context, not corroboration) — show it with a camera icon and a "snapshot" tag.

`GET /api/stats` → `pipeline` also has:
`"stage_ms": {"detect": 46.2, "track": 0.6, "rules": 0.2, "asr": 1722, "fusion": 0.3, "vlm": 2100}`,
`"frames_off_box": 0`, `"retention_h": 24`.

## `POST /api/ask`

Body `{"question": "Anything near exit C in the last 10 minutes?"}` →

```json
{"answer": "Yes — at 17:36:15 RADIO-1 reported people running toward exit C [SIG-M0003], part of [INC-M-0001].",
 "citations": ["INC-M-0001", "SIG-M0003"], "model": "Qwen2-VL-2B-Instruct", "ms": 1830}
```
