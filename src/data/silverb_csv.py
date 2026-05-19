"""Load Silver Bulletin pre-aggregated daily model estimates from CSV.

Silver Bulletin publishes daily polling-average model estimates with
confidence intervals.  These are *not* raw polls — they are final
model outputs — so they bypass the polling engine entirely and map
directly to snapshot objects.

Approval CSV format (M/D/YY dates):
    modeldate,approve,disapprove,approve_lo,approve_hi,disapprove_lo,disapprove_hi
    1/21/25,51.63,...

Generic ballot CSV format (M/D/YYYY dates):
    modeldate,dem,rep,dem_lo,dem_hi,rep_lo,rep_hi
    1/17/2025,43.78,...

The last row in each file is the most recent estimate.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path

from src.models.approval import ApprovalSnapshot
from src.models.generic_ballot import GenericBallotSnapshot


def _parse_mdyy(raw: str) -> date:
    """Parse 'M/D/YY' or 'M/D/YYYY' into a date."""
    parts = raw.strip().split("/")
    month, day, year_raw = int(parts[0]), int(parts[1]), parts[2]
    if len(year_raw) == 2:
        year = 2000 + int(year_raw)
    else:
        year = int(year_raw)
    return date(year, month, day)


class SilverBulletinApprovalLoader:
    """Load the most recent approval estimate from a Silver Bulletin CSV."""

    def load(self, path: Path) -> ApprovalSnapshot | None:
        text = path.read_text(encoding="utf-8")
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            return None

        row = rows[-1]  # last row = most recent
        try:
            as_of = _parse_mdyy(row["modeldate"])
            approve = float(row["approve"])
            disapprove = float(row["disapprove"])
            ci_approve: tuple[float, float] | None = None
            ci_disapprove: tuple[float, float] | None = None
            if row.get("approve_lo") and row.get("approve_hi"):
                ci_approve = (float(row["approve_lo"]), float(row["approve_hi"]))
            if row.get("disapprove_lo") and row.get("disapprove_hi"):
                ci_disapprove = (float(row["disapprove_lo"]), float(row["disapprove_hi"]))
        except (KeyError, ValueError):
            return None

        return ApprovalSnapshot(
            as_of=as_of,
            approve=approve,
            disapprove=disapprove,
            net_approval=round(approve - disapprove, 1),
            num_polls=len(rows),
            ci_approve=ci_approve,
            ci_disapprove=ci_disapprove,
        )


class SilverBulletinGenericBallotLoader:
    """Load the most recent generic ballot estimate from a Silver Bulletin CSV."""

    def load(self, path: Path) -> GenericBallotSnapshot | None:
        text = path.read_text(encoding="utf-8")
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            return None

        row = rows[-1]
        try:
            as_of = _parse_mdyy(row["modeldate"])
            dem = float(row["dem"])
            rep = float(row["rep"])
            ci_dem: tuple[float, float] | None = None
            ci_rep: tuple[float, float] | None = None
            if row.get("dem_lo") and row.get("dem_hi"):
                ci_dem = (float(row["dem_lo"]), float(row["dem_hi"]))
            if row.get("rep_lo") and row.get("rep_hi"):
                ci_rep = (float(row["rep_lo"]), float(row["rep_hi"]))
        except (KeyError, ValueError):
            return None

        margin = round(dem - rep, 1)
        return GenericBallotSnapshot(
            as_of=as_of,
            dem_pct=dem,
            rep_pct=rep,
            margin=margin,
            num_polls=len(rows),
            ci_dem=ci_dem,
            ci_rep=ci_rep,
        )
