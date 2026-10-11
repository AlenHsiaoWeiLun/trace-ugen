# IncidentLab report X-9e3d2e35

- Workspace: campus  ·  Model: yolo11n.pt  ·  Created: 2026-10-11T02:30:58
- Scope: {"source_ids": ["CAM-P3", "CAM-W1", "CAM-G2", "CAM-P5"], "frames_per_source": 4}  ·  Frames: 16
- Method: Reference = model detections on the clean frame (conf ≥ 0.5). Retention = share of reference boxes re-detected after perturbation (IoU ≥ 0.5, same class, conf ≥ 0.25). Not human ground truth. Occlusion graded on hidden boxes only.

| Perturbation | Level | Mitigation | Retained / reference | Retention | Δ vs baseline | New / frame | ms |
|---|---|---|---|---|---|---|---|
| Motion blur | 2 | Corruption-aware enhancement | 20/23 | 87% | +0% | 0.2 | 42.5 |
| Motion blur | 2 | Higher inference resolution (1280 px) | 19/23 | 83% | -4% | 0.27 | 64.4 |
| Motion blur | 2 | Baseline | 20/23 | 87% |  | 0.2 | 42.3 |
| Motion blur | 2 | Test-time augmentation | 21/23 | 91% | +4% | 0.2 | 100.4 |
| Low light | 2 | Corruption-aware enhancement | 22/23 | 96% | +4% | 0.2 | 41.5 |
| Low light | 2 | Higher inference resolution (1280 px) | 20/23 | 87% | -4% | 0.13 | 63.8 |
| Low light | 2 | Baseline | 21/23 | 91% |  | 0.07 | 42.3 |
| Low light | 2 | Test-time augmentation | 22/23 | 96% | +4% | 0.2 | 99.5 |
| Low resolution | 2 | Corruption-aware enhancement | 22/23 | 96% | +0% | 0.07 | 42.7 |
| Low resolution | 2 | Higher inference resolution (1280 px) | 21/23 | 91% | -4% | 0.2 | 64.6 |
| Low resolution | 2 | Baseline | 22/23 | 96% |  | 0.07 | 41.4 |
| Low resolution | 2 | Test-time augmentation | 22/23 | 96% | +0% | 0.2 | 101.9 |
| Sensor noise | 2 | Corruption-aware enhancement | 22/23 | 96% | +4% | 0.07 | 43.5 |
| Sensor noise | 2 | Higher inference resolution (1280 px) | 18/23 | 78% | -13% | 0.4 | 65.0 |
| Sensor noise | 2 | Baseline | 21/23 | 91% |  | 0.13 | 42.1 |
| Sensor noise | 2 | Test-time augmentation | 22/23 | 96% | +4% | 0.27 | 105.0 |
| Partial occlusion | 2 | Corruption-aware enhancement | 10/12 | 83% | +0% | 0.4 | 41.4 |
| Partial occlusion | 2 | Higher inference resolution (1280 px) | 8/12 | 67% | -17% | 0.5 | 62.9 |
| Partial occlusion | 2 | Baseline | 10/12 | 83% |  | 0.4 | 42.4 |
| Partial occlusion | 2 | Test-time augmentation | 9/12 | 75% | -8% | 0.6 | 101.2 |
| Distance (scale) | 2 | Corruption-aware enhancement | 21/23 | 91% | +0% | 0.13 | 45.1 |
| Distance (scale) | 2 | Higher inference resolution (1280 px) | 22/23 | 96% | +4% | 0.07 | 64.6 |
| Distance (scale) | 2 | Baseline | 21/23 | 91% |  | 0.13 | 46.5 |
| Distance (scale) | 2 | Test-time augmentation | 21/23 | 91% | +0% | 0.4 | 100.7 |
