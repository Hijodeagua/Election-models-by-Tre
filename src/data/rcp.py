"""RealClearPolitics scraper client.

Uses the `realclearpolitics` PyPI package where possible, with fallback
to direct HTML scraping via BeautifulSoup for pages not covered by the package.

Note: Scraping-based — may break if RCP changes their HTML structure.
Some pages have moved to realclearpolling.com.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from src.data.base import DataSource, Poll, PollAnswer, PollType, Population

# Known RCP page URLs — update as needed
RCP_URLS = {
    "trump_approval": (
        "https://www.realclearpolling.com/polls/approval/president/donald-trump"
    ),
    "generic_ballot": (
        "https://www.realclearpolling.com/polls/generic-ballot/national"
    ),
}


class RCPClient(DataSource):
    """Scraper for RealClearPolitics / RealClearPolling data."""

    name = "rcp"

    def __init__(self, cache_dir: Path | None = None, timeout: float = 30.0) -> None:
        super().__init__(cache_dir=cache_dir)
        self.timeout = timeout
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; ElectionOracle/0.1; "
                    "+https://github.com/election-oracle)"
                ),
            },
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RCPClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ── Public API ────────────────────────────────────────────────────

    def fetch_polls(
        self,
        poll_type: PollType | None = None,
        subject: str | None = None,
        url: str | None = None,
        **kwargs: Any,
    ) -> list[Poll]:
        """Fetch polls by scraping an RCP page.

        Args:
            poll_type: Used to select a known URL if `url` is not provided.
            subject: Unused for RCP (URL-driven).
            url: Direct URL to an RCP polling page. If None, infers from poll_type.
        """
        if url is None:
            if poll_type == PollType.APPROVAL:
                url = RCP_URLS["trump_approval"]
            elif poll_type == PollType.GENERIC_BALLOT:
                url = RCP_URLS["generic_ballot"]
            else:
                raise ValueError(
                    f"No known RCP URL for poll_type={poll_type}. Pass `url` directly."
                )

        cache_key = self._cache_key("page", url)
        cached = self._read_cache(cache_key)
        if cached is not None:
            return [self._dict_to_poll(p) for p in cached]

        html = self._fetch_page(url)
        polls = self._parse_polling_table(html, url)

        # Cache the normalized dicts
        self._write_cache(cache_key, [p.to_dict() for p in polls])
        return polls

    def fetch_pollsters(self) -> list[str]:
        """RCP does not expose a pollster list — returns empty."""
        return []

    # ── Scraping internals ────────────────────────────────────────────

    def _fetch_page(self, url: str) -> str:
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.text

    def _parse_polling_table(self, html: str, source_url: str) -> list[Poll]:
        """Parse the main polling data table from an RCP/RealClearPolling page.

        This is fragile by nature — RCP table structure may change.
        """
        soup = BeautifulSoup(html, "lxml")
        polls: list[Poll] = []

        # RCP typically uses a <table> with class containing "data-table" or similar
        table = soup.find("table")
        if table is None:
            return polls

        rows = table.find_all("tr")
        if len(rows) < 2:
            return polls

        # Parse header to find column indices
        header_cells = rows[0].find_all(["th", "td"])
        headers = [cell.get_text(strip=True).lower() for cell in header_cells]

        for i, row in enumerate(rows[1:], start=1):
            cells = row.find_all("td")
            if len(cells) < len(headers):
                continue

            cell_text = [c.get_text(strip=True) for c in cells]
            row_data = dict(zip(headers, cell_text, strict=False))

            try:
                poll = self._row_to_poll(row_data, index=i, source_url=source_url)
                if poll:
                    polls.append(poll)
            except (ValueError, KeyError):
                continue

        return polls

    def _row_to_poll(
        self, row: dict[str, str], index: int, source_url: str
    ) -> Poll | None:
        """Convert a single table row dict to a Poll. Returns None if unparseable."""
        pollster = row.get("poll", row.get("pollster", ""))
        if not pollster or pollster.lower() in ("rcp average", "average"):
            return None

        # Parse dates — RCP uses various formats like "2/1 - 2/5"
        date_str = row.get("date", row.get("dates", ""))
        start_date, end_date = self._parse_date_range(date_str)

        # Parse sample
        sample_raw = row.get("sample", row.get("n", ""))
        sample_size, population = self._parse_sample(sample_raw)

        # Build answers from remaining numeric columns
        skip_keys = {"poll", "pollster", "date", "dates", "sample", "n", "spread", "moe"}
        answers = []
        for key, val in row.items():
            if key in skip_keys:
                continue
            try:
                pct = float(val.replace("%", ""))
                answers.append(PollAnswer(choice=key.title(), pct=pct))
            except (ValueError, AttributeError):
                continue

        if not answers:
            return None

        # Determine poll type from URL
        poll_type = PollType.APPROVAL
        if "generic-ballot" in source_url:
            poll_type = PollType.GENERIC_BALLOT
        elif "favorab" in source_url:
            poll_type = PollType.FAVORABILITY

        return Poll(
            poll_id=f"rcp-{index}-{start_date.isoformat()}",
            source=self.name,
            poll_type=poll_type,
            pollster=pollster,
            subject=self._subject_from_url(source_url),
            start_date=start_date,
            end_date=end_date,
            sample_size=sample_size,
            population=population,
            answers=answers,
            url=source_url,
        )

    # ── Parsing helpers ───────────────────────────────────────────────

    @staticmethod
    def _parse_date_range(raw: str) -> tuple[date, date]:
        """Parse RCP date formats like '2/1 - 2/5' or '1/28 - 2/1'."""
        today = date.today()
        parts = raw.replace("–", "-").split("-")
        parts = [p.strip() for p in parts if p.strip()]

        if len(parts) == 2:
            try:
                start = datetime.strptime(parts[0], "%m/%d").replace(year=today.year).date()
                end = datetime.strptime(parts[1], "%m/%d").replace(year=today.year).date()
                # Handle year rollover (Dec poll ending in Jan)
                if end < start:
                    start = start.replace(year=today.year - 1)
                return start, end
            except ValueError:
                pass

        # Fallback: use today
        return today, today

    @staticmethod
    def _parse_sample(raw: str) -> tuple[int | None, Population | None]:
        """Parse sample like '1000 LV' or '800 RV'."""
        raw = raw.strip()
        if not raw:
            return None, None

        parts = raw.split()
        sample_size = None
        population = None

        for part in parts:
            if part.isdigit():
                sample_size = int(part)
            elif part.upper() in ("LV", "RV", "A"):
                pop_map = {
                    "LV": Population.LIKELY_VOTERS,
                    "RV": Population.REGISTERED_VOTERS,
                    "A": Population.ADULTS,
                }
                population = pop_map.get(part.upper())

        return sample_size, population

    @staticmethod
    def _subject_from_url(url: str) -> str:
        """Infer subject from the URL path."""
        if "trump" in url.lower():
            return "Donald Trump"
        if "generic-ballot" in url.lower():
            return "Generic Ballot"
        return "Unknown"

    def _dict_to_poll(self, d: dict[str, Any]) -> Poll:
        """Reconstruct a Poll from a cached dict."""
        return Poll(
            poll_id=d["poll_id"],
            source=d["source"],
            poll_type=PollType(d["poll_type"]),
            pollster=d["pollster"],
            subject=d["subject"],
            start_date=date.fromisoformat(d["start_date"]),
            end_date=date.fromisoformat(d["end_date"]),
            sample_size=d["sample_size"],
            population=Population(d["population"]) if d.get("population") else None,
            answers=[PollAnswer(**a) for a in d["answers"]],
            sponsors=d.get("sponsors", []),
            partisan=d.get("partisan", False),
            internal=d.get("internal", False),
            url=d.get("url"),
        )
