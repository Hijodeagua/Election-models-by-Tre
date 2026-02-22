"""Historical data backfill — populate historical election results for backtesting."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info("Historical backfill not yet implemented.")
    logger.info("This will populate data/historical/ with past election results.")


if __name__ == "__main__":
    main()
