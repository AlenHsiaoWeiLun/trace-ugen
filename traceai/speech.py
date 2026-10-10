"""Staff radio reports -> Signals.

Speech is transcribed locally with Whisper (faster-whisper on the laptop; Whisper on the
Hailo-10H in the target build), then mapped to a zone with a site keyword table and scored
by urgency keywords. Audio never leaves the box; only the transcript is stored.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from .schema import Signal

URGENT = {
    "help": 0.15, "running": 0.15, "run": 0.1, "fight": 0.2, "knife": 0.25, "weapon": 0.25,
    "smoke": 0.2, "fire": 0.25, "fell": 0.2, "fallen": 0.2, "collapsed": 0.25, "injured": 0.2,
    "bleeding": 0.25, "screaming": 0.15, "crowd": 0.05, "pushing": 0.15,
}

_model = None


def load_wav16k(path: str):
    """16 kHz mono float32 via ffmpeg (avoids PyAV version coupling)."""
    import subprocess

    import numpy as np

    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def transcribe(path: str, model_size: str = "tiny.en") -> str:
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = _model.transcribe(load_wav16k(path), beam_size=1, language="en", vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()


def to_signal(text: str, sid: str, sensor: str, ts: datetime, zone_keywords: dict[str, str],
              default_zone: str, scenario: str = "metro") -> Signal:
    low = text.lower()
    # The last place mentioned is usually where the event is ("this is platform two,
    # people running toward exit C" -> exit C), not where the speaker stands.
    zone, last = default_zone, -1
    for phrase, z in zone_keywords.items():
        pos = low.rfind(phrase)
        if pos > last:
            zone, last = z, pos
    words = set(re.findall(r"[a-z]+", low))
    hits = sorted(w for w in URGENT if w in words)
    conf = min(0.95, 0.5 + sum(URGENT[w] for w in hits))
    return Signal(id=sid, source="radio", sensor=sensor, zone=zone, ts=ts, kind="staff_report",
                  confidence=round(conf, 3), detail="keywords: " + (", ".join(hits) or "none"),
                  scenario=scenario, transcript=text)


def radio_signal(audio: str, sid: str, sensor: str, t0: datetime, at_s: float, zone_keywords: dict[str, str],
                 default_zone: str, model_size: str = "tiny.en", transcriber=None) -> Signal:
    text = transcriber(audio) if transcriber else transcribe(audio, model_size)
    return to_signal(text, sid, sensor, t0 + timedelta(seconds=at_s), zone_keywords, default_zone)
