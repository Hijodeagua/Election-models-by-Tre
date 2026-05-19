"""Fetch latest polls from all configured sources and write to disk cache.

Run this on a schedule (cron, APScheduler, etc.) to keep the cache fresh.
The run_models.py script reads from that cache.

Usage:
    python scripts/refresh_data.py
    python scripts/refresh_data.py --source rcp      # RCP only
    python scripts/refresh_data.py --source votehub  # VoteHub only (default)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings
from src.data.base import PollType
from src.data.rcp import RCPClient
from src.data.votehub import VoteHubClient

logger = logging.getLogger(__name__)


def refresh_votehub(cache_dir: Path) -> None:
    with VoteHubClient(cache_dir=cache_dir) as client:
        for poll_type in (PollType.APPROVAL, PollType.GENERIC_BALLOT, PollType.HEAD_TO_HEAD):
            polls = client.fetch_polls(poll_type=poll_type)
            logger.info("VoteHub %s: %d polls", poll_type.value, len(polls))


def refresh_rcp(cache_dir: Path) -> None:
    with RCPClient(cache_dir=cache_dir) as client:
        for poll_type in (PollType.APPROVAL, PollType.GENERIC_BALLOT):
            try:
                polls = client.fetch_polls(poll_type=poll_type)
                logger.info("RCP %s: %d polls", poll_type.value, len(polls))
            except Exception as exc:
                logger.warning("RCP %s failed: %s", poll_type.value, exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and cache polling data.")
    parser.add_argument("--source", choices=["votehub", "rcp", "all"], default="votehub")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    cache_dir = settings.raw_data_dir
    logger.info("Writing cache to %s", cache_dir)

    if args.source in ("votehub", "all"):
        logger.info("Refreshing VoteHub...")
        refresh_votehub(cache_dir)

    if args.source in ("rcp", "all"):
        logger.info("Refreshing RCP...")
        refresh_rcp(cache_dir)

    logger.info("Refresh complete.")


if __name__ == "__main__":
    main()
