"""Race rating ingestion from major forecasters.

Sources:
    - Cook Political Report (Solid/Likely/Lean/Toss-up)
    - Sabato's Crystal Ball
    - Inside Elections
    - FiveThirtyEight historical forecasts (GitHub archive)
    - RealClearPolitics race ratings
    - Silver Bulletin (when available)
    - Politico race ratings

Ratings are normalized to a common scale and converted to numeric
win probabilities for regression analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class RatingScale(StrEnum):
    """Normalized 7-point rating scale used across all forecasters."""

    SOLID_D = "solid_d"
    LIKELY_D = "likely_d"
    LEAN_D = "lean_d"
    TOSSUP = "tossup"
    LEAN_R = "lean_r"
    LIKELY_R = "likely_r"
    SOLID_R = "solid_r"

    @property
    def dem_win_probability(self) -> float:
        """Approximate Dem win probability implied by this rating."""
        return _RATING_TO_DEM_PROB[self]

    @property
    def numeric(self) -> int:
        """Numeric encoding: -3 (Solid R) to +3 (Solid D)."""
        return _RATING_TO_NUMERIC[self]


_RATING_TO_DEM_PROB: dict[RatingScale, float] = {
    RatingScale.SOLID_D: 0.97,
    RatingScale.LIKELY_D: 0.85,
    RatingScale.LEAN_D: 0.65,
    RatingScale.TOSSUP: 0.50,
    RatingScale.LEAN_R: 0.35,
    RatingScale.LIKELY_R: 0.15,
    RatingScale.SOLID_R: 0.03,
}

_RATING_TO_NUMERIC: dict[RatingScale, int] = {
    RatingScale.SOLID_D: 3,
    RatingScale.LIKELY_D: 2,
    RatingScale.LEAN_D: 1,
    RatingScale.TOSSUP: 0,
    RatingScale.LEAN_R: -1,
    RatingScale.LIKELY_R: -2,
    RatingScale.SOLID_R: -3,
}


@dataclass
class ForecastRating:
    """A single race rating from a forecaster at a point in time."""

    race: str  # e.g., "PA-Senate-2022"
    forecaster: str  # e.g., "cook", "sabato", "538", "rcp"
    rating: RatingScale
    as_of: date
    dem_candidate: str = ""
    rep_candidate: str = ""
    notes: str = ""

    @property
    def dem_win_probability(self) -> float:
        return self.rating.dem_win_probability


@dataclass
class ConsensusRating:
    """Aggregated rating across multiple forecasters for a single race."""

    race: str
    as_of: date
    ratings: list[ForecastRating]
    dem_candidate: str = ""
    rep_candidate: str = ""

    @property
    def average_dem_probability(self) -> float:
        """Average implied Dem win probability across forecasters."""
        if not self.ratings:
            return 0.5
        return sum(r.dem_win_probability for r in self.ratings) / len(self.ratings)

    @property
    def average_numeric(self) -> float:
        """Average numeric rating (-3 to +3)."""
        if not self.ratings:
            return 0.0
        return sum(r.rating.numeric for r in self.ratings) / len(self.ratings)

    @property
    def consensus_rating(self) -> RatingScale:
        """Closest RatingScale to the average."""
        avg = self.average_numeric
        closest = min(RatingScale, key=lambda r: abs(r.numeric - avg))
        return closest


# ── Parsing utilities ─────────────────────────────────────────────────

# Common strings used by various forecasters
_RATING_ALIASES: dict[str, RatingScale] = {
    # Cook / Sabato / Inside Elections standard labels
    "solid d": RatingScale.SOLID_D,
    "solid dem": RatingScale.SOLID_D,
    "solid democratic": RatingScale.SOLID_D,
    "safe d": RatingScale.SOLID_D,
    "safe dem": RatingScale.SOLID_D,
    "likely d": RatingScale.LIKELY_D,
    "likely dem": RatingScale.LIKELY_D,
    "likely democratic": RatingScale.LIKELY_D,
    "lean d": RatingScale.LEAN_D,
    "lean dem": RatingScale.LEAN_D,
    "lean democratic": RatingScale.LEAN_D,
    "tilt d": RatingScale.LEAN_D,
    "tilt dem": RatingScale.LEAN_D,
    "tilt democratic": RatingScale.LEAN_D,
    "toss up": RatingScale.TOSSUP,
    "toss-up": RatingScale.TOSSUP,
    "tossup": RatingScale.TOSSUP,
    "tilt r": RatingScale.LEAN_R,
    "tilt rep": RatingScale.LEAN_R,
    "tilt republican": RatingScale.LEAN_R,
    "lean r": RatingScale.LEAN_R,
    "lean rep": RatingScale.LEAN_R,
    "lean republican": RatingScale.LEAN_R,
    "likely r": RatingScale.LIKELY_R,
    "likely rep": RatingScale.LIKELY_R,
    "likely republican": RatingScale.LIKELY_R,
    "solid r": RatingScale.SOLID_R,
    "solid rep": RatingScale.SOLID_R,
    "solid republican": RatingScale.SOLID_R,
    "safe r": RatingScale.SOLID_R,
    "safe rep": RatingScale.SOLID_R,
}


def parse_rating(raw: str) -> RatingScale:
    """Parse a rating string from any major forecaster into the normalized scale."""
    normalized = raw.strip().lower()
    if normalized in _RATING_ALIASES:
        return _RATING_ALIASES[normalized]
    raise ValueError(f"Unrecognized rating: {raw!r}")


def build_consensus(ratings: list[ForecastRating], race: str) -> ConsensusRating:
    """Build a consensus rating for a race from multiple forecaster ratings."""
    race_ratings = [r for r in ratings if r.race == race]
    if not race_ratings:
        return ConsensusRating(race=race, as_of=date.today(), ratings=[])

    latest_date = max(r.as_of for r in race_ratings)
    return ConsensusRating(
        race=race,
        as_of=latest_date,
        ratings=race_ratings,
        dem_candidate=race_ratings[0].dem_candidate,
        rep_candidate=race_ratings[0].rep_candidate,
    )


# ── 538 Historical data (from their public GitHub repo) ──────────────

# FiveThirtyEight published final forecast files at:
#   https://github.com/fivethirtyeight/data/tree/master/election-forecasts-2022
# Columns include: state, office, party, win probability, projected vote share
# This function would parse those CSVs once downloaded to data/historical/

def load_538_historical(csv_path: str) -> list[ForecastRating]:
    """Load FiveThirtyEight historical forecasts from their GitHub data CSVs.

    Expected format: state, district, office, party, winprob, voteshare, ...
    Download from: https://github.com/fivethirtyeight/data
    """
    import csv
    from pathlib import Path

    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(
            f"538 data file not found: {csv_path}. "
            "Download from https://github.com/fivethirtyeight/data"
        )

    ratings: list[ForecastRating] = []
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Map 538's win probability to our rating scale
            try:
                dem_prob = float(row.get("winprob_Dparty", row.get("dem_winprob", 0.5)))
            except (ValueError, TypeError):
                continue

            rating = _prob_to_rating(dem_prob)
            state = row.get("state", "")
            office = row.get("office", row.get("office_type", ""))
            year = row.get("cycle", row.get("year", ""))

            ratings.append(ForecastRating(
                race=f"{state}-{office}-{year}".strip("-"),
                forecaster="538",
                rating=rating,
                as_of=date(int(year), 11, 1) if year else date.today(),
            ))

    return ratings


def _prob_to_rating(dem_prob: float) -> RatingScale:
    """Convert a numeric Dem win probability to the nearest rating."""
    if dem_prob >= 0.90:
        return RatingScale.SOLID_D
    elif dem_prob >= 0.75:
        return RatingScale.LIKELY_D
    elif dem_prob >= 0.57:
        return RatingScale.LEAN_D
    elif dem_prob >= 0.43:
        return RatingScale.TOSSUP
    elif dem_prob >= 0.25:
        return RatingScale.LEAN_R
    elif dem_prob >= 0.10:
        return RatingScale.LIKELY_R
    else:
        return RatingScale.SOLID_R
