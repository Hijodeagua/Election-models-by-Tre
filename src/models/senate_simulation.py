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
4. Simulate ``num_simulations`` elections (default 50000): one national error
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

DEFAULT_NUM_SIMULATIONS = 50000

# Fixed bins for the per-race simulated-margin histogram (Dem−Rep points), shared
# across races so they're directly comparable. Tails are clipped into the ends.
MARGIN_HIST_EDGES = np.arange(-30.0, 30.0001, 2.0)

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
    """Per-race output: polls-only, market and blended win probabilities, plus
    the simulated outcome distribution (win share + median/80% margin band)."""

    state: str
    race: str
    dem_candidate: str
    rep_candidate: str
    margin: float | None
    num_polls: int
    dem_win_prob_polls: float | None
    dem_win_prob_blended: float | None
    market_dem_prob: dict[str, float]
    # Drawn straight from the Monte Carlo: the share of simulations the Democrat
    # wins, and the Dem−Rep margin distribution across simulations.
    dem_win_prob_sim: float | None = None
    median_margin: float | None = None
    margin_p10: float | None = None
    margin_p90: float | None = None
    # Binned distribution of the simulated Dem−Rep margin: a list of
    # {"mid": bin_center, "pct": fraction_of_sims}. Powers the per-race histogram.
    margin_hist: list[dict] = field(default_factory=list)


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
    bias: float = 0.0
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
        bias: float = 0.0,
    ) -> None:
        if not 0.0 <= market_weight <= 1.0:
            raise ValueError(f"market_weight must be in [0, 1], got {market_weight}")
        self.dem_safe_seats = dem_safe_seats
        self.rep_safe_seats = rep_safe_seats
        self.dem_majority_threshold = dem_majority_threshold
        self.national_sigma = national_sigma
        self.race_sigma = race_sigma
        self.market_weight = market_weight
        # Systematic polling bias in Dem−Rep margin points (mean of
        # actual − poll over historical races). Positive = polls have
        # understated Democrats; the expected margin is shifted by +bias.
        self.bias = bias

    # ── Probability helpers ───────────────────────────────────────────────

    @property
    def _total_sigma(self) -> float:
        return float(np.hypot(self.national_sigma, self.race_sigma))

    def win_prob_from_margin(self, margin: float) -> float:
        """Marginal P(Dem win) implied by a Dem−Rep polling margin."""
        return float(norm.cdf((margin + self.bias) / self._total_sigma))

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
        # The simulation draws mean-zero noise, so its marginal for an effective
        # margin m is Φ(m/σ). We want that to equal `prob` — and `prob` already
        # carries the bias (it came from win_prob_from_margin / the market blend),
        # so the bias must NOT be re-applied here, or it cancels out.
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
        # Forecast index for each effective margin, so per-race simulated stats
        # can be written back onto the right RaceForecast.
        margin_to_forecast: list[int] = []
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
                margin_to_forecast.append(len(forecasts) - 1)

        margins = np.array(effective_margins)
        if margins.size > 0:
            national = rng.normal(0.0, self.national_sigma, size=(num_simulations, 1))
            idiosyncratic = rng.normal(
                0.0, self.race_sigma, size=(num_simulations, margins.size)
            )
            sim_margins = margins[None, :] + national + idiosyncratic
            dem_wins = sim_margins > 0.0
            dem_seats = self.dem_safe_seats + dem_wins.sum(axis=1)
            # Per-race simulated outcome distribution (median + 80% band + win share).
            race_median = np.median(sim_margins, axis=0)
            race_p10 = np.percentile(sim_margins, 10, axis=0)
            race_p90 = np.percentile(sim_margins, 90, axis=0)
            race_winshare = dem_wins.mean(axis=0)
            # Histogram bins (clip tails into the end bins so no mass is lost;
            # np.histogram's last bin is closed, so exact-edge clipping is safe).
            edges = MARGIN_HIST_EDGES
            mids = (edges[:-1] + edges[1:]) / 2.0
            for j, fi in enumerate(margin_to_forecast):
                fc = forecasts[fi]
                fc.dem_win_prob_sim = round(float(race_winshare[j]), 4)
                fc.median_margin = round(float(race_median[j]), 2)
                fc.margin_p10 = round(float(race_p10[j]), 2)
                fc.margin_p90 = round(float(race_p90[j]), 2)
                clipped = np.clip(sim_margins[:, j], edges[0], edges[-1])
                counts, _ = np.histogram(clipped, bins=edges)
                fc.margin_hist = [
                    {"mid": round(float(m), 1), "pct": round(float(c) / num_simulations, 5)}
                    for m, c in zip(mids, counts, strict=True)
                ]
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
            bias=self.bias,
            market_control_dem_prob=market_control_dem_prob or {},
        )
