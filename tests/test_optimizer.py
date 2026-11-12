import numpy as np
from gilching_optimizer.optimizer import optimize_p_median, optimize_stops


def test_p1_exact_candidate():
    m = np.array([
        [0, 10, 20],
        [10, 0, 10],
        [20, 10, 0],
    ], dtype=float)
    w = np.array([1, 5, 1], dtype=float)
    r = optimize_p_median(m, w, 1)
    assert r.selected == [1]


def test_p2_improves_p1():
    m = np.array([
        [0, 10, 20],
        [10, 0, 10],
        [20, 10, 0],
    ], dtype=float)
    w = np.ones(3)
    r1 = optimize_p_median(m, w, 1)
    r2 = optimize_p_median(m, w, 2)
    assert r2.objective_mean_m <= r1.objective_mean_m


def test_fixed_baseline_absorbs_nearby_demand():
    # Demand 0 is already perfectly served by a fixed stop (baseline 0).
    # The optimizer should cover the remaining mass at column 2, not column 0.
    m = np.array([
        [0.0, 50.0, 80.0],
        [50.0, 40.0, 5.0],
        [80.0, 45.0, 0.0],
    ], dtype=float)
    w = np.array([10.0, 1.0, 1.0])
    baseline = np.array([0.0, 100.0, 100.0])
    r = optimize_p_median(m, w, 1, baseline=baseline)
    assert r.selected == [2]
    assert r.objective_mean_m < 10.0


def test_fixed_baseline_p2_does_not_reselect_served_cluster():
    m = np.array([
        [0.0, 50.0, 80.0, 90.0],
        [50.0, 40.0, 5.0, 70.0],
        [80.0, 45.0, 0.0, 60.0],
        [90.0, 70.0, 60.0, 0.0],
    ], dtype=float)
    w = np.array([10.0, 1.0, 1.0, 8.0])
    baseline = np.array([0.0, 100.0, 100.0, 100.0])
    r = optimize_p_median(m, w, 2, baseline=baseline)
    assert 0 not in r.selected
    assert set(r.selected) == {2, 3}


def test_cover400_prefers_full_coverage_over_a_short_average():
    # Column 0 leaves the third resident outside 400 m and has the better average.
    # Column 1 puts everyone inside 400 m.
    m = np.array([
        [10.0, 390.0],
        [10.0, 390.0],
        [500.0, 390.0],
    ])
    w = np.array([5.0, 5.0, 1.0])
    mean = optimize_stops(m, w, 1, objective="mean")
    cover = optimize_stops(m, w, 1, objective="cover400")
    assert mean.selected == [0]
    assert cover.selected == [1]
    assert cover.objective_value == 0.0


def test_percentiles_and_minimax_pick_different_stops():
    # Column 0 has the best median and a long tail.
    # Column 1 has the best 80% walk and one resident much farther out.
    # Column 2 has the shortest longest walk.
    m = np.array([
        [10.0, 100.0, 400.0],
        [10.0, 100.0, 400.0],
        [10.0, 100.0, 400.0],
        [2000.0, 100.0, 400.0],
        [2000.0, 1500.0, 400.0],
    ])
    w = np.ones(5)
    assert optimize_stops(m, w, 1, objective="p50").selected == [0]
    assert optimize_stops(m, w, 1, objective="p80").selected == [1]
    assert optimize_stops(m, w, 1, objective="minimax").selected == [2]
