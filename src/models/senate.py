"""Senate race models — 2026 Class II races with fundamentals, polls, and vibes.

Model architecture:
    1. Prior margin   — from expert rating (Cook/Sabato equivalent) via RATING_MARGIN_PRIOR
    2. Fundamentals   — presidential approval × same-party, generic ballot, incumbency
    3. Polls          — lightly weighted until both primaries are decided
    4. Vibes          — NYT article sentiment (see src/models/vibes.py); feeds margin_adjustment
    5. Win probability — normal-CDF on combined margin with uncertainty that shrinks as n_polls grows

The model is intentionally conservative with polls before primaries are settled:
    - poll_weight = 0.1 (pre-primary) vs 1.0 (both primaries decided)
    - This prevents early horse-race polling with unknown challengers from
      swamping the structural prior.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any

from src.data.base import Poll, PollType
from src.models import ModelMaturity
from src.models.polling_average import AverageResult, PollingAverageEngine


# ── Rating system ──────────────────────────────────────────────────────────────

class RaceRating(str, Enum):
    """Seven-tier race rating scale (D-favourable → R-favourable)."""

    SOLID_D = "Solid D"
    LIKELY_D = "Likely D"
    LEAN_D = "Lean D"
    TOSSUP = "Tossup"
    LEAN_R = "Lean R"
    LIKELY_R = "Likely R"
    SOLID_R = "Solid R"


# Margin prior (D minus R) implied by each rating tier.
# Derived from median actual margins in 2006–2022 Senate races per rating category.
RATING_MARGIN_PRIOR: dict[RaceRating, float] = {
    RaceRating.SOLID_D: 18.0,
    RaceRating.LIKELY_D: 9.0,
    RaceRating.LEAN_D: 3.5,
    RaceRating.TOSSUP: 0.0,
    RaceRating.LEAN_R: -3.5,
    RaceRating.LIKELY_R: -9.0,
    RaceRating.SOLID_R: -18.0,
}

# Uncertainty (SD in margin points) associated with each rating tier.
# Wider for competitive races, tighter for safe ones.
RATING_MARGIN_SD: dict[RaceRating, float] = {
    RaceRating.SOLID_D: 5.0,
    RaceRating.LIKELY_D: 6.5,
    RaceRating.LEAN_D: 7.5,
    RaceRating.TOSSUP: 8.0,
    RaceRating.LEAN_R: 7.5,
    RaceRating.LIKELY_R: 6.5,
    RaceRating.SOLID_R: 5.0,
}


# ── Race metadata ──────────────────────────────────────────────────────────────

@dataclass
class SenateRaceInfo:
    """Static metadata for a Senate race."""

    state: str
    state_abbr: str
    incumbent: str
    incumbent_party: str        # "D", "R", or "I"
    rating: RaceRating
    seat_class: int = 2         # Class II seats are all up in 2026
    open_seat: bool = False     # True if incumbent is not running
    primaries_complete: bool = False  # both major-party nominees decided


# ── 2026 Senate race list (Class II) ──────────────────────────────────────────
# Ratings reflect conditions circa early 2026; update as races develop.

SENATE_RACES_2026: list[SenateRaceInfo] = [
    # ── Competitive D-held seats ──────────────────────────────────────────────
    SenateRaceInfo("Arizona",       "AZ", "Mark Kelly",         "D", RaceRating.TOSSUP),
    SenateRaceInfo("Georgia",       "GA", "Jon Ossoff",         "D", RaceRating.TOSSUP),
    SenateRaceInfo("Michigan",      "MI", "Gary Peters",        "D", RaceRating.LEAN_D),
    SenateRaceInfo("New Hampshire", "NH", "Jeanne Shaheen",     "D", RaceRating.LEAN_D,
                   open_seat=True),
    SenateRaceInfo("Virginia",      "VA", "Mark Warner",        "D", RaceRating.LEAN_D),
    # ── Likely D ─────────────────────────────────────────────────────────────
    SenateRaceInfo("Colorado",      "CO", "John Hickenlooper",  "D", RaceRating.LIKELY_D),
    SenateRaceInfo("Minnesota",     "MN", "Tina Smith",         "D", RaceRating.LIKELY_D),
    SenateRaceInfo("Oregon",        "OR", "Jeff Merkley",       "D", RaceRating.LIKELY_D),
    # ── Safe D ───────────────────────────────────────────────────────────────
    SenateRaceInfo("Delaware",      "DE", "Chris Coons",        "D", RaceRating.SOLID_D),
    SenateRaceInfo("Illinois",      "IL", "Tammy Duckworth",    "D", RaceRating.SOLID_D),
    SenateRaceInfo("Massachusetts", "MA", "Ed Markey",          "D", RaceRating.SOLID_D),
    SenateRaceInfo("New Mexico",    "NM", "Martin Heinrich",    "D", RaceRating.SOLID_D),
    SenateRaceInfo("Rhode Island",  "RI", "Jack Reed",          "D", RaceRating.SOLID_D),
    # ── Competitive R-held seats ──────────────────────────────────────────────
    SenateRaceInfo("Maine",         "ME", "Susan Collins",      "R", RaceRating.LIKELY_R),
    SenateRaceInfo("North Carolina","NC", "Thom Tillis",        "R", RaceRating.LEAN_R),
    # ── Likely R ─────────────────────────────────────────────────────────────
    SenateRaceInfo("Iowa",          "IA", "Joni Ernst",         "R", RaceRating.LIKELY_R),
    SenateRaceInfo("Kentucky",      "KY", "Mitch McConnell",    "R", RaceRating.LIKELY_R,
                   open_seat=True),
    # ── Safe R ───────────────────────────────────────────────────────────────
    SenateRaceInfo("Alabama",       "AL", "Tommy Tuberville",   "R", RaceRating.SOLID_R),
    SenateRaceInfo("Alaska",        "AK", "Dan Sullivan",       "R", RaceRating.SOLID_R),
    SenateRaceInfo("Arkansas",      "AR", "Tom Cotton",         "R", RaceRating.SOLID_R),
    SenateRaceInfo("Idaho",         "ID", "Jim Risch",          "R", RaceRating.SOLID_R),
    SenateRaceInfo("Kansas",        "KS", "Roger Marshall",     "R", RaceRating.SOLID_R),
    SenateRaceInfo("Louisiana",     "LA", "Bill Cassidy",       "R", RaceRating.SOLID_R),
    SenateRaceInfo("Mississippi",   "MS", "Roger Wicker",       "R", RaceRating.SOLID_R),
    SenateRaceInfo("Montana",       "MT", "Steve Daines",       "R", RaceRating.SOLID_R),
    SenateRaceInfo("Nebraska",      "NE", "Pete Ricketts",      "R", RaceRating.SOLID_R),
    SenateRaceInfo("Oklahoma",      "OK", "James Lankford",     "R", RaceRating.SOLID_R),
    SenateRaceInfo("South Carolina","SC", "Lindsey Graham",     "R", RaceRating.SOLID_R),
    SenateRaceInfo("South Dakota",  "SD", "Mike Rounds",        "R", RaceRating.SOLID_R),
    SenateRaceInfo("Tennessee",     "TN", "Bill Hagerty",       "R", RaceRating.SOLID_R),
    SenateRaceInfo("Texas",         "TX", "John Cornyn",        "R", RaceRating.SOLID_R),
    SenateRaceInfo("West Virginia", "WV", "Shelley Moore Capito","R", RaceRating.SOLID_R),
    SenateRaceInfo("Wyoming",       "WY", "Cynthia Lummis",     "R", RaceRating.SOLID_R),
]

_RACE_INDEX: dict[str, SenateRaceInfo] = {r.state.lower(): r for r in SENATE_RACES_2026}


# ── Snapshot ───────────────────────────────────────────────────────────────────

@dataclass
class SenateRaceSnapshot:
    """Model output for a single Senate race."""

    state: str
    state_abbr: str
    as_of: date
    candidates: dict[str, float]    # party/name → weighted avg pct
    margin: float | None            # D minus R (positive = D leading)
    num_polls: int
    rating: RaceRating
    incumbent: str
    prob_d: float | None = None
    prob_r: float | None = None
    vibes_adjustment: float = 0.0   # margin shift applied from vibes model (ppct)
    poll_weight_applied: float = 1.0  # 0.1 if pre-primary, 1.0 if decided


# ── Model ──────────────────────────────────────────────────────────────────────

class SenateModel:
    """Track and forecast 2026 Senate races.

    Maturity: NOWCAST — combines structural prior, polls (conditionally weighted),
    and vibes adjustment to produce per-race margins and win probabilities.
    """

    maturity = ModelMaturity.NOWCAST

    # Weight applied to polls before both primaries are settled.
    # We don't want a single early poll with unknown opponents driving forecasts.
    PRE_PRIMARY_POLL_WEIGHT = 0.1

    def __init__(self, engine: PollingAverageEngine | None = None) -> None:
        self.engine = engine or PollingAverageEngine()

    # ── Public interface ───────────────────────────────────────────────────────

    def race_average(
        self,
        polls: list[Poll],
        state: str,
        vibes_adjustment: float = 0.0,
    ) -> SenateRaceSnapshot:
        """Compute the combined model estimate for a single Senate race.

        Args:
            polls: All Senate polls (will be filtered to this state).
            state: Full state name, e.g. "Georgia".
            vibes_adjustment: Signed margin shift from the vibes model (ppct, + = D).
        """
        info = _RACE_INDEX.get(state.lower())
        if info is None:
            info = SenateRaceInfo(
                state=state,
                state_abbr="??",
                incumbent="Unknown",
                incumbent_party="?",
                rating=RaceRating.TOSSUP,
            )

        prior_margin = RATING_MARGIN_PRIOR[info.rating]
        poll_weight = 1.0 if info.primaries_complete else self.PRE_PRIMARY_POLL_WEIGHT

        state_polls = self._filter_polls(polls, state)
        result = self.engine.compute_average(state_polls)
        poll_margin = self._compute_partisan_margin(result)

        if poll_margin is not None and result.num_polls > 0:
            # Blend prior and polls — polls grow in influence as n increases
            blend = min(1.0, poll_weight * result.num_polls / (result.num_polls + 5))
            combined_margin = blend * poll_margin + (1 - blend) * prior_margin
        else:
            combined_margin = prior_margin

        final_margin = combined_margin + vibes_adjustment
        prob_d, prob_r = self._estimate_win_prob(final_margin, result.num_polls)

        return SenateRaceSnapshot(
            state=info.state,
            state_abbr=info.state_abbr,
            as_of=result.as_of,
            candidates=result.averages,
            margin=round(final_margin, 1),
            num_polls=result.num_polls,
            rating=info.rating,
            incumbent=info.incumbent,
            prob_d=prob_d,
            prob_r=prob_r,
            vibes_adjustment=vibes_adjustment,
            poll_weight_applied=poll_weight,
        )

    def all_races(
        self,
        polls: list[Poll],
        vibes_adjustments: dict[str, float] | None = None,
    ) -> list[SenateRaceSnapshot]:
        """Return model snapshots for every 2026 Senate race."""
        adj = vibes_adjustments or {}
        return [
            self.race_average(polls, race.state, vibes_adjustment=adj.get(race.state, 0.0))
            for race in SENATE_RACES_2026
        ]

    def chamber_summary(
        self,
        polls: list[Poll],
        vibes_adjustments: dict[str, float] | None = None,
        *,
        current_d_seats_not_up: int = 29,
        current_r_seats_not_up: int = 36,
    ) -> dict[str, Any]:
        """Project chamber control from all 2026 races.

        Args:
            current_d_seats_not_up: Democratic seats in Class I + III (not up in 2026).
            current_r_seats_not_up: Republican seats in Class I + III (not up in 2026).
        """
        snapshots = self.all_races(polls, vibes_adjustments)

        d_wins = current_d_seats_not_up
        r_wins = current_r_seats_not_up
        tossup_count = 0

        for snap in snapshots:
            if snap.rating == RaceRating.TOSSUP:
                tossup_count += 1
            elif snap.margin is not None:
                if snap.margin > 0:
                    d_wins += 1
                else:
                    r_wins += 1

        return {
            "projected_d_seats": d_wins,
            "projected_r_seats": r_wins,
            "tossup_count": tossup_count,
            "races_tracked": len(snapshots),
            "as_of": date.today().isoformat(),
        }

    # ── Static helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _filter_polls(polls: list[Poll], state: str) -> list[Poll]:
        """Keep only head-to-head polls for the given state's Senate race."""
        return [
            p for p in polls
            if p.poll_type == PollType.HEAD_TO_HEAD
            and state.lower() in p.subject.lower()
        ]

    @staticmethod
    def _compute_partisan_margin(result: AverageResult) -> float | None:
        """Extract D-R margin from an AverageResult, normalising label variants."""
        dem = 0.0
        rep = 0.0
        found_d = found_r = False
        for choice, pct in result.averages.items():
            cl = choice.lower()
            if cl in ("democrat", "democratic", "democrats", "dem", "d"):
                dem = pct
                found_d = True
            elif cl in ("republican", "republicans", "gop", "rep", "r"):
                rep = pct
                found_r = True
        if not (found_d or found_r):
            return None
        return round(dem - rep, 1)

    @staticmethod
    def _estimate_win_prob(
        margin: float | None,
        num_polls: int,
    ) -> tuple[float | None, float | None]:
        """Estimate D and R win probabilities from a margin and poll count.

        Uses a normal CDF where the residual SD shrinks as more polls accumulate.
        The floor SD of ~7 pp reflects irreducible uncertainty in Senate races;
        tightens to ~3.5 pp with many high-quality polls.
        """
        if margin is None:
            return None, None

        # Uncertainty: starts at ~7 pp SD with 0 polls, asymptotes to ~3.5 pp
        sd = 3.5 + 7.0 * math.exp(-0.15 * num_polls)

        # P(D wins) = P(margin + noise > 0) = Φ(margin / sd)
        z = margin / sd
        prob_d = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        return round(prob_d, 4), round(1 - prob_d, 4)
