"""NYT "vibes" adjustment for Senate race margins.

Takes the media-coverage metrics from src/media/vibes.py (CandidateVibes)
and converts them into a small, bounded shift of a race's polling margin.
This is intentionally a *seasoning* layer, not a model of its own:

    per-candidate adjustment (points of margin) =
        bucket_numeric * BUCKET_POINTS        # -2..+2 coverage tone
      - scandal_severity * SCANDAL_POINTS     # 0..1 composite scandal score
      clamped to ±MAX_CANDIDATE_SHIFT

    race adjustment = dem_adjustment - rep_adjustment,
      clamped to ±MAX_RACE_SHIFT

The live pipeline needs an NYT API key (settings.nyt_api_key) to compute
fresh CandidateVibes. For the offline/CI path, a snapshot CSV at
data/fallback/vibes_snapshot.csv carries the latest computed metrics; if it
is absent or empty the adjustment is simply 0 — vibes never get fabricated.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

BUCKET_POINTS = 0.5  # margin points per vibes bucket step (-2..+2 → ±1.0)
SCANDAL_POINTS = 1.5  # margin points subtracted at full scandal severity
MAX_CANDIDATE_SHIFT = 1.5  # cap on any one candidate's adjustment
MAX_RACE_SHIFT = 2.5  # cap on the net race-level adjustment

VIBES_SNAPSHOT_COLUMNS = [
    "state", "candidate", "party", "positive_pct", "negative_pct",
    "neutral_pct", "total_mentions", "bucket_numeric", "scandal_severity",
    "as_of",
]


@dataclass
class VibesSnapshotRow:
    """One candidate's vibes metrics from the offline snapshot CSV."""

    state: str
    candidate: str
    party: str  # "D" | "R"
    positive_pct: float
    negative_pct: float
    neutral_pct: float
    total_mentions: int
    bucket_numeric: int  # -2..+2
    scandal_severity: float  # 0..1
    as_of: date


def candidate_adjustment(bucket_numeric: int, scandal_severity: float) -> float:
    """Bounded margin adjustment for one candidate (positive = helps them)."""
    raw = bucket_numeric * BUCKET_POINTS - scandal_severity * SCANDAL_POINTS
    return round(max(-MAX_CANDIDATE_SHIFT, min(MAX_CANDIDATE_SHIFT, raw)), 2)


def race_adjustment(
    dem: VibesSnapshotRow | None,
    rep: VibesSnapshotRow | None,
) -> float:
    """Net Dem-margin adjustment for a race (positive = shifts toward Dem)."""
    dem_adj = candidate_adjustment(dem.bucket_numeric, dem.scandal_severity) if dem else 0.0
    rep_adj = candidate_adjustment(rep.bucket_numeric, rep.scandal_severity) if rep else 0.0
    net = dem_adj - rep_adj
    return round(max(-MAX_RACE_SHIFT, min(MAX_RACE_SHIFT, net)), 2)


def load_vibes_snapshot(path: Path) -> dict[str, dict[str, VibesSnapshotRow]]:
    """Load the snapshot CSV → {state: {party: row}}. Missing file → {}."""
    if not path.exists():
        return {}
    out: dict[str, dict[str, VibesSnapshotRow]] = {}
    for row in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))):
        try:
            parsed = VibesSnapshotRow(
                state=row["state"],
                candidate=row["candidate"],
                party=row["party"].upper(),
                positive_pct=float(row["positive_pct"]),
                negative_pct=float(row["negative_pct"]),
                neutral_pct=float(row["neutral_pct"]),
                total_mentions=int(row["total_mentions"]),
                bucket_numeric=int(row["bucket_numeric"]),
                scandal_severity=float(row["scandal_severity"]),
                as_of=date.fromisoformat(row["as_of"]),
            )
        except (KeyError, ValueError) as exc:
            logger.warning("Skipping malformed vibes_snapshot row: %s", exc)
            continue
        out.setdefault(parsed.state, {})[parsed.party] = parsed
    return out


def race_adjustment_for_state(
    snapshot: dict[str, dict[str, VibesSnapshotRow]],
    state: str,
) -> tuple[float, dict | None]:
    """Adjustment + a serialisable detail dict for one state ('' detail if none)."""
    rows = snapshot.get(state)
    if not rows:
        return 0.0, None
    dem, rep = rows.get("D"), rows.get("R")
    adj = race_adjustment(dem, rep)
    detail = {
        "adjustment": adj,
        "dem": _row_detail(dem),
        "rep": _row_detail(rep),
    }
    return adj, detail


def _row_detail(row: VibesSnapshotRow | None) -> dict | None:
    if row is None:
        return None
    return {
        "candidate": row.candidate,
        "positive_pct": row.positive_pct,
        "negative_pct": row.negative_pct,
        "total_mentions": row.total_mentions,
        "bucket_numeric": row.bucket_numeric,
        "scandal_severity": row.scandal_severity,
        "as_of": row.as_of.isoformat(),
    }
