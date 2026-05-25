"""Extract directional predictions from all fetched NYT Senate race articles.

Uses Claude Haiku to classify each article: does it contain a prediction
about who will win? If so, which party is favored and how confidently?

Results are cached to data/vibes/predictions.json — re-running skips articles
already processed. Safe to interrupt and resume.

Prerequisites:
    - data/vibes/article_signals.json (run scripts/fetch_vibes_articles.py first)
    - ANTHROPIC_API_KEY set in .env

Run: python -m scripts.extract_predictions
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models.vibes import ArticleSignal
from src.models.prediction_extractor import PredictionExtractor


def main() -> None:
    signals_path = Path("data/vibes/article_signals.json")
    if not signals_path.exists():
        print("ERROR: data/vibes/article_signals.json not found.")
        print("Run scripts/fetch_vibes_articles.py first.")
        sys.exit(1)

    raw = json.loads(signals_path.read_text())
    signals = [
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
    print(f"Loaded {len(signals)} articles")

    extractor = PredictionExtractor()
    cached_count = len(extractor.load_cached())
    print(f"Already cached: {cached_count} | To process: {len(signals) - cached_count}")

    records = extractor.extract_all(signals, skip_cached=True, save_every=25)

    # Summary stats
    with_pred = [r for r in records if r.has_prediction]
    d_pred = [r for r in with_pred if r.predicted_winner == "D"]
    r_pred = [r for r in with_pred if r.predicted_winner == "R"]
    tossup_pred = [r for r in with_pred if r.predicted_winner == "tossup"]

    print(f"\n{'='*60}")
    print(f"EXTRACTION COMPLETE")
    print(f"{'='*60}")
    print(f"Total articles processed : {len(records)}")
    print(f"Articles with prediction : {len(with_pred)} ({100*len(with_pred)/len(records):.1f}%)")
    print(f"  Predicted D wins       : {len(d_pred)}")
    print(f"  Predicted R wins       : {len(r_pred)}")
    print(f"  Called tossup          : {len(tossup_pred)}")
    print(f"\nBreakdown by confidence:")
    for conf in ["clear", "moderate", "slight"]:
        n = sum(1 for r in with_pred if r.confidence == conf)
        print(f"  {conf:<10}: {n}")
    print(f"\nSaved to data/vibes/predictions.json")
    print(f"Run scripts/analyze_journalist_accuracy.py to see results.")


if __name__ == "__main__":
    main()
