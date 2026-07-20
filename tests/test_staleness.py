"""Regression tests for the freshness guards.

Two silent-stall failure modes are covered:

1. A poll-of-polls row (e.g. an RCP average) carries a wide date range whose
   end date is recent, even when every underlying poll is weeks old. It must
   not be able to make a stalled feed look fresh.
2. VoteHub can return HTTP 200 with a payload whose newest poll is weeks old.
   A successful request is not proof of a healthy feed.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.data.base import Poll, PollAnswer, PollType
from src.data.votehub import VOTEHUB_STALE_AFTER_DAYS, VoteHubClient
from src.data.wikipedia_senate import is_aggregate_pollster


def _poll(pollster: str, end: date, days: int = 2) -> Poll:
    return Poll(
        poll_id=f"{pollster}-{end}",
        source="test",
        poll_type=PollType.GENERIC_BALLOT,
        pollster=pollster,
        subject="Generic Ballot",
        start_date=end - timedelta(days=days),
        end_date=end,
        sample_size=1000,
        population=None,
        answers=[PollAnswer("Democrat", 48.0), PollAnswer("Republican", 45.0)],
    )


def _newest_real_poll(polls: list[Poll]) -> date:
    """The freshness rule check_staleness.py applies: ignore aggregate rows,
    then take the newest end date."""
    real = [p for p in polls if not is_aggregate_pollster(p.pollster)]
    return max(p.end_date for p in real)


def test_rcp_average_cannot_mask_a_stalled_feed():
    today = date(2026, 7, 20)
    # Real polling stopped three weeks ago; the only "recent" row is an RCP
    # average whose range ends last week.
    polls = [
        _poll("YouGov", date(2026, 6, 29)),
        _poll("Emerson College", date(2026, 6, 30)),
        # RCP average: wide range ending July 14, but it is a poll-of-polls.
        Poll(
            poll_id="rcp",
            source="test",
            poll_type=PollType.GENERIC_BALLOT,
            pollster="RealClearPolitics",
            subject="Generic Ballot",
            start_date=date(2026, 6, 24),
            end_date=date(2026, 7, 14),
            sample_size=None,
            population=None,
            answers=[PollAnswer("Democrat", 49.0), PollAnswer("Republican", 44.0)],
        ),
    ]

    newest = _newest_real_poll(polls)
    # Without the guard the naive max end date is July 14 (6 days old); with it
    # the feed correctly reads as 20 days stale.
    assert newest == date(2026, 6, 30)
    assert (today - newest).days == 20
    assert (today - max(p.end_date for p in polls)).days == 6  # the masked value


def test_votehub_200_with_old_polls_is_flagged(caplog):
    client = VoteHubClient.__new__(VoteHubClient)  # no network/session needed
    stale = [_poll("YouGov", date.today() - timedelta(days=VOTEHUB_STALE_AFTER_DAYS + 12))]
    with caplog.at_level("WARNING"):
        age = client._warn_if_stale(stale, PollType.GENERIC_BALLOT)
    assert age == VOTEHUB_STALE_AFTER_DAYS + 12
    assert any("STALLED" in r.message for r in caplog.records)


def test_votehub_fresh_feed_is_not_flagged(caplog):
    client = VoteHubClient.__new__(VoteHubClient)
    fresh = [_poll("YouGov", date.today() - timedelta(days=1))]
    with caplog.at_level("WARNING"):
        age = client._warn_if_stale(fresh, PollType.GENERIC_BALLOT)
    assert age == 1
    assert not caplog.records
