"""Tests for the house model."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.data.base import Poll, PollAnswer, PollType, Population
from src.models.house import (
    HouseModel,
    HouseDistrictSnapshot,
    HouseOverview,
    TOTAL_HOUSE_SEATS,
    BASELINE_DEM_SEATS,
)


def _make_gb_poll(
    poll_id: str = "gb-1",
    dem: float = 47.0,
    rep: float = 45.0,
    start_date: date | None = None,
) -> Poll:
    if start_date is None:
        start_date = date.today() - timedelta(days=3)
    return Poll(
        poll_id=poll_id,
        source="test",
        poll_type=PollType.GENERIC_BALLOT,
        pollster="Test Pollster",
        subject="Generic Ballot",
        start_date=start_date,
        end_date=start_date + timedelta(days=3),
        sample_size=1200,
        population=Population.LIKELY_VOTERS,
        answers=[
            PollAnswer(choice="Democrat", pct=dem),
            PollAnswer(choice="Republican", pct=rep),
        ],
    )


class TestHouseModel:
    def setup_method(self):
        self.model = HouseModel()

    def test_national_projection_d_advantage(self):
        polls = [_make_gb_poll(dem=52.0, rep=44.0)]
        overview = self.model.national_projection(polls)
        assert isinstance(overview, HouseOverview)
        assert overview.projected_dem_seats > BASELINE_DEM_SEATS
        assert overview.projected_dem_seats + overview.projected_rep_seats == TOTAL_HOUSE_SEATS

    def test_national_projection_r_advantage(self):
        polls = [_make_gb_poll(dem=43.0, rep=51.0)]
        overview = self.model.national_projection(polls)
        assert overview.projected_dem_seats < BASELINE_DEM_SEATS

    def test_national_projection_seat_range(self):
        polls = [_make_gb_poll(dem=48.0, rep=46.0)]
        overview = self.model.national_projection(polls)
        assert overview.seat_range_low < overview.projected_dem_seats
        assert overview.seat_range_high > overview.projected_dem_seats

    def test_national_projection_clamped(self):
        polls = [_make_gb_poll(dem=80.0, rep=10.0)]
        overview = self.model.national_projection(polls)
        assert overview.projected_dem_seats <= 285
        assert overview.projected_dem_seats >= 150

    def test_district_average_no_polls(self):
        snap = self.model.district_average([], "PA", 7)
        assert isinstance(snap, HouseDistrictSnapshot)
        assert snap.num_polls == 0
        assert snap.state == "PA"
        assert snap.district == 7

    def test_national_projection_empty_polls(self):
        overview = self.model.national_projection([])
        assert overview.projected_dem_seats == BASELINE_DEM_SEATS
        assert overview.generic_ballot_margin == 0.0
