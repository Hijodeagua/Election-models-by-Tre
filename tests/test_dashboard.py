"""Tests for the dashboard stack: market data, probabilities, simulation, vibes."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.data.kalshi import _price_to_prob
from src.data.market_odds import (
    KIND_RACE,
    MarketOdds,
    detect_state,
    load_odds_csv,
    odds_to_csv,
)
from src.data.polymarket import _market_party_probs
from src.data.silverb_csv import load_approval_series
from src.models.senate_probability import (
    RaceProbability,
    load_senate_config,
    margin_to_win_prob,
    market_consensus,
    oriented_dem_margin,
    race_probability,
)
from src.models.senate_simulation import (
    date_seed,
    simulate_senate_control,
)
from src.models.vibes_adjustment import (
    MAX_CANDIDATE_SHIFT,
    MAX_RACE_SHIFT,
    candidate_adjustment,
    load_vibes_snapshot,
    race_adjustment_for_state,
)


def _quote(**kwargs) -> MarketOdds:
    defaults = dict(
        source="polymarket",
        market_id="m1",
        title="Georgia Senate Election Winner 2026",
        kind=KIND_RACE,
        state="Georgia",
        dem_win_prob=0.6,
        rep_win_prob=0.4,
        volume=1000.0,
        as_of=date(2026, 6, 1),
        url="",
    )
    defaults.update(kwargs)
    return MarketOdds(**defaults)


# ── market_odds ──────────────────────────────────────────────────────────────

class TestMarketOdds:
    def test_csv_round_trip(self, tmp_path: Path):
        quotes = [_quote(), _quote(source="kalshi", market_id="KX-1", volume=None)]
        path = tmp_path / "market_odds.csv"
        path.write_text(odds_to_csv(quotes), encoding="utf-8")
        loaded = load_odds_csv(path)
        assert len(loaded) == 2
        assert {q.source for q in loaded} == {"polymarket", "kalshi"}
        ga = next(q for q in loaded if q.source == "polymarket")
        assert ga.dem_win_prob == 0.6
        assert ga.as_of == date(2026, 6, 1)

    def test_missing_file_is_empty(self, tmp_path: Path):
        assert load_odds_csv(tmp_path / "nope.csv") == []

    def test_header_only_file_is_empty(self, tmp_path: Path):
        path = tmp_path / "market_odds.csv"
        path.write_text(odds_to_csv([]), encoding="utf-8")
        assert load_odds_csv(path) == []

    def test_detect_state_longest_match(self):
        assert detect_state("West Virginia Senate winner") == "West Virginia"
        assert detect_state("Virginia Senate winner") == "Virginia"
        assert detect_state("Which party controls the Senate?") == ""


# ── polymarket / kalshi parsing ──────────────────────────────────────────────

class TestMarketParsing:
    def test_polymarket_party_outcomes(self):
        market = {
            "outcomes": '["Democratic", "Republican"]',
            "outcomePrices": '["0.62", "0.38"]',
            "question": "Georgia Senate winner?",
        }
        dem, rep = _market_party_probs(market)
        assert dem == 0.62 and rep == 0.38

    def test_polymarket_yes_no_party_question(self):
        market = {
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.55", "0.45"]',
            "question": "Will Democrats win the Georgia Senate race?",
        }
        dem, rep = _market_party_probs(market)
        assert dem == 0.55 and rep is None

    def test_polymarket_mismatched_lengths(self):
        assert _market_party_probs({"outcomes": '["Yes"]', "outcomePrices": "[]"}) == (None, None)

    def test_kalshi_price_midpoint_and_last(self):
        assert _price_to_prob({"yes_bid": 40, "yes_ask": 44}) == 0.42
        assert _price_to_prob({"last_price": 73}) == 0.73
        assert _price_to_prob({}) is None


# ── senate_probability ───────────────────────────────────────────────────────

class TestSenateProbability:
    def test_margin_to_win_prob_center_and_monotone(self):
        assert margin_to_win_prob(0.0) == 0.5
        assert margin_to_win_prob(5.0) > 0.75
        assert margin_to_win_prob(-5.0) < 0.25
        assert margin_to_win_prob(3.0) > margin_to_win_prob(1.0)

    def test_oriented_dem_margin_party_labels(self):
        m = oriented_dem_margin({"Democrat": 48.0, "Republican": 44.0})
        assert m == 4.0

    def test_oriented_dem_margin_candidate_names(self):
        cfg = {"dem_candidate": "Ossoff", "rep_candidate": "Greene"}
        m = oriented_dem_margin({"Jon Ossoff": 49.0, "Marjorie Greene": 45.5}, cfg)
        assert m == 3.5

    def test_oriented_dem_margin_unknown(self):
        assert oriented_dem_margin({"Smith": 50.0, "Jones": 45.0}) is None
        assert oriented_dem_margin({}) is None

    def test_market_consensus_volume_weighted(self):
        odds = [
            _quote(dem_win_prob=0.6, volume=3000.0),
            _quote(source="kalshi", dem_win_prob=0.4, volume=1000.0),
        ]
        assert market_consensus(odds, "Georgia") == 0.55
        assert market_consensus(odds, "Texas") is None

    def test_market_consensus_uses_rep_complement(self):
        odds = [_quote(dem_win_prob=None, rep_win_prob=0.7)]
        assert market_consensus(odds, "Georgia") == pytest.approx(0.3)

    def test_race_probability_blend(self):
        cfg = {"rating": "tossup"}
        odds = [_quote(dem_win_prob=0.7)]
        rp = race_probability(
            "Georgia", {"Democrat": 50.0, "Republican": 50.0}, 5, cfg, odds,
            market_weight=0.25,
        )
        assert rp.poll_prob == 0.5
        assert rp.market_prob == 0.7
        # 0.75 * 0.5 + 0.25 * 0.7 = 0.55
        assert rp.blended_prob == pytest.approx(0.55)
        assert "markets" in rp.sources and "polls" in rp.sources

    def test_race_probability_falls_back_to_rating(self):
        rp = race_probability("Wyoming", {}, 0, {"rating": "solid_r"}, [])
        assert rp.poll_prob is None
        assert rp.model_prob == pytest.approx(0.03)
        assert rp.blended_prob == pytest.approx(0.03)
        assert rp.sources == ["rating_prior"]

    def test_vibes_margin_adjustment_shifts_probability(self):
        cfg = {"rating": "tossup"}
        base = race_probability("Georgia", {"Democrat": 50.0, "Republican": 50.0}, 5, cfg, [])
        shifted = race_probability(
            "Georgia", {"Democrat": 50.0, "Republican": 50.0}, 5, cfg, [],
            margin_adjustment=2.0,
        )
        assert shifted.blended_prob > base.blended_prob

    def test_config_landscape_is_consistent(self):
        cfg = load_senate_config()
        races = cfg["races"]
        assert len(races) == 35
        d_up = sum(1 for r in races if r["incumbent_party"] == "D")
        r_up = sum(1 for r in races if r["incumbent_party"] == "R")
        assert (d_up, r_up) == (13, 22)
        baseline = cfg["baseline_not_up"]
        # 100 seats total: not-up + up-this-cycle
        assert baseline["dem"] + baseline["rep"] + len(races) == 100
        # Current chamber: 47 D (incl. caucusing independents), 53 R
        assert baseline["dem"] + d_up == 47
        assert baseline["rep"] + r_up == 53


# ── senate_simulation ────────────────────────────────────────────────────────

def _race(state: str, prob: float) -> RaceProbability:
    return RaceProbability(
        state=state, rating=None, dem_margin=None, poll_prob=None,
        prior_prob=prob, model_prob=prob, market_prob=None,
        blended_prob=prob, market_weight=0.25,
    )


class TestSenateSimulation:
    def test_deterministic_with_seed(self):
        races = [_race(f"S{i}", 0.5) for i in range(10)]
        a = simulate_senate_control(races, 40, 50, n_sims=200, seed=42)
        b = simulate_senate_control(races, 40, 50, n_sims=200, seed=42)
        assert a.seat_histogram == b.seat_histogram
        assert a.dem_control_prob == b.dem_control_prob

    def test_histogram_sums_to_n_sims(self):
        races = [_race(f"S{i}", 0.5) for i in range(5)]
        res = simulate_senate_control(races, 45, 50, n_sims=300, seed=1)
        assert sum(res.seat_histogram.values()) == 300
        assert res.n_sims == 300

    def test_sure_things_decide_control(self):
        races = [_race(f"D{i}", 0.999) for i in range(5)]
        res = simulate_senate_control(races, 47, 48, dem_seats_needed=51, n_sims=500, seed=7)
        # 47 + 5 near-certain wins = 52 ≥ 51 almost always
        assert res.dem_control_prob > 0.95
        assert res.rep_control_prob == pytest.approx(1 - res.dem_control_prob)

    def test_win_freq_tracks_probability_direction(self):
        races = [_race("Safe D", 0.97), _race("Safe R", 0.03), _race("Tossup", 0.5)]
        res = simulate_senate_control(races, 48, 49, n_sims=1000, seed=3)
        assert res.race_win_freq["Safe D"] > 0.8
        assert res.race_win_freq["Safe R"] < 0.2
        assert 0.3 < res.race_win_freq["Tossup"] < 0.7

    def test_default_is_1000_sims(self):
        from src.models.senate_simulation import DEFAULT_N_SIMS
        assert DEFAULT_N_SIMS == 1000

    def test_date_seed(self):
        assert date_seed(date(2026, 6, 9)) == 20260609


# ── vibes_adjustment ─────────────────────────────────────────────────────────

_VIBES_CSV = (
    "state,candidate,party,positive_pct,negative_pct,neutral_pct,"
    "total_mentions,bucket_numeric,scandal_severity,as_of\n"
    "Georgia,Jon Ossoff,D,60.0,20.0,20.0,120,1,0.0,2026-06-01\n"
    "Georgia,Some Rep,R,15.0,75.0,10.0,80,-2,0.9,2026-06-01\n"
)


class TestVibesAdjustment:
    def test_candidate_adjustment_capped(self):
        assert candidate_adjustment(2, 0.0) == 1.0
        assert candidate_adjustment(-2, 1.0) == -MAX_CANDIDATE_SHIFT
        assert candidate_adjustment(0, 0.0) == 0.0

    def test_race_adjustment_from_snapshot(self, tmp_path: Path):
        path = tmp_path / "vibes_snapshot.csv"
        path.write_text(_VIBES_CSV, encoding="utf-8")
        snapshot = load_vibes_snapshot(path)
        adj, detail = race_adjustment_for_state(snapshot, "Georgia")
        # dem: +0.5; rep: capped at -1.5 → net +2.0, within ±2.5 cap
        assert adj == 2.0
        assert abs(adj) <= MAX_RACE_SHIFT
        assert detail is not None
        assert detail["dem"]["candidate"] == "Jon Ossoff"

    def test_unknown_state_is_zero(self, tmp_path: Path):
        path = tmp_path / "vibes_snapshot.csv"
        path.write_text(_VIBES_CSV, encoding="utf-8")
        snapshot = load_vibes_snapshot(path)
        adj, detail = race_adjustment_for_state(snapshot, "Texas")
        assert adj == 0.0 and detail is None

    def test_missing_file_is_empty(self, tmp_path: Path):
        assert load_vibes_snapshot(tmp_path / "nope.csv") == {}


# ── approval series loader ───────────────────────────────────────────────────

class TestApprovalSeries:
    def test_load_full_series(self, tmp_path: Path):
        csv_text = (
            "modeldate,approve,disapprove,approve_lo,approve_hi,disapprove_lo,disapprove_hi\n"
            "1/21/25,51.6,44.2,49.0,54.0,42.0,46.0\n"
            "1/22/25,51.2,44.8,,,,\n"
        )
        path = tmp_path / "silverb_approval.csv"
        path.write_text(csv_text, encoding="utf-8")
        series = load_approval_series(path)
        assert len(series) == 2
        assert series[0].as_of == date(2025, 1, 21)
        assert series[0].ci_approve == (49.0, 54.0)
        assert series[1].ci_approve is None
        assert series[1].net_approval == pytest.approx(6.4)

    def test_missing_file(self, tmp_path: Path):
        assert load_approval_series(tmp_path / "nope.csv") == []
