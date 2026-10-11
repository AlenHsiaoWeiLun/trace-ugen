"""First-run failures must be actionable and leave an existing memory intact."""
import json

import pytest

from vestige import db, scenarios


@pytest.fixture
def demo_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "ROOT", tmp_path)
    names = {s["media"] for spec in (scenarios.CAMPUS, scenarios.CONSTRUCTION) for s in spec["sources"]}
    names.update(media for _, _, media, _ in scenarios.BENCHMARK)
    for name in names:
        p = tmp_path / "data/videos" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"fixture video")
    (tmp_path / "data/run_metro.json").write_text(json.dumps({"incidents": [
        {"keyframe": "/media/metro/frame.jpg", "signals": []}
    ]}))
    frame = tmp_path / "media/metro/frame.jpg"
    frame.parent.mkdir(parents=True)
    frame.write_bytes(b"fixture frame")
    monkeypatch.setattr(scenarios.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    return tmp_path


@pytest.mark.parametrize("missing", ["data/videos/pexels_8405570.mp4", "data/videos/pexels_28795446.mp4",
                                      "data/videos/bridge_07.webm", "media/metro/frame.jpg"])
def test_missing_input_never_resets_memory(demo_inputs, monkeypatch, missing):
    (demo_inputs / missing).unlink()
    monkeypatch.setattr(db, "reset", lambda: pytest.fail("database reset before input validation"))
    with pytest.raises(FileNotFoundError, match=missing):
        scenarios.build()


def test_missing_ffmpeg_is_actionable(demo_inputs, monkeypatch):
    monkeypatch.setattr(scenarios.shutil, "which", lambda _: None)
    monkeypatch.setattr(db, "reset", lambda: pytest.fail("database reset without ffmpeg"))
    with pytest.raises(RuntimeError, match="ffmpeg"):
        scenarios.build()


def test_all_demo_inputs_pass_preflight(demo_inputs):
    scenarios.preflight()
