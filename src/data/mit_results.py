"""MIT Election Data + Science Lab (MEDSL) results downloader.

Provides cleaned historical election results for Senate, House, and Governor
races going back to 1976. Hosted on Harvard Dataverse and GitHub.

Primary source: https://electionlab.mit.edu/data
GitHub mirror: https://github.com/MEDSL

These results are the TARGET VARIABLE for training the polling average engine.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

# MEDSL data via Harvard Dataverse and GitHub mirrors
# Format: tab-separated files (.tab) or CSV
MEDSL_URLS: dict[str, list[str]] = {
    "senate": [
        # GitHub mirror (most reliable)
        "https://raw.githubusercontent.com/MEDSL/2022-elections-official/main/dataverse_files/1976-2022-senate.tab",
        # Harvard Dataverse direct download fallback
        "https://dataverse.harvard.edu/api/access/datafile/:persistentId?persistentId=doi:10.7910/DVN/IG0UN2/SDOUVT",
    ],
    "house": [
        "https://raw.githubusercontent.com/MEDSL/2022-elections-official/main/dataverse_files/1976-2022-house.tab",
        "https://dataverse.harvard.edu/api/access/datafile/:persistentId?persistentId=doi:10.7910/DVN/IG0UN2/ZSFUI2",
    ],
    "governor": [
        "https://raw.githubusercontent.com/MEDSL/2022-elections-official/main/dataverse_files/1976-2022-governor.tab",
    ],
}


@dataclass
class ElectionResult:
    """A single candidate's result in a historical election."""

    year: int
    state: str
    state_po: str  # two-letter abbreviation
    office: str    # senate, house, governor
    district: str | None
    special: bool
    candidate: str
    party: str
    candidatevotes: int
    totalvotes: int
    winner: bool

    @property
    def vote_share(self) -> float:
        if self.totalvotes == 0:
            return 0.0
        return round(self.candidatevotes / self.totalvotes * 100, 2)

    @property
    def race_id(self) -> str:
        parts = [self.state_po, self.office, str(self.year)]
        if self.district and self.district not in ("0", "statewide", ""):
            parts.insert(2, self.district)
        return "-".join(parts).upper()


@dataclass
class RaceResult:
    """Aggregated result for a single race — top two candidates."""

    race_id: str
    year: int
    state: str
    state_po: str
    office: str
    special: bool
    dem_candidate: str
    dem_votes: int
    rep_candidate: str
    rep_votes: int
    total_votes: int
    dem_share: float  # of total votes
    rep_share: float
    dem_two_party_share: float  # of two-party vote only
    winner_party: str

    @property
    def margin(self) -> float:
        return round(self.dem_share - self.rep_share, 2)


class MITResultsClient:
    """Downloads and parses MEDSL historical election results."""

    def __init__(self, cache_dir: Path | None = None, timeout: float = 60.0) -> None:
        self.cache_dir = cache_dir or (settings.raw_data_dir / "mit_results")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "election-oracle/0.1"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> MITResultsClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ── Public API ────────────────────────────────────────────────────

    def fetch_senate_results(self, min_year: int = 2000) -> list[RaceResult]:
        return self._fetch_results("senate", min_year)

    def fetch_governor_results(self, min_year: int = 2000) -> list[RaceResult]:
        return self._fetch_results("governor", min_year)

    def fetch_house_results(self, min_year: int = 2000) -> list[RaceResult]:
        return self._fetch_results("house", min_year)

    def fetch_all(self, min_year: int = 2000) -> list[RaceResult]:
        all_results: list[RaceResult] = []
        for office in MEDSL_URLS:
            try:
                all_results.extend(self._fetch_results(office, min_year))
            except Exception as e:
                logger.warning(f"Could not fetch {office} results: {e}")
        return all_results

    # ── Internals ─────────────────────────────────────────────────────

    def _fetch_results(self, office: str, min_year: int) -> list[RaceResult]:
        cache_path = self.cache_dir / f"{office}_results.tab"

        if cache_path.exists():
            logger.info(f"Loading cached MEDSL {office} results")
            text = cache_path.read_text(encoding="utf-8")
        else:
            text = self._download(office)
            cache_path.write_text(text, encoding="utf-8")

        candidates = self._parse_tab(text, office)
        candidates = [c for c in candidates if c.year >= min_year]
        return self._aggregate_to_races(candidates)

    def _download(self, office: str) -> str:
        urls = MEDSL_URLS.get(office, [])
        last_err: Exception | None = None

        for url in urls:
            try:
                logger.info(f"Downloading MEDSL {office} results from {url[:60]}...")
                resp = self._client.get(url)
                resp.raise_for_status()
                logger.info(f"Downloaded {len(resp.text.splitlines())} rows")
                return resp.text
            except Exception as e:
                logger.warning(f"Failed from {url[:60]}: {e}")
                last_err = e

        raise RuntimeError(
            f"Could not download {office} results from any known URL. "
            f"Last error: {last_err}. "
            "Download manually from https://electionlab.mit.edu/data "
            "and place in data/raw/mit_results/"
        ) from last_err

    @staticmethod
    def _parse_tab(text: str, office: str) -> list[ElectionResult]:
        """Parse MEDSL tab-separated file."""
        results: list[ElectionResult] = []
        # MEDSL files are tab-delimited
        delimiter = "\t" if "\t" in text[:500] else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)

        for row in reader:
            try:
                result = MITResultsClient._normalize_row(row, office)
                if result:
                    results.append(result)
            except (ValueError, KeyError):
                continue

        logger.info(f"Parsed {len(results)} {office} candidate rows")
        return results

    @staticmethod
    def _normalize_row(row: dict[str, str], office: str) -> ElectionResult | None:
        """Normalize a raw MEDSL row."""
        year_raw = row.get("year", "").strip()
        try:
            year = int(year_raw)
        except ValueError:
            return None

        state = (row.get("state") or "").strip()
        state_po = (row.get("state_po") or "").strip()
        candidate = (row.get("candidate") or "").strip()
        if not candidate or candidate.lower() in ("na", "nan", ""):
            return None

        party_raw = (
            (row.get("party_simplified") or row.get("party_detailed") or row.get("party") or "")
            .strip()
            .upper()
        )
        # Normalize party to D/R/OTHER
        if party_raw in ("DEMOCRAT", "DEMOCRATIC"):
            party = "D"
        elif party_raw in ("REPUBLICAN",):
            party = "R"
        else:
            party = party_raw or "OTHER"

        try:
            candidatevotes = int(float(row.get("candidatevotes", 0) or 0))
            totalvotes = int(float(row.get("totalvotes", 0) or 0))
        except ValueError:
            return None

        if totalvotes == 0:
            return None

        district = (row.get("district") or "").strip()
        special_raw = (row.get("special") or "").strip().lower()
        special = special_raw in ("true", "1", "yes")

        writein_raw = (row.get("writein") or "").strip().lower()
        if writein_raw in ("true", "1", "yes"):
            return None  # skip write-ins

        return ElectionResult(
            year=year,
            state=state,
            state_po=state_po,
            office=office,
            district=district if district else None,
            special=special,
            candidate=candidate,
            party=party,
            candidatevotes=candidatevotes,
            totalvotes=totalvotes,
            winner=False,  # computed in aggregate step
        )

    @staticmethod
    def _aggregate_to_races(candidates: list[ElectionResult]) -> list[RaceResult]:
        """Group individual candidate rows into race-level results."""
        # Group by race
        races: dict[str, list[ElectionResult]] = {}
        for c in candidates:
            key = c.race_id
            races.setdefault(key, []).append(c)

        results: list[RaceResult] = []
        for race_id, entries in races.items():
            if not entries:
                continue

            first = entries[0]
            total = max(e.totalvotes for e in entries)

            # Find top D and R candidates
            dems = sorted(
                [e for e in entries if e.party == "D"],
                key=lambda x: x.candidatevotes,
                reverse=True,
            )
            reps = sorted(
                [e for e in entries if e.party == "R"],
                key=lambda x: x.candidatevotes,
                reverse=True,
            )

            if not dems or not reps:
                continue  # skip uncontested

            dem = dems[0]
            rep = reps[0]

            dem_share = round(dem.candidatevotes / total * 100, 2) if total > 0 else 0.0
            rep_share = round(rep.candidatevotes / total * 100, 2) if total > 0 else 0.0
            two_party = dem.candidatevotes + rep.candidatevotes
            dem_two_party = round(dem.candidatevotes / two_party * 100, 2) if two_party > 0 else 0.0
            winner_party = "D" if dem.candidatevotes > rep.candidatevotes else "R"

            results.append(RaceResult(
                race_id=race_id,
                year=first.year,
                state=first.state,
                state_po=first.state_po,
                office=first.office,
                special=first.special,
                dem_candidate=dem.candidate,
                dem_votes=dem.candidatevotes,
                rep_candidate=rep.candidate,
                rep_votes=rep.candidatevotes,
                total_votes=total,
                dem_share=dem_share,
                rep_share=rep_share,
                dem_two_party_share=dem_two_party,
                winner_party=winner_party,
            ))

        logger.info(f"Aggregated to {len(results)} races")
        return results
