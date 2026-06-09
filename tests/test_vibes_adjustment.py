"""Tests for the NYT vibes adjustment layer (src/models/vibes_adjustment.py)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.models.vibes_adjustment import (
    MAX_ADJUSTMENT,
    SCANDAL_PENALTY_POINTS,
    TONE_POINTS_PER_BUCKET,
    CandidateVibesRecord,
    VibesAdjustedSenateModel,
    VibesCsvSource,
)

FALLBACK_DIR = Path(__file__).resolve().parent.parent / "data" / "fallback"
RACE = "Georgia Senate 2026"


def _record(candidate: str, bucket: int = 0, scandal: float = 0.0) -> CandidateVibesRecord:
    return CandidateVibesRecord(
        candidate=candidate,
        race=RACE,
        as_of=date(2026, 5, 19),
        bucket_numeric=bucket,
        scandal_severity=scandal,
    )


class TestEffectPoints:
    def test_neutral_candidate_has_zero_effect(self):
        assert _record("Ossoff").effect_points == 0.0

    def test_positive_tone_helps(self):
        assert _record("Ossoff", bucket=2).effect_points == pytest.approx(
            2 * TONE_POINTS_PER_BUCKET
        )

    def test_scandal_hurts(self):
        rec = _record("Collins", scandal=1.0)
        assert rec.effect_points == pytest.approx(-SCANDAL_PENALTY_POINTS)


class TestAdjustment:
    def test_neutral_records_yield_zero_adjustment(self):
        model = VibesAdjustedSenateModel([_record("Ossoff"), _record("Collins")])
        adj = model.adjustment_for_race(RACE, "Ossoff", "Collins")
        assert adj.adjustment == 0.0
        assert adj.has_data

    def test_rep_scandal_moves_margin_toward_dem(self):
        model = VibesAdjustedSenateModel(
            [_record("Ossoff"), _record("Collins", scandal=0.8)]
        )
        adj = model.adjustment_for_race(RACE, "Ossoff", "Collins")
        assert adj.adjustment > 0

    def test_adjustment_is_clamped(self):
        model = VibesAdjustedSenateModel(
            [_record("Ossoff", bucket=2), _record("Collins", bucket=-2, scandal=1.0)]
        )
        adj = model.adjustment_for_race(RACE, "Ossoff", "Collins")
        assert adj.adjustment == MAX_ADJUSTMENT

    def test_missing_candidates_yield_no_data(self):
        model = VibesAdjustedSenateModel([])
        adj = model.adjustment_for_race(RACE, "Ossoff", "Collins")
        assert not adj.has_data
        assert adj.adjustment == 0.0
        assert adj.as_of is None

    def test_name_matching_is_substring_tolerant(self):
        model = VibesAdjustedSenateModel([_record("Jon Ossoff")])
        adj = model.adjustment_for_race(RACE, "Ossoff", "Collins")
        assert adj.dem_record is not None


class TestCsvSource:
    def test_committed_placeholder_loads_and_is_neutral(self):
        records = VibesCsvSource(FALLBACK_DIR).load()
        assert len(records) > 0
        # The committed file is a neutral placeholder until the NYT
        # pipeline runs with an API key — adjustment must be zero.
        assert all(r.bucket_numeric == 0 and r.scandal_severity == 0.0 for r in records)

    def test_missing_file_returns_empty(self, tmp_path):
        assert VibesCsvSource(tmp_path).load() == []

    def test_malformed_rows_skipped(self, tmp_path):
        (tmp_path / "nyt_vibes.csv").write_text(
            "candidate,race,as_of,bucket_numeric,scandal_severity\n"
            "Ossoff,GA,2026-05-19,1,0.2\n"
            "Bad,GA,not-a-date,1,0.2\n"
        )
        records = VibesCsvSource(tmp_path).load()
        assert len(records) == 1
        assert records[0].candidate == "Ossoff"
