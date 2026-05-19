"""House race models — district-level polling + generic ballot extrapolation."""

from __future__ import annotations

from src.models import ModelMaturity
from src.models.polling_average import PollingAverageEngine


class HouseModel:
    """House race tracking and seat projection.

    Uses district-level polling where available and extrapolates from
    the generic ballot elsewhere.

    Maturity: STUB — not ready for any public output.
    """

    maturity = ModelMaturity.STUB

    def __init__(self, engine: PollingAverageEngine | None = None) -> None:
        self.engine = engine or PollingAverageEngine()
