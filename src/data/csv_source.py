"""Local CSV fallback data source.

When live API calls fail, polls can be loaded from hand-downloaded CSV files
placed in data/fallback/.  The runner prints the file's modification time and
the `source` column value so outputs are always labeled with where data came
from and when it was pulled.

Expected files in data/fallback/:
    approval.csv        — presidential approval polls
    generic_ballot.csv  — generic congressional ballot polls
    senate.csv          — Senate race head-to-head polls

CSV format (one row per poll answer, UTF-8):
    poll_id, pollster, subject, start_date, end_date,
    sample_size, population, partisan, choice, pct, source

All columns except poll_id, pollster, subject, start_date, end_date,
choice, and pct may be left blank.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from src.data.base import Poll, PollAnswer, PollType, Population

# Maps the fallback filename stem to a poll type
_FILENAME_TO_TYPE: dict[str, PollType] = {
    "approval": PollType.APPROVAL,
    "generic_ballot": PollType.GENERIC_BALLOT,
    "senate": PollType.HEAD_TO_HEAD,
}


@dataclass
class FallbackMeta:
    """Provenance info for a CSV-loaded dataset."""

    poll_type: PollType
    path: Path
    pulled_at: datetime   # file modification time — set by OS when user saves the file
    source_label: str     # first non-empty value from the `source` column

    def display(self) -> str:
        return (
            f"CSV fallback  ·  "
            f"pulled {self.pulled_at.strftime('%Y-%m-%d %H:%M')}  ·  "
            f"from {self.source_label}"
        )


class CsvFallbackSource:
    """Load normalized Poll objects from local CSV files.

    Usage:
        fb = CsvFallbackSource(Path("data/fallback"))
        polls, meta = fb.load(PollType.APPROVAL)
        if meta:
            print(meta.display())
    """

    REQUIRED_COLUMNS = {"poll_id", "pollster", "subject", "start_date", "end_date", "choice", "pct"}

    def __init__(self, fallback_dir: Path) -> None:
        self.fallback_dir = fallback_dir

    def load(self, poll_type: PollType) -> tuple[list[Poll], FallbackMeta | None]:
        """Return (polls, metadata) for the given poll type.

        Returns ([], None) if no file exists for that type.
        """
        stem = {v: k for k, v in _FILENAME_TO_TYPE.items()}.get(poll_type)
        if stem is None:
            return [], None

        path = self.fallback_dir / f"{stem}.csv"
        if not path.exists():
            return [], None

        pulled_at = datetime.fromtimestamp(path.stat().st_mtime)
        polls, source_label = self._parse(path, poll_type)

        if not polls:
            return [], None

        meta = FallbackMeta(
            poll_type=poll_type,
            path=path,
            pulled_at=pulled_at,
            source_label=source_label or path.name,
        )
        return polls, meta

    def available(self) -> list[PollType]:
        """Return poll types that have a fallback file present."""
        found = []
        for stem, pt in _FILENAME_TO_TYPE.items():
            if (self.fallback_dir / f"{stem}.csv").exists():
                found.append(pt)
        return found

    # ── Parsing ───────────────────────────────────────────────────────

    def _parse(self, path: Path, poll_type: PollType) -> tuple[list[Poll], str]:
        """Read the CSV and group rows into Poll objects by poll_id.

        Returns (polls, source_label).
        """
        text = path.read_text(encoding="utf-8")
        reader = csv.DictReader(io.StringIO(text))

        if reader.fieldnames is None:
            return [], ""

        missing = self.REQUIRED_COLUMNS - set(f.strip() for f in reader.fieldnames)
        if missing:
            raise ValueError(
                f"{path.name} is missing required columns: {missing}\n"
                f"Found: {list(reader.fieldnames)}"
            )

        # Group rows by poll_id; collect answers per poll
        grouped: dict[str, dict] = {}
        source_label = ""

        for row in reader:
            pid = row["poll_id"].strip()
            if not pid:
                continue

            if pid not in grouped:
                grouped[pid] = {
                    "pollster": row["pollster"].strip(),
                    "subject": row["subject"].strip(),
                    "start_date": row["start_date"].strip(),
                    "end_date": row["end_date"].strip(),
                    "sample_size": row.get("sample_size", "").strip(),
                    "population": row.get("population", "").strip(),
                    "partisan": row.get("partisan", "").strip().lower() in ("true", "1", "yes"),
                    "answers": [],
                    "source": row.get("source", "").strip(),
                }

            grouped[pid]["answers"].append(
                PollAnswer(
                    choice=row["choice"].strip(),
                    pct=float(row["pct"]),
                )
            )

            if not source_label and row.get("source", "").strip():
                source_label = row["source"].strip()

        polls = []
        for pid, data in grouped.items():
            try:
                poll = Poll(
                    poll_id=f"csv-{pid}",
                    source="csv_fallback",
                    poll_type=poll_type,
                    pollster=data["pollster"],
                    subject=data["subject"],
                    start_date=date.fromisoformat(data["start_date"]),
                    end_date=date.fromisoformat(data["end_date"]),
                    sample_size=int(data["sample_size"]) if data["sample_size"].isdigit() else None,
                    population=_parse_population(data["population"]),
                    answers=data["answers"],
                    partisan=data["partisan"],
                )
                polls.append(poll)
            except (ValueError, KeyError):
                continue

        return polls, source_label


def _parse_population(raw: str) -> Population | None:
    return {
        "lv": Population.LIKELY_VOTERS,
        "rv": Population.REGISTERED_VOTERS,
        "a": Population.ADULTS,
    }.get(raw.lower())
