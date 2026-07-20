"""Wikipedia fallback for national approval / generic-ballot polls.

VoteHub is the primary feed for both trackers, but it can go quiet (its
approval and generic-ballot feeds stalled for 10+ days in July 2026 while
the refresh job dutifully re-fetched the same stale payload twice a day).
When the primary feed's newest poll is older than a staleness threshold,
``scripts/refresh_data.py`` tops the CSV up from Wikipedia's national
polling articles using this module.

Why Wikipedia and not Ballotpedia: the MediaWiki action API is already
proven reachable from the CI runner (the Senate scraper uses it every
refresh), its wikitables are machine-regular, and parsing is shared with
``wikipedia_senate``. Ballotpedia's polling pages are hand-formatted HTML
with no API, unverified reachability from CI, and stricter reuse terms —
``scripts/probe_sources.py`` probes it so we have evidence if a second
fallback is ever needed.

Same design rules as the Senate scraper: parsing is a pure function
(unit-testable on fixture HTML) and every network path is best-effort —
failures yield zero polls, never exceptions.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from io import StringIO
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from src.data.base import DataSource, Poll, PollAnswer, PollType
from src.data.wikipedia_senate import (
    _UA,
    WIKIPEDIA_API,
    _clean,
    _parse_pct,
    _parse_sample,
    is_aggregate_pollster,
    parse_dates,
)

logger = logging.getLogger(__name__)

# Default article titles — override via arguments if Wikipedia reorganizes.
APPROVAL_ARTICLE = "Opinion_polling_on_the_second_Donald_Trump_administration"
GENERIC_BALLOT_ARTICLE = "2026_United_States_House_of_Representatives_elections"

_DATE_COL_RE = re.compile(r"administered|conducted|date", re.I)


def _find_col(columns: list[str], want: str, reject: str | None = None) -> str | None:
    """First column containing ``want`` (and not ``reject``), case-insensitive."""
    for col in columns:
        low = col.lower()
        if want in low and not (reject and reject in low):
            return col
    return None


def _table_polls(
    table: pd.DataFrame,
    poll_type: PollType,
    subject: str,
    choice_a: tuple[str, str, str | None],  # (want, canonical label, reject)
    choice_b: tuple[str, str, str | None],
    default_year: int,
    id_prefix: str,
) -> list[Poll]:
    """Extract polls from one wikitable, or [] if it isn't a polling table."""
    if isinstance(table.columns, pd.MultiIndex):
        table.columns = [
            " ".join(_clean(c) for c in tup if _clean(c)).strip()
            for tup in table.columns
        ]
    columns = [str(c) for c in table.columns]

    date_col = next((c for c in columns if _DATE_COL_RE.search(c)), None)
    a_col = _find_col(columns, choice_a[0], choice_a[2])
    b_col = _find_col(columns, choice_b[0], choice_b[2])
    poll_col = next(
        (c for c in columns if "poll" in c.lower() and "source" in c.lower()),
        columns[0] if columns else None,
    )
    if not (date_col and a_col and b_col and poll_col):
        return []
    sample_col = next((c for c in columns if "sample" in c.lower()), None)

    polls: list[Poll] = []
    for idx, row in table.iterrows():
        pollster = _clean(row.get(poll_col, ""))
        if not pollster or is_aggregate_pollster(pollster):
            continue
        dates = parse_dates(str(row.get(date_col, "")), default_year)
        a_pct = _parse_pct(str(row.get(a_col, "")))
        b_pct = _parse_pct(str(row.get(b_col, "")))
        if dates is None or a_pct is None or b_pct is None:
            continue
        start, end = dates
        sample_size, population = (
            _parse_sample(str(row.get(sample_col, ""))) if sample_col else (None, None)
        )
        polls.append(
            Poll(
                poll_id=f"wikipedia-{id_prefix}-{end.isoformat()}-{idx}",
                source="wikipedia",
                poll_type=poll_type,
                pollster=pollster,
                subject=subject,
                start_date=start,
                end_date=end,
                sample_size=sample_size,
                population=population,
                answers=[
                    PollAnswer(choice=choice_a[1], pct=a_pct),
                    PollAnswer(choice=choice_b[1], pct=b_pct),
                ],
            )
        )
    return polls


def parse_national_tables(
    html: str,
    poll_type: PollType,
    default_year: int = 2026,
) -> list[Poll]:
    """Extract national approval or generic-ballot polls from article HTML.

    Unlike the Senate parser this scans EVERY matching table — the national
    articles split polls into one wikitable per month/period.
    """
    if poll_type == PollType.APPROVAL:
        subject, id_prefix = "Donald Trump", "approval"
        choice_a = ("approv", "Approve", "disapprov")
        choice_b = ("disapprov", "Disapprove", None)
    elif poll_type == PollType.GENERIC_BALLOT:
        subject, id_prefix = "Generic Ballot", "generic-ballot"
        choice_a = ("democrat", "Democrat", None)
        choice_b = ("republican", "Republican", None)
    else:
        raise ValueError(f"No national Wikipedia source for poll_type={poll_type}")

    try:
        # flavor pinned to lxml: without it, a no-tables page makes pandas
        # fall back to html5lib and raise ImportError instead of ValueError.
        tables = pd.read_html(StringIO(html), match=_DATE_COL_RE, flavor="lxml")
    except (ValueError, ImportError):
        logger.info("  wikipedia %s: no polling tables found", id_prefix)
        return []

    polls: list[Poll] = []
    for table in tables:
        polls.extend(
            _table_polls(
                table, poll_type, subject, choice_a, choice_b, default_year, id_prefix
            )
        )
    logger.info("  wikipedia %s: parsed %d polls", id_prefix, len(polls))
    return polls


def polls_newer_than(polls: list[Poll], cutoff: date) -> list[Poll]:
    """Polls whose fieldwork ended strictly after ``cutoff``."""
    return [p for p in polls if p.end_date > cutoff]


class WikipediaNationalSource(DataSource):
    """Fetch national approval / generic-ballot polls from Wikipedia."""

    name = "wikipedia"

    def __init__(self, cache_dir: Path | None = None, timeout: float = 30.0) -> None:
        super().__init__(cache_dir=cache_dir)
        self.timeout = timeout
        self._client = httpx.Client(
            timeout=timeout, headers={"User-Agent": _UA}, follow_redirects=True
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> WikipediaNationalSource:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def fetch_pollsters(self) -> list[str]:  # noqa: D102 - not supported
        return []

    def _fetch_article_html(self, title: str) -> str:
        """Fetch rendered article HTML via the action API. '' on any failure."""
        try:
            resp = self._client.get(
                WIKIPEDIA_API,
                params={
                    "action": "parse",
                    "page": title,
                    "prop": "text",
                    "formatversion": "2",
                    "format": "json",
                    "redirects": "1",
                },
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            logger.warning("  wikipedia %s: fetch failed (%s)", title, exc)
            return ""
        if "error" in payload:
            logger.warning(
                "  wikipedia %s: API error (%s)", title, payload["error"].get("info")
            )
            return ""
        return payload.get("parse", {}).get("text", "")

    def fetch_polls(
        self,
        poll_type: PollType | None = None,
        subject: str | None = None,
        article: str | None = None,
        default_year: int = 2026,
        **kwargs: Any,
    ) -> list[Poll]:
        """Fetch national polls for APPROVAL or GENERIC_BALLOT. Best-effort."""
        if poll_type == PollType.APPROVAL:
            title = article or APPROVAL_ARTICLE
        elif poll_type == PollType.GENERIC_BALLOT:
            title = article or GENERIC_BALLOT_ARTICLE
        else:
            return []
        html = self._fetch_article_html(title)
        if not html:
            return []
        try:
            return parse_national_tables(html, poll_type, default_year=default_year)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("  wikipedia %s: parse failed (%s)", title, exc)
            return []
