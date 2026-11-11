from __future__ import annotations

import numpy as np

from .demand import KUEHNEL_SOURCE, evaluate_demand
from .electoral import electoral_context, scenario_access_index
from .emissions import UBA_SOURCE, emissions_for_mask, evaluate_emissions, sensitivity
from .scenario import Scenario


def _sensitivity(population, distance_old_m, distance_new_m, scenario: Scenario, demand: dict) -> list[dict]:
    rows = []
    for label, field, values in (
        ("baseline bus probability", "baseline_probability", (0.05, 0.10, 0.20)),
        ("journeys per resident per day", "journeys_per_resident_per_day", (1.0, 2.0, 3.0)),
    ):
        for value in values:
            alt = Scenario(**{**scenario.__dict__, field: value})
            alt_demand = evaluate_demand(population, distance_old_m, distance_new_m, alt)
            alt_emissions = evaluate_emissions(alt_demand["delta_by_point"], alt)
            rows.append({
                "parameter": label,
                "value": value,
                "additional_journeys_per_day": alt_demand["additional_journeys_per_day"],
                "co2e_tonnes_per_year": alt_emissions["co2e_tonnes_per_year"],
                "is_current": value == getattr(scenario, field),
            })
    for row in sensitivity(demand["additional_journeys_per_day"], scenario):
        row["additional_journeys_per_day"] = demand["additional_journeys_per_day"]
        rows.append(row)
    return rows


def evaluation_report(
    population: np.ndarray,
    distance_old_m: np.ndarray | None,
    distance_new_m: np.ndarray,
    assignment: np.ndarray,
    n_fixed: int,
    scenario: Scenario,
    demand_ids: list[str] | None = None,
) -> dict:
    if distance_old_m is None:
        electoral = electoral_context(scenario.region)
    else:
        electoral = electoral_context(
            scenario.region,
            scenario_access_index(population, distance_old_m),
            scenario_access_index(population, distance_new_m),
            from_walking=True,
        )
    if distance_old_m is None:
        return {
            "available": False,
            "reason": (
                "Place at least one existing stop. Those stops are the current network. "
                "The new stops are compared with that baseline on the walking network."
            ),
            "electoral": electoral,
        }

    demand = evaluate_demand(
        population, distance_old_m, distance_new_m, scenario, assignment=assignment, n_fixed=n_fixed
    )
    emissions = evaluate_emissions(demand["delta_by_point"], scenario)
    usable = np.isfinite(distance_old_m) & np.isfinite(distance_new_m)
    stop_impacts = []
    for row in demand["stops"]:
        mask = usable & (np.asarray(assignment) == row["stop_index"])
        impact = emissions_for_mask(demand["delta_by_point"], mask, scenario)
        impact.update({
            "stop_index": row["stop_index"],
            "role": row["role"],
            "new_index": row["new_index"],
        })
        stop_impacts.append(impact)

    point_delta = {}
    if demand_ids is not None:
        delta = demand["delta_by_point"]
        d_old = np.asarray(distance_old_m, dtype=float)
        d_new = np.asarray(distance_new_m, dtype=float)
        for i, did in enumerate(demand_ids):
            if not usable[i]:
                continue
            point_delta[str(did)] = {
                "distance_old_m": float(d_old[i]),
                "distance_new_m": float(d_new[i]),
                "additional_journeys_per_day": float(delta[i]),
            }

    new_stop_impacts = [s for s in stop_impacts if s["role"] == "new"]
    return {
        "available": True,
        "demand": {
            "journeys_per_day_before": demand["journeys_per_day_before"],
            "journeys_per_day_after": demand["journeys_per_day_after"],
            "additional_journeys_per_day": demand["additional_journeys_per_day"],
            "relative_change": demand["relative_change"],
            "unit": "expected public-transport journey chains per day",
            "residents_included": demand["residents_included"],
            "demand_points_excluded_unreachable": demand["demand_points_excluded_unreachable"],
            "residents_on_long_walks": demand["residents_on_long_walks"],
            "bands": demand["bands"],
            "source": KUEHNEL_SOURCE,
            "limitations": demand["limitations"],
        },
        "emissions": {
            "avoided_car_passenger_km_per_day": emissions["avoided_car_passenger_km_per_day"],
            "shifted_passenger_journeys_per_day": emissions["shifted_passenger_journeys_per_day"],
            "car_vehicle_trips_per_day": emissions["car_vehicle_trips_per_day"],
            "co2e_kg_per_day": emissions["co2e_kg_per_day"],
            "co2e_tonnes_per_year": emissions["co2e_tonnes_per_year"],
            "assumptions": emissions["assumptions"],
            "source": UBA_SOURCE,
            "limitations": emissions["limitations"],
            "sensitivity": _sensitivity(population, distance_old_m, distance_new_m, scenario, demand),
        },
        "stops": new_stop_impacts,
        "points": point_delta,
        "electoral": electoral,
        "parameters": {
            "baseline_probability": scenario.baseline_probability,
            "journeys_per_resident_per_day": scenario.journeys_per_resident_per_day,
            "car_shift_share": scenario.car_shift_share,
            "replaced_car_km": scenario.replaced_car_km,
            "operating_days_per_year": scenario.operating_days_per_year,
            "car_g_co2e_per_pkm": scenario.car_g_co2e_per_pkm,
            "beta_per_10m": scenario.beta_per_10m,
            "region": scenario.region,
        },
    }
