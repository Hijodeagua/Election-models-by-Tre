"""Export tracker snapshots to static JSON for the web/ Next.js spoke.

Reuses the offline pipeline from run_models.py — same data-loading fallback
chain (curated CSV → VoteHub CSV) and the same model classes. No new model
code: it calls the existing PresidentialApprovalModel, GenericBallotModel and
SenateModel, then serialises their dataclass snapshots with dataclasses.asdict.

Heavy state-space / PyMC estimates are intentionally skipped — too slow for CI.
Everything here runs in offline mode with no API keys.

Outputs (web/public/data/):
    approval.json            — current reading + daily trend series with CI bands
    generic_ballot.json      — D/R margin, current reading + daily trend series
    senate.json              — per-race SenateRaceSnapshots
    approval_comparison.json — our model vs Silver Bulletin vs VoteHub raw vs 50+1
    senate_races.json        — per-race probability stack (base / vibes / markets)
    senate_control.json      — 1,000-sim Monte Carlo control forecast + markets
    meta.json                — last_updated, data tier, model versions

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
from config.settings import settings
from src.data.base import Poll, PollType
from src.data.csv_source import CsvFallbackSource
from src.data.market_odds import KIND_CONTROL, MarketOdds, load_odds_csv
from src.data.silverb_csv import load_approval_series
from src.data.votehub_csv import VoteHubCsvLoader
from src.models.approval import PresidentialApprovalModel
from src.models.generic_ballot import GenericBallotModel, GenericBallotSnapshot
from src.models.senate import SenateModel, SenateRaceSnapshot
from src.models.senate_probability import (
    load_senate_config,
    race_probability,
)
from src.models.senate_simulation import (
    DEFAULT_N_SIMS,
    date_seed,
    simulate_senate_control,
)
from src.models.vibes_adjustment import load_vibes_snapshot, race_adjustment_for_state

FALLBACK_DIR = PROJECT_ROOT / "data" / "fallback"
OUTPUT_DIR = PROJECT_ROOT / "web" / "public" / "data"

# Maturity tier label shown in the UI — every output here is a TRACKER.
DATA_TIER = "tracker"

MODEL_VERSIONS = {
    "approval": "PresidentialApprovalModel (weighted polling average, Phase 2)",
    "generic_ballot": "GenericBallotModel (weighted polling average, Phase 2)",
    "senate": "SenateModel (per-race polling average)",
    "senate_probability": "margin→win-prob (normal CDF) + rating prior + market blend",
    "senate_control": f"Monte Carlo, {DEFAULT_N_SIMS} sims, correlated national swing",
    "vibes": "NYT coverage adjustment (bounded ±2.5 pts of margin)",
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
    races = _senate_snapshots(polls)
    return {"races": races, "num_races": len(races)}


def _senate_snapshots(polls: list[Poll]) -> list[SenateRaceSnapshot]:
    engine = _build_engine_from_polls(polls) if polls else None
    states = _detect_senate_states(polls) or _US_STATES
    model = SenateModel(engine=engine) if engine else SenateModel()
    races = [model.race_average(polls, state) for state in states]
    races = [r for r in races if r.num_polls > 0]
    races.sort(key=lambda r: r.state)
    return races


# ── Dashboard payloads (approval comparison / senate probabilities / control sim) ─

def _trend_series(snapshots) -> list[dict]:
    """Slim {as_of, approve, disapprove, net} series for comparison charts."""
    return [
        {
            "as_of": s.as_of,
            "approve": s.approve,
            "disapprove": s.disapprove,
            "net": round(s.approve - s.disapprove, 1),
        }
        for s in snapshots
    ]


def _votehub_raw_series(polls: list[Poll], trend_days: int, window_days: int = 14) -> list[dict]:
    """Unweighted rolling mean of raw VoteHub approval polls.

    Deliberately *not* the weighted engine — this is the "what the raw
    VoteHub numbers say" comparison series.
    """
    vh = [p for p in polls if p.source == "votehub" and p.poll_type == PollType.APPROVAL]
    if not vh:
        return []
    end = date.today()
    start = end - timedelta(days=trend_days)
    out: list[dict] = []
    current = start
    while current <= end:
        lo = current - timedelta(days=window_days)
        window = [p for p in vh if lo <= p.end_date <= current]
        approves = [a.pct for p in window for a in p.answers if a.choice.lower() == "approve"]
        disapproves = [a.pct for p in window for a in p.answers if a.choice.lower() == "disapprove"]
        if approves and disapproves:
            app = round(sum(approves) / len(approves), 1)
            dis = round(sum(disapproves) / len(disapproves), 1)
            out.append({"as_of": current, "approve": app, "disapprove": dis,
                        "net": round(app - dis, 1), "num_polls": len(window)})
        current += timedelta(days=1)
    return out


def _approval_comparison_payload(polls: list[Poll], trend_days: int) -> dict:
    """Multi-source approval series for the toggleable homepage chart."""
    engine = _build_engine_from_polls(polls) if polls else None
    model = PresidentialApprovalModel(engine=engine) if engine else PresidentialApprovalModel()
    end = date.today()
    start = end - timedelta(days=trend_days)
    our_trend = model.approval_trend(polls, start=start, end=end, step_days=1)

    cutoff = start
    silverb = [s for s in load_approval_series(FALLBACK_DIR / "silverb_approval.csv")
               if s.as_of >= cutoff]
    fifty = [s for s in load_approval_series(FALLBACK_DIR / "fiftyplusone_approval.csv")
             if s.as_of >= cutoff]

    series = {
        "our_model": _trend_series(our_trend),
        "silver_bulletin": _trend_series(silverb),
        "votehub_raw": _votehub_raw_series(polls, trend_days),
        "fifty_plus_one": _trend_series(fifty),
    }
    return {
        "series": series,
        "available": [k for k, v in series.items() if v],
        "labels": {
            "our_model": "Our model (weighted average)",
            "silver_bulletin": "Silver Bulletin",
            "votehub_raw": "VoteHub raw average",
            "fifty_plus_one": "50+1 (Strength In Numbers)",
        },
    }


def _race_market_quotes(market_odds: list[MarketOdds], state: str) -> list[dict]:
    return [
        o.to_dict() for o in market_odds
        if o.kind != KIND_CONTROL and o.state.lower() == state.lower()
    ]


def _senate_races_payload(
    snapshots: list[SenateRaceSnapshot],
    market_odds: list[MarketOdds],
) -> tuple[dict, list]:
    """Per-race probability stack. Returns (payload, blended RaceProbability list).

    The blended list (markets folded into the model) feeds the control
    simulation, so market prices participate in the forecast itself.
    """
    cfg = load_senate_config()
    races_cfg = {r["state"]: r for r in cfg["races"]}
    vibes_snapshot = load_vibes_snapshot(FALLBACK_DIR / "vibes_snapshot.csv")
    weight = settings.market_blend_weight

    snap_by_state = {s.state: s for s in snapshots}
    out_races: list[dict] = []
    blended_for_sim: list = []

    for state, race_cfg in sorted(races_cfg.items()):
        snap = snap_by_state.get(state)
        candidates = snap.candidates if snap else {}
        num_polls = snap.num_polls if snap else 0

        base = race_probability(
            state, candidates, num_polls, race_cfg, market_odds, market_weight=weight,
        )
        vibes_adj, vibes_detail = race_adjustment_for_state(vibes_snapshot, state)
        with_vibes = race_probability(
            state, candidates, num_polls, race_cfg, market_odds,
            market_weight=weight, margin_adjustment=vibes_adj,
        )
        blended_for_sim.append(with_vibes if vibes_adj else base)

        out_races.append({
            "state": state,
            "abbr": race_cfg.get("abbr"),
            "incumbent_party": race_cfg.get("incumbent_party"),
            "rating": race_cfg.get("rating"),
            "battleground": bool(race_cfg.get("battleground")),
            "open_seat": bool(race_cfg.get("open_seat")),
            "special": bool(race_cfg.get("special")),
            "candidates": candidates,
            "num_polls": num_polls,
            "dem_margin": base.dem_margin,
            "models": {
                "base": {
                    "dem_win_prob": base.model_prob,
                    "sources": base.sources,
                },
                "with_vibes": {
                    "dem_win_prob": with_vibes.model_prob,
                    "vibes_adjustment": vibes_adj,
                    "detail": vibes_detail,
                },
                "market_blend": {
                    "dem_win_prob": base.blended_prob,
                    "market_prob": base.market_prob,
                    "market_weight": weight,
                },
            },
            "markets": _race_market_quotes(market_odds, state),
        })

    payload = {
        "cycle": cfg["cycle"],
        "races": out_races,
        "num_races": len(out_races),
        "market_blend_weight": weight,
    }
    return payload, blended_for_sim


def _senate_control_payload(blended_races: list, market_odds: list[MarketOdds]) -> dict:
    cfg = load_senate_config()
    baseline = cfg["baseline_not_up"]
    result = simulate_senate_control(
        blended_races,
        baseline_dem=baseline["dem"],
        baseline_rep=baseline["rep"],
        dem_seats_needed=cfg["dem_seats_needed_for_control"],
        n_sims=DEFAULT_N_SIMS,
        seed=date_seed(date.today()),
    )

    control_markets = [o.to_dict() for o in market_odds if o.kind == KIND_CONTROL]
    return {
        "simulation": result,
        "market_control_odds": control_markets,
        "market_blend_weight": settings.market_blend_weight,
        "notes": [
            f"{result.n_sims} Monte Carlo simulations over per-race blended probabilities.",
            "Race outcomes are correlated through a shared national-environment swing "
            f"(σ={result.national_swing_sd} pts) plus per-race error "
            f"(σ={result.idiosyncratic_sd} pts).",
            "Prediction-market prices are blended into each race's probability before "
            "simulation, so markets inform the forecast as well as the comparison.",
        ],
    }


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

    market_odds = load_odds_csv(FALLBACK_DIR / "market_odds.csv")
    print(f"  market quotes loaded: {len(market_odds)}")

    _write("approval.json", _approval_payload(approval_polls, args.trend_days))
    _write("generic_ballot.json", _generic_ballot_payload(gb_polls, args.trend_days))
    senate_snapshots = _senate_snapshots(senate_polls)
    _write("senate.json", {"races": senate_snapshots, "num_races": len(senate_snapshots)})

    comparison = _approval_comparison_payload(approval_polls, args.trend_days)
    _write("approval_comparison.json", comparison)
    races_payload, blended = _senate_races_payload(senate_snapshots, market_odds)
    _write("senate_races.json", races_payload)
    _write("senate_control.json", _senate_control_payload(blended, market_odds))

    meta = {
        "last_updated": datetime.now().astimezone().isoformat(),
        "data_tier": DATA_TIER,
        "label": "Trackers + experimental Senate forecast (markets-blended, not yet backtested)",
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
