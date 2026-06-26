"""Tests for the Wikipedia Senate poll scraper (pure parsing, no network)."""

from __future__ import annotations

from datetime import date

from src.data.base import PollType
from src.data.markets import _candidate_party_map, _party_from_candidate
from src.data.wikipedia_senate import parse_dates, parse_polling_tables

# A realistic slice of a Wikipedia "General election polling" wikitable, with a
# same-month range, a cross-month range, an aggregate row (skipped) and a
# thousands-separated sample size.
FIXTURE_HTML = """
<table class="wikitable">
  <tr>
    <th>Poll source</th><th>Date(s) administered</th><th>Sample size</th>
    <th>Margin of error</th><th>Jon Ossoff (D)</th><th>Mike Collins (R)</th>
    <th>Other / Undecided</th>
  </tr>
  <tr>
    <td>Emerson College</td><td>October 1&ndash;5, 2026</td><td>800 (LV)</td>
    <td>&plusmn; 3.5%</td><td>47%</td><td>45%</td><td>8%</td>
  </tr>
  <tr>
    <td>Quinnipiac</td><td>September 28 &ndash; October 2, 2026</td>
    <td>1,050 (RV)</td><td>&plusmn; 2.9%</td><td>45%</td><td>46%</td><td>9%</td>
  </tr>
  <tr>
    <td>RCP Average</td><td>October 1&ndash;5, 2026</td><td>&ndash;</td>
    <td>&ndash;</td><td>46%</td><td>45.5%</td><td>&ndash;</td>
  </tr>
</table>
"""


def test_parse_polling_tables_extracts_matchup():
    polls = parse_polling_tables(
        FIXTURE_HTML,
        state="Georgia",
        race="Georgia Senate 2026",
        dem_candidate="Jon Ossoff",
        rep_candidate="Mike Collins",
    )
    # Two real polls; the aggregate "RCP Average" row is dropped.
    assert len(polls) == 2

    emerson = polls[0]
    assert emerson.pollster == "Emerson College"
    assert emerson.poll_type == PollType.HEAD_TO_HEAD
    assert emerson.subject == "Georgia Senate 2026"
    assert emerson.start_date == date(2026, 10, 1)
    assert emerson.end_date == date(2026, 10, 5)
    assert emerson.sample_size == 800
    answers = {a.choice: a.pct for a in emerson.answers}
    assert answers == {"Jon Ossoff": 47.0, "Mike Collins": 45.0}

    quinnipiac = polls[1]
    assert quinnipiac.start_date == date(2026, 9, 28)
    assert quinnipiac.end_date == date(2026, 10, 2)
    assert quinnipiac.sample_size == 1050


def test_parse_polling_tables_no_match_returns_empty():
    # Candidate names that don't appear → no usable matchup → empty, not error.
    polls = parse_polling_tables(
        FIXTURE_HTML, "Georgia", "Georgia Senate 2026", "Jane Doe", "John Roe"
    )
    assert polls == []


def test_parse_dates_variants():
    assert parse_dates("October 1-5, 2026", 2026) == (date(2026, 10, 1), date(2026, 10, 5))
    assert parse_dates("September 28 - October 2, 2026", 2026) == (
        date(2026, 9, 28),
        date(2026, 10, 2),
    )
    assert parse_dates("October 5, 2026", 2026) == (date(2026, 10, 5), date(2026, 10, 5))
    assert parse_dates("not a date", 2026) is None


def test_kalshi_candidate_party_mapping():
    mapping = _candidate_party_map("Jon Ossoff", "Mike Collins")
    assert mapping == {"ossoff": "Democrat", "collins": "Republican"}
    # Kalshi labels the YES side by candidate name, not party.
    assert _party_from_candidate(mapping, "Ossoff") == "Democrat"
    assert _party_from_candidate(mapping, "Will Mike Collins win?") == "Republican"
    assert _party_from_candidate(mapping, "Someone else") is None
