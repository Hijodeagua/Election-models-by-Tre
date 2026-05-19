"""2028 Presidential primary tracker.

Tracks early primary polling and candidate favorability for both parties.
"""

from __future__ import annotations

from src.models import ModelMaturity
from src.models.polling_average import PollingAverageEngine


class PresidentialPrimaryTracker:
    """Track 2028 presidential primary polling.

    Maturity: STUB — not ready for any public output.
    """

    maturity = ModelMaturity.STUB

    def __init__(self, engine: PollingAverageEngine | None = None) -> None:
        self.engine = engine or PollingAverageEngine()
