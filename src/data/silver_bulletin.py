"""Silver Bulletin pollster ratings scraper.

The public pollster ratings table is free and useful for weighting.
Full data (approval tracker, forecasts) requires a paid Substack subscription.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.data.base import DataSource, Poll, PollType


class SilverBulletinClient(DataSource):
    """Scraper for Silver Bulletin public pollster ratings.

    Stub — implement scraping when the ratings page structure is confirmed.
    """

    name = "silver_bulletin"

    def __init__(self, cache_dir: Path | None = None) -> None:
        super().__init__(cache_dir=cache_dir)

    def fetch_polls(
        self,
        poll_type: PollType | None = None,
        subject: str | None = None,
        **kwargs: Any,
    ) -> list[Poll]:
        raise NotImplementedError("Silver Bulletin poll data requires paid subscription")

    def fetch_pollsters(self) -> list[str]:
        raise NotImplementedError

    def fetch_pollster_ratings(self) -> dict[str, float]:
        """Scrape the public pollster ratings table.

        Returns:
            Dict mapping pollster name → numeric rating.
        """
        # TODO: Implement scraping of natesilver.net pollster ratings page
        raise NotImplementedError("Pollster ratings scraper not yet implemented")
