"""RealClearPolling "Latest Polls" page → Poll objects.

The per-race RCP pages need a URL per matchup; the latest-polls page lists
every new poll across all races in one place, which is what we want for a
daily sweep. The page's visible text is a fixed sequence per entry:

    <weekday, Month day>          (a date header, repeated per day)
    2026 Texas Senate - Paxton vs. Talarico
    YouGov                         (pollster; trailing * marks a partisan sponsor)
    Talarico 51, Paxton 47         (results)
    Talarico                       (leader)
    +4                             (spread, or "Tie")

So we parse the text, not the markup: ``BeautifulSoup.get_text("\\n")`` keeps
that order, and the parser survives class-name churn. Only entries we can
map onto a configured race are kept — Senate general-election lines whose
two names match the race's configured candidates (by last name), plus the
generic congressional ballot. Governor, House and primary lines are ignored.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from src.data.base import Poll, PollAnswer, PollType

logger = logging.getLogger(__name__)

LATEST_POLLS_URL = "https://www.realclearpolling.com/latest-polls"

_DATE_RE = re.compile(
    r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2})$"
)
_SENATE_RE = re.compile(
    r"^(?P<year>20\d\d)\s+(?P<state>[A-Z][A-Za-z .]+?)\s+Senate(?P<special>\s+Special Election)?"
    r"\s+-\s+(?P<matchup>.+)$"
)
_GENERIC_RE = re.compile(r"^(?P<year>20\d\d)\s+Generic Congressional Vote$")
_RESULT_RE = re.compile(
    r"^(?P<a>[^,]+?)\s+(?P<pa>\d{1,2}(?:\.\d)?),"
    r"\s*(?P<b>[^,]+?)\s+(?P<pb>\d{1,2}(?:\.\d)?)(?:,|$)"
)
_MONTHS = {
    m: i for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July", "August",
         "September", "October", "November", "December"], start=1,
    )
}


def _last_name(name: str) -> str:
    parts = re.sub(r"[^\w\s'-]", "", name).split()
    return parts[-1].lower() if parts else ""


def _name_matches(rcp_label: str, configured: str | None) -> bool:
    """RCP labels use surnames ("Graham Nordone", "J. Sullivan"); match on the
    configured candidate's last name appearing in the label."""
    if not configured:
        return False
    label = rcp_label.lower()
    last = _last_name(configured)
    return bool(last) and re.search(rf"\b{re.escape(last)}\b", label) is not None


def parse_latest_polls_text(
    text: str,
    races: list[dict],
    today: date | None = None,
) -> list[Poll]:
    """Parse the page text. ``races`` is config/senate_2026.json's
    competitive_races (state, race, dem_candidate, rep_candidate)."""
    today = today or date.today()
    by_state = {e["state"].lower(): e for e in races}
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]

    polls: list[Poll] = []
    current: date | None = None
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = _DATE_RE.match(ln)
        if m:
            month, day = _MONTHS[m.group(1)], int(m.group(2))
            year = today.year
            # Release lists only roll back a few days; a month ahead of today
            # means the previous year.
            if month > today.month + 1:
                year -= 1
            current = date(year, month, day)
            i += 1
            continue

        sen = _SENATE_RE.match(ln)
        gen = _GENERIC_RE.match(ln)
        if (sen or gen) and current is not None and i + 2 < len(lines):
            pollster_raw = lines[i + 1]
            result = _RESULT_RE.match(lines[i + 2])
            if result:
                stars = pollster_raw.count("*")
                pollster = pollster_raw.rstrip("*").strip()
                a, pa, b, pb = (
                    result.group("a").strip(), float(result.group("pa")),
                    result.group("b").strip(), float(result.group("pb")),
                )
                poll = None
                if gen:
                    choices = {"democrat": "Dem", "republican": "Rep"}
                    ca = next((v for k, v in choices.items() if k in a.lower()), None)
                    cb = next((v for k, v in choices.items() if k in b.lower()), None)
                    if ca and cb and ca != cb:
                        poll = _make_poll(
                            PollType.GENERIC_BALLOT, "2026", pollster, current, stars,
                            [PollAnswer(choice=ca, pct=pa), PollAnswer(choice=cb, pct=pb)],
                            f"rcp-generic-{current.isoformat()}-{i}",
                        )
                elif sen and "RCV" not in sen.group("matchup"):
                    entry = by_state.get(sen.group("state").strip().lower())
                    if entry:
                        dem, rep = entry.get("dem_candidate"), entry.get("rep_candidate")
                        answers = []
                        for label, pct in ((a, pa), (b, pb)):
                            if _name_matches(label, dem):
                                answers.append(PollAnswer(choice=dem, pct=pct, party="Democrat"))
                            elif _name_matches(label, rep):
                                answers.append(PollAnswer(choice=rep, pct=pct, party="Republican"))
                        parties = {ans.party for ans in answers}
                        if len(answers) == 2 and parties == {"Democrat", "Republican"}:
                            slug = entry["state"].lower().replace(" ", "-")
                            poll = _make_poll(
                                PollType.HEAD_TO_HEAD, entry["race"], pollster, current, stars,
                                answers, f"rcp-{slug}-{current.isoformat()}-{i}",
                            )
                        else:
                            logger.info(
                                "  rcp: %s — could not map %r / %r onto %s",
                                entry["race"], a, b, (dem, rep),
                            )
                if poll:
                    polls.append(poll)
                i += 3
                continue
        i += 1
    return polls


def _make_poll(
    poll_type: PollType, subject: str, pollster: str, day: date, stars: int,
    answers: list[PollAnswer], poll_id: str,
) -> Poll:
    return Poll(
        poll_id=poll_id,
        source="rcp",
        poll_type=poll_type,
        pollster=pollster,
        subject=subject,
        start_date=day,
        end_date=day,
        sample_size=None,
        population=None,
        answers=answers,
        raw={"partisan_flag": stars, "release_date_only": True},
    )


def parse_latest_polls_html(html: str, races: list[dict], today: date | None = None) -> list[Poll]:
    text = BeautifulSoup(html, "lxml").get_text("\n")
    return parse_latest_polls_text(text, races, today=today)


def _now() -> datetime:  # pragma: no cover - indirection for tests
    return datetime.now()
