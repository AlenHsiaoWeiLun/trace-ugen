import numpy as np

from traceai.rules import Obs, trajectory_features


def track(xs, ys, w=40.0):
    return [Obs(t=i / 30, cx=x, cy=y, w=w, h=w * 1.6, cls="motorcycle", conf=0.9, frame=i)
            for i, (x, y) in enumerate(zip(xs, ys))]


def test_straight_track_has_no_swings():
    n = 120
    f = trajectory_features(track(np.full(n, 500.0), np.linspace(900, 200, n)))
    assert f["swings"] == 0 and f["lateral_std_w"] < 0.05


def test_weaving_track_is_detected():
    n = 150
    y = np.linspace(900, 200, n)
    x = 500 + 25 * np.sin(np.linspace(0, 5 * np.pi, n))
    f = trajectory_features(track(x, y))
    assert f["swings"] >= 3 and f["lateral_std_w"] > 0.3


def test_wrong_way_against_flow():
    n = 90
    f = trajectory_features(track(np.full(n, 500.0), np.linspace(200, 900, n)), flow=np.array([0.0, -1.0]))
    assert f["heading_dot_flow"] < -0.9
