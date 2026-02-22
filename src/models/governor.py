"""Governor race models — state-level polling averages for 2026."""

from __future__ import annotations

from src.models.polling_average import PollingAverageEngine


class GovernorModel:
    """Track gubernatorial race polling.

    Stub — same pattern as Senate model, expand when data flows in.
    """

    def __init__(self, engine: PollingAverageEngine | None = None) -> None:
        self.engine = engine or PollingAverageEngine()
