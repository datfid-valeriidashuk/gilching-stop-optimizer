import numpy as np
from gilching_optimizer.institutions import load_institutions, stack_institution_demand
from gilching_optimizer.optimizer import optimize_p_median


def test_load_gilching_schools():
    records = load_institutions()
    by_id = {r["id"]: r for r in records}
    assert set(by_id) == {
        "cpg", "arnoldus", "james-kruss", "mittelschule", "montessori", "musikschule",
    }
    assert by_id["cpg"]["weight"] == 1486
    assert by_id["arnoldus"]["weight"] == 430
    assert by_id["james-kruss"]["weight"] == 350
    assert by_id["mittelschule"]["weight"] == 305
    assert by_id["montessori"]["weight"] == 104
    assert by_id["musikschule"]["weight"] == 250
    assert by_id["musikschule"]["weight_source"] == "estimated_daily_visits"
    assert all(r["weight"] > 0 for r in records)


def test_school_row_pulls_p1_toward_school():
    matrix = np.array([
        [0.0, 50.0, 80.0],
        [50.0, 0.0, 50.0],
        [80.0, 50.0, 0.0],
    ], dtype=float)
    weights = np.array([10.0, 1.0, 1.0])
    homes_only = optimize_p_median(matrix, weights, 1)
    assert homes_only.selected == [0]

    school_matrix = np.array([[90.0, 80.0, 1.0]])
    school_weights = np.array([40.0])
    combined_matrix, combined_weights = stack_institution_demand(
        matrix, weights, school_matrix, school_weights
    )
    with_school = optimize_p_median(combined_matrix, combined_weights, 1)
    assert with_school.selected == [2]
    assert combined_weights.sum() == weights.sum() + 40.0
