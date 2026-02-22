"""Generic ballot model — congressional preference tracking.

Tracks the national generic ballot (Democrat vs. Republican) and provides
translation to estimated seat outcomes using historical relationships.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.data.base import Poll, PollType
from src.models.polling_average import AverageResult, PollingAverageEngine

# Historical generic ballot → House seat share relationship (simplified linear model).
# Based on analysis of midterm elections 1998–2022.
# Each point of generic ballot margin ≈ 5–6 House seats.
SEATS_PER_MARGIN_POINT = 5.5
BASELINE_DEM_SEATS = 218  # Neutral starting point (simple majority)


@dataclass
class GenericBallotSnapshot:
    """A point-in-time generic ballot reading."""

    as_of: date
    dem_pct: float
    rep_pct: float
    margin: float  # positive = D advantage
    num_polls: int
    estimated_dem_seats: int | None = None
    estimated_rep_seats: int | None = None
    ci_dem: tuple[float, float] | None = None
    ci_rep: tuple[float, float] | None = None


class GenericBallotModel:
    """Generic ballot tracker with seat projection."""

    def __init__(self, engine: PollingAverageEngine | None = None) -> None:
        self.engine = engine or PollingAverageEngine()

    def current_ballot(self, polls: list[Poll]) -> GenericBallotSnapshot:
        """Compute the current generic ballot average."""
        gb_polls = [p for p in polls if p.poll_type == PollType.GENERIC_BALLOT]
        result = self.engine.compute_average(
            gb_polls,
            choices=["Democrat", "Democratic", "Democrats", "Republican", "Republicans", "GOP"],
        )
        return self._result_to_snapshot(result)

    def _result_to_snapshot(self, result: AverageResult) -> GenericBallotSnapshot:
        # Normalize choice names — different pollsters use different labels
        dem_pct = 0.0
        rep_pct = 0.0
        for choice, pct in result.averages.items():
            if choice.lower() in ("democrat", "democratic", "democrats", "dem"):
                dem_pct = pct
            elif choice.lower() in ("republican", "republicans", "gop", "rep"):
                rep_pct = pct

        margin = round(dem_pct - rep_pct, 1)

        # Seat estimation
        est_dem = round(BASELINE_DEM_SEATS + margin * SEATS_PER_MARGIN_POINT)
        est_dem = max(150, min(285, est_dem))  # clamp to reasonable range
        est_rep = 435 - est_dem

        ci = result.confidence_interval
        ci_dem = None
        ci_rep = None
        if ci:
            for choice, bounds in ci.items():
                if choice.lower() in ("democrat", "democratic", "democrats"):
                    ci_dem = bounds
                elif choice.lower() in ("republican", "republicans", "gop"):
                    ci_rep = bounds

        return GenericBallotSnapshot(
            as_of=result.as_of,
            dem_pct=dem_pct,
            rep_pct=rep_pct,
            margin=margin,
            num_polls=result.num_polls,
            estimated_dem_seats=est_dem,
            estimated_rep_seats=est_rep,
            ci_dem=ci_dem,
            ci_rep=ci_rep,
        )
