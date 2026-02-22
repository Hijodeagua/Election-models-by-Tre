"""Tests for data source clients."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.data.base import DataSource, Poll, PollAnswer, PollType, Population
from src.data.votehub import VoteHubClient, _parse_date, _parse_poll_type, _parse_population


# ── Poll dataclass tests ──────────────────────────────────────────────


class TestPollDataclass:
    def test_poll_creation(self):
        poll = Poll(
            poll_id="test-1",
            source="test",
            poll_type=PollType.APPROVAL,
            pollster="Test Pollster",
            subject="Donald Trump",
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 5),
            sample_size=1000,
            population=Population.LIKELY_VOTERS,
            answers=[
                PollAnswer(choice="Approve", pct=45.0),
                PollAnswer(choice="Disapprove", pct=52.0),
            ],
        )
        assert poll.poll_id == "test-1"
        assert poll.source == "test"
        assert len(poll.answers) == 2
        assert poll.answers[0].pct == 45.0

    def test_poll_midpoint_date(self):
        poll = Poll(
            poll_id="test-2",
            source="test",
            poll_type=PollType.APPROVAL,
            pollster="Test",
            subject="Test",
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 5),
            sample_size=800,
            population=None,
            answers=[],
        )
        assert poll.midpoint_date == date(2026, 2, 3)

    def test_poll_to_dict(self):
        poll = Poll(
            poll_id="test-3",
            source="test",
            poll_type=PollType.GENERIC_BALLOT,
            pollster="ABC/Ipsos",
            subject="Generic Ballot",
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 18),
            sample_size=1200,
            population=Population.REGISTERED_VOTERS,
            answers=[PollAnswer(choice="Democrat", pct=48.0)],
            partisan=False,
        )
        d = poll.to_dict()
        assert d["poll_type"] == "generic-ballot"
        assert d["population"] == "rv"
        assert len(d["answers"]) == 1

    def test_poll_type_enum(self):
        assert PollType.APPROVAL.value == "approval"
        assert PollType.GENERIC_BALLOT.value == "generic-ballot"
        assert PollType.FAVORABILITY.value == "favorability"

    def test_population_enum(self):
        assert Population.LIKELY_VOTERS.value == "lv"
        assert Population.REGISTERED_VOTERS.value == "rv"
        assert Population.ADULTS.value == "a"


# ── VoteHub parsing helpers ───────────────────────────────────────────


class TestVoteHubParsing:
    def test_parse_population_lv(self):
        assert _parse_population("lv") == Population.LIKELY_VOTERS
        assert _parse_population("LV") == Population.LIKELY_VOTERS

    def test_parse_population_rv(self):
        assert _parse_population("rv") == Population.REGISTERED_VOTERS

    def test_parse_population_adults(self):
        assert _parse_population("a") == Population.ADULTS

    def test_parse_population_none(self):
        assert _parse_population(None) is None

    def test_parse_population_unknown(self):
        assert _parse_population("xyz") is None

    def test_parse_poll_type(self):
        assert _parse_poll_type("approval") == PollType.APPROVAL
        assert _parse_poll_type("generic-ballot") == PollType.GENERIC_BALLOT
        assert _parse_poll_type("favorability") == PollType.FAVORABILITY

    def test_parse_poll_type_none(self):
        assert _parse_poll_type(None) == PollType.APPROVAL

    def test_parse_date(self):
        assert _parse_date("2026-02-15") == date(2026, 2, 15)


# ── VoteHub client normalization ──────────────────────────────────────


class TestVoteHubNormalization:
    def _make_client(self) -> VoteHubClient:
        return VoteHubClient(base_url="https://example.com/api")

    def test_normalize_poll(self):
        client = self._make_client()
        raw = {
            "id": 42,
            "poll_type": "approval",
            "pollster": "Marist College",
            "subject": "Donald Trump",
            "start_date": "2026-02-01",
            "end_date": "2026-02-05",
            "sample_size": 1100,
            "population": "lv",
            "answers": [
                {"choice": "Approve", "pct": 44},
                {"choice": "Disapprove", "pct": 53},
            ],
            "sponsors": [],
            "partisan": False,
            "internal": False,
        }
        poll = client._normalize(raw)
        assert poll.poll_id == "votehub-42"
        assert poll.source == "votehub"
        assert poll.pollster == "Marist College"
        assert poll.poll_type == PollType.APPROVAL
        assert poll.sample_size == 1100
        assert poll.population == Population.LIKELY_VOTERS
        assert len(poll.answers) == 2
        assert poll.answers[0].choice == "Approve"
        assert poll.answers[0].pct == 44.0

    def test_normalize_poll_missing_optional_fields(self):
        client = self._make_client()
        raw = {
            "id": 99,
            "poll_type": "favorability",
            "start_date": "2026-01-10",
            "end_date": "2026-01-12",
            "answers": [{"choice": "Favorable", "pct": 38}],
        }
        poll = client._normalize(raw)
        assert poll.poll_id == "votehub-99"
        assert poll.pollster == "Unknown"
        assert poll.sample_size is None
        assert poll.population is None
        assert poll.partisan is False


# ── DataSource cache tests ────────────────────────────────────────────


class TestCaching:
    def test_cache_key_deterministic(self):
        client = VoteHubClient(base_url="https://example.com/api")
        key1 = client._cache_key("polls", "type=approval")
        key2 = client._cache_key("polls", "type=approval")
        assert key1 == key2

    def test_cache_key_differs_for_different_inputs(self):
        client = VoteHubClient(base_url="https://example.com/api")
        key1 = client._cache_key("polls", "type=approval")
        key2 = client._cache_key("polls", "type=generic-ballot")
        assert key1 != key2

    def test_cache_write_and_read(self, tmp_path: Path):
        client = VoteHubClient(base_url="https://example.com/api", cache_dir=tmp_path)
        data = [{"id": 1, "value": "test"}]
        client._write_cache("test_key", data)
        result = client._read_cache("test_key")
        assert result == data

    def test_cache_read_miss(self, tmp_path: Path):
        client = VoteHubClient(base_url="https://example.com/api", cache_dir=tmp_path)
        result = client._read_cache("nonexistent")
        assert result is None
