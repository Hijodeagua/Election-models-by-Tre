"""Election-night conditioning and the live-forecast script."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import live_forecast as lf
from src.models.senate_simulation import RaceInput, SenateControlSimulator

SIM_KW = dict(
    dem_safe_seats=34,
    rep_safe_seats=31,
    # 34 safe seats + the six D-side races below can never reach 51, so the
    # fixture puts control at 38 (four of the six) to keep the odds in play.
    dem_majority_threshold=38,
    national_sigma=2.9,
    race_sigma=5.1,
    market_weight=0.25,
    tail_dof=5,
)


def _race(state: str, p: float, party: str = "D") -> RaceInput:
    return RaceInput(
        state=state,
        race=f"{state} Senate 2026",
        dem_candidate="Dee",
        rep_candidate="Rhea",
        margin=None,
        market_dem_prob={"frozen": p},
        challenger_party=party,
    )


RACES = [
    _race("Georgia", 0.94),
    _race("Maine", 0.77),
    _race("Ohio", 0.64),
    _race("Texas", 0.66),
    _race("Iowa", 0.43),
    _race("Florida", 0.13),
    _race("Nebraska", 0.24, "I"),
]


class TestConditioning:
    def test_unconditioned_reproduces_frozen_probabilities(self):
        sim = SenateControlSimulator(**SIM_KW)
        fc = sim.simulate(RACES, num_simulations=40_000, seed=1)
        for r, inp in zip(fc.races, RACES, strict=True):
            assert abs(r.dem_win_prob_sim - inp.market_dem_prob["frozen"]) < 0.02, r.state
        assert fc.condition_mode is None and fc.kept_simulations is None

    def test_a_call_fixes_that_race_and_moves_the_rest(self):
        sim = SenateControlSimulator(**SIM_KW)
        base = sim.simulate(RACES, num_simulations=60_000, seed=1)
        # Iowa called for the Democrat (a 43% shot): other races should drift D
        # through the shared national error, and control odds should rise.
        cond = sim.simulate(RACES, num_simulations=60_000, seed=1, conditions={"Iowa": True})
        by = {r.state: r for r in cond.races}
        assert by["Iowa"].dem_win_prob_sim == 1.0
        assert cond.condition_mode == "resample"
        assert 0 < cond.kept_simulations < 60_000
        assert cond.conditioned_races == ["Iowa"]
        assert cond.dem_control_prob > base.dem_control_prob
        texas_base = next(r for r in base.races if r.state == "Texas").dem_win_prob_sim
        assert by["Texas"].dem_win_prob_sim > texas_base
        # A called R race pulls the other way.
        cond_r = sim.simulate(RACES, num_simulations=60_000, seed=1, conditions={"Ohio": False})
        assert {r.state: r for r in cond_r.races}["Ohio"].dem_win_prob_sim == 0.0
        assert cond_r.dem_control_prob < base.dem_control_prob

    def test_independent_call_counts_as_an_independent_seat(self):
        sim = SenateControlSimulator(**SIM_KW)
        cond = sim.simulate(RACES, num_simulations=40_000, seed=2, conditions={"Nebraska": True})
        assert cond.mean_ind_seats == 1.0
        by = {r.state: r for r in cond.races}
        assert by["Nebraska"].dem_win_prob_sim == 1.0

    def test_forced_mode_when_too_few_draws_agree(self):
        sim = SenateControlSimulator(**SIM_KW)
        # Demand more consistent draws than exist: falls back to forcing.
        cond = sim.simulate(
            RACES,
            num_simulations=5_000,
            seed=3,
            conditions={"Florida": True},
            min_consistent=10_000,
        )
        assert cond.condition_mode == "forced"
        assert cond.kept_simulations < 10_000
        by = {r.state: r for r in cond.races}
        assert by["Florida"].dem_win_prob_sim == 1.0
        assert sum(cond.seat_distribution.values()) == 5_000

    def test_unknown_states_are_ignored(self):
        sim = SenateControlSimulator(**SIM_KW)
        fc = sim.simulate(RACES, num_simulations=2_000, seed=4, conditions={"Narnia": True})
        assert fc.condition_mode is None


# ── live_forecast.py ─────────────────────────────────────────────────────

def _snapshot() -> dict:
    base = SenateControlSimulator(**SIM_KW).simulate(RACES, num_simulations=40_000, seed=7)
    return {
        "as_of": "2026-11-03",
        "dem_control_prob": base.dem_control_prob,
        "mean_dem_seats": base.mean_dem_seats,
        "mean_ind_seats": base.mean_ind_seats,
        "dem_safe_seats": 34,
        "rep_safe_seats": 31,
        "dem_majority_threshold": 38,
        "national_sigma": 2.9,
        "race_sigma": 5.1,
        "market_weight": 0.25,
        "bias": -1.2,
        "tail_dof": 5,
        "races": [
            {
                "state": r.state, "race": r.race, "dem_candidate": r.dem_candidate,
                "rep_candidate": r.rep_candidate, "num_polls": 3,
                "dem_win_prob_blended": r.market_dem_prob["frozen"],
                "dem_win_prob_sim": r.market_dem_prob["frozen"],
                "challenger_party": r.challenger_party, "held_by": "R",
            }
            for r in RACES
        ],
    }


@pytest.fixture
def paths(tmp_path: Path) -> dict[str, Path]:
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "senate_forecast.json").write_text(json.dumps(_snapshot()))
    meta = {
        "ref": "abc1234",
        "committed_at": "2026-11-03T17:38:52Z",
        "frozen_at": "2026-11-03T23:00:00Z",
        "mode": "git",
    }
    (snap / "meta.json").write_text(json.dumps(meta))
    return {
        "snap": snap,
        "results": tmp_path / "senate_2026.json",
        "manual": tmp_path / "senate_2026_manual.json",
        "log": tmp_path / "call_log.json",
        "out": tmp_path / "live_forecast.json",
    }


def _run(paths: dict[str, Path], now: str) -> dict:
    rc = lf.main([
        "--snapshot-dir", str(paths["snap"]),
        "--results", str(paths["results"]),
        "--manual", str(paths["manual"]),
        "--call-log", str(paths["log"]),
        "--out", str(paths["out"]),
        "--num-simulations", "20000",
        "--now", now,
    ])
    assert rc == 0
    return json.loads(paths["out"].read_text())


def test_no_calls_matches_the_pre_election_forecast(paths):
    out = _run(paths, "2026-11-04T00:00:00+00:00")
    assert out["num_called"] == 0 and out["new_calls"] == []
    assert out["seats_so_far"] == {"D": 34, "R": 31, "I": 0}
    assert out["live"]["condition_mode"] is None
    assert abs(out["live"]["dem_control_prob"] - out["pre_election"]["dem_control_prob"]) < 0.05
    assert len(out["remaining"]) == 7 and out["called"] == []
    assert len(out["history"]) == 1
    assert out["snapshot"]["ref"] == "abc1234"


def test_calls_condition_the_forecast_and_are_logged(paths):
    _run(paths, "2026-11-04T00:00:00+00:00")
    paths["results"].write_text(json.dumps({"results": {
        "Georgia": {"winner": "Dee", "winner_party": "D", "margin": 8.0},
        "Iowa": {"winner": "Dee", "winner_party": "D", "margin": 0.5},
        "Nebraska": {"winner": "Dee", "winner_party": "I", "margin": 1.0},
    }}))
    out = _run(paths, "2026-11-04T01:00:00+00:00")
    assert out["num_called"] == 3
    assert sorted(out["new_calls"]) == ["Georgia", "Iowa", "Nebraska"]
    assert out["seats_so_far"] == {"D": 36, "R": 31, "I": 1}
    assert out["live"]["condition_mode"] == "resample"
    assert out["live"]["dem_control_prob"] > out["pre_election"]["dem_control_prob"]
    by = {c["state"]: c for c in out["called"]}
    assert by["Iowa"]["upset"] is True and by["Iowa"]["pre_election_prob"] == 0.43
    assert by["Georgia"]["upset"] is False and by["Georgia"]["pre_election_prob"] == 0.94
    assert by["Nebraska"]["pre_election_prob"] == 0.24
    assert {r["state"] for r in out["remaining"]} == {"Maine", "Ohio", "Texas", "Florida"}
    texas = next(r for r in out["remaining"] if r["state"] == "Texas")
    assert texas["live_prob"] > texas["pre_election_prob"]
    assert len(out["history"]) == 2
    log = json.loads(paths["log"].read_text())["calls"]
    assert {c["state"] for c in log} == {"Georgia", "Iowa", "Nebraska"}
    assert all(c["first_seen"].startswith("2026-11-04T01:00") for c in log)

    # An hour later with no new calls: nothing is "new", first_seen is kept,
    # and the history does not grow when nothing changed.
    out2 = _run(paths, "2026-11-04T02:30:00+00:00")
    assert out2["new_calls"] == []
    assert len(out2["history"]) == 2
    first = json.loads(paths["log"].read_text())["calls"][0]["first_seen"]
    assert first.startswith("2026-11-04T01:00")


def test_manual_results_override_scraped_ones(paths):
    paths["results"].write_text(json.dumps({"results": {
        "Ohio": {"winner": "Rhea", "winner_party": "R", "margin": -1.0},
    }}))
    paths["manual"].write_text(json.dumps({"results": {
        "Ohio": {"winner": "Dee", "winner_party": "D", "margin": 0.4, "note": "corrected"},
    }}))
    out = _run(paths, "2026-11-04T03:00:00+00:00")
    ohio = out["called"][0]
    assert ohio["state"] == "Ohio" and ohio["winner_party"] == "D" and ohio["source"] == "manual"
    assert out["seats_so_far"]["D"] == 35


def test_winner_pre_prob_sides():
    race = {"dem_win_prob_sim": 0.3, "challenger_party": "D"}
    assert lf._winner_pre_prob(race, "D") == 0.3
    assert lf._winner_pre_prob(race, "R") == 0.7
    assert lf._winner_pre_prob(race, "I") is None
    assert lf._winner_pre_prob({"dem_win_prob_sim": 0.2, "challenger_party": "I"}, "I") == 0.2


def test_now_defaults_to_utc():
    assert datetime.now(UTC).tzinfo is UTC


def test_retracted_calls_are_dropped_from_the_log_and_history(paths):
    paths["results"].write_text(json.dumps({"results": {
        "Georgia": {"winner": "Dee", "winner_party": "D", "margin": 8.0},
        "Maine": {"winner": "Wrong Person", "winner_party": "D", "margin": 9.0},
    }}))
    out = _run(paths, "2026-11-04T01:00:00+00:00")
    assert out["num_called"] == 2 and len(out["history"]) == 1
    # The source withdraws Maine (e.g. a mis-parse fixed upstream).
    paths["results"].write_text(json.dumps({"results": {
        "Georgia": {"winner": "Dee", "winner_party": "D", "margin": 8.0},
    }}))
    out2 = _run(paths, "2026-11-04T02:00:00+00:00")
    assert out2["retracted"] == ["Maine"]
    assert out2["num_called"] == 1
    assert {c["state"] for c in out2["called"]} == {"Georgia"}
    log = json.loads(paths["log"].read_text())["calls"]
    assert [c["state"] for c in log] == ["Georgia"]
    # The point computed with the bogus call is gone; the new one is kept.
    assert [h["num_called"] for h in out2["history"]] == [1]
