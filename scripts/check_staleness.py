"""Fail-loud staleness check for the polling feeds.

The refresh job used to be able to "succeed" for weeks while every feed sat
frozen (VoteHub returned HTTP 200 with the same stale payload each run, and
nothing measured data age). This script makes that state visible:

- prints each feed's newest poll date and age;
- emits GitHub Actions ``::warning::`` annotations for stale feeds;
- writes ``stale=<comma-list>`` to ``$GITHUB_OUTPUT`` (when set) so a
  workflow step can open an alert issue;
- ``--strict`` exits non-zero if anything is stale (for manual use — the
  scheduled workflow should keep publishing whatever it has).

Usage:
    python scripts/check_staleness.py               # warn only
    python scripts/check_staleness.py --strict      # exit 1 when stale
    python scripts/check_staleness.py --max-age-days 5
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.base import PollType
from src.data.votehub_csv import VoteHubCsvLoader
from src.data.wikipedia_senate import is_aggregate_pollster

FALLBACK_DIR = PROJECT_ROOT / "data" / "fallback"

FEEDS = [
    ("approval", PollType.APPROVAL, "votehub_approval.csv"),
    ("generic_ballot", PollType.GENERIC_BALLOT, "votehub_generic_ballot.csv"),
    ("senate", PollType.HEAD_TO_HEAD, "votehub_senate.csv"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Check polling feed freshness.")
    parser.add_argument(
        "--max-age-days", type=int, default=3,
        help="A feed is stale when its newest poll is older than this (default: 3).",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit non-zero when any feed is stale.",
    )
    args = parser.parse_args()

    today = date.today()
    stale: list[str] = []

    print(f"Feed freshness — {today} (threshold: {args.max_age_days} days)")
    for name, poll_type, filename in FEEDS:
        path = FALLBACK_DIR / filename
        if not path.exists():
            print(f"  {name:16} MISSING ({filename})")
            stale.append(name)
            continue
        try:
            polls = VoteHubCsvLoader(poll_type).load(path)
        except Exception as exc:
            print(f"  {name:16} UNREADABLE ({exc})")
            stale.append(name)
            continue
        # Ignore poll-of-polls / model rows: their wide "as-of" date ranges
        # carry a recent end date and mask a stalled feed (a RealClearPolitics
        # average dated through last week makes a feed with no real poll in
        # three weeks look fresh). Freshness must reflect genuine new polls.
        polls = [p for p in polls if not is_aggregate_pollster(p.pollster)]
        if not polls:
            print(f"  {name:16} EMPTY")
            stale.append(name)
            continue
        newest = max(p.end_date for p in polls)
        age = (today - newest).days
        flag = "STALE" if age > args.max_age_days else "ok"
        print(f"  {name:16} newest poll {newest}  ({age}d old)  {flag}")
        if age > args.max_age_days:
            stale.append(name)
            # GitHub Actions annotation — shows on the run summary page.
            print(
                f"::warning title=Stale polling feed::{name}: newest poll is "
                f"{age} days old ({newest}); threshold {args.max_age_days}d. "
                "Upstream source may have stalled."
            )

    # Hand the stale list to later workflow steps (issue creation).
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as fh:
            fh.write(f"stale={','.join(stale)}\n")

    if stale:
        print(f"\nStale feeds: {', '.join(stale)}")
        if args.strict:
            raise SystemExit(1)
    else:
        print("\nAll feeds fresh.")


if __name__ == "__main__":
    main()
