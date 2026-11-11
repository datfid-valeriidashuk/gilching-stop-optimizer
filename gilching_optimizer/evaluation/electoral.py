from __future__ import annotations

import numpy as np

KIESS_SOURCE = (
    "Johannes Kiess and Marius Dilling (2025), Das Kreuz mit den Öffentlichen. "
    "Else-Frenkel-Brunswik-Institut, commissioned by Greenpeace. "
    "Table 5 (AfD) and Table 8 (Die Linke). "
    "https://www.greenpeace.de/publikationen/20250507_Das_Kreuz_mit_den_Oeffentlichen_V05_FINAL.pdf"
)

# Second votes, Bundestag election 23 February 2025, municipality of Gilching
# (AGS 09188121). Sum of polling districts including postal districts, from the
# Bundeswahlleiterin Wahlbezirksstatistik, as compiled by wahlergebnisse.io
# (retrieved 11 Nov 2026). Shares are of valid second votes.
GILCHING_2025_SECOND_VOTES = {
    "election": "Bundestagswahl 2025",
    "date": "2025-02-23",
    "area": "Gemeinde Gilching",
    "ags": "09188121",
    "vote": "Zweitstimmen",
    "source": (
        "Die Bundeswahlleiterin, Bundestagswahl 2025, Wahlbezirksstatistik, "
        "endgültiges Ergebnis, Gemeinde sum including postal districts. "
        "Compilation: https://wahlergebnisse.io/gemeinde/09188121-gilching"
    ),
    "parties": [
        {"name": "CSU", "votes": 4374, "share_percent": 38.4},
        {"name": "Grüne", "votes": 1932, "share_percent": 16.9},
        {"name": "AfD", "votes": 1542, "share_percent": 13.5},
        {"name": "SPD", "votes": 1379, "share_percent": 12.1},
        {"name": "FDP", "votes": 630, "share_percent": 5.5},
        {"name": "Die Linke", "votes": 588, "share_percent": 5.2},
        {"name": "BSW", "votes": 294, "share_percent": 2.6},
    ],
}

# Table 5. Main effect is the East German reference. Southern Germany has an
# interaction of -0.31. Other regions are not assigned the southern slope.
AFD_QUALITY_SLOPE = {
    "east": 1.51,
    "south": 1.51 - 0.31,
}
DIE_LINKE_COEFFICIENT = -0.15


def scenario_access_index(population: np.ndarray, distance_m: np.ndarray) -> float | None:
    """Population-weighted walking-distance score from 1 (short walk) to 7 (long walk).

    Class edges are 300, 500, 750, 1000, 1500 and 2000 metres. A missing path
    scores 7. This is a scenario score for the association module. It is not
    the published municipal index, which also uses service frequency.
    """
    residents = np.asarray(population, dtype=float)
    distance = np.asarray(distance_m, dtype=float)
    counted = np.isfinite(residents) & (residents > 0)
    if not np.any(counted):
        return None
    classes = np.full(residents.shape, 7.0)
    reached = counted & np.isfinite(distance) & (distance >= 0)
    classes[reached & (distance <= 2000)] = 6
    classes[reached & (distance <= 1500)] = 5
    classes[reached & (distance <= 1000)] = 4
    classes[reached & (distance <= 750)] = 3
    classes[reached & (distance <= 500)] = 2
    classes[reached & (distance <= 300)] = 1
    score = float(np.average(classes[counted], weights=residents[counted]))
    return float(min(7.0, max(1.0, score)))


def afd_association_pp(q_old: float | None, q_new: float | None, region: str) -> float | None:
    """Associated AfD second-vote change in percentage points.

    Larger Q means poorer municipal public-transport access. Returns None when
    the index is missing or the region has no published slope in this module.
    """
    if q_old is None or q_new is None:
        return None
    if region not in AFD_QUALITY_SLOPE:
        return None
    return float(AFD_QUALITY_SLOPE[region] * (q_new - q_old))


def electoral_context(
    region: str = "south",
    q_old: float | None = None,
    q_new: float | None = None,
    from_walking: bool = False,
) -> dict:
    association = afd_association_pp(q_old, q_new, region)
    if from_walking:
        reason = (
            "Filled from residents' walking distance to the nearest stop: "
            "up to 300 m scores 1, then 500, 750, 1000, 1500 and 2000 m, and beyond 2000 m scores 7. "
            "The published index also uses service frequency, which this score does not."
        )
    else:
        reason = (
            "The published index needs modes, frequencies, catchment classes, "
            "and how residents are spread across those classes. "
            "A comparison fills a walking-distance scenario score from the stops on the map."
        )
    return {
        "label": "Model-based electoral association, not a forecast of voting changes",
        "causal": False,
        "quality_index": {
            "scale": "1 = very good access, 7 = very poor or no public transport",
            "gilching_score": None,
            "from_walking_distance": from_walking,
            "reason_unavailable": reason,
            "scenario_old": q_old,
            "scenario_new": q_new,
        },
        "election": GILCHING_2025_SECOND_VOTES,
        "afd": {
            "table": "Table 5",
            "beta_quality_east": 1.51,
            "beta_south_interaction": -0.31,
            "slope_by_region": AFD_QUALITY_SLOPE,
            "region_used": region if region in AFD_QUALITY_SLOPE else None,
            "associated_percentage_points": association,
            "statement": (
                "For Southern Germany the published slope is 1.20 percentage points of AfD "
                "second-vote share per one-step worsening of the municipal quality index, "
                "conditional on the study's other municipal controls."
            ),
        },
        "die_linke": {
            "table": "Table 8",
            "coefficient": DIE_LINKE_COEFFICIENT,
            "statistically_significant_in_multivariate_model": False,
            "associated_percentage_points": None,
            "statement": (
                "Table 8 reports a coefficient of -0.15 for Die Linke. After the other municipal "
                "controls, that estimate is not statistically significant. No electoral change is calculated."
            ),
        },
        "bsw": {
            "associated_percentage_points": None,
            "statement": (
                "The same study reports no statistically significant accessibility association for BSW. "
                "No coefficient is applied."
            ),
        },
        "source": KIESS_SOURCE,
        "limitations": [
            "The study compares municipalities. It does not show that building a bus stop changes a person's vote.",
            "The southern interaction is used for Gilching because it is in Bavaria. It is not applied to other regions.",
            "A hypothetical index entered by hand is a scenario, not a measured before/after score for this stop plan.",
        ],
    }
