"""Export tracker snapshots to static JSON for the web/ Next.js spoke.

Reuses the offline pipeline from run_models.py — same data-loading fallback
chain (curated CSV → VoteHub CSV) and the same model classes. No new model
code: it calls the existing PresidentialApprovalModel, GenericBallotModel and
SenateModel, then serialises their dataclass snapshots with dataclasses.asdict.

State-space / PyMC estimates run when --state-space is passed (the audit's
runtime measurement put a full fit at a few minutes — affordable in the
twice-daily refresh). Without the flag, everything runs offline with no
heavy dependencies.

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
    "senate_control": "SenateControlSimulator (50,000-sim Monte Carlo NOWCAST)",
    # Overwritten at runtime when --state-space runs (see main()).
    "state_space": "not run this refresh (pass --state-space)",
}

# Fixed seed so the daily cron produces a stable simulation for a given
# polling snapshot (diffs in git stay meaningful).
SIMULATION_SEED = 20260101
NUM_SIMULATIONS = 50000

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


# ── State-space (Jackman) estimates — opt-in via --state-space ────────────────

def _ss_series_block(result, dis_result=None, labels=("approve", "disapprove")) -> dict:
    """Serialize one (or a pair of) StateSpaceResult latent paths for the web.

    Emits the full posterior path so the frontend can draw the corrected trend
    with credible bands, plus the fitted house effects — the whole point of
    publishing this model is that additive pollster lean is removed rather
    than merely downweighted (METHODOLOGY_REVIEW Error 3).
    """
    a, b = labels
    lo_by_date = dict(zip(result.dates, zip(result.alpha_lo, result.alpha_hi)))
    series = []
    dis_by_date = {}
    if dis_result is not None:
        dis_by_date = {
            d: (m, lo, hi)
            for d, m, lo, hi in zip(
                dis_result.dates, dis_result.alpha_mean,
                dis_result.alpha_lo, dis_result.alpha_hi,
            )
        }
    for d, mean in zip(result.dates, result.alpha_mean):
        lo, hi = lo_by_date[d]
        point = {
            "as_of": d,
            a: round(float(mean), 2),
            f"{a}_lo": round(float(lo), 2),
            f"{a}_hi": round(float(hi), 2),
        }
        if d in dis_by_date:
            m2, lo2, hi2 = dis_by_date[d]
            point[b] = round(float(m2), 2)
            point[f"{b}_lo"] = round(float(lo2), 2)
            point[f"{b}_hi"] = round(float(hi2), 2)
        series.append(point)

    house_effects = sorted(
        (
            {
                "pollster": p,
                "effect": round(float(m), 2),
                "lo": round(float(lo), 2),
                "hi": round(float(hi), 2),
            }
            for p, m, lo, hi in zip(
                result.pollsters, result.delta_mean, result.delta_lo, result.delta_hi
            )
        ),
        key=lambda r: -abs(r["effect"]),
    )

    return {
        "trend": series,
        "house_effects": house_effects,
        "sigma_alpha": round(float(result.sigma_alpha_mean), 3),
        "convergence_ok": bool(result.convergence_ok),
        "n_polls": result.n_polls,
    }


def _approval_state_space(polls: list[Poll], draws: int, tune: int) -> dict:
    """Jackman state-space presidential approval block, or {'available': False}."""
    from src.models import state_space
    from src.models.approval import PRESIDENTIAL_SUBJECT_KEYWORD

    pres = [
        p for p in polls
        if not p.subject or PRESIDENTIAL_SUBJECT_KEYWORD in p.subject.lower()
    ]
    approve = state_space.fit(pres, choice="Approve", draws=draws, tune=tune)
    disapprove = state_space.fit(pres, choice="Disapprove", draws=draws, tune=tune)
    if approve is None or disapprove is None:
        return {"available": False, "reason": "fit failed or PyMC unavailable"}

    today = date.today()
    a_mean, a_lo, a_hi = approve.estimate_at(today)
    d_mean, d_lo, d_hi = disapprove.estimate_at(today)
    block = {
        "available": True,
        "model": "Jackman state-space: random-walk latent + additive house effects (Phase 3)",
        "as_of": today,
        "current": {
            "approve": round(a_mean, 1),
            "approve_lo": round(a_lo, 1),
            "approve_hi": round(a_hi, 1),
            "disapprove": round(d_mean, 1),
            "disapprove_lo": round(d_lo, 1),
            "disapprove_hi": round(d_hi, 1),
            "net": round(a_mean - d_mean, 1),
        },
    }
    block.update(_ss_series_block(approve, disapprove))
    return block


def _generic_ballot_state_space(polls: list[Poll], draws: int, tune: int) -> dict:
    """Jackman state-space generic-ballot block, or {'available': False}."""
    from src.models import state_space
    from src.models.generic_ballot import _dominant_choice

    gb = [p for p in polls if p.poll_type == PollType.GENERIC_BALLOT]
    dem_choice = _dominant_choice(gb, ("democrat", "democratic", "democrats", "dem"), "Democrat")
    rep_choice = _dominant_choice(gb, ("republican", "republicans", "gop", "rep"), "Republican")
    dem = state_space.fit(gb, choice=dem_choice, draws=draws, tune=tune)
    rep = state_space.fit(gb, choice=rep_choice, draws=draws, tune=tune)
    if dem is None or rep is None:
        return {"available": False, "reason": "fit failed or PyMC unavailable"}

    today = date.today()
    d_mean, d_lo, d_hi = dem.estimate_at(today)
    r_mean, r_lo, r_hi = rep.estimate_at(today)
    block = {
        "available": True,
        "model": "Jackman state-space: random-walk latent + additive house effects (Phase 3)",
        "as_of": today,
        "current": {
            "dem": round(d_mean, 1),
            "dem_lo": round(d_lo, 1),
            "dem_hi": round(d_hi, 1),
            "rep": round(r_mean, 1),
            "rep_lo": round(r_lo, 1),
            "rep_hi": round(r_hi, 1),
            "margin": round(d_mean - r_mean, 1),
        },
    }
    block.update(_ss_series_block(dem, rep, labels=("dem", "rep")))
    return block


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
    # Same subject screen as PresidentialApprovalModel: the approval feed also
    # carries Congress / Supreme Court / VP ratings that don't belong here.
    from src.models.approval import PRESIDENTIAL_SUBJECT_KEYWORD
    polls = [
        p for p in polls
        if not p.subject or PRESIDENTIAL_SUBJECT_KEYWORD in p.subject.lower()
    ]

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

    # Shared error model used to turn a margin into a Dem win probability
    # (same parameters the control simulation uses).
    prob_simulator = SenateControlSimulator(
        dem_safe_seats=cycle["dem_safe_seats"],
        rep_safe_seats=cycle["rep_safe_seats"],
        dem_majority_threshold=cycle["dem_majority_threshold"],
    )

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
            record["dem_win_prob"] = (
                round(prob_simulator.win_prob_from_margin(dem_margin), 4)
                if dem_margin is not None
                else None
            )

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


def _load_forecast_calibration() -> dict:
    """Load the fitted error model from scripts/calibrate_forecast.py, if present.

    Returns an empty dict when the file is missing or unreadable so the
    simulation falls back to its built-in default sigmas.
    """
    path = PROJECT_ROOT / "config" / "forecast_calibration.json"
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:  # pragma: no cover - defensive
        logging.warning("could not read forecast_calibration.json: %s", exc)
        return {}


def _national_environment(
    cfg: dict, approval_net: float | None, generic_margin: float | None
) -> dict:
    """Translate today's presidential approval + generic ballot into a uniform
    national swing (Dem−Rep points) relative to the 2024 House baseline.

    Returns a dict with the swing and its components for transparency. When the
    config block is absent the swing is 0 and the forecast is unchanged.
    """
    if not cfg:
        return {"national_swing": 0.0, "available": False}

    pres_party = cfg.get("president_party", "R").upper()
    house_baseline = cfg.get("house_baseline_2024", 0.0)
    generic_weight = cfg.get("generic_weight", 0.6)
    approval_weight = cfg.get("approval_weight", 0.4)
    appr_coef = cfg.get("approval_to_margin_coef", 0.3)
    responsiveness = cfg.get("senate_responsiveness", 1.0)

    # Generic ballot is already a Dem−Rep margin (positive = D advantage).
    gb_term = generic_margin if generic_margin is not None else None
    # Approval → the president's party's national margin, then flip to Dem−Rep.
    if approval_net is not None:
        pres_party_margin = appr_coef * approval_net
        appr_term = -pres_party_margin if pres_party == "R" else pres_party_margin
    else:
        appr_term = None

    # Re-normalise the weights over whichever signals are available so a missing
    # feed doesn't silently halve the environment.
    parts = []
    if gb_term is not None:
        parts.append((generic_weight, gb_term))
    if appr_term is not None:
        parts.append((approval_weight, appr_term))
    if not parts:
        return {"national_swing": 0.0, "available": False}
    wsum = sum(w for w, _ in parts) or 1.0
    e_national = sum(w * v for w, v in parts) / wsum

    national_swing = round((e_national - house_baseline) * responsiveness, 3)
    return {
        "national_swing": national_swing,
        "available": True,
        "president_party": pres_party,
        "approval_net": approval_net,
        "generic_margin": generic_margin,
        "approval_implied_margin": (round(appr_term, 3) if appr_term is not None else None),
        "expected_national_margin": round(e_national, 3),
        "house_baseline_2024": house_baseline,
        "senate_responsiveness": responsiveness,
    }


def _deep_merge(base: dict, overrides: dict) -> dict:
    """Recursively merge ``overrides`` onto a copy of ``base``."""
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _senate_forecast_payload(
    senate_payload: dict,
    approval_net: float | None = None,
    generic_margin: float | None = None,
    overrides: dict | None = None,
    quiet: bool = False,
) -> dict:
    """50,000-simulation Senate-control Monte Carlo + market comparison.

    ``overrides`` deep-merges onto the cycle config so the sensitivity sweep
    (scripts/sensitivity_sweep.py) can vary governance knobs through the exact
    production path. The special top-level key ``market_weight`` overrides the
    simulator's market blend weight.
    """
    cycle = load_cycle_config()
    overrides = overrides or {}
    if overrides:
        cycle = _deep_merge(cycle, {k: v for k, v in overrides.items() if k != "market_weight"})
    market_odds = MarketOddsCsvSource(FALLBACK_DIR).load()
    races_by_state = {r["state"]: r for r in senate_payload["races"]}

    fund_cfg = cycle.get("fundamentals", {})
    w_recent = fund_cfg.get("pres_weight_recent", 0.75)
    blend_k = fund_cfg.get("blend_k", 3.0)

    env = _national_environment(
        cycle.get("national_environment", {}), approval_net, generic_margin
    )
    national_swing = env["national_swing"]
    if env.get("available") and not quiet:
        print(
            f"  national environment: approval_net={approval_net}, "
            f"generic_margin={generic_margin} → swing={national_swing:+.2f} "
            f"Dem−Rep points (vs 2024 House baseline "
            f"{env.get('house_baseline_2024')})"
        )

    def _fundamentals_margin(entry: dict) -> float | None:
        """Dem−Rep fundamentals prior: blend of the state's 2024 & 2020
        presidential margins (2024 weighted ``pres_weight_recent``), shifted by
        the current national midterm swing (approval + generic ballot)."""
        p24, p20 = entry.get("pres_2024"), entry.get("pres_2020")
        if p24 is None and p20 is None:
            base = entry.get("lean_margin")
            return None if base is None else base + national_swing
        if p20 is None:
            return p24 + national_swing
        if p24 is None:
            return p20 + national_swing
        return w_recent * p24 + (1.0 - w_recent) * p20 + national_swing

    def _build_inputs(apply_vibes: bool) -> list[RaceInput]:
        out: list[RaceInput] = []
        for entry in cycle["competitive_races"]:
            rr = races_by_state.get(entry["state"], {})
            per_source = odds_for_race(market_odds, entry["race"])
            market_dem_prob = {
                source: outcomes["Democrat"]
                for source, outcomes in per_source.items()
                if "Democrat" in outcomes
            }
            poll_margin = rr.get("dem_margin")
            fund = _fundamentals_margin(entry)
            n = rr.get("num_polls", 0)
            # Blend polls with fundamentals; fundamentals weight = k/(k+n) so it
            # anchors thin-poll races and fades as polls accumulate.
            if poll_margin is None:
                margin = fund
            elif fund is None:
                margin = poll_margin
            else:
                w = blend_k / (blend_k + n)
                margin = (1.0 - w) * poll_margin + w * fund
            if apply_vibes and margin is not None:
                vibes = rr.get("vibes") or {}
                if vibes.get("available"):
                    margin = margin + vibes.get("adjustment", 0.0)
            out.append(
                RaceInput(
                    state=entry["state"],
                    race=entry["race"],
                    dem_candidate=entry["dem_candidate"],
                    rep_candidate=entry["rep_candidate"],
                    margin=round(margin, 3) if margin is not None else None,
                    num_polls=n,
                    market_dem_prob=market_dem_prob,
                )
            )
        return out

    inputs = _build_inputs(apply_vibes=False)

    calib = _load_forecast_calibration()
    bias_weight = cycle.get("forecast", {}).get("calibration_bias_weight", 0.5)
    sim_kwargs: dict = {}
    if calib.get("usable"):
        applied_bias = round(calib.get("bias", 0.0) * bias_weight, 3)
        sim_kwargs = {
            "national_sigma": calib["national_sigma"],
            "race_sigma": calib["race_sigma"],
            "bias": applied_bias,
        }
        if not quiet:
            print(
                f"  using calibrated error model (σ_nat={calib['national_sigma']}, "
                f"σ_race={calib['race_sigma']}, bias={calib.get('bias', 0.0)}×{bias_weight}"
                f"={applied_bias}, from {calib['n_races']} historical races)"
            )
    if "market_weight" in overrides:
        sim_kwargs["market_weight"] = overrides["market_weight"]
    tail_dof = cycle.get("forecast", {}).get("tail_dof")
    if tail_dof is not None:
        sim_kwargs["tail_dof"] = tail_dof
    simulator = SenateControlSimulator(
        dem_safe_seats=cycle["dem_safe_seats"],
        rep_safe_seats=cycle["rep_safe_seats"],
        dem_majority_threshold=cycle["dem_majority_threshold"],
        **sim_kwargs,
    )
    control_odds = odds_for_race(market_odds, SENATE_CONTROL_RACE)
    market_control_dem_prob = {
        source: outcomes["Democrat"]
        for source, outcomes in control_odds.items()
        if "Democrat" in outcomes
    }
    forecast = simulator.simulate(
        inputs,
        num_simulations=NUM_SIMULATIONS,
        seed=SIMULATION_SEED,
        market_control_dem_prob=market_control_dem_prob,
    )
    # Same simulation with the experimental NYT-vibes overlay applied, for
    # side-by-side comparison. (Vibes data is a neutral placeholder until the
    # NYT pipeline runs with a key, so today this matches the base forecast.)
    vibes_forecast = simulator.simulate(
        _build_inputs(apply_vibes=True),
        num_simulations=NUM_SIMULATIONS,
        seed=SIMULATION_SEED,
    )
    payload = dataclasses.asdict(forecast)
    # JSON object keys must be strings.
    payload["seat_distribution"] = {
        str(k): v for k, v in forecast.seat_distribution.items()
    }
    payload["maturity"] = "nowcast"
    payload["label"] = (
        "Where the race stands today — current polling averages blended with "
        "prediction-market odds. A work in progress from Policy y Peaches."
    )
    # Fundamentals blend (2024 + 2020 presidential lean) and the NYT-vibes
    # variant of the chamber forecast, for comparison.
    payload["fundamentals_weight_recent"] = w_recent
    payload["fundamentals_blend_k"] = blend_k
    payload["dem_control_prob_with_vibes"] = vibes_forecast.dem_control_prob
    payload["mean_dem_seats_with_vibes"] = vibes_forecast.mean_dem_seats
    # National midterm environment (presidential approval + generic ballot)
    # folded into the fundamentals prior, exposed for transparency in the UI.
    payload["national_environment"] = env
    return payload


def _attach_race_forecasts(senate_payload: dict, forecast_payload: dict) -> None:
    """Fold each race's simulation summary onto its battleground-card record.

    The margin histogram is *moved* (popped) rather than copied: senate.json is
    where the chart reads it, and leaving a second copy in senate_forecast.json
    would ship the same ~8 KB to every visitor twice.
    """
    fc_by_state = {r["state"]: r for r in forecast_payload.get("races", [])}
    n_sims = forecast_payload.get("num_simulations")
    for rec in senate_payload.get("races", []):
        fc = fc_by_state.get(rec["state"])
        if not fc:
            continue
        # Prefer the simulated win share; fall back to the marginal probability.
        win_prob = fc.get("dem_win_prob_sim")
        if win_prob is None:
            win_prob = fc.get("dem_win_prob_blended") or fc.get("dem_win_prob_polls")
        rec["forecast"] = {
            "dem_win_prob": win_prob,
            "median_margin": fc.get("median_margin"),
            "margin_p10": fc.get("margin_p10"),
            "margin_p90": fc.get("margin_p90"),
            "num_simulations": n_sims,
            "margin_hist": fc.pop("margin_hist", []),
        }
    # Any histogram left on a race senate.json doesn't render is still dead
    # weight in senate_forecast.json — drop those too.
    for fc in fc_by_state.values():
        fc.pop("margin_hist", None)


# ── Pollster grades + polls-by-state tab ─────────────────────────────────────────

def _quality_to_grade(quality: float | None) -> str | None:
    """Map a 0–3 pollster-quality score to a letter grade (rated pool ≈ [1.0, 2.0])."""
    if quality is None:
        return None
    cutoffs = [
        (1.85, "A"), (1.65, "A-"), (1.45, "B+"), (1.25, "B"),
        (1.05, "B-"), (0.85, "C+"), (0.65, "C"), (0.0, "C-"),
    ]
    for lo, grade in cutoffs:
        if quality >= lo:
            return grade
    return "C-"


def _poll_candidate_pct(poll: Poll, target: str) -> float | None:
    """A poll's pct for a candidate, matched by surname (name-tolerant)."""
    surname = target.split()[-1].lower() if target else ""
    for ans in poll.answers:
        if surname and surname in ans.choice.lower():
            return ans.pct
    return None


def _state_from_subject(subject: str, states: list[str]) -> str | None:
    """Map a poll subject ("Ohio Senate 2026") to a configured state name."""
    subj = subject.lower()
    for state in states:
        if state.lower() in subj:
            return state
    return None


def _pollsters_payload(senate_polls: list[Poll]) -> dict:
    """Pollster grades (national + per-state track record) and the live polls
    behind each state's Senate race, for the Pollsters tab."""
    from src.data.pollster_ratings import (
        _SB_RAW_ERRORS,
        _UNKNOWN_DEFAULT,
        _canonical,
        hybrid_quality,
    )

    calib = _load_forecast_calibration()
    emp = {row["pollster"]: row for row in calib.get("pollster_bias", [])}
    state_hist = calib.get("state_pollster_bias", {})  # {abbr: [{pollster, ...}]}

    # National grades: the rated Silver-Bulletin pool, enriched with our own
    # historical actual-minus-poll track record where the calibration has it.
    national: list[dict] = []
    for name in _SB_RAW_ERRORS:
        q = hybrid_quality(name)
        e = emp.get(name) or emp.get(_canonical(name))
        national.append({
            "pollster": name,
            "quality": q,
            "grade": _quality_to_grade(q),
            "sb_error": _SB_RAW_ERRORS[name],
            "empirical": (
                {
                    "mean_error": e["mean_error"],
                    "std_error": e["std_error"],
                    "n_polls": e["n_polls"],
                }
                if e else None
            ),
        })
    national.sort(key=lambda r: -r["quality"])

    cycle = load_cycle_config()
    config_by_state = {e["state"]: e for e in cycle["competitive_races"]}
    states = list(config_by_state)

    by_state: dict[str, list[dict]] = {}
    for poll in senate_polls:
        st = _state_from_subject(poll.subject, states)
        if not st:
            continue
        entry = config_by_state[st]
        dem_pct = _poll_candidate_pct(poll, entry["dem_candidate"])
        rep_pct = _poll_candidate_pct(poll, entry["rep_candidate"])
        margin = (
            round(dem_pct - rep_pct, 1)
            if dem_pct is not None and rep_pct is not None
            else None
        )
        canonical = _canonical(poll.pollster)
        rated = canonical in _SB_RAW_ERRORS
        q = hybrid_quality(poll.pollster) if rated else None
        by_state.setdefault(st, []).append({
            "pollster": poll.pollster,
            "rated": rated,
            "grade": _quality_to_grade(q) if rated else None,
            "quality": q,
            "start_date": poll.start_date.isoformat(),
            "end_date": poll.end_date.isoformat(),
            "sample_size": poll.sample_size,
            "population": poll.population.value if poll.population else None,
            "dem_candidate": entry["dem_candidate"],
            "rep_candidate": entry["rep_candidate"],
            "dem_pct": dem_pct,
            "rep_pct": rep_pct,
            "margin": margin,
            "partisan": poll.partisan,
        })

    states_out: list[dict] = []
    for st in states:
        polls = by_state.get(st, [])
        polls.sort(key=lambda p: p["end_date"], reverse=True)
        abbr = config_by_state[st].get("abbr")
        states_out.append({
            "state": st,
            "abbr": abbr,
            "num_polls": len(polls),
            "polls": polls,
            # Per-pollster historical accuracy IN this state (actual − poll),
            # from the calibration backtest. Populates once CI recalibrates.
            "pollster_history": state_hist.get(abbr, []) if abbr else [],
        })

    return {
        "national": national,
        "states": states_out,
        "unknown_default_quality": _UNKNOWN_DEFAULT,
        "unknown_default_grade": _quality_to_grade(_UNKNOWN_DEFAULT),
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
    parser.add_argument(
        "--state-space", action="store_true",
        help="Also fit and publish the Jackman state-space estimates "
        "(requires PyMC; ~2-3 min per series on a CI runner).",
    )
    parser.add_argument("--ss-draws", type=int, default=1000, help="Posterior draws per chain.")
    parser.add_argument("--ss-tune", type=int, default=1000, help="Tuning steps per chain.")
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
    gb_payload = _generic_ballot_payload(gb_polls, args.trend_days)

    if args.state_space:
        print("  fitting state-space models (this takes a few minutes)...")
        approval_payload["state_space"] = _approval_state_space(
            approval_polls, args.ss_draws, args.ss_tune
        )
        gb_payload["state_space"] = _generic_ballot_state_space(
            gb_polls, args.ss_draws, args.ss_tune
        )
        for name, payload in (("approval", approval_payload), ("generic ballot", gb_payload)):
            ss = payload["state_space"]
            status = "ok" if ss.get("available") else f"unavailable ({ss.get('reason')})"
            print(f"  state-space {name}: {status}")
    else:
        approval_payload["state_space"] = {"available": False, "reason": "not run (opt-in)"}
        gb_payload["state_space"] = {"available": False, "reason": "not run (opt-in)"}

    _write("approval.json", approval_payload)
    _write(
        "approval_comparison.json",
        _approval_comparison_payload(approval_payload, approval_polls, args.trend_days),
    )
    _write("generic_ballot.json", gb_payload)
    senate_payload = _senate_payload(senate_polls)

    # Current national environment feeding the forecast's fundamentals prior.
    approval_current = approval_payload.get("current")
    approval_net = (
        approval_current.net_approval if approval_current is not None else None
    )
    gb_current = gb_payload.get("current")
    generic_margin = gb_current.margin if gb_current is not None else None
    forecast_payload = _senate_forecast_payload(
        senate_payload, approval_net, generic_margin
    )

    # Fold each race's simulation summary (win share + median margin) back onto
    # the battleground cards so /senate reads the forecast, not just the polls.
    _attach_race_forecasts(senate_payload, forecast_payload)
    _write("senate.json", senate_payload)
    _write("senate_forecast.json", forecast_payload)
    _write("pollsters.json", _pollsters_payload(senate_polls))

    def _latest_poll(polls: list[Poll]) -> str | None:
        dates = [p.midpoint_date for p in polls if p.midpoint_date]
        return max(dates).isoformat() if dates else None

    model_versions = dict(MODEL_VERSIONS)
    if args.state_space:
        ss_ok = approval_payload["state_space"].get("available") and gb_payload[
            "state_space"
        ].get("available")
        model_versions["state_space"] = (
            "Jackman state-space (random-walk latent + house effects), published"
            if ss_ok
            else "attempted this refresh but unavailable — see state_space.reason"
        )

    meta = {
        "last_updated": datetime.now().astimezone().isoformat(),
        "data_tier": DATA_TIER,
        "label": "A work in progress from the team at Policy y Peaches",
        "model_versions": model_versions,
        "poll_counts": {
            "approval": len(approval_polls),
            "generic_ballot": len(gb_polls),
            "senate": len(senate_polls),
        },
        # Date of the most recent poll in each feed — i.e. when the underlying
        # polling actually last refreshed, distinct from the pipeline run time.
        "last_poll_dates": {
            "approval": _latest_poll(approval_polls),
            "generic_ballot": _latest_poll(gb_polls),
            "senate": _latest_poll(senate_polls),
        },
    }
    _write("meta.json", meta)

    print("Done.")


if __name__ == "__main__":
    main()
