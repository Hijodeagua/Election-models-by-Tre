"""Tests for the Wikipedia Senate poll scraper (pure parsing, no network)."""

from __future__ import annotations

from datetime import date

from src.data.base import PollType
from src.data.markets import _candidate_party_map, _party_from_candidate
from src.data.wikipedia_senate import (
    is_aggregate_pollster,
    parse_dates,
    parse_polling_tables,
)

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


# A race article as Wikipedia actually lays them out: the poll-*aggregation*
# table (RealClearPolitics / 270toWin, with the same candidate columns and a
# date column) sits ABOVE the individual-poll table. The parser must skip the
# aggregation table entirely and return the real polls below it — the July 2026
# Senate freeze was this table being accepted, yielding only aggregate rows,
# and the loop breaking before it reached the real polls.
AGGREGATION_FIRST_HTML = """
<table class="wikitable">
  <tr>
    <th>Source of poll aggregation</th><th>Dates administered</th>
    <th>Roy Cooper (D)</th><th>Michael Whatley (R)</th><th>Margin</th>
  </tr>
  <tr>
    <td>RealClearPolitics</td><td>May 4 - July 11, 2026</td>
    <td>49%</td><td>42%</td><td>7.0</td>
  </tr>
  <tr>
    <td>270toWin</td><td>June 23 - July 1, 2026</td>
    <td>49%</td><td>38%</td><td>11.0</td>
  </tr>
</table>
<table class="wikitable">
  <tr>
    <th>Poll source</th><th>Date(s) administered</th><th>Sample size</th>
    <th>Roy Cooper (D)</th><th>Michael Whatley (R)</th><th>Undecided</th>
  </tr>
  <tr>
    <td>East Carolina University</td><td>July 15-17, 2026</td><td>900 (RV)</td>
    <td>48%</td><td>44%</td><td>8%</td>
  </tr>
  <tr>
    <td>SurveyUSA</td><td>July 12-14, 2026</td><td>1,100 (LV)</td>
    <td>47%</td><td>45%</td><td>8%</td>
  </tr>
</table>
"""


def test_aggregation_table_is_skipped_for_individual_polls():
    polls = parse_polling_tables(
        AGGREGATION_FIRST_HTML,
        state="North Carolina",
        race="North Carolina Senate 2026",
        dem_candidate="Roy Cooper",
        rep_candidate="Michael Whatley",
    )
    # The aggregation table's RealClearPolitics/270toWin rows are dropped, and
    # the parser falls through to the real individual polls below it.
    pollsters = [p.pollster for p in polls]
    assert pollsters == ["East Carolina University", "SurveyUSA"]
    assert "RealClearPolitics" not in pollsters
    assert "270toWin" not in pollsters
    # The genuine newest poll (July 17) is now surfaced, not masked by the
    # aggregate's wide "through July 11" range.
    assert max(p.end_date for p in polls) == date(2026, 7, 17)


def test_is_aggregate_pollster_precision():
    # Poll-of-polls / model rows → excluded.
    for name in [
        "RealClearPolitics", "270toWin", "Race to the WH", "RCP Average",
        "538 aggregate", "Silver Bulletin", "Polling average", "FiveThirtyEight",
    ]:
        assert is_aggregate_pollster(name), name
    # Genuine pollsters that merely share a word → kept.
    for name in [
        "RealClear Opinion Research", "NewsNation/Decision Desk HQ",
        "Emerson College", "Quantus Insights (R)", "Trafalgar Group (R)",
        "The New York Times/Siena College",
    ]:
        assert not is_aggregate_pollster(name), name


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
