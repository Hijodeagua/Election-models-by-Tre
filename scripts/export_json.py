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
from src.data.fiftyplusone import FiftyPlusOneApprovalCsvLoader
from src.data.markets import SENATE_CONTROL_RACE, MarketOddsCsvSource, odds_for_race
from src.data.silverb_csv import SilverBulletinApprovalLoader
from src.data.votehub_csv import VoteHubCsvLoader
from src.models.approval import PresidentialApprovalModel
from src.models.generic_ballot import (
    GENERIC_BALLOT_CHOICES,
    GenericBallotModel,
    GenericBallotSnapshot,
)
from src.models.senate import SenateModel
from src.models.senate_simulation import (
    RaceInput,
    SenateControlSimulator,
    load_cycle_config,
)
from src.models.vibes_adjustment import VibesAdjustedSenateModel, VibesCsvSource

FALLBACK_DIR = PROJECT_ROOT / "data" / "fallback"
OUTPUT_DIR = PROJECT_ROOT / "web" / "public" / "data"

# Maturity tier label shown in the UI — every output here is a TRACKER.
DATA_TIER = "tracker"

MODEL_VERSIONS = {
    "approval": "PresidentialApprovalModel (weighted polling average, Phase 2)",
    "generic_ballot": "GenericBallotModel (weighted polling average, Phase 2)",
    "senate": "SenateModel (per-race polling average) + vibes/market overlays",
    "senate_control": "SenateControlSimulator (1000-sim Monte Carlo NOWCAST)",
    "state_space": "skipped (opt-in only — too heavy for CI)",
}

# Fixed seed so the daily cron produces a stable simulation for a given
# polling snapshot (diffs in git stay meaningful).
SIMULATION_SEED = 20260101
NUM_SIMULATIONS = 1000


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
    """Prefer the full VoteHub CSV export (hundreds of polls, refreshed daily
    by the cron); fall back to the small hand-curated smoke-test CSV only when
    the export is missing or unreadable. Offline-safe either way."""
    vh_path = FALLBACK_DIR / votehub_filename
    if vh_path.exists():
        try:
            polls = VoteHubCsvLoader(poll_type).load(vh_path)
            if polls:
                return polls
        except Exception as exc:  # pragma: no cover - defensive
            logging.warning("%s load failed: %s", votehub_filename, exc)
    source = CsvFallbackSource(FALLBACK_DIR)
    polls, _meta = source.load(poll_type)
    return polls


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
            gb_polls, as_of=current, choices=GENERIC_BALLOT_CHOICES
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


def _votehub_unweighted_trend(
    polls: list[Poll], start: date, end: date, window_days: int = 14
) -> list[dict]:
    """Simple unweighted trailing mean of approval polls, one point per day.

    This is the "raw VoteHub polls" comparison series — no pollster quality,
    recency or population weighting, so divergence from our model shows what
    the weighting buys us.
    """
    points: list[dict] = []
    current = start
    while current <= end:
        window_lo = current - timedelta(days=window_days)
        approves: list[float] = []
        disapproves: list[float] = []
        for poll in polls:
            if not (window_lo < poll.midpoint_date <= current):
                continue
            for answer in poll.answers:
                choice = answer.choice.lower()
                if choice == "approve":
                    approves.append(answer.pct)
                elif choice == "disapprove":
                    disapproves.append(answer.pct)
        if approves and disapproves:
            approve = sum(approves) / len(approves)
            disapprove = sum(disapproves) / len(disapproves)
            points.append(
                {
                    "as_of": current,
                    "approve": round(approve, 2),
                    "disapprove": round(disapprove, 2),
                    "net": round(approve - disapprove, 2),
                    "num_polls": len(approves),
                }
            )
        current += timedelta(days=1)
    return points


def _approval_comparison_payload(
    approval_payload: dict, polls: list[Poll], trend_days: int
) -> dict:
    """Multi-model approval comparison for the homepage toggle chart."""
    end = date.today()
    start = end - timedelta(days=trend_days)

    ours = [
        {
            "as_of": s.as_of,
            "approve": s.approve,
            "disapprove": s.disapprove,
            "net": s.net_approval,
            "lo": s.ci_approve[0] if s.ci_approve else None,
            "hi": s.ci_approve[1] if s.ci_approve else None,
        }
        for s in approval_payload["trend"]
    ]

    silverb_series: list[dict] = []
    silverb_path = FALLBACK_DIR / "silverb_approval.csv"
    if silverb_path.exists():
        try:
            silverb_series = [
                {
                    "as_of": s.as_of,
                    "approve": round(s.approve, 2),
                    "disapprove": round(s.disapprove, 2),
                    "net": round(s.net_approval, 2),
                }
                for s in SilverBulletinApprovalLoader().load_series(silverb_path)
                if s.as_of >= start
            ]
        except Exception as exc:  # pragma: no cover - defensive
            logging.warning("silver bulletin series load failed: %s", exc)

    votehub_series = _votehub_unweighted_trend(polls, start=start, end=end)

    fpo_series = [
        {
            "as_of": p["as_of"],
            "approve": p["approve"],
            "disapprove": p["disapprove"],
            "net": round(p["approve"] - p["disapprove"], 2),
        }
        for p in FiftyPlusOneApprovalCsvLoader().load_series(
            FALLBACK_DIR / "fiftyplusone_approval.csv"
        )
        if p["as_of"] >= start
    ]

    return {
        "sources": {
            "ours": {
                "label": "Our model",
                "description": "Weighted polling average: recency decay, pollster quality, "
                "sample size and population weighting, partisan penalty.",
                "available": len(ours) > 0,
                "series": ours,
            },
            "silver_bulletin": {
                "label": "Silver Bulletin",
                "description": "Silver Bulletin's published daily approval model.",
                "available": len(silverb_series) > 0,
                "series": silverb_series,
            },
            "votehub": {
                "label": "VoteHub (raw average)",
                "description": "Unweighted 14-day trailing mean of VoteHub approval polls.",
                "available": len(votehub_series) > 0,
                "series": votehub_series,
            },
            "fiftyplusone": {
                "label": "50+1",
                "description": "G. Elliott Morris's 50+1 average (requires API access; "
                "series appears once data/fallback/fiftyplusone_approval.csv exists).",
                "available": len(fpo_series) > 0,
                "series": fpo_series,
            },
        },
    }


def _dem_rep_margin(
    candidates: dict[str, float], dem_candidate: str, rep_candidate: str
) -> float | None:
    """Dem − Rep margin from a race's candidate averages (name-tolerant)."""

    def _find(target: str) -> float | None:
        for name, pct in candidates.items():
            if target.lower() in name.lower() or name.lower() in target.lower():
                return pct
        return None

    dem = _find(dem_candidate)
    rep = _find(rep_candidate)
    if dem is None or rep is None:
        return None
    return round(dem - rep, 2)


def _senate_payload(polls: list[Poll]) -> dict:
    engine = _build_engine_from_polls(polls) if polls else None
    states = _detect_senate_states(polls) or _US_STATES
    model = SenateModel(engine=engine) if engine else SenateModel()
    races = [model.race_average(polls, state) for state in states]
    races = [r for r in races if r.num_polls > 0]
    races.sort(key=lambda r: r.state)

    cycle = load_cycle_config()
    config_by_state = {entry["state"]: entry for entry in cycle["competitive_races"]}
    market_odds = MarketOddsCsvSource(FALLBACK_DIR).load()
    vibes_model = VibesAdjustedSenateModel(VibesCsvSource(FALLBACK_DIR).load())

    enriched = []
    for race in races:
        entry = config_by_state.get(race.state)
        record: dict = dataclasses.asdict(race)
        if entry:
            race_key = entry["race"]
            record["dem_candidate"] = entry["dem_candidate"]
            record["rep_candidate"] = entry["rep_candidate"]
            dem_margin = _dem_rep_margin(
                race.candidates, entry["dem_candidate"], entry["rep_candidate"]
            )
            record["dem_margin"] = dem_margin

            vibes = vibes_model.adjustment_for_race(
                race_key, entry["dem_candidate"], entry["rep_candidate"]
            )
            record["vibes"] = {
                "available": vibes.has_data,
                "adjustment": vibes.adjustment,
                "dem_effect": vibes.dem_effect,
                "rep_effect": vibes.rep_effect,
                "adjusted_dem_margin": (
                    round(dem_margin + vibes.adjustment, 2) if dem_margin is not None else None
                ),
            }
            record["market_odds"] = odds_for_race(market_odds, race_key)
        enriched.append(record)

    return {"races": enriched, "num_races": len(enriched)}


def _senate_forecast_payload(senate_payload: dict) -> dict:
    """1000-simulation Senate-control Monte Carlo + market comparison."""
    cycle = load_cycle_config()
    market_odds = MarketOddsCsvSource(FALLBACK_DIR).load()
    races_by_state = {r["state"]: r for r in senate_payload["races"]}

    inputs: list[RaceInput] = []
    for entry in cycle["competitive_races"]:
        race_record = races_by_state.get(entry["state"], {})
        per_source = odds_for_race(market_odds, entry["race"])
        market_dem_prob = {
            source: outcomes["Democrat"]
            for source, outcomes in per_source.items()
            if "Democrat" in outcomes
        }
        inputs.append(
            RaceInput(
                state=entry["state"],
                race=entry["race"],
                dem_candidate=entry["dem_candidate"],
                rep_candidate=entry["rep_candidate"],
                margin=race_record.get("dem_margin"),
                num_polls=race_record.get("num_polls", 0),
                market_dem_prob=market_dem_prob,
            )
        )

    simulator = SenateControlSimulator(
        dem_safe_seats=cycle["dem_safe_seats"],
        rep_safe_seats=cycle["rep_safe_seats"],
        dem_majority_threshold=cycle["dem_majority_threshold"],
    )
    control_odds = odds_for_race(market_odds, SENATE_CONTROL_RACE)
    forecast = simulator.simulate(
        inputs,
        num_simulations=NUM_SIMULATIONS,
        seed=SIMULATION_SEED,
        market_control_dem_prob={
            source: outcomes["Democrat"]
            for source, outcomes in control_odds.items()
            if "Democrat" in outcomes
        },
    )
    payload = dataclasses.asdict(forecast)
    # JSON object keys must be strings.
    payload["seat_distribution"] = {
        str(k): v for k, v in forecast.seat_distribution.items()
    }
    payload["maturity"] = "nowcast"
    payload["label"] = (
        "NOWCAST — if the election were held today, based on current polling "
        "averages blended with prediction-market odds. Not a calibrated "
        "election-day forecast."
    )
    return payload


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

    approval_payload = _approval_payload(approval_polls, args.trend_days)
    _write("approval.json", approval_payload)
    _write(
        "approval_comparison.json",
        _approval_comparison_payload(approval_payload, approval_polls, args.trend_days),
    )
    _write("generic_ballot.json", _generic_ballot_payload(gb_polls, args.trend_days))
    senate_payload = _senate_payload(senate_polls)
    _write("senate.json", senate_payload)
    _write("senate_forecast.json", _senate_forecast_payload(senate_payload))

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
