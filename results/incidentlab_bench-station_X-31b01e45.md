# IncidentLab report X-31b01e45

- Workspace: bench-station  ·  Model: yolo11n.pt  ·  Created: 2026-10-11T02:33:33
- Scope: {"source_ids": ["BENCH-STATION-1", "BENCH-STATION-2"], "frames_per_source": 8}  ·  Frames: 16
- Method: Reference = model detections on the clean frame (conf ≥ 0.5). Retention = share of reference boxes re-detected after perturbation (IoU ≥ 0.5, same class, conf ≥ 0.25). Not human ground truth. Occlusion graded on hidden boxes only.

| Perturbation | Level | Mitigation | Retained / reference | Retention | Δ vs baseline | New / frame | ms |
|---|---|---|---|---|---|---|---|
| Motion blur | 2 | Corruption-aware enhancement | 140/151 | 93% | +1% | 0.94 | 42.5 |
| Motion blur | 2 | Higher inference resolution (1280 px) | 143/151 | 95% | +3% | 1.75 | 71.8 |
| Motion blur | 2 | Larger model (YOLO11s) | 143/151 | 95% | +3% | 1.31 | 73.1 |
| Motion blur | 2 | Baseline | 138/151 | 91% |  | 0.88 | 44.2 |
| Motion blur | 2 | Test-time augmentation | 144/151 | 95% | +4% | 0.94 | 117.4 |
| Low light | 2 | Corruption-aware enhancement | 141/151 | 93% | +1% | 0.44 | 44.2 |
| Low light | 2 | Higher inference resolution (1280 px) | 144/151 | 95% | +3% | 1.25 | 67.9 |
| Low light | 2 | Larger model (YOLO11s) | 143/151 | 95% | +2% | 1.44 | 68.9 |
| Low light | 2 | Baseline | 140/151 | 93% |  | 0.19 | 45.5 |
| Low light | 2 | Test-time augmentation | 145/151 | 96% | +3% | 0.44 | 104.6 |
| Sensor noise | 2 | Corruption-aware enhancement | 143/151 | 95% | -1% | 0.62 | 45.0 |
| Sensor noise | 2 | Higher inference resolution (1280 px) | 145/151 | 96% | +0% | 1.12 | 72.2 |
| Sensor noise | 2 | Larger model (YOLO11s) | 146/151 | 97% | +1% | 1.69 | 69.9 |
| Sensor noise | 2 | Baseline | 145/151 | 96% |  | 0.5 | 43.4 |
| Sensor noise | 2 | Test-time augmentation | 149/151 | 99% | +3% | 0.94 | 105.0 |
| Partial occlusion | 2 | Corruption-aware enhancement | 59/82 | 72% | +0% | 1.69 | 42.8 |
| Partial occlusion | 2 | Higher inference resolution (1280 px) | 58/82 | 71% | -1% | 3.38 | 68.6 |
| Partial occlusion | 2 | Larger model (YOLO11s) | 60/82 | 73% | +1% | 3.62 | 69.4 |
| Partial occlusion | 2 | Baseline | 59/82 | 72% |  | 1.69 | 42.7 |
| Partial occlusion | 2 | Test-time augmentation | 58/82 | 71% | -1% | 2.94 | 101.9 |
