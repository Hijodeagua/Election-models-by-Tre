"""House race models — district-level polling + generic ballot extrapolation."""

from __future__ import annotations

from src.models.polling_average import PollingAverageEngine


class HouseModel:
    """House race tracking and seat projection.

    Uses district-level polling where available and extrapolates from
    the generic ballot elsewhere.

    Stub — expand as district-level data becomes available.
    """

    def __init__(self, engine: PollingAverageEngine | None = None) -> None:
        self.engine = engine or PollingAverageEngine()
