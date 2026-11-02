"""Phase 0 guarantees: nominees match the source of truth, independents are
tallied separately, and stale-matchup polls are excluded but not deleted."""

from __future__ import annotations

from datetime import date

from scripts.export_json import audit_stale_matchups
from src.data.base import Poll, PollAnswer, PollType
from src.models.senate_simulation import RaceInput, SenateControlSimulator, load_cycle_config

GONE = {"Scott Brown", "Haley Stevens", "Lindsey Graham", "Bill Cassidy", "Tina Smith"}


def test_no_superseded_nominee_remains_in_config():
    cfg = load_cycle_config()
    names = {e["dem_candidate"] for e in cfg["competitive_races"]} | {
        e["rep_candidate"] for e in cfg["competitive_races"]
    }
    assert not (names & GONE)
    by = {e["abbr"]: e for e in cfg["competitive_races"]}
    assert by["NH"]["rep_candidate"] == "John E. Sununu"
    assert by["MI"]["dem_candidate"] == "Abdul El-Sayed"
    assert by["SC"]["dem_candidate"] == "Annie Andrews"
    assert by["SC"]["rep_candidate"] == "Darline Graham"
    assert (by["LA"]["dem_candidate"], by["LA"]["rep_candidate"]) == ("Jamie Davis", "Julia Letlow")
    assert by["MT"]["dem_candidate"] == "Seth Bodnar" and by["MT"]["challenger_party"] == "I"
    assert by["MT"]["third_candidate"] == "Alani Bankhead (D)"
    for ab in ("NE", "SD", "ID"):
        assert by[ab]["challenger_party"] == "I"


def _poll(subject, names, end=date(2026, 10, 20)):
    return Poll(
        poll_id=f"{subject}-{end}-{names[0]}", source="t", poll_type=PollType.HEAD_TO_HEAD,
        pollster="Tester", subject=subject, start_date=end, end_date=end,
        sample_size=500, population=None,
        answers=[PollAnswer(choice=n, pct=48.0) for n in names],
    )


def test_stale_matchup_polls_are_flagged_not_dropped_silently():
    cfg = load_cycle_config()
    polls = [
        _poll("Michigan Senate 2026", ["Haley Stevens", "Mike Rogers"]),
        _poll("Michigan Senate 2026", ["Abdul El-Sayed", "Mike Rogers"]),
        _poll("New Hampshire Senate 2026", ["Chris Pappas", "Scott Brown"]),
        _poll("South Carolina Senate 2026", ["Darline Graham Nordone", "Annie Andrews"]),
        _poll("Nebraska Senate 2026", ["Pete Ricketts", "Dan Osborn"]),
    ]
    valid, stale = audit_stale_matchups(polls, cfg)
    assert [p.answers[0].choice for p in valid] == [
        "Abdul El-Sayed", "Darline Graham Nordone", "Pete Ricketts",
    ]
    assert {(s["state"], s["polled"]) for s in stale} == {
        ("Michigan", "Haley Stevens v Mike Rogers"),
        ("New Hampshire", "Chris Pappas v Scott Brown"),
    }
    assert all(s["flag"] == "stale_matchup" for s in stale)


def test_independent_wins_do_not_count_toward_democratic_control():
    sim = SenateControlSimulator(dem_safe_seats=50, rep_safe_seats=48, dem_majority_threshold=51,
                                 national_sigma=0.01, race_sigma=0.01)
    dem_race = RaceInput(
        state="A", race="A Senate", dem_candidate="D", rep_candidate="R", margin=10.0,
    )
    ind_race = RaceInput(
        state="B", race="B Senate", dem_candidate="I", rep_candidate="R", margin=10.0,
        challenger_party="I",
    )
    with_dem = sim.simulate([dem_race], num_simulations=200, seed=1)
    with_ind = sim.simulate([ind_race], num_simulations=200, seed=1)
    assert with_dem.dem_control_prob == 1.0 and with_dem.mean_dem_seats == 51.0
    assert with_ind.dem_control_prob == 0.0 and with_ind.mean_dem_seats == 50.0
    assert with_ind.mean_ind_seats == 1.0 and with_ind.ind_races == ["B"]
    # The race-level win share still describes the challenger.
    assert with_ind.races[0].dem_win_prob_sim == 1.0
