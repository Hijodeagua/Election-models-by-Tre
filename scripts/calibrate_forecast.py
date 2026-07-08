"""Calibrate the Senate forecast's error model against historical results.

The chamber simulation turns a Dem−Rep polling margin into a win probability
with a normal error model: ``P(D) = Φ((margin + bias) / σ_total)`` where
``σ_total = hypot(national_sigma, race_sigma)``. Those three numbers decide how
confident every probability on the site is, so they should be *fitted* to how
far real Senate polling has missed — not eyeballed.

This script does that backtest:

1. Load historical Senate races (538 archive polls + MEDSL actual results) via
   the existing TrainingDataLoader — one record per race with its late polls
   and the actual outcome.
2. For each race compute the final weighted polling margin (our engine) and the
   actual margin; the signed error is ``actual − poll``.
3. Decompose the errors:
     * ``bias``            = mean error (positive ⇒ polls understated Democrats)
     * ``national_sigma``  = spread of each cycle's *mean* error (correlated miss)
     * ``race_sigma``      = spread of the within-cycle residuals (idiosyncratic)
4. Validate: score every race with the fitted model and report win accuracy,
   Brier score, and a reliability table (predicted vs. actual win rate by bin).
5. Write ``config/forecast_calibration.json``, which scripts/export_json.py
   loads to parameterise the live simulation.

Data is fetched from public GitHub mirrors, so this runs in CI (the dev sandbox
has no outbound network). It is read-only except for the JSON it writes.

Usage:
    python scripts/calibrate_forecast.py
    python scripts/calibrate_forecast.py --min-year 2016 --lookback-days 21
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.models.polling_average import PollingAverageEngine  # noqa: E402
from src.models.senate_simulation import (  # noqa: E402
    DEFAULT_NATIONAL_SIGMA,
    DEFAULT_RACE_SIGMA,
)
from src.training.data_loader import TrainingDataLoader, _election_day  # noqa: E402

logger = logging.getLogger(__name__)

OUTPUT_PATH = PROJECT_ROOT / "config" / "forecast_calibration.json"
RAW_CACHE = PROJECT_ROOT / "data" / "raw"

# Below this many usable races the fit is too noisy to trust — we still write
# the file (for inspection) but mark it not-usable so export keeps the defaults.
MIN_RACES_FOR_USE = 20


def _dem_rep_poll_margin(race, engine: PollingAverageEngine) -> float | None:
    """Final weighted Dem−Rep polling margin for one historical race.

    Uses the same engine the live site uses, as of election day, and maps the
    averaged choices back to the Democratic/Republican candidate by surname.
    """
    election_day = _election_day(race.year)
    result = engine.compute_average(race.polls, as_of=election_day)
    if not result.averages:
        return None

    def _match(target: str) -> float | None:
        if not target:
            return None
        surname = target.split()[-1].lower()
        for choice, pct in result.averages.items():
            if surname and surname in choice.lower():
                return pct
        return None

    dem = _match(race.dem_candidate)
    rep = _match(race.rep_candidate)
    if dem is None or rep is None:
        return None
    return dem - rep


def _poll_dem_rep_margin(poll, dem_candidate: str, rep_candidate: str) -> float | None:
    """A single poll's own Dem−Rep margin, matching answers by candidate surname."""
    answers = {a.choice.lower(): a.pct for a in poll.answers}

    def _match(target: str) -> float | None:
        if not target:
            return None
        surname = target.split()[-1].lower()
        for choice, pct in answers.items():
            if surname and surname in choice:
                return pct
        return None

    dem = _match(dem_candidate)
    rep = _match(rep_candidate)
    if dem is None or rep is None:
        return None
    return dem - rep


def _pollster_bias(pollster_errs: dict[str, list[float]], min_polls: int = 5) -> list[dict]:
    """Mean error (actual − poll) per pollster with enough polls — the house effect."""
    out = []
    for name, errs in pollster_errs.items():
        if len(errs) >= min_polls:
            arr = np.array(errs, dtype=float)
            out.append(
                {
                    "pollster": name,
                    "n_polls": len(errs),
                    "mean_error": round(float(arr.mean()), 2),
                    "std_error": round(float(arr.std(ddof=1)) if len(errs) > 1 else 0.0, 2),
                }
            )
    # Most Dem-leaning (negative) first.
    return sorted(out, key=lambda x: x["mean_error"])


def _build_rows(
    races: list, engine: PollingAverageEngine
) -> tuple[list[dict], dict, dict]:
    """Per-race poll-vs-actual error rows for one office.

    Also returns per-pollster errors (the national house effect) and per-state
    per-pollster errors (the in-state track record), both as
    ``{name: [error, ...]}`` / ``{state: {name: [error, ...]}}``.
    """
    rows: list[dict] = []
    pollster_errs: dict[str, list[float]] = {}
    state_pollster_errs: dict[str, dict[str, list[float]]] = {}
    for race in races:
        poll_margin = _dem_rep_poll_margin(race, engine)
        if poll_margin is None:
            continue
        actual_margin = race.actual_dem_share - race.actual_rep_share
        state = race.race_id.split("-")[0]
        rows.append(
            {
                "race_id": race.race_id,
                "state": state,
                "year": race.year,
                "poll_margin": round(poll_margin, 2),
                "actual_margin": round(actual_margin, 2),
                "error": round(actual_margin - poll_margin, 2),  # actual − poll
                "dem_won": bool(race.dem_won),
            }
        )
        for poll in race.polls:
            pm = _poll_dem_rep_margin(poll, race.dem_candidate, race.rep_candidate)
            if pm is not None:
                err = actual_margin - pm
                name = poll.pollster or "Unknown"
                pollster_errs.setdefault(name, []).append(err)
                state_pollster_errs.setdefault(state, {}).setdefault(name, []).append(err)
    return rows, pollster_errs, state_pollster_errs


def _state_pollster_bias(
    state_pollster_errs: dict[str, dict[str, list[float]]], min_polls: int = 2
) -> dict[str, list[dict]]:
    """Per-state, per-pollster mean error (actual − poll) — the in-state track
    record. Samples are thin, so this is gated at ``min_polls`` and meant as a
    directional signal, not a precise grade."""
    out: dict[str, list[dict]] = {}
    for state, pmap in state_pollster_errs.items():
        entries = []
        for name, errs in pmap.items():
            if len(errs) >= min_polls:
                arr = np.array(errs, dtype=float)
                entries.append(
                    {
                        "pollster": name,
                        "n_polls": len(errs),
                        "mean_error": round(float(arr.mean()), 2),
                        "std_error": round(
                            float(arr.std(ddof=1)) if len(errs) > 1 else 0.0, 2
                        ),
                    }
                )
        if entries:
            out[state] = sorted(entries, key=lambda x: x["mean_error"])
    return out


def _state_bias(rows: list[dict]) -> dict[str, dict]:
    """Mean polling error by state, for cross-office comparison."""
    by: dict[str, list[float]] = {}
    for r in rows:
        by.setdefault(r["state"], []).append(r["error"])
    return {s: {"bias": round(float(np.mean(e)), 2), "n": len(e)} for s, e in by.items()}


def calibrate(
    min_year: int,
    max_year: int,
    lookback_days: int,
    control_offices: list[str] | None = None,
) -> dict:
    control_offices = control_offices if control_offices is not None else ["governor"]
    loader = TrainingDataLoader(
        cache_dir=RAW_CACHE, lookback_days=lookback_days, min_polls=2
    )
    all_races = loader.load(
        offices=["senate"] + control_offices, min_year=min_year, max_year=max_year
    )
    by_office: dict[str, list] = {}
    for race in all_races:
        by_office.setdefault(race.office, []).append(race)
    logger.info("Loaded races by office: %s", {o: len(rs) for o, rs in by_office.items()})

    engine = PollingAverageEngine()
    rows, pollster_errs, state_pollster_errs = _build_rows(
        by_office.get("senate", []), engine
    )

    logger.info("Usable senate races with a clean D−R matchup: %d", len(rows))
    for r in rows:
        logger.info(
            "  %-18s poll D%+.1f  actual D%+.1f  err %+.1f",
            r["race_id"], r["poll_margin"], r["actual_margin"], r["error"],
        )

    # ── Cross-office control: statewide governor races as a check on the
    # state-level Senate polling bias (off-year; use agreement, not the level) ──
    control: dict[str, dict] = {}
    cross_office: list[dict] = []
    senate_state = _state_bias(rows)
    for office in control_offices:
        o_rows, _, _ = _build_rows(by_office.get(office, []), engine)
        if not o_rows:
            continue
        o_err = np.array([r["error"] for r in o_rows], dtype=float)
        o_state = _state_bias(o_rows)
        control[office] = {
            "n_races": len(o_rows),
            "cycles": sorted({r["year"] for r in o_rows}),
            "bias": round(float(o_err.mean()), 3),
            "sigma": round(float(o_err.std(ddof=1)), 3) if len(o_rows) > 1 else 0.0,
            "by_state": o_state,
        }
        logger.info(
            "Control [%s]: n=%d bias=%+.2f sigma=%.2f",
            office, len(o_rows), float(o_err.mean()),
            float(o_err.std(ddof=1)) if len(o_rows) > 1 else 0.0,
        )
        for st, sb in senate_state.items():
            if st in o_state:
                cross_office.append(
                    {
                        "state": st,
                        "senate_bias": sb["bias"],
                        "senate_n": sb["n"],
                        f"{office}_bias": o_state[st]["bias"],
                        f"{office}_n": o_state[st]["n"],
                    }
                )

    if len(rows) < 2:
        logger.warning("Not enough races to calibrate — writing a not-usable stub.")
        return {
            "usable": False,
            "n_races": len(rows),
            "national_sigma": DEFAULT_NATIONAL_SIGMA,
            "race_sigma": DEFAULT_RACE_SIGMA,
            "bias": 0.0,
            "rows": rows,
        }

    errors = np.array([r["error"] for r in rows], dtype=float)
    years = sorted({r["year"] for r in rows})

    bias = float(errors.mean())
    overall_sigma = float(np.std(errors, ddof=1))
    cycle_means = {y: float(errors[[r["year"] == y for r in rows]].mean()) for y in years}

    # Decompose total error into a shared national component (variance of the
    # per-cycle mean error) and an idiosyncratic per-race component (within-cycle
    # residuals). This needs at least two cycles.
    single_cycle_split = len(years) < 2
    if not single_cycle_split:
        residuals = np.array([r["error"] - cycle_means[r["year"]] for r in rows], dtype=float)
        national_sigma = float(np.std(list(cycle_means.values()), ddof=1))
        race_sigma = float(np.std(residuals, ddof=1))
    else:
        # One cycle only: we can't separate correlated vs idiosyncratic error
        # empirically. Keep the empirically-calibrated *total*, but split it with
        # a literature ratio (correlated ≈ 0.5× idiosyncratic; Shirani-Mehr et al.
        # 2018) so the chamber simulation still carries a national-error term
        # rather than treating every race as independent (which would be
        # overconfident about sweeps).
        national_sigma = round(0.45 * overall_sigma, 3)
        race_sigma = round(float(np.sqrt(max(overall_sigma**2 - national_sigma**2, 0.0))), 3)
    total_sigma = float(np.hypot(national_sigma, race_sigma))

    # ── Validation: how well do the fitted params predict past winners? ──────
    from scipy.stats import norm

    probs = norm.cdf((errors * 0 + np.array([r["poll_margin"] for r in rows]) + bias) / total_sigma)
    actual = np.array([1.0 if r["dem_won"] else 0.0 for r in rows])
    brier = float(np.mean((probs - actual) ** 2))
    win_acc = float(np.mean((probs >= 0.5) == (actual == 1.0)))

    # Reliability table: predicted vs. realised Dem win rate by probability bin.
    bins = [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]
    reliability = []
    for lo, hi in bins:
        mask = (probs >= lo) & (probs < hi)
        n = int(mask.sum())
        reliability.append(
            {
                "bin": f"{int(lo*100)}-{int(hi*100)}%",
                "n": n,
                "predicted": round(float(probs[mask].mean()), 3) if n else None,
                "actual": round(float(actual[mask].mean()), 3) if n else None,
            }
        )

    # ── Tail comparison: Gaussian vs variance-matched Student-t ─────────────
    # Scores the same fitted bias/sigma under fat-tailed error, to ground the
    # tail_dof knob in evidence rather than taste (audit item 8). The t draws
    # are variance-matched (scale = σ·√((ν−2)/ν)) so only tail shape varies.
    from scipy.stats import t as student_t

    margins_arr = np.array([r["poll_margin"] for r in rows])
    clip = lambda p: np.clip(p, 1e-6, 1 - 1e-6)  # noqa: E731

    def _scores(p: np.ndarray) -> dict[str, float]:
        p = clip(p)
        return {
            "brier": round(float(np.mean((p - actual) ** 2)), 4),
            "log_loss": round(
                float(-np.mean(actual * np.log(p) + (1 - actual) * np.log(1 - p))), 4
            ),
        }

    tail_comparison: dict[str, dict[str, float]] = {
        "gaussian": _scores(norm.cdf((margins_arr + bias) / total_sigma))
    }
    for dof in (10, 7, 5, 3):
        scale = total_sigma * np.sqrt((dof - 2) / dof)
        tail_comparison[f"t{dof}"] = _scores(
            student_t.cdf((margins_arr + bias) / scale, df=dof)
        )

    logger.info(
        "Fitted: bias=%+.2f  national_sigma=%.2f  race_sigma=%.2f  total_sigma=%.2f",
        bias, national_sigma, race_sigma, total_sigma,
    )
    logger.info("Validation: win_accuracy=%.1f%%  brier=%.3f", win_acc * 100, brier)
    logger.info("Tail comparison: %s", tail_comparison)

    return {
        "usable": len(rows) >= MIN_RACES_FOR_USE,
        "source": "538 archive polls (FiveThirtyEight) + MEDSL official results",
        "cycles": years,
        "n_races": len(rows),
        "lookback_days": lookback_days,
        "bias": round(bias, 3),
        "national_sigma": round(national_sigma, 3),
        "race_sigma": round(race_sigma, 3),
        "total_sigma": round(total_sigma, 3),
        "overall_sigma": round(overall_sigma, 3),
        "single_cycle_split": single_cycle_split,
        "cycle_mean_error": {str(y): round(v, 2) for y, v in cycle_means.items()},
        "pollster_bias": _pollster_bias(pollster_errs),
        "state_pollster_bias": _state_pollster_bias(state_pollster_errs),
        "control": control,
        "cross_office_state_bias": cross_office,
        "win_accuracy": round(win_acc, 4),
        "brier_score": round(brier, 4),
        "tail_comparison": tail_comparison,
        "reliability": reliability,
        "default_national_sigma": DEFAULT_NATIONAL_SIGMA,
        "default_race_sigma": DEFAULT_RACE_SIGMA,
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate the Senate forecast error model.")
    parser.add_argument("--min-year", type=int, default=2016)
    parser.add_argument("--max-year", type=int, default=2024)
    parser.add_argument("--lookback-days", type=int, default=21)
    parser.add_argument(
        "--control-offices", nargs="*", default=["governor"],
        choices=["governor", "house"],
        help="Statewide off-year races used as a polling-bias control (default: governor).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    result = calibrate(
        args.min_year, args.max_year, args.lookback_days,
        control_offices=args.control_offices,
    )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    print(f"Wrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)} (usable={result.get('usable')})")


if __name__ == "__main__":
    main()
