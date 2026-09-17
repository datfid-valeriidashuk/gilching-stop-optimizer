import numpy as np
from gilching_optimizer.optimizer import optimize_p_median


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
