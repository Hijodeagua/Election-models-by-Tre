"""Pollster rating and weighting system.

Manages pollster quality ratings from multiple sources (Silver Bulletin,
historical accuracy, manual overrides) and provides weight lookups for
the polling average engine.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_RATING = 1.5  # Unknown pollsters get a middling rating


class PollsterWeightManager:
    """Manage and query pollster quality ratings."""

    def __init__(self, ratings_path: Path | None = None) -> None:
        self._ratings_path = ratings_path or (
            Path(__file__).resolve().parent.parent.parent / "config" / "pollster_ratings.json"
        )
        self._ratings: dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        if self._ratings_path.exists():
            data = json.loads(self._ratings_path.read_text())
            self._ratings = data.get("ratings", {})

    def get_rating(self, pollster: str) -> float:
        """Get rating for a pollster. Returns DEFAULT_RATING if unknown."""
        # Try exact match first, then case-insensitive
        if pollster in self._ratings:
            return self._ratings[pollster]
        for name, rating in self._ratings.items():
            if name.lower() == pollster.lower():
                return rating
        return DEFAULT_RATING

    def set_rating(self, pollster: str, rating: float) -> None:
        """Set or update a pollster's rating."""
        if not 0.0 <= rating <= 3.0:
            raise ValueError(f"Rating must be 0.0–3.0, got {rating}")
        self._ratings[pollster] = rating

    def save(self) -> None:
        """Persist ratings to disk."""
        data = {
            "_meta": {
                "description": "Pollster quality ratings (0-3 scale).",
                "scale": "0.0 (banned/unreliable) to 3.0 (gold standard)",
            },
            "ratings": self._ratings,
        }
        self._ratings_path.write_text(json.dumps(data, indent=2))

    @property
    def all_ratings(self) -> dict[str, float]:
        return dict(self._ratings)
