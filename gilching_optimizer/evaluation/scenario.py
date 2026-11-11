from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    """Illustrative parameters. None of the defaults is a measured Gilching value."""

    baseline_probability: float = 0.10
    journeys_per_resident_per_day: float = 2.0
    car_shift_share: float = 0.5
    replaced_car_km: float = 8.0
    operating_days_per_year: float = 250.0
    car_g_co2e_per_pkm: float = 164.0
    beta_per_10m: float = -0.004
    distance_threshold_m: float = 100.0
    # Project caution, not a cutoff published in Kühnel Table 6-1.
    long_walk_flag_m: float = 1500.0
    region: str = "south"
    quality_index_old: float | None = None
    quality_index_new: float | None = None
    # Passengers per car. Left unset so vehicle-trip counts are not invented.
    car_occupancy: float | None = None

    def validate(self) -> None:
        if not 0.0 <= self.baseline_probability <= 1.0:
            raise ValueError("baseline_probability must be between 0 and 1")
        if self.journeys_per_resident_per_day < 0:
            raise ValueError("journeys_per_resident_per_day must be >= 0")
        if not 0.0 <= self.car_shift_share <= 1.0:
            raise ValueError("car_shift_share must be between 0 and 1")
        if self.replaced_car_km < 0:
            raise ValueError("replaced_car_km must be >= 0")
        if self.operating_days_per_year <= 0:
            raise ValueError("operating_days_per_year must be > 0")
        if self.car_g_co2e_per_pkm < 0:
            raise ValueError("car_g_co2e_per_pkm must be >= 0")
        if self.distance_threshold_m < 0 or self.long_walk_flag_m <= 0:
            raise ValueError("distance thresholds must be non-negative")
        if self.car_occupancy is not None and self.car_occupancy <= 0:
            raise ValueError("car_occupancy must be > 0 when set")
        if self.region not in {"south", "east"}:
            raise ValueError("region must be 'south' or 'east'")
        for q in (self.quality_index_old, self.quality_index_new):
            if q is not None and not 1.0 <= q <= 7.0:
                raise ValueError("quality index must be between 1 and 7")
