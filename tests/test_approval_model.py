"""Tests for the presidential approval model."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.data.base import Poll, PollAnswer, PollType, Population
from src.models.approval import PresidentialApprovalModel, ApprovalSnapshot
from src.models.polling_average import PollingAverageEngine


def _make_approval_poll(
    poll_id: str = "ap-1",
    approve: float = 43.0,
    disapprove: float = 54.0,
    start_date: date | None = None,
    sample_size: int = 1000,
) -> Poll:
    if start_date is None:
        start_date = date.today() - timedelta(days=3)
    return Poll(
        poll_id=poll_id,
        source="test",
        poll_type=PollType.APPROVAL,
        pollster="Test Pollster",
        subject="President",
        start_date=start_date,
        end_date=start_date + timedelta(days=3),
        sample_size=sample_size,
        population=Population.LIKELY_VOTERS,
        answers=[
            PollAnswer(choice="Approve", pct=approve),
            PollAnswer(choice="Disapprove", pct=disapprove),
        ],
    )


class TestPresidentialApprovalModel:
    def setup_method(self):
        self.model = PresidentialApprovalModel()

    def test_current_approval_basic(self):
        polls = [_make_approval_poll(approve=45.0, disapprove=52.0)]
        snapshot = self.model.current_approval(polls)
        assert isinstance(snapshot, ApprovalSnapshot)
        assert snapshot.approve == 45.0
        assert snapshot.disapprove == 52.0
        assert snapshot.net_approval == -7.0
        assert snapshot.num_polls == 1

    def test_current_approval_multiple_polls(self):
        polls = [
            _make_approval_poll(poll_id="p1", approve=44.0, disapprove=53.0),
            _make_approval_poll(poll_id="p2", approve=46.0, disapprove=51.0),
        ]
        snapshot = self.model.current_approval(polls)
        assert snapshot.num_polls == 2
        assert 44.0 <= snapshot.approve <= 46.0
        assert 51.0 <= snapshot.disapprove <= 53.0

    def test_current_approval_filters_non_approval(self):
        approval = _make_approval_poll(poll_id="ap", approve=45.0, disapprove=52.0)
        gb = Poll(
            poll_id="gb-1",
            source="test",
            poll_type=PollType.GENERIC_BALLOT,
            pollster="Test",
            subject="Congress",
            start_date=date.today() - timedelta(days=3),
            end_date=date.today(),
            sample_size=1000,
            population=Population.LIKELY_VOTERS,
            answers=[
                PollAnswer(choice="Democrat", pct=48.0),
                PollAnswer(choice="Republican", pct=46.0),
            ],
        )
        snapshot = self.model.current_approval([approval, gb])
        assert snapshot.num_polls == 1

    def test_empty_polls(self):
        snapshot = self.model.current_approval([])
        assert snapshot.num_polls == 0
        assert snapshot.approve == 0.0

    def test_approval_trend_returns_list(self):
        polls = [
            _make_approval_poll(
                poll_id=f"p{i}",
                approve=43.0 + i,
                disapprove=54.0 - i,
                start_date=date.today() - timedelta(days=20 - i * 2),
            )
            for i in range(8)
        ]
        trend = self.model.approval_trend(polls, step_days=5)
        assert isinstance(trend, list)
        assert len(trend) > 0
        assert all(isinstance(s, ApprovalSnapshot) for s in trend)

    def test_approval_trend_empty(self):
        trend = self.model.approval_trend([])
        assert trend == []
