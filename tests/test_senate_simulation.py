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

    def test_bias_shifts_the_tossup_point(self):
        # A +2 bias means a tied polling margin already favours the Democrat,
        # and the 50/50 point sits at a 2-point Republican polling lead.
        sim = _simulator(bias=2.0)
        assert sim.win_prob_from_margin(0.0) > 0.5
        assert sim.win_prob_from_margin(-2.0) == pytest.approx(0.5)

    def test_effective_margin_reproduces_prob_in_simulation(self):
        # The mean-zero noise sim turns an effective margin m into Φ(m/σ); that
        # must equal the input prob (which already carries the bias), so bias is
        # not re-applied in _effective_margin.
        from scipy.stats import norm

        sim = _simulator(bias=1.5)
        for prob in (0.2, 0.5, 0.75, 0.9):
            m = sim._effective_margin(prob)
            assert float(norm.cdf(m / sim._total_sigma)) == pytest.approx(prob, abs=1e-6)

    def test_bias_lowers_dem_control_in_simulation(self):
        # End-to-end: a Republican-leaning bias must actually reduce simulated
        # Dem control (regression test for the cancel-out bug).
        races = [_race(s, margin=1.0) for s in ("A", "B", "C", "D", "E")]
        no_bias = _simulator(bias=0.0).simulate(races, num_simulations=20000, seed=1)
        r_bias = _simulator(bias=-3.0).simulate(races, num_simulations=20000, seed=1)
        assert r_bias.dem_control_prob < no_bias.dem_control_prob

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

    def test_per_race_simulation_summary(self):
        # The simulated median margin and win share are populated and internally
        # consistent: a positive median margin implies the Dem wins >50% of sims.
        races = [_race("A", 6.0), _race("B", -6.0)]
        result = _simulator().simulate(races, num_simulations=20000, seed=7)
        dem_fav, rep_fav = result.races
        assert dem_fav.median_margin > 0 and dem_fav.dem_win_prob_sim > 0.5
        assert rep_fav.median_margin < 0 and rep_fav.dem_win_prob_sim < 0.5
        # 80% band is ordered and brackets the median.
        for fc in result.races:
            assert fc.margin_p10 < fc.median_margin < fc.margin_p90
        # Simulated win share tracks the analytic marginal within sampling noise.
        assert dem_fav.dem_win_prob_sim == pytest.approx(
            dem_fav.dem_win_prob_blended, abs=0.02
        )

    def test_margin_histogram_is_a_distribution(self):
        # The per-race histogram covers ~all the probability mass and leans the
        # right way: a Dem-favoured race puts most of its mass on positive bins.
        races = [_race("A", margin=8.0)]
        result = _simulator().simulate(races, num_simulations=20000, seed=11)
        hist = result.races[0].margin_hist
        assert hist, "expected a non-empty histogram"
        total = sum(b["pct"] for b in hist)
        assert total == pytest.approx(1.0, abs=1e-3)
        dem_mass = sum(b["pct"] for b in hist if b["mid"] > 0)
        assert dem_mass > 0.5

    def test_median_margin_carries_bias(self):
        # A Republican bias must pull the simulated median margin downward.
        races = [_race("A", margin=0.0)]
        no_bias = _simulator(bias=0.0).simulate(races, num_simulations=20000, seed=3)
        r_bias = _simulator(bias=-4.0).simulate(races, num_simulations=20000, seed=3)
        assert r_bias.races[0].median_margin < no_bias.races[0].median_margin

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


# ── Student-t fat tails (audit item 8) ────────────────────────────────


class TestStudentTTails:
    def _simulator(self, tail_dof=None):
        from src.models.senate_simulation import SenateControlSimulator
        return SenateControlSimulator(
            dem_safe_seats=45, rep_safe_seats=45, tail_dof=tail_dof,
        )

    def test_dof_must_exceed_two(self):
        import pytest
        with pytest.raises(ValueError, match="tail_dof"):
            self._simulator(tail_dof=2.0)

    def test_simulated_win_share_matches_analytic_marginal(self):
        """The chi-square-mixed draws must reproduce the t marginal that
        win_prob_from_margin computes, or the effective-margin inversion
        breaks."""
        from src.models.senate_simulation import RaceInput
        sim = self._simulator(tail_dof=5.0)
        race = RaceInput(state="X", race="X Senate", dem_candidate="D",
                         rep_candidate="R", margin=4.0, num_polls=5)
        fc = sim.simulate([race], num_simulations=200_000, seed=7)
        analytic = sim.win_prob_from_margin(4.0)
        assert abs(fc.races[0].dem_win_prob_sim - analytic) < 0.01

    def test_variance_matched_to_calibrated_sigma(self):
        """t draws must keep the calibrated error variance, so the sigmas
        retain their empirical meaning."""
        from src.models.senate_simulation import RaceInput
        race = RaceInput(state="X", race="X Senate", dem_candidate="D",
                         rep_candidate="R", margin=0.0, num_polls=5)
        gauss = self._simulator().simulate([race], num_simulations=200_000, seed=7)
        fat = self._simulator(tail_dof=5.0).simulate([race], num_simulations=200_000, seed=7)
        # Compare inter-decile widths only loosely; variances should be close
        g_w = gauss.races[0].margin_p90 - gauss.races[0].margin_p10
        f_w = fat.races[0].margin_p90 - fat.races[0].margin_p10
        # Same variance but heavier tails ⇒ t's 10-90 width is a bit NARROWER
        assert f_w < g_w
        assert abs(f_w - g_w) / g_w < 0.25

    def test_big_leads_less_certain_under_fat_tails(self):
        """Fat tails put more mass on huge misses, so a big polling lead
        converts to a lower win probability than under a Gaussian."""
        gauss = self._simulator().win_prob_from_margin(12.0)
        fat = self._simulator(tail_dof=5.0).win_prob_from_margin(12.0)
        assert fat < gauss
        assert fat > 0.9  # still a very likely win

    def test_default_stays_gaussian(self):
        sim = self._simulator()
        assert sim.tail_dof is None
        fc = sim.simulate([], num_simulations=10)
        assert fc.tail_dof is None
