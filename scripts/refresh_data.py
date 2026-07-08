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
    markets     — Polymarket + Kalshi prediction-market odds

Outputs written to data/fallback/:
    votehub_approval.csv
    votehub_generic_ballot.csv
    silverb_approval.csv          (if download succeeds)
    silverb_generic_ballot.csv    (if download succeeds)
    market_odds.csv               (if at least one market fetch succeeds)
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
from src.data.wikipedia_senate import WikipediaSenateSource

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

# If the newest poll in a primary (VoteHub) feed is older than this, top the
# feed up from Wikipedia's national polling articles. VoteHub's approval and
# generic-ballot feeds stalled for 10+ days in July 2026 while returning
# HTTP 200 the whole time — a silent failure this guard turns loud and
# self-healing. Senate already sources from Wikipedia directly.
STALE_FALLBACK_HOURS = 72


def _wikipedia_topup(
    polls: list[Poll], poll_type: PollType, label: str
) -> list[Poll]:
    """When the primary feed is stale, append newer polls from Wikipedia.

    Best-effort: any failure returns the polls unchanged.
    """
    from datetime import date, timedelta

    from src.data.wikipedia_national import WikipediaNationalSource, polls_newer_than

    if poll_type not in (PollType.APPROVAL, PollType.GENERIC_BALLOT) or not polls:
        return polls
    newest = max(p.end_date for p in polls)
    age_hours = (date.today() - newest).days * 24
    if age_hours <= STALE_FALLBACK_HOURS:
        return polls

    logger.warning(
        "  %s: newest primary poll is %s (>%dh old) — trying Wikipedia fallback",
        label, newest, STALE_FALLBACK_HOURS,
    )
    try:
        with WikipediaNationalSource(cache_dir=settings.raw_data_dir) as src:
            wiki = src.fetch_polls(poll_type=poll_type)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("  %s: Wikipedia fallback failed (%s)", label, exc)
        return polls
    fresh = polls_newer_than(wiki, newest)
    # Only trust the fallback for genuinely recent polls — stale-on-stale
    # (Wikipedia also behind) adds nothing.
    fresh = polls_newer_than(fresh, date.today() - timedelta(days=45))
    if fresh:
        logger.info(
            "  %s: +%d Wikipedia polls newer than %s (through %s)",
            label, len(fresh), newest, max(p.end_date for p in fresh),
        )
    else:
        logger.warning("  %s: Wikipedia had nothing newer either", label)
    return polls + fresh


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
                if not dry_run:
                    polls = _wikipedia_topup(polls, poll_type, label)
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


def _refresh_markets(dry_run: bool = False) -> None:
    """Fetch Polymarket + Kalshi odds for the configured Senate races.

    Best-effort: only overwrites market_odds.csv when at least one source
    returns data, so the committed snapshot survives network failures.
    """
    logger.info("=== Prediction markets (Polymarket / Kalshi) ===")
    from src.data.markets import (
        SENATE_CONTROL_RACE,
        KalshiClient,
        MarketOdds,
        PolymarketClient,
        write_market_odds_csv,
    )
    from src.models.senate_simulation import load_cycle_config

    cycle = load_cycle_config()
    polymarket = PolymarketClient()
    kalshi = KalshiClient()
    collected: list[MarketOdds] = []

    for entry in cycle["competitive_races"]:
        state, race, abbr = entry["state"], entry["race"], entry.get("abbr", "")
        if dry_run:
            logger.info("  (dry run — would fetch %s)", race)
            continue
        pm = polymarket.fetch_markets(
            f"{state} Senate 2026", race=race,
            required_tokens=(state.lower(), "senate"),
        )
        ks = (
            kalshi.fetch_race_odds(
                abbr,
                race=race,
                dem_candidate=entry.get("dem_candidate"),
                rep_candidate=entry.get("rep_candidate"),
            )
            if abbr
            else []
        )
        logger.info("  %s: polymarket=%d kalshi=%d", race, len(pm), len(ks))
        collected.extend(pm)
        collected.extend(ks)

    if not dry_run:
        pm = polymarket.fetch_markets(
            "Senate control 2026", race=SENATE_CONTROL_RACE,
            required_tokens=("senate",),
        )
        ks = kalshi.fetch_control_odds(race=SENATE_CONTROL_RACE)
        logger.info("  %s: polymarket=%d kalshi=%d", SENATE_CONTROL_RACE, len(pm), len(ks))
        collected.extend(pm)
        collected.extend(ks)

    if not dry_run:
        if collected:
            dest = FALLBACK_DIR / "market_odds.csv"
            write_market_odds_csv(collected, dest)
            logger.info("  → %s (%d rows)", dest.name, len(collected))
        else:
            logger.warning("  no market data fetched — keeping existing market_odds.csv")


def _refresh_silverb(dry_run: bool = False) -> None:
    logger.info("=== Silver Bulletin ===")
    # Silver Bulletin's model CSVs are paywalled — there is no free public URL.
    # Skip entirely unless the operator supplies real URLs via env vars, instead
    # of hammering a dead default and logging a DNS error every run.
    approval_url = getattr(settings, "silverb_approval_csv_url", "") or ""
    gb_url = getattr(settings, "silverb_gb_csv_url", "") or ""
    if not approval_url and not gb_url:
        logger.info(
            "  skipped — set SILVERB_APPROVAL_CSV_URL / SILVERB_GB_CSV_URL to enable "
            "(data is subscriber-only; the comparison line uses the committed snapshot)."
        )
        return
    if dry_run:
        logger.info("  (dry run — would download approval + generic ballot CSVs)")
        return
    with SilverBulletinDownloader(fallback_dir=FALLBACK_DIR) as dl:
        for name, ok in dl.refresh_all().items():
            logger.info("  %s: %s", name, "✓ updated" if ok else "✗ kept existing file")


def _refresh_wikipedia_senate(dry_run: bool = False) -> None:
    """Scrape per-race Senate polls from Wikipedia → votehub_senate.csv.

    VoteHub exposes no head-to-head Senate polls, so without this the Senate
    tracker runs on the hand-curated fallback. Best-effort: only overwrites the
    CSV when we parse at least one real poll, so a Wikipedia layout change or
    network failure leaves the committed snapshot in place.
    """
    from src.models.senate_simulation import load_cycle_config

    logger.info("=== Wikipedia (Senate head-to-head) ===")
    cycle = load_cycle_config()
    all_polls: list[Poll] = []
    with WikipediaSenateSource(cache_dir=settings.raw_data_dir) as src:
        for entry in cycle["competitive_races"]:
            if dry_run:
                logger.info("  (dry run — would fetch %s)", entry["race"])
                continue
            polls = src.fetch_race(
                state=entry["state"],
                race=entry["race"],
                dem_candidate=entry["dem_candidate"],
                rep_candidate=entry["rep_candidate"],
                article=entry.get("wikipedia"),
            )
            all_polls.extend(polls)

    if dry_run:
        return
    if all_polls:
        dest = FALLBACK_DIR / "votehub_senate.csv"
        dest.write_text(_polls_to_votehub_csv(all_polls), encoding="utf-8")
        logger.info("  → %s (%d polls across %d races)", dest.name, len(all_polls),
                    len({p.subject for p in all_polls}))
    else:
        logger.warning(
            "  no Senate polls parsed — keeping existing senate fallback CSV. "
            "(If this persists, a Wikipedia table layout likely changed.)"
        )


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh all polling data sources.")
    parser.add_argument(
        "--source",
        choices=["votehub", "rcp", "silverb", "markets", "wikipedia", "all"],
        default="all",
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
    if args.source in ("all", "wikipedia"):
        _refresh_wikipedia_senate(dry_run=args.dry_run)
    if args.source in ("all", "rcp"):
        _refresh_rcp(dry_run=args.dry_run)
    if args.source in ("all", "silverb"):
        _refresh_silverb(dry_run=args.dry_run)
    if args.source in ("all", "markets"):
        _refresh_markets(dry_run=args.dry_run)

    if not args.dry_run:
        logger.info("\nDone. Run: python scripts/run_models.py --offline")


if __name__ == "__main__":
    main()
