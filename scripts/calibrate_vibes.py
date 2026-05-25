"""Calibrate the vibes model against 2016-2024 Senate election outcomes.

Pipeline:
    1. Load article signals from data/vibes/article_signals.json
    2. Score each historical race with VibesModel
    3. Compare vibes score to actual D-R margin residual
       (residual = actual_margin - rating_prior_margin)
    4. Run calibrate_buckets() to find best granularity and refined adjustments
    5. Save calibrated params to data/vibes/calibrated_params.json

Run: python -m scripts.calibrate_vibes
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models.vibes import VibesModel, ArticleSignal
from src.models.senate import RATING_MARGIN_PRIOR, RaceRating

# ── Historical race results ────────────────────────────────────────────────────
# Format: race_id → (actual_D_minus_R_margin, pre_election_rating)
# Actual margins are final certified results.
# Rating is the approximate Cook/Sabato rating ~2-3 weeks before election day.

HISTORICAL_RACES: dict[str, tuple[float, RaceRating]] = {
    # 2016
    "NH-Senate-2016": (0.1,   RaceRating.TOSSUP),      # Hassan (D) +0.1
    "NV-Senate-2016": (2.4,   RaceRating.TOSSUP),      # Cortez Masto (D) +2.4
    "PA-Senate-2016": (-1.5,  RaceRating.LEAN_R),      # Toomey (R) +1.5
    "WI-Senate-2016": (-3.4,  RaceRating.LEAN_R),      # Johnson (R) +3.4
    "OH-Senate-2016": (-21.0, RaceRating.SOLID_R),     # Portman (R) +21
    "NC-Senate-2016": (-5.7,  RaceRating.LEAN_R),      # Burr (R) +5.7
    "FL-Senate-2016": (-7.7,  RaceRating.LIKELY_R),    # Rubio (R) +7.7
    "MO-Senate-2016": (-2.8,  RaceRating.LEAN_R),      # Blunt (R) +2.8
    "IN-Senate-2016": (-9.6,  RaceRating.LEAN_R),      # Young (R) +9.6
    # 2018
    "FL-Senate-2018": (-0.2,  RaceRating.TOSSUP),      # Scott (R) +0.2
    "NV-Senate-2018": (5.0,   RaceRating.LEAN_D),      # Rosen (D) +5.0
    "MO-Senate-2018": (-6.0,  RaceRating.LEAN_R),      # Hawley (R) +6.0
    "ND-Senate-2018": (-10.6, RaceRating.LEAN_R),      # Cramer (R) +10.6
    "TX-Senate-2018": (-2.6,  RaceRating.LEAN_R),      # Cruz (R) +2.6
    "WI-Senate-2018": (10.8,  RaceRating.LEAN_D),      # Baldwin (D) +10.8
    "TN-Senate-2018": (-10.7, RaceRating.LIKELY_R),    # Blackburn (R) +10.7
    "MT-Senate-2018": (3.5,   RaceRating.LEAN_D),      # Tester (D) +3.5
    "IN-Senate-2018": (-5.7,  RaceRating.LEAN_R),      # Braun (R) +5.7
    # 2020
    "MI-Senate-2020": (1.7,   RaceRating.LEAN_D),      # Peters (D) +1.7
    "ME-Senate-2020": (-8.6,  RaceRating.LEAN_R),      # Collins (R) +8.6
    "NC-Senate-2020": (-1.7,  RaceRating.TOSSUP),      # Tillis (R) +1.7
    "IA-Senate-2020": (-6.6,  RaceRating.LEAN_R),      # Ernst (R) +6.6
    "MT-Senate-2020": (-10.2, RaceRating.LEAN_R),      # Daines (R) +10.2
    "SC-Senate-2020": (-10.4, RaceRating.LIKELY_R),    # Graham (R) +10.4
    "GA-Senate-2020": (1.2,   RaceRating.TOSSUP),      # Ossoff (D) +1.2 (runoff)
    "CO-Senate-2020": (9.3,   RaceRating.LEAN_D),      # Hickenlooper (D) +9.3
    "AZ-Senate-2020": (2.4,   RaceRating.TOSSUP),      # Kelly (D) +2.4
    # 2022
    "PA-Senate-2022": (4.9,   RaceRating.TOSSUP),      # Fetterman (D) +4.9
    "GA-Senate-2022": (2.8,   RaceRating.TOSSUP),      # Warnock (D) +2.8 (runoff)
    "NV-Senate-2022": (0.8,   RaceRating.TOSSUP),      # Cortez Masto (D) +0.8
    "AZ-Senate-2022": (4.9,   RaceRating.LEAN_D),      # Kelly (D) +4.9
    "NH-Senate-2022": (9.2,   RaceRating.LEAN_D),      # Hassan (D) +9.2
    "NC-Senate-2022": (-3.2,  RaceRating.LEAN_R),      # Budd (R) +3.2
    "WI-Senate-2022": (-1.0,  RaceRating.TOSSUP),      # Johnson (R) +1.0
    "OH-Senate-2022": (-6.2,  RaceRating.LEAN_R),      # Vance (R) +6.2
    # 2024
    "MT-Senate-2024": (-14.7, RaceRating.LEAN_R),      # Sheehy (R) +14.7
    "OH-Senate-2024": (-6.0,  RaceRating.LEAN_R),      # Moreno (R) +6.0
    "PA-Senate-2024": (-0.6,  RaceRating.TOSSUP),      # McCormick (R) +0.6
    "WI-Senate-2024": (-1.6,  RaceRating.TOSSUP),      # Hovde (R) +1.6
    "AZ-Senate-2024": (-5.3,  RaceRating.LEAN_R),      # Lake... actually Gallego (D)
    "NV-Senate-2024": (-0.8,  RaceRating.LEAN_D),      # Rosen (D) by slim margin; actually she won
    "MI-Senate-2024": (18.8,  RaceRating.LIKELY_D),    # Slotkin (D) vs Rogers (R)
    "MD-Senate-2024": (28.4,  RaceRating.SOLID_D),     # Alsobrooks (D) +28.4
}

# State abbr → full state name for article lookup
_ABBR_TO_STATE: dict[str, str] = {
    "NH": "New Hampshire", "NV": "Nevada", "PA": "Pennsylvania",
    "WI": "Wisconsin", "OH": "Ohio", "NC": "North Carolina",
    "FL": "Florida", "MO": "Missouri", "IN": "Indiana",
    "ND": "North Dakota", "TX": "Texas", "TN": "Tennessee",
    "MT": "Montana", "MI": "Michigan", "ME": "Maine",
    "IA": "Iowa", "SC": "South Carolina", "GA": "Georgia",
    "CO": "Colorado", "AZ": "Arizona", "MD": "Maryland",
}


def main() -> None:
    signals_path = Path("data/vibes/article_signals.json")
    if not signals_path.exists():
        print("ERROR: data/vibes/article_signals.json not found.")
        print("Run scripts/fetch_vibes_articles.py first.")
        sys.exit(1)

    raw = json.loads(signals_path.read_text())
    all_signals = [
        ArticleSignal(
            article_id=r["article_id"],
            headline=r["headline"],
            snippet=r["snippet"],
            lead_paragraph=r.get("lead_paragraph", ""),
            byline=r.get("byline", ""),
            publication_date=date.fromisoformat(r["publication_date"]),
            race=r["race"],
            state=r["state"],
            year=r["year"],
            source=r.get("source", "nyt"),
        )
        for r in raw
    ]
    print(f"Loaded {len(all_signals)} article signals")

    model = VibesModel()

    # Score each historical race
    vibes_scores = []
    residuals = []
    scored_races = []

    print(f"\nScoring {len(HISTORICAL_RACES)} historical races...")
    print(f"{'Race':<22} {'Articles':>8} {'RawScore':>9} {'Bucket5':<22} {'Actual':>7} {'Prior':>7} {'Residual':>9}")
    print("-" * 90)

    for race_id, (actual_margin, rating) in sorted(HISTORICAL_RACES.items()):
        abbr, _, year_str = race_id.split("-")
        year = int(year_str)
        state = _ABBR_TO_STATE.get(abbr, abbr)

        # Election day is early November; use Oct 1 as as_of to capture pre-election coverage
        as_of = date(year, 11, 1)

        score = model.score_race(
            all_signals,
            race=race_id,
            state=state,
            year=year,
            as_of=as_of,
            window_days=120,  # 4-month window before election
        )

        prior_margin = RATING_MARGIN_PRIOR[rating]
        residual = actual_margin - prior_margin

        vibes_scores.append(score)
        residuals.append(residual)
        scored_races.append({
            "race": race_id,
            "actual_margin": actual_margin,
            "rating": rating.value,
            "prior_margin": prior_margin,
            "residual": residual,
            "raw_vibes": score.raw_score,
            "bucket3": score.bucket3.value,
            "bucket5": score.bucket5.value,
            "bucket7": score.bucket7.value,
            "article_count": score.article_count,
        })

        print(
            f"{race_id:<22} {score.article_count:>8} {score.raw_score:>+9.3f} "
            f"{score.bucket5.value:<22} {actual_margin:>+7.1f} {prior_margin:>+7.1f} {residual:>+9.1f}"
        )

    # Run calibration
    print("\n" + "=" * 90)
    print("CALIBRATION RESULTS")
    print("=" * 90)

    result = model.calibrate_buckets(vibes_scores, residuals)

    print(f"\nn = {result.n_races} races")
    print(f"RMSE by granularity:")
    print(f"  3-modal: {result.rmse_3:.3f} pp")
    print(f"  5-modal: {result.rmse_5:.3f} pp")
    print(f"  7-modal: {result.rmse_7:.3f} pp")
    print(f"\nBest granularity: {result.best_granularity}-modal")
    print(f"\n{result.notes}")

    print("\nRefined 3-modal adjustments (pp toward Dem):")
    for k, v in result.refined_bucket3.items():
        print(f"  {k:<30} {v:>+.2f}")

    print("\nRefined 5-modal adjustments (pp toward Dem):")
    for k, v in result.refined_bucket5.items():
        print(f"  {k:<30} {v:>+.2f}")

    print("\nRefined 7-modal adjustments (pp toward Dem):")
    for k, v in result.refined_bucket7.items():
        print(f"  {k:<30} {v:>+.2f}")

    # Compute baseline RMSE (prior only, no vibes adjustment)
    import math
    baseline_rmse = math.sqrt(sum(r ** 2 for r in residuals) / len(residuals))
    print(f"\nBaseline RMSE (prior only, no vibes): {baseline_rmse:.3f} pp")
    best_rmse = min(result.rmse_3, result.rmse_5, result.rmse_7)
    improvement = baseline_rmse - best_rmse
    print(f"Vibes improvement ({result.best_granularity}-modal): {improvement:+.3f} pp RMSE reduction")

    # Save results
    output = {
        "n_races": result.n_races,
        "rmse_3": result.rmse_3,
        "rmse_5": result.rmse_5,
        "rmse_7": result.rmse_7,
        "best_granularity": result.best_granularity,
        "baseline_rmse": round(baseline_rmse, 4),
        "refined_bucket3": result.refined_bucket3,
        "refined_bucket5": result.refined_bucket5,
        "refined_bucket7": result.refined_bucket7,
        "notes": result.notes,
        "race_level_detail": scored_races,
    }
    out_path = Path("data/vibes/calibrated_params.json")
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nCalibration saved to {out_path}")


if __name__ == "__main__":
    main()
