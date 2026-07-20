"""VoteHub API client — free, CC BY 4.0 polling data.

API docs: https://votehub.com/polls/api/
Endpoints:
    GET /polls          — all polls (filterable by poll_type, subject, pollster)
    GET /polls/{id}     — single poll
    GET /pollsters      — list of pollster names
    GET /subjects       — list of subjects
    GET /poll-types     — list of poll types
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from src.data.base import DataSource, Poll, PollAnswer, PollType, Population

logger = logging.getLogger(__name__)

# A 200 OK with only weeks-old polls is a stalled upstream, not a healthy feed.
# VoteHub's approval and generic-ballot feeds did exactly this for 10+ days in
# July 2026 — same payload, HTTP 200 every run — and nothing noticed because
# the request "succeeded". Fetches older than this are flagged loudly so a
# silent stall can't masquerade as fresh data.
VOTEHUB_STALE_AFTER_DAYS = 3


def _parse_population(raw: str | None) -> Population | None:
    if raw is None:
        return None
    mapping = {
        "lv": Population.LIKELY_VOTERS,
        "rv": Population.REGISTERED_VOTERS,
        "a": Population.ADULTS,
    }
    return mapping.get(raw.lower())


def _parse_poll_type(raw: str | None) -> PollType:
    if raw is None:
        return PollType.APPROVAL
    mapping = {
        "approval": PollType.APPROVAL,
        "favorability": PollType.FAVORABILITY,
        "generic-ballot": PollType.GENERIC_BALLOT,
        "head-to-head": PollType.HEAD_TO_HEAD,
        "primary": PollType.PRIMARY,
    }
    return mapping.get(raw.lower(), PollType.APPROVAL)


def _parse_date(raw: str) -> date:
    return date.fromisoformat(raw)


class VoteHubClient(DataSource):
    """Client for the VoteHub free polling API."""

    name = "votehub"

    def __init__(
        self,
        base_url: str | None = None,
        cache_dir: Path | None = None,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(cache_dir=cache_dir)
        self.base_url = (base_url or settings.votehub_base_url).rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> VoteHubClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ── Public API ────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Make a GET request with automatic retry on transient failures."""
        resp = self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    def fetch_polls(
        self,
        poll_type: PollType | None = None,
        subject: str | None = None,
        pollster: str | None = None,
        **kwargs: Any,
    ) -> list[Poll]:
        """Fetch polls from VoteHub, optionally filtered."""
        params: dict[str, str] = {}
        if poll_type:
            params["poll_type"] = poll_type.value
        if subject:
            params["subject"] = subject
        if pollster:
            params["pollster"] = pollster

        # Check cache first
        cache_key = self._cache_key("polls", str(params))
        cached = self._read_cache(cache_key)
        if cached is not None:
            raw_polls = cached
        else:
            raw_polls = self._get("/polls", params=params)
            self._write_cache(cache_key, raw_polls)

        polls = [self._normalize(p) for p in raw_polls]
        self._warn_if_stale(polls, poll_type)
        return polls

    def _warn_if_stale(
        self, polls: list[Poll], poll_type: PollType | None
    ) -> int | None:
        """Flag a feed whose newest poll is older than the staleness threshold,
        even though the HTTP request succeeded. Returns the age in days of the
        newest poll (None when the feed is empty). Never raises — a monitoring
        aid, not a gate."""
        ends = [p.end_date for p in polls if p.end_date]
        if not ends:
            return None
        newest = max(ends)
        age = (date.today() - newest).days
        if age > VOTEHUB_STALE_AFTER_DAYS:
            label = poll_type.value if poll_type else "polls"
            logger.warning(
                "VoteHub returned HTTP 200 for %s but its newest poll is %s "
                "(%dd old, threshold %dd) — treating the feed as STALLED, not "
                "healthy.",
                label, newest, age, VOTEHUB_STALE_AFTER_DAYS,
            )
            # GitHub Actions annotation so the stall is loud on the run summary.
            print(
                f"::warning title=VoteHub feed stalled::{label}: HTTP 200 but "
                f"newest poll is {newest} ({age}d old, threshold "
                f"{VOTEHUB_STALE_AFTER_DAYS}d)."
            )
        return age

    def fetch_poll_by_id(self, poll_id: str) -> Poll:
        """Fetch a single poll by its VoteHub ID."""
        raw = self._get(f"/polls/{poll_id}")
        return self._normalize(raw)

    def fetch_pollsters(self) -> list[str]:
        """Return all known pollster names."""
        cache_key = self._cache_key("pollsters")
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached
        result = self._get("/pollsters")
        self._write_cache(cache_key, result)
        return result

    def fetch_subjects(self) -> list[str]:
        """Return all known subjects (e.g., 'Donald Trump', 'Congress')."""
        cache_key = self._cache_key("subjects")
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached
        result = self._get("/subjects")
        self._write_cache(cache_key, result)
        return result

    def fetch_poll_types(self) -> list[str]:
        """Return available poll types."""
        cache_key = self._cache_key("poll-types")
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached
        result = self._get("/poll-types")
        self._write_cache(cache_key, result)
        return result

    # ── Normalization ─────────────────────────────────────────────────

    def _normalize(self, raw: dict[str, Any]) -> Poll:
        """Convert a raw VoteHub API response dict into a normalized Poll."""
        answers = [
            PollAnswer(choice=a["choice"], pct=float(a["pct"]))
            for a in raw.get("answers", [])
        ]

        return Poll(
            poll_id=f"votehub-{raw['id']}",
            source=self.name,
            poll_type=_parse_poll_type(raw.get("poll_type")),
            pollster=raw.get("pollster", "Unknown"),
            subject=raw.get("subject", ""),
            start_date=_parse_date(raw["start_date"]),
            end_date=_parse_date(raw["end_date"]),
            sample_size=raw.get("sample_size"),
            population=_parse_population(raw.get("population")),
            answers=answers,
            sponsors=raw.get("sponsors", []),
            partisan=bool(raw.get("partisan", False)),
            internal=bool(raw.get("internal", False)),
            raw=raw,
        )
