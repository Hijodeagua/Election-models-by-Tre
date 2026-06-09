"""Run models and publish charts to Datawrapper for Substack embedding.

Usage:
    python scripts/publish.py                     # publish all charts
    python scripts/publish.py --chart approval    # one chart only
    python scripts/publish.py --dry-run           # print CSVs, skip API calls

Prerequisites:
    1. Add DATAWRAPPER_API_TOKEN to .env
    2. Create charts in Datawrapper and add their IDs to .env:
         DW_CHART_APPROVAL_ID=xxxxx
         DW_CHART_GB_ID=xxxxx
         DW_CHART_SENATE_ID=xxxxx
         DW_CHART_HOUSE_EFFECTS_ID=xxxxx   (requires --state-space)
    3. Run scripts/refresh_data.py first to get current polls

Workflow:
    refresh_data.py  →  publish.py  →  Datawrapper  →  Substack embed
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.base import PollType
from src.data.csv_source import CsvFallbackSource
from src.data.datawrapper import ChartIds, DatawrapperClient
from src.data.pollster_ratings import hybrid_quality
from src.data.votehub_csv import VoteHubCsvLoader
from src.models.approval import PresidentialApprovalModel
from src.models.generic_ballot import GenericBallotModel
from src.models.polling_average import PollingAverageEngine
from src.models.senate import SenateModel

logger = logging.getLogger(__name__)

FALLBACK_DIR = Path(__file__).resolve().parent.parent / "data" / "fallback"


def _build_engine(polls):
    grades = {}
    for p in polls:
        grade = (p.raw or {}).get("grade", "")
        grades[p.pollster] = hybrid_quality(p.pollster, grade)
    return PollingAverageEngine(pollster_ratings=grades)


def _detect_states(polls):
    seen = set()
    return [
        p.subject
        for p in polls
        if p.subject and p.subject not in seen and not seen.add(p.subject)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish model outputs to Datawrapper.")
    parser.add_argument(
        "--chart",
        choices=["approval", "approval_pro", "generic_ballot", "senate", "house_effects", "all"],
        default="all",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print CSV, skip API.")
    parser.add_argument(
        "--trend-days", type=int, default=90,
        help="Days of trend history to include in trend charts (default: 90).",
    )
    parser.add_argument(
        "--state-space", action="store_true",
        help="Use state-space estimate for house_effects chart (~2 min).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # ── Load polls ───────────────────────────────────────────────────────────
    approval_polls, gb_polls, senate_polls = [], [], []

    vh_approval = FALLBACK_DIR / "votehub_approval.csv"
    vh_gb = FALLBACK_DIR / "votehub_generic_ballot.csv"
    vh_senate = FALLBACK_DIR / "votehub_senate.csv"

    if vh_approval.exists():
        approval_polls = VoteHubCsvLoader(PollType.APPROVAL).load(vh_approval)
    if vh_gb.exists():
        gb_polls = VoteHubCsvLoader(PollType.GENERIC_BALLOT).load(vh_gb)
    if vh_senate.exists():
        senate_polls = VoteHubCsvLoader(PollType.HEAD_TO_HEAD).load(vh_senate)

    # Fall back to hand-curated senate.csv if VoteHub senate file missing
    if not senate_polls:
        csv_source = CsvFallbackSource(FALLBACK_DIR)
        senate_polls, _ = csv_source.load(PollType.HEAD_TO_HEAD)

    if not approval_polls and not gb_polls:
        logger.error("No polls found. Run scripts/refresh_data.py first.")
        sys.exit(1)

    # ── Build engines ────────────────────────────────────────────────────────
    approval_engine = _build_engine(approval_polls) if approval_polls else PollingAverageEngine()
    gb_engine = _build_engine(gb_polls) if gb_polls else PollingAverageEngine()
    senate_engine = _build_engine(senate_polls) if senate_polls else PollingAverageEngine()

    approval_model = PresidentialApprovalModel(engine=approval_engine)
    gb_model = GenericBallotModel(engine=gb_engine)

    # ── Build chart data ─────────────────────────────────────────────────────
    chart_ids = ChartIds.from_settings()
    chart_data: dict[str, str] = {}

    run_approval = args.chart in ("all", "approval")
    run_approval_pro = args.chart in ("all", "approval_pro")
    run_gb = args.chart in ("all", "generic_ballot")
    run_senate = args.chart in ("all", "senate")
    run_he = args.chart in ("all", "house_effects")

    if run_approval and approval_polls:
        logger.info("Building approval trend (%d days)...", args.trend_days)
        end = date.today()
        start = end - timedelta(days=args.trend_days)
        snapshots = approval_model.approval_trend(approval_polls, start=start, end=end)
        if snapshots:
            chart_data["approval"] = DatawrapperClient.approval_trend_csv(snapshots)
            logger.info("  %d daily snapshots", len(snapshots))

    if run_approval_pro:
        sb_path = FALLBACK_DIR / "silverb_approval.csv"
        rcp_path = FALLBACK_DIR / "rcp_approval.csv"
        if sb_path.exists():
            logger.info("Building professional reference (%d days)...", args.trend_days)
            start = date.today() - timedelta(days=args.trend_days)
            csv_text = DatawrapperClient.approval_pro_consensus_csv(
                sb_path, rcp_csv_path=rcp_path, start_date=start
            )
            lines = csv_text.strip().splitlines()
            if len(lines) > 1:
                chart_data["approval_pro"] = csv_text
                logger.info("  %d daily snapshots", len(lines) - 1)

    if run_gb and gb_polls:
        logger.info("Building generic ballot trend (%d days)...", args.trend_days)
        end = date.today()
        start = end - timedelta(days=args.trend_days)
        snaps = []
        current = start
        while current <= end:
            result = gb_engine.compute_average(
                [p for p in gb_polls],
                as_of=current,
                choices=["Democrat", "Democratic", "Democrats", "Republican", "Republicans"],
            )
            if result.num_polls > 0:
                snaps.append(gb_model._result_to_snapshot(result))
            current += timedelta(days=1)
        if snaps:
            chart_data["generic_ballot"] = DatawrapperClient.generic_ballot_csv(snaps)
            logger.info("  %d daily snapshots", len(snaps))

    if run_senate and senate_polls:
        logger.info("Building senate snapshot...")
        states = _detect_states(senate_polls)
        races = [SenateModel(engine=senate_engine).race_average(senate_polls, s) for s in states]
        active = [r for r in races if r.num_polls > 0]
        if active:
            chart_data["senate"] = DatawrapperClient.senate_snapshot_csv(active)
            logger.info("  %d races", len(active))

    if run_he and args.state_space and approval_polls:
        logger.info("Running state-space model for house effects (~2 min)...")
        try:
            from src.models import state_space
            ss_result = state_space.fit(approval_polls, choice="Approve")
            if ss_result:
                chart_data["house_effects"] = DatawrapperClient.house_effects_csv(ss_result)
                logger.info("  %d pollsters with estimates", len(ss_result.pollsters))
        except Exception as exc:
            logger.warning("State-space failed: %s", exc)

    # ── Publish ──────────────────────────────────────────────────────────────
    if args.dry_run:
        for name, csv_text in chart_data.items():
            print(f"\n{'='*60}")
            print(f"Chart: {name}")
            print('='*60)
            lines = csv_text.strip().splitlines()
            print("\n".join(lines[:6]))
            if len(lines) > 6:
                print(f"  ... ({len(lines)-1} data rows total)")
        return

    if not chart_data:
        logger.warning("No chart data built — nothing to publish.")
        return

    _metadata = {
        "approval": DatawrapperClient.approval_metadata(),
        "approval_pro": DatawrapperClient.approval_pro_metadata(),
        "generic_ballot": DatawrapperClient.generic_ballot_metadata(),
        "senate": DatawrapperClient.senate_metadata(),
    }
    _id_map = {
        "approval": "approval_trend",
        "approval_pro": "approval_pro",
        "generic_ballot": "generic_ballot_trend",
        "senate": "senate_snapshot",
        "house_effects": "house_effects",
    }

    try:
        with DatawrapperClient() as dw:
            for name, csv_text in chart_data.items():
                chart_id = getattr(chart_ids, _id_map.get(name, name), "")
                if not chart_id:
                    logger.warning(
                        "No chart ID for '%s' — skipping. Set DW_CHART_%s_ID in .env",
                        name, name.upper(),
                    )
                    continue
                ok = dw.update_and_publish(chart_id, csv_text, metadata=_metadata.get(name))
                logger.info("  %s: %s", name, "✓ published" if ok else "✗ failed")
    except ValueError as exc:
        logger.error(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
