"""Detector backends + host-side tracking.

The split mirrors the target deployment: the *detector* is the only stage that runs on the
accelerator (ASUS UGen300 / Hailo-10H), while tracking, rules and fusion run on the host
CPU. Both backends feed the same ByteTrack implementation, so everything downstream of
`Detector.detect()` is identical on a laptop and on the UGen300.

- `UltralyticsDetector`: PyTorch on CPU / Apple MPS / CUDA. Used for Stage I development.
- `HailoDetector`: HailoRT async API with an NMS-on-chip YOLO HEF from the Hailo Model Zoo.
  Written against the documented HailoRT Python API; validated on hardware in Stage II.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

COCO_NAMES = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


@dataclass
class Detection:
    xyxy: tuple[float, float, float, float]
    conf: float
    cls: int
    track_id: int | None = None

    @property
    def name(self) -> str:
        return COCO_NAMES.get(self.cls, str(self.cls))


class Detector:
    name = "base"

    def detect(self, frame: np.ndarray) -> list[Detection]:  # pragma: no cover - interface
        raise NotImplementedError


class UltralyticsDetector(Detector):
    def __init__(self, weights: str = "yolo11n.pt", device: str | None = None, imgsz: int = 960,
                 conf: float = 0.3, classes: list[int] | None = None):
        from ultralytics import YOLO

        self.model = YOLO(weights)
        self.device = device
        self.imgsz, self.conf, self.classes = imgsz, conf, classes
        self.name = f"{weights.rsplit('/', 1)[-1].removesuffix('.pt')} ({device or 'auto'})"

    def detect(self, frame: np.ndarray) -> list[Detection]:
        r = self.model.predict(frame, imgsz=self.imgsz, conf=self.conf, classes=self.classes,
                               device=self.device, verbose=False)[0]
        b = r.boxes
        return [Detection(tuple(map(float, xyxy)), float(c), int(k))
                for xyxy, c, k in zip(b.xyxy.cpu().numpy(), b.conf.cpu().numpy(), b.cls.cpu().numpy())]


class HailoDetector(Detector):
    """YOLO HEF with on-chip NMS (Hailo Model Zoo `yolov8n`/`yolov8s`, HAILO_NMS_BY_CLASS output).

    Requires `hailort` + its Python wheel (`hailo_platform`) and a compiled `.hef` for the
    Hailo-10H. Frames are letterboxed to the HEF input size on the host.
    """

    def __init__(self, hef_path: str, conf: float = 0.3, classes: list[int] | None = None):
        from hailo_platform import FormatType  # type: ignore

        from .hailo import shared_vdevice

        self.infer_model = shared_vdevice().create_infer_model(hef_path)
        self.infer_model.input().set_format_type(FormatType.UINT8)
        self.infer_model.output().set_format_type(FormatType.FLOAT32)
        self.configured = self.infer_model.configure()
        self.h, self.w = self.infer_model.input().shape[:2]
        self.conf, self.classes = conf, set(classes) if classes else None
        self.name = f"{hef_path.rsplit('/', 1)[-1]} (Hailo-10H)"

    def _letterbox(self, frame: np.ndarray):
        import cv2

        H, W = frame.shape[:2]
        s = min(self.w / W, self.h / H)
        nw, nh = int(W * s), int(H * s)
        canvas = np.full((self.h, self.w, 3), 114, np.uint8)
        dx, dy = (self.w - nw) // 2, (self.h - nh) // 2
        canvas[dy:dy + nh, dx:dx + nw] = cv2.resize(frame, (nw, nh))
        return cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB), s, dx, dy

    def detect(self, frame: np.ndarray) -> list[Detection]:
        img, s, dx, dy = self._letterbox(frame)
        bindings = self.configured.create_bindings()
        bindings.input().set_buffer(np.ascontiguousarray(img))
        out = np.empty(self.infer_model.output().shape, dtype=np.float32)
        bindings.output().set_buffer(out)
        self.configured.run([bindings], 1000)
        per_class = bindings.output().get_buffer()  # list[class] of (N, 5): ymin, xmin, ymax, xmax, score
        dets = []
        for cls, arr in enumerate(per_class):
            if self.classes is not None and cls not in self.classes:
                continue
            for ymin, xmin, ymax, xmax, score in np.asarray(arr).reshape(-1, 5):
                if score < self.conf:
                    continue
                box = ((xmin * self.w - dx) / s, (ymin * self.h - dy) / s,
                       (xmax * self.w - dx) / s, (ymax * self.h - dy) / s)
                dets.append(Detection(box, float(score), cls))
        return dets


class Tracker:
    """ByteTrack (Ultralytics implementation) on the host, fed by any Detector."""

    def __init__(self, frame_rate: float = 30.0):
        from ultralytics.trackers.byte_tracker import BYTETracker
        from ultralytics.utils import IterableSimpleNamespace, YAML
        from ultralytics.utils.checks import check_yaml

        cfg = YAML.load(check_yaml("bytetrack.yaml"))
        cfg["track_buffer"] = max(1, int(round(frame_rate)))  # keep lost tracks ~1 s
        self.bt = BYTETracker(IterableSimpleNamespace(**cfg))

    def update(self, dets: list[Detection], frame: np.ndarray) -> list[Detection]:
        from ultralytics.engine.results import Boxes

        if dets:
            arr = np.array([[*d.xyxy, d.conf, d.cls] for d in dets], dtype=np.float32)
        else:
            arr = np.zeros((0, 6), dtype=np.float32)
        tracks = self.bt.update(Boxes(arr, frame.shape[:2]), frame)
        # rows: x1, y1, x2, y2, track_id, score, cls, idx
        return [Detection((float(t[0]), float(t[1]), float(t[2]), float(t[3])), float(t[5]), int(t[6]), int(t[4]))
                for t in tracks]


def make_detector(backend: str, **kw) -> Detector:
    if backend == "hailo":
        return HailoDetector(kw["hef"], conf=kw.get("conf", 0.3), classes=kw.get("classes"))
    kw.pop("hef", None)
    return UltralyticsDetector(**kw)


class StageTimer:
    """Accumulates per-stage wall time so benchmarks report where the milliseconds go."""

    def __init__(self):
        self.total: dict[str, float] = {}
        self.n: dict[str, int] = {}

    def __call__(self, stage: str):
        timer = self

        class _Ctx:
            def __enter__(self):
                self.t = time.perf_counter()

            def __exit__(self, *exc):
                timer.total[stage] = timer.total.get(stage, 0.0) + time.perf_counter() - self.t
                timer.n[stage] = timer.n.get(stage, 0) + 1

        return _Ctx()

    def report(self) -> dict[str, float]:
        return {k: 1000 * v / self.n[k] for k, v in self.total.items()}
