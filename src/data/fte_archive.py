"""FiveThirtyEight archived polling data downloader.

538 published all their polling data to GitHub before shutdown (March 2025).
The repo remains live at https://github.com/fivethirtyeight/data

Downloads Senate, House, and Governor polls for use as training data.
All files cached locally after first download.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

FTE_POLL_FILES: dict[str, str] = {
    "senate":    "senate_polls.csv",
    "president": "president_polls.csv",
    "house":     "house_polls.csv",
    "governor":  "governor_polls.csv",
}

# 538's poll database is published as one CSV per office. After ABC wound 538
# down (2025) the canonical home moved off the old `master` branch, so we try
# several mirrors in order: the still-served projects.fivethirtyeight.com data
# files, then both branch names on the GitHub archive.
FTE_URL_BASES: list[str] = [
    "https://projects.fivethirtyeight.com/polls/data",
    "https://raw.githubusercontent.com/fivethirtyeight/data/main/polls",
    "https://raw.githubusercontent.com/fivethirtyeight/data/master/polls",
]

# Back-compat: primary URL per office (first base).
FTE_POLL_URLS: dict[str, str] = {
    office: f"{FTE_URL_BASES[0]}/{fname}" for office, fname in FTE_POLL_FILES.items()
}

# GitHub API to discover what's actually in the polls directory (last resort).
FTE_GITHUB_API = "https://api.github.com/repos/fivethirtyeight/data/contents/polls"


def _candidate_urls(office: str) -> list[str]:
    """Ordered list of mirror URLs to try for an office's poll CSV."""
    fname = FTE_POLL_FILES.get(office)
    if not fname:
        return []
    return [f"{base}/{fname}" for base in FTE_URL_BASES]


@dataclass
class FTEPoll:
    """A single poll record from the 538 archive."""

    poll_id: str
    cycle: int
    state: str
    office: str          # senate, president, house, governor
    pollster: str
    start_date: date
    end_date: date
    sample_size: int | None
    population: str | None  # lv, rv, a
    candidate: str
    party: str
    pct: float
    internal: bool
    partisan: bool


class FTEArchiveClient:
    """Downloads and parses 538's archived polling data from GitHub."""

    def __init__(self, cache_dir: Path | None = None, timeout: float = 60.0) -> None:
        self.cache_dir = cache_dir or (settings.raw_data_dir / "fte_archive")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "User-Agent": "election-oracle/0.1 (github.com/Hijodeagua/Election-models-by-Tre)"
            },
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> FTEArchiveClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ── Public API ────────────────────────────────────────────────────

    def fetch_senate_polls(self) -> list[FTEPoll]:
        return self._fetch_polls("senate")

    def fetch_governor_polls(self) -> list[FTEPoll]:
        return self._fetch_polls("governor")

    def fetch_president_polls(self) -> list[FTEPoll]:
        return self._fetch_polls("president")

    def fetch_all(self) -> list[FTEPoll]:
        all_polls: list[FTEPoll] = []
        for office in FTE_POLL_URLS:
            try:
                all_polls.extend(self._fetch_polls(office))
            except Exception as e:
                logger.warning(f"Could not fetch {office} polls: {e}")
        return all_polls

    def discover_available_files(self) -> list[str]:
        """Query GitHub API to see what CSV files are actually in the polls directory."""
        resp = self._client.get(FTE_GITHUB_API)
        if resp.status_code != 200:
            logger.warning("GitHub API unavailable, using known URLs")
            return list(FTE_POLL_URLS.keys())
        files = resp.json()
        return [f["name"] for f in files if f["name"].endswith(".csv")]

    # ── Internals ─────────────────────────────────────────────────────

    def _fetch_polls(self, office: str) -> list[FTEPoll]:
        cache_path = self.cache_dir / f"{office}_polls.csv"

        if cache_path.exists():
            logger.info(f"Loading cached 538 {office} polls")
            return self._parse_csv(cache_path.read_text(), office)

        candidates = _candidate_urls(office)
        if not candidates:
            raise ValueError(f"Unknown office: {office}")

        # Append the GitHub-API-discovered URL as a final fallback.
        discovered = self._discover_url(office)
        if discovered and discovered not in candidates:
            candidates.append(discovered)

        resp = None
        for url in candidates:
            logger.info(f"Downloading 538 {office} polls: {url}")
            try:
                r = self._client.get(url)
            except Exception as exc:
                logger.warning(f"  fetch failed ({exc})")
                continue
            if r.status_code == 200 and "," in r.text[:2000]:
                resp = r
                break
            logger.warning(f"  HTTP {r.status_code} — trying next mirror")

        if resp is None:
            raise FileNotFoundError(
                f"538 {office} polls not reachable at any known mirror "
                f"({', '.join(candidates)}). The 538 data repo may have moved."
            )

        cache_path.write_text(resp.text)
        logger.info(f"Cached {len(resp.text.splitlines())} rows for {office}")
        return self._parse_csv(resp.text, office)

    def _discover_url(self, office: str) -> str | None:
        """Try GitHub API to find the actual filename for an office."""
        try:
            resp = self._client.get(FTE_GITHUB_API)
            files = resp.json()
            for f in files:
                name = f["name"].lower()
                if office in name and name.endswith(".csv"):
                    return f["download_url"]
        except Exception:
            pass
        return None

    @staticmethod
    def _parse_csv(text: str, office: str) -> list[FTEPoll]:
        """Parse 538 poll CSV into FTEPoll records."""
        polls: list[FTEPoll] = []
        reader = csv.DictReader(io.StringIO(text))

        for row in reader:
            try:
                poll = FTEArchiveClient._normalize_row(row, office)
                if poll:
                    polls.append(poll)
            except (ValueError, KeyError):
                continue

        logger.info(f"Parsed {len(polls)} {office} poll records")
        return polls

    @staticmethod
    def _normalize_row(row: dict[str, str], office: str) -> FTEPoll | None:
        """Convert a raw CSV row to a FTEPoll. Returns None for unparseable rows."""
        # Cycle / year
        cycle_raw = row.get("cycle", row.get("year", ""))
        try:
            cycle = int(str(cycle_raw).strip())
        except ValueError:
            return None

        # State
        state = (row.get("state") or row.get("state_name") or "").strip()
        if not state:
            return None

        # Pollster
        pollster = (row.get("pollster") or row.get("display_name") or "Unknown").strip()

        # Dates
        start_raw = row.get("start_date") or row.get("field_start") or ""
        end_raw = row.get("end_date") or row.get("field_end") or ""
        start_date = _parse_fte_date(start_raw)
        end_date = _parse_fte_date(end_raw)
        if not start_date or not end_date:
            return None

        # Sample
        sample_raw = row.get("sample_size") or row.get("n") or ""
        try:
            sample_size = int(float(sample_raw)) if sample_raw else None
        except ValueError:
            sample_size = None

        population = (row.get("population") or "").strip().lower() or None

        # Candidate / pct
        candidate = (row.get("answer") or row.get("candidate_name") or "").strip()
        party = (row.get("party") or row.get("candidate_party") or "").strip().upper()
        pct_raw = row.get("pct") or row.get("estimate") or "0"
        try:
            pct = float(pct_raw)
        except ValueError:
            return None

        return FTEPoll(
            poll_id=row.get("poll_id", f"fte-{state}-{cycle}-{pollster}"),
            cycle=cycle,
            state=state,
            office=office,
            pollster=pollster,
            start_date=start_date,
            end_date=end_date,
            sample_size=sample_size,
            population=population,
            candidate=candidate,
            party=party,
            pct=pct,
            internal=row.get("internal", "").strip().lower() in ("true", "1", "yes"),
            partisan=row.get("partisan", "").strip() not in ("", "0", "false", "no"),
        )


def _parse_fte_date(raw: str) -> date | None:
    """Parse 538 date formats: M/D/YY, MM/DD/YYYY, YYYY-MM-DD."""
    raw = raw.strip()
    if not raw:
        return None
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None
