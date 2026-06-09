"""Shared types for prediction-market odds (Polymarket, Kalshi).

Market quotes are *prices*, not polls, so they bypass the polling engine the
same way Silver Bulletin model CSVs do. Clients normalise everything into
``MarketOdds`` records; the refresh script serialises them to
``data/fallback/market_odds.csv`` so the export pipeline stays offline-safe.

Probabilities are expressed on a 0–1 scale and always from the Democratic
side (``dem_win_prob``); ``rep_win_prob`` is carried separately rather than
assumed to be the complement because some markets list third candidates.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

# Markets about who controls the chamber (vs. a single race).
KIND_RACE = "race"
KIND_CONTROL = "control"

_US_STATE_NAMES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
    "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "West Virginia", "Wisconsin", "Wyoming",
]


@dataclass
class MarketOdds:
    """One normalised prediction-market quote."""

    source: str  # "polymarket" | "kalshi"
    market_id: str
    title: str
    kind: str  # KIND_RACE | KIND_CONTROL
    state: str  # full state name for races, "" for control markets
    dem_win_prob: float | None  # 0–1
    rep_win_prob: float | None  # 0–1
    volume: float | None
    as_of: date
    url: str = ""

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "market_id": self.market_id,
            "title": self.title,
            "kind": self.kind,
            "state": self.state,
            "dem_win_prob": self.dem_win_prob,
            "rep_win_prob": self.rep_win_prob,
            "volume": self.volume,
            "as_of": self.as_of.isoformat(),
            "url": self.url,
        }


def detect_state(title: str) -> str:
    """Find a US state name in a market title ('' if none).

    Longest match wins so 'West Virginia' beats 'Virginia'.
    """
    found = ""
    for name in _US_STATE_NAMES:
        if re.search(rf"\b{re.escape(name)}\b", title, re.IGNORECASE) and len(name) > len(found):
            found = name
    return found


# ── CSV round-trip for the offline fallback file ─────────────────────────────

_CSV_COLUMNS = [
    "source", "market_id", "title", "kind", "state",
    "dem_win_prob", "rep_win_prob", "volume", "as_of", "url",
]


def odds_to_csv(odds: list[MarketOdds]) -> str:
    """Serialise quotes to the fallback CSV format (header always written)."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS)
    w.writeheader()
    for o in sorted(odds, key=lambda x: (x.kind, x.state, x.source)):
        w.writerow(o.to_dict())
    return buf.getvalue()


def load_odds_csv(path: Path) -> list[MarketOdds]:
    """Load quotes from the fallback CSV. Missing/empty file → empty list."""
    if not path.exists():
        return []
    odds: list[MarketOdds] = []
    for row in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))):
        try:
            odds.append(
                MarketOdds(
                    source=row["source"],
                    market_id=row["market_id"],
                    title=row["title"],
                    kind=row["kind"],
                    state=row.get("state", ""),
                    dem_win_prob=float(row["dem_win_prob"]) if row.get("dem_win_prob") else None,
                    rep_win_prob=float(row["rep_win_prob"]) if row.get("rep_win_prob") else None,
                    volume=float(row["volume"]) if row.get("volume") else None,
                    as_of=date.fromisoformat(row["as_of"]),
                    url=row.get("url", ""),
                )
            )
        except (KeyError, ValueError) as exc:
            logger.warning("Skipping malformed market_odds row: %s", exc)
    return odds
