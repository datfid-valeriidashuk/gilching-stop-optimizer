from __future__ import annotations

import numpy as np

from .scenario import Scenario

UBA_SOURCE = (
    "Umweltbundesamt, Verkehrsemissionsdaten, 2024 passenger-car average: "
    "164 g CO2e per passenger-kilometre, including the energy chain. "
    "https://www.umweltbundesamt.de/themen/verkehr/emissionsdaten"
)


def evaluate_emissions(additional_journeys: np.ndarray, scenario: Scenario, stop_rows: list[dict] | None = None) -> dict:
    """Avoided car emissions if extra bus passengers ride services that already run.

    Bus vehicle-kilometres are unchanged, so marginal bus emissions are zero.
    Average bus emissions per passenger-kilometre are not subtracted.
    """
    scenario.validate()
    delta = np.asarray(additional_journeys, dtype=float)
    gained = np.maximum(delta, 0.0)
    shifted_journeys = gained * float(scenario.car_shift_share)
    avoided_pkm = shifted_journeys * float(scenario.replaced_car_km)
    kg_day = avoided_pkm * float(scenario.car_g_co2e_per_pkm) / 1000.0
    kg_day_total = float(kg_day.sum())
    tonnes_year = kg_day_total * float(scenario.operating_days_per_year) / 1000.0
    shifted_total = float(shifted_journeys.sum())
    vehicle_trips = None
    if scenario.car_occupancy is not None:
        vehicle_trips = shifted_total / float(scenario.car_occupancy)

    per_stop = []
    if stop_rows:
        # Recomputed by the caller from the same exclusive assignment masks.
        per_stop = stop_rows

    return {
        "avoided_car_passenger_km_per_day": float(avoided_pkm.sum()),
        "shifted_passenger_journeys_per_day": shifted_total,
        "car_vehicle_trips_per_day": vehicle_trips,
        "co2e_kg_per_day": kg_day_total,
        "co2e_tonnes_per_year": tonnes_year,
        "kg_day_by_point": kg_day,
        "stops": per_stop,
        "assumptions": {
            "buses_already_operating": True,
            "marginal_bus_emissions": 0.0,
            "bus_average_emissions_subtracted": False,
            "car_shift_share": scenario.car_shift_share,
            "replaced_car_km": scenario.replaced_car_km,
            "operating_days_per_year": scenario.operating_days_per_year,
            "car_g_co2e_per_pkm": scenario.car_g_co2e_per_pkm,
            "car_occupancy": scenario.car_occupancy,
        },
        "source": UBA_SOURCE,
        "limitations": [
            "Valid only while the bus service and its vehicle-kilometres stay the same. A new route or an extra bus is outside this model.",
            "Replaced car kilometres are a scenario average, not a measured Gilching trip length.",
            "The car-shift share is below 100% by default because some new bus journeys may replace walking, cycling, or no journey.",
            "Vehicle-trip counts are omitted unless a car occupancy is supplied.",
        ],
    }


def emissions_for_mask(delta: np.ndarray, mask: np.ndarray, scenario: Scenario) -> dict:
    piece = np.zeros_like(delta, dtype=float)
    piece[mask] = delta[mask]
    result = evaluate_emissions(piece, scenario)
    return {
        "additional_journeys_per_day": float(delta[mask].sum()),
        "co2e_kg_per_day": result["co2e_kg_per_day"],
        "co2e_tonnes_per_year": result["co2e_tonnes_per_year"],
        "avoided_car_passenger_km_per_day": result["avoided_car_passenger_km_per_day"],
    }


def sensitivity(additional_journeys_per_day: float, scenario: Scenario) -> list[dict]:
    """One-at-a-time scenarios around the current assumptions. The journey total stays fixed."""
    base_delta = np.array([additional_journeys_per_day], dtype=float)
    specs = [
        ("car share of new bus journeys", "car_shift_share", [0.25, 0.5, 1.0]),
        ("replaced car km per journey", "replaced_car_km", [4.0, 8.0, 12.0]),
        ("operating days per year", "operating_days_per_year", [200.0, 250.0, 300.0]),
    ]
    rows = []
    for label, field, values in specs:
        for value in values:
            alt = Scenario(**{**scenario.__dict__, field: value})
            emissions = evaluate_emissions(base_delta, alt)
            rows.append({
                "parameter": label,
                "value": value,
                "co2e_kg_per_day": emissions["co2e_kg_per_day"],
                "co2e_tonnes_per_year": emissions["co2e_tonnes_per_year"],
                "is_current": value == getattr(scenario, field),
            })
    return rows
