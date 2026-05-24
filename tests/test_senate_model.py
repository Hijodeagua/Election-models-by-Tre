"""Tests for the senate model."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.data.base import Poll, PollAnswer, PollType, Population
from src.models.senate import (
    SenateModel,
    SenateRaceSnapshot,
    RaceRating,
    SENATE_RACES_2026,
    RATING_MARGIN_PRIOR,
)
from src.models.polling_average import PollingAverageEngine


def _make_senate_poll(
    poll_id: str = "sen-1",
    state: str = "Georgia",
    dem: float = 47.0,
    rep: float = 46.0,
    start_date: date | None = None,
) -> Poll:
    if start_date is None:
        start_date = date.today() - timedelta(days=3)
    return Poll(
        poll_id=poll_id,
        source="test",
        poll_type=PollType.HEAD_TO_HEAD,
        pollster="Test Pollster",
        subject=f"{state}-Senate",
        start_date=start_date,
        end_date=start_date + timedelta(days=3),
        sample_size=800,
        population=Population.LIKELY_VOTERS,
        answers=[
            PollAnswer(choice="Democrat", pct=dem),
            PollAnswer(choice="Republican", pct=rep),
        ],
    )


class TestRaceRating:
    def test_all_ratings_have_margin_prior(self):
        for rating in RaceRating:
            assert rating in RATING_MARGIN_PRIOR

    def test_solid_d_positive_margin(self):
        assert RATING_MARGIN_PRIOR[RaceRating.SOLID_D] > 0

    def test_solid_r_negative_margin(self):
        assert RATING_MARGIN_PRIOR[RaceRating.SOLID_R] < 0

    def test_tossup_zero_margin(self):
        assert RATING_MARGIN_PRIOR[RaceRating.TOSSUP] == 0.0


class TestSenateRaces2026:
    def test_races_exist(self):
        assert len(SENATE_RACES_2026) > 0

    def test_all_races_have_required_fields(self):
        for race in SENATE_RACES_2026:
            assert race.state
            assert race.state_abbr
            assert race.incumbent
            assert race.incumbent_party in ("D", "R")
            assert isinstance(race.rating, RaceRating)

    def test_unique_states(self):
        states = [r.state for r in SENATE_RACES_2026]
        assert len(states) == len(set(states))


class TestSenateModel:
    def setup_method(self):
        self.model = SenateModel()

    def test_race_average_with_polls(self):
        polls = [
            _make_senate_poll(poll_id="s1", state="Georgia", dem=48.0, rep=46.0),
            _make_senate_poll(poll_id="s2", state="Georgia", dem=47.0, rep=47.0),
        ]
        snap = self.model.race_average(polls, "Georgia")
        assert isinstance(snap, SenateRaceSnapshot)
        assert snap.state == "Georgia"
        assert snap.state_abbr == "GA"
        assert snap.num_polls == 2
        assert snap.rating == RaceRating.TOSSUP

    def test_race_average_no_polls_uses_prior(self):
        snap = self.model.race_average([], "Georgia")
        assert snap.num_polls == 0
        assert snap.margin == RATING_MARGIN_PRIOR[RaceRating.TOSSUP]

    def test_race_average_unknown_state(self):
        snap = self.model.race_average([], "Atlantis")
        assert snap.rating == RaceRating.TOSSUP
        assert snap.incumbent == "Unknown"

    def test_win_prob_d_leading(self):
        prob_d, prob_r = SenateModel._estimate_win_prob(5.0, 10)
        assert prob_d is not None
        assert prob_r is not None
        assert prob_d > 0.5
        assert prob_r < 0.5
        assert abs(prob_d + prob_r - 1.0) < 0.01

    def test_win_prob_r_leading(self):
        prob_d, prob_r = SenateModel._estimate_win_prob(-5.0, 10)
        assert prob_d < 0.5
        assert prob_r > 0.5

    def test_win_prob_none_margin(self):
        prob_d, prob_r = SenateModel._estimate_win_prob(None, 0)
        assert prob_d is None
        assert prob_r is None

    def test_all_races_returns_list(self):
        snapshots = self.model.all_races([])
        assert len(snapshots) == len(SENATE_RACES_2026)

    def test_chamber_summary_keys(self):
        summary = self.model.chamber_summary([])
        assert "projected_d_seats" in summary
        assert "projected_r_seats" in summary
        assert "tossup_count" in summary
        assert "races_tracked" in summary

    def test_partisan_margin_extraction(self):
        from src.models.polling_average import AverageResult
        result = AverageResult(
            as_of=date.today(),
            averages={"Democrat": 48.0, "Republican": 45.0},
            margin=3.0,
            num_polls=5,
            confidence_interval=None,
        )
        margin = SenateModel._compute_partisan_margin(result)
        assert margin == 3.0

    def test_partisan_margin_empty(self):
        from src.models.polling_average import AverageResult
        result = AverageResult(
            as_of=date.today(),
            averages={},
            margin=None,
            num_polls=0,
            confidence_interval=None,
        )
        margin = SenateModel._compute_partisan_margin(result)
        assert margin is None
