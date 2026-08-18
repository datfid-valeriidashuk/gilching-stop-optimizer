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
