"""Tests for the canonical poll deduplication rule (audit Finding 6)."""

from __future__ import annotations

from datetime import date

from src.data.base import Poll, PollAnswer, PollType, Population, dedupe_polls


def make_poll(
    pollster: str = "Tracker Inc",
    subject: str = "Trump",
    start: date = date(2026, 7, 1),
    end: date = date(2026, 7, 3),
    population: Population | None = Population.LIKELY_VOTERS,
    sample_size: int | None = 1000,
    poll_id: str = "",
) -> Poll:
    return Poll(
        poll_id=poll_id or f"{pollster}-{start}-{end}-{population}",
        source="test",
        poll_type=PollType.APPROVAL,
        pollster=pollster,
        subject=subject,
        start_date=start,
        end_date=end,
        sample_size=sample_size,
        population=population,
        answers=[PollAnswer("Approve", 45.0), PollAnswer("Disapprove", 50.0)],
    )


class TestMultiPopulationRelease:
    def test_lv_preferred_over_rv(self):
        lv = make_poll(population=Population.LIKELY_VOTERS)
        rv = make_poll(population=Population.REGISTERED_VOTERS)
        result = dedupe_polls([rv, lv])
        assert result == [lv]

    def test_rv_preferred_over_adults(self):
        rv = make_poll(population=Population.REGISTERED_VOTERS)
        adults = make_poll(population=Population.ADULTS)
        assert dedupe_polls([adults, rv]) == [rv]

    def test_sample_size_breaks_population_tie(self):
        small = make_poll(sample_size=600, poll_id="small")
        large = make_poll(sample_size=1500, poll_id="large")
        assert dedupe_polls([small, large]) == [large]


class TestOverlappingTrackingWindows:
    def test_overlapping_releases_keep_newest(self):
        # Daily tracker: 3-day windows released daily — heavy overlap
        releases = [
            make_poll(start=date(2026, 7, d), end=date(2026, 7, d + 2))
            for d in range(1, 6)  # ends 7/3 .. 7/7
        ]
        result = dedupe_polls(releases)
        ends = sorted(p.end_date for p in result)
        # Newest release (ends 7/7) always survives; kept windows never overlap
        assert date(2026, 7, 7) in ends
        for a in result:
            for b in result:
                if a is not b:
                    assert a.start_date > b.end_date or b.start_date > a.end_date

    def test_non_overlapping_polls_all_kept(self):
        weekly = [
            make_poll(start=date(2026, 7, 1), end=date(2026, 7, 3)),
            make_poll(start=date(2026, 7, 8), end=date(2026, 7, 10)),
            make_poll(start=date(2026, 7, 15), end=date(2026, 7, 17)),
        ]
        assert len(dedupe_polls(weekly)) == 3

    def test_different_pollsters_never_collapse(self):
        a = make_poll(pollster="Pollster A")
        b = make_poll(pollster="Pollster B")
        assert len(dedupe_polls([a, b])) == 2

    def test_different_subjects_never_collapse(self):
        oh = make_poll(subject="Ohio Senate 2026")
        nc = make_poll(subject="North Carolina Senate 2026")
        assert len(dedupe_polls([oh, nc])) == 2

    def test_empty_input(self):
        assert dedupe_polls([]) == []
