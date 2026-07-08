"""Tests for the Wikipedia national approval/generic-ballot fallback."""

from __future__ import annotations

from datetime import date, timedelta

from src.data.base import Poll, PollAnswer, PollType, Population
from src.data.wikipedia_national import parse_national_tables, polls_newer_than

APPROVAL_HTML = """
<h3>July 2026</h3>
<table class="wikitable">
  <tr><th>Poll source</th><th>Date(s) administered</th><th>Sample size[a]</th>
      <th>Approve</th><th>Disapprove</th><th>Undecided</th></tr>
  <tr><td>YouGov/The Economist</td><td>July 5-7, 2026</td><td>1,500 (RV)</td>
      <td>41%</td><td>56%</td><td>3%</td></tr>
  <tr><td>RCP Average</td><td>July 1-7, 2026</td><td>-</td>
      <td>42%</td><td>55%</td><td>-</td></tr>
  <tr><td>Quinnipiac University</td><td>June 30 - July 3, 2026</td><td>982 (A)</td>
      <td>39%</td><td>57%</td><td>4%</td></tr>
</table>
<h3>June 2026</h3>
<table class="wikitable">
  <tr><th>Poll source</th><th>Date(s) administered</th><th>Sample size[a]</th>
      <th>Approve</th><th>Disapprove</th><th>Undecided</th></tr>
  <tr><td>Gallup</td><td>June 20-25, 2026</td><td>1,010 (A)</td>
      <td>40%</td><td>56%</td><td>4%</td></tr>
</table>
"""

GENERIC_BALLOT_HTML = """
<table class="wikitable">
  <tr><th>Poll source</th><th>Date(s) administered</th><th>Sample size[b]</th>
      <th>Margin of error</th><th>Democratic</th><th>Republican</th><th>Other</th></tr>
  <tr><td>Emerson College</td><td>July 3-5, 2026</td><td>1,200 (LV)</td>
      <td>± 2.8%</td><td>48%</td><td>43%</td><td>9%</td></tr>
  <tr><td>538 aggregate</td><td>July 1-6, 2026</td><td>-</td>
      <td>-</td><td>47%</td><td>44%</td><td>-</td></tr>
</table>
"""


class TestApprovalParsing:
    def test_parses_all_tables_and_skips_aggregates(self):
        polls = parse_national_tables(APPROVAL_HTML, PollType.APPROVAL)
        # 3 real polls across two monthly tables; the RCP Average row dropped
        assert len(polls) == 3
        pollsters = {p.pollster for p in polls}
        assert "RCP Average" not in pollsters
        assert {"YouGov/The Economist", "Quinnipiac University", "Gallup"} == pollsters

    def test_normalized_fields(self):
        polls = parse_national_tables(APPROVAL_HTML, PollType.APPROVAL)
        yg = next(p for p in polls if "YouGov" in p.pollster)
        assert yg.poll_type == PollType.APPROVAL
        assert yg.subject == "Donald Trump"
        assert yg.start_date == date(2026, 7, 5)
        assert yg.end_date == date(2026, 7, 7)
        assert yg.sample_size == 1500
        assert yg.population == Population.REGISTERED_VOTERS
        assert {a.choice: a.pct for a in yg.answers} == {
            "Approve": 41.0, "Disapprove": 56.0,
        }

    def test_cross_month_dates(self):
        polls = parse_national_tables(APPROVAL_HTML, PollType.APPROVAL)
        q = next(p for p in polls if "Quinnipiac" in p.pollster)
        assert q.start_date == date(2026, 6, 30)
        assert q.end_date == date(2026, 7, 3)


class TestGenericBallotParsing:
    def test_parses_and_labels_parties(self):
        polls = parse_national_tables(GENERIC_BALLOT_HTML, PollType.GENERIC_BALLOT)
        assert len(polls) == 1  # aggregate row dropped
        p = polls[0]
        assert p.poll_type == PollType.GENERIC_BALLOT
        assert p.subject == "Generic Ballot"
        assert {a.choice: a.pct for a in p.answers} == {
            "Democrat": 48.0, "Republican": 43.0,
        }
        assert p.population == Population.LIKELY_VOTERS

    def test_no_tables_returns_empty(self):
        assert parse_national_tables("<p>nothing here</p>", PollType.APPROVAL) == []


class TestPollsNewerThan:
    def _poll(self, end: date) -> Poll:
        return Poll(
            poll_id=f"t-{end}", source="test", poll_type=PollType.APPROVAL,
            pollster="T", subject="Donald Trump",
            start_date=end - timedelta(days=2), end_date=end,
            sample_size=1000, population=None,
            answers=[PollAnswer("Approve", 40.0), PollAnswer("Disapprove", 55.0)],
        )

    def test_strictly_newer(self):
        cutoff = date(2026, 7, 1)
        polls = [self._poll(date(2026, 6, 30)), self._poll(cutoff),
                 self._poll(date(2026, 7, 2))]
        kept = polls_newer_than(polls, cutoff)
        assert [p.end_date for p in kept] == [date(2026, 7, 2)]


class TestStaleTopup:
    """The refresh-time trigger: only engage past the staleness threshold."""

    def _polls(self, newest_age_days: int, n: int = 5) -> list[Poll]:
        newest = date.today() - timedelta(days=newest_age_days)
        return [
            Poll(
                poll_id=f"vh-{i}", source="votehub", poll_type=PollType.APPROVAL,
                pollster=f"P{i}", subject="Donald Trump",
                start_date=newest - timedelta(days=3 + i),
                end_date=newest - timedelta(days=i),
                sample_size=900, population=None,
                answers=[PollAnswer("Approve", 40.0), PollAnswer("Disapprove", 55.0)],
            )
            for i in range(n)
        ]

    def test_fresh_feed_untouched(self, monkeypatch):
        from scripts import refresh_data

        called = {"fetch": False}

        class FakeSource:
            def __init__(self, **kw): ...
            def __enter__(self): return self
            def __exit__(self, *a): ...
            def fetch_polls(self, **kw):
                called["fetch"] = True
                return []

        import src.data.wikipedia_national as wn
        monkeypatch.setattr(wn, "WikipediaNationalSource", FakeSource)
        polls = self._polls(newest_age_days=1)
        out = refresh_data._wikipedia_topup(polls, PollType.APPROVAL, "approval")
        assert out == polls
        assert called["fetch"] is False  # under threshold — no network attempt

    def test_stale_feed_topped_up(self, monkeypatch):
        from scripts import refresh_data

        fresh_end = date.today() - timedelta(days=1)

        class FakeSource:
            def __init__(self, **kw): ...
            def __enter__(self): return self
            def __exit__(self, *a): ...
            def fetch_polls(self, **kw):
                return [Poll(
                    poll_id="wiki-1", source="wikipedia",
                    poll_type=PollType.APPROVAL, pollster="Gallup",
                    subject="Donald Trump",
                    start_date=fresh_end - timedelta(days=3), end_date=fresh_end,
                    sample_size=1000, population=None,
                    answers=[PollAnswer("Approve", 41.0), PollAnswer("Disapprove", 55.0)],
                )]

        import src.data.wikipedia_national as wn
        monkeypatch.setattr(wn, "WikipediaNationalSource", FakeSource)
        stale = self._polls(newest_age_days=10)
        out = refresh_data._wikipedia_topup(stale, PollType.APPROVAL, "approval")
        assert len(out) == len(stale) + 1
        assert out[-1].source == "wikipedia"
        assert out[-1].end_date == fresh_end

    def test_senate_type_never_topped_up(self):
        from scripts import refresh_data

        polls = self._polls(newest_age_days=30)
        for p in polls:
            p.poll_type = PollType.HEAD_TO_HEAD
        out = refresh_data._wikipedia_topup(polls, PollType.HEAD_TO_HEAD, "senate")
        assert out == polls
