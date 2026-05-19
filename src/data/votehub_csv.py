"""Parse VoteHub's exported wide-format CSV into normalized Poll objects.

VoteHub exports one row per poll in a "Leading / Trailing" layout:

    Date Range,Grade,Pollster,Sponsor,Sample Size,Sample Type,
    Population,Weight,Leading Result,Leading %,Trailing Result,
    Trailing %,Spread

Rows are ordered newest-first.  Because no year is included, year is
inferred by walking the file top-to-bottom and decrementing whenever
the end-month jumps numerically forward (i.e. we crossed a Jan→Dec
boundary going backwards in time).

Population "V" (voter file) is treated as REGISTERED_VOTERS.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date
from pathlib import Path

from src.data.base import Poll, PollAnswer, PollType, Population

_MONTH_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

_POPULATION_MAP = {
    "v": Population.REGISTERED_VOTERS,
    "rv": Population.REGISTERED_VOTERS,
    "lv": Population.LIKELY_VOTERS,
    "a": Population.ADULTS,
    "r": Population.REGISTERED_VOTERS,  # VoteHub "R" = registered
    "a": Population.ADULTS,             # VoteHub "A" = adults
}

_GRADE_QUALITY: dict[str, float] = {
    "A+": 1.0, "A": 0.95, "A-": 0.90,
    "B+": 0.80, "B": 0.75, "B-": 0.70,
    "C+": 0.60, "C": 0.55, "C-": 0.50,
    "D": 0.35, "-": 0.20, "": 0.20,
}


def _parse_month(token: str) -> int:
    """'May.' → 5, 'Jan.' → 1"""
    key = token.rstrip(".").strip()
    return _MONTH_MAP[key]


def _parse_date_range(raw: str, year: int) -> tuple[date, date, int, int]:
    """Return (start_date, end_date, start_month, end_month).

    Handles:
        "May. 11-15"         → same month
        "Apr. 29-May. 5"     → cross-month
        "May. 11"            → single day
        "Nov. 20-Dec. 8"     → cross-month
    """
    raw = raw.strip()
    # cross-month: "Apr. 29-May. 5" or "Nov. 20-Dec. 8"
    cross = re.match(
        r"([A-Za-z]+)\.\s*(\d+)\s*-\s*([A-Za-z]+)\.\s*(\d+)", raw
    )
    if cross:
        sm = _parse_month(cross.group(1))
        sd = int(cross.group(2))
        em = _parse_month(cross.group(3))
        ed = int(cross.group(4))
        ey = year
        # if end month < start month we crossed a real Dec→Jan within one entry
        sy = year if sm >= em else year - 1
        return date(sy, sm, sd), date(ey, em, ed), sm, em

    # same-month range or single day: "May. 11-15" or "May. 11"
    same = re.match(r"([A-Za-z]+)\.\s*(\d+)(?:\s*-\s*(\d+))?", raw)
    if same:
        m = _parse_month(same.group(1))
        sd = int(same.group(2))
        ed = int(same.group(3)) if same.group(3) else sd
        return date(year, m, sd), date(year, m, ed), m, m

    raise ValueError(f"Cannot parse date range: {raw!r}")


def _clean_pct(raw: str) -> float | None:
    """'59%' → 59.0, 'EVEN' → 50.0, '' → None, non-numeric → None"""
    raw = raw.strip()
    if not raw or raw.upper() in ("N/A", "NA", "-"):
        return None
    if raw.upper() == "EVEN":
        return 50.0
    stripped = raw.rstrip("%")
    try:
        return float(stripped)
    except ValueError:
        return None


def _make_poll_id(pollster: str, start: date, end: date) -> str:
    key = f"{pollster}|{start}|{end}"
    return "vh-csv-" + hashlib.md5(key.encode()).hexdigest()[:10]


class VoteHubCsvLoader:
    """Load a VoteHub-exported CSV and return normalized Poll objects.

    Usage:
        loader = VoteHubCsvLoader(poll_type=PollType.APPROVAL)
        polls = loader.load(Path("data/fallback/votehub_approval.csv"))
    """

    def __init__(self, poll_type: PollType) -> None:
        self.poll_type = poll_type

    def load(self, path: Path) -> list[Poll]:
        text = path.read_text(encoding="utf-8")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)

        # Pre-extract end-months to do year inference in a single pass
        parsed_rows: list[tuple[date, date, dict]] = []
        current_year = 2026
        prev_end_month: int | None = None

        for row in rows:
            date_range = row.get("Date Range", "").strip()
            if not date_range:
                continue

            try:
                start, end, sm, em = _parse_date_range(date_range, current_year)
            except (ValueError, KeyError):
                continue

            # If end-month jumped forward (numerically), we crossed a year boundary
            # going backwards through the file (e.g., Jan→Dec means we moved to prior year)
            if prev_end_month is not None and em > prev_end_month:
                current_year -= 1
                # Re-parse with corrected year
                try:
                    start, end, sm, em = _parse_date_range(date_range, current_year)
                except (ValueError, KeyError):
                    continue

            prev_end_month = em
            parsed_rows.append((start, end, row))

        polls: list[Poll] = []
        seen_ids: set[str] = set()

        for start, end, row in parsed_rows:
            pollster = row.get("Pollster", "").strip()
            if not pollster:
                continue

            leading_choice = row.get("Leading Result") or row.get("Leading Party") or ""
            trailing_choice = row.get("Trailing Result") or row.get("Trailing Party") or ""
            leading_pct = _clean_pct(row.get("Leading %", ""))
            trailing_pct = _clean_pct(row.get("Trailing %", ""))

            leading_choice = leading_choice.strip()
            trailing_choice = trailing_choice.strip()

            # Skip rows with misaligned columns (malformed CSV lines)
            raw_pct = row.get("Leading %", "").strip()
            if raw_pct and raw_pct.upper() not in ("EVEN",) and not raw_pct.endswith("%"):
                continue

            if not leading_choice or leading_pct is None:
                continue

            # Normalize choice labels for approval polls
            if self.poll_type == PollType.APPROVAL:
                leading_choice = _normalize_approval_choice(leading_choice)
                trailing_choice = _normalize_approval_choice(trailing_choice)

            answers = [PollAnswer(choice=leading_choice, pct=leading_pct)]
            if trailing_choice and trailing_pct is not None:
                answers.append(PollAnswer(choice=trailing_choice, pct=trailing_pct))

            sample_raw = row.get("Sample Size", "").strip()
            try:
                sample_size = int(sample_raw.replace(",", ""))
            except (ValueError, AttributeError):
                sample_size = None

            pop_raw = row.get("Population", "").strip().lower()
            population = _POPULATION_MAP.get(pop_raw)

            sponsor_raw = row.get("Sponsor", "").strip()
            sponsors = [s.strip() for s in sponsor_raw.split("/")] if sponsor_raw else []

            poll_id = _make_poll_id(pollster, start, end)
            if poll_id in seen_ids:
                # Deduplicate same pollster/dates
                continue
            seen_ids.add(poll_id)

            subject = _default_subject(self.poll_type)
            grade = row.get("Grade", "").strip()

            polls.append(Poll(
                poll_id=poll_id,
                source="votehub_csv",
                poll_type=self.poll_type,
                pollster=pollster,
                subject=subject,
                start_date=start,
                end_date=end,
                sample_size=sample_size,
                population=population,
                answers=answers,
                sponsors=sponsors,
                partisan=False,
                raw={"grade": grade},
            ))

        return polls


def _normalize_approval_choice(raw: str) -> str:
    """Normalize VoteHub approval labels to canonical 'Approve'/'Disapprove'."""
    low = raw.lower()
    if "approve" in low and "dis" not in low:
        return "Approve"
    if "disapprove" in low or ("approve" in low and "dis" in low):
        return "Disapprove"
    return raw  # pass through for generic ballot party names


def _default_subject(poll_type: PollType) -> str:
    if poll_type == PollType.APPROVAL:
        return "Donald Trump"
    if poll_type == PollType.GENERIC_BALLOT:
        return "Generic Ballot"
    return ""
