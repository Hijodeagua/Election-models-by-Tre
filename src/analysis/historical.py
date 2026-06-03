"""Historical election comparisons.

Utilities for comparing current polling to historical cycles
at equivalent points in time.
"""

from __future__ import annotations

# Placeholder — will be populated as historical data is backfilled.
# Structure: { year: { "approval_at_500_days": float, "generic_ballot_margin": float, ... } }
MIDTERM_BENCHMARKS: dict[int, dict[str, float]] = {
    2022: {"approval_at_500_days": 41.3, "generic_ballot_margin": -0.6, "house_seat_change": -9},
    2018: {"approval_at_500_days": 40.0, "generic_ballot_margin": 8.6, "house_seat_change": 40},
    2014: {"approval_at_500_days": 42.6, "generic_ballot_margin": -2.4, "house_seat_change": -13},
    2010: {"approval_at_500_days": 45.5, "generic_ballot_margin": -6.8, "house_seat_change": -63},
    2006: {"approval_at_500_days": 36.0, "generic_ballot_margin": 11.5, "house_seat_change": 31},
}


def compare_to_cycle(current_approval: float, cycle_year: int) -> dict[str, float] | None:
    """Compare current approval to a historical midterm cycle.

    Returns:
        Dict with differences, or None if cycle data unavailable.
    """
    benchmark = MIDTERM_BENCHMARKS.get(cycle_year)
    if benchmark is None:
        return None
    return {
        "approval_diff": round(current_approval - benchmark["approval_at_500_days"], 1),
        "benchmark_approval": benchmark["approval_at_500_days"],
        "benchmark_gb_margin": benchmark["generic_ballot_margin"],
        "benchmark_seat_change": benchmark["house_seat_change"],
    }
