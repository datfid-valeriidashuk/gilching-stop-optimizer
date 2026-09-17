from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class OptimizationResult:
    selected: list[int]
    objective_mean_m: float


def _weighted_mean(nearest: np.ndarray, weights: np.ndarray) -> float:
    return float(np.sum(nearest * weights) / np.sum(weights))


def _best_addition(
    matrix: np.ndarray,
    weights: np.ndarray,
    current: np.ndarray | None,
    excluded: set[int],
    batch_size: int = 256,
) -> tuple[int, np.ndarray, float]:
    n_candidates = matrix.shape[1]
    best_j = -1
    best_obj = np.inf
    best_nearest: np.ndarray | None = None

    for start in range(0, n_candidates, batch_size):
        end = min(n_candidates, start + batch_size)
        block = np.asarray(matrix[:, start:end], dtype=np.float64)
        if current is None:
            nearest_block = block
        else:
            nearest_block = np.minimum(current[:, None], block)
        objs = (nearest_block * weights[:, None]).sum(axis=0) / weights.sum()
        for j in excluded:
            if start <= j < end:
                objs[j - start] = np.inf
        local = int(np.argmin(objs))
        obj = float(objs[local])
        if obj < best_obj:
            best_obj = obj
            best_j = start + local
            best_nearest = nearest_block[:, local].copy()

    if best_j < 0 or best_nearest is None:
        raise RuntimeError("Could not find a candidate facility.")
    return best_j, best_nearest, best_obj


def optimize_p_median(
    matrix: np.ndarray,
    weights: np.ndarray,
    p: int,
    local_search_rounds: int = 4,
    batch_size: int = 256,
    baseline: np.ndarray | None = None,
) -> OptimizationResult:
    """Greedy construction followed by 1-swap local search.

    p=1 is exact over the supplied candidate set. p>1 is a fast near-optimal
    heuristic over the supplied candidates.

    If `baseline` is given (length = demand points), it is the current best
    distance from already-fixed facilities. New stops are chosen to improve
    that baseline, not to replace the fixed stops.
    """
    if p < 1:
        raise ValueError("p must be at least 1")
    if p > matrix.shape[1]:
        raise ValueError("p exceeds the number of candidates")

    weights = np.asarray(weights, dtype=np.float64)
    if weights.ndim != 1 or weights.shape[0] != matrix.shape[0]:
        raise ValueError("weights must match the number of demand points")
    if baseline is not None:
        baseline = np.asarray(baseline, dtype=np.float64)
        if baseline.shape != (matrix.shape[0],):
            raise ValueError("baseline must match the number of demand points")

    selected: list[int] = []
    nearest: np.ndarray | None = None if baseline is None else baseline.copy()
    for _ in range(p):
        j, nearest, _ = _best_addition(
            matrix, weights, nearest, set(selected), batch_size=batch_size
        )
        selected.append(j)

    if p == 1:
        return OptimizationResult(selected, _weighted_mean(nearest, weights))

    for _round in range(local_search_rounds):
        improved = False
        for position in range(p):
            others = [j for k, j in enumerate(selected) if k != position]
            if others:
                base = np.min(np.asarray(matrix[:, others], dtype=np.float64), axis=1)
                if baseline is not None:
                    base = np.minimum(base, baseline)
            else:
                base = None if baseline is None else baseline
            excluded = set(others)
            candidate, candidate_nearest, candidate_obj = _best_addition(
                matrix, weights, base, excluded, batch_size=batch_size
            )
            current_nearest = np.min(
                np.asarray(matrix[:, selected], dtype=np.float64), axis=1
            )
            if baseline is not None:
                current_nearest = np.minimum(current_nearest, baseline)
            current_obj = _weighted_mean(current_nearest, weights)
            if candidate_obj + 1e-9 < current_obj and candidate not in others:
                selected[position] = candidate
                nearest = candidate_nearest
                improved = True
        if not improved:
            break

    nearest = np.min(np.asarray(matrix[:, selected], dtype=np.float64), axis=1)
    if baseline is not None:
        nearest = np.minimum(nearest, baseline)
    return OptimizationResult(selected, _weighted_mean(nearest, weights))


def load_distance_matrix(path: str | Path, shape: tuple[int, int]) -> np.memmap:
    return np.memmap(path, dtype="float32", mode="r", shape=shape)
