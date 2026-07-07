"""Generic ballot model — congressional preference tracking.

Tracks the national generic ballot (Democrat vs. Republican) and provides
translation to estimated seat outcomes using historical relationships.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from src.data.base import Poll, PollType
from src.models import ModelMaturity
from src.models.polling_average import AverageResult, PollingAverageEngine

if TYPE_CHECKING:
    from src.models.state_space import StateSpaceResult

# Placeholder constants for the generic ballot → seat translation.
# Derived from a rough OLS fit over midterm cycles 1998–2022.
# TODO: replace with a cycle-aware fit (with uncertainty bands) once historical
#       data is loaded via scripts/download_training_data.py.  Do NOT use these
#       fixed values for probability claims — they are too static across cycles.
_DEFAULT_SEATS_PER_MARGIN_POINT = 5.5
_DEFAULT_BASELINE_DEM_SEATS = 218  # simple majority (neutral point)

MIN_POLLS_FOR_ESTIMATE = 3

# Pollster/source label variants for the two parties. The live VoteHub API
# abbreviates to "Dem"/"Rep"; older exports spell the names out.
GENERIC_BALLOT_CHOICES = [
    "Democrat", "Democratic", "Democrats", "Dem",
    "Republican", "Republicans", "GOP", "Rep",
]


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


def _dominant_choice(
    polls: list[Poll], variants: tuple[str, ...], default: str
) -> str:
    """Most common answer label among the given variants, or ``default``."""
    from collections import Counter

    counter: Counter[str] = Counter()
    for p in polls:
        for a in p.answers:
            if a.choice.lower() in variants:
                counter[a.choice] += 1
    return counter.most_common(1)[0][0] if counter else default


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
        gb_polls = [p for p in polls if p.poll_type == PollType.GENERIC_BALLOT]
        if len(gb_polls) < MIN_POLLS_FOR_ESTIMATE:
            return None
        result = self.engine.compute_average(gb_polls, choices=GENERIC_BALLOT_CHOICES)
        return self._result_to_snapshot(result)

    def current_estimate_ss(
        self,
        polls: list[Poll],
        as_of: date | None = None,
        draws: int = 1000,
        tune: int = 1000,
    ) -> tuple[GenericBallotSnapshot, StateSpaceResult] | None:
        """State-space estimate. Replaces current_ballot() once validated."""
        from src.models import state_space

        as_of = as_of or date.today()
        gb_polls = [p for p in polls if p.poll_type == PollType.GENERIC_BALLOT]
        if len(gb_polls) < MIN_POLLS_FOR_ESTIMATE:
            return None

        # Detect which Dem/Rep labels dominate this dataset
        dem_choice = _dominant_choice(
            gb_polls, ("democrat", "democratic", "democrats", "dem"), "Democrat"
        )
        rep_choice = _dominant_choice(
            gb_polls, ("republican", "republicans", "gop", "rep"), "Republican"
        )

        result = state_space.fit(
            gb_polls, choice=dem_choice, as_of=as_of,
            draws=draws, tune=tune,
        )
        if result is None:
            return None

        # Republican fitted as its own latent series, NOT 100 − dem: the
        # complement folds undecided/third-party into the Republican share and
        # inflates the margin (which then feeds the seat translation). The
        # second fit doubles runtime — acceptable for this opt-in path.
        rep_result = state_space.fit(
            gb_polls, choice=rep_choice, as_of=as_of,
            draws=draws, tune=tune,
        )
        if rep_result is None:
            return None

        dem_mean, dem_lo, dem_hi = result.estimate_at(as_of)
        rep_mean, rep_lo, rep_hi = rep_result.estimate_at(as_of)
        ci_rep = (round(rep_lo, 1), round(rep_hi, 1))

        margin = round(dem_mean - rep_mean, 1)
        est_dem = round(self.baseline_dem_seats + margin * self.seats_per_margin_point)
        est_dem = max(150, min(285, est_dem))

        snap = GenericBallotSnapshot(
            as_of=as_of,
            dem_pct=round(dem_mean, 1),
            rep_pct=round(rep_mean, 1),
            margin=margin,
            num_polls=result.n_polls,
            estimated_dem_seats=est_dem,
            estimated_rep_seats=435 - est_dem,
            ci_dem=(round(dem_lo, 1), round(dem_hi, 1)),
            ci_rep=ci_rep,
        )
        return snap, result

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
