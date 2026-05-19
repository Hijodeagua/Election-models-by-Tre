"""Senate race models — individual race polling averages for 2026."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.data.base import Poll, PollType
from src.models import ModelMaturity
from src.models.polling_average import AverageResult, PollingAverageEngine


@dataclass
class SenateRaceSnapshot:
    """Polling average for a single Senate race."""

    state: str
    as_of: date
    candidates: dict[str, float]  # candidate_name -> avg pct
    margin: float | None
    num_polls: int
    rating: str | None = None  # Cook/Sabato rating


class SenateModel:
    """Track and aggregate Senate race polling.

    Maturity: TRACKER — per-race polling averages only; no win probabilities yet.
    """

    maturity = ModelMaturity.TRACKER

    def __init__(self, engine: PollingAverageEngine | None = None) -> None:
        self.engine = engine or PollingAverageEngine()

    def race_average(self, polls: list[Poll], state: str) -> SenateRaceSnapshot:
        """Compute polling average for a single Senate race."""
        state_polls = [
            p for p in polls
            if state.lower() in p.subject.lower()
        ]
        result = self.engine.compute_average(state_polls)
        return SenateRaceSnapshot(
            state=state,
            as_of=result.as_of,
            candidates=result.averages,
            margin=result.margin,
            num_polls=result.num_polls,
        )
