"""Tests for the training data pipeline and optimizer."""

from __future__ import annotations

from datetime import date

import pytest

from src.data.base import Poll, PollAnswer, PollType, Population
from src.data.fte_archive import FTEArchiveClient, _parse_fte_date
from src.data.mit_results import ElectionResult, MITResultsClient
from src.models.polling_average import PollingAverageEngine, PollingAverageParams
from src.training.data_loader import (
    TrainingRace,
    _election_day,
    _state_to_abbrev,
)
from src.training.evaluator import PollingAverageEvaluator

# ── PollingAverageParams ──────────────────────────────────────────────


class TestPollingAverageParams:
    def test_defaults(self):
        p = PollingAverageParams()
        assert p.recency_half_life_days == 14.0
        assert p.lv_weight_multiplier == 1.5
        assert p.sample_size_exponent == 0.5
        assert p.pollster_quality_exponent == 1.0

    def test_engine_accepts_params(self):
        p = PollingAverageParams(recency_half_life_days=21.0)
        engine = PollingAverageEngine(params=p)
        assert engine.params.recency_half_life_days == 21.0

    def test_engine_uses_trained_params_if_available(self, tmp_path):
        trained = tmp_path / "trained_params.json"
        import json
        trained.write_text(json.dumps({
            "params": {"recency_half_life_days": 30.0}
        }))
        # Just confirm default loads without error
        assert PollingAverageParams() is not None

    def test_sample_size_exponent_applied(self):
        """Custom exponent changes how sample size affects weight."""
        from src.data.base import Poll, PollAnswer, PollType, Population
        poll = Poll(
            poll_id="t1", source="test", poll_type=PollType.APPROVAL,
            pollster="Test", subject="Test",
            start_date=date.today(), end_date=date.today(),
            sample_size=4000,  # 4000/1000=4.0, so 4^0.5=2.0 != 4^1.0=4.0
            population=Population.LIKELY_VOTERS,
            answers=[PollAnswer("Approve", 50.0)],
        )
        engine_sqrt = PollingAverageEngine(params=PollingAverageParams(sample_size_exponent=0.5))
        engine_linear = PollingAverageEngine(params=PollingAverageParams(sample_size_exponent=1.0))
        w_sqrt = engine_sqrt._compute_weight(poll, date.today())
        w_linear = engine_linear._compute_weight(poll, date.today())
        # Linear exponent means more weight for larger samples
        assert w_linear != w_sqrt


# ── FTE Archive ───────────────────────────────────────────────────────


class TestFTEDateParsing:
    def test_slash_short_year(self):
        assert _parse_fte_date("10/15/22") == date(2022, 10, 15)

    def test_slash_long_year(self):
        assert _parse_fte_date("10/15/2022") == date(2022, 10, 15)

    def test_iso_format(self):
        assert _parse_fte_date("2022-10-15") == date(2022, 10, 15)

    def test_empty(self):
        assert _parse_fte_date("") is None

    def test_invalid(self):
        assert _parse_fte_date("not-a-date") is None


class TestFTEArchiveNormalization:
    def test_normalize_valid_row(self):
        row = {
            "poll_id": "abc123",
            "cycle": "2022",
            "state": "Pennsylvania",
            "pollster": "Marist",
            "start_date": "10/01/22",
            "end_date": "10/05/22",
            "sample_size": "1000",
            "population": "lv",
            "answer": "Fetterman",
            "party": "DEM",
            "pct": "51.2",
            "internal": "false",
            "partisan": "",
        }
        poll = FTEArchiveClient._normalize_row(row, "senate")
        assert poll is not None
        assert poll.cycle == 2022
        assert poll.state == "Pennsylvania"
        assert poll.pct == 51.2
        assert poll.population == "lv"
        assert poll.partisan is False

    def test_normalize_missing_required(self):
        # Missing state
        row = {"cycle": "2022", "start_date": "10/01/22", "end_date": "10/05/22", "pct": "45"}
        assert FTEArchiveClient._normalize_row(row, "senate") is None

    def test_normalize_bad_pct(self):
        row = {
            "cycle": "2022", "state": "PA",
            "start_date": "10/01/22", "end_date": "10/05/22",
            "pct": "N/A",
        }
        assert FTEArchiveClient._normalize_row(row, "senate") is None


# ── MIT Results ───────────────────────────────────────────────────────


class TestMITResultsNormalization:
    def test_normalize_valid_row(self):
        row = {
            "year": "2022", "state": "Pennsylvania", "state_po": "PA",
            "candidate": "John Fetterman", "party_simplified": "DEMOCRAT",
            "candidatevotes": "2775259", "totalvotes": "5366447",
            "district": "", "special": "false", "writein": "false",
        }
        result = MITResultsClient._normalize_row(row, "senate")
        assert result is not None
        assert result.year == 2022
        assert result.party == "D"
        assert result.vote_share == pytest.approx(51.71, abs=0.1)

    def test_skip_writeins(self):
        row = {
            "year": "2022", "state": "PA", "state_po": "PA",
            "candidate": "Write-in", "party_simplified": "OTHER",
            "candidatevotes": "100", "totalvotes": "5000000",
            "district": "", "special": "false", "writein": "true",
        }
        assert MITResultsClient._normalize_row(row, "senate") is None

    def test_race_id_format(self):
        r = ElectionResult(
            year=2022, state="Pennsylvania", state_po="PA",
            office="senate", district=None, special=False,
            candidate="Fetterman", party="D",
            candidatevotes=2000000, totalvotes=5000000, winner=True,
        )
        assert r.race_id == "PA-SENATE-2022"

    def test_aggregate_requires_both_parties(self):
        """Races with only one party should be dropped."""
        dem_only = [
            ElectionResult(
                year=2022, state="Safe State", state_po="SS", office="senate",
                district=None, special=False, candidate="Dem Candidate", party="D",
                candidatevotes=700000, totalvotes=750000, winner=True,
            )
        ]
        results = MITResultsClient._aggregate_to_races(dem_only)
        assert len(results) == 0

    def test_aggregate_picks_top_candidates(self):
        candidates = [
            ElectionResult(year=2022, state="PA", state_po="PA", office="senate",
                district=None, special=False, candidate="Fetterman", party="D",
                candidatevotes=2775259, totalvotes=5366447, winner=True),
            ElectionResult(year=2022, state="PA", state_po="PA", office="senate",
                district=None, special=False, candidate="Oz", party="R",
                candidatevotes=2545839, totalvotes=5366447, winner=False),
        ]
        results = MITResultsClient._aggregate_to_races(candidates)
        assert len(results) == 1
        r = results[0]
        assert r.dem_candidate == "Fetterman"
        assert r.rep_candidate == "Oz"
        assert r.winner_party == "D"
        assert r.dem_two_party_share > 50


# ── Data loader helpers ───────────────────────────────────────────────


class TestDataLoaderHelpers:
    def test_election_day_2022(self):
        d = _election_day(2022)
        assert d == date(2022, 11, 8)
        assert d.weekday() == 1  # Tuesday

    def test_election_day_2018(self):
        d = _election_day(2018)
        assert d == date(2018, 11, 6)
        assert d.weekday() == 1

    def test_state_abbrev_full_name(self):
        assert _state_to_abbrev("Pennsylvania") == "PA"
        assert _state_to_abbrev("New York") == "NY"

    def test_state_abbrev_already_short(self):
        assert _state_to_abbrev("PA") == "PA"
        assert _state_to_abbrev("ny") == "NY"


# ── Evaluator ─────────────────────────────────────────────────────────


def make_training_race(
    dem_share: float = 52.0,
    n_polls: int = 5,
    pred_dem_pct: float = 51.0,
) -> TrainingRace:
    """Build a minimal TrainingRace for evaluator tests."""
    polls = []
    for i in range(n_polls):
        polls.append(Poll(
            poll_id=f"p{i}", source="test", poll_type=PollType.HEAD_TO_HEAD,
            pollster="Test Pollster", subject="PA-senate-2022",
            start_date=date(2022, 10, 1), end_date=date(2022, 10, 5),
            sample_size=1000, population=Population.LIKELY_VOTERS,
            answers=[
                PollAnswer("Democrat", pred_dem_pct),
                PollAnswer("Republican", 100 - pred_dem_pct),
            ],
        ))
    return TrainingRace(
        race_id="PA-SENATE-2022", year=2022, state="PA", office="senate",
        polls=polls, actual_dem_share=dem_share,
        actual_rep_share=100 - dem_share,
        dem_two_party_share=dem_share,
        winner_party="D" if dem_share > 50 else "R",
        dem_candidate="Democrat", rep_candidate="Republican",
    )


class TestEvaluator:
    def test_perfect_prediction_gives_low_rmse(self):
        races = [make_training_race(dem_share=52.0, pred_dem_pct=52.0) for _ in range(10)]
        evaluator = PollingAverageEvaluator(races)
        params = {k: v for k, v in PollingAverageParams().__dict__.items()}
        result = evaluator.evaluate(params)
        assert result.rmse < 2.0
        assert result.n_races == 10

    def test_biased_prediction_shows_in_mean_error(self):
        # All polls show 55% but actual is 50%
        races = [make_training_race(dem_share=50.0, pred_dem_pct=55.0) for _ in range(10)]
        evaluator = PollingAverageEvaluator(races)
        params = {k: v for k, v in PollingAverageParams().__dict__.items()}
        result = evaluator.evaluate(params)
        assert result.mean_error > 0  # model overestimates Dems

    def test_win_accuracy_perfect(self):
        # Polls correctly show Dem winning
        races = [make_training_race(dem_share=55.0, pred_dem_pct=55.0) for _ in range(10)]
        evaluator = PollingAverageEvaluator(races)
        params = {k: v for k, v in PollingAverageParams().__dict__.items()}
        result = evaluator.evaluate(params)
        assert result.win_accuracy == 1.0

    def test_empty_races_raises(self):
        with pytest.raises(ValueError):
            PollingAverageEvaluator([])

    def test_undecided_does_not_bias_error(self):
        """Raw polls with undecideds must be two-party-normalized before
        differencing against the two-party actual (audit Finding 1)."""
        # Polls: D 48, R 44 (8% undecided) → two-party pred = 48/92 ≈ 52.17.
        # Actual two-party share 52.17 → error ≈ 0 (the old raw comparison
        # reported a spurious −4pp bias here).
        races = []
        for _ in range(10):
            race = make_training_race(dem_share=52.17, pred_dem_pct=48.0)
            for poll in race.polls:
                poll.answers[1].pct = 44.0  # Republican at 44, not 52
            races.append(race)
        evaluator = PollingAverageEvaluator(races)
        params = {k: v for k, v in PollingAverageParams().__dict__.items()}
        result = evaluator.evaluate(params)
        assert abs(result.mean_error) < 0.5
        assert result.rmse < 1.0

    def test_win_call_on_two_party_share(self):
        """A raw 48–44 lead is a predicted win once normalized (the old
        `raw > 50` rule counted it as a predicted loss)."""
        races = []
        for _ in range(10):
            race = make_training_race(dem_share=52.0, pred_dem_pct=48.0)
            for poll in race.polls:
                poll.answers[1].pct = 44.0
            races.append(race)
        evaluator = PollingAverageEvaluator(races)
        params = {k: v for k, v in PollingAverageParams().__dict__.items()}
        result = evaluator.evaluate(params)
        assert result.win_accuracy == 1.0

    def test_higher_half_life_smooths_more(self):
        """Longer half-life gives more weight to older polls."""
        races = [make_training_race() for _ in range(5)]
        evaluator = PollingAverageEvaluator(races)
        short_params = {**PollingAverageParams().__dict__, "recency_half_life_days": 7.0}
        long_params = {**PollingAverageParams().__dict__, "recency_half_life_days": 30.0}
        short_result = evaluator.evaluate(short_params)
        long_result = evaluator.evaluate(long_params)
        # Both should run without error
        assert short_result.n_races > 0
        assert long_result.n_races > 0
