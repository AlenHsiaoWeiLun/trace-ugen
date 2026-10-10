from datetime import datetime, timedelta

from traceai.fusion import FusionEngine, ZoneGraph
from traceai.schema import Signal
from traceai.verify import second_opinion

T0 = datetime(2026, 10, 10, 17, 0, 0)
G = ZoneGraph.from_pairs([["A", "B"]])


class FakeVLM:
    def __init__(self, answer):
        self.answer = answer

    def caption(self, path, prompt):
        return self.answer


def sig(i, src, kind, conf, zone="A", sensor=None):
    return Signal(id=f"S{i}", source=src, sensor=sensor or f"{src}-{i}", zone=zone,
                  ts=T0 + timedelta(seconds=i), kind=kind, confidence=conf)


def test_vlm_downgrades_camera_only_surge():
    inc = FusionEngine(G).run([sig(0, "camera", "crowd_surge", 0.9), sig(1, "camera", "crowd_surge", 0.9)])[0]
    assert inc.priority == "medium"  # camera-only evidence is capped below high
    v = second_opinion(inc, FakeVLM("Yes, a train is at the platform."), "kf.jpg")
    assert v["benign"] and inc.priority == "low" and "train" in inc.title
    assert inc.audit[-1]["actor"] == "vlm"


def test_vlm_never_overrides_alarm_or_radio():
    inc = FusionEngine(G).run([sig(0, "camera", "crowd_surge", 0.9), sig(1, "detector", "detector_alarm", 0.8)])[0]
    before = inc.priority
    assert second_opinion(inc, FakeVLM("Yes."), "kf.jpg") is None
    assert inc.priority == before


def test_scene_check_is_not_corroboration():
    base = FusionEngine(G).run([sig(0, "detector", "detector_alarm", 0.75)])[0].score
    with_snap = FusionEngine(G).run([sig(0, "detector", "detector_alarm", 0.75),
                                     sig(1, "camera", "scene_check", 0.35)])[0].score
    assert with_snap - base < 0.02
