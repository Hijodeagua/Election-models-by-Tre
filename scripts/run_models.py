"""Run all available models and print a formatted snapshot to stdout.

Usage:
    python scripts/run_models.py                 # live fetch from VoteHub
    python scripts/run_models.py --offline       # disk cache only, no network
    python scripts/run_models.py --source rcp    # use RCP scraper instead
    python scripts/run_models.py --source csv    # force CSV fallback

Fallback chain (when not overridden by --source):
    1. VoteHub API (live or disk cache)
    2. VoteHub CSV export (disk)
    3. Silver Bulletin daily model estimate (bypasses engine — used as Bayesian prior)
    4. Hand-curated CSVs in data/fallback/

Pollster weighting: hybrid quality score combining RCP historical accuracy (50%),
Silver Bulletin ratings (30%), and VoteHub grade from CSV (20%).

Model: Bayesian shrinkage — at ~14 recent polls the prior (Silver Bulletin) contributes
~30% and raw polls contribute ~70%. Prior fades naturally as poll count grows.
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
from src.data.pollster_ratings import build_ratings_dict, hybrid_quality
from src.data.rcp import RCPClient
from src.data.silverb_csv import SilverBulletinApprovalLoader, SilverBulletinGenericBallotLoader
from src.data.votehub import VoteHubClient
from src.data.votehub_csv import VoteHubCsvLoader
from src.models.approval import PresidentialApprovalModel
from src.models.bayesian import bayesian_blend_approval, bayesian_blend_generic_ballot
from src.models.generic_ballot import GenericBallotModel
from src.models.polling_average import PollingAverageEngine
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


# ── Pollster ratings ──────────────────────────────────────────────────────────

def _build_engine_from_polls(polls: list[Poll]) -> PollingAverageEngine:
    """Build a PollingAverageEngine with hybrid pollster ratings extracted from polls."""
    grade_map: dict[str, str] = {}
    for p in polls:
        if p.pollster not in grade_map:
            grade_map[p.pollster] = p.raw.get("grade", "") if p.raw else ""
    ratings = build_ratings_dict(list(grade_map.keys()))
    for name, grade in grade_map.items():
        if grade:
            ratings[name] = hybrid_quality(name, grade)
    return PollingAverageEngine(pollster_ratings=ratings)


# ── Output helpers ─────────────────────────────────────────────────────────────

def _section(title: str) -> None:
    print(f"\n{_DIVIDER}\n  {title}\n{_DIVIDER}")


def _ci(bounds: tuple[float, float] | None) -> str:
    return f"  [{bounds[0]:.1f}–{bounds[1]:.1f}]" if bounds else ""


def _provenance(label: str) -> None:
    print(f"  [data: {label}]")


def _blend_note(alpha: float | None, beta: float | None, n_polls: int) -> str:
    if alpha is None:
        return "TRACKER — polling average only"
    return (
        f"HYBRID  ·  {alpha:.0%} polls (N={n_polls}, hybrid-weighted)"
        f"  ·  {beta:.0%} Silver Bulletin prior"
    )


def _print_approval(snap, label: str, alpha: float | None = None, beta: float | None = None) -> None:
    _section(f"PRESIDENTIAL APPROVAL  ·  {snap.as_of}  ·  N={snap.num_polls}")
    print(f"  Approve     {snap.approve:5.1f}%{_ci(snap.ci_approve)}")
    print(f"  Disapprove  {snap.disapprove:5.1f}%{_ci(snap.ci_disapprove)}")
    sign = "+" if snap.net_approval > 0 else ""
    print(f"  Net         {sign}{snap.net_approval:.1f}")
    print(f"  [{_blend_note(alpha, beta, snap.num_polls)}]")
    _provenance(label)


def _print_generic_ballot(snap, label: str, alpha: float | None = None, beta: float | None = None) -> None:
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
    print(f"  [{_blend_note(alpha, beta, snap.num_polls)}]")
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

    # Silver Bulletin is always loaded as the Bayesian prior (independent of source)
    sb_approval_snap = None
    sb_gb_snap = None
    sb_approval_path = fallback_dir / "silverb_approval.csv"
    sb_gb_path = fallback_dir / "silverb_generic_ballot.csv"
    if sb_approval_path.exists():
        try:
            sb_approval_snap = SilverBulletinApprovalLoader().load(sb_approval_path)
        except Exception as exc:
            logging.warning("Silver Bulletin approval CSV load failed: %s", exc)
    if sb_gb_path.exists():
        try:
            sb_gb_snap = SilverBulletinGenericBallotLoader().load(sb_gb_path)
        except Exception as exc:
            logging.warning("Silver Bulletin generic ballot CSV load failed: %s", exc)

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

        # If no raw polls at all, use SB as label; otherwise polls label stands
        if not approval_polls:
            if sb_approval_snap:
                approval_label = _SB_LABEL
            else:
                approval_polls, approval_meta = csv_source.load(PollType.APPROVAL)

        if not gb_polls:
            if sb_gb_snap:
                gb_label = _SB_LABEL
            else:
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
    print(
        f"  Polls loaded: {total} total"
        f"  (approval={len(approval_polls)}, generic ballot={len(gb_polls)}, senate={len(senate_polls)})"
    )

    # Build hybrid-weighted engines from each poll set's embedded grades
    approval_engine = _build_engine_from_polls(approval_polls) if approval_polls else PollingAverageEngine()
    gb_engine = _build_engine_from_polls(gb_polls) if gb_polls else PollingAverageEngine()

    # Presidential approval — hybrid engine + Bayesian shrinkage onto SB prior
    poll_snap = PresidentialApprovalModel(engine=approval_engine).current_approval(approval_polls)
    blended_approval, alpha_a, beta_a = bayesian_blend_approval(poll_snap, sb_approval_snap)
    if blended_approval:
        a_label = f"{approval_label}  +  {_SB_LABEL}" if (poll_snap and sb_approval_snap) else approval_label
        _print_approval(
            blended_approval, a_label,
            alpha=alpha_a if (poll_snap and sb_approval_snap) else None,
            beta=beta_a if (poll_snap and sb_approval_snap) else None,
        )
    else:
        _section("PRESIDENTIAL APPROVAL")
        print(f"  No estimate — need ≥3 polls, got {len(approval_polls)}")
        _provenance(approval_label)

    # Generic ballot — hybrid engine + Bayesian shrinkage onto SB prior
    poll_gb_snap = GenericBallotModel(engine=gb_engine).current_ballot(gb_polls)
    blended_gb, alpha_g, beta_g = bayesian_blend_generic_ballot(poll_gb_snap, sb_gb_snap)
    if blended_gb:
        g_label = f"{gb_label}  +  {_SB_LABEL}" if (poll_gb_snap and sb_gb_snap) else gb_label
        _print_generic_ballot(
            blended_gb, g_label,
            alpha=alpha_g if (poll_gb_snap and sb_gb_snap) else None,
            beta=beta_g if (poll_gb_snap and sb_gb_snap) else None,
        )
    else:
        _section("GENERIC BALLOT")
        print(f"  No estimate — need ≥3 polls, got {len(gb_polls)}")
        _provenance(gb_label)

    states = _detect_senate_states(senate_polls)
    senate_engine = _build_engine_from_polls(senate_polls) if senate_polls else PollingAverageEngine()
    races = [SenateModel(engine=senate_engine).race_average(senate_polls, state) for state in states]
    _print_senate(races, senate_label)

    print()


if __name__ == "__main__":
    main()
