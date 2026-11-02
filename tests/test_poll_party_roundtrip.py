"""Regression tests for two refresh bugs seen on 2026-11-02.

1. The Senate poll CSV dropped the party tags the Wikipedia scraper attaches,
   so races with no configured nominee lost their polls on export.
2. Polymarket's title match on "virginia" picked up West Virginia's market.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from scripts.refresh_data import _MARKET_TITLE_EXCLUSIONS, _polls_to_votehub_csv
from src.data.base import Poll, PollAnswer, PollType, Population
from src.data.markets import PolymarketClient
from src.data.votehub_csv import VoteHubCsvLoader


def _poll(dem: str, rep: str, dem_pct: float, rep_pct: float) -> Poll:
    return Poll(
        poll_id="wikipedia-minnesota-2026-10-20-0",
        source="wikipedia",
        poll_type=PollType.HEAD_TO_HEAD,
        pollster="Test Pollster",
        subject="Minnesota Senate 2026",
        start_date=date(2026, 10, 15),
        end_date=date(2026, 10, 20),
        sample_size=800,
        population=Population.LIKELY_VOTERS,
        answers=[
            PollAnswer(choice=dem, pct=dem_pct, party="Democrat"),
            PollAnswer(choice=rep, pct=rep_pct, party="Republican"),
        ],
    )


def test_senate_csv_round_trip_keeps_party_tags(tmp_path: Path):
    # Republican leads so the Dem is the *trailing* answer — both must keep a tag.
    csv_text = _polls_to_votehub_csv([_poll("Peggy Flanagan", "Royce White", 44.0, 47.0)])
    assert "Leading Party" in csv_text.splitlines()[0]
    path = tmp_path / "votehub_senate.csv"
    path.write_text(csv_text)
    polls = VoteHubCsvLoader(poll_type=PollType.HEAD_TO_HEAD).load(path)
    assert len(polls) == 1
    by_name = {a.choice: a.party for a in polls[0].answers}
    assert by_name == {"Royce White": "Republican", "Peggy Flanagan": "Democrat"}


def test_generic_ballot_style_rows_still_use_party_as_choice(tmp_path: Path):
    # VoteHub generic-ballot files have no Result name; the Party column is the
    # choice itself and must not be read as a tag.
    header = (
        "Date Range,Grade,Pollster,Subject,Sponsor,Sample Size,Sample Type,Population,"
        "Weight,Leading Result,Leading %,Trailing Result,Trailing %,Spread,"
        "Leading Party,Trailing Party\n"
    )
    row = "Oct. 15-20,,Test Pollster,Generic Ballot,,800,,lv,,,47%,,44%,3.0,Democrat,Republican\n"
    path = tmp_path / "votehub_generic_ballot.csv"
    path.write_text(header + row)
    polls = VoteHubCsvLoader(poll_type=PollType.GENERIC_BALLOT).load(path)
    assert len(polls) == 1
    assert [(a.choice, a.party) for a in polls[0].answers] == [
        ("Democrat", None),
        ("Republican", None),
    ]


def test_polymarket_excluded_tokens_skip_lookalike_state(monkeypatch):
    payload = {
        "events": [
            {
                "title": "West Virginia Senate Election Winner",
                "slug": "west-virginia-senate-election-winner",
                "markets": [
                    {
                        "question": "Which party wins?",
                        "outcomes": '["Democrat", "Republican"]',
                        "outcomePrices": '["0.01", "0.99"]',
                    }
                ],
            },
            {
                "title": "Virginia Senate Election Winner",
                "slug": "virginia-senate-election-winner",
                "markets": [
                    {
                        "question": "Which party wins?",
                        "outcomes": '["Democrat", "Republican"]',
                        "outcomePrices": '["0.95", "0.05"]',
                    }
                ],
            },
        ]
    }
    client = PolymarketClient()
    monkeypatch.setattr(client, "_get", lambda *a, **k: payload)
    odds = client.fetch_markets(
        "Virginia Senate 2026",
        race="Virginia Senate 2026",
        required_tokens=("virginia", "senate"),
        excluded_tokens=_MARKET_TITLE_EXCLUSIONS["Virginia"],
    )
    assert [(o.outcome, o.probability) for o in odds] == [("Democrat", 0.95), ("Republican", 0.05)]
    assert all("west-virginia" not in (o.url or "") for o in odds)
    # Without the exclusion the first (wrong) event would have been taken.
    wrong = client.fetch_markets("q", race="r", required_tokens=("virginia", "senate"))
    assert wrong and "west-virginia" in (wrong[0].url or "")
