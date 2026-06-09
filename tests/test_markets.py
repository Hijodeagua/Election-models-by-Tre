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
        # Seed snapshot is flagged so the UI can label it.
        assert all(o.is_seed for o in odds)

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


class TestClientParsing:
    def test_polymarket_network_failure_returns_empty(self, monkeypatch):
        client = PolymarketClient()
        monkeypatch.setattr(
            client, "_get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
        )
        assert client.fetch_markets("Georgia Senate", race="Georgia Senate 2026") == []

    def test_polymarket_parses_gamma_payload(self, monkeypatch):
        payload = [
            {
                "slug": "ga-senate",
                "outcomes": '["Democrat", "Republican"]',
                "outcomePrices": '["0.47", "0.53"]',
            }
        ]
        client = PolymarketClient()
        monkeypatch.setattr(client, "_get", lambda *a, **k: payload)
        odds = client.fetch_markets("Georgia Senate", race="Georgia Senate 2026")
        assert len(odds) == 2
        assert odds[0].outcome == "Democrat"
        assert odds[0].probability == 0.47
        assert odds[0].url and "ga-senate" in odds[0].url

    def test_kalshi_parses_cents(self, monkeypatch):
        payload = {
            "markets": [
                {"ticker": "KXSENATEGA-26", "last_price": 46, "yes_sub_title": "Democrat"}
            ]
        }
        client = KalshiClient()
        monkeypatch.setattr(client, "_get", lambda *a, **k: payload)
        odds = client.fetch_markets("KXSENATEGA", race="Georgia Senate 2026", outcome="Democrat")
        assert len(odds) == 1
        assert odds[0].probability == 0.46
        assert odds[0].source == "kalshi"

    def test_kalshi_network_failure_returns_empty(self, monkeypatch):
        client = KalshiClient()
        monkeypatch.setattr(
            client, "_get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
        )
        assert client.fetch_markets("X", race="Y", outcome="Democrat") == []


class TestJsonList:
    def test_passthrough_list(self):
        assert _json_list(["a"]) == ["a"]

    def test_json_string(self):
        assert _json_list('["a", "b"]') == ["a", "b"]

    def test_garbage_returns_empty(self):
        assert _json_list("not json") == []
        assert _json_list(None) == []
        assert _json_list('{"a": 1}') == []
