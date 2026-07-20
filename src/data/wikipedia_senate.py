"""Wikipedia Senate poll scraper — fills the gap VoteHub leaves.

VoteHub's public API returns zero head-to-head polls, so the Senate tracker
otherwise falls back to a hand-curated CSV. Wikipedia keeps a well-maintained
"General election polling" wikitable on each race's article
(e.g. ``2026 United States Senate election in Georgia``); this client fetches
those tables and normalises them into :class:`Poll` objects.

Design notes
------------
* Parsing is split from fetching so the table parser can be unit-tested against
  a saved HTML fixture (no network).
* It is **best-effort**: any failure (network, layout change, unparseable row)
  yields fewer/zero polls rather than raising, so the export pipeline keeps
  running on the committed fallback CSV.
* Candidate columns are matched to the configured Dem/Rep names, so only the
  head-to-head matchup we track is extracted (hypothetical/primary subsections
  that don't name both tracked candidates are skipped).
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

from src.data.base import DataSource, Poll, PollAnswer, PollType, Population

logger = logging.getLogger(__name__)

# Use the sanctioned MediaWiki action API rather than scraping the human-facing
# /wiki/ page — Wikimedia 403s datacenter IPs (e.g. CI runners) that fetch
# rendered pages with a browser UA, but serves the API to clients that identify
# themselves per its User-Agent policy.
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

# Wikimedia's UA policy wants a descriptive agent with a contact URL — a
# spoofed browser UA is what gets blocked.
_UA = (
    "PolicyPeachesElectionOracle/0.1 "
    "(https://github.com/Hijodeagua/Election-models-by-Tre)"
)

_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ],
        start=1,
    )
}
# Accept 3-letter abbreviations too.
_MONTHS.update({k[:3]: v for k, v in _MONTHS.items()})

_POP_MAP = {
    "lv": Population.LIKELY_VOTERS,
    "rv": Population.REGISTERED_VOTERS,
    "v": Population.REGISTERED_VOTERS,
    "a": Population.ADULTS,
}

# Poll-of-polls / model rows that Wikipedia lists inside the same wikitables as
# real polls. They must never enter a feed: ingesting an average as if it were
# a single poll double-counts and distorts the weighted average, and — worse —
# a race article's *aggregation* table often sits ABOVE the individual-poll
# table, so if the parser accepts its rows it stops at the aggregates and never
# reaches the real polls (this is exactly how the Senate feed froze in July
# 2026: "RealClearPolitics"/"270toWin" rows were accepted and the real polls
# below them were never read).
#
# Patterns are deliberately specific so genuine pollsters that merely share a
# word are kept — e.g. "RealClear Opinion Research" (a real poll) is NOT
# "RealClearPolitics" (the RCP average), and "NewsNation/Decision Desk HQ" (a
# real poll) is left in.
_AGGREGATE_PATTERNS = (
    r"\baverage\b",              # "RCP Average", "Polling average"
    r"aggregat",                 # aggregate / aggregation
    r"projection",
    r"\bnowcast\b",
    r"realclearpolitics",        # RCP poll-of-polls (keeps "RealClear Opinion Research")
    r"real\s*clear\s*politics",
    r"\brcp\b",
    r"270\s*to\s*win",           # 270toWin model
    r"race to the wh",           # "Race to the WH" / "...White House"
    r"fivethirtyeight",
    r"\b538\b",
    r"silver bulletin",
    r"split[\s-]ticket",
)
_AGGREGATE_RE = re.compile("|".join(_AGGREGATE_PATTERNS), re.I)


def is_aggregate_pollster(name: str) -> bool:
    """True for poll-of-polls / model rows that must be excluded from feeds."""
    return bool(name) and bool(_AGGREGATE_RE.search(name))


def article_title_for_state(state: str) -> str:
    """Default Wikipedia article title for a state's 2026 Senate race."""
    return f"2026 United States Senate election in {state}".replace(" ", "_")


def _clean(text: Any) -> str:
    """Strip footnote markers, citations and whitespace from a cell."""
    s = str(text)
    s = re.sub(r"\[[^\]]*\]", "", s)  # [a], [1], [note 1]
    s = s.replace("\xa0", " ").replace("–", "-").replace("—", "-")
    return s.strip()


def _parse_pct(text: str) -> float | None:
    """Extract a percentage like '45%' or '45.3' → 45.0 / 45.3."""
    cleaned = _clean(text).replace("%", "").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def _parse_sample(text: str) -> tuple[int | None, Population | None]:
    """Parse '812 (LV)' / '1,003 LV' → (812, LV)."""
    cleaned = _clean(text)
    pop: Population | None = None
    pm = re.search(r"\b(LV|RV|V|A)\b", cleaned, re.IGNORECASE)
    if pm:
        pop = _POP_MAP.get(pm.group(1).lower())
    nm = re.search(r"[\d,]{2,}", cleaned)
    size = int(nm.group().replace(",", "")) if nm else None
    return size, pop


def parse_dates(text: str, default_year: int) -> tuple[date, date] | None:
    """Parse Wikipedia date ranges into (start, end).

    Handles: 'October 1-5, 2026', 'September 28 - October 2, 2026',
    'October 5, 2026' (single day), 'Oct 1-5, 2026'.
    """
    raw = _clean(text)
    # Year, if present at the end.
    ym = re.search(r"(\d{4})\s*$", raw)
    year = int(ym.group(1)) if ym else default_year
    body = raw[: ym.start()].strip(" ,") if ym else raw

    # Cross-month: "September 28 - October 2"
    m = re.match(
        r"([A-Za-z]+)\s+(\d{1,2})\s*-\s*([A-Za-z]+)\s+(\d{1,2})$", body
    )
    if m:
        sm = _MONTHS.get(m.group(1).lower())
        em = _MONTHS.get(m.group(3).lower())
        if sm and em:
            sy = year - 1 if sm > em else year
            try:
                return date(sy, sm, int(m.group(2))), date(year, em, int(m.group(4)))
            except ValueError:
                return None

    # Same-month range: "October 1-5" or single day "October 5"
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2})(?:\s*-\s*(\d{1,2}))?$", body)
    if m:
        mo = _MONTHS.get(m.group(1).lower())
        if mo:
            sd = int(m.group(2))
            ed = int(m.group(3)) if m.group(3) else sd
            try:
                return date(year, mo, sd), date(year, mo, ed)
            except ValueError:
                return None
    return None


def _match_column(columns: list[str], candidate: str) -> str | None:
    """Find the table column whose header contains the candidate's surname."""
    surname = candidate.split()[-1].lower()
    for col in columns:
        if surname in col.lower():
            return col
    return None


# Party annotation in a candidate column header, e.g. "Troy Jackson (D)",
# "Susan Collins (R)", "Tim Walz (DFL)". Wikipedia race tables carry these on
# the general-election matchup columns, which lets us pick "the Democrat" and
# "the Republican" without a configured nominee name.
_PARTY_SUFFIX_RE = re.compile(r"\(\s*(D|DFL|R)\b[^)]*\)", re.I)


def _column_party(col: str) -> str | None:
    """"Democrat"/"Republican" if the column header is party-annotated."""
    m = _PARTY_SUFFIX_RE.search(col)
    if not m:
        return None
    letter = m.group(1).upper()
    if letter in ("D", "DFL"):
        return "Democrat"
    if letter == "R":
        return "Republican"
    return None


def _candidate_name_from_column(col: str) -> str:
    """Clean candidate name from a column header ('Troy Jackson (D)' → 'Troy
    Jackson'), dropping the party parenthetical and any footnote markers."""
    name = _PARTY_SUFFIX_RE.sub("", _clean(col)).strip()
    # Drop a trailing bare parenthetical (e.g. sample-note leftovers).
    return re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()


def _top_party_column(
    table: pd.DataFrame, columns: list[str], party: str
) -> str | None:
    """Pick the leading candidate column for a party: the party-annotated
    column with the most filled-in poll numbers (the de-facto frontrunner),
    breaking ties by higher average share. Returns None if the party isn't
    represented with annotated columns."""
    candidates = [c for c in columns if _column_party(c) == party]
    if not candidates:
        return None

    def _score(col: str) -> tuple[int, float]:
        vals = [_parse_pct(str(v)) for v in table[col]]
        vals = [v for v in vals if v is not None]
        count = len(vals)
        mean = sum(vals) / count if count else 0.0
        return count, mean

    return max(candidates, key=_score)


def parse_polling_tables(
    html: str,
    state: str,
    race: str,
    dem_candidate: str | None,
    rep_candidate: str | None,
    default_year: int = 2026,
) -> list[Poll]:
    """Extract head-to-head polls for one race from article HTML.

    Pure function (no network) so it can be unit-tested against a fixture.

    ``dem_candidate`` / ``rep_candidate`` name the tracked matchup. When a
    configured name isn't a column in the table — the race has no settled
    nominee yet, or the tracked candidate dropped out — the parser falls back
    to the party's top (most-polled) candidate, read from Wikipedia's ``(D)`` /
    ``(R)`` column annotations. Pass ``None`` to always auto-pick that party's
    frontrunner. Extracted answers are tagged with their party so downstream
    code can find "the Democrat" without the nominee's name.
    """
    try:
        # flavor pinned to lxml: without it, a no-tables page makes pandas
        # fall back to html5lib and raise ImportError instead of ValueError.
        tables = pd.read_html(
            StringIO(html), match=re.compile("administered|conducted", re.I),
            flavor="lxml",
        )
    except (ValueError, ImportError):
        logger.info("  %s: no polling table found in article", race)
        return []

    polls: list[Poll] = []
    for table in tables:
        # Flatten any multi-index headers to single strings.
        if isinstance(table.columns, pd.MultiIndex):
            table.columns = [
                " ".join(_clean(c) for c in tup if _clean(c)).strip()
                for tup in table.columns
            ]
        columns = [str(c) for c in table.columns]
        date_col = next(
            (c for c in columns if "administered" in c.lower() or "conducted" in c.lower()),
            None,
        )
        poll_col = next(
            (c for c in columns if "poll" in c.lower() and "source" in c.lower()),
            columns[0] if columns else None,
        )
        # Resolve each side to a column: the configured candidate if present,
        # otherwise the party's top-polled candidate from the (D)/(R) columns.
        dem_col = _match_column(columns, dem_candidate) if dem_candidate else None
        dem_name = dem_candidate
        if dem_col is None:
            dem_col = _top_party_column(table, columns, "Democrat")
            dem_name = _candidate_name_from_column(dem_col) if dem_col else None

        rep_col = _match_column(columns, rep_candidate) if rep_candidate else None
        rep_name = rep_candidate
        if rep_col is None:
            rep_col = _top_party_column(table, columns, "Republican")
            rep_name = _candidate_name_from_column(rep_col) if rep_col else None

        if not (date_col and dem_col and rep_col and dem_name and rep_name):
            logger.info(
                "  %s: skipping a table (cols=%s; dem=%s rep=%s)",
                race, columns, dem_col, rep_col,
            )
            continue

        sample_col = next((c for c in columns if "sample" in c.lower()), None)

        for idx, row in table.iterrows():
            pollster = _clean(row.get(poll_col, ""))
            # Skip aggregate / non-poll rows. Dropping these also lets the loop
            # fall through an aggregation table to the real individual-poll
            # table below it, instead of stopping on the aggregates.
            if not pollster or is_aggregate_pollster(pollster):
                continue
            dates = parse_dates(str(row.get(date_col, "")), default_year)
            dem_pct = _parse_pct(str(row.get(dem_col, "")))
            rep_pct = _parse_pct(str(row.get(rep_col, "")))
            if dates is None or dem_pct is None or rep_pct is None:
                continue
            sample_size, population = (
                _parse_sample(str(row.get(sample_col, ""))) if sample_col else (None, None)
            )
            start, end = dates
            polls.append(
                Poll(
                    poll_id=f"wikipedia-{state.lower().replace(' ', '-')}-{end.isoformat()}-{idx}",
                    source="wikipedia",
                    poll_type=PollType.HEAD_TO_HEAD,
                    pollster=pollster,
                    subject=race,  # e.g. "Georgia Senate 2026" — state-detectable
                    start_date=start,
                    end_date=end,
                    sample_size=sample_size,
                    population=population,
                    answers=[
                        PollAnswer(choice=dem_name, pct=dem_pct, party="Democrat"),
                        PollAnswer(choice=rep_name, pct=rep_pct, party="Republican"),
                    ],
                )
            )
        if polls:
            # First table that yields the matchup is the general-election table.
            break
    logger.info("  %s: parsed %d polls from Wikipedia", race, len(polls))
    return polls


class WikipediaSenateSource(DataSource):
    """Fetch per-race Senate polls from Wikipedia race articles."""

    name = "wikipedia"

    def __init__(self, cache_dir: Path | None = None, timeout: float = 30.0) -> None:
        super().__init__(cache_dir=cache_dir)
        self.timeout = timeout
        self._client = httpx.Client(
            timeout=timeout, headers={"User-Agent": _UA}, follow_redirects=True
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> WikipediaSenateSource:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def fetch_pollsters(self) -> list[str]:  # noqa: D102 - not supported
        return []

    def fetch_race(
        self,
        state: str,
        race: str,
        dem_candidate: str | None,
        rep_candidate: str | None,
        article: str | None = None,
        default_year: int = 2026,
    ) -> list[Poll]:
        """Fetch and parse one race's article. Best-effort (never raises)."""
        title = article or article_title_for_state(state)
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
        except Exception as exc:  # network / HTTP errors fall back silently
            logger.warning("  %s: Wikipedia fetch failed (%s)", race, exc)
            return []
        if "error" in payload:
            logger.warning(
                "  %s: Wikipedia API error (%s)", race, payload["error"].get("info")
            )
            return []
        html = payload.get("parse", {}).get("text", "")
        if not html:
            logger.info("  %s: empty article body", race)
            return []
        return parse_polling_tables(
            html, state, race, dem_candidate, rep_candidate, default_year
        )

    def fetch_polls(
        self,
        poll_type: PollType | None = None,
        subject: str | None = None,
        **kwargs: Any,
    ) -> list[Poll]:
        """DataSource interface shim — use :meth:`fetch_race` for real work."""
        return []
