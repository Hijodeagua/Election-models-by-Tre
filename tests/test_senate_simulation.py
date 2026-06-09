"""Tests for the Senate control Monte Carlo (src/models/senate_simulation.py)."""

from __future__ import annotations

import pytest

from src.models.senate_simulation import (
    RaceInput,
    SenateControlSimulator,
    load_cycle_config,
)


def _simulator(**overrides) -> SenateControlSimulator:
    defaults = dict(dem_safe_seats=47, rep_safe_seats=48, dem_majority_threshold=51)
    defaults.update(overrides)
    return SenateControlSimulator(**defaults)


def _race(state="Georgia", margin=0.0, market=None) -> RaceInput:
    return RaceInput(
        state=state,
        race=f"{state} Senate 2026",
        dem_candidate="D",
        rep_candidate="R",
        margin=margin,
        num_polls=3,
        market_dem_prob=market or {},
    )


class TestWinProbability:
    def test_even_margin_is_a_tossup(self):
        assert _simulator().win_prob_from_margin(0.0) == pytest.approx(0.5)

    def test_monotonic_in_margin(self):
        sim = _simulator()
        probs = [sim.win_prob_from_margin(m) for m in (-10, -5, 0, 5, 10)]
        assert probs == sorted(probs)
        assert probs[0] < 0.05 and probs[-1] > 0.95

    def test_market_blend_pulls_toward_market(self):
        sim = _simulator(market_weight=0.5)
        polls_only = _simulator(market_weight=0.0)
        race = _race(margin=5.0, market={"polymarket": 0.10})
        p_polls = polls_only._blended_prob(race)
        p_blend = sim._blended_prob(race)
        assert p_blend < p_polls
        assert p_blend == pytest.approx(0.5 * p_polls + 0.5 * 0.10)

    def test_blend_without_polls_uses_market(self):
        sim = _simulator()
        race = _race(margin=None, market={"kalshi": 0.62})
        assert sim._blended_prob(race) == pytest.approx(0.62)

    def test_blend_without_any_data_is_none(self):
        assert _simulator()._blended_prob(_race(margin=None)) is None

    def test_invalid_market_weight_rejected(self):
        with pytest.raises(ValueError):
            _simulator(market_weight=1.5)


class TestSimulation:
    def test_seeded_run_is_reproducible(self):
        races = [_race("Georgia", -1.0), _race("Arizona", 4.0)]
        a = _simulator().simulate(races, num_simulations=1000, seed=42)
        b = _simulator().simulate(races, num_simulations=1000, seed=42)
        assert a.dem_control_prob == b.dem_control_prob
        assert a.seat_distribution == b.seat_distribution

    def test_seat_distribution_sums_to_num_simulations(self):
        races = [_race("Georgia", -1.0), _race("Arizona", 4.0)]
        result = _simulator().simulate(races, num_simulations=1000, seed=1)
        assert sum(result.seat_distribution.values()) == 1000
        assert result.num_simulations == 1000

    def test_seat_range_bounded_by_races(self):
        races = [_race("Georgia", 0.0), _race("Arizona", 0.0)]
        result = _simulator().simulate(races, num_simulations=500, seed=1)
        seats = sorted(result.seat_distribution)
        assert seats[0] >= 47
        assert seats[-1] <= 49

    def test_landslide_margins_secure_control(self):
        # Dems need 4 of 5 to reach 51; +20 everywhere should get there.
        races = [_race(s, 20.0) for s in ("A", "B", "C", "D", "E")]
        result = _simulator().simulate(races, num_simulations=1000, seed=1)
        assert result.dem_control_prob > 0.9

    def test_no_races_means_safe_seats_only(self):
        result = _simulator().simulate([], num_simulations=100, seed=1)
        assert result.seat_distribution == {47: 100}
        assert result.dem_control_prob == 0.0

    def test_market_control_comparison_passthrough(self):
        result = _simulator().simulate(
            [], num_simulations=10, seed=1, market_control_dem_prob={"kalshi": 0.31}
        )
        assert result.market_control_dem_prob == {"kalshi": 0.31}

    def test_per_race_forecasts_present(self):
        races = [_race("Georgia", -1.0, market={"polymarket": 0.47})]
        result = _simulator().simulate(races, num_simulations=100, seed=1)
        forecast = result.races[0]
        assert forecast.state == "Georgia"
        assert forecast.dem_win_prob_polls is not None
        assert forecast.dem_win_prob_blended is not None
        assert forecast.market_dem_prob == {"polymarket": 0.47}

    def test_zero_simulations_rejected(self):
        with pytest.raises(ValueError):
            _simulator().simulate([], num_simulations=0)


class TestCycleConfig:
    def test_config_is_consistent(self):
        cfg = load_cycle_config()
        n_competitive = len(cfg["competitive_races"])
        assert cfg["dem_safe_seats"] + cfg["rep_safe_seats"] + n_competitive == 100
        # Both parties must be able to reach the Dem threshold boundary.
        assert cfg["dem_safe_seats"] + n_competitive >= cfg["dem_majority_threshold"]
        for entry in cfg["competitive_races"]:
            assert {"state", "race", "dem_candidate", "rep_candidate"} <= set(entry)
