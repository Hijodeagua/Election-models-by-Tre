"""Non-polling fundamentals for election modeling.

Economic indicators, presidential approval, and structural factors
that historically predict election outcomes independently of polling.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FundamentalsSnapshot:
    """Key non-polling predictors for a midterm election."""

    president_party: str  # "D" or "R"
    midterm_penalty: float  # Historical avg loss for president's party
    gdp_growth_q2: float | None  # Q2 GDP growth rate (annualized)
    unemployment_rate: float | None
    consumer_sentiment: float | None
    presidential_approval: float | None


# Historical midterm penalty: the president's party almost always loses seats.
# Average House seat loss in midterms (1946–2022): ~26 seats.
AVERAGE_MIDTERM_PENALTY = -26.0


def estimate_structural_lean(fundamentals: FundamentalsSnapshot) -> float:
    """Estimate structural advantage/disadvantage from fundamentals.

    Returns a rough seat estimate relative to baseline (positive = president's party gains).
    This is a simplified model — a real implementation would use regression.
    """
    lean = AVERAGE_MIDTERM_PENALTY

    # Approval adjustment: each point above/below 50% ≈ 1.5 seats
    if fundamentals.presidential_approval is not None:
        lean += (fundamentals.presidential_approval - 50.0) * 1.5

    # GDP adjustment: strong growth helps the incumbent party
    if fundamentals.gdp_growth_q2 is not None:
        lean += fundamentals.gdp_growth_q2 * 3.0

    return round(lean, 0)
