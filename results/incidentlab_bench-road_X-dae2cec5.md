# IncidentLab report X-dae2cec5

- Workspace: bench-road  ·  Model: yolo11n.pt  ·  Created: 2026-10-11T02:32:32
- Scope: {"source_ids": ["BENCH-ROAD-1", "BENCH-ROAD-2", "BENCH-ROAD-3"], "frames_per_source": 8}  ·  Frames: 24
- Method: Reference = model detections on the clean frame (conf ≥ 0.5). Retention = share of reference boxes re-detected after perturbation (IoU ≥ 0.5, same class, conf ≥ 0.25). Not human ground truth. Occlusion graded on hidden boxes only.

| Perturbation | Level | Mitigation | Retained / reference | Retention | Δ vs baseline | New / frame | ms |
|---|---|---|---|---|---|---|---|
| Motion blur | 2 | Corruption-aware enhancement | 51/98 | 52% | -4% | 0.04 | 47.9 |
| Motion blur | 2 | Higher inference resolution (1280 px) | 43/98 | 44% | -12% | 0.08 | 76.8 |
| Motion blur | 2 | Larger model (YOLO11s) | 87/98 | 89% | +33% | 0.42 | 74.9 |
| Motion blur | 2 | Baseline | 55/98 | 56% |  | 0.08 | 50.3 |
| Motion blur | 2 | Test-time augmentation | 68/98 | 69% | +13% | 0.5 | 112.4 |
| Low light | 2 | Corruption-aware enhancement | 77/98 | 79% | -11% | 0.17 | 47.0 |
| Low light | 2 | Higher inference resolution (1280 px) | 69/98 | 70% | -19% | 0.21 | 75.9 |
| Low light | 2 | Larger model (YOLO11s) | 96/98 | 98% | +8% | 1.04 | 77.6 |
| Low light | 2 | Baseline | 88/98 | 90% |  | 0.08 | 47.1 |
| Low light | 2 | Test-time augmentation | 93/98 | 95% | +5% | 0.5 | 111.6 |
| Sensor noise | 2 | Corruption-aware enhancement | 58/98 | 59% | +3% | 0.0 | 49.2 |
| Sensor noise | 2 | Higher inference resolution (1280 px) | 34/98 | 35% | -21% | 0.12 | 73.0 |
| Sensor noise | 2 | Larger model (YOLO11s) | 86/98 | 88% | +32% | 1.0 | 77.0 |
| Sensor noise | 2 | Baseline | 55/98 | 56% |  | 0.17 | 46.6 |
| Sensor noise | 2 | Test-time augmentation | 90/98 | 92% | +36% | 0.38 | 111.4 |
| Partial occlusion | 2 | Corruption-aware enhancement | 19/58 | 33% | +0% | 0.17 | 45.9 |
| Partial occlusion | 2 | Higher inference resolution (1280 px) | 23/58 | 40% | +7% | 0.91 | 73.0 |
| Partial occlusion | 2 | Larger model (YOLO11s) | 36/58 | 62% | +29% | 2.52 | 75.4 |
| Partial occlusion | 2 | Baseline | 19/58 | 33% |  | 0.17 | 45.8 |
| Partial occlusion | 2 | Test-time augmentation | 22/58 | 38% | +5% | 0.52 | 108.8 |
