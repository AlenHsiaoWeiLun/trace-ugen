"""Evidence rendering: keyframes and short clips with privacy masking.

Every frame that leaves the pipeline has the head region of each detected person blurred
(an upper slice of the person box) before it is written to disk. Raw video is never stored
by TRACE; only these short, masked evidence clips attached to an incident.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np

TEAL = (196, 214, 61)
ORANGE = (74, 160, 245)


def mask_people(frame: np.ndarray, boxes: list[tuple[float, float, float, float]]) -> np.ndarray:
    out = frame
    H, W = frame.shape[:2]
    for x1, y1, x2, y2 in boxes:
        h = y2 - y1
        hx1, hy1 = int(max(0, x1)), int(max(0, y1))
        hx2, hy2 = int(min(W, x2)), int(min(H, y1 + 0.22 * h))
        if hx2 - hx1 < 2 or hy2 - hy1 < 2:
            continue
        roi = out[hy1:hy2, hx1:hx2]
        k = max(3, (min(roi.shape[:2]) // 2) | 1)
        out[hy1:hy2, hx1:hx2] = cv2.GaussianBlur(roi, (k, k), 0)
    return out


def draw(frame: np.ndarray, dets, highlight_ids: set[int] | None = None, label: str | None = None,
         trails: dict[int, list[tuple[float, float]]] | None = None) -> np.ndarray:
    highlight_ids = highlight_ids or set()
    for d in dets:
        x1, y1, x2, y2 = map(int, d.xyxy)
        hot = d.track_id in highlight_ids
        color = ORANGE if hot else TEAL
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3 if hot else 1, cv2.LINE_AA)
        if hot or d.name != "person":
            cv2.putText(frame, f"{d.name} #{d.track_id}", (x1, max(14, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, color, 1, cv2.LINE_AA)
    for tid, pts in (trails or {}).items():
        if len(pts) > 1:
            cv2.polylines(frame, [np.array(pts, np.int32)], False,
                          ORANGE if tid in highlight_ids else TEAL, 2 if tid in highlight_ids else 1, cv2.LINE_AA)
    if label:
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        cv2.rectangle(frame, (12, 12), (28 + tw, 24 + th + 8), (32, 24, 11), -1)
        cv2.putText(frame, label, (20, 20 + th), cv2.FONT_HERSHEY_SIMPLEX, 0.7, TEAL, 2, cv2.LINE_AA)
    return frame


class ClipWriter:
    """Writes frames to a temporary MJPG AVI, then transcodes to browser-friendly H.264."""

    def __init__(self, path: Path, fps: float, size: tuple[int, int]):
        self.path = Path(path)
        self.tmp = self.path.with_suffix(".tmp.avi")
        self.w = cv2.VideoWriter(str(self.tmp), cv2.VideoWriter_fourcc(*"MJPG"), fps, size)

    def write(self, frame: np.ndarray) -> None:
        self.w.write(frame)

    def close(self) -> None:
        self.w.release()
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(self.tmp), "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-crf", "26", "-preset", "veryfast", "-movflags", "+faststart",
                        "-vf", "scale='min(1280,iw)':-2", str(self.path)], check=True)
        self.tmp.unlink(missing_ok=True)
