from datetime import datetime, timedelta
from itertools import count

from traceai.fusion import FusionEngine, ZoneGraph, pairwise_f1
from traceai.schema import Signal

T0 = datetime(2026, 10, 10, 17, 36, 0)
_ids = count(1)


def sig(sec, zone, sensor="CAM-1", source="camera", kind="crowd_surge", conf=0.7):
    return Signal(id=f"S{next(_ids)}", source=source, sensor=sensor, zone=zone,
                  ts=T0 + timedelta(seconds=sec), kind=kind, confidence=conf)


GRAPH = ZoneGraph.from_pairs([["A", "B"], ["B", "C"], ["C", "D"]])


def test_adjacent_zones_close_in_time_fuse():
    incs = FusionEngine(GRAPH).run([sig(0, "B", conf=0.8), sig(4, "C", "CAM-2", conf=0.8),
                                  sig(9, "C", "RADIO-1", "radio", "staff_report", 0.8)])
    assert len(incs) == 1
    assert incs[0].title == "Possible multi-zone disturbance"
    assert incs[0].priority == "high"


def test_distant_zones_stay_separate():
    incs = FusionEngine(GRAPH).run([sig(0, "A"), sig(2, "D", "CAM-2")])
    assert len(incs) == 2


def test_time_gap_splits():
    incs = FusionEngine(GRAPH, window_s=30).run([sig(0, "B"), sig(45, "B")])
    assert len(incs) == 2


def test_bridge_signal_merges_incidents():
    incs = FusionEngine(GRAPH, max_hops=1).run([sig(0, "A"), sig(1, "C", "CAM-3"), sig(2, "B", "CAM-2")])
    assert len(incs) == 1 and len(incs[0].signals) == 3


def test_chattering_sensor_does_not_inflate_score():
    one = FusionEngine(GRAPH).run([sig(i, "B", conf=0.5) for i in range(10)])[0]
    two = FusionEngine(GRAPH).run([sig(0, "B", conf=0.5), sig(1, "B", "DET-1", "detector", "detector_alarm", 0.5)])[0]
    assert one.score < two.score


def test_pairwise_f1_perfect():
    m = pairwise_f1({"a": "1", "b": "1", "c": "2"}, {"a": "x", "b": "x", "c": ""})
    assert m["f1"] == 1.0
