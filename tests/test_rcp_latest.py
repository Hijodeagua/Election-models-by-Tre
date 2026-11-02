"""RealClearPolling latest-polls text parser, against a saved page excerpt."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.data.base import PollType
from src.data.rcp_latest import parse_latest_polls_html, parse_latest_polls_text

FIXTURE = Path(__file__).parent / "fixtures" / "rcp_latest_polls_2026-11-01.txt"


def _race(state, dem, rep):
    return {
        "state": state, "race": f"{state} Senate 2026",
        "dem_candidate": dem, "rep_candidate": rep,
    }


RACES = [
    _race("Maine", "Troy Jackson", "Susan Collins"),
    _race("Texas", "James Talarico", "Ken Paxton"),
    _race("Ohio", "Sherrod Brown", "Jon Husted"),
    _race("Iowa", "Josh Turek", "Ashley Hinson"),
    _race("Nebraska", "Dan Osborn", "Pete Ricketts"),
    _race("Florida", "Angie Nixon", "Ashley Moody"),
    _race("Alaska", "Mary Peltola", "Dan Sullivan"),
    _race("South Carolina", "Annie Andrews", "Darline Graham"),
    _race("New Hampshire", "Chris Pappas", "John E. Sununu"),
]


def test_parses_senate_and_generic_rows_with_dates_and_parties():
    polls = parse_latest_polls_text(FIXTURE.read_text(), RACES, today=date(2026, 11, 2))
    senate = [p for p in polls if p.poll_type == PollType.HEAD_TO_HEAD]
    generic = [p for p in polls if p.poll_type == PollType.GENERIC_BALLOT]
    # 12 Senate lines in the fixture; the RCV first-round line is skipped.
    assert len(senate) == 11
    assert len(generic) == 1

    by = {(p.subject, p.pollster): p for p in senate}
    me = by[("Maine Senate 2026", "YouGov")]
    assert me.end_date == date(2026, 11, 1)
    assert {(a.choice, a.pct, a.party) for a in me.answers} == {
        ("Troy Jackson", 52.0, "Democrat"), ("Susan Collins", 47.0, "Republican"),
    }
    # Trailing asterisks are stripped and counted; the special-election label parses.
    oh = by[("Ohio Senate 2026", "InsiderAdvantage")]
    assert oh.raw["partisan_flag"] == 1 and oh.end_date == date(2026, 11, 1)
    # "Graham Nordone" maps to the configured "Darline Graham" by surname.
    sc = by[("South Carolina Senate 2026", "NY Times/Siena")]
    assert sc.end_date == date(2026, 10, 28)
    assert {a.party: a.pct for a in sc.answers} == {"Democrat": 48.0, "Republican": 48.0}
    # Independent in the Dem column (Nebraska) still maps.
    ne = by[("Nebraska Senate 2026", "NY Times/Siena")]
    assert {a.choice: a.pct for a in ne.answers} == {"Pete Ricketts": 49.0, "Dan Osborn": 43.0}
    gb = generic[0]
    assert gb.subject == "2026"
    assert {a.choice: a.pct for a in gb.answers} == {"Dem": 52.0, "Rep": 45.0}


def test_html_wrapper_preserves_order():
    text = FIXTURE.read_text()
    body = "".join(f"<div><span>{ln}</span></div>" for ln in text.splitlines())
    html = f"<html><body>{body}</body></html>"
    polls = parse_latest_polls_html(html, RACES, today=date(2026, 11, 2))
    assert len(polls) == 12


def test_unknown_races_and_governors_are_ignored():
    text = (
        "Friday, October 30\n2026 California Governor - Hilton vs. Becerra\n"
        "LA Times\nBecerra 61, Hilton 34\nBecerra\n+27\n"
    )
    assert parse_latest_polls_text(text, RACES, today=date(2026, 11, 2)) == []
