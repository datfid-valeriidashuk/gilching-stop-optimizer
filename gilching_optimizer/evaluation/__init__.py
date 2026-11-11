"""Research-based evaluation of a proposed stop set.

Demand and emissions use walking-network distances already computed by the
optimizer. The electoral module is a separate observational association and
is not a forecast of how votes change if a stop is built.
"""

from .demand import (
    excess_distance_steps,
    log_odds_change,
    odds_ratio,
    probability_after_odds_ratio,
    evaluate_demand,
)
from .emissions import evaluate_emissions
from .electoral import electoral_context, afd_association_pp
from .scenario import Scenario

__all__ = [
    "Scenario",
    "excess_distance_steps",
    "log_odds_change",
    "odds_ratio",
    "probability_after_odds_ratio",
    "evaluate_demand",
    "evaluate_emissions",
    "electoral_context",
    "afd_association_pp",
]
