"""Pollster rating and weighting system.

Manages pollster quality ratings from multiple sources (Silver Bulletin,
historical accuracy, manual overrides) and provides weight lookups for
the polling average engine.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.analysis.pollster_grades import GradeBook
from src.data.pollster_ratings import _UNKNOWN_DEFAULT

# Unknown pollsters get the survivorship-adjusted 25th-percentile default
# (~1.41), matching the engine and the documented ratings policy.
DEFAULT_RATING = _UNKNOWN_DEFAULT


class PollsterWeightManager:
    """Manage and query pollster quality ratings."""

    def __init__(self, ratings_path: Path | None = None) -> None:
        root = Path(__file__).resolve().parent.parent.parent
        self._ratings_path = ratings_path or (root / "config" / "pollster_ratings.json")
        self._ratings: dict[str, float] = {}
        # Our own fitted grades take precedence when they have been built.
        # They cover ~80% of live poll volume against the imported table's ~51%,
        # and they resolve sponsor-tagged and re-mastheaded names.
        self._grades: GradeBook | None = None
        grades_path = root / "config" / "pollster_grades.json"
        if ratings_path is None and grades_path.exists():
            self._grades = GradeBook(json.loads(grades_path.read_text()))
        self._load()

    def _load(self) -> None:
        if self._ratings_path.exists():
            data = json.loads(self._ratings_path.read_text())
            self._ratings = data.get("ratings", {})

    @property
    def grades(self) -> GradeBook | None:
        """The fitted grade book, if one has been built."""
        return self._grades

    def house_effect(self, pollster: str) -> float:
        """Fitted Democratic lean for this house, 0.0 when it has no record."""
        return self._grades.lean(pollster) if self._grades else 0.0

    def get_rating(self, pollster: str) -> float:
        """Get rating for a pollster. Returns DEFAULT_RATING if unknown."""
        if self._grades is not None:
            rec = self._grades.get(pollster)
            if rec is not None:
                return rec["quality"]
        # Try exact match first, then case-insensitive
        if pollster in self._ratings:
            return self._ratings[pollster]
        for name, rating in self._ratings.items():
            if name.lower() == pollster.lower():
                return rating
        if self._grades is not None:
            return self._grades.unknown_quality
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
