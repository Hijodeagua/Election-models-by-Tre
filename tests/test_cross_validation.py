"""Tests for the rolling-origin CV training protocol (audit item 5)."""

from __future__ import annotations

from datetime import date

import pytest

from src.data.base import Poll, PollAnswer, PollType, Population
from src.training.cross_validation import CVReport, run_cv_optimization, split_by_cycle
from src.training.data_loader import TrainingRace


def make_race(
    year: int,
    race_idx: int = 0,
    dem_share: float = 52.0,
    poll_dem: float = 48.0,
    poll_rep: float = 44.0,
    n_polls: int = 4,
) -> TrainingRace:
    polls = []
    for i in range(n_polls):
        polls.append(Poll(
            poll_id=f"{year}-r{race_idx}-p{i}", source="test",
            poll_type=PollType.HEAD_TO_HEAD,
            pollster=f"Pollster {i}", subject=f"ST-senate-{year}",
            start_date=date(year, 10, 1 + i), end_date=date(year, 10, 4 + i),
            sample_size=800 + 100 * i, population=Population.LIKELY_VOTERS,
            answers=[
                PollAnswer("Democrat", poll_dem + 0.3 * i),
                PollAnswer("Republican", poll_rep - 0.2 * i),
            ],
        ))
    return TrainingRace(
        race_id=f"ST{race_idx}-SENATE-{year}", year=year, state="ST",
        office="senate", polls=polls,
        actual_dem_share=dem_share, actual_rep_share=100 - dem_share,
        dem_two_party_share=dem_share,
        winner_party="D" if dem_share > 50 else "R",
        dem_candidate="Democrat", rep_candidate="Republican",
    )


def make_cycles(years: list[int], races_per_cycle: int = 5) -> list[TrainingRace]:
    races = []
    for year in years:
        for i in range(races_per_cycle):
            # Vary outcomes so the objective isn't flat across parameter sets
            dem = 46.0 + (i * 2.5) + (year % 8) * 0.4
            races.append(make_race(
                year, i, dem_share=dem,
                poll_dem=dem * 0.92, poll_rep=(100 - dem) * 0.92,
            ))
    return races


class TestSplitByCycle:
    def test_groups_and_sorts(self):
        races = make_cycles([2018, 2014, 2022])
        by_cycle = split_by_cycle(races)
        assert list(by_cycle) == [2014, 2018, 2022]
        assert all(len(v) == 5 for v in by_cycle.values())


class TestRunCVOptimization:
    def test_requires_three_cycles(self):
        pytest.importorskip("optuna")
        with pytest.raises(ValueError, match="at least 3 cycles"):
            run_cv_optimization(make_cycles([2020, 2022]), n_trials=2)

    def test_holdout_is_latest_and_excluded_from_selection(self):
        pytest.importorskip("optuna")
        races = make_cycles([2016, 2018, 2020, 2022])
        _, report = run_cv_optimization(races, n_trials=3, save_path=_devnull())
        assert report.holdout_cycle == 2022
        assert report.selection_cycles == [2016, 2018, 2020]
        assert 2022 not in report.per_cycle

    def test_report_carries_out_of_cycle_metrics(self):
        pytest.importorskip("optuna")
        races = make_cycles([2016, 2018, 2020, 2022])
        _, report = run_cv_optimization(races, n_trials=3, save_path=_devnull())
        assert isinstance(report, CVReport)
        assert report.holdout_trained["n_races"] == 5
        assert report.holdout_default["n_races"] == 5
        assert report.gate_reason  # always explained, pass or fail

    def test_gate_fails_when_holdout_unscorable(self, tmp_path):
        pytest.importorskip("optuna")
        races = make_cycles([2016, 2018, 2020])
        # Holdout cycle whose polls name neither major party — nothing to score
        broken = make_race(2022, dem_share=52.0)
        for p in broken.polls:
            p.answers = [PollAnswer("Someone Else", 50.0)]
        broken.dem_candidate = ""
        broken.rep_candidate = ""
        out = tmp_path / "trained.json"
        _, report = run_cv_optimization(races + [broken], n_trials=2, save_path=out)
        assert not report.passed_gate
        assert "no holdout races" in report.gate_reason
        assert not out.exists()  # gate failure must not write params

    def test_passed_gate_writes_params_with_report(self, tmp_path):
        pytest.importorskip("optuna")
        import json
        races = make_cycles([2016, 2018, 2020, 2022])
        out = tmp_path / "trained.json"
        params, report = run_cv_optimization(races, n_trials=5, save_path=out)
        if report.passed_gate:  # TPE with 5 trials usually ties/beats defaults here
            data = json.loads(out.read_text())
            assert data["params"] == params
            assert data["cv"]["holdout_cycle"] == 2022
            assert "rolling-origin" in data["protocol"]
        else:
            assert not out.exists()


def _devnull():
    """A tmp path that tests can let the module write to and ignore."""
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp()) / "trained_params.json"
