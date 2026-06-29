"""Tests for the national midterm environment term (scripts/export_json.py).

The environment translates today's presidential approval + generic ballot into
a uniform Dem−Rep swing relative to the 2024 House baseline, which shifts the
fundamentals prior in the Senate-control forecast.
"""

from __future__ import annotations

import pytest

from scripts.export_json import _national_environment

# Mirrors config/senate_2026.json's national_environment block.
CFG = {
    "president_party": "R",
    "house_baseline_2024": -2.8,
    "generic_weight": 0.6,
    "approval_weight": 0.4,
    "approval_to_margin_coef": 0.3,
    "senate_responsiveness": 1.0,
}


def test_swing_is_dem_favorable_under_unpopular_r_president():
    # Net approval -19.7 (R president) + generic D+5.1 should push the
    # environment well to the Democrats' side of the 2024 baseline.
    env = _national_environment(CFG, approval_net=-19.7, generic_margin=5.1)
    assert env["available"]
    # approval term flips to Dem−Rep: -(0.3 * -19.7) = +5.91
    assert env["approval_implied_margin"] == pytest.approx(5.91, abs=1e-2)
    # weighted expected margin then swing vs -2.8 baseline.
    assert env["expected_national_margin"] == pytest.approx(5.424, abs=1e-2)
    assert env["national_swing"] == pytest.approx(8.224, abs=1e-2)


def test_approval_sign_flips_with_president_party():
    r = _national_environment(CFG, approval_net=-19.7, generic_margin=None)
    d_cfg = {**CFG, "president_party": "D"}
    d = _national_environment(d_cfg, approval_net=-19.7, generic_margin=None)
    # Same net approval, opposite in-party → opposite-signed Dem−Rep term.
    assert r["approval_implied_margin"] == pytest.approx(-d["approval_implied_margin"])
    assert r["approval_implied_margin"] > 0  # unpopular R president helps Dems


def test_missing_feed_renormalises_weights():
    # With only the generic ballot present, the swing must use the generic
    # term alone (not halve it because approval weight is missing).
    env = _national_environment(CFG, approval_net=None, generic_margin=5.1)
    assert env["expected_national_margin"] == pytest.approx(5.1, abs=1e-6)
    assert env["national_swing"] == pytest.approx(5.1 - (-2.8), abs=1e-6)


def test_no_signals_means_zero_swing():
    env = _national_environment(CFG, approval_net=None, generic_margin=None)
    assert env["national_swing"] == 0.0
    assert env["available"] is False


def test_absent_config_is_a_noop():
    env = _national_environment({}, approval_net=-19.7, generic_margin=5.1)
    assert env["national_swing"] == 0.0
    assert env["available"] is False


def test_responsiveness_scales_the_swing():
    half = _national_environment(
        {**CFG, "senate_responsiveness": 0.5}, approval_net=-19.7, generic_margin=5.1
    )
    full = _national_environment(CFG, approval_net=-19.7, generic_margin=5.1)
    assert half["national_swing"] == pytest.approx(0.5 * full["national_swing"], abs=1e-2)
