"""Tests for the prediction-market data layer (src/data/markets.py)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.data.markets import (
    SENATE_CONTROL_RACE,
    KalshiClient,
    MarketOdds,
    MarketOddsCsvSource,
    PolymarketClient,
    _json_list,
    odds_for_race,
    write_market_odds_csv,
)

FALLBACK_DIR = Path(__file__).resolve().parent.parent / "data" / "fallback"


def _odds(**overrides) -> MarketOdds:
    defaults = dict(
        as_of=date(2026, 5, 19),
        source="polymarket",
        race="Georgia Senate 2026",
        outcome="Democrat",
        probability=0.47,
    )
    defaults.update(overrides)
    return MarketOdds(**defaults)


class TestCsvRoundTrip:
    def test_committed_fallback_loads(self):
        odds = MarketOddsCsvSource(FALLBACK_DIR).load()
        assert len(odds) > 0
        assert all(0.0 <= o.probability <= 1.0 for o in odds)
        assert any(o.race == SENATE_CONTROL_RACE for o in odds)

    def test_round_trip(self, tmp_path):
        original = [_odds(), _odds(source="kalshi", probability=0.46, is_seed=True)]
        path = tmp_path / "market_odds.csv"
        write_market_odds_csv(original, path)
        loaded = MarketOddsCsvSource(tmp_path).load()
        assert len(loaded) == 2
        assert loaded[0].probability == 0.47
        assert loaded[1].source == "kalshi"
        assert loaded[1].is_seed is True
        assert loaded[0].is_seed is False

    def test_missing_file_returns_empty(self, tmp_path):
        assert MarketOddsCsvSource(tmp_path).load() == []

    def test_malformed_rows_skipped(self, tmp_path):
        (tmp_path / "market_odds.csv").write_text(
            "as_of,source,race,outcome,probability,url,is_seed\n"
            "2026-05-19,polymarket,X,Democrat,0.5,,false\n"
            "not-a-date,polymarket,X,Democrat,0.5,,false\n"
            "2026-05-19,polymarket,X,Democrat,not-a-number,,false\n"
        )
        loaded = MarketOddsCsvSource(tmp_path).load()
        assert len(loaded) == 1


class TestOddsForRace:
    def test_groups_by_source_and_outcome(self):
        odds = [
            _odds(),
            _odds(outcome="Republican", probability=0.53),
            _odds(source="kalshi", probability=0.46),
            _odds(race="Other race", probability=0.99),
        ]
        grouped = odds_for_race(odds, "Georgia Senate 2026")
        assert grouped == {
            "polymarket": {"Democrat": 0.47, "Republican": 0.53},
            "kalshi": {"Democrat": 0.46},
        }

    def test_most_recent_snapshot_wins(self):
        odds = [
            _odds(as_of=date(2026, 5, 1), probability=0.40),
            _odds(as_of=date(2026, 5, 19), probability=0.47),
        ]
        grouped = odds_for_race(odds, "Georgia Senate 2026")
        assert grouped["polymarket"]["Democrat"] == 0.47


class TestPolymarketParsing:
    def test_network_failure_returns_empty(self, monkeypatch):
        client = PolymarketClient()
        monkeypatch.setattr(
            client, "_get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
        )
        assert client.fetch_markets("Georgia Senate", race="Georgia Senate 2026") == []

    def test_parses_party_outcomes_from_search_events(self, monkeypatch):
        payload = {
            "events": [
                {"title": "Something unrelated", "slug": "x", "markets": []},
                {
                    "title": "Georgia Senate Election 2026",
                    "slug": "ga-senate-2026",
                    "markets": [
                        {
                            "question": "Which party wins?",
                            "outcomes": '["Democrat", "Republican"]',
                            "outcomePrices": '["0.47", "0.53"]',
                        }
                    ],
                },
            ]
        }
        client = PolymarketClient()
        monkeypatch.setattr(client, "_get", lambda *a, **k: payload)
        odds = client.fetch_markets(
            "Georgia Senate 2026",
            race="Georgia Senate 2026",
            required_tokens=("georgia", "senate"),
        )
        assert [(o.outcome, o.probability) for o in odds] == [
            ("Democrat", 0.47),
            ("Republican", 0.53),
        ]
        assert odds[0].url and "ga-senate-2026" in odds[0].url

    def test_yes_no_market_uses_question_party(self, monkeypatch):
        payload = {
            "events": [
                {
                    "title": "Georgia Senate Election 2026",
                    "slug": "ga",
                    "markets": [
                        {
                            "question": "Will a Republican win the Georgia Senate race?",
                            "outcomes": '["Yes", "No"]',
                            "outcomePrices": '["0.53", "0.47"]',
                        }
                    ],
                }
            ]
        }
        client = PolymarketClient()
        monkeypatch.setattr(client, "_get", lambda *a, **k: payload)
        odds = client.fetch_markets("q", race="r", required_tokens=("georgia",))
        # Only the Yes leg maps to a party; the No leg is ambiguous and skipped.
        assert [(o.outcome, o.probability) for o in odds] == [("Republican", 0.53)]

    def test_candidate_name_outcomes_skipped(self, monkeypatch):
        payload = {
            "events": [
                {
                    "title": "Georgia Senate Election 2026",
                    "slug": "ga",
                    "markets": [
                        {
                            "question": "Who wins?",
                            "outcomes": '["Ossoff", "Collins"]',
                            "outcomePrices": '["0.47", "0.53"]',
                        }
                    ],
                }
            ]
        }
        client = PolymarketClient()
        monkeypatch.setattr(client, "_get", lambda *a, **k: payload)
        assert client.fetch_markets("q", race="r", required_tokens=("georgia",)) == []


class TestKalshiParsing:
    def test_parses_cents_and_party(self, monkeypatch):
        payload = {
            "markets": [
                {
                    "ticker": "SENATEGA-26-D",
                    "title": "Georgia Senate winner?",
                    "yes_sub_title": "Democrat",
                    "last_price": 46,
                },
                {
                    "ticker": "SENATEGA-26-R",
                    "title": "Georgia Senate winner?",
                    "yes_sub_title": "Republican",
                    "last_price": 54,
                },
            ]
        }
        client = KalshiClient()
        monkeypatch.setattr(client, "_get", lambda *a, **k: payload)
        odds = client.fetch_race_odds("GA", race="Georgia Senate 2026")
        assert [(o.outcome, o.probability) for o in odds] == [
            ("Democrat", 0.46),
            ("Republican", 0.54),
        ]

    def test_single_party_market_gets_complement(self, monkeypatch):
        payload = {
            "markets": [
                {
                    "ticker": "SENATEME-26",
                    "title": "Maine Senate winner?",
                    "yes_sub_title": "Democrat",
                    "last_price": 70,
                }
            ]
        }
        client = KalshiClient()
        monkeypatch.setattr(client, "_get", lambda *a, **k: payload)
        odds = client.fetch_race_odds("ME", race="Maine Senate 2026")
        assert [(o.outcome, o.probability) for o in odds] == [
            ("Democrat", 0.70),
            ("Republican", 0.30),
        ]

    def test_control_filter_keeps_senate_only(self, monkeypatch):
        payload = {
            "markets": [
                {
                    "ticker": "CONTROLS-2026-HR",
                    "title": "Which party will win the U.S. House?",
                    "yes_sub_title": "Republican",
                    "last_price": 40,
                },
                {
                    "ticker": "CONTROLS-2026-SR",
                    "title": "Which party will win the U.S. Senate?",
                    "yes_sub_title": "Republican",
                    "last_price": 69,
                },
            ]
        }
        client = KalshiClient()
        monkeypatch.setattr(client, "_get", lambda *a, **k: payload)
        odds = client.fetch_control_odds(race="senate-control-2026")
        assert [(o.outcome, o.probability) for o in odds] == [
            ("Republican", 0.69),
            ("Democrat", 0.31),
        ]

    def test_network_failure_returns_empty(self, monkeypatch):
        client = KalshiClient()
        monkeypatch.setattr(
            client, "_get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
        )
        assert client.fetch_race_odds("GA", race="Georgia Senate 2026") == []


class TestJsonList:
    def test_passthrough_list(self):
        assert _json_list(["a"]) == ["a"]

    def test_json_string(self):
        assert _json_list('["a", "b"]') == ["a", "b"]

    def test_garbage_returns_empty(self):
        assert _json_list("not json") == []
        assert _json_list(None) == []
        assert _json_list('{"a": 1}') == []
