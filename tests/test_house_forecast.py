"""Tests for the House forecast (src/models/house_forecast.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models.house_forecast import (
    DistrictInput,
    HouseForecastSimulator,
    expected_national_margin,
    load_districts,
    load_house_config,
    two_party_margin,
)

ROOT = Path(__file__).resolve().parent.parent


def _districts(margins):
    return [
        DistrictInput(
            state="XX",
            district=f"District {i + 1}",
            margin_2024=m,
            winner_2024="D" if m > 0 else "R",
        )
        for i, m in enumerate(margins)
    ]


def _sim(**kw):
    defaults = dict(baseline_margin=-2.4, national_sigma=2.5, district_sigma=6.0, tail_dof=5.0,
                    dem_majority_threshold=3, total_seats=10)
    defaults.update(kw)
    return HouseForecastSimulator(**defaults)


class TestBaselineData:
    def test_committed_district_file_is_complete(self):
        districts = load_districts()
        assert len(districts) == 435
        dems = sum(1 for d in districts if d.winner_2024 == "D")
        reps = sum(1 for d in districts if d.winner_2024 == "R")
        assert (dems, reps) == (215, 220)  # actual 2024 result
        # Every imputed margin sits on the winner's side of zero.
        for d in districts:
            if d.imputed_from:
                assert (d.margin_2024 > 0) == (d.winner_2024 == "D")

    def test_config_loads_and_redistricting_entries_are_well_formed(self):
        cfg = load_house_config()
        assert cfg["dem_majority_threshold"] == 218
        for entry in cfg["redistricting"]["states"]:
            assert {"state", "dem_seat_shift", "sd", "include"} <= set(entry)

    def test_two_party_margin(self):
        assert two_party_margin(50.0, 44.0) == pytest.approx(6.0 / 94.0 * 100)
        assert two_party_margin(0.0, 0.0) == 0.0


class TestSimulator:
    def test_uniform_swing_counts_seats(self):
        # No noise: seats are exactly the districts whose 2024 margin plus the
        # swing is positive.
        sim = _sim(national_sigma=0.0, district_sigma=0.0, tail_dof=None)
        ds = _districts([-10, -3, -1, 2, 8])
        fc = sim.simulate(ds, expected_national_margin=-2.4 + 2.0, num_simulations=10, seed=0)
        assert fc.mean_dem_seats == 3  # -1 and -3 become +1 and -1 → districts 3,4,5
        assert fc.dem_majority_prob == 1.0

    def test_monotonic_in_national_margin(self):
        sim = _sim()
        ds = _districts([-12, -6, -2, 1, 4, 9])
        probs = [
            sim.simulate(ds, m, num_simulations=4000, seed=1).dem_majority_prob
            for m in (-6, -2, 2, 6)
        ]
        assert probs == sorted(probs)

    def test_district_win_prob_matches_simulation(self):
        sim = _sim()
        ds = _districts([-4.0])
        fc = sim.simulate(ds, expected_national_margin=0.0, num_simulations=60000, seed=2)
        analytic = sim.district_win_prob(-4.0, 0.0)
        assert fc.districts[0].dem_win_prob == pytest.approx(analytic, abs=0.01)

    def test_redistricting_shift_moves_seats(self):
        ds = _districts([-12, -6, -2, 1, 4, 9])
        base = _sim().simulate(ds, 0.0, num_simulations=5000, seed=3)
        shifted = _sim(redistricting=[{"state": "TX", "dem_seat_shift": -2, "sd": 0.0}]).simulate(
            ds, 0.0, num_simulations=5000, seed=3
        )
        assert shifted.mean_dem_seats == pytest.approx(base.mean_dem_seats - 2, abs=0.05)
        excluded = _sim(
            redistricting=[{"state": "TX", "dem_seat_shift": -2, "sd": 0.0, "include": False}]
        ).simulate(ds, 0.0, num_simulations=5000, seed=3)
        assert excluded.mean_dem_seats == pytest.approx(base.mean_dem_seats)

    def test_seats_votes_curve_and_tipping_point(self):
        sim = _sim(dem_majority_threshold=3)
        ds = _districts([-12, -6, -2, 1, 4])
        fc = sim.simulate(ds, 0.0, num_simulations=100, seed=0, curve_margins=[-4, 0, 4])
        seats = [p["dem_seats"] for p in fc.seats_by_margin]
        assert seats == sorted(seats)
        assert fc.tipping_point_margin is not None
        assert sim.expected_seats_at(ds, fc.tipping_point_margin) == pytest.approx(3.0, abs=0.01)

    def test_competitive_list_is_sorted_by_closeness(self):
        sim = _sim()
        ds = _districts([-30, -3, 0.5, 2, 30])
        fc = sim.simulate(ds, 0.0, num_simulations=3000, seed=4)
        closeness = [abs(f.dem_win_prob - 0.5) for f in fc.competitive]
        assert closeness == sorted(closeness)
        assert all(0.10 <= f.dem_win_prob <= 0.90 for f in fc.competitive)

    def test_rejects_bad_inputs(self):
        with pytest.raises(ValueError):
            _sim().simulate([], 0.0)
        with pytest.raises(ValueError):
            _sim(national_sigma=-1.0)


class TestNationalEnvironment:
    CFG = {
        "national_environment": {
            "president_party": "R",
            "generic_weight": 0.75,
            "approval_weight": 0.25,
            "approval_to_margin_coef": 0.3,
            "generic_ballot_bias": -1.0,
        }
    }

    def test_blend_and_bias(self):
        out = expected_national_margin(self.CFG, generic_two_party=6.0, approval_net=-20.0)
        # approval-implied: -(0.3 * -20) = +6; blend = 6; bias -1 → 5
        assert out["approval_implied"] == 6.0
        assert out["raw"] == pytest.approx(6.0)
        assert out["expected"] == pytest.approx(5.0)

    def test_missing_signal_renormalises(self):
        out = expected_national_margin(self.CFG, generic_two_party=4.0, approval_net=None)
        assert out["raw"] == pytest.approx(4.0)
        assert out["expected"] == pytest.approx(3.0)

    def test_no_signals(self):
        assert expected_national_margin(self.CFG, None, None)["expected"] is None


def test_full_pipeline_on_committed_data_is_sane():
    cfg = load_house_config()
    districts = load_districts()
    sim = HouseForecastSimulator(
        baseline_margin=cfg["baseline"]["two_party_margin"],
        national_sigma=2.5,
        district_sigma=cfg["district_error"]["district_sigma"],
        tail_dof=5.0,
        redistricting=cfg["redistricting"]["states"],
    )
    neutral = sim.simulate(districts, expected_national_margin=-2.4, num_simulations=4000, seed=0)
    # At the 2024 environment the model should roughly reproduce 2024 (215 D)
    # shifted by the configured redistricting net.
    assert abs(neutral.mean_dem_seats - (215 + sim.redistricting_shift_mean)) < 6
    wave = sim.simulate(districts, expected_national_margin=6.0, num_simulations=4000, seed=0)
    assert wave.mean_dem_seats > neutral.mean_dem_seats + 15
    assert wave.dem_majority_prob > 0.8
