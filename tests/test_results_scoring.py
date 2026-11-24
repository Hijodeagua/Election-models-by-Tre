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


# The real 2026 article layout: the primary's table sits under its own
# "Results" sub-heading, so the nearest heading alone says nothing.
PRIMARY_WITH_RESULTS_SUBHEADING = """
<div class="mw-heading mw-heading3"><h3>Democratic primary</h3></div>
<p>Candidates…</p>
<div class="mw-heading mw-heading4"><h4>Results</h4></div>
<table class="wikitable"><tr><th colspan=2>Party</th><th>Candidate</th><th>Votes</th><th>%</th></tr>
<tr><td></td><td>Democratic</td><td>Graham Platner</td><td>156,000</td><td>72.1</td></tr>
<tr><td></td><td>Democratic</td><td>Janet Mills</td><td>60,402</td><td>27.9</td></tr>
<tr><td colspan=3>Total votes</td><td>216,402</td><td>100.0</td></tr></table>
"""
TOP_FOUR_PRIMARY = """
<div class="mw-heading mw-heading3"><h3>Top-four primary</h3></div>
<div class="mw-heading mw-heading4"><h4>Results</h4></div>
<table class="wikitable"><tr><th colspan=2>Party</th><th>Candidate</th><th>Votes</th><th>%</th></tr>
<tr><td></td><td>Democratic</td><td>Mary Peltola</td><td>82,000</td><td>49.5</td></tr>
<tr><td></td><td>Republican</td><td>Dan S. Sullivan (incumbent)</td>
<td>68,700</td><td>41.4</td></tr>
<tr><td></td><td>Republican</td><td>Someone Else</td><td>15,304</td><td>9.1</td></tr></table>
"""
SINGLE_PARTY_UNDER_GENERAL = """
<h3>General election</h3>
<table class="wikitable"><tr><th colspan=2>Party</th><th>Candidate</th><th>Votes</th><th>%</th></tr>
<tr><td></td><td>Republican</td><td>Bill Hagerty (incumbent)</td>
<td>629,195</td><td>100.0</td></tr></table>
"""


def _infobox(after: str) -> str:
    return f"""
<table class="infobox"><tbody>
<tr><th>U.S. senator before election</th><th>Elected U.S. Senator</th></tr>
<tr><td>Jon Ossoff<br>Democratic</td><td>{after}</td></tr>
</tbody></table>
"""


def test_parser_rejects_primary_tables_under_a_results_subheading():
    assert parse_results_tables(PRIMARY_WITH_RESULTS_SUBHEADING, "Maine") is None
    assert parse_results_tables(TOP_FOUR_PRIMARY, "Alaska") is None
    assert parse_results_tables(SINGLE_PARTY_UNDER_GENERAL, "Tennessee") is None
    # The general table still wins when it is there too.
    res = parse_results_tables(PRIMARY_WITH_RESULTS_SUBHEADING + GENERAL_TABLE, "Testland")
    assert res is not None and res.winner == "Jane Dem"


def test_parser_respects_the_infobox_call():
    # Elected cell still TBD: counting may be under way, but not called.
    assert parse_results_tables(_infobox("TBD") + GENERAL_TABLE, "Testland") is None
    assert parse_results_tables(_infobox("") + GENERAL_TABLE, "Testland") is None
    # Infobox names the table's winner: called.
    res = parse_results_tables(_infobox("Jane Dem<br>Democratic") + GENERAL_TABLE, "Testland")
    assert res is not None and res.winner == "Jane Dem" and "infobox-confirmed" in res.note
    # Infobox disagrees with the table: skip rather than guess.
    wrong = _infobox("John Rep<br>Republican") + GENERAL_TABLE
    assert parse_results_tables(wrong, "Testland") is None
    # No infobox cell at all: the two-party general table is accepted.
    assert parse_results_tables(GENERAL_TABLE, "Testland") is not None


def test_fetch_nominee_gate():
    from scripts.fetch_results import winner_is_a_nominee

    entry = {"dem_candidate": "Troy Jackson", "rep_candidate": "Susan Collins"}
    assert winner_is_a_nominee("Susan Collins (incumbent)", entry)
    assert winner_is_a_nominee("Troy Jackson", entry)
    assert not winner_is_a_nominee("Graham Platner", entry)
    assert not winner_is_a_nominee(None, entry)
    sc = {"dem_candidate": "Annie Andrews", "rep_candidate": "Darline Graham"}
    assert not winner_is_a_nominee("Lindsey Graham (incumbent)", sc)
    ak = {"dem_candidate": "Mary Peltola", "rep_candidate": "Dan Sullivan"}
    assert winner_is_a_nominee("Dan S. Sullivan (incumbent)", ak)


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


# --------------------------------------------------------------------------
# Grades (scripts/grade_forecast.py)
# --------------------------------------------------------------------------
def test_letters_follow_the_rubrics():
    from scripts.grade_forecast import (
        BRIER_RUBRIC,
        MARGIN_RUBRIC,
        gpa_letter,
        letter,
        rating_to_prob,
    )

    assert letter(0.05, BRIER_RUBRIC) == "A" and letter(0.071, BRIER_RUBRIC) == "A-"
    assert letter(0.3, BRIER_RUBRIC) == "F" and letter(None, BRIER_RUBRIC) is None
    assert letter(6.8, MARGIN_RUBRIC) == "C+"
    assert gpa_letter(["A", "C"]) == "B" and gpa_letter([None]) is None
    assert rating_to_prob("Leans D (10/6, reaffirmed 10/27)") == 0.75
    assert rating_to_prob("Solid R (10/30)") == pytest.approx(0.02)
    assert rating_to_prob("Safe D (3/4, stale)") == 0.98
    assert rating_to_prob("Toss Up (10/30)") == 0.5 and rating_to_prob("Toss-up (IE page)") == 0.5
    assert rating_to_prob("Tilt R (10/29, from Lean R)") == pytest.approx(0.40)
    assert rating_to_prob(None) is None and rating_to_prob("no rating") is None


def test_forecaster_grades_cover_only_their_own_races():
    snap = _snapshot()
    snap["senate_forecast"]["races"][0]["consensus"] = {
        "cook": "Toss Up (10/30)", "sabato": "Leans R", "ddhq_p_dem": 0.8, "kalshi_p_dem": 0.9,
    }
    results = {
        "A": {"winner": "x", "winner_party": "D", "margin": 9.0},
        "B": {"winner": "y", "winner_party": "R", "margin": -5.0},
    }
    card = build_scorecard(snap, {"mode": "test"}, results)
    by = {f["key"]: f for f in card["forecasters"]}
    assert by["model"]["n"] == 2 and by["model"]["calls_right"] == 2
    # A toss-up is scored on Brier but is not a call.
    assert by["cook"]["n"] == 1 and by["cook"]["calls_made"] == 0 and by["cook"]["brier"] == 0.25
    assert by["sabato"]["misses"] == ["A"] and by["sabato"]["grade"] == "F"
    assert by["kalshi"]["brier"] == pytest.approx(0.01) and by["kalshi"]["grade"] == "A"
    # Same-race comparison: the model's Brier on race A alone.
    assert by["ddhq"]["model_brier_same_races"] == pytest.approx(0.01)
    assert by["picks"]["calls_right"] == 1 and by["picks"]["calls_made"] == 2
    assert card["report_card"]["subjects"][0]["value"] == "2/2"
    assert card["model"]["band_coverage"]["n"] == 0


def test_independent_challenger_margin_uses_the_runner_up_gap():
    snap = _snapshot()
    snap["senate_forecast"]["races"][1].update(
        {"challenger_party": "I", "margin_p10": -9.0, "margin_p90": 2.0}
    )
    results = {"B": {"winner": "y", "winner_party": "R", "margin": -35.0, "dem_pct": 12.0}}
    status = {"B": {"leader_margin": 6.0}}
    card = build_scorecard(snap, {"mode": "test"}, results, status=status)
    row = next(r for r in card["races"] if r["state"] == "B")
    assert row["result"]["margin"] == -6.0
    assert row["result"]["margin_basis"] == "challenger_minus_rep"
    assert row["model"]["margin_error"] == pytest.approx(-3.0) and row["model"]["in_80_band"]


def _poll(pollster, end, dem, rep, **kw):
    return {"pollster": pollster, "start_date": end, "end_date": end, "dem_pct": dem,
            "rep_pct": rep, "margin": dem - rep, "partisan": False, "grade": None, **kw}


def test_pollster_grades_window_dedupe_and_bias_sign():
    from scripts.grade_forecast import grade_pollsters

    states = [
        {"state": "A", "polls": [
            _poll("Siena/NYT", "2026-10-30", 50, 46),
            _poll("New York Times/Siena University", "2026-11-01", 50, 46),  # same poll again
            _poll("Acme (R)", "2026-10-20", 44, 48),
            _poll("Acme", "2026-10-25", 45, 47),
            _poll("Acme", "2026-11-01", 46, 46),
            _poll("Old Poll Co", "2026-09-01", 60, 30),  # outside the window
        ]},
        {"state": "B", "polls": [_poll("Siena/NYT", "2026-10-28", 40, 50)]},
        {"state": "Ind", "polls": [_poll("Acme", "2026-10-28", 40, 50)]},
    ]
    out = grade_pollsters(states, {"A": 6.0, "B": -8.0, "Ind": -3.0}, skip_states={"Ind"})
    by = {r["pollster"]: r for r in out["pollsters"]}
    assert "Acme" in by and len(by) == 2
    acme = by["Acme"]
    assert acme["n_polls"] == 3 and acme["partisan_tag"] == "R"
    # actual − poll: Democrats beat every Acme poll, so the bias is positive.
    assert acme["bias"] == pytest.approx((10 + 8 + 6) / 3) and acme["mae"] == acme["bias"]
    assert acme["grade"] == "C" and acme["leaders_called"] == 2 and acme["leaders_right"] == 0
    siena = next(r for r in out["pollsters"] if r is not acme)
    assert siena["n_polls"] == 2 and siena["grade"] is None  # too few polls for a letter
    assert out["field"]["n_polls"] == 5 and out["field"]["n_races"] == 2


def test_generic_ballot_grade():
    from scripts.grade_forecast import grade_generic_ballot

    avg = {"as_of": "2026-11-03", "dem_pct": 51.5, "rep_pct": 42.4, "margin": 9.1,
           "estimated_dem_seats": 240, "estimated_dem_seats_lo": 229,
           "estimated_dem_seats_hi": 251, "num_polls": 410}
    assert grade_generic_ballot(None, None)["available"] is False
    assert grade_generic_ballot(avg, None)["result"] is None
    out = grade_generic_ballot(avg, {"dem_seats": 259, "rep_seats": 173, "national_margin": 14.0})
    assert out["result"]["margin_error"] == pytest.approx(4.9)
    assert out["result"]["seats_error"] == 19 and out["result"]["seats_in_range"] is False
    assert out["result"]["winner_right"] is True
    assert out["grades"]["margin"] == "B" and out["grades"]["seats"] == "D"
