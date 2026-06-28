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


def calibrate(min_year: int, max_year: int, lookback_days: int) -> dict:
    loader = TrainingDataLoader(
        cache_dir=RAW_CACHE, lookback_days=lookback_days, min_polls=2
    )
    races = loader.load(offices=["senate"], min_year=min_year, max_year=max_year)
    logger.info("Loaded %d senate training races", len(races))

    engine = PollingAverageEngine()
    rows: list[dict] = []
    for race in races:
        poll_margin = _dem_rep_poll_margin(race, engine)
        if poll_margin is None:
            continue
        actual_margin = race.actual_dem_share - race.actual_rep_share
        rows.append(
            {
                "race_id": race.race_id,
                "year": race.year,
                "poll_margin": round(poll_margin, 2),
                "actual_margin": round(actual_margin, 2),
                "error": round(actual_margin - poll_margin, 2),  # actual − poll
                "dem_won": bool(race.dem_won),
            }
        )

    logger.info("Usable races with a clean D−R matchup: %d", len(rows))
    for r in rows:
        logger.info(
            "  %-18s poll D%+.1f  actual D%+.1f  err %+.1f",
            r["race_id"], r["poll_margin"], r["actual_margin"], r["error"],
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

    logger.info(
        "Fitted: bias=%+.2f  national_sigma=%.2f  race_sigma=%.2f  total_sigma=%.2f",
        bias, national_sigma, race_sigma, total_sigma,
    )
    logger.info("Validation: win_accuracy=%.1f%%  brier=%.3f", win_acc * 100, brier)

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
        "win_accuracy": round(win_acc, 4),
        "brier_score": round(brier, 4),
        "reliability": reliability,
        "default_national_sigma": DEFAULT_NATIONAL_SIGMA,
        "default_race_sigma": DEFAULT_RACE_SIGMA,
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate the Senate forecast error model.")
    parser.add_argument("--min-year", type=int, default=2016)
    parser.add_argument("--max-year", type=int, default=2022)
    parser.add_argument("--lookback-days", type=int, default=21)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    result = calibrate(args.min_year, args.max_year, args.lookback_days)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    print(f"Wrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)} (usable={result.get('usable')})")


if __name__ == "__main__":
    main()
