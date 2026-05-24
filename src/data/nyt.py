"""NYT Article Search API client.

Fetches articles for a given state/race and normalises them into
ArticleSignal objects for consumption by the vibes model.

Authentication
--------------
Set NYT_API_KEY in the environment (or .env file) before use.

Rate limits
-----------
The Article Search API allows 10 requests/minute and 4000/day.
This client enforces a 6-second inter-request sleep and uses disk cache
to avoid re-fetching pages we've already pulled.

Historical coverage
-------------------
The API goes back to 1851 in principle, though article snippets and metadata
quality varies.  For vibes purposes we target 2012–present where coverage is
consistent enough to score.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.models.vibes import ArticleSignal

logger = logging.getLogger(__name__)

_NYT_ARTICLE_SEARCH_URL = "https://api.nytimes.com/svc/search/v2/articlesearch.json"
_DEFAULT_CACHE_DIR = Path("data/cache/nyt")
_RATE_LIMIT_SLEEP_SEC = 6.5  # NYT allows 10 req/min → one per 6 s + buffer


class NYTArticleSource:
    """Fetch and normalise NYT articles for Senate race vibes scoring.

    Parameters
    ----------
    api_key:
        NYT API key.  Defaults to the NYT_API_KEY environment variable.
    cache_dir:
        Directory for JSON page caches.  Caches are keyed by query + date range.
    """

    def __init__(
        self,
        api_key: str | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("NYT_API_KEY", "")
        if not self.api_key:
            logger.warning(
                "NYT_API_KEY not set — live fetch will fail. "
                "Provide the key or use cached results."
            )
        self.cache_dir = cache_dir or _DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(timeout=30)

    # ── Public interface ───────────────────────────────────────────────────────

    def fetch_race_articles(
        self,
        state: str,
        year: int,
        race_id: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        max_pages: int = 10,
    ) -> list[ArticleSignal]:
        """Fetch NYT articles about a Senate race and return ArticleSignals.

        Args:
            state: Full state name ("Georgia") or abbreviation ("GA").
            year: Election year.
            race_id: Override the auto-generated race ID (e.g. "GA-Senate-2026").
            start_date: Earliest article date (defaults to Jan 1 of year-1).
            end_date: Latest article date (defaults to election day = Nov of year).
            max_pages: Pagination cap (each page = 10 articles).
        """
        abbr = _STATE_ABBREVS.get(state.title(), state.upper()[:2])
        rid = race_id or f"{abbr}-Senate-{year}"

        if start_date is None:
            start_date = date(year - 1, 1, 1)
        if end_date is None:
            end_date = date(year, 11, 30)

        query = f'"{state}" Senate {year}'
        raw_docs = self._paginate(query, start_date, end_date, max_pages)

        signals: list[ArticleSignal] = []
        for doc in raw_docs:
            signal = self._normalise(doc, rid, state, year)
            if signal is not None:
                signals.append(signal)
        return signals

    def fetch_historical_race_articles(
        self,
        races: list[tuple[str, int]],   # (state, year) pairs
        max_pages_per_race: int = 5,
    ) -> list[ArticleSignal]:
        """Batch fetch articles for multiple historical races (2012–present).

        Respects rate limits between races.
        """
        all_signals: list[ArticleSignal] = []
        for state, year in races:
            logger.info("Fetching NYT articles: %s %d", state, year)
            signals = self.fetch_race_articles(state, year, max_pages=max_pages_per_race)
            all_signals.extend(signals)
            time.sleep(_RATE_LIMIT_SLEEP_SEC)
        return all_signals

    # ── Pagination ─────────────────────────────────────────────────────────────

    def _paginate(
        self,
        query: str,
        start_date: date,
        end_date: date,
        max_pages: int,
    ) -> list[dict]:
        docs: list[dict] = []
        for page in range(max_pages):
            cache_key = f"{query}_{start_date}_{end_date}_p{page}"
            cached = self._read_cache(cache_key)
            if cached is not None:
                docs.extend(cached)
                if len(cached) < 10:
                    break  # last page
                continue

            page_docs = self._fetch_page(query, start_date, end_date, page)
            self._write_cache(cache_key, page_docs)
            docs.extend(page_docs)
            if len(page_docs) < 10:
                break  # end of results
            time.sleep(_RATE_LIMIT_SLEEP_SEC)
        return docs

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=10, max=60))
    def _fetch_page(
        self,
        query: str,
        start_date: date,
        end_date: date,
        page: int,
    ) -> list[dict]:
        params = {
            "q": query,
            "begin_date": start_date.strftime("%Y%m%d"),
            "end_date": end_date.strftime("%Y%m%d"),
            "sort": "relevance",
            "page": page,
            "fq": 'section_name:("U.S." "Politics") OR desk:("National Desk" "Politics")',
            "api-key": self.api_key,
        }
        resp = self._client.get(_NYT_ARTICLE_SEARCH_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", {}).get("docs", [])

    # ── Normalisation ──────────────────────────────────────────────────────────

    @staticmethod
    def _normalise(doc: dict, race: str, state: str, year: int) -> ArticleSignal | None:
        """Convert a raw NYT API doc into an ArticleSignal."""
        try:
            headline = doc.get("headline", {}).get("main", "")
            snippet = doc.get("snippet", "") or doc.get("abstract", "")
            pub_date_str = doc.get("pub_date", "")[:10]  # "2026-05-01T..."
            pub_date = date.fromisoformat(pub_date_str)
            article_id = doc.get("_id", doc.get("web_url", ""))
        except Exception:
            return None

        if not headline:
            return None

        return ArticleSignal(
            article_id=article_id,
            headline=headline,
            snippet=snippet,
            publication_date=pub_date,
            race=race,
            state=state,
            year=year,
            source="nyt",
        )

    # ── Cache helpers ──────────────────────────────────────────────────────────

    def _cache_path(self, key: str) -> Path:
        import hashlib
        hashed = hashlib.sha256(key.encode()).hexdigest()[:16]
        return self.cache_dir / f"{hashed}.json"

    def _read_cache(self, key: str) -> list[dict] | None:
        path = self._cache_path(key)
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                return None
        return None

    def _write_cache(self, key: str, docs: list[dict]) -> None:
        path = self._cache_path(key)
        try:
            path.write_text(json.dumps(docs, default=str))
        except Exception as exc:
            logger.warning("Failed to write NYT cache: %s", exc)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> NYTArticleSource:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# ── State name → abbreviation lookup ──────────────────────────────────────────

_STATE_ABBREVS: dict[str, str] = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
}
