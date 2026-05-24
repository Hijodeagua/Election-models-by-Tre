"""Fetch NYT article signals for Senate races (2012-2026) for vibes calibration.

Targets competitive races only to stay within API daily limits.
Results are disk-cached in data/cache/nyt/ — re-running is safe (cache hits).
Run: python -m scripts.fetch_vibes_articles
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.nyt import NYTArticleSource

# ── Competitive Senate races by cycle ─────────────────────────────────────────
# Format: (state, year)
# Focused on tossup / lean races where vibes have the most marginal impact.

HISTORICAL_COMPETITIVE_RACES: list[tuple[str, int]] = [
    # 2012
    ("Massachusetts", 2012), ("Virginia", 2012), ("Ohio", 2012),
    ("Missouri", 2012), ("Indiana", 2012), ("Montana", 2012),
    # 2014
    ("North Carolina", 2014), ("Iowa", 2014), ("Colorado", 2014),
    ("Alaska", 2014), ("New Hampshire", 2014), ("Arkansas", 2014),
    ("Louisiana", 2014), ("Georgia", 2014), ("Kansas", 2014),
    # 2016
    ("New Hampshire", 2016), ("Nevada", 2016), ("Pennsylvania", 2016),
    ("Wisconsin", 2016), ("Ohio", 2016), ("North Carolina", 2016),
    ("Florida", 2016), ("Missouri", 2016), ("Indiana", 2016),
    # 2018
    ("Florida", 2018), ("Nevada", 2018), ("Missouri", 2018),
    ("North Dakota", 2018), ("Texas", 2018), ("Wisconsin", 2018),
    ("Tennessee", 2018), ("Arizona", 2018), ("Montana", 2018), ("Indiana", 2018),
    # 2020
    ("Michigan", 2020), ("Maine", 2020), ("North Carolina", 2020),
    ("Iowa", 2020), ("Montana", 2020), ("South Carolina", 2020),
    ("Georgia", 2020), ("Colorado", 2020), ("Arizona", 2020),
    ("Georgia", 2020),  # special runoff
    # 2022
    ("Pennsylvania", 2022), ("Georgia", 2022), ("Nevada", 2022),
    ("Arizona", 2022), ("New Hampshire", 2022), ("North Carolina", 2022),
    ("Wisconsin", 2022), ("Ohio", 2022),
    # 2024
    ("Montana", 2024), ("Ohio", 2024), ("Pennsylvania", 2024),
    ("Wisconsin", 2024), ("Arizona", 2024), ("Nevada", 2024),
    ("Michigan", 2024), ("Maryland", 2024),
    # 2026 (current cycle — all competitive races)
    ("Arizona", 2026), ("Georgia", 2026), ("Michigan", 2026),
    ("New Hampshire", 2026), ("Virginia", 2026), ("North Carolina", 2026),
    ("Maine", 2026), ("Iowa", 2026), ("Minnesota", 2026), ("Colorado", 2026),
]

# Deduplicate while preserving order
seen: set[tuple[str, int]] = set()
RACES: list[tuple[str, int]] = []
for r in HISTORICAL_COMPETITIVE_RACES:
    if r not in seen:
        seen.add(r)
        RACES.append(r)


def main() -> None:
    output_dir = Path("data/vibes")
    output_dir.mkdir(parents=True, exist_ok=True)

    api_key = os.environ.get("NYT_API_KEY", "")
    if not api_key:
        print("ERROR: NYT_API_KEY not set. Add it to .env and retry.")
        sys.exit(1)

    print(f"Fetching NYT articles for {len(RACES)} Senate races (2012-2026)")
    print("Cache dir: data/cache/nyt/  (re-runs skip cached pages)")
    print("-" * 60)

    all_signals = []
    client = NYTArticleSource(api_key=api_key)

    for i, (state, year) in enumerate(RACES, 1):
        print(f"[{i:2d}/{len(RACES)}] {state} {year} ... ", end="", flush=True)
        try:
            signals = client.fetch_race_articles(state, year, max_pages=5)
            all_signals.extend(signals)
            print(f"{len(signals)} articles")
        except Exception as exc:
            print(f"ERROR: {exc}")

    # Persist as JSON for later calibration
    output_path = output_dir / "article_signals.json"
    records = [
        {
            "article_id": s.article_id,
            "headline": s.headline,
            "snippet": s.snippet,
            "publication_date": s.publication_date.isoformat(),
            "race": s.race,
            "state": s.state,
            "year": s.year,
            "source": s.source,
        }
        for s in all_signals
    ]
    output_path.write_text(json.dumps(records, indent=2))

    print("-" * 60)
    print(f"Done. {len(all_signals)} total articles saved to {output_path}")
    by_year: dict[int, int] = {}
    for s in all_signals:
        by_year[s.year] = by_year.get(s.year, 0) + 1
    for yr in sorted(by_year):
        print(f"  {yr}: {by_year[yr]} articles")


if __name__ == "__main__":
    main()
