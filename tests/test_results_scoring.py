"""Tests for the results scraper and the scorecard (no network)."""

from __future__ import annotations

import pytest

from scripts.score_forecast import (
    build_scorecard,
    calibration_bins,
    pick_dem_margin,
    score_margins,
    score_probabilities,
)
from src.data.wikipedia_results import parse_results_tables

PRIMARY_TABLE = """
<h3>Republican primary</h3>
<table class="wikitable"><tr><th colspan=2>Party</th><th>Candidate</th><th>Votes</th><th>%</th></tr>
<tr><td></td><td>Republican</td><td>A. Primary</td><td>300,000</td><td>60.0</td></tr>
<tr><td></td><td>Republican</td><td>B. Primary</td><td>200,000</td><td>40.0</td></tr></table>
"""
GENERAL_TABLE = """
<div class="mw-heading mw-heading3"><h3>General election</h3></div>
<table class="wikitable">
<tr><th colspan=2>Party</th><th>Candidate</th><th>Votes</th><th>%</th><th>±%</th></tr>
<tr><td></td><td>Democratic</td><td>Jane Dem</td><td>1,250,000</td><td>51.2</td><td>+2</td></tr>
<tr><td></td><td>Republican</td><td>John Rep</td><td>1,150,000</td><td>47.1</td><td>−2</td></tr>
<tr><td></td><td>Libertarian</td><td>Lib Person</td><td>41,500</td><td>1.7</td><td></td></tr>
<tr><td colspan=3>Total votes</td><td>2,441,500</td><td>100.0</td><td></td></tr></table>
"""
EMPTY_TABLE = """
<h3>General election</h3>
<table class="wikitable"><tr><th colspan=2>Party</th><th>Candidate</th><th>Votes</th><th>%</th></tr>
<tr><td></td><td>Democratic</td><td>Jane Dem</td><td>0</td><td></td></tr>
<tr><td></td><td>Republican</td><td>John Rep</td><td>0</td><td></td></tr></table>
"""


def test_parser_prefers_general_election_over_primary():
    res = parse_results_tables(PRIMARY_TABLE + GENERAL_TABLE, "Testland")
    assert res is not None
    assert res.winner == "Jane Dem" and res.winner_party == "D"
    assert res.dem_pct == 51.2 and res.rep_pct == 47.1
    assert res.margin == pytest.approx(4.1)
    assert res.total_votes == 2_441_500
    assert res.dem_candidate == "Jane Dem" and res.rep_candidate == "John Rep"


def test_parser_ignores_empty_pre_election_boxes():
    assert parse_results_tables(EMPTY_TABLE, "Testland") is None
    assert parse_results_tables(PRIMARY_TABLE, "Testland") is None
    assert parse_results_tables("", "Testland") is None


def test_probability_scores():
    s = score_probabilities([(0.9, True), (0.2, False), (0.7, False)])
    assert s["n"] == 3
    assert s["accuracy"] == pytest.approx(2 / 3, abs=1e-3)
    assert s["brier"] == pytest.approx((0.01 + 0.04 + 0.49) / 3, abs=1e-4)
    assert score_probabilities([])["brier"] is None


def test_margin_scores_and_sign_convention():
    m = score_margins([(3.0, 5.0), (-2.0, -6.0)])
    assert m["mae"] == 3.0 and m["bias"] == -1.0
    assert pick_dem_margin("D", 4.0) == 4.0
    assert pick_dem_margin("R", 4.0) == -4.0
    assert pick_dem_margin("I", 4.0) is None and pick_dem_margin(None, None) is None


def test_calibration_bins_group_by_probability():
    bins = calibration_bins([(0.1, False), (0.15, True), (0.95, True)])
    assert [b["bin"] for b in bins] == ["0-20%", "80-100%"]
    assert bins[0]["n"] == 2 and bins[0]["actual"] == 0.5


def _snapshot():
    return {
        "senate_forecast": {
            "dem_control_prob": 0.6,
            "mean_dem_seats": 51.0,
            "races": [
                {"state": "A", "dem_win_prob_sim": 0.9, "median_margin": 8.0, "num_polls": 5,
                 "market_dem_prob": {"polymarket": 0.95}},
                {"state": "B", "dem_win_prob_sim": 0.3, "median_margin": -3.0, "num_polls": 0,
                 "market_dem_prob": {}},
                {"state": "C", "dem_win_prob_sim": 0.5, "median_margin": 0.0, "num_polls": 2,
                 "market_dem_prob": {}},
            ],
        },
        "senate": {"races": [{"state": "A", "dem_margin": 7.0}]},
        "predictions": {"races": [
            {"state": "A", "pick": "D", "margin": 6.0},
            {"state": "B", "pick": "D", "margin": 1.0},
            {"state": "C", "pick": None, "margin": None},
        ]},
    }


def test_scorecard_scores_only_called_races():
    results = {
        "A": {"winner": "x", "winner_party": "D", "margin": 9.0, "source": "manual"},
        "B": {"winner": "y", "winner_party": "R", "margin": -5.0, "source": "manual"},
    }
    card = build_scorecard(_snapshot(), {"mode": "test"}, results)
    assert card["status"] == "partial" and card["num_called"] == 2 and card["num_races"] == 3
    assert card["model"]["n"] == 2 and card["model"]["accuracy"] == 1.0
    assert card["model"]["margins"]["mae"] == pytest.approx(1.5)
    # Picks: A right (D), B wrong (picked D, R won); C never called.
    assert card["picks"]["n"] == 2 and card["picks"]["accuracy"] == 0.5
    assert card["picks"]["margins"]["mae"] == pytest.approx((3.0 + 6.0) / 2)
    assert card["market"]["n"] == 1 and card["market"]["accuracy"] == 1.0
    rows = {r["state"]: r for r in card["races"]}
    assert rows["A"]["pick"]["correct"] is True and rows["B"]["pick"]["correct"] is False
    assert rows["C"]["called"] is False and rows["C"]["result"] is None
    assert card["chamber"]["final"] is False and card["chamber"]["dem_seats_so_far"] == 34 + 1


def test_scorecard_awaiting_results_is_clean():
    card = build_scorecard(_snapshot(), {"mode": "test"}, {})
    assert card["status"] == "awaiting_results"
    assert card["model"]["brier"] is None and card["picks"]["n"] == 0
    assert card["picks_made"] == 2
