"""Tests for the economic-signal pre-registration test.

The real run needs the 538 poll archive and the FRED vintage panels, neither of
which exists in CI, so everything here is synthetic. What is worth pinning down
is the arithmetic that could silently invert a conclusion: election dates, the
president's-party sign flip, the join, and the holdout comparison.
"""

from __future__ import annotations

import csv
from datetime import date

import pytest

from scripts.economic_signal import (
    FEATURES,
    PRESIDENT_PARTY,
    RaceRow,
    build_rows,
    election_day,
    holdout_test,
    load_aligned,
    regress,
)
from src.training.data_loader import TrainingRace
from src.training.evaluator import RacePrediction


class TestElectionDay:
    """First Tuesday after the first Monday in November — not 'first Tuesday'."""

    @pytest.mark.parametrize(("year", "expected"), [
        (2018, date(2018, 11, 6)),
        (2019, date(2019, 11, 5)),
        (2020, date(2020, 11, 3)),
        (2021, date(2021, 11, 2)),
        (2022, date(2022, 11, 8)),
        (2024, date(2024, 11, 5)),
        (2026, date(2026, 11, 3)),
    ])
    def test_known_election_days(self, year, expected):
        assert election_day(year) == expected

    def test_never_november_first(self):
        # 2021 is the trap: Nov 1 was a Monday, so election day is the 2nd.
        assert election_day(2021).day == 2
        for year in range(2000, 2040):
            assert election_day(year).weekday() == 1  # Tuesday
            assert 2 <= election_day(year).day <= 8


def _race(year: int, state: str, race_idx: int = 0) -> TrainingRace:
    return TrainingRace(
        race_id=f"{state}-SENATE-{year}-{race_idx}", year=year, state=state,
        office="senate", polls=[], actual_dem_share=50.0, actual_rep_share=50.0,
        dem_two_party_share=50.0, winner_party="D",
        dem_candidate="Dem", rep_candidate="Rep",
    )


def _prediction(year: int, state: str, pred_2p: float, actual_2p: float) -> RacePrediction:
    race = _race(year, state)
    race.dem_two_party_share = actual_2p
    return RacePrediction(
        race=race, pred_dem_2p=pred_2p, actual_dem_2p=actual_2p,
        error=pred_2p - actual_2p, n_polls=5,
    )


def _write_panel(tmp_path, cutoff: date, rows: list[dict]) -> None:
    stamp = cutoff.isoformat()
    path = tmp_path / f"state_economics_aligned_{stamp}_vintage{stamp}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["state", "concept", "value", "change_12m", "change_pct_12m"]
        )
        writer.writeheader()
        writer.writerows(rows)


def _full_state_rows(state: str, unemp: float = 4.0) -> list[dict]:
    """One row per concept the feature list needs."""
    return [
        {"state": state, "concept": "unemployment_rate",
         "value": unemp, "change_12m": -0.3, "change_pct_12m": -7.0},
        {"state": state, "concept": "nonfarm_payrolls",
         "value": 5000, "change_12m": 100, "change_pct_12m": 2.0},
        {"state": state, "concept": "house_price_index",
         "value": 300, "change_12m": 15, "change_pct_12m": 5.0},
        {"state": state, "concept": "personal_income",
         "value": 400000, "change_12m": 20000, "change_pct_12m": 5.0},
    ]


@pytest.fixture
def panel_dir(tmp_path, monkeypatch):
    """Point aligned_path at a tmp dir so tests can write fake panels."""
    import scripts.economic_signal as mod

    monkeypatch.setattr(
        mod, "aligned_path",
        lambda realtime, cutoff: tmp_path
        / f"state_economics_aligned_{cutoff.isoformat()}"
        f"{f'_vintage{realtime.isoformat()}' if realtime else ''}.csv",
    )
    return tmp_path


class TestLoadAligned:
    def test_missing_vintage_returns_none_rather_than_dying(self, panel_dir):
        assert load_aligned(2018) is None

    def test_parses_values_and_blanks(self, panel_dir):
        _write_panel(panel_dir, date(2022, 11, 8), [
            {"state": "GA", "concept": "unemployment_rate",
             "value": 3.1, "change_12m": -0.5, "change_pct_12m": ""},
        ])
        panel = load_aligned(2022)
        assert panel is not None
        entry = panel[("GA", "unemployment_rate")]
        assert entry["value"] == 3.1
        assert entry["change_12m"] == -0.5
        assert "change_pct_12m" not in entry  # blank is absent, not zero


class TestBuildRows:
    def test_sign_flips_for_a_republican_president(self, panel_dir):
        # 2018: Trump. A Democrat beating their polls by 2 points is the
        # president's party UNDER-performing by 2.
        _write_panel(panel_dir, date(2018, 11, 6), _full_state_rows("OH"))
        # pred 50, actual 51 → Dem margin +2 vs predicted 0 → residual +2
        rows, skipped, missing = build_rows([_prediction(2018, "OH", 50.0, 51.0)])
        assert not missing
        assert len(rows) == 1
        assert rows[0].residual == pytest.approx(2.0)
        assert rows[0].residual_pres == pytest.approx(-2.0)

    def test_sign_keeps_for_a_democratic_president(self, panel_dir):
        _write_panel(panel_dir, date(2022, 11, 8), _full_state_rows("GA"))
        rows, _, _ = build_rows([_prediction(2022, "GA", 50.0, 51.0)])
        assert PRESIDENT_PARTY[2022] == "D"
        assert rows[0].residual_pres == pytest.approx(2.0)

    def test_incomplete_economic_data_skips_the_race(self, panel_dir):
        _write_panel(panel_dir, date(2022, 11, 8), [
            {"state": "GA", "concept": "unemployment_rate",
             "value": 3.1, "change_12m": -0.5, "change_pct_12m": -14.0},
        ])  # missing payrolls / HPI / income
        rows, skipped, _ = build_rows([_prediction(2022, "GA", 50.0, 51.0)])
        assert rows == []
        assert any("incomplete" in reason for reason in skipped)

    def test_a_missing_cycle_does_not_block_the_others(self, panel_dir):
        _write_panel(panel_dir, date(2022, 11, 8), _full_state_rows("GA"))
        rows, skipped, missing = build_rows([
            _prediction(2018, "OH", 50.0, 51.0),   # no 2018 panel
            _prediction(2022, "GA", 50.0, 51.0),
        ])
        assert missing == [2018]
        assert [r.year for r in rows] == [2022]
        assert skipped["no economic vintage for 2018"] == 1

    def test_every_feature_lands_on_the_row(self, panel_dir):
        _write_panel(panel_dir, date(2022, 11, 8), _full_state_rows("GA"))
        rows, _, _ = build_rows([_prediction(2022, "GA", 50.0, 51.0)])
        assert set(rows[0].features) == {label for label, _, _ in FEATURES}


def _rows_with(values: list[tuple[int, float, float]]) -> list[RaceRow]:
    """(year, feature value, residual_pres) → rows carrying a full feature set."""
    out = []
    for i, (year, x, resid) in enumerate(values):
        out.append(RaceRow(
            race_id=f"R{i}", year=year, state="XX", office="senate", n_polls=5,
            pred_margin=0.0, actual_margin=resid, residual=resid,
            residual_pres=resid,
            features={label: x for label, _, _ in FEATURES},
        ))
    return out


class TestRegress:
    def test_recovers_a_planted_slope(self):
        # residual_pres = 2 * x exactly, across three cycles.
        rows = _rows_with([
            (2018, 1.0, 2.0), (2018, 2.0, 4.0), (2018, 3.0, 6.0),
            (2020, 1.5, 3.0), (2020, 2.5, 5.0), (2020, 3.5, 7.0),
            (2022, 0.5, 1.0), (2022, 4.0, 8.0), (2022, 2.0, 4.0),
        ])
        fit = regress(rows, "unemp_level")
        assert fit["coef"] == pytest.approx(2.0, abs=1e-6)
        assert fit["r_squared"] == pytest.approx(1.0, abs=1e-6)
        assert fit["n"] == 9
        assert fit["n_clusters"] == 3

    def test_reports_no_slope_for_pure_noise(self):
        rows = _rows_with([
            (2018, 1.0, 1.0), (2018, 2.0, -1.0),
            (2020, 1.0, 1.0), (2020, 2.0, -1.0),
            (2022, 1.0, 1.0), (2022, 2.0, -1.0),
        ])
        fit = regress(rows, "unemp_level")
        assert fit["coef"] == pytest.approx(-2.0, abs=1e-6)  # the planted pattern
        assert fit["expected_sign"] == "negative"  # unemployment is a pain feature


class TestHoldout:
    def test_a_real_relationship_lowers_holdout_rmse(self):
        rows = _rows_with([
            (2018, 1.0, 2.0), (2018, 2.0, 4.0), (2018, 3.0, 6.0),
            (2018, 4.0, 8.0), (2018, 5.0, 10.0), (2018, 6.0, 12.0),
            (2020, 1.0, 2.0), (2020, 2.0, 4.0), (2020, 3.0, 6.0),
            (2020, 4.0, 8.0), (2020, 5.0, 10.0), (2020, 6.0, 12.0),
            (2022, 1.5, 3.0), (2022, 2.5, 5.0), (2022, 3.5, 7.0),
            (2022, 4.5, 9.0), (2022, 0.5, 1.0),
        ])
        result = holdout_test(rows, "unemp_level", 2022)
        assert result["usable"]
        assert result["helps"]
        assert result["rmse_with"] < 0.01  # near-perfect fit carries over

    def test_a_feature_that_does_not_generalize_is_reported_as_such(self):
        # Slope is +2 in the training cycles and -2 in the holdout.
        rows = _rows_with([
            (2018, 1.0, 2.0), (2018, 2.0, 4.0), (2018, 3.0, 6.0),
            (2018, 4.0, 8.0), (2018, 5.0, 10.0), (2018, 6.0, 12.0),
            (2020, 1.0, 2.0), (2020, 2.0, 4.0), (2020, 3.0, 6.0),
            (2020, 4.0, 8.0), (2020, 5.0, 10.0), (2020, 6.0, 12.0),
            (2022, 1.0, -2.0), (2022, 2.0, -4.0), (2022, 3.0, -6.0),
            (2022, 4.0, -8.0), (2022, 5.0, -10.0),
        ])
        result = holdout_test(rows, "unemp_level", 2022)
        assert result["usable"]
        assert not result["helps"]
        assert result["improvement"] < 0

    def test_too_few_races_is_declared_unusable(self):
        # The floor is 10 training + 5 holdout races for a univariate fit.
        rows = _rows_with([(2018, 1.0, 1.0), (2022, 2.0, 2.0)])
        result = holdout_test(rows, "unemp_level", 2022)
        assert not result["usable"]
        assert "too few" in result["reason"]
