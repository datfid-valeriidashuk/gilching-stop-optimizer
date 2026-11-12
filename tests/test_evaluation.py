import math

import numpy as np
import pytest

from gilching_optimizer.evaluation.demand import (
    evaluate_demand,
    log_odds_change,
    odds_ratio,
    probability_after_odds_ratio,
)
from gilching_optimizer.evaluation.electoral import afd_association_pp, electoral_context, scenario_access_index
from gilching_optimizer.evaluation.emissions import evaluate_emissions
from gilching_optimizer.evaluation.scenario import Scenario


def test_kuehnel_validation_example():
    d_old = np.array([600.0])
    d_new = np.array([200.0])
    delta = log_odds_change(d_old, d_new)
    ratio = float(odds_ratio(delta)[0])
    assert math.isclose(ratio, 1.1735108709918103, rel_tol=1e-12)
    p_new = float(probability_after_odds_ratio(np.array([0.10]), np.array([ratio]))[0])
    assert math.isclose(p_new, 0.115349, rel_tol=1e-4)
    scenario = Scenario(baseline_probability=0.10, journeys_per_resident_per_day=2.0)
    result = evaluate_demand(np.array([1000.0]), d_old, d_new, scenario)
    assert math.isclose(result["additional_journeys_per_day"], 30.698, rel_tol=1e-3)


def test_distance_at_or_below_100m_does_not_change_odds():
    delta = log_odds_change(np.array([50.0, 100.0]), np.array([80.0, 40.0]))
    assert np.allclose(delta, 0.0)


def test_shorter_walk_raises_probability():
    p_old = np.array([0.10])
    ratio = odds_ratio(log_odds_change(np.array([800.0]), np.array([150.0])))
    p_new = probability_after_odds_ratio(p_old, ratio)
    assert float(p_new[0]) > 0.10


def test_probabilities_stay_inside_unit_interval():
    p = probability_after_odds_ratio(
        np.array([0.0, 1.0, 0.10, 0.10]),
        np.array([3.0, 0.2, 0.0, 50.0]),
    )
    assert np.all(p >= 0.0) and np.all(p <= 1.0)
    assert p[0] == 0.0
    assert p[1] == 1.0


def test_unchanged_network_has_zero_change():
    d = np.array([120.0, 640.0, 90.0])
    result = evaluate_demand(np.array([10.0, 20.0, 5.0]), d, d, Scenario())
    assert result["additional_journeys_per_day"] == 0.0
    assert result["journeys_per_day_before"] == result["journeys_per_day_after"]


def test_population_weights_scale_the_total():
    small = evaluate_demand(np.array([1000.0]), np.array([600.0]), np.array([200.0]), Scenario())
    large = evaluate_demand(np.array([2000.0]), np.array([600.0]), np.array([200.0]), Scenario())
    assert math.isclose(large["additional_journeys_per_day"], 2 * small["additional_journeys_per_day"])


def test_multiple_stops_do_not_double_count():
    population = np.array([100.0, 100.0, 100.0])
    d_old = np.array([600.0, 600.0, 400.0])
    d_new = np.array([200.0, 300.0, 400.0])
    # Stop 0 is existing. Stops 1 and 2 are new. Each resident is assigned once.
    assignment = np.array([1, 2, 0])
    result = evaluate_demand(population, d_old, d_new, Scenario(), assignment=assignment, n_fixed=1)
    attributed = sum(row["additional_journeys_per_day"] for row in result["stops"])
    assert math.isclose(attributed, result["additional_journeys_per_day"])
    assert result["stops"][0]["role"] == "existing"
    assert result["stops"][1]["role"] == "new"


def test_fixed_service_co2e_example():
    scenario = Scenario(car_shift_share=1.0, replaced_car_km=8.0, operating_days_per_year=250, car_g_co2e_per_pkm=164)
    result = evaluate_emissions(np.array([30.7]), scenario)
    assert math.isclose(result["co2e_kg_per_day"], 30.7 * 8 * 0.164, rel_tol=1e-12)
    assert math.isclose(result["co2e_tonnes_per_year"], 30.7 * 8 * 0.164 * 250 / 1000, rel_tol=1e-12)
    assert result["assumptions"]["marginal_bus_emissions"] == 0.0
    assert result["car_vehicle_trips_per_day"] is None


def test_southern_afd_association_and_missing_index():
    assert math.isclose(afd_association_pp(5.0, 4.5, "south"), 1.20 * (4.5 - 5.0))
    assert math.isclose(afd_association_pp(5.0, 4.5, "east"), 1.51 * (4.5 - 5.0))
    assert afd_association_pp(5.0, 4.5, "north") is None
    assert afd_association_pp(None, 4.5, "south") is None
    card = electoral_context("south", 5.0, 4.5)
    assert card["causal"] is False
    assert card["die_linke"]["associated_percentage_points"] is None
    assert card["die_linke"]["statistically_significant_in_multivariate_model"] is False
    assert card["bsw"]["associated_percentage_points"] is None
    assert card["afd"]["associated_percentage_points"] == pytest.approx(-0.60)
    assert electoral_context("south")["afd"]["associated_percentage_points"] is None


def test_access_index_is_filled_from_existing_then_combined_stops():
    assert scenario_access_index(np.array([1000.0]), np.array([200.0])) == 1
    assert scenario_access_index(np.array([1000.0]), np.array([2500.0])) == 7
    assert scenario_access_index(np.array([1000.0]), np.array([np.inf])) == 7
    mixed = scenario_access_index(np.array([1000.0, 3000.0]), np.array([200.0, 2500.0]))
    assert mixed == pytest.approx((1 * 1000 + 7 * 3000) / 4000)
    old = scenario_access_index(np.array([1000.0, 1000.0]), np.array([2000.0, 2000.0]))
    new = scenario_access_index(np.array([1000.0, 1000.0]), np.array([200.0, 200.0]))
    assert old == 6
    assert new == 1
    assert afd_association_pp(old, new, "south") == pytest.approx(1.20 * (new - old))
