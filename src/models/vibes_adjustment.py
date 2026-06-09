"""NYT "vibes" adjustment for Senate race margins.

Maturity: NOWCAST (experimental). The base Senate tracker is a pure weighted
polling average. This module layers a small, bounded adjustment on top of it
derived from the media-sentiment pipeline in ``src/media`` (NYT Archive API →
candidate mentions → sentiment scoring → :class:`~src.media.vibes.CandidateVibes`).

How the adjustment works (also explained on the website):

1. Each candidate's recent NYT coverage is classified into a five-point
   tone bucket (−2 overwhelmingly negative … +2 overwhelmingly positive)
   and a 0–1 scandal-severity score.
2. Candidate effect (margin points) =
   ``TONE_POINTS_PER_BUCKET · bucket − SCANDAL_PENALTY_POINTS · severity``.
3. Race adjustment = Dem effect − Rep effect, clamped to ±``MAX_ADJUSTMENT``
   so vibes can nudge — never overturn — the polling average.

Coefficients are deliberately conservative priors, not fitted values; the
training pipeline can tune them once enough labelled cycles exist.

Offline operation: the live path needs ``NYT_API_KEY`` and network access, so
the daily cron caches pipeline output to ``data/fallback/nyt_vibes.csv``. The
committed file is a neutral placeholder (all candidates neutral, no scandals →
zero adjustment) until real coverage data is fetched.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.models import ModelMaturity

logger = logging.getLogger(__name__)

# Margin points per tone bucket step (bucket is −2 … +2).
TONE_POINTS_PER_BUCKET = 0.4
# Margin points subtracted at scandal severity 1.0.
SCANDAL_PENALTY_POINTS = 2.5
# The total race adjustment is clamped to ±MAX_ADJUSTMENT points.
MAX_ADJUSTMENT = 3.0


@dataclass
class CandidateVibesRecord:
    """Cached vibes metrics for one candidate (subset of CandidateVibes)."""

    candidate: str
    race: str
    as_of: date
    bucket_numeric: int  # -2 … +2
    scandal_severity: float  # 0–1
    positive_pct: float = 0.0
    negative_pct: float = 0.0
    total_mentions: int = 0

    @property
    def effect_points(self) -> float:
        """This candidate's contribution to the margin, in points."""
        return (
            TONE_POINTS_PER_BUCKET * self.bucket_numeric
            - SCANDAL_PENALTY_POINTS * self.scandal_severity
        )


@dataclass
class VibesAdjustment:
    """The vibes layer for a single race."""

    race: str
    as_of: date | None
    dem_effect: float
    rep_effect: float
    adjustment: float  # clamped Dem-margin delta in points
    dem_record: CandidateVibesRecord | None
    rep_record: CandidateVibesRecord | None

    @property
    def has_data(self) -> bool:
        return self.dem_record is not None or self.rep_record is not None


class VibesCsvSource:
    """Load cached vibes metrics from ``data/fallback/nyt_vibes.csv``."""

    def __init__(self, fallback_dir: Path) -> None:
        self.path = fallback_dir / "nyt_vibes.csv"

    def load(self) -> list[CandidateVibesRecord]:
        if not self.path.exists():
            return []
        rows = list(csv.DictReader(io.StringIO(self.path.read_text(encoding="utf-8"))))
        records: list[CandidateVibesRecord] = []
        for row in rows:
            try:
                records.append(
                    CandidateVibesRecord(
                        candidate=row["candidate"],
                        race=row["race"],
                        as_of=date.fromisoformat(row["as_of"]),
                        bucket_numeric=int(row["bucket_numeric"]),
                        scandal_severity=float(row["scandal_severity"]),
                        positive_pct=float(row.get("positive_pct") or 0.0),
                        negative_pct=float(row.get("negative_pct") or 0.0),
                        total_mentions=int(row.get("total_mentions") or 0),
                    )
                )
            except (KeyError, ValueError) as exc:
                logger.warning("skipping malformed nyt_vibes row %r: %s", row, exc)
        return records


class VibesAdjustedSenateModel:
    """Compute the vibes adjustment for a race from cached candidate records.

    Maturity: NOWCAST — experimental layer on top of the Senate TRACKER.
    """

    maturity = ModelMaturity.NOWCAST

    def __init__(self, records: list[CandidateVibesRecord]) -> None:
        self._by_race_candidate = {(r.race, r.candidate): r for r in records}

    def _lookup(self, race: str, candidate: str) -> CandidateVibesRecord | None:
        record = self._by_race_candidate.get((race, candidate))
        if record is not None:
            return record
        # Tolerate last-name-only vs full-name mismatches between poll
        # answer choices and the vibes pipeline's canonical names.
        for (rec_race, rec_candidate), rec in self._by_race_candidate.items():
            if rec_race == race and (
                candidate.lower() in rec_candidate.lower()
                or rec_candidate.lower() in candidate.lower()
            ):
                return rec
        return None

    def adjustment_for_race(
        self, race: str, dem_candidate: str, rep_candidate: str
    ) -> VibesAdjustment:
        """Bounded Dem-margin delta for one race (positive favours the Dem)."""
        dem = self._lookup(race, dem_candidate)
        rep = self._lookup(race, rep_candidate)
        dem_effect = dem.effect_points if dem else 0.0
        rep_effect = rep.effect_points if rep else 0.0
        raw = dem_effect - rep_effect
        clamped = max(-MAX_ADJUSTMENT, min(MAX_ADJUSTMENT, raw))
        as_of_candidates = [r.as_of for r in (dem, rep) if r is not None]
        return VibesAdjustment(
            race=race,
            as_of=max(as_of_candidates) if as_of_candidates else None,
            dem_effect=round(dem_effect, 2),
            rep_effect=round(rep_effect, 2),
            adjustment=round(clamped, 2),
            dem_record=dem,
            rep_record=rep,
        )
