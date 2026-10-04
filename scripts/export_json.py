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

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Reuse helpers from the CLI entrypoint rather than re-implementing them.
from scripts.run_models import (
    _US_STATES,
    _build_engine_from_polls,
    _detect_senate_states,
)
from src.analysis.fundamentals import economic_components, schedule_lookup
from src.data.base import Poll, PollType
from src.data.csv_source import CsvFallbackSource
from src.data.economic import load_economic_csv, snapshot_from_rows
from src.data.fiftyplusone import FiftyPlusOneApprovalCsvLoader
from src.data.markets import (
    SENATE_CONTROL_RACE,
    MarketOddsCsvSource,
    odds_for_race,
    urls_for_race,
)
from src.data.votehub_csv import VoteHubCsvLoader
from src.data.wikipedia_senate import is_aggregate_pollster
from src.models.approval import PresidentialApprovalModel
from src.models.generic_ballot import (
    GENERIC_BALLOT_CHOICES,
    GenericBallotModel,
    GenericBallotSnapshot,
)
from src.models.house_forecast import (
    HouseForecastSimulator,
    load_districts,
    load_house_config,
    load_state_presidential,
    two_party_margin,
)
from src.models.house_forecast import (
    expected_national_margin as _house_expected_margin,
)
from src.models.senate import SenateModel
from src.models.senate_simulation import (
    DEFAULT_NATIONAL_SIGMA,
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
    "house_control": "HouseForecastSimulator (435-district uniform swing + noise, 50,000 sims)",
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
                return _drop_aggregates(polls)
        except Exception as exc:  # pragma: no cover - defensive
            logging.warning("%s load failed: %s", votehub_filename, exc)
    source = CsvFallbackSource(FALLBACK_DIR)
    polls, _meta = source.load(poll_type)
    return _drop_aggregates(polls)


def _drop_aggregates(polls: list[Poll]) -> list[Poll]:
    """Exclude poll-of-polls / model rows (RealClearPolitics, 270toWin, RCP
    Average, …) so they never enter the weighted average or the reported
    last-poll date. Ingesting an average as a single poll double-counts and,
    because these rows carry wide date ranges, makes a stalled feed look fresh."""
    return [p for p in polls if not is_aggregate_pollster(p.pollster)]


# ── State-space (Jackman) estimates — opt-in via --state-space ────────────────

def _ss_series_block(result, dis_result=None, labels=("approve", "disapprove")) -> dict:
    """Serialize one (or a pair of) StateSpaceResult latent paths for the web.

    Emits the full posterior path so the frontend can draw the corrected trend
    with credible bands, plus the fitted house effects — the whole point of
    publishing this model is that additive pollster lean is removed rather
    than merely downweighted (METHODOLOGY_REVIEW Error 3).
    """
    a, b = labels
    bounds = zip(result.alpha_lo, result.alpha_hi, strict=True)
    lo_by_date = dict(zip(result.dates, bounds, strict=True))
    series = []
    dis_by_date = {}
    if dis_result is not None:
        dis_by_date = {
            d: (m, lo, hi)
            for d, m, lo, hi in zip(
                dis_result.dates, dis_result.alpha_mean,
                dis_result.alpha_lo, dis_result.alpha_hi, strict=True,
            )
        }
    for d, mean in zip(result.dates, result.alpha_mean, strict=True):
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
                result.pollsters, result.delta_mean, result.delta_lo, result.delta_hi,
                strict=True,
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

    dem = _find_candidate_pct(candidates, dem_candidate)
    rep = _find_candidate_pct(candidates, rep_candidate)
    if dem is None or rep is None:
        return None
    return round(dem - rep, 2)


def _find_candidate_pct(candidates: dict[str, float], target: str | None) -> float | None:
    """Average share for a candidate, matched tolerantly by name."""
    if not target:
        return None
    for name, pct in candidates.items():
        if target.lower() in name.lower() or name.lower() in target.lower():
            return pct
    return None


def _party_by_candidate(polls: list[Poll], state: str) -> dict[str, str]:
    """Map each polled candidate name → party for one state, from the party
    tags the Wikipedia scraper attaches to head-to-head answers."""
    out: dict[str, str] = {}
    for p in polls:
        if state.lower() not in p.subject.lower():
            continue
        for a in p.answers:
            if a.party and a.choice:
                out[a.choice] = a.party
    return out


def _resolve_nominee(
    candidates: dict[str, float],
    party_by_name: dict[str, str],
    configured: str | None,
    party: str,
) -> str | None:
    """The name to track for one party in a race: the configured nominee when
    it's actually in the polling, otherwise the party's frontrunner (highest
    average share among candidates tagged with that party). This is how a race
    with no settled primary — or a stale configured name — picks up the top
    candidate for each party instead of showing nothing."""
    if configured and _find_candidate_pct(candidates, configured) is not None:
        return configured
    ranked = sorted(
        (name for name, pct in candidates.items() if party_by_name.get(name) == party),
        key=lambda n: candidates[n],
        reverse=True,
    )
    return ranked[0] if ranked else configured


# Answer labels that are not candidates and must never be picked as a nominee.
_NON_CANDIDATE_LABELS = ("undecided", "other", "someone else", "none", "refused", "unsure")


def _top_other_candidate(
    candidates: dict[str, float], exclude: str | None, min_share: float = 20.0
) -> str | None:
    """Highest-polling name other than ``exclude`` — the fallback nominee for a
    party when its configured name isn't in the polls *and* the polls carry no
    party tags (the VoteHub/CSV path). Two-way head-to-heads make this safe:
    once one side is identified, the other side is whoever is left. Guarded by
    a minimum share so an "Undecided" row can't be promoted."""
    ranked = sorted(
        (
            (name, pct)
            for name, pct in candidates.items()
            if name != exclude
            and pct >= min_share
            and not any(tok in name.lower() for tok in _NON_CANDIDATE_LABELS)
        ),
        key=lambda kv: kv[1],
        reverse=True,
    )
    return ranked[0][0] if ranked else None


def _house_effect_table(calib: dict, shrink_k: float = 10.0, cap: float = 2.5) -> dict[str, dict]:
    """Relative house effect per pollster from the calibration's pollster_bias.

    effect = clip((mean_error − pooled_bias) · n/(n+k), −cap, cap), in Dem−Rep
    points of *actual − poll*: positive means the pollster has understated
    Democrats, so its polls are shifted toward Democrats. Keyed by canonical
    pollster name; each value carries the inputs for transparency.
    """
    from src.data.pollster_ratings import _canonical

    pooled = float(calib.get("bias", 0.0))
    out: dict[str, dict] = {}
    for row in calib.get("pollster_bias", []):
        n = int(row.get("n_polls", 0))
        if n <= 0:
            continue
        raw = float(row["mean_error"]) - pooled
        shrunk = raw * n / (n + shrink_k)
        effect = float(np.clip(shrunk, -cap, cap))
        out[_canonical(row["pollster"])] = {
            "pollster": row["pollster"],
            "n_polls": n,
            "mean_error": float(row["mean_error"]),
            "relative_error": round(raw, 3),
            "effect": round(effect, 3),
        }
    return out


def _match_house_effect(pollster: str, table: dict[str, dict]) -> dict | None:
    """Find a pollster's house-effect row by canonical name, tolerating the
    sponsor/partner decorations the live feeds add ("Elon University/YouGov",
    "Rasmussen Reports (R)")."""
    from src.data.pollster_ratings import _canonical

    if not pollster:
        return None
    name = _canonical(pollster).lower()
    if name in table:
        return table[name]
    for key, row in table.items():
        k = key.lower()
        if len(k) >= 5 and (k in name or name in k):
            return row
    return None


def _apply_house_effects(
    polls: list[Poll],
    dem_name: str | None,
    rep_name: str | None,
    table: dict[str, dict],
) -> tuple[list[Poll], dict]:
    """Return copies of ``polls`` with each matched pollster's house effect
    added to its Dem−Rep margin (half to each side), plus a coverage summary."""
    adjusted: list[Poll] = []
    n_adj, total_shift = 0, 0.0
    for poll in polls:
        row = _match_house_effect(poll.pollster, table)
        if row is None or not row["effect"] or not dem_name or not rep_name:
            adjusted.append(poll)
            continue
        half = row["effect"] / 2.0
        new_answers = []
        touched = False
        for a in poll.answers:
            if _find_candidate_pct({a.choice: a.pct}, dem_name) is not None:
                new_answers.append(dataclasses.replace(a, pct=a.pct + half))
                touched = True
            elif _find_candidate_pct({a.choice: a.pct}, rep_name) is not None:
                new_answers.append(dataclasses.replace(a, pct=a.pct - half))
                touched = True
            else:
                new_answers.append(a)
        if touched:
            n_adj += 1
            total_shift += row["effect"]
            adjusted.append(dataclasses.replace(poll, answers=new_answers))
        else:
            adjusted.append(poll)
    return adjusted, {
        "polls_adjusted": n_adj,
        "polls_total": len(polls),
        "mean_effect_applied": round(total_shift / n_adj, 3) if n_adj else 0.0,
    }


def _senate_payload(polls: list[Poll]) -> dict:
    engine = _build_engine_from_polls(polls) if polls else None
    states = _detect_senate_states(polls) or _US_STATES
    model = SenateModel(engine=engine) if engine else SenateModel()
    races = [model.race_average(polls, state) for state in states]
    races = [r for r in races if r.num_polls > 0]
    races.sort(key=lambda r: r.state)

    cycle = load_cycle_config()
    config_by_state = {entry["state"]: entry for entry in cycle["competitive_races"]}
    poll_cfg = cycle.get("polls", {})
    house_effects: dict[str, dict] = {}
    if poll_cfg.get("house_effect_correction"):
        house_effects = _house_effect_table(
            _load_forecast_calibration(),
            shrink_k=poll_cfg.get("house_effect_shrink_k", 10.0),
            cap=poll_cfg.get("house_effect_cap", 2.5),
        )
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
            # Track the configured nominee, but fall back to the party's
            # frontrunner when that name isn't in the polls (no settled primary,
            # or a candidate who has since dropped out).
            party_by_name = _party_by_candidate(polls, race.state)
            dem_name = _resolve_nominee(
                race.candidates, party_by_name, entry.get("dem_candidate"), "Democrat"
            )
            rep_name = _resolve_nominee(
                race.candidates, party_by_name, entry.get("rep_candidate"), "Republican"
            )
            # Without party tags a stale configured name resolves to nothing and
            # the race silently drops its polling margin (MI/NH ran on
            # fundamentals alone for weeks in 2026). If exactly one side is
            # identified, the other nominee is the top remaining name.
            dem_found = _find_candidate_pct(race.candidates, dem_name) is not None
            rep_found = _find_candidate_pct(race.candidates, rep_name) is not None
            if dem_found and not rep_found:
                rep_name = _top_other_candidate(race.candidates, dem_name) or rep_name
            elif rep_found and not dem_found:
                dem_name = _top_other_candidate(race.candidates, rep_name) or dem_name
            record["dem_candidate"] = dem_name
            record["rep_candidate"] = rep_name
            raw_margin = _dem_rep_margin(race.candidates, dem_name, rep_name)
            record["raw_dem_margin"] = raw_margin
            dem_margin = raw_margin
            if house_effects:
                # Re-average this race on house-effect-corrected polls.
                state_polls = [p for p in polls if race.state.lower() in p.subject.lower()]
                corrected, coverage = _apply_house_effects(
                    state_polls, dem_name, rep_name, house_effects
                )
                if coverage["polls_adjusted"]:
                    corrected_race = model.race_average(corrected, race.state)
                    record["candidates"] = corrected_race.candidates
                    record["margin"] = corrected_race.margin
                    dem_margin = _dem_rep_margin(corrected_race.candidates, dem_name, rep_name)
                record["house_effect"] = {
                    **coverage,
                    "adjustment": (
                        round(dem_margin - raw_margin, 2)
                        if dem_margin is not None and raw_margin is not None
                        else None
                    ),
                }
            record["dem_margin"] = dem_margin
            record["dem_win_prob"] = (
                round(prob_simulator.win_prob_from_margin(dem_margin), 4)
                if dem_margin is not None
                else None
            )

            vibes = vibes_model.adjustment_for_race(
                race_key, dem_name, rep_name
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
            record["market_urls"] = urls_for_race(market_odds, race_key)
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


def _load_economy():
    """EconomicSnapshot from data/fallback/economic.csv (None if absent)."""
    rows = load_economic_csv(FALLBACK_DIR / "economic.csv")
    return snapshot_from_rows(rows) if rows else None


def _senate_similarity(entries: list[dict], cfg: dict) -> np.ndarray | None:
    """Race-by-race similarity K (unit diagonal) from region and 2024 lean:
    ``K_ij = w·[same region] + (1−w)·exp(−|lean_i − lean_j| / scale)``."""
    if not cfg or float(cfg.get("similarity_share", 0.0)) <= 0.0:
        return None
    w = float(cfg.get("region_weight", 0.4))
    scale = float(cfg.get("lean_scale", 8.0))
    regions = np.array([e.get("region", e.get("abbr", "")) for e in entries])
    lean = np.array([float(e.get("pres_2024") or 0.0) for e in entries])
    k = w * (regions[:, None] == regions[None, :]) + (1.0 - w) * np.exp(
        -np.abs(lean[:, None] - lean[None, :]) / scale
    )
    np.fill_diagonal(k, 1.0)
    return k


def _calibration_bias(calib: dict, cycle_type: str = "all") -> tuple[float, int, list[int]]:
    """Mean polling error (actual − poll, Dem−Rep points) from the calibration
    rows, restricted to one kind of cycle.

    ``cycle_type``: ``"all"`` uses the pooled fitted bias; ``"midterm"`` /
    ``"presidential"`` average only the races from those cycles (midterm years
    are ≡ 2 mod 4). Returns ``(bias, n_races, years_used)``. Falls back to the
    pooled figure when no rows match.
    """
    rows = calib.get("rows") or []
    if cycle_type == "midterm":
        rows = [r for r in rows if r.get("year", 0) % 4 == 2]
    elif cycle_type == "presidential":
        rows = [r for r in rows if r.get("year", 0) % 4 == 0]
    elif cycle_type != "all":
        raise ValueError(f"unknown bias_cycle_type {cycle_type!r}")
    if cycle_type != "all" and rows:
        errors = [float(r["error"]) for r in rows if r.get("error") is not None]
        if errors:
            years = sorted({int(r["year"]) for r in rows})
            return float(sum(errors) / len(errors)), len(errors), years
    return float(calib.get("bias", 0.0)), int(calib.get("n_races", 0)), [
        int(y) for y in calib.get("cycles", [])
    ]


def _days_to_election(election_date: str | None, as_of: date | None = None) -> int:
    """Whole days from ``as_of`` (default today) to the configured election
    date, floored at 0 so the drift term vanishes on and after election day."""
    if not election_date:
        return 0
    as_of = as_of or date.today()
    return max(0, (date.fromisoformat(election_date) - as_of).days)


def _campaign_drift_sigma(per_sqrt_day: float | None, days: int) -> float:
    """Extra national-error SD for campaign movement still to come:
    ``per_sqrt_day · √days`` (a random walk in the national margin)."""
    if not per_sqrt_day or days <= 0:
        return 0.0
    return float(per_sqrt_day) * float(np.sqrt(days))


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
    as_of: date | None = None,
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
    blend_k = fund_cfg.get("blend_k", 3.0)
    w_p24 = fund_cfg.get("pres_2024_weight", 1.0)
    w_p20 = fund_cfg.get("pres_2020_shift_weight", 0.0)
    w_last = fund_cfg.get("last_senate_shift_weight", 0.0)
    incumbency_adv = fund_cfg.get("incumbency_advantage", 0.0)
    appointed_factor = fund_cfg.get("appointed_incumbent_factor", 0.5)
    tenure_schedule = fund_cfg.get("incumbent_tenure_schedule", {}) or {}
    office_schedule = fund_cfg.get("office_years_schedule", {}) or {}
    exp_win = fund_cfg.get("experience_per_statewide_win", 0.0)
    exp_loss = fund_cfg.get("experience_per_statewide_loss", 0.0)
    exp_cap = fund_cfg.get("experience_cap", 3.0)
    midterm_penalty = fund_cfg.get("midterm_penalty", 0.0)
    pres_party = cycle.get("national_environment", {}).get("president_party", "R").upper()
    econ_cfg = cycle.get("economy", {}) or {}
    economy = _load_economy()

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

    def _fundamentals(entry: dict) -> dict:
        """Dem−Rep fundamentals prior and every component behind it.

        lean         = pres_2024 + w20·(pres_2020 − pres_2024)
                       + wlast·(last Senate race − pres_2024)
        swing        = national midterm environment (approval + generic ballot)
        incumbency   = ±incumbency_advantage for the incumbent's party (binary;
                       × appointed factor when appointed)
        tenure       = incumbent's years in this seat, categorical schedule
        office_years = each non-incumbent candidate's years in elected office,
                       categorical schedule, net D − R
        record       = prior statewide general-election wins/losses, net D − R,
                       capped (an incumbent's wins for this seat are excluded)
        economy      = inflation (national) + state gas-price and
                       unemployment deviations, signed against the president
        midterm      = president's-party penalty (default 0)
        prior        = lean + swing + incumbency + tenure + office_years
                       + record + economy + midterm
        """
        feats = entry.get("features", {}) or {}
        p24, p20 = entry.get("pres_2024"), entry.get("pres_2020")
        last = feats.get("last_senate") or {}
        last_margin = last.get("margin")
        shift_20 = shift_last = 0.0
        if p24 is None:
            base = p20 if p20 is not None else last_margin
            if base is None:
                return {"available": False}
            lean = float(base)
        else:
            shift_20 = w_p20 * (p20 - p24) if p20 is not None else 0.0
            shift_last = w_last * (last_margin - p24) if last_margin is not None else 0.0
            lean = w_p24 * p24 + shift_20 + shift_last

        inc_party = feats.get("incumbent_party")
        inc_sign = 1.0 if inc_party == "D" else -1.0 if inc_party == "R" else 0.0
        inc_factor = appointed_factor if feats.get("incumbent_appointed") else 1.0
        incumbency = inc_sign * incumbency_adv * inc_factor
        tenure_cat, tenure_val = (
            schedule_lookup(tenure_schedule, feats.get("incumbent_years"))
            if inc_party
            else ("none", 0.0)
        )
        tenure = inc_sign * tenure_val

        dem_f, rep_f = feats.get("dem", {}) or {}, feats.get("rep", {}) or {}
        dem_cat, dem_oy = (
            ("incumbent", 0.0) if inc_party == "D"
            else schedule_lookup(office_schedule, dem_f.get("office_years"))
        )
        rep_cat, rep_oy = (
            ("incumbent", 0.0) if inc_party == "R"
            else schedule_lookup(office_schedule, rep_f.get("office_years"))
        )
        office_years = dem_oy - rep_oy

        def _exp(side: dict) -> float:
            return side.get("statewide_wins", 0) * exp_win + side.get(
                "statewide_losses", 0
            ) * exp_loss

        exp_raw = _exp(dem_f) - _exp(rep_f)
        experience = float(np.clip(exp_raw, -exp_cap, exp_cap))

        econ = economic_components(economy, econ_cfg, pres_party, entry.get("abbr"))

        midterm = 0.0
        if midterm_penalty and cycle.get("cycle", 0) % 4 == 2:
            midterm = midterm_penalty if pres_party == "R" else -midterm_penalty

        prior = (
            lean + national_swing + incumbency + tenure + office_years + experience
            + econ["total"] + midterm
        )
        return {
            "available": True,
            "pres_2024": p24,
            "pres_2020": p20,
            "last_senate": last or None,
            "lean_weights": {
                "pres_2024": w_p24, "pres_2020_shift": w_p20, "last_senate_shift": w_last,
            },
            "pres_2020_shift_effect": round(shift_20, 3),
            "last_senate_shift_effect": round(shift_last, 3),
            "lean": round(lean, 3),
            "national_swing": round(national_swing, 3),
            "incumbent_party": inc_party,
            "incumbent_years": feats.get("incumbent_years"),
            "incumbent_appointed": bool(feats.get("incumbent_appointed", False)),
            "incumbency_advantage": incumbency_adv,
            "incumbency_effect": round(incumbency, 3),
            "tenure_category": tenure_cat,
            "tenure_effect": round(tenure, 3),
            "dem_office_years": dem_f.get("office_years"),
            "rep_office_years": rep_f.get("office_years"),
            "dem_office_category": dem_cat,
            "rep_office_category": rep_cat,
            "office_years_effect": round(office_years, 3),
            "dem_statewide_wins": dem_f.get("statewide_wins", 0),
            "dem_statewide_losses": dem_f.get("statewide_losses", 0),
            "rep_statewide_wins": rep_f.get("statewide_wins", 0),
            "rep_statewide_losses": rep_f.get("statewide_losses", 0),
            "experience_raw": round(exp_raw, 3),
            "experience_effect": round(experience, 3),
            "economy": econ,
            "economy_effect": econ["total"],
            "midterm_penalty_effect": round(midterm, 3),
            "prior": round(prior, 3),
        }

    def _fundamentals_margin(entry: dict) -> float | None:
        f = _fundamentals(entry)
        return f["prior"] if f.get("available") else None

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
            fund_detail = _fundamentals(entry)
            fund = fund_detail["prior"] if fund_detail.get("available") else None
            n = rr.get("num_polls", 0)
            # Blend polls with fundamentals; fundamentals weight = k/(k+n) so it
            # anchors thin-poll races and fades as polls accumulate.
            if poll_margin is None:
                margin, w = fund, 1.0
            elif fund is None:
                margin, w = poll_margin, 0.0
            else:
                w = blend_k / (blend_k + n)
                margin = (1.0 - w) * poll_margin + w * fund
            fund_detail.update(
                poll_margin=poll_margin,
                num_polls=n,
                fundamentals_weight=round(w, 3),
                blend_k=blend_k,
                final_margin=round(margin, 3) if margin is not None else None,
            )
            if apply_vibes and margin is not None:
                vibes = rr.get("vibes") or {}
                if vibes.get("available"):
                    margin = margin + vibes.get("adjustment", 0.0)
            out.append(
                RaceInput(
                    state=entry["state"],
                    race=entry["race"],
                    # The nominee the polls actually track (see _senate_payload),
                    # falling back to the configured name when there are no polls.
                    dem_candidate=rr.get("dem_candidate") or entry["dem_candidate"],
                    rep_candidate=rr.get("rep_candidate") or entry["rep_candidate"],
                    margin=round(margin, 3) if margin is not None else None,
                    num_polls=n,
                    market_dem_prob=market_dem_prob,
                    fundamentals=fund_detail,
                )
            )
        return out

    inputs = _build_inputs(apply_vibes=False)

    calib = _load_forecast_calibration()
    fcfg = cycle.get("forecast", {})
    bias_weight = fcfg.get("calibration_bias_weight", 0.5)
    bias_cycle_type = fcfg.get("bias_cycle_type", "all")
    days_left = _days_to_election(fcfg.get("election_date"), as_of)
    drift_sigma = _campaign_drift_sigma(fcfg.get("campaign_drift_per_sqrt_day"), days_left)
    sim_kwargs: dict = {}
    bias_info: dict = {
        "cycle_type": bias_cycle_type,
        "weight": bias_weight,
        "raw_bias": None,
        "n_races": 0,
        "years": [],
        "applied": 0.0,
    }
    if calib.get("usable"):
        raw_bias, n_bias, bias_years = _calibration_bias(calib, bias_cycle_type)
        applied_bias = round(raw_bias * bias_weight, 3)
        bias_info.update(
            raw_bias=round(raw_bias, 3), n_races=n_bias, years=bias_years, applied=applied_bias
        )
        national_sigma = round(float(np.hypot(calib["national_sigma"], drift_sigma)), 3)
        sim_kwargs = {
            "national_sigma": national_sigma,
            "race_sigma": calib["race_sigma"],
            "bias": applied_bias,
        }
        if not quiet:
            print(
                f"  using calibrated error model (σ_nat={calib['national_sigma']}"
                f"{f' ⊕ drift {drift_sigma:.2f} = {national_sigma}' if drift_sigma else ''}, "
                f"σ_race={calib['race_sigma']}, bias[{bias_cycle_type}, "
                f"{n_bias} races {bias_years}]={raw_bias:.3f}×{bias_weight}={applied_bias}; "
                f"{days_left} days to election)"
            )
    elif drift_sigma:
        sim_kwargs["national_sigma"] = round(
            float(np.hypot(DEFAULT_NATIONAL_SIGMA, drift_sigma)), 3
        )
    if "market_weight" in fcfg:
        sim_kwargs["market_weight"] = float(fcfg["market_weight"])
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
    corr_cfg = cycle.get("correlation", {}) or {}
    similarity = _senate_similarity(cycle["competitive_races"], corr_cfg)
    sim_share = float(corr_cfg.get("similarity_share", 0.0))
    forecast = simulator.simulate(
        inputs,
        num_simulations=NUM_SIMULATIONS,
        seed=SIMULATION_SEED,
        as_of=as_of,
        market_control_dem_prob=market_control_dem_prob,
        similarity=similarity,
        similarity_share=sim_share,
    )
    # Same simulation with the experimental NYT-vibes overlay applied, for
    # side-by-side comparison. (Vibes data is a neutral placeholder until the
    # NYT pipeline runs with a key, so today this matches the base forecast.)
    vibes_forecast = simulator.simulate(
        _build_inputs(apply_vibes=True),
        num_simulations=NUM_SIMULATIONS,
        seed=SIMULATION_SEED,
        as_of=as_of,
        similarity=similarity,
        similarity_share=sim_share,
    )
    payload = dataclasses.asdict(forecast)
    # JSON object keys must be strings.
    payload["seat_distribution"] = {
        str(k): v for k, v in forecast.seat_distribution.items()
    }
    # Market page links so the site can send readers to the source market.
    for race_dict in payload.get("races", []):
        race_dict["market_urls"] = urls_for_race(market_odds, race_dict["race"])
    payload["market_control_urls"] = urls_for_race(market_odds, SENATE_CONTROL_RACE)
    payload["maturity"] = "nowcast"
    payload["label"] = (
        "Where the race stands today — current polling averages blended with "
        "prediction-market odds. A work in progress from Policy y Peaches."
    )
    # Fundamentals blend (2024 + 2020 presidential lean) and the NYT-vibes
    # variant of the chamber forecast, for comparison.
    payload["fundamentals_blend_k"] = blend_k
    # Fundamentals coefficients actually applied this run (see config comment).
    payload["fundamentals_coefficients"] = {
        "pres_2024_weight": w_p24,
        "pres_2020_shift_weight": w_p20,
        "last_senate_shift_weight": w_last,
        "blend_k": blend_k,
        "incumbency_advantage": incumbency_adv,
        "appointed_incumbent_factor": appointed_factor,
        "incumbent_tenure_schedule": {
            k: v for k, v in tenure_schedule.items() if not k.startswith("_")
        },
        "office_years_schedule": {
            k: v for k, v in office_schedule.items() if not k.startswith("_")
        },
        "experience_per_statewide_win": exp_win,
        "experience_per_statewide_loss": exp_loss,
        "experience_cap": exp_cap,
        "midterm_penalty": midterm_penalty,
        "economy": {k: v for k, v in econ_cfg.items() if not k.startswith("_")},
    }
    payload["economy"] = economy.to_dict() if economy is not None else {"available": False}
    payload["dem_control_prob_with_vibes"] = vibes_forecast.dem_control_prob
    payload["mean_dem_seats_with_vibes"] = vibes_forecast.mean_dem_seats
    # National midterm environment (presidential approval + generic ballot)
    # folded into the fundamentals prior, exposed for transparency in the UI.
    payload["national_environment"] = env
    # Error-model provenance: which calibration cycles the bias came from and
    # how much forward-looking campaign drift was added to the national sigma.
    payload["bias_calibration"] = bias_info
    payload["correlation"] = {
        "similarity_share": sim_share,
        "region_weight": corr_cfg.get("region_weight"),
        "lean_scale": corr_cfg.get("lean_scale"),
        "regions": {e["state"]: e.get("region") for e in cycle["competitive_races"]},
    }
    # House-effect correction summary per race (from senate.json records).
    payload["house_effects"] = {
        s: r.get("house_effect")
        for s, r in races_by_state.items()
        if r.get("house_effect") is not None
    }
    payload["election_date"] = fcfg.get("election_date")
    payload["days_to_election"] = days_left
    payload["campaign_drift_sigma"] = round(drift_sigma, 3)
    payload["polling_national_sigma"] = (
        calib["national_sigma"] if calib.get("usable") else DEFAULT_NATIONAL_SIGMA
    )
    return payload


def _house_forecast_payload(
    gb_current,
    approval_net: float | None,
    overrides: dict | None = None,
    quiet: bool = False,
    as_of: date | None = None,
) -> dict:
    """435-district House-control simulation → house_forecast.json.

    ``gb_current`` is the GenericBallotSnapshot (dem_pct / rep_pct); the model
    works on its two-party margin. ``overrides`` deep-merge onto
    config/house_2026.json for sensitivity sweeps.
    """
    cfg = load_house_config()
    if overrides:
        cfg = _deep_merge(cfg, overrides)
    lean_cfg = cfg.get("district_lean", {})
    corr_cfg = cfg.get("correlation", {}) or {}
    sf_cfg = cfg.get("state_fundamentals", {}) or {}
    econ_cfg = cfg.get("economy", {}) or {}
    pres_party = econ_cfg.get(
        "president_party", cfg.get("national_environment", {}).get("president_party", "R")
    )
    economy = _load_economy()
    state_pres = load_state_presidential(
        FALLBACK_DIR / sf_cfg.get("csv", "state_presidential.csv")
    )
    # Per-state economic adjustment (gas + unemployment deviations); the
    # national inflation term enters the expected national margin instead.
    state_adjust: dict = {}
    for st in state_pres:
        comp = economic_components(economy, econ_cfg, pres_party, st)
        state_adjust[st] = (comp["gas_effect"] + comp["unemployment_effect"], comp)
    nat = next(iter(state_pres.values()), {}) if state_pres else {}
    national_trend = float(nat.get("national_2024", 0.0)) - float(nat.get("national_2020", 0.0))
    districts = load_districts(
        FALLBACK_DIR / cfg.get("districts_csv", "house_districts_2024.csv"),
        open_seats=lean_cfg.get("open_seats", {}).get("districts", []),
        state_pres=state_pres,
        state_adjust=state_adjust,
    )

    gb_two_party = (
        round(two_party_margin(gb_current.dem_pct, gb_current.rep_pct), 3)
        if gb_current is not None
        else None
    )
    nat_econ = economic_components(economy, econ_cfg, pres_party, None)
    env = _house_expected_margin(cfg, gb_two_party, approval_net, economy=nat_econ)
    if env["expected"] is None:
        return {"available": False, "reason": "no generic-ballot or approval signal"}

    ncfg = cfg.get("national_environment", {})
    polling_sigma = float(ncfg.get("generic_ballot_sigma", 2.5))
    days_left = _days_to_election(cfg.get("election_date"), as_of)
    drift_sigma = _campaign_drift_sigma(cfg.get("campaign_drift_per_sqrt_day"), days_left)
    national_sigma = float(np.hypot(polling_sigma, drift_sigma))
    dcfg = cfg.get("district_error", {})

    simulator = HouseForecastSimulator(
        baseline_margin=float(cfg["baseline"]["two_party_margin"]),
        national_sigma=national_sigma,
        district_sigma=float(dcfg.get("district_sigma", 6.5)),
        tail_dof=ncfg.get("national_tail_dof", 5),
        dem_majority_threshold=int(cfg.get("dem_majority_threshold", 218)),
        total_seats=int(cfg.get("total_seats", 435)),
        redistricting=cfg.get("redistricting", {}).get("states", []),
        lean_weight_2024=float(lean_cfg.get("weight_2024", 1.0)),
        lean_weight_2022=float(lean_cfg.get("weight_2022", 0.0)),
        incumbency_advantage=float(lean_cfg.get("incumbency_advantage", 0.0)),
        similarity_share=float(corr_cfg.get("similarity_share", 0.0)),
        similarity_weights=corr_cfg.get("weights"),
        lean_scale=float(corr_cfg.get("lean_scale", 10.0)),
        regions=corr_cfg.get("regions"),
        state_trend_weight=float(sf_cfg.get("state_trend_weight", 0.0)),
        national_trend=national_trend,
    )
    forecast = simulator.simulate(
        districts,
        expected_national_margin=env["expected"],
        num_simulations=NUM_SIMULATIONS,
        seed=SIMULATION_SEED,
        as_of=as_of,
        curve_margins=cfg.get("seats_votes_curve_margins"),
        generic_ballot_two_party=gb_two_party,
        approval_implied_margin=env["approval_implied"],
        generic_ballot_bias=env.get("bias", 0.0),
        polling_sigma=polling_sigma,
        campaign_drift_sigma=drift_sigma,
        days_to_election=days_left,
    )
    if not quiet:
        print(
            f"  house: generic two-party {gb_two_party:+.2f}, approval-implied "
            f"{env['approval_implied']:+.2f} → expected national {env['expected']:+.2f} "
            f"(bias {env.get('bias', 0.0):+.1f}, inflation {nat_econ['inflation_effect']:+.2f}); "
            f"swing {forecast.national_swing:+.2f}; "
            f"σ_nat={polling_sigma} ⊕ drift {drift_sigma:.2f} = {national_sigma:.2f}, "
            f"σ_district={simulator.district_sigma}; lean {simulator.lean_weight_2024:.2f}×2024 "
            f"+ {simulator.lean_weight_2022:.2f}×2022, {forecast.num_open_seats} open seats "
            f"(−{simulator.incumbency_advantage} pts); redistricting net "
            f"{simulator.redistricting_shift_mean:+.0f} seats → P(D majority)="
            f"{forecast.dem_majority_prob:.3f}, mean {forecast.mean_dem_seats:.1f} seats"
        )

    payload = dataclasses.asdict(forecast)
    payload["seat_distribution"] = {str(k): v for k, v in forecast.seat_distribution.items()}
    payload["available"] = True
    payload["maturity"] = "forecast-lite"
    payload["label"] = (
        "Where the House stands today — the generic ballot and presidential approval "
        "swung uniformly across all 435 districts, with correlated national error and "
        "district-level noise. A work in progress from Policy y Peaches."
    )
    payload["raw_national_margin"] = env["raw"]
    payload["economy"] = {
        "snapshot": economy.to_dict() if economy is not None else {"available": False},
        "coefficients": {k: v for k, v in econ_cfg.items() if not k.startswith("_")},
        "national": nat_econ,
    }
    payload["state_trend"] = {
        "weight": float(sf_cfg.get("state_trend_weight", 0.0)),
        "national_trend_2020_to_2024": national_trend,
    }
    payload["generic_ballot_raw_margin"] = (
        round(gb_current.margin, 2) if gb_current is not None else None
    )
    payload["approval_net"] = approval_net
    payload["num_districts"] = len(districts)
    payload["num_competitive"] = len(forecast.competitive)
    payload["election_date"] = cfg.get("election_date")
    # The full per-district list is ~435 rows; keep it (the page renders the
    # competitive subset and a per-state rollup) but drop the duplicate copy
    # the competitive list would otherwise carry.
    payload["competitive"] = [f.label for f in forecast.competitive]
    seats_by_party_2024 = {
        "D": sum(1 for d in districts if d.winner_2024 == "D"),
        "R": sum(1 for d in districts if d.winner_2024 == "R"),
    }
    payload["seats_2024"] = seats_by_party_2024
    # Districts in states redrawn since 2024 are simulated on their *old* lines
    # (the state's net effect enters via the redistricting shift), so their
    # per-district numbers are flagged rather than presented as live seats.
    redrawn = sorted({r["state"] for r in simulator.redistricting})
    payload["redrawn_states"] = redrawn
    for d in payload["districts"]:
        d["redrawn"] = d["state"] in redrawn
    # Expected flips: 2024 R seats now favoured D, and vice versa.
    payload["expected_flips"] = {
        "r_to_d": round(sum(f.dem_win_prob for f in forecast.districts if f.winner_2024 == "R"), 1),
        "d_to_r": round(
            sum(1.0 - f.dem_win_prob for f in forecast.districts if f.winner_2024 == "D"), 1
        ),
    }
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

    # House control: uniform swing of the national environment over 435
    # districts (config/house_2026.json + data/fallback/house_districts_2024.csv).
    _write("house_forecast.json", _house_forecast_payload(gb_current, approval_net))

    def _latest_poll(polls: list[Poll]) -> str | None:
        dates = [p.midpoint_date for p in polls if p.midpoint_date]
        return max(dates).isoformat() if dates else None

    def _stale_feeds(threshold_days: int = 3) -> list[str]:
        """Feeds whose newest poll ended more than threshold_days ago."""
        out = []
        for name, polls in (
            ("approval", approval_polls),
            ("generic_ballot", gb_polls),
            ("senate", senate_polls),
        ):
            ends = [p.end_date for p in polls]
            if not ends or (date.today() - max(ends)).days > threshold_days:
                out.append(name)
        return out

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
        # Feeds whose newest poll is >3 days old at export time. The site
        # badges these; scripts/check_staleness.py alerts on them in CI.
        "stale_feeds": _stale_feeds(),
    }
    _write("meta.json", meta)

    print("Done.")


if __name__ == "__main__":
    main()
