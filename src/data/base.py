"""Abstract base class for all polling data sources."""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any


class PollType(str, Enum):
    APPROVAL = "approval"
    FAVORABILITY = "favorability"
    GENERIC_BALLOT = "generic-ballot"
    HEAD_TO_HEAD = "head-to-head"
    PRIMARY = "primary"


class Population(str, Enum):
    LIKELY_VOTERS = "lv"
    REGISTERED_VOTERS = "rv"
    ADULTS = "a"


@dataclass
class PollAnswer:
    """A single answer choice within a poll (e.g., 'Approve 45%')."""

    choice: str
    pct: float

    def to_dict(self) -> dict[str, Any]:
        return {"choice": self.choice, "pct": self.pct}


@dataclass
class Poll:
    """Normalized poll record — common schema across all data sources."""

    poll_id: str
    source: str  # e.g., "votehub", "rcp", "fiftyplusone"
    poll_type: PollType
    pollster: str
    subject: str  # e.g., "Donald Trump", "Congress", "PA-Senate"
    start_date: date
    end_date: date
    sample_size: int | None
    population: Population | None
    answers: list[PollAnswer]
    sponsors: list[str] = field(default_factory=list)
    partisan: bool = False
    internal: bool = False
    url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def midpoint_date(self) -> date:
        """Midpoint of the polling field period."""
        delta = (self.end_date - self.start_date).days // 2
        return self.start_date + __import__("datetime").timedelta(days=delta)

    @property
    def age_days(self) -> int:
        """Days since the poll's midpoint."""
        return (date.today() - self.midpoint_date).days

    def to_dict(self) -> dict[str, Any]:
        return {
            "poll_id": self.poll_id,
            "source": self.source,
            "poll_type": self.poll_type.value,
            "pollster": self.pollster,
            "subject": self.subject,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "sample_size": self.sample_size,
            "population": self.population.value if self.population else None,
            "answers": [a.to_dict() for a in self.answers],
            "sponsors": self.sponsors,
            "partisan": self.partisan,
            "internal": self.internal,
            "url": self.url,
        }


class DataSource(ABC):
    """Interface every data source must implement.

    Subclasses handle API-specific details and normalize results into Poll objects.
    Raw responses can optionally be cached to disk to reduce API load.
    """

    name: str  # e.g., "votehub"

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    # ── Required methods ──────────────────────────────────────────────

    @abstractmethod
    def fetch_polls(
        self,
        poll_type: PollType | None = None,
        subject: str | None = None,
        **kwargs: Any,
    ) -> list[Poll]:
        """Fetch polls, optionally filtered. Returns normalized Poll objects."""
        ...

    @abstractmethod
    def fetch_pollsters(self) -> list[str]:
        """Return list of known pollster names from this source."""
        ...

    # ── Caching helpers ───────────────────────────────────────────────

    def _cache_key(self, *parts: str) -> str:
        raw = ":".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _read_cache(self, key: str) -> dict | list | None:
        if not self.cache_dir:
            return None
        path = self.cache_dir / f"{self.name}_{key}.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def _write_cache(self, key: str, data: dict | list) -> None:
        if not self.cache_dir:
            return
        path = self.cache_dir / f"{self.name}_{key}.json"
        path.write_text(json.dumps(data, default=str, indent=2))
