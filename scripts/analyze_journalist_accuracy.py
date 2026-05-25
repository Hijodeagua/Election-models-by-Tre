"""Analyze journalist prediction accuracy against 2016-2024 Senate outcomes.

Joins extracted predictions (data/vibes/predictions.json) against actual
certified results to measure:
  1. Overall press prediction accuracy by race
  2. Per-journalist directional accuracy and calibration
  3. Whether press consensus added signal beyond expert ratings

Prerequisites:
    - data/vibes/predictions.json (run scripts/extract_predictions.py first)

Run: python -m scripts.analyze_journalist_accuracy
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.calibrate_vibes import HISTORICAL_RACES
from src.models.senate import RATING_MARGIN_PRIOR, RaceRating

# ── Actual outcomes (D wins = True) ───────────────────────────────────────────

def _d_won(margin: float) -> bool:
    return margin > 0


@dataclass
class JournalistStats:
    name: str
    total_predictions: int
    correct: int
    races_covered: set[str]
    confidence_breakdown: dict[str, dict[str, int]]  # conf -> {correct, total}

    @property
    def accuracy(self) -> float:
        return self.correct / self.total_predictions if self.total_predictions else 0.0

    @property
    def n_races(self) -> int:
        return len(self.races_covered)


def _clean_byline(byline: str) -> str:
    """Normalize 'By NICHOLAS FANDOS' -> 'Nicholas Fandos'."""
    name = byline.removeprefix("By ").strip()
    if not name:
        return ""
    return name.title()


def main() -> None:
    pred_path = Path("data/vibes/predictions.json")
    if not pred_path.exists():
        print("ERROR: data/vibes/predictions.json not found.")
        print("Run scripts/extract_predictions.py first.")
        sys.exit(1)

    records = json.loads(pred_path.read_text())
    print(f"Loaded {len(records)} prediction records")

    # Only use races where we know the actual outcome
    known_races = set(HISTORICAL_RACES.keys())
    matched = [r for r in records if r["race"] in known_races and r["has_prediction"]]
    print(f"Directional predictions in calibrated races: {len(matched)}")

    # ── Race-level press consensus ─────────────────────────────────────────────

    race_preds: dict[str, list[dict]] = defaultdict(list)
    for r in matched:
        if r["predicted_winner"] in ("D", "R"):
            race_preds[r["race"]].append(r)

    print(f"\n{'='*70}")
    print("RACE-LEVEL PRESS CONSENSUS vs. ACTUAL OUTCOME")
    print(f"{'='*70}")
    print(f"{'Race':<22} {'n':>4} {'%D':>6} {'%R':>6} {'Actual':>8} {'Press':>6} {'Rating':>8} {'Correct?':>9}")
    print("-" * 70)

    press_correct = 0
    rating_correct = 0
    n_races_with_preds = 0

    for race_id in sorted(race_preds):
        preds = race_preds[race_id]
        actual_margin, rating = HISTORICAL_RACES[race_id]
        d_won_actual = _d_won(actual_margin)
        rating_pred_d = RATING_MARGIN_PRIOR[rating] > 0

        n = len(preds)
        d_count = sum(1 for p in preds if p["predicted_winner"] == "D")
        r_count = n - d_count
        pct_d = d_count / n
        press_says_d = pct_d > 0.5
        press_says_tossup = abs(pct_d - 0.5) < 0.1

        press_call = "D" if press_says_d else ("Tossup" if press_says_tossup else "R")
        press_correct_flag = (
            "Y" if (not press_says_tossup and press_says_d == d_won_actual)
            else ("-" if press_says_tossup else "N")
        )
        rating_correct_flag = "Y" if rating_pred_d == d_won_actual else "N"

        if not press_says_tossup:
            n_races_with_preds += 1
            if press_says_d == d_won_actual:
                press_correct += 1
        if rating_pred_d == d_won_actual:
            rating_correct += 1

        print(
            f"{race_id:<22} {n:>4} {pct_d:>6.0%} {1-pct_d:>6.0%} "
            f"{'D+' if d_won_actual else 'R+'}{abs(actual_margin):>4.1f}  "
            f"{press_call:>6}  {rating.value:>10}  {press_correct_flag:>4} / {rating_correct_flag}"
        )

    total_races = len(HISTORICAL_RACES)
    if n_races_with_preds:
        print(f"\nPress directional accuracy : {press_correct}/{n_races_with_preds} ({100*press_correct/n_races_with_preds:.0f}%)")
    print(f"Rating directional accuracy: {rating_correct}/{total_races} ({100*rating_correct/total_races:.0f}%)")

    # ── Journalist-level accuracy ──────────────────────────────────────────────

    journalist_data: dict[str, JournalistStats] = {}

    for rec in matched:
        if rec["predicted_winner"] not in ("D", "R"):
            continue  # skip tossup calls for directional accuracy
        if rec["race"] not in known_races:
            continue

        name = _clean_byline(rec["byline"])
        if not name:
            name = "[No byline]"

        actual_margin, _ = HISTORICAL_RACES[rec["race"]]
        d_won_actual = _d_won(actual_margin)
        predicted_d = rec["predicted_winner"] == "D"
        correct = predicted_d == d_won_actual
        conf = rec.get("confidence", "none")

        if name not in journalist_data:
            journalist_data[name] = JournalistStats(
                name=name,
                total_predictions=0,
                correct=0,
                races_covered=set(),
                confidence_breakdown={"clear": {"correct": 0, "total": 0},
                                      "moderate": {"correct": 0, "total": 0},
                                      "slight": {"correct": 0, "total": 0}},
            )

        stats = journalist_data[name]
        stats.total_predictions += 1
        stats.correct += int(correct)
        stats.races_covered.add(rec["race"])
        if conf in stats.confidence_breakdown:
            stats.confidence_breakdown[conf]["total"] += 1
            stats.confidence_breakdown[conf]["correct"] += int(correct)

    # Filter to journalists with ≥3 directional predictions
    qualified = [s for s in journalist_data.values() if s.total_predictions >= 3]
    qualified.sort(key=lambda s: (-s.accuracy, -s.total_predictions))

    print(f"\n{'='*70}")
    print("JOURNALIST ACCURACY (min 3 directional predictions)")
    print(f"{'='*70}")
    print(f"{'Journalist':<30} {'N':>4} {'Races':>6} {'Correct':>8} {'Accuracy':>9}")
    print("-" * 70)

    for s in qualified:
        print(
            f"{s.name:<30} {s.total_predictions:>4} {s.n_races:>6} "
            f"{s.correct:>8} {s.accuracy:>8.0%}"
        )

    # ── Confidence calibration ─────────────────────────────────────────────────

    print(f"\n{'='*50}")
    print("CONFIDENCE CALIBRATION (all journalists)")
    print(f"{'='*50}")
    print(f"{'Confidence':<12} {'N':>5} {'Accuracy':>9}  (expect: clear>80%, moderate~70%, slight~60%)")
    print("-" * 50)

    conf_totals: dict[str, dict[str, int]] = {
        "clear": {"correct": 0, "total": 0},
        "moderate": {"correct": 0, "total": 0},
        "slight": {"correct": 0, "total": 0},
    }
    for rec in matched:
        if rec["predicted_winner"] not in ("D", "R"):
            continue
        if rec["race"] not in known_races:
            continue
        conf = rec.get("confidence", "none")
        if conf not in conf_totals:
            continue
        actual_margin, _ = HISTORICAL_RACES[rec["race"]]
        correct = (_d_won(actual_margin)) == (rec["predicted_winner"] == "D")
        conf_totals[conf]["total"] += 1
        conf_totals[conf]["correct"] += int(correct)

    for conf, counts in conf_totals.items():
        if counts["total"]:
            acc = counts["correct"] / counts["total"]
            print(f"{conf:<12} {counts['total']:>5} {acc:>8.0%}")

    # ── Sentiment 3×3 matrix ───────────────────────────────────────────────────
    # dem_sentiment and rep_sentiment are INDEPENDENT scales — an article can be
    # positive for both candidates (tossup narrative), negative for both (ugly race),
    # or any combination. Collapsing to dem-rep diff loses this signal.

    all_records = json.loads(pred_path.read_text())
    sentiments = ["positive", "neutral", "negative"]

    print(f"\n{'='*60}")
    print("SENTIMENT PAIR DISTRIBUTION (dem_sentiment × rep_sentiment)")
    print("Each cell = article count | % D-win in calibrated races")
    print(f"{'='*60}")
    print(f"{'':20}", end="")
    for rs in sentiments:
        print(f"  Rep:{rs:<10}", end="")
    print()
    print("-" * 60)

    for ds in sentiments:
        print(f"Dem:{ds:<17}", end="")
        for rs in sentiments:
            cell = [
                r for r in all_records
                if r.get("dem_sentiment") == ds and r.get("rep_sentiment") == rs
            ]
            n = len(cell)
            calibrated = [
                r for r in cell
                if r["race"] in known_races
            ]
            if calibrated:
                d_wins = sum(1 for r in calibrated if _d_won(HISTORICAL_RACES[r["race"]][0]))
                pct = f"{100*d_wins//len(calibrated)}%D"
            else:
                pct = "—"
            print(f"  {n:>4} ({pct:<5})", end="")
        print()

    print(f"\nInterpretation guide:")
    print(f"  (pos,neg) -> strongest D signal  |  (neg,pos) -> strongest R signal")
    print(f"  (pos,pos) -> tossup narrative     |  (neg,neg) -> chaotic/ugly race")
    print(f"  (neu,neu) -> generic coverage     |  off-diagonal -> one candidate has edge")
    print(f"\nFull results in data/vibes/predictions.json")


if __name__ == "__main__":
    main()
