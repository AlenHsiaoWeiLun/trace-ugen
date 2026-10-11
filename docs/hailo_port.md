# Hailo port plan

Audience: ASUS/Hailo engineering review. **Not verified on UGen300** means code-inspected or published, not locally measured.

## Target

TRACE targets ASUS UGen300 accelerators with Hailo-10H and 8 GB memory, in USB and M.2 form factors. Runtime: HailoRT 5.x plus `hailo_platform` on an x86 or ARM host such as an ASUS NUC, laptop, or Raspberry Pi 5. The host keeps tracking, rules, fusion, evidence, audit logs, and console; UGen300 runs continuous detection and event-driven GenAI.

## Model inventory

Published performance is for Hailo-10H/PCIe. USB UGen300 performance is **not verified on hardware**.

| Role | Model | Source | Input | When it runs | Published perf |
|---|---|---|---|---|---:|
| Object detection | YOLOv11n HEF, NMS on chip | Hailo Model Zoo v5.x for HAILO10H | HEF-defined RGB letterbox | Every processed frame | 302 FPS on PCIe |
| Object detection | YOLOv8s HEF, NMS on chip | Hailo Model Zoo v5.x for HAILO10H | HEF-defined RGB letterbox | Every processed frame | 166 FPS on PCIe |
| Radio ASR | Whisper-Base | Hailo GenAI Model Zoo | 16 kHz mono audio | On voice activity / radio clip | 25.3 tok/s |
| Incident VLM | Qwen2-VL-2B-Instruct | Hailo GenAI Model Zoo | 336x336 RGB keyframe | Per fused incident | 7.0 tok/s, TTFT 1.02 s |
| Event-log Q&A | Qwen2.5-1.5B-Instruct | Hailo GenAI Model Zoo | Text event log | On operator question | 7.35 tok/s, TTFT 0.37 s |

## Code mapping to HailoRT

`traceai/hailo.py` creates one shared `VDevice` with `params.group_id = "TRACE"` for detector, Whisper, VLM, and future LLM scheduling.

`traceai/perception.py:HailoDetector`:

| Step | Code behavior |
|---|---|
| Load HEF | `shared_vdevice().create_infer_model(hef_path)` |
| Configure | input `UINT8`, output `FLOAT32`; `infer_model.configure()` once |
| Preprocess | Host letterbox to HEF input, fill 114, resize, BGR to RGB |
| Bindings | `create_bindings()`, set input, allocate output |
| Run | `configured.run([bindings], 1000)` |
| Parse | NMS-by-class `(N,5)` buffers as `ymin,xmin,ymax,xmax,score`; undo letterbox |

GenAI is implemented in `traceai/hailo.py`:

| Model | Code path |
|---|---|
| Whisper | `hailo_platform.genai.Speech2Text(shared_vdevice(), hef_path)` and `generate_all_segments(...)` |
| Qwen2-VL | `hailo_platform.genai.VLM(shared_vdevice(), hef_path)` and `generate_all(...)` |

For VLM, `HailoVLMCaptioner.caption()` converts the privacy-masked, overlay-free keyframe BGR to RGB, letterboxes it to `336x336`, and sends one image plus one targeted prompt. `traceai/verify.py` calls VLM only after fusion; it may downgrade camera-only incidents but cannot override alarms or radio.

The VESTIGE agent (`vestige/agent.py`) composes answers only from memory lookups. Planned Hailo path: Qwen2.5-1.5B-Instruct through the same VDevice; current code accepts injected `.chat()`/`.model_id`.

## Scheduling budget

Current configs process cameras at `process_fps: 15`. For 8 cameras:

| Item | Budget |
|---|---:|
| Camera streams | 8 |
| Processed FPS per camera | 15 |
| Detector requests | 120 inferences/s |
| Compared with YOLOv11n published PCIe capacity | 120 / 302 = ~40% |

This leaves headroom for host tracking/rules and bursty GenAI if USB and scheduler overhead do not dominate; **not verified on UGen300 USB**.

Scheduling policy:

| Load | Behavior |
|---|---|
| Normal | Detection continuous; Whisper on radio; VLM after fusion; Q&A on explicit question |
| VLM duty cycle | Low: one keyframe per incident, short yes/no plus factual description |
| Contention | Detection has operational priority; VLM/Q&A requests are queued; static cameras can reduce `process_fps` first |
| Sustained overload | Drop static or low-priority cameras below 15 FPS before disabling detector streams |

## Config switch

UGen300 detector and ASR use YAML:

```yaml
detector:
  backend: hailo
  hef: models/yolov11n_h10.hef
  conf: 0.3
  process_fps: 15

asr:
  backend: hailo
  hef: models/Whisper-Base.hef
```

VLM is selected at runtime:

```bash
python scripts/run_pipeline.py configs/metro_demo.yaml \
  --vlm-hef models/Qwen2-VL-2B-Instruct.hef
```

Laptop path mirrors deployment: `UltralyticsDetector` replaces `HailoDetector`, `VLMCaptioner` replaces `HailoVLMCaptioner`, but tracking, fusion, evidence, prompts, and `336x336` VLM keyframes stay in host code.

## Stage II measurement plan

Add `scripts/bench_hailo.py` for real USB and M.2 UGen300 hardware. Planned metrics:

| Metric | Method |
|---|---|
| USB FPS by stream count | Replay 1/2/4/8 videos at 15 FPS target; report achieved FPS, p50/p95 latency, drops |
| End-to-end alarm latency | Time from signal creation to incident JSON/card with keyframe and summary |
| VLM TTFT/tok/s | Fixed keyframes/prompts through Qwen2-VL; report TTFT, tok/s, wall time |
| ASR latency/tok/s | Fixed radio clips through Whisper-Base; report audio duration vs wall time |
| Power | Inline USB-C power meter during idle, detector-only, detector+ASR, detector+VLM |
| Thermal | Log device temperature if exposed; otherwise sustained-run notes |

The script should accept `--hef-det`, `--hef-whisper`, `--hef-vlm`, `--streams`, `--duration-s`, `--transport {usb,m2}` and write JSON/CSV under `results/hailo/`.

## Known risks and mitigations

| Risk | Mitigation |
|---|---|
| USB bandwidth and latency may be below PCIe published figures | Measure USB first; keep M.2 path as reference; reduce static camera FPS before changing models |
| Model switching overhead under one scheduler group | Keep detector resident; make Whisper/VLM event-driven; queue VLM/Q&A behind detection |
| 8 GB memory across detector, Whisper, VLM, and LLM HEFs | Validate resident-set behavior; if needed, keep detector+Whisper resident and lazy-load VLM/LLM |
| Four HEFs may not fit simultaneously | Stage by scenario: detector always loaded, GenAI loaded by feature flag; benchmark load/unload cost |
| Mandarin radio may underperform with Whisper-Base English-oriented setup | Move to Whisper-Small or multilingual HEF; update language setting and urgency keywords |
| NMS output layout can differ by HEF export | Keep NMS-by-class parser covered by hardware sample dumps before demo |
