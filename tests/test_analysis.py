"""Tests for analysis utilities."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.analysis.historical import MIDTERM_BENCHMARKS, compare_to_cycle
from src.analysis.pollster_weights import PollsterWeightManager
from src.analysis.trend import TrendPoint, moving_average


# ── Pollster weights ──────────────────────────────────────────────────


class TestPollsterWeightManager:
    def test_load_default_ratings(self):
        mgr = PollsterWeightManager()
        # Should load from config/pollster_ratings.json
        assert mgr.get_rating("Marist College") == 2.9

    def test_unknown_pollster_gets_default(self):
        mgr = PollsterWeightManager()
        assert mgr.get_rating("Unknown Pollster Inc") == 1.5

    def test_case_insensitive_lookup(self):
        mgr = PollsterWeightManager()
        assert mgr.get_rating("marist college") == 2.9

    def test_set_and_get_rating(self):
        mgr = PollsterWeightManager()
        mgr.set_rating("New Pollster", 2.0)
        assert mgr.get_rating("New Pollster") == 2.0

    def test_invalid_rating_rejected(self):
        mgr = PollsterWeightManager()
        with pytest.raises(ValueError):
            mgr.set_rating("Bad", 5.0)
        with pytest.raises(ValueError):
            mgr.set_rating("Bad", -1.0)

    def test_save_and_reload(self, tmp_path: Path):
        ratings_path = tmp_path / "ratings.json"
        mgr = PollsterWeightManager(ratings_path=ratings_path)
        mgr.set_rating("Custom Pollster", 2.5)
        mgr.save()

        mgr2 = PollsterWeightManager(ratings_path=ratings_path)
        assert mgr2.get_rating("Custom Pollster") == 2.5


# ── Trend ─────────────────────────────────────────────────────────────


class TestMovingAverage:
    def test_single_point(self):
        result = moving_average([date(2026, 1, 1)], [45.0], window_days=7)
        assert len(result) == 1
        assert result[0].value == 45.0

    def test_smoothing_effect(self):
        dates = [date(2026, 1, i) for i in range(1, 8)]
        values = [40.0, 42.0, 41.0, 45.0, 44.0, 43.0, 46.0]
        result = moving_average(dates, values, window_days=5)
        # Smoothed values should have less variance than raw values
        raw_range = max(values) - min(values)
        smooth_range = max(r.value for r in result) - min(r.value for r in result)
        assert smooth_range <= raw_range

    def test_empty_input(self):
        assert moving_average([], [], window_days=7) == []


# ── Historical comparisons ───────────────────────────────────────────


class TestHistorical:
    def test_compare_to_known_cycle(self):
        result = compare_to_cycle(43.0, 2022)
        assert result is not None
        assert result["approval_diff"] == pytest.approx(43.0 - 41.3, abs=0.1)
        assert result["benchmark_seat_change"] == -9

    def test_compare_to_unknown_cycle(self):
        assert compare_to_cycle(43.0, 1900) is None

    def test_benchmarks_have_expected_years(self):
        assert 2022 in MIDTERM_BENCHMARKS
        assert 2018 in MIDTERM_BENCHMARKS
        assert 2010 in MIDTERM_BENCHMARKS
