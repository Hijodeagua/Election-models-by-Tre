"""Snapshot-style checks on the exported forecast: the table the site
renders must carry the right nominees, treatments and badges."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FORECAST = ROOT / "web" / "public" / "data" / "senate_forecast.json"

GONE = {"Scott Brown", "Haley Stevens", "Lindsey Graham", "Bill Cassidy", "Tina Smith"}
CONSENSUS_SAFE = {"DE", "NJ", "OR", "WV", "WY", "CO", "OK", "KY", "VA", "TN"}
PARTISAN_ONLY = {"ID", "LA", "MS"}
ABBR = {
    "Delaware": "DE", "New Jersey": "NJ", "Oregon": "OR", "West Virginia": "WV", "Wyoming": "WY",
    "Colorado": "CO", "Oklahoma": "OK", "Kentucky": "KY", "Virginia": "VA", "Tennessee": "TN",
    "Idaho": "ID", "Louisiana": "LA", "Mississippi": "MS", "Montana": "MT", "Nebraska": "NE",
    "South Dakota": "SD", "New Hampshire": "NH", "Michigan": "MI", "South Carolina": "SC",
    "Minnesota": "MN", "Kansas": "KS", "Massachusetts": "MA", "Rhode Island": "RI",
}


@pytest.fixture(scope="module")
def races():
    data = json.loads(FORECAST.read_text())
    return {r["state"]: r for r in data["races"]}, data


def test_thirty_five_races_with_current_nominees(races):
    by, _ = races
    assert len(by) == 35
    names = {r["dem_candidate"] for r in by.values()} | {r["rep_candidate"] for r in by.values()}
    assert not (names & GONE)
    assert by["New Hampshire"]["rep_candidate"] == "John E. Sununu"
    assert by["Michigan"]["dem_candidate"] == "Abdul El-Sayed"
    assert (by["South Carolina"]["dem_candidate"], by["South Carolina"]["rep_candidate"]) == (
        "Annie Andrews", "Darline Graham",
    )
    assert (by["Louisiana"]["dem_candidate"], by["Louisiana"]["rep_candidate"]) == (
        "Jamie Davis", "Julia Letlow",
    )
    assert by["Minnesota"]["dem_candidate"] == "Peggy Flanagan"
    assert by["Kansas"]["dem_candidate"] == "Adam Hamilton"
    assert by["Nebraska"]["challenger_party"] == "I"
    assert by["Nebraska"]["dem_candidate"] == "Dan Osborn"
    assert by["Montana"]["third_candidate"] == "Alani Bankhead (D)"
    assert "Massachusetts" in by and "Rhode Island" in by


def test_consensus_safe_races_use_the_consensus_probability(races):
    by, _ = races
    for state, r in by.items():
        ab = ABBR.get(state)
        if ab in CONSENSUS_SAFE:
            assert r["treatment"] == "CONSENSUS_SAFE"
            assert r["margin"] is None and r["badge"].startswith("No public polls in window")
            p = r["dem_win_prob_sim"]
            assert p >= 0.97 or p <= 0.03, (state, p)
            assert r["consensus"]["pick"]
        elif ab in PARTISAN_ONLY:
            assert r["treatment"] == "POLLED_PARTISAN_ONLY"
            assert r["badge"].startswith("In-window polls are partisan-sponsored only")


def test_independents_are_tallied_separately(races):
    by, data = races
    assert set(data["ind_races"]) == {"Idaho", "Montana", "Nebraska", "South Dakota"}
    assert data["mean_ind_seats"] >= 0
    assert by["Montana"]["badge"] == "three-way race; polls exclude Bodnar"
    assert by["Montana"]["open_seat"] is True


def test_open_seats_and_specials_are_marked(races):
    by, _ = races
    assert by["Louisiana"]["open_seat"] and by["Texas"]["open_seat"]
    assert by["Florida"]["format_note"] == "special election"
    assert by["Ohio"]["format_note"] == "special election"
