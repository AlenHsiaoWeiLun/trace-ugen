# VESTIGE — feature status (2026-10-11)

Legend: **TESTED** implemented and covered by automated tests or a reproduced run · **IMPLEMENTED**
works in the app, not covered by tests · **PARTIAL** works with stated limits · **BLOCKED** cannot be
done without hardware/credentials · **PLANNED** designed, not built.

| Area | Feature | Status | Evidence |
|---|---|---|---|
| Perception | YOLO11n + ByteTrack on video sources | TESTED | `vestige.scenarios` build; tracks in DB |
| Perception | Tracklet stitching | IMPLEMENTED | measured: CAM-G2 4 → 2 tracks |
| Perception | Track-level colour signature | IMPLEMENTED | same bike 0.57–0.59, other bike 0.11–0.17 |
| Perception | Privacy masking of stored frames + proxy video | IMPLEMENTED | visual check |
| Perception | HailoRT detector / Whisper / VLM backends | BLOCKED | needs UGen300 (Stage II) |
| Memory | SQLite World Memory with provenance + evidence states | TESTED | `tests/test_vestige.py` |
| Memory | Object history (recorded → observed → inferred → unknown) | TESTED | `test_object_history_states_and_order` |
| Memory | Cross-camera association (topology + travel + colour) | TESTED | `test_inferred_links_respect_travel_window_and_colour` |
| Memory | Coverage gaps (route beyond last camera; staged outage) | TESTED | `test_missing_recording_is_reported_not_filled` |
| Memory | User check-in stored as RECORDED, not observed | TESTED | `test_checkin_is_recorded_not_observed` |
| Investigate | Tool planner + cited answers | TESTED | `test_answer_citations_resolve_to_stored_evidence` |
| Investigate | No timestamps outside the store | TESTED | `test_answer_contains_no_unstored_timestamps` |
| Investigate | Event-scoped questions | TESTED | `test_ask_endpoint_and_event_scoped_question` |
| Investigate | Optional local LLM intent classifier | IMPLEMENTED | `VESTIGE_LLM=qwen`; not in tests (model load) |
| Investigate | Cloud LLM tool-calling planner | PLANNED | deterministic planner covers the demo |
| Investigate | Human review (confirm / uncertain / reject) + audit | TESTED | `test_review_is_audited` |
| Scenarios | Campus bicycle disappearance | TESTED | object history test |
| Scenarios | Metro incident investigation (TRACE replay) | TESTED | gap + timestamp tests |
| Scenarios | Construction worker–vehicle proximity | IMPLEMENTED | image-space only; COCO "truck" for machinery |
| Scenarios | Construction machinery-specific model | PLANNED | needs site data (pilot under discussion with WanZe) |
| IncidentLab | 6 perturbations × 3 levels, seeded | TESTED | `tests/test_incidentlab.py` |
| IncidentLab | Retention metric, occlusion graded on hidden boxes | TESTED | unit tests |
| IncidentLab | Mitigations: enhance / hires / TTA / larger model | IMPLEMENTED | `results/incidentlab_*.md` |
| IncidentLab | Experiment history, before/after images, report export | IMPLEMENTED | UI + `/report.md` |
| IncidentLab | Temporal (track-memory) recovery under occlusion | PLANNED | — |
| Sources | Upload with authorization gate → background ingestion job → ask | TESTED | `test_upload_requires_authorization`, `test_upload_ingest_ask_flow` |
| Sources | Live RTSP cameras | PLANNED | file sources only |
| Security | Workspace isolation (403) on API, media files and IncidentLab scopes | TESTED | `test_workspace_isolation_*`, `test_cross_workspace_ids_are_rejected`, `test_media_is_served_through_workspace_guard` |
| Security | Authentication / multi-user roles | PARTIAL | single demo user with an allow-list |
| TRACE | Alarm/radio/camera fusion, alert-storm benchmark | TESTED | `tests/test_fusion.py`, alert storm reproduced 2026-10-11 |
| Hardware | Measurements on ASUS UGen300 | BLOCKED | hardware arrives in Stage II |

## Measured numbers and where they come from

| Number | Type | Source |
|---|---|---|
| Road occlusion retention 33 % → 62 % (YOLO11s) | public-video evaluation | `results/incidentlab_bench-road_X-dae2cec5.md` |
| Road blur 56 % → 89 %, noise 56 % → 92 % (TTA) | public-video evaluation | same |
| Low-light enhancement −11 pp | public-video evaluation | same |
| 409 → 9.4 high cards/h, 99 % recall | synthetic benchmark | `results/alert_storm_w30.json` |
| 29 % road occlusion (Phase 1 pilot) | public-video evaluation, earlier frame sample | `results/incidentlab_pilot.json`; re-run gives 33 % on 24 frames |
| YOLOv11n 302 FPS / v11s 142 FPS on Hailo-10H | vendor-published | Hailo Model Zoo v5.4 |
| Query latency 1.6–3 ms | measured, laptop | `/api/metrics` |

## Known limitations

- Appearance association uses colour only: two bicycles of the same colour on adjacent cameras would be
  linked as *candidates*; the UI and answers say "not a confirmed identity".
- Using YOLO11s for ingestion (the best model under stress in IncidentLab) changed box geometry enough to drop the
  campus cross-camera colour similarity from 0.59 to 0.46, so links were rejected. Making the comparison hue-shift
  tolerant raises same-bike similarity (0.46 → 0.66) but also different-bike similarity (0.16 → 0.43); re-picking the
  threshold on these few demo clips would be overfitting, so the demo stays on YOLO11n. Stage II: an appearance
  signature validated on held-out footage.
- Proximity is image-space (body-heights) from uncalibrated cameras; no metric distance or TTC is claimed.
- The detector is COCO-trained: construction machinery is detected as "truck"; rollers/excavators can be missed.
- Demo timestamps are assigned to stock clips; the scenarios are reconstructions, not real incidents.
- Stage I deadline 2026-10-14 17:00 still requires the demo video (YouTube, unlisted).
- Retention period is stored and displayed per workspace but not yet enforced (no automatic expiry job).

## Independent review (Codex gpt-5.5, read-only, 2026-10-11)

| Finding | Severity | Resolution |
|---|---|---|
| `/media` served as unguarded static files | high | replaced by a route that resolves the owning workspace and applies the same guard; traversal-safe |
| IncidentLab scope ids not checked against the workspace | high | `lab_scope_guard` → 403 / 404 |
| IncidentLab `model` / `mitigations` not whitelisted | high | allow-lists → 400 |
| Check-in could attach to another workspace's object | medium | 403 |
| `/ask` `event_id` from another workspace silently fell back | medium | 404 / 403 |
| "every claim cites evidence" overstated (records/gaps are uncited) | medium | wording changed in README, UI and deck sources |
| Isolation status overstated | medium | covered by two new tests |
| Retention shown as "active policy" | low | labelled display-only |
