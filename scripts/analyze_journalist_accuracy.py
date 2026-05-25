"""Analyze journalist prediction accuracy against 2016-2024 Senate outcomes.

Joins extracted predictions (data/vibes/predictions.json) against the full
article corpus (data/vibes/article_signals.json) to preserve multi-race
article weighting — an article that appeared in 8 race queries is counted
in all 8 races, not collapsed to one.

Measures:
  1. Overall press prediction accuracy by race
  2. Per-journalist directional accuracy and calibration
  3. Sentiment pair distribution across the full corpus

Prerequisites:
    - data/vibes/article_signals.json (run scripts/fetch_vibes_articles.py)
    - data/vibes/predictions.json (run scripts/extract_predictions.py)

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
from src.models.senate import RATING_MARGIN_PRIOR


def _d_won(margin: float) -> bool:
    return margin > 0


@dataclass
class JournalistStats:
    name: str
    total_predictions: int
    correct: int
    races_covered: set[str]
    confidence_breakdown: dict[str, dict[str, int]]

    @property
    def accuracy(self) -> float:
        return self.correct / self.total_predictions if self.total_predictions else 0.0

    @property
    def n_races(self) -> int:
        return len(self.races_covered)


def _clean_byline(byline: str) -> str:
    name = byline.removeprefix("By ").strip()
    return name.title() if name else ""


def _load_race_records(
    articles_path: Path,
    pred_path: Path,
) -> list[dict]:
    """Return one record per article-race pair, preserving multi-race weighting.

    Multi-race articles (returned by multiple state queries) appear once per
    race they were associated with, each carrying the same prediction/sentiment
    data. This is intentional: national Senate environment articles that were
    fetched for 8 races contribute signal in all 8 races.
    """
    articles = json.loads(articles_path.read_text())
    pred_map = {p["article_id"]: p for p in json.loads(pred_path.read_text())}

    records = []
    for art in articles:
        pred = pred_map.get(art["article_id"])
        if pred is None:
            continue
        # Override race/state/year with the article's assignment (not prediction's)
        r = dict(pred)
        r["race"] = art["race"]
        r["state"] = art["state"]
        r["year"] = art["year"]
        r["byline"] = art.get("byline") or pred.get("byline", "")
        records.append(r)
    return records


def main() -> None:
    articles_path = Path("data/vibes/article_signals.json")
    pred_path = Path("data/vibes/predictions.json")

    for p in (articles_path, pred_path):
        if not p.exists():
            print(f"ERROR: {p} not found.")
            sys.exit(1)

    records = _load_race_records(articles_path, pred_path)
    unique_preds = json.loads(pred_path.read_text())

    print(f"Article-race records (multi-race preserved): {len(records)}")
    print(f"Unique classified articles:                  {len(unique_preds)}")

    known_races = set(HISTORICAL_RACES.keys())

    # Directional predictions only (D or R, not tossup)
    directional = [
        r for r in records
        if r["has_prediction"] and r["predicted_winner"] in ("D", "R")
        and r["race"] in known_races
    ]
    print(f"Directional predictions in calibrated races: {len(directional)}")

    # ── Race-level press consensus ─────────────────────────────────────────────

    race_preds: dict[str, list[dict]] = defaultdict(list)
    for r in directional:
        race_preds[r["race"]].append(r)

    print(f"\n{'='*72}")
    print("RACE-LEVEL PRESS CONSENSUS vs. ACTUAL OUTCOME")
    print(f"{'='*72}")
    header = (
        f"{'Race':<22} {'n':>4} {'%D':>6} {'%R':>6}"
        f" {'Actual':>8} {'Press':>7} {'Rating':>10} {'Press':>6} {'Rating':>7}"
    )
    print(header)
    print("-" * 72)

    press_correct = press_total = 0
    # Tossup ratings excluded from directional rating accuracy
    rating_correct = rating_total = 0

    for race_id in sorted(race_preds):
        preds = race_preds[race_id]
        actual_margin, rating = HISTORICAL_RACES[race_id]
        d_won_actual = _d_won(actual_margin)

        n = len(preds)
        d_count = sum(1 for p in preds if p["predicted_winner"] == "D")
        pct_d = d_count / n
        press_says_d = pct_d > 0.5
        press_is_tossup = abs(pct_d - 0.5) <= 0.1

        press_call = "D" if press_says_d else ("~Tossup" if press_is_tossup else "R")
        press_flag = (
            "Y" if (not press_is_tossup and press_says_d == d_won_actual)
            else ("-" if press_is_tossup else "N")
        )

        prior = RATING_MARGIN_PRIOR[rating]
        if prior == 0.0:
            rating_flag = "-"  # tossup: abstain rather than guess R
        else:
            rating_pred_d = prior > 0
            rating_flag = "Y" if rating_pred_d == d_won_actual else "N"
            rating_total += 1
            if rating_pred_d == d_won_actual:
                rating_correct += 1

        if not press_is_tossup:
            press_total += 1
            if press_says_d == d_won_actual:
                press_correct += 1

        print(
            f"{race_id:<22} {n:>4} {pct_d:>6.0%} {1-pct_d:>6.0%}"
            f" {'D+' if d_won_actual else 'R+'}{abs(actual_margin):>4.1f}"
            f"  {press_call:>7}  {rating.value:>10}  {press_flag:>5}  {rating_flag:>5}"
        )

    print()
    if press_total:
        pct = 100 * press_correct / press_total
        print(
            f"Press directional accuracy : {press_correct}/{press_total} ({pct:.0f}%)"
            f"  [races where press took a non-tossup position]"
        )
    pct_r = 100 * rating_correct / rating_total if rating_total else 0
    print(
        f"Rating directional accuracy: {rating_correct}/{rating_total} ({pct_r:.0f}%)"
        f"  [non-tossup ratings only; tossup ratings excluded]"
    )
    print()
    print(
        "NOTE: These are not directly comparable. Press predictions are self-selected"
        " (journalists only call clear races); ratings cover all races."
    )

    # ── Journalist-level accuracy ──────────────────────────────────────────────

    journalist_data: dict[str, JournalistStats] = {}

    for rec in directional:
        name = _clean_byline(rec.get("byline", ""))
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
                confidence_breakdown={
                    "clear": {"correct": 0, "total": 0},
                    "moderate": {"correct": 0, "total": 0},
                    "slight": {"correct": 0, "total": 0},
                },
            )

        stats = journalist_data[name]
        stats.total_predictions += 1
        stats.correct += int(correct)
        stats.races_covered.add(rec["race"])
        if conf in stats.confidence_breakdown:
            stats.confidence_breakdown[conf]["total"] += 1
            stats.confidence_breakdown[conf]["correct"] += int(correct)

    qualified = [s for s in journalist_data.values() if s.total_predictions >= 3]
    qualified.sort(key=lambda s: (-s.accuracy, -s.total_predictions))

    print(f"\n{'='*70}")
    print("JOURNALIST ACCURACY (min 3 directional predictions in calibrated races)")
    print("Small samples — treat as anecdotal, not rankings")
    print(f"{'='*70}")
    print(f"{'Journalist':<30} {'N':>4} {'Races':>6} {'Correct':>8} {'Accuracy':>9}")
    print("-" * 70)

    for s in qualified:
        print(
            f"{s.name:<30} {s.total_predictions:>4} {s.n_races:>6}"
            f" {s.correct:>8} {s.accuracy:>8.0%}"
        )

    # ── Confidence calibration ─────────────────────────────────────────────────

    print(f"\n{'='*50}")
    print("CONFIDENCE CALIBRATION (directional D/R predictions only)")
    print(f"{'='*50}")
    print(
        f"{'Confidence':<12} {'N':>5} {'Accuracy':>9}"
        "  (expect: clear>80%, moderate~70%, slight~60%)"
    )
    print("-" * 50)

    conf_totals: dict[str, dict[str, int]] = {
        "clear": {"correct": 0, "total": 0},
        "moderate": {"correct": 0, "total": 0},
        "slight": {"correct": 0, "total": 0},
    }
    for rec in directional:
        conf = rec.get("confidence", "none")
        if conf not in conf_totals:
            continue
        actual_margin, _ = HISTORICAL_RACES[rec["race"]]
        correct = _d_won(actual_margin) == (rec["predicted_winner"] == "D")
        conf_totals[conf]["total"] += 1
        conf_totals[conf]["correct"] += int(correct)

    for conf, counts in conf_totals.items():
        if counts["total"]:
            acc = counts["correct"] / counts["total"]
            print(f"{conf:<12} {counts['total']:>5} {acc:>8.0%}")

    # ── Sentiment 3×3 matrix (full corpus, multi-race preserved) ──────────────

    sentiments = ["positive", "neutral", "negative"]

    print(f"\n{'='*65}")
    print("SENTIMENT PAIR DISTRIBUTION (dem_sentiment x rep_sentiment)")
    print("Article-race records (multi-race articles counted per race)")
    print("Each cell: count | D-win % in calibrated races")
    print(f"{'='*65}")
    print(f"{'':20}", end="")
    for rs in sentiments:
        print(f"  Rep:{rs:<11}", end="")
    print()
    print("-" * 65)

    for ds in sentiments:
        print(f"Dem:{ds:<17}", end="")
        for rs in sentiments:
            cell = [
                r for r in records
                if r.get("dem_sentiment") == ds and r.get("rep_sentiment") == rs
            ]
            n = len(cell)
            calibrated = [r for r in cell if r["race"] in known_races]
            if calibrated:
                d_wins = sum(
                    1 for r in calibrated
                    if _d_won(HISTORICAL_RACES[r["race"]][0])
                )
                pct = f"{100*d_wins//len(calibrated)}%D"
            else:
                pct = "n/a"
            print(f"  {n:>5} ({pct:<5})", end="")
        print()

    print()
    print("Interpretation guide:")
    print("  (pos,neg) -> strongest D signal  |  (neg,pos) -> strongest R signal")
    print("  (pos,pos) -> tossup narrative     |  (neg,neg) -> chaotic/ugly race")
    print("  (neu,neu) -> generic coverage     |  off-diagonal -> one candidate has edge")
    print("\nFull results in data/vibes/predictions.json")


if __name__ == "__main__":
    main()
