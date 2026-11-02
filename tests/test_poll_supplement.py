"""Supplementary poll merge: hand-added polls join the feed without duplicates."""

from __future__ import annotations

from datetime import date

from scripts.export_json import merge_supplement
from src.data.base import Poll, PollAnswer, PollType


def _poll(pollster: str, end: date, dem: float, rep: float, subject="Kansas Senate 2026") -> Poll:
    return Poll(
        poll_id=f"{pollster}-{end}", source="test", poll_type=PollType.HEAD_TO_HEAD,
        pollster=pollster, subject=subject, start_date=end, end_date=end,
        sample_size=None, population=None,
        answers=[PollAnswer(choice="Adam Hamilton", pct=dem, party="Democrat"),
                 PollAnswer(choice="Roger Marshall", pct=rep, party="Republican")],
    )


def test_duplicate_by_toplines_and_date_is_dropped_despite_pollster_spelling():
    base = [_poll("Siena/NYT", date(2026, 10, 28), 54.0, 40.0)]
    extra = [_poll("NY Times/Siena", date(2026, 10, 29), 54.0, 40.0)]  # off by a day
    assert merge_supplement(base, extra) == []


def test_distinct_poll_is_added_and_internal_duplicates_collapse():
    base = [_poll("Siena/NYT", date(2026, 10, 28), 54.0, 40.0)]
    extra = [
        _poll("Emerson", date(2026, 10, 30), 50.0, 47.0),
        _poll("Emerson College", date(2026, 10, 30), 50.0, 47.0),
        _poll("Emerson", date(2026, 10, 30), 50.0, 47.0, subject="Iowa Senate 2026"),
    ]
    added = merge_supplement(base, extra)
    assert [(p.pollster, p.subject) for p in added] == [
        ("Emerson", "Kansas Senate 2026"),
        ("Emerson", "Iowa Senate 2026"),
    ]
