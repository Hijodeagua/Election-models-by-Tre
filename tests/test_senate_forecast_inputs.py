"""Tests for the Senate-forecast input fixes (scripts/export_json.py):
nominee fallback without party tags, cycle-matched calibration bias, and the
campaign-drift term."""

from __future__ import annotations

from datetime import date

import pytest

from scripts.export_json import (
    _calibration_bias,
    _campaign_drift_sigma,
    _days_to_election,
    _top_other_candidate,
)


class TestTopOtherCandidate:
    def test_picks_remaining_head_to_head_name(self):
        cands = {"Chris Pappas": 48.6, "John E. Sununu": 42.3}
        assert _top_other_candidate(cands, "Chris Pappas") == "John E. Sununu"

    def test_never_promotes_undecided_or_tiny_shares(self):
        cands = {"Abdul El-Sayed": 47.0, "Undecided": 9.0, "Someone else": 3.0}
        assert _top_other_candidate(cands, "Abdul El-Sayed") is None

    def test_highest_share_wins_when_several_remain(self):
        cands = {"D": 45.0, "R1": 40.0, "R2": 22.0}
        assert _top_other_candidate(cands, "D") == "R1"


class TestCalibrationBias:
    CALIB = {
        "bias": -2.5,
        "n_races": 4,
        "cycles": [2018, 2020, 2022, 2024],
        "rows": [
            {"year": 2018, "error": 0.0},
            {"year": 2020, "error": -6.0},
            {"year": 2022, "error": -1.0},
            {"year": 2024, "error": -3.0},
        ],
    }

    def test_all_uses_pooled_fit(self):
        bias, n, years = _calibration_bias(self.CALIB, "all")
        assert bias == -2.5 and n == 4 and years == [2018, 2020, 2022, 2024]

    def test_midterm_averages_only_midterm_rows(self):
        bias, n, years = _calibration_bias(self.CALIB, "midterm")
        assert bias == pytest.approx(-0.5)
        assert n == 2 and years == [2018, 2022]

    def test_presidential_rows(self):
        bias, n, _ = _calibration_bias(self.CALIB, "presidential")
        assert bias == pytest.approx(-4.5) and n == 2

    def test_falls_back_to_pooled_without_rows(self):
        bias, n, _ = _calibration_bias({"bias": -1.1, "n_races": 9, "cycles": [2020]}, "midterm")
        assert bias == -1.1 and n == 9

    def test_unknown_type_rejected(self):
        with pytest.raises(ValueError):
            _calibration_bias(self.CALIB, "weird")

    def test_committed_calibration_midterm_bias_is_near_zero(self):
        # The pooled fit (-2.5) is dominated by 2020; the two midterms in the
        # calibration set show essentially no bias. This pins the empirical
        # fact the bias_cycle_type="midterm" setting rests on.
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parent.parent / "config" / "forecast_calibration.json"
        calib = json.loads(path.read_text())
        pooled, _, _ = _calibration_bias(calib, "all")
        midterm, n, years = _calibration_bias(calib, "midterm")
        assert years == [2018, 2022] and n > 30
        assert abs(midterm) < 1.0
        assert pooled < -2.0


class TestCampaignDrift:
    def test_days_floor_at_zero(self):
        assert _days_to_election("2026-11-03", date(2026, 11, 10)) == 0
        assert _days_to_election("2026-11-03", date(2026, 10, 4)) == 30
        assert _days_to_election(None, date(2026, 10, 4)) == 0

    def test_sigma_scales_with_sqrt_days(self):
        assert _campaign_drift_sigma(0.35, 0) == 0.0
        assert _campaign_drift_sigma(None, 30) == 0.0
        assert _campaign_drift_sigma(0.35, 16) == pytest.approx(1.4)
        assert _campaign_drift_sigma(0.35, 30) == pytest.approx(0.35 * 30**0.5)


class TestFundamentalsPrior:
    """End-to-end through the production path on the committed config, so the
    exported feature values are what the config says they should be."""

    @pytest.fixture(scope="class")
    def payload(self):
        from scripts.export_json import _senate_forecast_payload

        # No polls → every race runs on fundamentals alone (weight 1.0).
        return _senate_forecast_payload({"races": []}, approval_net=-20.0,
                                        generic_margin=5.0, quiet=True)

    def _race(self, payload, state):
        return next(r for r in payload["races"] if r["state"] == state)

    def test_components_sum_to_prior_and_prior_is_the_margin(self, payload):
        for r in payload["races"]:
            f = r["fundamentals"]
            parts = (f["lean"] + f["national_swing"] + f["incumbency_effect"]
                     + f["experience_effect"] + f["midterm_penalty_effect"])
            assert f["prior"] == pytest.approx(parts, abs=0.002)
            assert f["fundamentals_weight"] == 1.0
            assert r["margin"] == pytest.approx(f["prior"], abs=0.002)

    def test_incumbency_signs(self, payload):
        coefs = payload["fundamentals_coefficients"]
        adv = coefs["incumbency_advantage"]
        assert self._race(payload, "Maine")["fundamentals"]["incumbency_effect"] == -adv
        assert self._race(payload, "Georgia")["fundamentals"]["incumbency_effect"] == adv
        assert self._race(payload, "Michigan")["fundamentals"]["incumbency_effect"] == 0.0
        # Appointed incumbent (Husted) gets the reduced advantage.
        oh = self._race(payload, "Ohio")["fundamentals"]
        assert oh["incumbent_appointed"] is True
        assert oh["incumbency_effect"] == pytest.approx(-adv * coefs["appointed_incumbent_factor"])

    def test_experience_is_capped_and_signed(self, payload):
        coefs = payload["fundamentals_coefficients"]
        nc = self._race(payload, "North Carolina")["fundamentals"]  # Cooper: 6 statewide wins
        assert nc["experience_raw"] == pytest.approx(6 * coefs["experience_per_statewide_win"])
        assert nc["experience_effect"] == coefs["experience_cap"]
        tx = self._race(payload, "Texas")["fundamentals"]  # Paxton: 3 wins, Talarico: 0
        assert tx["experience_effect"] == pytest.approx(-3 * coefs["experience_per_statewide_win"])

    def test_lean_blends_presidential_and_2022(self, payload):
        f = self._race(payload, "Ohio")["fundamentals"]
        w, w22 = f["pres_weight_recent"], f["statewide_2022_weight"]
        pres = w * f["pres_2024"] + (1 - w) * f["pres_2020"]
        expected = (1 - w22) * pres + w22 * f["statewide_2022"]["margin"]
        assert f["lean"] == pytest.approx(expected, abs=0.002)
