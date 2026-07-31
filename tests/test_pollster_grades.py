"""Tests for the fitted pollster grading system."""

from __future__ import annotations

import pytest

from src.analysis.pollster_grades import (
    GRADE_PERCENTILES,
    GradeBook,
    RawPoll,
    build_records,
    normalize_name,
    normalize_poll_row,
    quality_from_par,
)


def _row(**kw) -> dict:
    base = {
        "type_simple": "Sen-G", "cycle": "2020", "race_id": "1", "location": "GA",
        "pollster": "Test Polling", "time_to_election": "10", "samplesize": "800",
        "methodology": "Live Phone", "partisan": "NA",
        "cand1_party": "DEM", "cand2_party": "REP",
        "margin_poll": "5", "margin_actual": "2",
    }
    base.update(kw)
    return base


class TestNormalizePollRow:
    def test_dem_first_keeps_sign(self):
        p = normalize_poll_row(_row())
        assert p.dem_margin_poll == 5 and p.dem_margin_actual == 2
        assert p.signed_error == 3  # poll overstated the Democrat by 3

    def test_rep_first_flips_sign(self):
        p = normalize_poll_row(_row(cand1_party="REP", cand2_party="DEM"))
        assert p.dem_margin_poll == -5 and p.dem_margin_actual == -2
        assert p.signed_error == -3

    def test_primaries_dropped(self):
        assert normalize_poll_row(_row(type_simple="Sen-P")) is None

    def test_third_party_matchup_dropped(self):
        assert normalize_poll_row(_row(cand2_party="IND")) is None

    def test_unparseable_margin_dropped(self):
        assert normalize_poll_row(_row(margin_poll="")) is None

    def test_missing_sample_size_is_tolerated(self):
        assert normalize_poll_row(_row(samplesize="")).sample_size is None


def _poll(pollster, race, err, cycle=2022, ttoe=10) -> RawPoll:
    return RawPoll(pollster=pollster, cycle=cycle, race_id=race, race_type="Sen-G",
                   location="GA", time_to_election=ttoe, sample_size=800,
                   methodology="Live Phone", partisan=None,
                   dem_margin_poll=err, dem_margin_actual=0.0)


class TestBuildRecords:
    def test_par_is_leave_one_out(self):
        """A pollster is scored against the rest of the field, not against itself."""
        polls = []
        for i in range(30):
            polls.append(_poll("Sharp", f"r{i}", 1.0))
            polls.append(_poll("Blunt", f"r{i}", 5.0))
            polls.append(_poll("Middling", f"r{i}", 3.0))
        recs = {r.pollster: r for r in build_records(polls)}
        assert recs["Sharp"].par_error < recs["Middling"].par_error < recs["Blunt"].par_error
        # Sharp is 1.0 off; the field excluding Sharp averages 4.0 off.
        assert recs["Sharp"].par_error == pytest.approx(-3.0, abs=0.01)

    def test_lean_is_signed_and_par_is_not(self):
        """A house that is consistently wrong in one direction has a lean but
        the same par error as one that is wrong by as much in both."""
        polls = []
        for i in range(30):
            polls.append(_poll("Skewed", f"r{i}", 4.0))
            polls.append(_poll("Noisy", f"r{i}", 4.0 if i % 2 else -4.0))
            polls.append(_poll("Filler", f"r{i}", 1.0))
        recs = {r.pollster: r for r in build_records(polls)}
        assert recs["Skewed"].lean == pytest.approx(4.0, abs=0.01)
        assert recs["Noisy"].lean == pytest.approx(0.0, abs=0.01)
        assert recs["Skewed"].par_error == pytest.approx(recs["Noisy"].par_error, abs=0.01)

    def test_shrinkage_pulls_thin_records_toward_the_pool(self):
        """Ten perfect polls must not outrank a long record of near-perfect ones."""
        polls = [_poll("Filler", f"r{i}", 3.0) for i in range(60)]
        polls += [_poll("Filler2", f"r{i}", 3.0) for i in range(60)]
        polls += [_poll("Lucky", f"r{i}", 0.0) for i in range(10)]
        polls += [_poll("Steady", f"r{i}", 0.2) for i in range(60)]
        recs = {r.pollster: r for r in build_records(polls)}
        assert abs(recs["Lucky"].par_error_shrunk) < abs(recs["Lucky"].par_error)
        assert recs["Steady"].par_error_shrunk < recs["Lucky"].par_error_shrunk

    def test_thin_records_are_not_graded(self):
        polls = [_poll("Filler", f"r{i}", 2.0) for i in range(40)]
        polls += [_poll("Filler2", f"r{i}", 3.0) for i in range(40)]
        polls += [_poll("Barely There", "r0", 1.0)]
        names = {r.pollster for r in build_records(polls)}
        assert "Barely There" not in names

    def test_races_with_too_few_polls_are_skipped(self):
        """Par is undefined without a field to compare against."""
        assert build_records([_poll("Solo", "r0", 1.0), _poll("Solo2", "r0", 2.0)]) == []

    def test_every_record_gets_a_valid_grade(self):
        polls = []
        for i in range(40):
            for j, name in enumerate(["A", "B", "C", "D", "E"]):
                polls.append(_poll(name, f"r{i}", float(j)))
        recs = build_records(polls)
        letters = {g for _, g in GRADE_PERCENTILES}
        assert recs and all(r.grade in letters for r in recs)
        # Sorted best first, so grades run best to worst.
        assert recs[0].par_error_shrunk <= recs[-1].par_error_shrunk

    def test_recency_decay_is_off_by_default(self):
        """Decay lost on both holdout splits, so the default is no decay.

        This is deliberate and counterintuitive enough to be worth pinning: an
        old poll is bad evidence about today's race but good evidence about a
        pollster's house effect.
        """
        import src.analysis.pollster_grades as PG
        assert PG.RECENCY_HALF_LIFE_CYCLES is None
        assert PG._recency_weight(1998, 2022) == 1.0

    def test_recency_decay_works_when_enabled(self, monkeypatch):
        import src.analysis.pollster_grades as PG
        monkeypatch.setattr(PG, "RECENCY_HALF_LIFE_CYCLES", 2.0)
        assert PG._recency_weight(2022, 2022) == 1.0
        assert PG._recency_weight(2018, 2022) < PG._recency_weight(2020, 2022) < 1.0

        old = [_poll("Faded", f"r{i}", 0.0, cycle=1998) for i in range(40)]
        new = [_poll("Faded", f"r{i}", 6.0, cycle=2022) for i in range(40)]
        filler = [_poll(f"F{j}", f"r{i}", 3.0, cycle=c)
                  for i in range(40) for j, c in enumerate([1998, 2022])]
        recs = {r.pollster: r for r in build_records(old + new + filler)}
        # With decay on, the recent bad run dominates the ancient good one.
        assert recs["Faded"].par_error > 0


class TestQualityMapping:
    def test_par_zero_is_midscale(self):
        assert quality_from_par(0.0) == pytest.approx(1.5)

    def test_monotone_decreasing_in_error(self):
        assert quality_from_par(-2.0) > quality_from_par(0.0) > quality_from_par(2.0)

    def test_clamped_to_scale(self):
        assert 0.0 <= quality_from_par(-100.0) <= 3.0
        assert 0.0 <= quality_from_par(100.0) <= 3.0


class TestNameResolution:
    def test_strips_sponsor_party_tags(self):
        assert normalize_name("Trafalgar Group (R)") == normalize_name("Trafalgar Group")

    def test_strips_filler_words(self):
        assert normalize_name("Marquette University Law School") == normalize_name("Marquette Law School")

    def test_distinct_shops_stay_distinct(self):
        assert normalize_name("Emerson College") != normalize_name("Suffolk University")


class TestGradeBook:
    def _book(self) -> GradeBook:
        return GradeBook({
            "_meta": {"unknown_default": 1.2},
            "grades": [
                {"pollster": "Marquette Law School", "grade": "A", "quality": 1.9,
                 "lean_shrunk": 2.0, "n_weighted": 30.0},
                {"pollster": "Trafalgar Group", "grade": "C", "quality": 1.1,
                 "lean_shrunk": -2.0, "n_weighted": 10.0},
            ],
        })

    def test_resolves_tagged_and_reworded_names(self):
        b = self._book()
        assert b.grade("Trafalgar Group (R)") == "C"
        assert b.grade("Marquette University Law School") == "A"

    def test_unknown_name_falls_back(self):
        b = self._book()
        assert b.get("Nobody Polling") is None
        assert b.quality("Nobody Polling") == 1.2
        assert b.lean("Nobody Polling") == 0.0

    def test_pool_lean_is_volume_weighted(self):
        # (2.0*30 + -2.0*10) / 40
        assert self._book().pool_lean == pytest.approx(1.0)

    def test_relative_lean_is_centred_on_the_pool(self):
        b = self._book()
        assert b.relative_lean("Marquette Law School") == pytest.approx(1.0)
        assert b.relative_lean("Trafalgar Group") == pytest.approx(-3.0)

    def test_unrated_house_is_treated_as_average(self):
        """No record means no correction — not a correction of zero lean."""
        assert self._book().relative_lean("Nobody Polling") == 0.0
