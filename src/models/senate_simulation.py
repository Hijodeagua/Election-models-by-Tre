"""Monte Carlo simulation of Senate control.

Runs N simulations (default 1,000) over the per-race blended win
probabilities from senate_probability.py. Race outcomes are correlated
through a shared national-environment shock: each simulation draws one
national swing (sigma = NATIONAL_SWING_SD points of margin) applied to every
race, plus an independent idiosyncratic error per race. This matches how
polling errors actually behave — they are mostly systematic, not
independent — and is what separates a simulation from multiplying
independent probabilities.

Implementation notes:
    * Probabilities are converted back to implied margins (inverse normal
      CDF), shocked in margin space, then compared against zero.
    * Pure stdlib (random + math/statistics) — no numpy needed in CI.
    * Seeded for reproducibility; the daily export uses a date-based seed so
      reruns on the same day are identical.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from statistics import NormalDist

from src.models.senate_probability import DEFAULT_POLL_SIGMA, RaceProbability

DEFAULT_N_SIMS = 1000
# Shared national swing: systematic polling/environment error, in margin points.
NATIONAL_SWING_SD = 3.0
# Per-race independent error, in margin points.
IDIOSYNCRATIC_SD = 4.0

_NORMAL = NormalDist()


def _prob_to_margin(prob: float, sigma: float = DEFAULT_POLL_SIGMA) -> float:
    """Implied Dem margin from a win probability (inverse of margin_to_win_prob)."""
    clamped = min(max(prob, 0.001), 0.999)
    return _NORMAL.inv_cdf(clamped) * sigma


@dataclass
class SimulationResult:
    """Aggregate outcome of the Senate control simulation."""

    n_sims: int
    dem_control_prob: float  # P(Dems reach the control threshold)
    rep_control_prob: float
    mean_dem_seats: float
    median_dem_seats: int
    seat_histogram: dict[int, int]  # dem_seats -> count of simulations
    race_win_freq: dict[str, float]  # state -> simulated Dem win frequency
    tipping_point_freq: dict[str, float]  # state -> share of sims as tipping point
    baseline_dem: int
    baseline_rep: int
    dem_seats_needed: int
    seed: int
    national_swing_sd: float = NATIONAL_SWING_SD
    idiosyncratic_sd: float = IDIOSYNCRATIC_SD
    notes: list[str] = field(default_factory=list)


def simulate_senate_control(
    races: list[RaceProbability],
    baseline_dem: int,
    baseline_rep: int,
    dem_seats_needed: int = 51,
    n_sims: int = DEFAULT_N_SIMS,
    seed: int = 2026,
    national_swing_sd: float = NATIONAL_SWING_SD,
    idiosyncratic_sd: float = IDIOSYNCRATIC_SD,
    sigma: float = DEFAULT_POLL_SIGMA,
) -> SimulationResult:
    """Simulate Senate control n_sims times from blended race probabilities."""
    rng = random.Random(seed)
    margins = {r.state: _prob_to_margin(r.blended_prob, sigma) for r in races}
    states = [r.state for r in races]

    seat_histogram: dict[int, int] = {}
    win_counts = dict.fromkeys(states, 0)
    tipping_counts = dict.fromkeys(states, 0)
    dem_control = 0
    total_dem_seats = 0
    all_dem_seats: list[int] = []

    for _ in range(n_sims):
        national_swing = rng.gauss(0.0, national_swing_sd)
        sim_margins = {
            s: margins[s] + national_swing + rng.gauss(0.0, idiosyncratic_sd)
            for s in states
        }
        dem_wins = [s for s in states if sim_margins[s] > 0]
        dem_seats = baseline_dem + len(dem_wins)

        for s in dem_wins:
            win_counts[s] += 1
        seat_histogram[dem_seats] = seat_histogram.get(dem_seats, 0) + 1
        total_dem_seats += dem_seats
        all_dem_seats.append(dem_seats)
        if dem_seats >= dem_seats_needed:
            dem_control += 1

        # Tipping point: order races by simulated Dem margin (strongest first)
        # and find the seat that pushes Dems across the threshold (or, if they
        # fall short, the first one they failed to take).
        needed_from_races = dem_seats_needed - baseline_dem
        if 0 < needed_from_races <= len(states):
            ranked = sorted(states, key=lambda s: sim_margins[s], reverse=True)
            tipping_counts[ranked[needed_from_races - 1]] += 1

    all_dem_seats.sort()
    median_seats = all_dem_seats[n_sims // 2] if all_dem_seats else baseline_dem

    return SimulationResult(
        n_sims=n_sims,
        dem_control_prob=round(dem_control / n_sims, 4),
        rep_control_prob=round(1.0 - dem_control / n_sims, 4),
        mean_dem_seats=round(total_dem_seats / n_sims, 2) if n_sims else float(baseline_dem),
        median_dem_seats=median_seats,
        seat_histogram=dict(sorted(seat_histogram.items())),
        race_win_freq={s: round(c / n_sims, 4) for s, c in win_counts.items()},
        tipping_point_freq={
            s: round(c / n_sims, 4) for s, c in tipping_counts.items() if c > 0
        },
        baseline_dem=baseline_dem,
        baseline_rep=baseline_rep,
        dem_seats_needed=dem_seats_needed,
        seed=seed,
    )


def date_seed(d) -> int:
    """Deterministic per-day seed so daily CI reruns are reproducible."""
    return int(d.strftime("%Y%m%d")) if hasattr(d, "strftime") else int(d)


__all__ = [
    "DEFAULT_N_SIMS",
    "IDIOSYNCRATIC_SD",
    "NATIONAL_SWING_SD",
    "SimulationResult",
    "date_seed",
    "simulate_senate_control",
]
