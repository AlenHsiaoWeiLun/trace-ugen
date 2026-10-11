import numpy as np

from vestige import incidentlab as L


def test_match_and_retention_are_exact():
    ref = [(0, 0, 10, 10, 0.9, 0), (20, 20, 30, 30, 0.9, 0)]
    pred = [(0, 0, 10, 10, 0.8, 0), (50, 50, 60, 60, 0.7, 0)]
    kept, new = L.match(ref, pred)
    assert kept == [0] and new == [1]


def test_perturbations_are_seeded_and_scale_moves_boxes():
    img = np.full((100, 200, 3), 128, np.uint8)
    ref = [(50, 20, 150, 80, 0.9, 0)]
    a, _, _ = L.perturb(img, "noise", 2, ref, np.random.default_rng(1))
    b, _, _ = L.perturb(img, "noise", 2, ref, np.random.default_rng(1))
    assert (a == b).all()
    _, boxes, _ = L.perturb(img, "scale", 2, ref, np.random.default_rng(1))
    assert boxes[0][2] - boxes[0][0] == 50


def test_occlusion_grades_only_hidden_boxes():
    img = np.full((100, 200, 3), 128, np.uint8)
    ref = [(10, 10, 60, 90, 0.9, 0)] * 20
    out, _, hidden = L.perturb(img, "occlusion", 2, ref, np.random.default_rng(3))
    assert 0 < len(hidden) < 20
    assert (out != img).any()


def test_summary_marks_mitigation_deltas():
    agg = {("blur", 2, "none"): [5, 10, 1, 40.0, 2], ("blur", 2, "large"): [8, 10, 2, 70.0, 2]}
    s = L.summarize(agg, 2)
    big = next(c for c in s["cells"] if c["mitigation"] == "large")
    assert big["delta"] == 0.3 and s["best_mitigation"]["blur:2"]["mitigation"] == "large"
