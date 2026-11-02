"""Phase 0/1 merge rules: variant collapse, researched-sheet precedence
(same dates or ±7 days), overrides, UNCONFIRMED exclusion."""

from __future__ import annotations

from datetime import date

from scripts.export_json import (
    apply_overrides,
    collapse_variants,
    drop_unconfirmed,
    merge_researched,
)
from src.data.base import Poll, PollAnswer, PollType

MT, SC, FL = "Montana Senate 2026", "South Carolina Senate 2026", "Florida Senate 2026"
RI, MS = "Rhode Island Senate 2026", "Mississippi Senate 2026"
LA, TN = "Louisiana Senate 2026", "Tennessee Senate 2026"
D = date


def _p(subject, pollster, start, end, d, r, flags="", pid=None):
    return Poll(
        poll_id=pid or f"{subject}-{pollster}-{end}-{d}", source="t",
        poll_type=PollType.HEAD_TO_HEAD, pollster=pollster, subject=subject,
        start_date=start, end_date=end, sample_size=500, population=None,
        answers=[PollAnswer(choice="Dem", pct=d, party="Democrat"),
                 PollAnswer(choice="Rep", pct=r, party="Republican")],
        raw={"quality_flags": flags},
    )


def test_collapse_keeps_first_variant_per_pollster_and_field_dates():
    polls = [
        _p(MT, "Quantus Insights (R)", D(2026, 10, 15), D(2026, 10, 18), 21, 46),
        _p(MT, "Quantus Insights (R)", D(2026, 10, 15), D(2026, 10, 18), 21, 44),
        _p(MT, "Quantus Insights (R)", D(2026, 10, 15), D(2026, 10, 18), 22, 47),
        _p(MT, "Quantus Insights (R)", D(2026, 9, 14), D(2026, 9, 15), 23, 44),
    ]
    out, notes = collapse_variants(polls)
    assert [p.answers[1].pct for p in out] == [46, 44]
    assert len(notes) == 2


def test_researched_sheet_replaces_release_dated_supplement_rows():
    feed = [
        _p(SC, "Siena/NYT", D(2026, 10, 28), D(2026, 10, 28), 48, 48),
        _p(SC, "The Citadel", D(2026, 10, 28), D(2026, 10, 28), 39, 43),
        # 17 days before the sheet's Trafalgar poll: kept, not replaced.
        _p(SC, "Trafalgar Group", D(2026, 10, 1), D(2026, 10, 1), 45, 49),
        _p(FL, "Big Data Poll", D(2026, 10, 30), D(2026, 10, 30), 45, 52),
    ]
    sheet = [
        _p(SC, "NYT/Siena", D(2026, 10, 19), D(2026, 10, 26), 47.76, 48.47),
        _p(SC, "The Citadel Poll", D(2026, 10, 14), D(2026, 10, 25), 39, 42),
        _p(SC, "Trafalgar Group", D(2026, 10, 16), D(2026, 10, 18), 45.6, 48.6),
        _p(FL, "Big Data Poll", D(2026, 10, 26), D(2026, 10, 30), 42, 48),
    ]
    merged, notes = merge_researched(feed, sheet)
    pollsters = sorted((p.subject[:2], p.pollster, p.end_date.isoformat()) for p in merged)
    assert pollsters == [
        ("Fl", "Big Data Poll", "2026-10-30"),
        ("So", "NYT/Siena", "2026-10-26"),
        ("So", "The Citadel Poll", "2026-10-25"),
        ("So", "Trafalgar Group", "2026-10-01"),
        ("So", "Trafalgar Group", "2026-10-18"),
    ]
    assert len(notes) == 3 and all(n.startswith("replaced") for n in notes)


def test_unconfirmed_rows_are_excluded_and_logged():
    polls = [
        _p(RI, "UNH Survey Center", D(2026, 10, 27), D(2026, 10, 31), 63, 32,
           flags="UNCONFIRMED: not on scholars.unh.edu"),
        _p(RI, "Emerson College", D(2026, 10, 8), D(2026, 10, 11), 59, 25),
    ]
    out, notes = drop_unconfirmed(polls)
    assert [p.pollster for p in out] == ["Emerson College"] and len(notes) == 1


def test_overrides_drop_relabel_and_fix_toplines():
    polls = [
        _p(MS, "Wedgewood Polls", D(2026, 10, 12), D(2026, 10, 14), 48, 52),
        _p(MS, "Impact Research (D)", D(2026, 10, 21), D(2026, 10, 22), 39, 43),
        _p(LA, "Hart Research Associates (D)", D(2026, 10, 28), D(2026, 10, 29), 45, 45.5),
        _p(TN, "Targoz Market Research", D(2026, 8, 15), D(2026, 8, 26), 31, 51),
        _p(TN, "Targoz Market Research", D(2026, 8, 15), D(2026, 8, 26), 33, 58, pid="lv"),
    ]
    rules = [
        {"id": "a", "subject": MS, "pollster": "Wedgewood Polls", "action": "drop",
         "reason": "fab"},
        {"id": "b", "subject": MS, "pollster": "Impact Research", "end_date": "2026-10-22",
         "tolerance_days": 3, "action": "relabel",
         "pollster_new": "Change Research (D, The 365 Project)",
         "dem_pct": 40, "rep_pct": 43, "reason": "mislabel"},
        {"id": "c", "subject": LA, "pollster": "Hart Research Associates",
         "end_date": "2026-10-29", "tolerance_days": 2,
         "action": "set_toplines", "dem_pct": 45, "rep_pct": 45, "reason": "tie"},
        {"id": "d", "subject": TN, "pollster": "Targoz Market Research", "end_date": "2026-08-26",
         "tolerance_days": 2, "dem_pct": 33, "rep_pct": 58, "action": "drop", "reason": "LV cut"},
        {"id": "e", "subject": "New Jersey Senate 2026", "pollster": "StimSight Research",
         "action": "drop", "reason": "district"},
    ]
    out, notes = apply_overrides(polls, rules)
    by = {(p.subject[:2], p.pollster): p for p in out}
    assert ("Mi", "Wedgewood Polls") not in by
    assert by[("Mi", "Change Research (D, The 365 Project)")].answers[0].pct == 40
    assert [a.pct for a in by[("Lo", "Hart Research Associates (D)")].answers] == [45, 45]
    tn = [p for p in out if p.subject.startswith("Tennessee")]
    assert len(tn) == 1 and tn[0].answers[1].pct == 51
    assert any("no matching poll" in n for n in notes)  # StimSight not loaded → no-op logged
