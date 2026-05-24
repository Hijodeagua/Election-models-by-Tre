"""Regression tests for the six bug fixes from the code-review patch set.

Covers:
  Fix 1 — _parse_date_range cross-month year inference
  Fix 2 — compute_average future-poll filter
  Fix 3 — bayesian _blend_ci preserves single-side CI unchanged
  Fix 4 — VoteHubCsvLoader reads Subject column (Senate round-trip)
  Fix 5 — _make_poll_id avoids collisions on (subject, sponsor, population)
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.data.base import Poll, PollAnswer, PollType, Population
from src.data.votehub_csv import VoteHubCsvLoader, _make_poll_id, _parse_date_range
from src.models.bayesian import (
    bayesian_blend_approval,
    bayesian_blend_generic_ballot,
)
from src.models.approval import ApprovalSnapshot
from src.models.generic_ballot import GenericBallotSnapshot
from src.models.polling_average import PollingAverageEngine


# ─── Fix 1 ──────────────────────────────────────────────────────────────────────

class TestParseDateRange:
    def test_same_month_range(self):
        s, e, _, _ = _parse_date_range("May. 11-15", 2026)
        assert s == date(2026, 5, 11)
        assert e == date(2026, 5, 15)

    def test_cross_month_same_year(self):
        # Apr→May: same year, NOT year-1
        s, e, _, _ = _parse_date_range("Apr. 29-May. 5", 2026)
        assert s == date(2026, 4, 29)
        assert e == date(2026, 5, 5)

    def test_cross_year_dec_to_jan(self):
        # Dec→Jan within one entry: start month is in PRIOR year
        s, e, _, _ = _parse_date_range("Dec. 29-Jan. 3", 2026)
        assert s == date(2025, 12, 29)
        assert e == date(2026, 1, 3)

    def test_single_day(self):
        s, e, _, _ = _parse_date_range("May. 11", 2026)
        assert s == date(2026, 5, 11)
        assert e == date(2026, 5, 11)


# ─── Fix 2 ──────────────────────────────────────────────────────────────────────

def _mk_poll(pid: str, end: date, pct: float, pollster: str = "Pollster A") -> Poll:
    return Poll(
        poll_id=pid,
        source="test",
        poll_type=PollType.APPROVAL,
        pollster=pollster,
        subject="Donald Trump",
        start_date=end - timedelta(days=2),
        end_date=end,
        sample_size=1000,
        population=Population.REGISTERED_VOTERS,
        answers=[PollAnswer("Approve", pct), PollAnswer("Disapprove", 100 - pct)],
    )


class TestFuturePollFilter:
    def test_future_poll_excluded(self):
        as_of = date(2026, 1, 15)
        past = [_mk_poll(f"p{i}", as_of - timedelta(days=i * 2), 50.0) for i in range(1, 6)]
        future = _mk_poll("future", as_of + timedelta(days=30), 80.0)

        engine = PollingAverageEngine()
        without_future = engine.compute_average(past, as_of=as_of, choices=["Approve"])
        with_future = engine.compute_average(past + [future], as_of=as_of, choices=["Approve"])

        # The future poll must not affect the average at as_of.
        assert without_future.averages == with_future.averages
        assert without_future.num_polls == with_future.num_polls

    def test_filter_uses_end_date_not_midpoint(self):
        # A poll whose midpoint < as_of but end_date > as_of must still be excluded.
        # (Strict end_date filter — fieldwork still ongoing.)
        as_of = date(2026, 1, 15)
        straddler = Poll(
            poll_id="straddle",
            source="test",
            poll_type=PollType.APPROVAL,
            pollster="X",
            subject="Donald Trump",
            start_date=date(2026, 1, 10),
            end_date=date(2026, 1, 20),  # > as_of
            sample_size=1000,
            population=Population.REGISTERED_VOTERS,
            answers=[PollAnswer("Approve", 90.0), PollAnswer("Disapprove", 10.0)],
        )
        baseline = [_mk_poll(f"p{i}", as_of - timedelta(days=i), 50.0) for i in range(1, 8)]
        engine = PollingAverageEngine()
        out = engine.compute_average(baseline + [straddler], as_of=as_of, choices=["Approve"])
        # If straddler had been included its 90% would pull the average above 50.
        assert out.averages["Approve"] == pytest.approx(50.0, abs=0.5)


# ─── Fix 3 ──────────────────────────────────────────────────────────────────────

def _approval_snap(num_polls: int, ci_approve, ci_disapprove) -> ApprovalSnapshot:
    return ApprovalSnapshot(
        as_of=date(2026, 1, 15),
        approve=42.0,
        disapprove=52.0,
        net_approval=-10.0,
        num_polls=num_polls,
        ci_approve=ci_approve,
        ci_disapprove=ci_disapprove,
    )


class TestBlendCi:
    def test_both_cis_blend_linearly(self):
        poll = _approval_snap(14, (40.0, 44.0), (50.0, 54.0))
        prior = _approval_snap(14, (38.0, 43.0), (51.0, 55.0))
        prior.approve, prior.disapprove = 40.0, 53.0
        blended, alpha, beta = bayesian_blend_approval(poll, prior, k=6.0)
        assert blended is not None
        # Linear blend formula unchanged.
        expected_lo = alpha * 40.0 + beta * 38.0
        assert blended.ci_approve[0] == pytest.approx(expected_lo)

    def test_poll_only_ci_preserved_unchanged(self):
        poll = _approval_snap(14, (39.0, 41.0), (51.0, 53.0))
        prior = _approval_snap(14, None, None)
        blended, _, _ = bayesian_blend_approval(poll, prior, k=6.0)
        # Plan 1 framing: preserve available interval as display fallback
        # (NOT scale by alpha — that shrank toward zero).
        assert blended.ci_approve == (39.0, 41.0)
        assert blended.ci_disapprove == (51.0, 53.0)

    def test_prior_only_ci_preserved_unchanged(self):
        poll = _approval_snap(14, None, None)
        prior = _approval_snap(14, (37.0, 43.0), (50.0, 56.0))
        blended, _, _ = bayesian_blend_approval(poll, prior, k=6.0)
        assert blended.ci_approve == (37.0, 43.0)
        assert blended.ci_disapprove == (50.0, 56.0)

    def test_generic_ballot_poll_only_ci_preserved(self):
        poll = GenericBallotSnapshot(
            as_of=date(2026, 1, 15),
            dem_pct=46.0, rep_pct=44.0, margin=2.0,
            num_polls=14,
            estimated_dem_seats=None, estimated_rep_seats=None,
            ci_dem=(45.0, 47.0), ci_rep=(43.0, 45.0),
        )
        prior = GenericBallotSnapshot(
            as_of=date(2026, 1, 15),
            dem_pct=45.0, rep_pct=45.0, margin=0.0,
            num_polls=0,
            estimated_dem_seats=None, estimated_rep_seats=None,
            ci_dem=None, ci_rep=None,
        )
        blended, _, _ = bayesian_blend_generic_ballot(poll, prior, k=6.0)
        assert blended.ci_dem == (45.0, 47.0)
        assert blended.ci_rep == (43.0, 45.0)


# ─── Fix 4 + 5 ─────────────────────────────────────────────────────────────────

class TestSubjectAndPollId:
    def test_make_poll_id_distinct_subjects(self):
        d = date(2026, 5, 1)
        a = _make_poll_id("Marist", d, d, subject="PA-Senate")
        b = _make_poll_id("Marist", d, d, subject="OH-Senate")
        assert a != b

    def test_make_poll_id_distinct_sponsors(self):
        d = date(2026, 5, 1)
        a = _make_poll_id("Marist", d, d, subject="X", sponsor="NPR")
        b = _make_poll_id("Marist", d, d, subject="X", sponsor="NYT")
        assert a != b

    def test_make_poll_id_distinct_populations(self):
        d = date(2026, 5, 1)
        a = _make_poll_id("Marist", d, d, subject="X", sponsor="NPR", population="lv")
        b = _make_poll_id("Marist", d, d, subject="X", sponsor="NPR", population="rv")
        assert a != b

    def test_make_poll_id_deterministic(self):
        d = date(2026, 5, 1)
        a = _make_poll_id("Marist", d, d, subject="X")
        b = _make_poll_id("Marist", d, d, subject="X")
        assert a == b
        assert a.startswith("vh-csv-")

    def test_csv_loader_reads_subject_column(self, tmp_path: Path):
        csv_text = (
            "Date Range,Grade,Pollster,Subject,Sponsor,Sample Size,Sample Type,"
            "Population,Weight,Leading Result,Leading %,Trailing Result,"
            "Trailing %,Spread\n"
            "May. 11-15,A,Marist,PA-Senate,NPR,1000,LV,lv,1.0,Dem,49%,Rep,46%,3.0\n"
            "May. 11-15,A,Marist,OH-Senate,NPR,1000,LV,lv,1.0,Dem,42%,Rep,52%,-10.0\n"
        )
        path = tmp_path / "votehub_senate.csv"
        path.write_text(csv_text, encoding="utf-8")

        polls = VoteHubCsvLoader(PollType.HEAD_TO_HEAD).load(path)
        assert len(polls) == 2
        subjects = {p.subject for p in polls}
        assert subjects == {"PA-Senate", "OH-Senate"}
        # Distinct IDs prove Fix 5 works for the round-trip.
        ids = {p.poll_id for p in polls}
        assert len(ids) == 2

    def test_csv_loader_backwards_compat_no_subject_column(self, tmp_path: Path):
        # Legacy file without Subject column still loads; default is used.
        csv_text = (
            "Date Range,Grade,Pollster,Sponsor,Sample Size,Sample Type,"
            "Population,Weight,Leading Result,Leading %,Trailing Result,"
            "Trailing %,Spread\n"
            "May. 11-15,A,Marist,NPR,1000,A,a,1.0,Approve,45%,Disapprove,52%,-7.0\n"
        )
        path = tmp_path / "votehub_approval.csv"
        path.write_text(csv_text, encoding="utf-8")

        polls = VoteHubCsvLoader(PollType.APPROVAL).load(path)
        assert len(polls) == 1
        assert polls[0].subject == "Donald Trump"  # _default_subject for APPROVAL
