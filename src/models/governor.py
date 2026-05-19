"""Governor race models — state-level polling averages for 2026."""

from __future__ import annotations

from src.models import ModelMaturity
from src.models.polling_average import PollingAverageEngine


class GovernorModel:
    """Track gubernatorial race polling.

    Maturity: STUB — not ready for any public output.
    """

    maturity = ModelMaturity.STUB

    def __init__(self, engine: PollingAverageEngine | None = None) -> None:
        self.engine = engine or PollingAverageEngine()
