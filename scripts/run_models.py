"""Run all available models and print a formatted snapshot to stdout.

Usage:
    python scripts/run_models.py                 # live fetch from VoteHub
    python scripts/run_models.py --offline       # disk cache only, no network
    python scripts/run_models.py --source rcp    # use RCP scraper instead
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings
from src.data.base import Poll, PollType
from src.data.rcp import RCPClient
from src.data.votehub import VoteHubClient
from src.models.approval import PresidentialApprovalModel
from src.models.generic_ballot import GenericBallotModel
from src.models.senate import SenateModel

_DIVIDER = "─" * 62

# US state names used to detect Senate races in poll subjects
_US_STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
    "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "West Virginia", "Wisconsin", "Wyoming",
]


# ── Output helpers ────────────────────────────────────────────────────────────

def _section(title: str) -> None:
    print(f"\n{_DIVIDER}\n  {title}\n{_DIVIDER}")


def _ci(bounds: tuple[float, float] | None) -> str:
    return f"  [{bounds[0]:.1f}–{bounds[1]:.1f}]" if bounds else ""


def _print_approval(snap) -> None:
    _section(f"PRESIDENTIAL APPROVAL  ·  {snap.as_of}  ·  N={snap.num_polls}")
    print(f"  Approve     {snap.approve:5.1f}%{_ci(snap.ci_approve)}")
    print(f"  Disapprove  {snap.disapprove:5.1f}%{_ci(snap.ci_disapprove)}")
    sign = "+" if snap.net_approval > 0 else ""
    print(f"  Net         {sign}{snap.net_approval:.1f}")
    print(f"  [TRACKER — polling average only]")


def _print_generic_ballot(snap) -> None:
    _section(f"GENERIC BALLOT  ·  {snap.as_of}  ·  N={snap.num_polls}")
    print(f"  Democrat    {snap.dem_pct:5.1f}%{_ci(snap.ci_dem)}")
    print(f"  Republican  {snap.rep_pct:5.1f}%{_ci(snap.ci_rep)}")
    m = snap.margin
    leader = "D" if m >= 0 else "R"
    print(f"  Margin      {leader}+{abs(m):.1f}")
    if snap.estimated_dem_seats is not None:
        print(
            f"  Est. seats  D {snap.estimated_dem_seats} / R {snap.estimated_rep_seats}"
            "  [illustrative — not a probability]"
        )
    print(f"  [TRACKER — polling average only]")


def _print_senate(races: list) -> None:
    active = [r for r in races if r.num_polls > 0]
    if not active:
        _section("SENATE RACES")
        print("  No Senate polls found in fetched data.")
        return

    _section(f"SENATE RACES  ·  {active[0].as_of}  ·  {len(active)} races with data")
    for race in sorted(active, key=lambda r: r.state):
        top = sorted(race.candidates.items(), key=lambda x: x[1], reverse=True)
        cands = "  ".join(f"{name}: {pct:.1f}%" for name, pct in top[:2])
        margin_str = f"  margin {race.margin:+.1f}" if race.margin is not None else ""
        print(f"  {race.state:<22} {cands}  N={race.num_polls}{margin_str}")
    print(f"  [TRACKER — polling average only]")


# ── Data fetching ─────────────────────────────────────────────────────────────

def _fetch_votehub(cache_dir: Path, offline: bool) -> dict[str, list[Poll]]:
    result: dict[str, list[Poll]] = {}
    try:
        with VoteHubClient(cache_dir=cache_dir) as client:
            # In offline mode the client will hit disk cache; if no cache exists
            # the HTTP call will fail and we fall through to the except block.
            if offline:
                client.timeout = 0.001  # effectively disables live calls
            result["approval"] = client.fetch_polls(poll_type=PollType.APPROVAL)
            result["generic_ballot"] = client.fetch_polls(poll_type=PollType.GENERIC_BALLOT)
            result["senate"] = client.fetch_polls(poll_type=PollType.HEAD_TO_HEAD)
    except Exception as exc:
        if offline:
            logging.warning("Offline mode: no cached VoteHub data found (%s)", exc)
        else:
            logging.warning("VoteHub fetch failed: %s", exc)
    return result


def _fetch_rcp(cache_dir: Path) -> dict[str, list[Poll]]:
    result: dict[str, list[Poll]] = {}
    try:
        with RCPClient(cache_dir=cache_dir) as client:
            result["approval"] = client.fetch_polls(poll_type=PollType.APPROVAL)
            result["generic_ballot"] = client.fetch_polls(poll_type=PollType.GENERIC_BALLOT)
    except Exception as exc:
        logging.warning("RCP fetch failed: %s", exc)
    return result


def _detect_senate_states(senate_polls: list[Poll]) -> list[str]:
    """Return state names that appear in any HEAD_TO_HEAD poll subject."""
    h2h = [p for p in senate_polls if p.poll_type == PollType.HEAD_TO_HEAD]
    return [s for s in _US_STATES if any(s.lower() in p.subject.lower() for p in h2h)]


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Print current model snapshots.")
    parser.add_argument(
        "--offline", action="store_true",
        help="Use disk cache only. Run once live first to populate the cache.",
    )
    parser.add_argument(
        "--source", choices=["votehub", "rcp"], default="votehub",
        help="Primary data source (default: votehub).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    cache_dir = settings.raw_data_dir

    print(f"\nElection Oracle — {date.today()}")
    print("=" * 62)
    if args.offline:
        print("  [offline mode — reading from disk cache]")

    # Fetch
    if args.source == "rcp":
        polls = _fetch_rcp(cache_dir)
    else:
        polls = _fetch_votehub(cache_dir, offline=args.offline)
        # RCP fallback for approval + generic ballot if VoteHub came back empty
        if not polls.get("approval") and not polls.get("generic_ballot") and not args.offline:
            logging.info("VoteHub empty — trying RCP for approval + generic ballot")
            rcp = _fetch_rcp(cache_dir)
            polls.setdefault("approval", rcp.get("approval", []))
            polls.setdefault("generic_ballot", rcp.get("generic_ballot", []))

    approval_polls = polls.get("approval", [])
    gb_polls = polls.get("generic_ballot", [])
    senate_polls = polls.get("senate", [])

    total = len(approval_polls) + len(gb_polls) + len(senate_polls)
    print(f"  Polls loaded: {total} total"
          f"  (approval={len(approval_polls)}, generic ballot={len(gb_polls)}, senate H2H={len(senate_polls)})")

    # Approval
    approval_snap = PresidentialApprovalModel().current_approval(approval_polls)
    if approval_snap:
        _print_approval(approval_snap)
    else:
        _section("PRESIDENTIAL APPROVAL")
        print(f"  No estimate — need ≥3 polls, got {len(approval_polls)}")

    # Generic ballot
    gb_snap = GenericBallotModel().current_ballot(gb_polls)
    if gb_snap:
        _print_generic_ballot(gb_snap)
    else:
        _section("GENERIC BALLOT")
        print(f"  No estimate — need ≥3 polls, got {len(gb_polls)}")

    # Senate
    states = _detect_senate_states(senate_polls)
    senate_model = SenateModel()
    races = [senate_model.race_average(senate_polls, state) for state in states]
    _print_senate(races)

    print()


if __name__ == "__main__":
    main()
