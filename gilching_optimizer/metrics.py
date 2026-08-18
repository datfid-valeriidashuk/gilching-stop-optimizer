from __future__ import annotations

import numpy as np


def weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    mask = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not np.any(mask):
        return float("nan")
    values = values[mask]
    weights = weights[mask]
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    cumulative = np.cumsum(weights)
    target = q * cumulative[-1]
    idx = np.searchsorted(cumulative, target, side="left")
    return float(values[min(idx, len(values) - 1)])


def summarize_distances(distances_m: np.ndarray, population: np.ndarray) -> dict[str, float]:
    distances_m = np.asarray(distances_m, dtype=float)
    population = np.asarray(population, dtype=float)
    mask = np.isfinite(distances_m) & np.isfinite(population) & (population > 0)
    if not np.any(mask):
        raise ValueError("No finite demand distances are available.")

    d = distances_m[mask]
    w = population[mask]
    total = float(w.sum())
    return {
        "population": total,
        "mean_m": float(np.average(d, weights=w)),
        "median_m": weighted_quantile(d, w, 0.50),
        "p90_m": weighted_quantile(d, w, 0.90),
        "p95_m": weighted_quantile(d, w, 0.95),
        "max_m": float(np.max(d)),
        "within_300_pct": float(100.0 * w[d <= 300].sum() / total),
        "within_500_pct": float(100.0 * w[d <= 500].sum() / total),
        "within_750_pct": float(100.0 * w[d <= 750].sum() / total),
    }
