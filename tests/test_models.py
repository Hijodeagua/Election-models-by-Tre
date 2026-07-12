"""Tests for the polling average engine and models."""

from __future__ import annotations

from datetime import date, timedelta

from src.data.base import Poll, PollAnswer, PollType, Population
from src.models.polling_average import PollingAverageEngine

# ── Test helpers ──────────────────────────────────────────────────────


def make_poll(
    poll_id: str = "test-1",
    pollster: str = "Test Pollster",
    approve: float = 45.0,
    disapprove: float = 52.0,
    start_date: date | None = None,
    sample_size: int = 1000,
    population: Population = Population.LIKELY_VOTERS,
    partisan: bool = False,
) -> Poll:
    """Helper to create test polls with sensible defaults."""
    if start_date is None:
        start_date = date.today() - timedelta(days=3)
    return Poll(
        poll_id=poll_id,
        source="test",
        poll_type=PollType.APPROVAL,
        pollster=pollster,
        subject="Donald Trump",
        start_date=start_date,
        end_date=start_date + timedelta(days=3),
        sample_size=sample_size,
        population=population,
        answers=[
            PollAnswer(choice="Approve", pct=approve),
            PollAnswer(choice="Disapprove", pct=disapprove),
        ],
        partisan=partisan,
    )


# ── PollingAverageEngine tests ────────────────────────────────────────


class TestPollingAverageEngine:
    def setup_method(self):
        self.engine = PollingAverageEngine(
            pollster_ratings={"Good Pollster": 2.8, "Bad Pollster": 1.0}
        )

    def test_empty_polls_returns_empty_result(self):
        result = self.engine.compute_average([])
        assert result.num_polls == 0
        assert result.averages == {}
        assert result.margin is None

    def test_single_poll_returns_its_values(self):
        poll = make_poll(approve=46.0, disapprove=51.0)
        result = self.engine.compute_average(
            [poll], choices=["Approve", "Disapprove"]
        )
        assert result.num_polls == 1
        assert result.averages["Approve"] == 46.0
        assert result.averages["Disapprove"] == 51.0
        assert result.margin == 5.0  # Disapprove leads by 5 (margin is top - second)

    def test_multiple_polls_weighted_average(self):
        polls = [
            make_poll(poll_id="p1", approve=44.0, disapprove=53.0, sample_size=1000),
            make_poll(poll_id="p2", approve=48.0, disapprove=49.0, sample_size=1000),
        ]
        result = self.engine.compute_average(
            polls, choices=["Approve", "Disapprove"]
        )
        assert result.num_polls == 2
        # Average should be between the two polls
        assert 44.0 <= result.averages["Approve"] <= 48.0
        assert 49.0 <= result.averages["Disapprove"] <= 53.0

    def test_recency_weighting_favors_newer_polls(self):
        old_poll = make_poll(
            poll_id="old",
            approve=40.0,
            disapprove=55.0,
            start_date=date.today() - timedelta(days=60),
        )
        new_poll = make_poll(
            poll_id="new",
            approve=48.0,
            disapprove=49.0,
            # 5 days back so end_date (start+3) is in the past — Fix 2 strict
            # end_date > as_of filter would otherwise drop a still-in-field poll.
            start_date=date.today() - timedelta(days=5),
        )
        result = self.engine.compute_average(
            [old_poll, new_poll], choices=["Approve", "Disapprove"]
        )
        # The average should be closer to the new poll's values
        assert result.averages["Approve"] > 44.0  # Closer to 48 than to 40

    def test_pollster_quality_weighting(self):
        good = make_poll(poll_id="good", pollster="Good Pollster", approve=50.0, disapprove=48.0)
        bad = make_poll(poll_id="bad", pollster="Bad Pollster", approve=40.0, disapprove=58.0)
        result = self.engine.compute_average(
            [good, bad], choices=["Approve", "Disapprove"]
        )
        # Good pollster has 2.8x rating vs 1.0, so average should lean toward good
        assert result.averages["Approve"] > 45.0

    def test_partisan_polls_downweighted(self):
        neutral = make_poll(poll_id="neutral", approve=45.0, disapprove=52.0, partisan=False)
        partisan = make_poll(poll_id="partisan", approve=55.0, disapprove=42.0, partisan=True)
        result = self.engine.compute_average(
            [neutral, partisan], choices=["Approve", "Disapprove"]
        )
        # Partisan poll is downweighted, so average should be closer to neutral
        assert result.averages["Approve"] < 50.0

    def test_adults_weighted_higher_than_lv_for_approval(self):
        # Phase 1a: approval polls invert the LV > Adults hierarchy.
        # Adults capture broader public opinion; LV screens create selection
        # bias unrelated to approval dynamics (Pew/Kennedy & Deane 2017).
        lv_poll = make_poll(
            poll_id="lv", approve=45.0, disapprove=52.0, population=Population.LIKELY_VOTERS
        )
        adults_poll = make_poll(
            poll_id="adults", approve=50.0, disapprove=47.0, population=Population.ADULTS
        )
        result = self.engine.compute_average(
            [lv_poll, adults_poll], choices=["Approve", "Disapprove"]
        )
        # Adults poll should have more influence → average pushed toward 50.0
        assert result.averages["Approve"] > 47.5

    def test_margin_calculation(self):
        poll = make_poll(approve=47.0, disapprove=50.0)
        result = self.engine.compute_average(
            [poll], choices=["Approve", "Disapprove"]
        )
        assert result.margin == 3.0  # Disapprove leads by 3 (margin is top - second)

    def test_confidence_intervals_with_enough_polls(self):
        polls = [
            make_poll(
                poll_id=f"p{i}",
                approve=44.0 + i,
                disapprove=53.0 - i,
                start_date=date.today() - timedelta(days=i),
            )
            for i in range(10)
        ]
        result = self.engine.compute_average(
            polls, choices=["Approve", "Disapprove"]
        )
        assert result.confidence_interval is not None
        assert "Approve" in result.confidence_interval
        ci = result.confidence_interval["Approve"]
        assert ci[0] < ci[1]  # low < high

    def test_auto_detect_choices(self):
        polls = [
            make_poll(poll_id=f"p{i}", approve=45.0, disapprove=52.0)
            for i in range(5)
        ]
        result = self.engine.compute_average(polls)
        # Should auto-detect Approve and Disapprove as choices
        assert "Approve" in result.averages
        assert "Disapprove" in result.averages


# ── PresidentialApprovalModel subject screen ──────────────────────────


class TestPresidentialApprovalSubjectFilter:
    def test_non_presidential_subjects_excluded(self):
        """Congress/Supreme Court/VP approval polls arrive with the same
        PollType.APPROVAL and must not leak into the presidential average."""
        from dataclasses import replace

        from src.models.approval import PresidentialApprovalModel

        trump = [
            make_poll(poll_id=f"t{i}", pollster=f"Pollster {i}", approve=40.0, disapprove=55.0)
            for i in range(5)
        ]
        congress = [
            replace(p, poll_id=f"c{i}", subject="Congress",
                    answers=[PollAnswer("Approve", 15.0), PollAnswer("Disapprove", 70.0)])
            for i, p in enumerate(trump)
        ]
        model = PresidentialApprovalModel(engine=PollingAverageEngine(pollster_ratings={}))
        snap = model.current_approval(trump + congress)
        assert snap is not None
        assert snap.num_polls == 5
        assert abs(snap.approve - 40.0) < 0.2  # Congress's 15% never mixed in

    def test_blank_subject_passes_for_legacy_feeds(self):
        from dataclasses import replace

        from src.models.approval import PresidentialApprovalModel

        legacy = [
            replace(
                make_poll(poll_id=f"l{i}", pollster=f"Pollster {i}"),
                subject="",
            )
            for i in range(5)
        ]
        model = PresidentialApprovalModel(engine=PollingAverageEngine(pollster_ratings={}))
        snap = model.current_approval(legacy)
        assert snap is not None
        assert snap.num_polls == 5


# ── Generic ballot seat conversion (fitted, audit item 8) ─────────────


class TestSeatConversionFit:
    def test_model_loads_fitted_conversion(self):
        """With config/seat_conversion.json present, the model uses the
        empirical slope/baseline, not the old hand-set 5.5/218."""
        import json
        from pathlib import Path

        from src.models.generic_ballot import GenericBallotModel

        fitted = json.loads(
            (Path(__file__).parent.parent / "config" / "seat_conversion.json").read_text()
        )
        model = GenericBallotModel(engine=PollingAverageEngine(pollster_ratings={}))
        assert model.seats_per_margin_point == fitted["seats_per_margin_point"]
        assert model.baseline_dem_seats == round(fitted["baseline_dem_seats"])
        assert model.seat_resid_sd == fitted["resid_sd_seats"]

    def test_explicit_args_override_fit(self):
        from src.models.generic_ballot import GenericBallotModel

        model = GenericBallotModel(
            engine=PollingAverageEngine(pollster_ratings={}),
            seats_per_margin_point=5.5, baseline_dem_seats=218,
        )
        assert model.seats_per_margin_point == 5.5
        assert model.baseline_dem_seats == 218

    def test_seat_estimate_carries_uncertainty_band(self):
        from src.models.generic_ballot import GenericBallotModel

        model = GenericBallotModel(engine=PollingAverageEngine(pollster_ratings={}))
        est, lo, hi = model._seat_estimate(margin=4.0)
        assert lo is not None and hi is not None
        assert lo < est < hi
        # 80% band from resid SD ≈ ±1.282σ
        assert (hi - lo) >= 2 * model.seat_resid_sd
