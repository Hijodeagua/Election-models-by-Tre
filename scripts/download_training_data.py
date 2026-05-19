"""Download all training data from public sources.

Fetches and caches:
- 538 archived polls (Senate, Governor) from GitHub
- MIT election results from Harvard Dataverse / MEDSL GitHub
- Silver Bulletin pollster ratings

Run this once before training. Data is cached in data/raw/ and
won't re-download on subsequent runs unless --force is passed.

Usage:
    python scripts/download_training_data.py
    python scripts/download_training_data.py --force
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download historical training data")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    parser.add_argument(
        "--sources", nargs="+",
        default=["538", "mit", "silver_bulletin"],
        choices=["538", "mit", "silver_bulletin"],
    )
    args = parser.parse_args()

    from config.settings import settings
    from src.data.fte_archive import FTEArchiveClient
    from src.data.mit_results import MITResultsClient
    from src.data.silver_bulletin import SilverBulletinClient

    if args.force:
        logger.info("Force mode: clearing existing cache")
        _clear_cache(settings.raw_data_dir)

    # ── 538 Polls ─────────────────────────────────────────────────────
    if "538" in args.sources:
        logger.info("=== Downloading 538 archived polls ===")
        with FTEArchiveClient() as fte:
            available = fte.discover_available_files()
            logger.info(f"Available 538 files: {available}")
            for office in ["senate", "governor"]:
                try:
                    polls = fte._fetch_polls(office)
                    logger.info(f"  {office}: {len(polls)} poll records")
                except Exception as e:
                    logger.warning(f"  {office}: FAILED — {e}")

    # ── MIT Results ───────────────────────────────────────────────────
    if "mit" in args.sources:
        logger.info("=== Downloading MIT election results ===")
        with MITResultsClient() as mit:
            for office in ["senate", "governor"]:
                try:
                    results = mit._fetch_results(office, min_year=2000)
                    logger.info(f"  {office}: {len(results)} race results")
                except Exception as e:
                    logger.warning(f"  {office}: FAILED — {e}")

    # ── Silver Bulletin Ratings ───────────────────────────────────────
    if "silver_bulletin" in args.sources:
        logger.info("=== Downloading Silver Bulletin pollster ratings ===")
        with SilverBulletinClient() as sb:
            ratings = sb.fetch_pollster_ratings(force_refresh=args.force)
            logger.info(f"  Got {len(ratings)} pollster ratings")

    logger.info("\nDownload complete. Run training with:")
    logger.info("  python scripts/train_parameters.py")


def _clear_cache(raw_dir: Path) -> None:
    for subdir in ["fte_archive", "mit_results", "silver_bulletin"]:
        path = raw_dir / subdir
        if path.exists():
            for f in path.glob("*"):
                f.unlink()
            logger.info(f"Cleared {path}")


if __name__ == "__main__":
    main()
