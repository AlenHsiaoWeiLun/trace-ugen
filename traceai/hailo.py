"""UGen300 (Hailo-10H) backends for speech and vision-language.

All TRACE models share one VDevice (same `group_id`), so the HailoRT scheduler time-slices
the detector, Whisper and the VLM on a single 2.5 W chip. API usage follows Hailo's
official examples in hailo-ai/hailo-apps (`gen_ai_apps/simple_whisper_chat`,
`gen_ai_apps/simple_vlm_chat`). Validated on hardware in Stage II.
"""
from __future__ import annotations

import wave

import numpy as np

GROUP_ID = "TRACE"
_vdevice = None


def shared_vdevice():
    global _vdevice
    if _vdevice is None:
        from hailo_platform import VDevice  # type: ignore

        params = VDevice.create_params()
        params.group_id = GROUP_ID
        _vdevice = VDevice(params)
    return _vdevice


class HailoWhisper:
    """Whisper-Tiny/Base/Small HEF from the Hailo GenAI Model Zoo."""

    def __init__(self, hef_path: str):
        from hailo_platform.genai import Speech2Text  # type: ignore

        self.s2t = Speech2Text(shared_vdevice(), hef_path)

    def transcribe(self, wav_path: str) -> str:
        from hailo_platform.genai import Speech2TextTask  # type: ignore

        with wave.open(wav_path, "rb") as w:
            raw = w.readframes(w.getnframes())
        audio = (np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0).astype("<f4")
        segs = self.s2t.generate_all_segments(audio_data=audio, task=Speech2TextTask.TRANSCRIBE,
                                              language="en", timeout_ms=15000)
        return "".join(s.text for s in segs).strip()


class HailoVLMCaptioner:
    """Qwen2-VL-2B-Instruct HEF; expects 336x336 RGB frames."""

    def __init__(self, hef_path: str):
        from hailo_platform.genai import VLM  # type: ignore

        self.vlm = VLM(shared_vdevice(), hef_path)
        self.model_id = "Qwen2-VL-2B-Instruct (Hailo-10H)"

    def caption(self, image_path: str, prompt: str) -> str:
        import cv2

        img = cv2.cvtColor(cv2.imread(image_path), cv2.COLOR_BGR2RGB)
        h, w = img.shape[:2]
        side = max(h, w)
        sq = np.zeros((side, side, 3), np.uint8)
        sq[(side - h) // 2:(side - h) // 2 + h, (side - w) // 2:(side - w) // 2 + w] = img
        img = cv2.resize(sq, (336, 336), interpolation=cv2.INTER_AREA).astype(np.uint8)
        msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}]
        out = self.vlm.generate_all(prompt=msgs, frames=[img], temperature=0.1, seed=42, max_generated_tokens=60)
        return out.split("<|im_end|>")[0].strip()
