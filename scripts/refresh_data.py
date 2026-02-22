"""Scheduled data pull — fetches latest polls from all configured sources."""

from __future__ import annotations

import logging
from pathlib import Path

from config.settings import settings
from src.data.votehub import VoteHubClient

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=getattr(logging, settings.log_level))
    cache_dir = settings.raw_data_dir

    logger.info("Starting data refresh...")

    # VoteHub
    with VoteHubClient(cache_dir=cache_dir) as client:
        logger.info("Fetching approval polls from VoteHub...")
        approval = client.fetch_polls(poll_type=__import__("src.data.base", fromlist=["PollType"]).PollType.APPROVAL)
        logger.info(f"  Got {len(approval)} approval polls")

        logger.info("Fetching generic ballot polls from VoteHub...")
        from src.data.base import PollType
        gb = client.fetch_polls(poll_type=PollType.GENERIC_BALLOT)
        logger.info(f"  Got {len(gb)} generic ballot polls")

    logger.info("Data refresh complete.")


if __name__ == "__main__":
    main()
