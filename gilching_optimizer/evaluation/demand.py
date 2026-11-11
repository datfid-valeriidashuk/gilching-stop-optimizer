from __future__ import annotations

import numpy as np

from .scenario import Scenario

KUEHNEL_SOURCE = (
    "Fabian Kühnel (2025), Entwicklung von Kriterien zur kleinräumigen Bewertung "
    "des ÖPNV-Angebots, RWTH Aachen, model V3, Table 6-1 and Table A-7. "
    "DOI 10.18154/RWTH-2025-08909."
)


def excess_distance_steps(distance_m: np.ndarray, threshold_m: float = 100.0) -> np.ndarray:
    """10 m steps of walking distance beyond the study threshold."""
    d = np.asarray(distance_m, dtype=float)
    return np.maximum(d - threshold_m, 0.0) / 10.0


def log_odds_change(
    distance_old_m: np.ndarray,
    distance_new_m: np.ndarray,
    beta_per_10m: float = -0.004,
    threshold_m: float = 100.0,
) -> np.ndarray:
    """Change in log-odds of choosing public transport when only walk distance changes.

    Service frequency is held fixed, so the model V3 frequency terms are not applied.
    """
    steps_old = excess_distance_steps(distance_old_m, threshold_m)
    steps_new = excess_distance_steps(distance_new_m, threshold_m)
    return beta_per_10m * (steps_new - steps_old)


def odds_ratio(delta_logit: np.ndarray) -> np.ndarray:
    return np.exp(np.asarray(delta_logit, dtype=float))


def probability_after_odds_ratio(p_old: np.ndarray, ratio: np.ndarray) -> np.ndarray:
    """Map an odds ratio back to a probability. Result stays in [0, 1]."""
    p = np.clip(np.asarray(p_old, dtype=float), 0.0, 1.0)
    r = np.asarray(ratio, dtype=float)
    numer = p * r
    denom = 1.0 - p + numer
    out = np.divide(numer, denom, out=np.zeros_like(numer, dtype=float), where=denom != 0)
    return np.clip(out, 0.0, 1.0)


def evaluate_demand(
    population: np.ndarray,
    distance_old_m: np.ndarray,
    distance_new_m: np.ndarray,
    scenario: Scenario,
    assignment: np.ndarray | None = None,
    n_fixed: int = 0,
) -> dict:
    """Population-weighted journey chains per day from the distance coefficient.

    Points with a non-finite before or after distance are excluded. An infinite
    walk is not treated as a very long finite distance.
    """
    scenario.validate()
    n = np.asarray(population, dtype=float)
    d_old = np.asarray(distance_old_m, dtype=float)
    d_new = np.asarray(distance_new_m, dtype=float)
    if n.shape != d_old.shape or n.shape != d_new.shape:
        raise ValueError("population and distances must have the same shape")

    usable = np.isfinite(n) & (n >= 0) & np.isfinite(d_old) & np.isfinite(d_new) & (d_old >= 0) & (d_new >= 0)
    p_old = np.full(n.shape, float(scenario.baseline_probability), dtype=float)
    delta_logit = np.zeros(n.shape, dtype=float)
    ratio = np.ones(n.shape, dtype=float)
    p_new = p_old.copy()
    delta_logit[usable] = log_odds_change(
        d_old[usable], d_new[usable], scenario.beta_per_10m, scenario.distance_threshold_m
    )
    ratio[usable] = odds_ratio(delta_logit[usable])
    p_new[usable] = probability_after_odds_ratio(p_old[usable], ratio[usable])

    q = float(scenario.journeys_per_resident_per_day)
    e_old = np.zeros(n.shape, dtype=float)
    e_new = np.zeros(n.shape, dtype=float)
    e_old[usable] = n[usable] * q * p_old[usable]
    e_new[usable] = n[usable] * q * p_new[usable]
    delta = e_new - e_old

    long = usable & ((d_old > scenario.long_walk_flag_m) | (d_new > scenario.long_walk_flag_m))
    e_old_total = float(e_old.sum())
    e_new_total = float(e_new.sum())
    delta_total = float(delta.sum())
    relative = None if e_old_total == 0 else delta_total / e_old_total

    bands = _bands(d_old, delta, usable)
    stops = _attribute_stops(delta, assignment, n_fixed, usable) if assignment is not None else []

    return {
        "journeys_per_day_before": e_old_total,
        "journeys_per_day_after": e_new_total,
        "additional_journeys_per_day": delta_total,
        "relative_change": relative,
        "residents_included": float(n[usable].sum()),
        "demand_points_included": int(usable.sum()),
        "demand_points_excluded_unreachable": int((~usable & np.isfinite(n) & (n > 0)).sum()),
        "residents_on_long_walks": float(n[long].sum()),
        "delta_by_point": delta,
        "bands": bands,
        "stops": stops,
        "limitations": [
            "Baseline probability is an illustrative scenario, not a measured Gilching modal split.",
            "One probability is applied to every residential demand point. No zone or demographic split is loaded.",
            "School and music-school weights are destination demand for stop placement. They are not residents and are excluded here.",
            "Service frequency is assumed unchanged, so model V3 frequency coefficients are not applied.",
            "Published coefficients come from an observational mode-choice model. Using them as a counterfactual for a new stop is an extrapolation.",
            (
                f"Walks longer than {scenario.long_walk_flag_m:.0f} m are flagged. "
                "That threshold is a project caution, not a range published in Table 6-1."
            ),
        ],
    }


def _bands(d_old: np.ndarray, delta: np.ndarray, usable: np.ndarray) -> list[dict]:
    edges = [0, 100, 300, 500, 750, 1500, np.inf]
    labels = ["0–100 m", "100–300 m", "300–500 m", "500–750 m", "750–1500 m", "over 1500 m"]
    rows = []
    for i, label in enumerate(labels):
        mask = usable & (d_old >= edges[i]) & (d_old < edges[i + 1])
        rows.append({
            "walking_distance_before": label,
            "additional_journeys_per_day": float(delta[mask].sum()),
            "demand_points": int(mask.sum()),
        })
    return rows


def _attribute_stops(delta: np.ndarray, assignment: np.ndarray, n_fixed: int, usable: np.ndarray) -> list[dict]:
    """Give each resident's journey change to exactly one nearest stop.

    Fixed stops are stacked first. A resident whose nearest stop is still an
    existing one keeps a zero change when the new network is a superset, so
    their change is not also given to a new stop.
    """
    assignment = np.asarray(assignment)
    if assignment.shape != delta.shape:
        raise ValueError("assignment must align with demand points")
    n_stops = int(assignment[usable].max()) + 1 if usable.any() else n_fixed
    rows = []
    for stop in range(n_stops):
        mask = usable & (assignment == stop)
        rows.append({
            "stop_index": stop,
            "role": "existing" if stop < n_fixed else "new",
            "new_index": None if stop < n_fixed else stop - n_fixed,
            "additional_journeys_per_day": float(delta[mask].sum()),
        })
    return rows
