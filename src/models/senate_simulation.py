"""Senate control simulation — Monte Carlo over competitive races.

Maturity: NOWCAST. Win probabilities come from current polling averages, not a
calibrated election-day forecast (no fundamentals drift, no time-to-election
widening yet — see METHODOLOGY_REVIEW.md Phase 5/6).

Method
------
1. Each competitive race contributes a Dem−Rep polling margin.
2. Margin → win probability via a normal error model with two components:
   a *national* error shared across every race (polls miss in the same
   direction nationwide) and an *idiosyncratic* per-race error. Defaults
   (3.0 / 4.5 points) approximate recent-cycle Senate polling error
   (Shirani-Mehr et al. 2018 put total RMSE near 5–6 points).
3. Prediction-market odds (Polymarket/Kalshi averaged) can be blended in:
   ``p = (1 − w) · p_polls + w · p_market``. The blended probability is mapped
   back to an effective margin so the simulation keeps the correlated error
   structure. ``market_weight`` is a model input — the training pipeline can
   tune it like any other hyperparameter.
4. Simulate ``num_simulations`` elections (default 1000): one national error
   draw per simulation, one idiosyncratic draw per race, count Dem seats
   against the safe-seat baseline from ``config/senate_2026.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import norm

from src.models import ModelMaturity

# Race-level polling error (points of Dem−Rep margin), split into a shared
# national component and an independent per-race component.
DEFAULT_NATIONAL_SIGMA = 3.0
DEFAULT_RACE_SIGMA = 4.5

# Weight on market-implied probability when blending with the polls-only
# probability. 0 = ignore markets entirely.
DEFAULT_MARKET_WEIGHT = 0.25

DEFAULT_NUM_SIMULATIONS = 1000

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "senate_2026.json"


@dataclass
class RaceInput:
    """One competitive race entering the simulation."""

    state: str
    race: str
    dem_candidate: str
    rep_candidate: str
    margin: float | None  # Dem − Rep polling-average margin; None = no polls
    num_polls: int = 0
    # Market-implied P(Dem win) per source, e.g. {"polymarket": 0.47}.
    market_dem_prob: dict[str, float] = field(default_factory=dict)


@dataclass
class RaceForecast:
    """Per-race output: polls-only, market and blended win probabilities."""

    state: str
    race: str
    dem_candidate: str
    rep_candidate: str
    margin: float | None
    num_polls: int
    dem_win_prob_polls: float | None
    dem_win_prob_blended: float | None
    market_dem_prob: dict[str, float]


@dataclass
class SenateControlForecast:
    """Aggregate simulation output."""

    as_of: date
    num_simulations: int
    dem_control_prob: float
    mean_dem_seats: float
    median_dem_seats: float
    # seat count -> number of simulations landing there
    seat_distribution: dict[int, int]
    races: list[RaceForecast]
    dem_safe_seats: int
    rep_safe_seats: int
    dem_majority_threshold: int
    market_weight: float
    national_sigma: float
    race_sigma: float
    # Chamber-control odds straight from the markets, for comparison.
    market_control_dem_prob: dict[str, float] = field(default_factory=dict)


def load_cycle_config(path: Path | None = None) -> dict[str, Any]:
    """Load the cycle configuration (safe seats + competitive race list)."""
    with (path or CONFIG_PATH).open(encoding="utf-8") as fh:
        return json.load(fh)


class SenateControlSimulator:
    """Monte Carlo simulation of Senate control from race-level margins.

    Maturity: NOWCAST — "if the election were held today" given current
    polling averages and market prices.
    """

    maturity = ModelMaturity.NOWCAST

    def __init__(
        self,
        dem_safe_seats: int,
        rep_safe_seats: int,
        dem_majority_threshold: int = 51,
        national_sigma: float = DEFAULT_NATIONAL_SIGMA,
        race_sigma: float = DEFAULT_RACE_SIGMA,
        market_weight: float = DEFAULT_MARKET_WEIGHT,
    ) -> None:
        if not 0.0 <= market_weight <= 1.0:
            raise ValueError(f"market_weight must be in [0, 1], got {market_weight}")
        self.dem_safe_seats = dem_safe_seats
        self.rep_safe_seats = rep_safe_seats
        self.dem_majority_threshold = dem_majority_threshold
        self.national_sigma = national_sigma
        self.race_sigma = race_sigma
        self.market_weight = market_weight

    # ── Probability helpers ───────────────────────────────────────────────

    @property
    def _total_sigma(self) -> float:
        return float(np.hypot(self.national_sigma, self.race_sigma))

    def win_prob_from_margin(self, margin: float) -> float:
        """Marginal P(Dem win) implied by a Dem−Rep polling margin."""
        return float(norm.cdf(margin / self._total_sigma))

    def _blended_prob(self, race: RaceInput) -> float | None:
        """Combine the polls-only probability with averaged market odds."""
        p_polls = self.win_prob_from_margin(race.margin) if race.margin is not None else None
        market_probs = list(race.market_dem_prob.values())
        p_market = float(np.mean(market_probs)) if market_probs else None

        if p_polls is None and p_market is None:
            return None
        if p_polls is None:
            return p_market
        if p_market is None or self.market_weight == 0.0:
            return p_polls
        return (1.0 - self.market_weight) * p_polls + self.market_weight * p_market

    def _effective_margin(self, prob: float) -> float:
        """Margin whose marginal win probability equals ``prob``.

        Keeps blended probabilities inside the correlated-error simulation.
        Probabilities are clipped away from 0/1 so the inverse CDF stays finite.
        """
        clipped = float(np.clip(prob, 1e-4, 1.0 - 1e-4))
        return float(norm.ppf(clipped) * self._total_sigma)

    # ── Simulation ────────────────────────────────────────────────────────

    def simulate(
        self,
        races: list[RaceInput],
        num_simulations: int = DEFAULT_NUM_SIMULATIONS,
        seed: int | None = None,
        as_of: date | None = None,
        market_control_dem_prob: dict[str, float] | None = None,
    ) -> SenateControlForecast:
        """Run the Monte Carlo simulation and aggregate seat outcomes."""
        if num_simulations < 1:
            raise ValueError("num_simulations must be >= 1")
        rng = np.random.default_rng(seed)
        as_of = as_of or date.today()

        forecasts: list[RaceForecast] = []
        effective_margins: list[float] = []
        for race in races:
            p_polls = (
                round(self.win_prob_from_margin(race.margin), 4)
                if race.margin is not None
                else None
            )
            p_blend = self._blended_prob(race)
            forecasts.append(
                RaceForecast(
                    state=race.state,
                    race=race.race,
                    dem_candidate=race.dem_candidate,
                    rep_candidate=race.rep_candidate,
                    margin=race.margin,
                    num_polls=race.num_polls,
                    dem_win_prob_polls=p_polls,
                    dem_win_prob_blended=round(p_blend, 4) if p_blend is not None else None,
                    market_dem_prob=dict(race.market_dem_prob),
                )
            )
            if p_blend is not None:
                effective_margins.append(self._effective_margin(p_blend))

        margins = np.array(effective_margins)
        if margins.size > 0:
            national = rng.normal(0.0, self.national_sigma, size=(num_simulations, 1))
            idiosyncratic = rng.normal(
                0.0, self.race_sigma, size=(num_simulations, margins.size)
            )
            dem_wins = (margins[None, :] + national + idiosyncratic) > 0.0
            dem_seats = self.dem_safe_seats + dem_wins.sum(axis=1)
        else:
            dem_seats = np.full(num_simulations, self.dem_safe_seats)

        dem_control = dem_seats >= self.dem_majority_threshold
        unique_seats, seat_counts = np.unique(dem_seats, return_counts=True)
        counts = {int(s): int(c) for s, c in zip(unique_seats, seat_counts, strict=True)}

        return SenateControlForecast(
            as_of=as_of,
            num_simulations=num_simulations,
            dem_control_prob=round(float(dem_control.mean()), 4),
            mean_dem_seats=round(float(dem_seats.mean()), 2),
            median_dem_seats=float(np.median(dem_seats)),
            seat_distribution=counts,
            races=forecasts,
            dem_safe_seats=self.dem_safe_seats,
            rep_safe_seats=self.rep_safe_seats,
            dem_majority_threshold=self.dem_majority_threshold,
            market_weight=self.market_weight,
            national_sigma=self.national_sigma,
            race_sigma=self.race_sigma,
            market_control_dem_prob=market_control_dem_prob or {},
        )
