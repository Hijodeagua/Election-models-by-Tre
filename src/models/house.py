"""House race models — district-level polling + generic ballot extrapolation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.data.base import Poll, PollType
from src.models import ModelMaturity
from src.models.polling_average import AverageResult, PollingAverageEngine

TOTAL_HOUSE_SEATS = 435
BASELINE_DEM_SEATS = 218  # 50% of seats (neutral generic ballot environment)

# Seats gained per 1 pp of generic ballot margin — OLS estimate on 1998-2022 data.
_SEATS_PER_MARGIN_POINT = 5.5
# ±1 σ uncertainty around the regression line (historical SE ≈ 12 seats)
_SEAT_UNCERTAINTY = 12


@dataclass
class HouseDistrictSnapshot:
    """Polling average for a single House district."""

    state: str
    district: int
    as_of: date
    candidates: dict[str, float]  # name/party → avg pct
    margin: float | None
    num_polls: int


@dataclass
class HouseOverview:
    """National House projection from the generic ballot."""

    as_of: date
    generic_ballot_margin: float    # positive = D advantage
    projected_dem_seats: int
    projected_rep_seats: int
    seat_range_low: int             # -1σ bound for Dems
    seat_range_high: int            # +1σ bound for Dems
    num_gb_polls: int


class HouseModel:
    """House race tracking and seat projection.

    Uses district-level polling where available and extrapolates from
    the generic ballot elsewhere.

    Maturity: NOWCAST — projects seats from generic ballot; no district-level
    win probabilities yet.
    """

    maturity = ModelMaturity.NOWCAST

    def __init__(self, engine: PollingAverageEngine | None = None) -> None:
        self.engine = engine or PollingAverageEngine()

    def national_projection(self, polls: list[Poll]) -> HouseOverview:
        """Project national seat count from the generic ballot.

        Returns a baseline-only projection when no polls are provided.
        """
        gb_polls = [p for p in polls if p.poll_type == PollType.GENERIC_BALLOT]
        result = self.engine.compute_average(
            gb_polls,
            choices=["Democrat", "Democratic", "Democrats", "Republican", "Republicans", "GOP"],
        )

        margin = self._gb_margin(result)
        projected = round(BASELINE_DEM_SEATS + margin * _SEATS_PER_MARGIN_POINT)
        projected = max(150, min(285, projected))

        return HouseOverview(
            as_of=result.as_of,
            generic_ballot_margin=margin,
            projected_dem_seats=projected,
            projected_rep_seats=TOTAL_HOUSE_SEATS - projected,
            seat_range_low=max(150, projected - _SEAT_UNCERTAINTY),
            seat_range_high=min(285, projected + _SEAT_UNCERTAINTY),
            num_gb_polls=result.num_polls,
        )

    def district_average(self, polls: list[Poll], state: str, district: int) -> HouseDistrictSnapshot:
        """Compute polling average for a single House district."""
        tag = f"{state}-{district}"
        district_polls = [p for p in polls if tag.lower() in p.subject.lower()]
        result = self.engine.compute_average(district_polls)
        return HouseDistrictSnapshot(
            state=state,
            district=district,
            as_of=result.as_of,
            candidates=result.averages,
            margin=result.margin,
            num_polls=result.num_polls,
        )

    @staticmethod
    def _gb_margin(result: AverageResult) -> float:
        dem = 0.0
        rep = 0.0
        for choice, pct in result.averages.items():
            cl = choice.lower()
            if cl in ("democrat", "democratic", "democrats", "dem"):
                dem = pct
            elif cl in ("republican", "republicans", "gop", "rep"):
                rep = pct
        return round(dem - rep, 1)
