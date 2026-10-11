# Reproducing VESTIGE

## Environment and scope

The current implementation is a local Python/FastAPI service with a Preact UI served as ES modules.
Use Python 3.11+ and FFmpeg. The review run used Python 3.13 on macOS and existing YOLO weights; CPU operation
is supported by the detector but is slower. Neither Windows-native setup nor UGen300 has been validated here.

Install with the [README quickstart](../README.md). `requirements.txt` includes FastAPI's multipart upload
parser and HTTPX for API tests. No Node tooling is needed to run the application.

## Data preparation

```bash
bash scripts/download_media.sh
python -m vestige
```

The script downloads 11 Pexels videos and two Wikimedia videos. Credits and per-file names are in
[ATTRIBUTION.md](../ATTRIBUTION.md). The campus scenario needs four bicycle clips, construction needs two site
clips, and the lab has road/station sources. If a download is blocked, save the corresponding video manually
under its listed name; do not substitute unrelated footage while claiming to reproduce these results.

`python -m vestige` builds memory if `data/vestige.db` does not exist. It runs detection/tracking for campus and
construction; metro imports the committed TRACE replay in `data/run_metro.json` and `media/metro/`.
It does **not** re-run the metro speech/VLM pipeline during this import.

Before resetting memory, the builder checks scenario videos, saved metro replay assets and FFmpeg. A missing
input produces its path and leaves an existing database intact. Completed downloads are reused and failed
transfers do not become final filenames.

`python -m vestige --rebuild` deliberately replaces local demo state, including user check-ins, reviews and
lab history. Back up the database first if those records matter. Source footage stays under `data/videos/`;
generated evidence/proxy video is under `media/vestige/`. Neither is needed in source control.

The build registers lab sources but does not pre-populate experiments. To reproduce a stored report, run a
new experiment in More → Detection lab; the report shown in the README records a previous run.

## IncidentLab benchmark

1. Open **More → Detection lab → New test → Benchmark → Taipei Bridge scooters**.
2. Select **8 frames per camera**, four stresses (motion blur, low light, sensor noise, partial occlusion),
   and **level 2** for each.
3. Select all fixes: baseline, enhancement, higher resolution, test-time augmentation, larger model.
4. Run, wait for the background job, inspect the comparison and use **Full results and method → Download report**.

The [road report](../results/incidentlab_bench-road_X-dae2cec5.md) has 24 frames, 98 clean-frame reference boxes
and 58 hidden boxes for the occlusion subset. Reference threshold is 0.5; the perturbed-match threshold is 0.25;
matching requires the same class and IoU ≥ 0.5. Retention is not recall against human annotations. “New” boxes
are not automatically true positives. Exact latency varies with device, model version and load.

The [station report](../results/incidentlab_bench-station_X-31b01e45.md) is a separate workspace and should not
be pooled with the road results.

## TRACE fusion experiment

```bash
python scripts/simulate_alert_storm.py --seeds 20 --window 30 --hops 1 --out /tmp/vestige-alert-storm.json
```

Compare the aggregate fields with [the recorded 30-second run](../results/alert_storm_w30.json).
This simulation generates nuisance signals and labeled synthetic incidents. Its high-priority-card reduction
and incident recall describe that simulator, not a labeled real CCTV incident benchmark.

To regenerate the earlier metro perception replay rather than import it:

```bash
python scripts/run_pipeline.py configs/metro_demo.yaml
```

This overwrites `data/run_metro.json` and derived metro assets. Add `--vlm` only after separately preparing the
local Qwen2-VL model; the default VESTIGE walkthrough does not need it.

## Tests and API

```bash
python -m pytest -q tests
```

Build the demo before testing so the end-to-end database checks run. API tests copy the database; the upload
flow writes and then cleans temporary files in the local checkout. Run tests against a disposable local demo,
not during a live demonstration. Missing footage can cause the upload test to skip; inspect the summary.

Current VESTIGE API: [endpoint guide](vestige_api.md), or `/docs` on the running service for generated OpenAPI.

## Hardware boundary

The laptop detector downloads YOLO weights on first use if absent. Optional local intent classification uses
`VESTIGE_LLM=qwen` and `models/qwen2-vl-2b`; it has not been exercised by the default test suite.
HailoRT/HEF setup is separate: see [the port plan](hailo_port.md). Vendor PCIe figures are not evidence of
USB throughput, shared-model scheduling, end-to-end latency or power on this application.

## Verification on 2026-10-11

- Before cleanup, **39 tests passed**, including actual upload → ingestion → cited-answer checks and six new preflight tests.
  The retired console and its three Q&A tests were then removed; **37 current tests passed** after cleanup and integration of the latest site-routing test.
- A fresh temporary database was built from the available footage/weights: 5 workspaces, 16 sources,
  23 tracks, 63 observations, 7 events, 38 evidence items and 1 stored gap. This used an existing Python
  environment and local model/media files; it was not a fresh internet-only dependency installation.
- The 20-seed synthetic fusion run reproduced all aggregate fields of the committed 30-second report.
- Browser checks covered home → answer → cited video playback → inferred evidence details → object memory,
  event review/audit and a new IncidentLab experiment (12 frames, low light, baseline versus enhancement).
- Desktop and 390 × 844 mobile views were inspected before the latest single-page UI integration.
  Those obsolete captures were removed; the README uses the current [product screenshot set](screenshots/).
- After retiring the console, browser checks confirmed construction alert questions, the extracted object-route
  map and evidence video playback still work; no browser console errors were observed.
- UGen300 hardware, optional local Qwen intent classification and a final YouTube submission URL remain unverified.
