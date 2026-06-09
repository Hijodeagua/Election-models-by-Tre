"""Tests for forecaster ratings and candidate quality model."""

from __future__ import annotations

from datetime import date

import pytest

from src.data.forecasters import (
    ForecastRating,
    RatingScale,
    _prob_to_rating,
    build_consensus,
    parse_rating,
)
from src.models.candidate_quality import (
    CandidateQualityModel,
    RaceFundamentals,
)

# ── Rating scale ──────────────────────────────────────────────────────


class TestRatingScale:
    def test_dem_win_probability(self):
        assert RatingScale.SOLID_D.dem_win_probability == 0.97
        assert RatingScale.TOSSUP.dem_win_probability == 0.50
        assert RatingScale.SOLID_R.dem_win_probability == 0.03

    def test_numeric_encoding(self):
        assert RatingScale.SOLID_D.numeric == 3
        assert RatingScale.TOSSUP.numeric == 0
        assert RatingScale.SOLID_R.numeric == -3

    def test_symmetry(self):
        assert (
            RatingScale.LEAN_D.dem_win_probability + RatingScale.LEAN_R.dem_win_probability == 1.0
        )
        assert RatingScale.LIKELY_D.numeric == -RatingScale.LIKELY_R.numeric


class TestParseRating:
    def test_standard_labels(self):
        assert parse_rating("Solid D") == RatingScale.SOLID_D
        assert parse_rating("Lean Republican") == RatingScale.LEAN_R
        assert parse_rating("Toss-up") == RatingScale.TOSSUP
        assert parse_rating("TOSSUP") == RatingScale.TOSSUP

    def test_tilt_maps_to_lean(self):
        assert parse_rating("Tilt D") == RatingScale.LEAN_D
        assert parse_rating("Tilt Republican") == RatingScale.LEAN_R

    def test_safe_maps_to_solid(self):
        assert parse_rating("Safe D") == RatingScale.SOLID_D
        assert parse_rating("Safe Rep") == RatingScale.SOLID_R

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            parse_rating("Unknown Category")


class TestProbToRating:
    def test_high_dem_prob(self):
        assert _prob_to_rating(0.95) == RatingScale.SOLID_D

    def test_tossup(self):
        assert _prob_to_rating(0.50) == RatingScale.TOSSUP

    def test_lean_r(self):
        assert _prob_to_rating(0.30) == RatingScale.LEAN_R

    def test_solid_r(self):
        assert _prob_to_rating(0.05) == RatingScale.SOLID_R


# ── Consensus rating ──────────────────────────────────────────────────


class TestConsensus:
    def test_build_consensus_basic(self):
        ratings = [
            ForecastRating(
                race="PA-Senate-2022", forecaster="cook",
                rating=RatingScale.LEAN_D, as_of=date(2022, 10, 1),
            ),
            ForecastRating(
                race="PA-Senate-2022", forecaster="sabato",
                rating=RatingScale.TOSSUP, as_of=date(2022, 10, 5),
            ),
            ForecastRating(
                race="PA-Senate-2022", forecaster="538",
                rating=RatingScale.LEAN_D, as_of=date(2022, 10, 3),
            ),
        ]
        consensus = build_consensus(ratings, "PA-Senate-2022")
        assert consensus.race == "PA-Senate-2022"
        assert len(consensus.ratings) == 3
        assert consensus.average_dem_probability > 0.5  # 2 lean D + 1 tossup
        assert consensus.consensus_rating == RatingScale.LEAN_D

    def test_empty_race(self):
        consensus = build_consensus([], "Nonexistent-Race")
        assert consensus.average_dem_probability == 0.5
        assert consensus.average_numeric == 0.0

    def test_filters_to_correct_race(self):
        ratings = [
            ForecastRating(
                race="PA-Senate-2022", forecaster="cook",
                rating=RatingScale.LEAN_D, as_of=date(2022, 10, 1),
            ),
            ForecastRating(
                race="GA-Senate-2022", forecaster="cook",
                rating=RatingScale.TOSSUP, as_of=date(2022, 10, 1),
            ),
        ]
        consensus = build_consensus(ratings, "PA-Senate-2022")
        assert len(consensus.ratings) == 1


# ── Candidate quality / WAR model ─────────────────────────────────────


class TestCandidateQualityModel:
    def setup_method(self):
        self.model = CandidateQualityModel()

    def _make_race(self, **overrides: ...) -> RaceFundamentals:
        defaults = dict(
            race="PA-Senate-2022",
            state="PA",
            year=2022,
            office="senate",
            partisan_lean=1.0,  # slight D lean
            generic_ballot_margin=-0.6,
            dem_incumbent=False,
            rep_incumbent=False,
            open_seat=True,
            presidential_approval=42.0,
            president_party="D",
        )
        defaults.update(overrides)
        return RaceFundamentals(**defaults)

    def test_projection_at_neutral(self):
        race = self._make_race(
            partisan_lean=0.0, generic_ballot_margin=0.0,
            presidential_approval=50.0, year=2024,  # presidential year = no midterm penalty
        )
        proj = self.model.project_fundamentals(race)
        assert proj.expected_dem_share == pytest.approx(50.0, abs=1.0)

    def test_partisan_lean_shifts_projection(self):
        d_lean = self._make_race(partisan_lean=10.0, year=2024)
        r_lean = self._make_race(partisan_lean=-10.0, year=2024)
        d_proj = self.model.project_fundamentals(d_lean)
        r_proj = self.model.project_fundamentals(r_lean)
        assert d_proj.expected_dem_share > r_proj.expected_dem_share

    def test_dem_incumbency_bonus(self):
        inc = self._make_race(dem_incumbent=True, open_seat=False, year=2024)
        open_seat = self._make_race(year=2024)
        inc_proj = self.model.project_fundamentals(inc)
        open_proj = self.model.project_fundamentals(open_seat)
        assert inc_proj.expected_dem_share > open_proj.expected_dem_share

    def test_midterm_penalty(self):
        # 2022 is a midterm with D president → hurts Dems
        midterm = self._make_race(year=2022)
        pres = self._make_race(year=2024)
        mid_proj = self.model.project_fundamentals(midterm)
        pres_proj = self.model.project_fundamentals(pres)
        assert mid_proj.expected_dem_share < pres_proj.expected_dem_share

    def test_compute_quality(self):
        race = self._make_race()
        dem_q, rep_q = self.model.compute_quality(
            race, actual_dem_share=53.0,
            dem_candidate="Fetterman", rep_candidate="Oz",
        )
        assert dem_q.candidate == "Fetterman"
        assert dem_q.party == "D"
        assert dem_q.actual_vote_share == 53.0
        # Quality = actual - expected
        assert dem_q.quality_score == pytest.approx(
            53.0 - dem_q.expected_vote_share, abs=0.1
        )
        # WAR is the same as quality_score
        assert dem_q.war == dem_q.quality_score
        # Rep quality should mirror
        assert rep_q.actual_vote_share == pytest.approx(47.0, abs=0.1)

    def test_projection_clamped(self):
        # Extreme values shouldn't produce >80 or <20
        extreme = self._make_race(partisan_lean=50.0)
        proj = self.model.project_fundamentals(extreme)
        assert proj.expected_dem_share <= 80.0

    def test_backtest(self):
        races = [
            self._make_race(race="PA-2022", partisan_lean=1.0),
            self._make_race(race="GA-2022", partisan_lean=-3.0),
            self._make_race(race="NV-2022", partisan_lean=0.5),
        ]
        actuals = [51.2, 49.4, 48.8]
        results = self.model.backtest(races, actuals)
        assert results["n_races"] == 3
        assert "rmse" in results
        assert "mae" in results
        assert len(results["results"]) == 3

    def test_fundamentals_components_add_up(self):
        race = self._make_race(year=2022)
        proj = self.model.project_fundamentals(race)
        component_sum = sum(proj.components.values())
        assert proj.expected_dem_share == pytest.approx(component_sum, abs=0.2)
