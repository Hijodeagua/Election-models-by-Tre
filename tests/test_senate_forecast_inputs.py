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
