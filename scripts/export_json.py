"""Export tracker snapshots to static JSON for the web/ Next.js spoke.

Reuses the offline pipeline from run_models.py — same data-loading fallback
chain (curated CSV → VoteHub CSV) and the same model classes. No new model
code: it calls the existing PresidentialApprovalModel, GenericBallotModel and
SenateModel, then serialises their dataclass snapshots with dataclasses.asdict.

Heavy state-space / PyMC estimates are intentionally skipped — too slow for CI.
Everything here runs in offline mode with no API keys.

Outputs (web/public/data/):
    approval.json        — current reading + daily trend series with CI bands
    generic_ballot.json  — D/R margin, current reading + daily trend series
    senate.json          — per-race SenateRaceSnapshots
    meta.json            — last_updated, data tier, model versions

Usage:
    python scripts/export_json.py            # offline CSV pipeline (default)
    python scripts/export_json.py --trend-days 240
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Reuse helpers from the CLI entrypoint rather than re-implementing them.
from scripts.run_models import (
    _US_STATES,
    _build_engine_from_polls,
    _detect_senate_states,
)
from src.data.base import Poll, PollType
from src.data.csv_source import CsvFallbackSource
from src.data.votehub_csv import VoteHubCsvLoader
from src.models.approval import PresidentialApprovalModel
from src.models.generic_ballot import GenericBallotModel, GenericBallotSnapshot
from src.models.senate import SenateModel

FALLBACK_DIR = PROJECT_ROOT / "data" / "fallback"
OUTPUT_DIR = PROJECT_ROOT / "web" / "public" / "data"

# Maturity tier label shown in the UI — every output here is a TRACKER.
DATA_TIER = "tracker"

MODEL_VERSIONS = {
    "approval": "PresidentialApprovalModel (weighted polling average, Phase 2)",
    "generic_ballot": "GenericBallotModel (weighted polling average, Phase 2)",
    "senate": "SenateModel (per-race polling average)",
    "state_space": "skipped (opt-in only — too heavy for CI)",
}


class _JSONEncoder(json.JSONEncoder):
    """Serialise date/datetime and dataclasses transparently."""

    def default(self, o):  # noqa: D102
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            return dataclasses.asdict(o)
        return super().default(o)


# ── Data loading (offline CSV fallback chain) ──────────────────────────────────

def _load_polls(poll_type: PollType, votehub_filename: str) -> list[Poll]:
    """Curated CSV first, then the larger raw VoteHub CSV export. Offline-safe."""
    source = CsvFallbackSource(FALLBACK_DIR)
    polls, _meta = source.load(poll_type)
    if polls:
        return polls
    vh_path = FALLBACK_DIR / votehub_filename
    if vh_path.exists():
        try:
            return VoteHubCsvLoader(poll_type).load(vh_path)
        except Exception as exc:  # pragma: no cover - defensive
            logging.warning("%s load failed: %s", votehub_filename, exc)
    return []


# ── Serialisers ────────────────────────────────────────────────────────────────

def _approval_payload(polls: list[Poll], trend_days: int) -> dict:
    engine = _build_engine_from_polls(polls) if polls else None
    model = PresidentialApprovalModel(engine=engine) if engine else PresidentialApprovalModel()
    current = model.current_approval(polls)

    end = date.today()
    start = end - timedelta(days=trend_days)
    trend = model.approval_trend(polls, start=start, end=end, step_days=1)

    return {
        "current": current,
        "trend": trend,
        "num_polls": len(polls),
    }


def _generic_ballot_trend(
    model: GenericBallotModel,
    polls: list[Poll],
    start: date,
    end: date,
    step_days: int = 1,
) -> list[GenericBallotSnapshot]:
    """Daily generic-ballot snapshots — mirrors PresidentialApprovalModel.approval_trend."""
    gb_polls = [p for p in polls if p.poll_type == PollType.GENERIC_BALLOT]
    if not gb_polls:
        return []
    snapshots: list[GenericBallotSnapshot] = []
    current = start
    while current <= end:
        result = model.engine.compute_average(
            gb_polls,
            as_of=current,
            choices=[
                "Democrat", "Democratic", "Democrats",
                "Republican", "Republicans", "GOP",
            ],
        )
        if result.num_polls > 0:
            snapshots.append(model._result_to_snapshot(result))
        current += timedelta(days=step_days)
    return snapshots


def _generic_ballot_payload(polls: list[Poll], trend_days: int) -> dict:
    engine = _build_engine_from_polls(polls) if polls else None
    model = GenericBallotModel(engine=engine) if engine else GenericBallotModel()
    current = model.current_ballot(polls)

    end = date.today()
    start = end - timedelta(days=trend_days)
    trend = _generic_ballot_trend(model, polls, start=start, end=end)

    return {
        "current": current,
        "trend": trend,
        "num_polls": len(polls),
    }


def _senate_payload(polls: list[Poll]) -> dict:
    engine = _build_engine_from_polls(polls) if polls else None
    states = _detect_senate_states(polls) or _US_STATES
    model = SenateModel(engine=engine) if engine else SenateModel()
    races = [model.race_average(polls, state) for state in states]
    races = [r for r in races if r.num_polls > 0]
    races.sort(key=lambda r: r.state)
    return {"races": races, "num_races": len(races)}


def _write(name: str, payload: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, cls=_JSONEncoder, indent=2)
    print(f"  wrote {path.relative_to(PROJECT_ROOT)}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Export tracker JSON for the web spoke.")
    parser.add_argument(
        "--trend-days", type=int, default=240,
        help="Number of days of daily trend history to emit (default: 240).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    print(f"Exporting tracker JSON — {date.today()} (offline CSV pipeline)")

    approval_polls = _load_polls(PollType.APPROVAL, "votehub_approval.csv")
    gb_polls = _load_polls(PollType.GENERIC_BALLOT, "votehub_generic_ballot.csv")
    senate_polls = _load_polls(PollType.HEAD_TO_HEAD, "votehub_senate.csv")
    print(
        f"  polls loaded: approval={len(approval_polls)}, "
        f"generic_ballot={len(gb_polls)}, senate={len(senate_polls)}"
    )

    _write("approval.json", _approval_payload(approval_polls, args.trend_days))
    _write("generic_ballot.json", _generic_ballot_payload(gb_polls, args.trend_days))
    _write("senate.json", _senate_payload(senate_polls))

    meta = {
        "last_updated": datetime.now().astimezone().isoformat(),
        "data_tier": DATA_TIER,
        "label": "TRACKER — weighted polling averages only, not a forecast",
        "model_versions": MODEL_VERSIONS,
        "poll_counts": {
            "approval": len(approval_polls),
            "generic_ballot": len(gb_polls),
            "senate": len(senate_polls),
        },
    }
    _write("meta.json", meta)

    print("Done.")


if __name__ == "__main__":
    main()
