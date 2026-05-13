"""Candidate quality / WAR (Wins Above Replacement) model.

Approach (inspired by Split Ticket / G. Elliott Morris):
    1. Estimate expected vote share for a generic D/R candidate from fundamentals:
       - District/state partisan lean (Cook PVI or equivalent)
       - National environment (generic ballot margin)
       - Incumbency advantage
       - Presidential approval × same-party interaction
    2. Candidate quality = actual vote share − expected vote share
    3. Media vibes can then be regressed against the residual to isolate
       candidate-specific signal from structural factors.

This module provides both the fundamentals-based baseline and the
WAR computation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np


# ── Data structures ───────────────────────────────────────────────────


@dataclass
class RaceFundamentals:
    """Structural inputs for a single race."""

    race: str  # e.g., "PA-Senate-2022"
    state: str
    year: int
    office: str  # "senate", "house", "governor"
    partisan_lean: float  # PVI or equivalent (+ = D lean, - = R lean)
    generic_ballot_margin: float  # national D-R margin at time of election
    dem_incumbent: bool
    rep_incumbent: bool
    open_seat: bool
    presidential_approval: float  # 0–100
    president_party: str  # "D" or "R"

    @property
    def same_party_as_president(self) -> str:
        """Which candidate's party matches the sitting president."""
        return self.president_party


@dataclass
class CandidateQuality:
    """WAR-style quality assessment for a candidate."""

    candidate: str
    party: str  # "D" or "R"
    race: str
    actual_vote_share: float
    expected_vote_share: float
    quality_score: float  # actual − expected (+ = overperformed, - = underperformed)

    @property
    def war(self) -> float:
        """Wins Above Replacement — how much better/worse than generic."""
        return self.quality_score


@dataclass
class FundamentalsProjection:
    """Output of the generic-candidate baseline model."""

    race: str
    expected_dem_share: float
    expected_rep_share: float
    fundamentals_margin: float  # expected D − R
    components: dict[str, float]  # breakdown of each factor's contribution


# ── Baseline model ────────────────────────────────────────────────────

# Coefficients from simplified regressions on 2006–2022 Senate/Governor races.
# These are rough starting points — refine with your own backtesting.
DEFAULT_COEFFICIENTS = {
    "intercept": 50.0,  # baseline Dem vote share at neutral
    "partisan_lean": 0.85,  # each PVI point → ~0.85% vote share
    "generic_ballot": 0.40,  # each GB margin point → ~0.40% vote share
    "incumbency_dem": 3.0,  # Dem incumbent bonus
    "incumbency_rep": -3.0,  # Rep incumbent bonus (hurts Dem share)
    "open_seat": 0.0,  # no adjustment for open seats
    "pres_approval_same_party": 0.15,  # each approval point above 50 helps same party
    "midterm_penalty": -2.5,  # president's party penalty in midterms
}


class CandidateQualityModel:
    """Compute expected vote share from fundamentals and derive candidate quality."""

    def __init__(self, coefficients: dict[str, float] | None = None) -> None:
        self.coefs = coefficients or dict(DEFAULT_COEFFICIENTS)

    def project_fundamentals(self, race: RaceFundamentals) -> FundamentalsProjection:
        """Project expected Dem vote share from structural factors alone."""
        components: dict[str, float] = {}

        # Start from baseline
        expected = self.coefs["intercept"]
        components["intercept"] = self.coefs["intercept"]

        # Partisan lean
        lean_effect = race.partisan_lean * self.coefs["partisan_lean"]
        expected += lean_effect
        components["partisan_lean"] = lean_effect

        # National environment (generic ballot)
        gb_effect = race.generic_ballot_margin * self.coefs["generic_ballot"]
        expected += gb_effect
        components["generic_ballot"] = gb_effect

        # Incumbency
        if race.dem_incumbent:
            inc_effect = self.coefs["incumbency_dem"]
        elif race.rep_incumbent:
            inc_effect = self.coefs["incumbency_rep"]
        else:
            inc_effect = self.coefs["open_seat"]
        expected += inc_effect
        components["incumbency"] = inc_effect

        # Presidential approval × same party
        approval_delta = race.presidential_approval - 50.0
        if race.president_party == "D":
            # High approval helps Dem candidates
            app_effect = approval_delta * self.coefs["pres_approval_same_party"]
        else:
            # High approval for R president hurts Dem candidates
            app_effect = -approval_delta * self.coefs["pres_approval_same_party"]
        expected += app_effect
        components["presidential_approval"] = app_effect

        # Midterm penalty for president's party
        is_midterm = race.year % 4 == 2
        if is_midterm:
            if race.president_party == "D":
                midterm_effect = self.coefs["midterm_penalty"]
            else:
                midterm_effect = -self.coefs["midterm_penalty"]  # helps Dems if R president
            expected += midterm_effect
            components["midterm_penalty"] = midterm_effect

        expected = max(20.0, min(80.0, expected))  # clamp to reasonable range
        rep_expected = 100.0 - expected

        return FundamentalsProjection(
            race=race.race,
            expected_dem_share=round(expected, 1),
            expected_rep_share=round(rep_expected, 1),
            fundamentals_margin=round(expected - rep_expected, 1),
            components=components,
        )

    def compute_quality(
        self,
        race: RaceFundamentals,
        actual_dem_share: float,
        dem_candidate: str = "",
        rep_candidate: str = "",
    ) -> tuple[CandidateQuality, CandidateQuality]:
        """Compute candidate quality (WAR) for both candidates in a race.

        Returns:
            (dem_quality, rep_quality) tuple.
        """
        projection = self.project_fundamentals(race)

        dem_quality = CandidateQuality(
            candidate=dem_candidate,
            party="D",
            race=race.race,
            actual_vote_share=actual_dem_share,
            expected_vote_share=projection.expected_dem_share,
            quality_score=round(actual_dem_share - projection.expected_dem_share, 1),
        )

        actual_rep_share = 100.0 - actual_dem_share
        rep_quality = CandidateQuality(
            candidate=rep_candidate,
            party="R",
            race=race.race,
            actual_vote_share=actual_rep_share,
            expected_vote_share=projection.expected_rep_share,
            quality_score=round(actual_rep_share - projection.expected_rep_share, 1),
        )

        return dem_quality, rep_quality

    # ── Backtesting ───────────────────────────────────────────────────

    def backtest(
        self,
        races: list[RaceFundamentals],
        actual_dem_shares: list[float],
    ) -> dict[str, Any]:
        """Run the model on historical races and compute error metrics.

        Returns:
            Dict with RMSE, MAE, mean error, and per-race results.
        """
        errors: list[float] = []
        results: list[dict] = []

        for race, actual in zip(races, actual_dem_shares):
            proj = self.project_fundamentals(race)
            error = actual - proj.expected_dem_share
            errors.append(error)
            results.append({
                "race": race.race,
                "actual": actual,
                "expected": proj.expected_dem_share,
                "error": round(error, 1),
                "components": proj.components,
            })

        errors_arr = np.array(errors)
        return {
            "n_races": len(races),
            "rmse": round(float(np.sqrt(np.mean(errors_arr ** 2))), 2),
            "mae": round(float(np.mean(np.abs(errors_arr))), 2),
            "mean_error": round(float(np.mean(errors_arr)), 2),
            "median_error": round(float(np.median(errors_arr)), 2),
            "results": results,
        }
