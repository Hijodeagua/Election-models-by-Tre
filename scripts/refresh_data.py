"""Pull fresh data from all configured sources and update data/fallback/.

Run this before scripts/run_models.py to get up-to-date polls.

Usage:
    python scripts/refresh_data.py              # all sources
    python scripts/refresh_data.py --source rcp # one source only
    python scripts/refresh_data.py --dry-run    # show what would be fetched

Sources:
    votehub     — VoteHub API (free, no key required)
    rcp         — RealClearPolling scraper
    silverb     — Silver Bulletin model CSV download

Outputs written to data/fallback/:
    votehub_approval.csv
    votehub_generic_ballot.csv
    silverb_approval.csv          (if download succeeds)
    silverb_generic_ballot.csv    (if download succeeds)
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings
from src.data.base import Poll, PollType
from src.data.rcp import RCPClient
from src.data.silverb_download import SilverBulletinDownloader
from src.data.votehub import VoteHubClient

logger = logging.getLogger(__name__)

FALLBACK_DIR = Path(__file__).resolve().parent.parent / "data" / "fallback"


# ── CSV serialisation ────────────────────────────────────────────────────────

_VH_COLUMNS = [
    "Date Range", "Grade", "Pollster", "Subject", "Sponsor", "Sample Size",
    "Sample Type", "Population", "Weight",
    "Leading Result", "Leading %", "Trailing Result", "Trailing %", "Spread",
]
# Note: "Subject" was added (Fix 4). VoteHubCsvLoader falls back to a default
# subject when the column is absent, so existing committed CSVs without it
# continue to load. Senate CSVs require this column to be regenerated for
# state-detection (publish.py --chart senate) to find any races.


def _polls_to_votehub_csv(polls: list[Poll]) -> str:
    """Serialise Poll objects to VoteHub-style wide CSV for the fallback file."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_VH_COLUMNS)
    for poll in sorted(polls, key=lambda p: p.end_date, reverse=True):
        answers = sorted(poll.answers, key=lambda a: a.pct or 0, reverse=True)
        leading = answers[0] if answers else None
        trailing = answers[1] if len(answers) > 1 else None

        # Build "Apr. 29-May. 5" style date range
        s, e = poll.start_date, poll.end_date
        if s.month == e.month:
            date_range = f"{s.strftime('%b.')} {s.day}-{e.day}"
        else:
            date_range = f"{s.strftime('%b.')} {s.day}-{e.strftime('%b.')} {e.day}"

        spread = ""
        if leading and trailing and leading.pct is not None and trailing.pct is not None:
            spread = f"{leading.pct - trailing.pct:.1f}"

        pop = ""
        if poll.population:
            pop = poll.population.value.lower()[:2]

        grade = (poll.raw or {}).get("grade", "")

        w.writerow([
            date_range, grade, poll.pollster,
            poll.subject or "",
            "/".join(poll.sponsors) if poll.sponsors else "",
            poll.sample_size or "", "", pop, "",
            leading.choice if leading else "",
            f"{leading.pct:.0f}%" if leading and leading.pct is not None else "",
            trailing.choice if trailing else "",
            f"{trailing.pct:.0f}%" if trailing and trailing.pct is not None else "",
            spread,
        ])
    return buf.getvalue()


# ── Source fetchers ──────────────────────────────────────────────────────────

def _refresh_votehub(dry_run: bool = False) -> None:
    logger.info("=== VoteHub ===")
    with VoteHubClient(cache_dir=settings.raw_data_dir) as client:
        for poll_type, filename in [
            (PollType.APPROVAL, "votehub_approval.csv"),
            (PollType.GENERIC_BALLOT, "votehub_generic_ballot.csv"),
            (PollType.HEAD_TO_HEAD, "votehub_senate.csv"),
        ]:
            label = poll_type.value.replace("_", " ")
            try:
                polls = client.fetch_polls(poll_type=poll_type)
                logger.info("  %s: %d polls", label, len(polls))
                if not dry_run and polls:
                    dest = FALLBACK_DIR / filename
                    dest.write_text(_polls_to_votehub_csv(polls), encoding="utf-8")
                    logger.info("  → %s", dest.name)
            except Exception as exc:
                logger.warning("  %s failed: %s", label, exc)


def _refresh_rcp(dry_run: bool = False) -> None:
    logger.info("=== RealClearPolling ===")
    with RCPClient(cache_dir=settings.raw_data_dir) as client:
        for poll_type, filename, subject in [
            (PollType.APPROVAL, "rcp_approval.csv", "Trump"),
            (PollType.GENERIC_BALLOT, "rcp_generic_ballot.csv", None),
        ]:
            label = poll_type.value.replace("_", " ")
            try:
                polls = client.fetch_polls(poll_type=poll_type, subject=subject)
                logger.info("  %s: %d polls", label, len(polls))
                if not dry_run and polls:
                    dest = FALLBACK_DIR / filename
                    dest.write_text(_polls_to_votehub_csv(polls), encoding="utf-8")
                    logger.info("  → %s", dest.name)
            except Exception as exc:
                logger.warning("  %s failed: %s", label, exc)


def _refresh_silverb(dry_run: bool = False) -> None:
    logger.info("=== Silver Bulletin ===")
    if dry_run:
        logger.info("  (dry run — would download approval + generic ballot CSVs)")
        return
    with SilverBulletinDownloader(fallback_dir=FALLBACK_DIR) as dl:
        for name, ok in dl.refresh_all().items():
            logger.info("  %s: %s", name, "✓ updated" if ok else "✗ kept existing file")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh all polling data sources.")
    parser.add_argument(
        "--source", choices=["votehub", "rcp", "silverb", "all"], default="all",
        help="Which source to refresh (default: all).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be fetched without writing files.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    FALLBACK_DIR.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        logger.info("DRY RUN — no files will be written\n")

    if args.source in ("all", "votehub"):
        _refresh_votehub(dry_run=args.dry_run)
    if args.source in ("all", "rcp"):
        _refresh_rcp(dry_run=args.dry_run)
    if args.source in ("all", "silverb"):
        _refresh_silverb(dry_run=args.dry_run)

    if not args.dry_run:
        logger.info("\nDone. Run: python scripts/run_models.py --offline")


if __name__ == "__main__":
    main()
