"""Silver Bulletin pollster ratings scraper.

Scrapes Nate Silver's public pollster ratings table.
These ratings seed the quality weights before optimization runs.

Public ratings page: https://www.natesilver.net/p/pollster-ratings-silver-bulletin
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from config.settings import settings

logger = logging.getLogger(__name__)

RATINGS_URLS = [
    "https://www.natesilver.net/p/pollster-ratings-silver-bulletin",
    "https://natesilver.net/p/pollster-ratings-silver-bulletin",
]


class SilverBulletinClient:
    """Scraper for Silver Bulletin public pollster ratings."""

    def __init__(self, cache_dir: Path | None = None, timeout: float = 30.0) -> None:
        self.cache_dir = cache_dir or (settings.raw_data_dir / "silver_bulletin")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; election-oracle/0.1; "
                    "+https://policyypeaches.substack.com)"
                ),
            },
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SilverBulletinClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def fetch_pollster_ratings(self, force_refresh: bool = False) -> dict[str, float]:
        """Scrape the public pollster ratings table.

        Returns:
            Dict mapping pollster name → numeric rating (0–3 scale).
        """
        cache_path = self.cache_dir / "pollster_ratings.json"

        if cache_path.exists() and not force_refresh:
            logger.info("Loading cached Silver Bulletin ratings")
            return json.loads(cache_path.read_text())

        ratings = self._scrape_ratings()
        if ratings:
            cache_path.write_text(json.dumps(ratings, indent=2))
            logger.info(f"Cached {len(ratings)} pollster ratings")

        return ratings

    def _scrape_ratings(self) -> dict[str, float]:
        """Try each known URL to find the ratings table."""
        for url in RATINGS_URLS:
            try:
                logger.info(f"Fetching Silver Bulletin ratings from {url}")
                resp = self._client.get(url)
                resp.raise_for_status()
                ratings = self._parse_ratings_page(resp.text)
                if ratings:
                    logger.info(f"Parsed {len(ratings)} ratings")
                    return ratings
            except Exception as e:
                logger.warning(f"Failed to scrape {url}: {e}")

        logger.warning(
            "Could not scrape Silver Bulletin ratings. "
            "Using fallback from config/pollster_ratings.json"
        )
        return self._load_fallback()

    @staticmethod
    def _parse_ratings_page(html: str) -> dict[str, float]:
        """Parse the ratings table from the Silver Bulletin page HTML."""
        soup = BeautifulSoup(html, "lxml")
        ratings: dict[str, float] = {}

        # Silver Bulletin uses Substack's table format
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]

            # Find relevant columns — Silver Bulletin uses "pollster" and some numeric grade
            pollster_col = _find_col(headers, ["pollster", "firm", "name"])
            grade_col = _find_col(headers, ["grade", "rating", "score", "numeric grade"])

            if pollster_col is None:
                continue

            for row in rows[1:]:
                cells = row.find_all("td")
                if len(cells) <= max(
                    filter(lambda x: x is not None, [pollster_col, grade_col or 0])
                ):
                    continue

                pollster = cells[pollster_col].get_text(strip=True)
                if not pollster:
                    continue

                # Try to extract numeric rating
                if grade_col is not None:
                    raw = cells[grade_col].get_text(strip=True)
                    numeric = _grade_to_numeric(raw)
                else:
                    # Fall back to letter grade in any cell
                    all_text = " ".join(c.get_text(strip=True) for c in cells)
                    numeric = _extract_grade_from_text(all_text)

                if numeric is not None:
                    ratings[pollster] = numeric

        return ratings

    @staticmethod
    def _load_fallback() -> dict[str, float]:
        """Load ratings from the bundled config/pollster_ratings.json."""
        path = Path(__file__).resolve().parent.parent.parent / "config" / "pollster_ratings.json"
        if path.exists():
            data = json.loads(path.read_text())
            return data.get("ratings", {})
        return {}


def _find_col(headers: list[str], candidates: list[str]) -> int | None:
    for candidate in candidates:
        for i, h in enumerate(headers):
            if candidate in h:
                return i
    return None


def _grade_to_numeric(raw: str) -> float | None:
    """Convert letter grade or numeric string to 0–3 scale."""
    raw = raw.strip()

    # Already numeric
    try:
        val = float(raw)
        # Silver Bulletin may use 0–3 or 0–100 scale — normalize
        if val > 3:
            val = val / 100 * 3
        return round(min(3.0, max(0.0, val)), 2)
    except ValueError:
        pass

    # Letter grade → numeric
    grade_map = {
        "A+": 3.0, "A": 2.8, "A-": 2.6,
        "B+": 2.4, "B": 2.2, "B-": 2.0,
        "C+": 1.8, "C": 1.6, "C-": 1.4,
        "D+": 1.2, "D": 1.0, "D-": 0.8,
        "F": 0.3,
    }
    for grade, val in grade_map.items():
        if raw.upper().startswith(grade):
            return val

    return None


def _extract_grade_from_text(text: str) -> float | None:
    """Extract a letter grade from anywhere in a string."""
    match = re.search(r"\b([A-F][+-]?)\b", text)
    if match:
        return _grade_to_numeric(match.group(1))
    return None
