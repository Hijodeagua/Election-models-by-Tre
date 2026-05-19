"""Run all available models and print a formatted snapshot to stdout.

Usage:
    python scripts/run_models.py                 # live fetch from VoteHub
    python scripts/run_models.py --offline       # disk cache only, no network
    python scripts/run_models.py --source rcp    # use RCP scraper instead
    python scripts/run_models.py --source csv    # force CSV fallback

Fallback chain (when not overridden by --source):
    1. VoteHub API (live or disk cache)
    2. RCP scraper
    3. Local CSVs in data/fallback/  (approval.csv, generic_ballot.csv, senate.csv)

Every section prints a [data: ...] provenance line so it's always clear
what was used and when it was pulled.
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
from src.data.csv_source import CsvFallbackSource, FallbackMeta
from src.data.rcp import RCPClient
from src.data.silverb_csv import SilverBulletinApprovalLoader, SilverBulletinGenericBallotLoader
from src.data.votehub import VoteHubClient
from src.data.votehub_csv import VoteHubCsvLoader
from src.models.approval import PresidentialApprovalModel
from src.models.generic_ballot import GenericBallotModel
from src.models.senate import SenateModel

_DIVIDER = "─" * 62

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

_LIVE_LABEL = "VoteHub API  ·  live"
_RCP_LABEL = "RealClearPolling  ·  scraped"
_VH_CSV_LABEL = "VoteHub CSV  ·  disk"
_SB_LABEL = "Silver Bulletin model  ·  disk"


# ── Output helpers ─────────────────────────────────────────────────────────────

def _section(title: str) -> None:
    print(f"\n{_DIVIDER}\n  {title}\n{_DIVIDER}")


def _ci(bounds: tuple[float, float] | None) -> str:
    return f"  [{bounds[0]:.1f}–{bounds[1]:.1f}]" if bounds else ""


def _provenance(label: str) -> None:
    print(f"  [data: {label}]")


def _print_approval(snap, label: str) -> None:
    _section(f"PRESIDENTIAL APPROVAL  ·  {snap.as_of}  ·  N={snap.num_polls}")
    print(f"  Approve     {snap.approve:5.1f}%{_ci(snap.ci_approve)}")
    print(f"  Disapprove  {snap.disapprove:5.1f}%{_ci(snap.ci_disapprove)}")
    sign = "+" if snap.net_approval > 0 else ""
    print(f"  Net         {sign}{snap.net_approval:.1f}")
    print(f"  [TRACKER — polling average only]")
    _provenance(label)


def _print_generic_ballot(snap, label: str) -> None:
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
    _provenance(label)


def _print_senate(races: list, label: str) -> None:
    active = [r for r in races if r.num_polls > 0]
    if not active:
        _section("SENATE RACES")
        print("  No Senate polls found in fetched data.")
        _provenance(label)
        return

    _section(f"SENATE RACES  ·  {active[0].as_of}  ·  {len(active)} races with data")
    for race in sorted(active, key=lambda r: r.state):
        top = sorted(race.candidates.items(), key=lambda x: x[1], reverse=True)
        cands = "  ".join(f"{name}: {pct:.1f}%" for name, pct in top[:2])
        margin_str = f"  margin {race.margin:+.1f}" if race.margin is not None else ""
        print(f"  {race.state:<22} {cands}  N={race.num_polls}{margin_str}")
    print(f"  [TRACKER — polling average only]")
    _provenance(label)


# ── Data fetching ──────────────────────────────────────────────────────────────

def _fetch_votehub(cache_dir: Path, offline: bool) -> dict[str, list[Poll]]:
    result: dict[str, list[Poll]] = {}
    try:
        with VoteHubClient(cache_dir=cache_dir) as client:
            if offline:
                client.timeout = 0.001
            result["approval"] = client.fetch_polls(poll_type=PollType.APPROVAL)
            result["generic_ballot"] = client.fetch_polls(poll_type=PollType.GENERIC_BALLOT)
            result["senate"] = client.fetch_polls(poll_type=PollType.HEAD_TO_HEAD)
    except Exception as exc:
        if offline:
            logging.warning("Offline: no VoteHub cache found (%s)", exc)
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
    h2h = [p for p in senate_polls if p.poll_type == PollType.HEAD_TO_HEAD]
    return [s for s in _US_STATES if any(s.lower() in p.subject.lower() for p in h2h)]


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Print current model snapshots.")
    parser.add_argument(
        "--offline", action="store_true",
        help="Read from disk cache only. Run live once first to populate it.",
    )
    parser.add_argument(
        "--source", choices=["votehub", "rcp", "csv"], default="votehub",
        help="Data source (default: votehub, with rcp→csv fallback chain).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    cache_dir = settings.raw_data_dir
    fallback_dir = Path(__file__).resolve().parent.parent / "data" / "fallback"
    csv_source = CsvFallbackSource(fallback_dir)

    print(f"\nElection Oracle — {date.today()}")
    print("=" * 62)

    approval_polls: list[Poll] = []
    gb_polls: list[Poll] = []
    senate_polls: list[Poll] = []
    approval_label = gb_label = senate_label = "no data"
    approval_meta: FallbackMeta | None = None
    gb_meta: FallbackMeta | None = None
    senate_meta: FallbackMeta | None = None

    # Silver Bulletin snapshots bypass the polling engine entirely
    sb_approval_snap = None
    sb_gb_snap = None

    if args.source == "csv":
        approval_polls, approval_meta = csv_source.load(PollType.APPROVAL)
        gb_polls, gb_meta = csv_source.load(PollType.GENERIC_BALLOT)
        senate_polls, senate_meta = csv_source.load(PollType.HEAD_TO_HEAD)
    else:
        if args.source == "rcp":
            live = _fetch_rcp(cache_dir)
            live_label = _RCP_LABEL
        else:
            live = _fetch_votehub(cache_dir, offline=args.offline)
            live_label = _LIVE_LABEL if not args.offline else "VoteHub  ·  disk cache"

        approval_polls = live.get("approval", [])
        gb_polls = live.get("generic_ballot", [])
        senate_polls = live.get("senate", [])

        # RCP fallback for approval + generic ballot
        if args.source == "votehub" and not args.offline:
            if not approval_polls or not gb_polls:
                rcp = _fetch_rcp(cache_dir)
                if not approval_polls:
                    approval_polls = rcp.get("approval", [])
                    live_label = _RCP_LABEL
                if not gb_polls:
                    gb_polls = rcp.get("generic_ballot", [])

        # VoteHub CSV fallback (raw polls → through engine)
        if not approval_polls:
            vh_approval_path = fallback_dir / "votehub_approval.csv"
            if vh_approval_path.exists():
                try:
                    approval_polls = VoteHubCsvLoader(PollType.APPROVAL).load(vh_approval_path)
                    approval_label = _VH_CSV_LABEL
                except Exception as exc:
                    logging.warning("VoteHub approval CSV load failed: %s", exc)

        if not gb_polls:
            vh_gb_path = fallback_dir / "votehub_generic_ballot.csv"
            if vh_gb_path.exists():
                try:
                    gb_polls = VoteHubCsvLoader(PollType.GENERIC_BALLOT).load(vh_gb_path)
                    gb_label = _VH_CSV_LABEL
                except Exception as exc:
                    logging.warning("VoteHub generic ballot CSV load failed: %s", exc)

        # Silver Bulletin CSV fallback (pre-aggregated — bypasses engine)
        sb_approval_path = fallback_dir / "silverb_approval.csv"
        sb_gb_path = fallback_dir / "silverb_generic_ballot.csv"

        if not approval_polls and sb_approval_path.exists():
            try:
                sb_approval_snap = SilverBulletinApprovalLoader().load(sb_approval_path)
                if sb_approval_snap:
                    approval_label = _SB_LABEL
            except Exception as exc:
                logging.warning("Silver Bulletin approval CSV load failed: %s", exc)

        if not gb_polls and sb_gb_path.exists():
            try:
                sb_gb_snap = SilverBulletinGenericBallotLoader().load(sb_gb_path)
                if sb_gb_snap:
                    gb_label = _SB_LABEL
            except Exception as exc:
                logging.warning("Silver Bulletin generic ballot CSV load failed: %s", exc)

        # Generic hand-curated CSV final fallback
        if not approval_polls and sb_approval_snap is None:
            approval_polls, approval_meta = csv_source.load(PollType.APPROVAL)

        if not gb_polls and sb_gb_snap is None:
            gb_polls, gb_meta = csv_source.load(PollType.GENERIC_BALLOT)

        if not approval_polls and not sb_approval_snap:
            approval_label = live_label if approval_label == "no data" else approval_label
        elif approval_polls and approval_label == "no data":
            approval_label = live_label

        if not gb_polls and not sb_gb_snap:
            gb_label = live_label if gb_label == "no data" else gb_label
        elif gb_polls and gb_label == "no data":
            gb_label = live_label

        if senate_polls:
            senate_label = live_label
        else:
            senate_polls, senate_meta = csv_source.load(PollType.HEAD_TO_HEAD)

    if approval_meta:
        approval_label = approval_meta.display()
    if gb_meta:
        gb_label = gb_meta.display()
    if senate_meta:
        senate_label = senate_meta.display()

    total = len(approval_polls) + len(gb_polls) + len(senate_polls)
    sb_note = ""
    if sb_approval_snap or sb_gb_snap:
        sb_note = "  (some sections use Silver Bulletin model estimates)"
    print(
        f"  Polls loaded: {total} total"
        f"  (approval={len(approval_polls)}, generic ballot={len(gb_polls)}, senate={len(senate_polls)})"
        + sb_note
    )

    if sb_approval_snap:
        _print_approval(sb_approval_snap, approval_label)
    else:
        snap = PresidentialApprovalModel().current_approval(approval_polls)
        if snap:
            _print_approval(snap, approval_label)
        else:
            _section("PRESIDENTIAL APPROVAL")
            print(f"  No estimate — need ≥3 polls, got {len(approval_polls)}")
            _provenance(approval_label)

    if sb_gb_snap:
        _print_generic_ballot(sb_gb_snap, gb_label)
    else:
        gb_snap = GenericBallotModel().current_ballot(gb_polls)
        if gb_snap:
            _print_generic_ballot(gb_snap, gb_label)
        else:
            _section("GENERIC BALLOT")
            print(f"  No estimate — need ≥3 polls, got {len(gb_polls)}")
            _provenance(gb_label)

    states = _detect_senate_states(senate_polls)
    races = [SenateModel().race_average(senate_polls, state) for state in states]
    _print_senate(races, senate_label)

    print()


if __name__ == "__main__":
    main()
