"""Training data loader — joins 538 polls to MIT election results.

Produces TrainingRace objects: a set of polls for a race paired with
the actual election result. These are the inputs/outputs for optimizer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from src.data.base import Poll, PollAnswer, PollType, Population
from src.data.fte_archive import FTEArchiveClient, FTEPoll
from src.data.mit_results import MITResultsClient, RaceResult

logger = logging.getLogger(__name__)

# Polls taken within this many days before election day are used for training
DEFAULT_LOOKBACK_DAYS = 60

# Minimum polls per race to include in training
MIN_POLLS_PER_RACE = 3


@dataclass
class TrainingRace:
    """A race with its pre-election polls and actual result — one training example."""

    race_id: str
    year: int
    state: str
    office: str
    polls: list[Poll]
    actual_dem_share: float       # actual election result
    actual_rep_share: float
    dem_two_party_share: float    # of two-party vote only (cleaner for regression)
    winner_party: str
    dem_candidate: str = ""
    rep_candidate: str = ""

    @property
    def dem_won(self) -> bool:
        return self.winner_party == "D"


class TrainingDataLoader:
    """Loads and joins 538 polls with MIT results for model training."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        min_polls: int = MIN_POLLS_PER_RACE,
    ) -> None:
        self.cache_dir = cache_dir
        self.lookback_days = lookback_days
        self.min_polls = min_polls

    def load(
        self,
        offices: list[str] | None = None,
        min_year: int = 2010,
        max_year: int = 2022,
    ) -> list[TrainingRace]:
        """Load all training races.

        Args:
            offices: Subset of ['senate', 'governor', 'house']. Default: senate + governor.
            min_year: Earliest election cycle to include.
            max_year: Latest election cycle to include.

        Returns:
            List of TrainingRace objects ready for the optimizer.
        """
        if offices is None:
            offices = ["senate", "governor"]

        logger.info(f"Loading training data: {offices} {min_year}–{max_year}")

        # Download / load from cache
        fte = FTEArchiveClient(cache_dir=self.cache_dir)
        mit = MITResultsClient(cache_dir=self.cache_dir)

        fte_polls: list[FTEPoll] = []
        results: list[RaceResult] = []

        for office in offices:
            try:
                if office == "senate":
                    fte_polls.extend(fte.fetch_senate_polls())
                    results.extend(mit.fetch_senate_results(min_year=min_year))
                elif office == "governor":
                    fte_polls.extend(fte.fetch_governor_polls())
                    results.extend(mit.fetch_governor_results(min_year=min_year))
                elif office == "house":
                    fte_polls.extend(
                        fte.fetch_house_results() if hasattr(fte, "fetch_house_results") else []
                    )
                    results.extend(mit.fetch_house_results(min_year=min_year))
            except Exception as e:
                logger.warning(f"Error loading {office} data: {e}")

        fte.close()
        mit.close()

        # Filter by year range
        results = [r for r in results if min_year <= r.year <= max_year]
        fte_polls = [p for p in fte_polls if min_year <= p.cycle <= max_year]

        logger.info(f"Loaded {len(fte_polls)} polls and {len(results)} race results")

        return self._join(fte_polls, results)

    def _join(
        self, fte_polls: list[FTEPoll], results: list[RaceResult]
    ) -> list[TrainingRace]:
        """Match polls to race results and build TrainingRace objects."""
        # Index results by race_id
        result_index: dict[str, RaceResult] = {r.race_id: r for r in results}

        # Group polls by (state_po, office, cycle)
        poll_groups: dict[str, list[FTEPoll]] = {}
        for poll in fte_polls:
            state_po = _state_to_abbrev(poll.state)
            key = f"{state_po}-{poll.office.upper()}-{poll.cycle}"
            poll_groups.setdefault(key, []).append(poll)

        training_races: list[TrainingRace] = []

        for race_id, result in result_index.items():
            # Find matching polls
            poll_key = race_id  # already in STATE-OFFICE-YEAR format
            raw_polls = poll_groups.get(poll_key, [])

            if not raw_polls:
                # Try alternate key formats
                alt_key = f"{result.state_po}-{result.office.upper()}-{result.year}"
                raw_polls = poll_groups.get(alt_key, [])

            if len(raw_polls) < self.min_polls:
                continue

            # Filter to polls within lookback window before election day
            election_day = _election_day(result.year)
            cutoff = election_day - timedelta(days=self.lookback_days)
            recent_polls = [p for p in raw_polls if p.end_date >= cutoff]

            if len(recent_polls) < self.min_polls:
                continue

            # Convert FTEPolls to normalized Poll objects
            normalized = _fte_polls_to_polls(recent_polls, result)

            training_races.append(TrainingRace(
                race_id=race_id,
                year=result.year,
                state=result.state_po,
                office=result.office,
                polls=normalized,
                actual_dem_share=result.dem_share,
                actual_rep_share=result.rep_share,
                dem_two_party_share=result.dem_two_party_share,
                winner_party=result.winner_party,
                dem_candidate=result.dem_candidate,
                rep_candidate=result.rep_candidate,
            ))

        logger.info(
            f"Joined {len(training_races)} training races "
            f"(dropped {len(result_index) - len(training_races)} with insufficient polls)"
        )
        return training_races


# ── Helpers ───────────────────────────────────────────────────────────


def _fte_polls_to_polls(fte_polls: list[FTEPoll], result: RaceResult) -> list[Poll]:
    """Convert FTE poll records to normalized Poll objects.

    Groups by poll_id to reconstruct multi-candidate polls.
    """
    # Group by poll_id to reconstruct answer lists
    poll_groups: dict[str, list[FTEPoll]] = {}
    for p in fte_polls:
        poll_groups.setdefault(p.poll_id, []).append(p)

    polls: list[Poll] = []
    for poll_id, entries in poll_groups.items():
        first = entries[0]
        answers = []
        for e in entries:
            # Map to candidate name or party
            choice = e.candidate if e.candidate else e.party
            answers.append(PollAnswer(choice=choice, pct=e.pct))

        pop_map = {
            "lv": Population.LIKELY_VOTERS,
            "rv": Population.REGISTERED_VOTERS,
            "a": Population.ADULTS,
        }
        population = pop_map.get((first.population or "").lower())

        polls.append(Poll(
            poll_id=f"fte-{poll_id}",
            source="fte_archive",
            poll_type=PollType.HEAD_TO_HEAD,
            pollster=first.pollster,
            subject=f"{result.state_po}-{result.office}-{result.year}",
            start_date=first.start_date,
            end_date=first.end_date,
            sample_size=first.sample_size,
            population=population,
            answers=answers,
            partisan=first.partisan,
            internal=first.internal,
        ))

    return polls


def _election_day(year: int) -> date:
    """First Tuesday after first Monday in November."""
    nov1 = date(year, 11, 1)
    # Tuesday is weekday 1
    days_until_tuesday = (1 - nov1.weekday()) % 7
    if days_until_tuesday == 0:
        days_until_tuesday = 7
    return nov1 + timedelta(days=days_until_tuesday)


_STATE_ABBREVS: dict[str, str] = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
}


def _state_to_abbrev(state: str) -> str:
    """Convert full state name to two-letter abbreviation."""
    if len(state) == 2:
        return state.upper()
    return _STATE_ABBREVS.get(state.title(), state.upper()[:2])
