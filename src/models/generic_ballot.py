"""Generic ballot model — congressional preference tracking.

Tracks the national generic ballot (Democrat vs. Republican) and provides
translation to estimated seat outcomes using historical relationships.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.data.base import Poll, PollType
from src.models import ModelMaturity
from src.models.polling_average import AverageResult, PollingAverageEngine

# Placeholder constants for the generic ballot → seat translation.
# Derived from a rough OLS fit over midterm cycles 1998–2022.
# TODO: replace with a cycle-aware fit (with uncertainty bands) once historical
#       data is loaded via scripts/download_training_data.py.  Do NOT use these
#       fixed values for probability claims — they are too static across cycles.
_DEFAULT_SEATS_PER_MARGIN_POINT = 5.5
_DEFAULT_BASELINE_DEM_SEATS = 218  # simple majority (neutral point)

MIN_POLLS_FOR_ESTIMATE = 3


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
    """Generic ballot tracker with seat projection.

    Maturity: TRACKER — reports a weighted polling average and a rough seat
    translation.  Seat estimates are illustrative; treat them as directional
    indicators, not probability forecasts.
    """

    maturity = ModelMaturity.TRACKER

    def __init__(
        self,
        engine: PollingAverageEngine | None = None,
        seats_per_margin_point: float = _DEFAULT_SEATS_PER_MARGIN_POINT,
        baseline_dem_seats: int = _DEFAULT_BASELINE_DEM_SEATS,
    ) -> None:
        self.engine = engine or PollingAverageEngine()
        self.seats_per_margin_point = seats_per_margin_point
        self.baseline_dem_seats = baseline_dem_seats

    def current_ballot(self, polls: list[Poll]) -> GenericBallotSnapshot | None:
        """Return current generic ballot average, or None if too few polls."""
        """Compute the current generic ballot average."""
        gb_polls = [p for p in polls if p.poll_type == PollType.GENERIC_BALLOT]
        if len(gb_polls) < MIN_POLLS_FOR_ESTIMATE:
            return None
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

        # Seat estimation — uses configurable slope; see class docstring caveat
        est_dem = round(self.baseline_dem_seats + margin * self.seats_per_margin_point)
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
