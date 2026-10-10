"""Operator-facing incident summaries.

The default summariser is deterministic: it only restates measured facts (which sensor,
where, when, what was measured) and suggests the next review step. Optionally a small
vision-language model adds a one-sentence scene description of the keyframe; on the
UGen300 this is Qwen2-VL-2B from the Hailo GenAI model zoo, on a laptop SmolVLM.
The VLM sentence is always labelled as a model description, never as a finding.
"""
from __future__ import annotations

from .schema import Incident

KIND_TEXT = {
    "crowd_surge": "crowd density surge",
    "sudden_dispersal": "several people running at once",
    "person_down": "person lying on the floor",
    "detector_alarm": "fixed detector alarm",
    "scene_check": "camera snapshot at alarm time",
    "staff_report": "staff radio report",
    "lateral_weaving": "repeated lateral deviation",
    "wrong_way": "movement against traffic flow",
    "speed_outlier": "speed far above surrounding traffic",
}


def _phrase(s) -> str:
    if s.kind == "detector_alarm":
        return f"{s.detail[:1].upper() + s.detail[1:]} at {s.sensor} (zone {s.zone}) [{s.id}]"
    if s.kind == "staff_report":
        return f'a staff radio call on {s.sensor} reported: "{s.transcript}" [{s.id}]'
    if s.kind in ("crowd_surge", "sudden_dispersal", "person_down"):
        return f"{s.sensor} measured a {KIND_TEXT[s.kind]} in zone {s.zone}, {s.detail} [{s.id}]"
    if s.kind in ("lateral_weaving", "wrong_way", "speed_outlier"):
        return f"{s.sensor} flagged {KIND_TEXT[s.kind]}: {s.detail} [{s.id}]"
    return f"{s.sensor} (zone {s.zone}): {s.detail} [{s.id}]"


def template_summary(inc: Incident) -> str:
    """Plain-English summary built only from measured facts; every clause cites its signal."""
    sig = sorted(inc.signals, key=lambda s: s.ts)
    t0 = sig[0].ts
    main = [s for s in sig if s.kind != "scene_check"]
    snaps = [s for s in sig if s.kind == "scene_check"]
    parts = []
    for i, s in enumerate(main):
        dt = (s.ts - t0).total_seconds()
        p = _phrase(s)
        if i == 0:
            parts.append(p[:1].upper() + p[1:])
        else:
            parts.append((f"{dt:.0f} s later, " if dt >= 1 else "at the same time, ") + p)
    text = "; ".join(parts) + "."
    if snaps:
        counts = ", ".join(f"{s.detail.split(' people')[0]} at {s.sensor} [{s.id}]" for s in snaps[:3])
        text += f" Camera snapshots at alarm time show people counts of {counts}."
    if inc.scenario == "road":
        text += " The system does not infer the cause (impairment, distraction or avoidance)."
    return text


class VLMCaptioner:
    """Small VLM keyframe captioner (HuggingFace transformers)."""

    def __init__(self, model_id: str | None = None, device: str | None = None, size: int = 336):
        from pathlib import Path

        import torch

        local = Path(__file__).resolve().parent.parent / "models" / "qwen2-vl-2b"
        model_id = model_id or (str(local) if (local / "config.json").exists() else "Qwen/Qwen2-VL-2B-Instruct")
        from transformers import AutoModelForImageTextToText, AutoProcessor

        self.device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
        self.processor = AutoProcessor.from_pretrained(model_id)
        dtype = torch.float16 if self.device != "cpu" else torch.float32
        self.model = AutoModelForImageTextToText.from_pretrained(model_id, dtype=dtype).to(self.device)
        self.model_id = "Qwen2-VL-2B-Instruct" if model_id == str(local) else model_id
        # Same 336x336 input as the Qwen2-VL-2B HEF on the Hailo-10H, so laptop and UGen300 see the same pixels.
        self.size = size

    def chat(self, prompt: str, max_new_tokens: int = 120) -> str:
        """Text-only generation with the same model (used by "Ask the station")."""
        msgs = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        text = self.processor.apply_chat_template(msgs, add_generation_prompt=True)
        inputs = self.processor(text=text, return_tensors="pt").to(self.device)
        out = self.model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        return self.processor.batch_decode(out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()

    def caption(self, image_path: str, prompt: str) -> str:
        from PIL import Image

        msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}]
        text = self.processor.apply_chat_template(msgs, add_generation_prompt=True)
        # Letterbox (keep aspect) to the HEF's square input instead of squashing the frame.
        src = Image.open(image_path).convert("RGB")
        side = max(src.size)
        img = Image.new("RGB", (side, side))
        img.paste(src, ((side - src.size[0]) // 2, (side - src.size[1]) // 2))
        img = img.resize((self.size, self.size))
        inputs = self.processor(text=text, images=[img], return_tensors="pt").to(self.device)
        out = self.model.generate(**inputs, max_new_tokens=60, do_sample=False)
        ans = self.processor.batch_decode(out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0]
        return ans.strip().split("\n")[0].strip()

