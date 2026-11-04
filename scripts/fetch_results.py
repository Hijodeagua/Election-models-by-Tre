#!/usr/bin/env python3
"""Collect 2026 Senate results into data/results/senate_2026.json.

Sources, in order of precedence:
  1. data/results/senate_2026_manual.json — hand-entered corrections (same
     per-state schema; anything here overrides what was fetched).
  2. The Associated Press race calls and live counts, via the New York Times
     election feed (src/data/nyt_results.py): called races, who called them
     and when, expected vote in, leader and margin for every race.
  3. Wikipedia race articles (src/data/wikipedia_results.py), only when the
     AP feed is unavailable.

``results`` holds called races only, so the scorer only counts races that
have actually been called; ``status`` holds every race's reporting state for
the live map. Re-running is safe: it rewrites the file from scratch.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.names import names_match  # noqa: E402
from src.data.nyt_results import NytResultsSource, summarize  # noqa: E402
from src.data.wikipedia_results import WikipediaResultsSource  # noqa: E402
from src.models.senate_simulation import load_cycle_config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "results" / "senate_2026.json"
MANUAL = ROOT / "data" / "results" / "senate_2026_manual.json"

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("fetch_results")


def nominees_for(entry: dict) -> list[str]:
    """The configured general-election candidates for a race."""
    names = [entry.get("dem_candidate"), entry.get("rep_candidate"), entry.get("third_candidate")]
    return [n for n in names if n]


def winner_is_a_nominee(winner: str | None, entry: dict) -> bool:
    """Guard against a primary table or a stale page: the winner has to be one
    of the race's configured general-election candidates."""
    return any(names_match(winner, n) for n in nominees_for(entry))


def main() -> int:
    cycle = load_cycle_config()
    manual = {}
    if MANUAL.exists():
        manual = json.loads(MANUAL.read_text()).get("results", {})
        logger.info("manual results for %d states", len(manual))

    with NytResultsSource() as nyt:
        statuses = nyt.fetch()
    feed_ok = bool(statuses)
    logger.info("AP/NYT feed: %s", summarize(statuses) if feed_ok else "unavailable")

    results: dict[str, dict] = {}
    status: dict[str, dict] = {}
    wiki = None if feed_ok else WikipediaResultsSource()
    try:
        for entry in cycle["competitive_races"]:
            state = entry["state"]
            st = statuses.get(state)
            if st is not None:
                status[state] = st.to_status_dict()
            if state in manual:
                results[state] = {**manual[state], "source": "manual"}
                status[state] = {
                    **status.get(state, {"state": state}),
                    "status": "called", "called": True,
                    "winner": manual[state].get("winner"),
                    "winner_party": manual[state].get("winner_party"),
                    "source": "manual",
                }
                logger.info("  %s: manual — %s (%s)", state, manual[state].get("winner"),
                            manual[state].get("winner_party"))
                continue
            if feed_ok:
                if st is None:
                    logger.warning("  %s: not in the AP/NYT feed", state)
                    continue
                if not st.called:
                    logger.info("  %s: %s (%.0f%% in, %s leads)", state, st.status,
                                st.eevp or 0.0, st.leader or "nobody")
                    continue
                note = ""
                if not winner_is_a_nominee(st.winner, entry):
                    note = "winner is not a configured nominee"
                    logger.warning("  %s: AP winner %r is not a configured nominee (%s)",
                                   state, st.winner, ", ".join(nominees_for(entry)))
                rec = st.to_result_dict()
                if note:
                    rec["note"] = (rec["note"] + "; " + note).strip("; ")
                results[state] = rec
                logger.info("  %s: CALLED %s (%s) at %s — D %.1f / R %.1f, %.0f%% in%s",
                            state, st.winner, st.winner_party, st.called_at,
                            st.dem_pct or 0.0, st.rep_pct or 0.0, st.eevp or 0.0,
                            " FLIP" if st.gained else "")
                continue
            # Fallback: Wikipedia.
            assert wiki is not None
            res = wiki.fetch_result(state, entry.get("wikipedia"))
            if res is None:
                logger.info("  %s: no result yet", state)
                continue
            if not winner_is_a_nominee(res.winner, entry):
                logger.warning(
                    "  %s: parsed winner %r is not a configured nominee (%s) — skipping",
                    state, res.winner, ", ".join(nominees_for(entry)),
                )
                continue
            results[state] = res.to_dict()
            status[state] = {
                "state": state, "status": "called", "called": True, "winner": res.winner,
                "winner_party": res.winner_party, "source": "wikipedia",
            }
            logger.info(
                "  %s: %s (%s) D %.1f / R %.1f → margin %+.1f",
                state, res.winner, res.winner_party,
                res.dem_pct or 0.0, res.rep_pct or 0.0, res.margin or 0.0,
            )
    finally:
        if wiki is not None:
            wiki.close()

    payload = {
        "cycle": cycle["cycle"],
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": "ap-via-nyt" if feed_ok else "wikipedia",
        "num_results": len(results),
        "results": results,
        "status": status,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    logger.info(
        "wrote %s (%d of %d races called)",
        OUT.relative_to(ROOT), len(results), len(cycle["competitive_races"]),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
