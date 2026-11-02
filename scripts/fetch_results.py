#!/usr/bin/env python3
"""Collect 2026 Senate results into data/results/senate_2026.json.

Sources, in order of precedence:
  1. data/results/senate_2026_manual.json — hand-entered corrections (same
     per-state schema; anything here overrides what was scraped).
  2. Wikipedia race articles (src/data/wikipedia_results.py), one per entry
     in config/senate_2026.json, using the configured article override for
     the special elections.

States with no parsable result are left out of the file, so the scorer only
counts races that have actually been called. Re-running is safe: it rewrites
the file from scratch each time.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.wikipedia_results import WikipediaResultsSource  # noqa: E402
from src.models.senate_simulation import load_cycle_config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "results" / "senate_2026.json"
MANUAL = ROOT / "data" / "results" / "senate_2026_manual.json"

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("fetch_results")


def main() -> int:
    cycle = load_cycle_config()
    manual = {}
    if MANUAL.exists():
        manual = json.loads(MANUAL.read_text()).get("results", {})
        logger.info("manual results for %d states", len(manual))

    results: dict[str, dict] = {}
    with WikipediaResultsSource() as src:
        for entry in cycle["competitive_races"]:
            state = entry["state"]
            if state in manual:
                results[state] = {**manual[state], "source": "manual"}
                continue
            res = src.fetch_result(state, entry.get("wikipedia"))
            if res is None:
                logger.info("  %s: no result yet", state)
                continue
            results[state] = res.to_dict()
            logger.info(
                "  %s: %s (%s) D %.1f / R %.1f → margin %+.1f",
                state, res.winner, res.winner_party,
                res.dem_pct or 0.0, res.rep_pct or 0.0, res.margin or 0.0,
            )

    payload = {
        "cycle": cycle["cycle"],
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "num_results": len(results),
        "results": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    logger.info(
        "wrote %s (%d of %d races)",
        OUT.relative_to(ROOT), len(results), len(cycle["competitive_races"]),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
