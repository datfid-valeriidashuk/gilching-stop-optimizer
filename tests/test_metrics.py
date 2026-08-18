import numpy as np
from gilching_optimizer.metrics import summarize_distances


def test_weighted_mean_and_coverage():
    d = np.array([100.0, 500.0, 900.0])
    w = np.array([1.0, 2.0, 1.0])
    s = summarize_distances(d, w)
    assert abs(s["mean_m"] - 500.0) < 1e-9
    assert abs(s["within_500_pct"] - 75.0) < 1e-9
