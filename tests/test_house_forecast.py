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


class TestDistrictLean:
    def test_blends_2022_when_available(self):
        sim = _sim(lean_weight_2024=0.75, lean_weight_2022=0.25, incumbency_advantage=2.5)
        d = DistrictInput("XX", "District 1", margin_2024=4.0, winner_2024="D", margin_2022=8.0)
        lean, adjust = sim.district_lean(d)
        assert lean == pytest.approx(5.0)
        assert adjust == 0.0

    def test_falls_back_to_2024_without_2022(self):
        sim = _sim(lean_weight_2024=0.75, lean_weight_2022=0.25)
        d = DistrictInput("XX", "District 1", margin_2024=4.0, winner_2024="D", margin_2022=None)
        assert sim.district_lean(d)[0] == pytest.approx(4.0)

    def test_open_seat_loses_incumbent_advantage(self):
        sim = _sim(incumbency_advantage=2.5)
        d_open = DistrictInput(
            "XX", "District 1", margin_2024=4.0, winner_2024="D", open_seat=True
        )
        r_open = DistrictInput(
            "XX", "District 2", margin_2024=-4.0, winner_2024="R", open_seat=True
        )
        assert sim.district_lean(d_open)[1] == -2.5
        assert sim.district_lean(r_open)[1] == 2.5
        held = DistrictInput("XX", "District 3", margin_2024=4.0, winner_2024="D")
        assert sim.district_lean(held)[1] == 0.0

    def test_open_seat_lowers_win_probability_in_simulation(self):
        sim = _sim(incumbency_advantage=2.5)
        held = [DistrictInput("XX", "District 1", margin_2024=1.0, winner_2024="D")]
        open_ = [
            DistrictInput("XX", "District 1", margin_2024=1.0, winner_2024="D", open_seat=True)
        ]
        p_held = sim.simulate(held, -2.4, num_simulations=20000, seed=5).districts[0].dem_win_prob
        p_open = sim.simulate(open_, -2.4, num_simulations=20000, seed=5).districts[0].dem_win_prob
        assert p_open < p_held - 0.05

    def test_feature_values_are_exported_per_district(self):
        sim = _sim(lean_weight_2024=0.75, lean_weight_2022=0.25, incumbency_advantage=2.5)
        d = DistrictInput("XX", "District 1", 4.0, "D", margin_2022=8.0, open_seat=True,
                          open_seat_reason="retiring")
        fc = sim.simulate([d], -2.4, num_simulations=100, seed=0).districts[0]
        assert fc.margin_2022 == 8.0 and fc.lean == 5.0 and fc.incumbency_adjust == -2.5
        assert fc.open_seat and fc.open_seat_reason == "retiring" and fc.incumbent_party == ""
        assert fc.expected_margin == pytest.approx(5.0 - 2.5 + 0.0, abs=0.01)

    def test_committed_open_seats_all_resolve_and_2022_margins_load(self):
        cfg = load_house_config()
        districts = load_districts(open_seats=cfg["district_lean"]["open_seats"]["districts"])
        assert sum(1 for d in districts if d.open_seat) == len(
            cfg["district_lean"]["open_seats"]["districts"]
        )
        assert sum(1 for d in districts if d.margin_2022 is not None) > 300
        # Redrawn-for-2024 states carry no 2022 margin.
        assert all(d.margin_2022 is None for d in districts if d.state in {"NC", "NY", "GA"})

    def test_unknown_open_seat_label_is_an_error(self):
        with pytest.raises(ValueError):
            load_districts(open_seats=[{"label": "ZZ-99"}])


class TestDistrictSimilarity:
    def test_similarity_matrix_is_unit_diagonal_psd_and_ordered(self):
        import numpy as np

        ds = [
            DistrictInput("OH", "District 1", -2.0, "R"),
            DistrictInput("OH", "District 9", -1.0, "R"),
            DistrictInput("CA", "District 13", 0.0, "D"),
            DistrictInput("CA", "District 45", 30.0, "D"),
        ]
        sim = _sim(similarity_share=0.4, regions={"OH": "Midwest", "CA": "West"})
        k = sim.similarity_matrix(ds)
        assert np.allclose(np.diag(k), 1.0)
        assert np.all(np.linalg.eigvalsh(k) > -1e-9)
        assert k[0, 1] > k[0, 2] > k[0, 3]  # same state+lean > lean only > neither

    def test_similarity_keeps_marginals_and_widens_seats(self):
        import numpy as np

        ds = [DistrictInput("OH", f"District {i}", m, "D" if m > 0 else "R")
              for i, m in enumerate([-3, -2, -1, 0, 1, 2, 3])]
        base = _sim(dem_majority_threshold=4).simulate(ds, -2.4, num_simulations=30000, seed=1)
        corr = _sim(dem_majority_threshold=4, similarity_share=0.6).simulate(
            ds, -2.4, num_simulations=30000, seed=1
        )
        for a, b in zip(base.districts, corr.districts, strict=True):
            assert b.dem_win_prob == pytest.approx(a.dem_win_prob, abs=0.02)
        assert (corr.seats_p90 - corr.seats_p10) >= (base.seats_p90 - base.seats_p10)
        assert corr.similarity_share == 0.6
        assert np.isfinite(corr.mean_dem_seats)


class TestStateFundamentals:
    def test_state_presidential_file_covers_every_state(self):
        from src.models.house_forecast import load_state_presidential

        sp = load_state_presidential()
        assert len(sp) == 51 and sp["TX"]["pres_2024"] < 0 < sp["CA"]["pres_2024"]
        assert sp["GA"]["national_2024"] == -1.5

    def test_state_trend_and_econ_adjust_enter_expected_margin(self):
        sim = _sim(state_trend_weight=0.2, national_trend=-6.0)
        d = DistrictInput("TX", "District 15", -14.0, "R", state_pres_2024=-13.6,
                          state_pres_2020=-5.6, state_adjust=-0.3)
        # TX moved R by 8.0 vs national 6.0 → +(-2.0)*0.2 = -0.4 ; econ -0.3
        assert sim.state_trend_adjust(d) == pytest.approx(-0.4)
        assert sim.district_base(d) == pytest.approx(-14.0 - 0.4 - 0.3)
        fc = sim.simulate([d], -2.4, num_simulations=50, seed=0).districts[0]
        assert fc.state_trend_adjust == -0.4 and fc.econ_adjust == -0.3
        assert fc.incumbent is True and fc.incumbent_party == "R"
        assert fc.state_pres_2024 == -13.6

    def test_expected_national_margin_includes_inflation(self):
        cfg = {"national_environment": {"president_party": "R", "generic_weight": 1.0,
                                        "approval_weight": 0.0, "generic_ballot_bias": 0.0}}
        out = expected_national_margin(cfg, 5.0, None, economy={"inflation_effect": 0.27})
        assert out["expected"] == pytest.approx(5.27)
