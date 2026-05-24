"""Tests for the generic ballot model."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.data.base import Poll, PollAnswer, PollType, Population
from src.models.generic_ballot import GenericBallotModel, GenericBallotSnapshot


def _make_gb_poll(
    poll_id: str = "gb-1",
    dem: float = 47.0,
    rep: float = 45.0,
    start_date: date | None = None,
    sample_size: int = 1200,
) -> Poll:
    if start_date is None:
        start_date = date.today() - timedelta(days=3)
    return Poll(
        poll_id=poll_id,
        source="test",
        poll_type=PollType.GENERIC_BALLOT,
        pollster="Test Pollster",
        subject="Generic Ballot",
        start_date=start_date,
        end_date=start_date + timedelta(days=3),
        sample_size=sample_size,
        population=Population.LIKELY_VOTERS,
        answers=[
            PollAnswer(choice="Democrat", pct=dem),
            PollAnswer(choice="Republican", pct=rep),
        ],
    )


class TestGenericBallotModel:
    def setup_method(self):
        self.model = GenericBallotModel()

    def test_current_ballot_basic(self):
        polls = [_make_gb_poll(dem=48.0, rep=45.0)]
        snapshot = self.model.current_ballot(polls)
        assert isinstance(snapshot, GenericBallotSnapshot)
        assert snapshot.dem_pct == 48.0
        assert snapshot.rep_pct == 45.0
        assert snapshot.margin == 3.0
        assert snapshot.num_polls == 1

    def test_margin_positive_means_d_advantage(self):
        polls = [_make_gb_poll(dem=50.0, rep=44.0)]
        snapshot = self.model.current_ballot(polls)
        assert snapshot.margin > 0

    def test_margin_negative_means_r_advantage(self):
        polls = [_make_gb_poll(dem=43.0, rep=49.0)]
        snapshot = self.model.current_ballot(polls)
        assert snapshot.margin < 0

    def test_seat_estimation_d_advantage(self):
        polls = [_make_gb_poll(dem=52.0, rep=44.0)]
        snapshot = self.model.current_ballot(polls)
        assert snapshot.estimated_dem_seats is not None
        assert snapshot.estimated_dem_seats > 218

    def test_seat_estimation_r_advantage(self):
        polls = [_make_gb_poll(dem=43.0, rep=51.0)]
        snapshot = self.model.current_ballot(polls)
        assert snapshot.estimated_dem_seats is not None
        assert snapshot.estimated_dem_seats < 218

    def test_seat_estimation_clamped(self):
        polls = [_make_gb_poll(dem=70.0, rep=20.0)]
        snapshot = self.model.current_ballot(polls)
        assert snapshot.estimated_dem_seats <= 285
        assert snapshot.estimated_rep_seats >= 150

    def test_empty_polls(self):
        snapshot = self.model.current_ballot([])
        assert snapshot.num_polls == 0
        assert snapshot.dem_pct == 0.0
        assert snapshot.rep_pct == 0.0

    def test_filters_non_gb_polls(self):
        gb = _make_gb_poll()
        approval = Poll(
            poll_id="ap-1",
            source="test",
            poll_type=PollType.APPROVAL,
            pollster="Test",
            subject="President",
            start_date=date.today() - timedelta(days=3),
            end_date=date.today(),
            sample_size=1000,
            population=Population.LIKELY_VOTERS,
            answers=[
                PollAnswer(choice="Approve", pct=45.0),
                PollAnswer(choice="Disapprove", pct=52.0),
            ],
        )
        snapshot = self.model.current_ballot([gb, approval])
        assert snapshot.num_polls == 1

    def test_multiple_polls_averaged(self):
        polls = [
            _make_gb_poll(poll_id="p1", dem=46.0, rep=48.0),
            _make_gb_poll(poll_id="p2", dem=50.0, rep=44.0),
        ]
        snapshot = self.model.current_ballot(polls)
        assert snapshot.num_polls == 2
        assert 46.0 <= snapshot.dem_pct <= 50.0
        assert 44.0 <= snapshot.rep_pct <= 48.0
