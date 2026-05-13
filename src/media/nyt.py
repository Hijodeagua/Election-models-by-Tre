"""New York Times Archive + Article Search API client.

Archive API: every article published in a given month.
Article Search API: keyword search with filters.

Free tier: 10 requests/minute, 4000 requests/day.
Docs: https://developer.nytimes.com/

All responses are cached to disk to avoid re-fetching and to respect rate limits.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://api.nytimes.com/svc/archive/v1/{year}/{month}.json"
SEARCH_URL = "https://api.nytimes.com/svc/search/v2/articlesearch.json"

# Rate limit: 10 req/min → 6 seconds between requests as a safe floor
MIN_REQUEST_INTERVAL = 6.0


@dataclass
class NYTArticle:
    """Normalized article from either the Archive or Search API."""

    article_id: str
    pub_date: date
    headline: str
    abstract: str
    lead_paragraph: str
    section: str
    keywords: list[str]
    word_count: int
    web_url: str
    source: str = "The New York Times"
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def full_text_for_analysis(self) -> str:
        """Combine headline + abstract + lead paragraph for sentiment analysis."""
        parts = [self.headline, self.abstract, self.lead_paragraph]
        return " ".join(p for p in parts if p)


class NYTClient:
    """Client for the NYT Archive and Article Search APIs."""

    def __init__(
        self,
        api_key: str = "",
        cache_dir: Path | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.cache_dir = cache_dir or settings.raw_data_dir / "nyt"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(timeout=timeout)
        self._last_request_time: float = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> NYTClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ── Archive API ───────────────────────────────────────────────────

    def fetch_archive(self, year: int, month: int) -> list[NYTArticle]:
        """Fetch all articles published in a given year/month.

        Results are cached per month — subsequent calls hit disk.
        """
        cache_path = self.cache_dir / f"archive_{year}_{month:02d}.json"
        if cache_path.exists():
            logger.info(f"Loading cached archive for {year}-{month:02d}")
            raw_docs = json.loads(cache_path.read_text())
            return [self._normalize(doc) for doc in raw_docs]

        url = ARCHIVE_URL.format(year=year, month=month)
        data = self._get(url)
        docs = data.get("response", {}).get("docs", [])

        cache_path.write_text(json.dumps(docs, default=str, indent=2))
        logger.info(f"Cached {len(docs)} articles for {year}-{month:02d}")

        return [self._normalize(doc) for doc in docs]

    def fetch_archive_range(
        self, start_year: int, start_month: int, end_year: int, end_month: int
    ) -> list[NYTArticle]:
        """Fetch articles across a range of months."""
        articles: list[NYTArticle] = []
        y, m = start_year, start_month
        while (y, m) <= (end_year, end_month):
            articles.extend(self.fetch_archive(y, m))
            m += 1
            if m > 12:
                m = 1
                y += 1
        return articles

    # ── Article Search API ────────────────────────────────────────────

    def search_articles(
        self,
        query: str,
        begin_date: date | None = None,
        end_date: date | None = None,
        section: str | None = None,
        max_pages: int = 10,
    ) -> list[NYTArticle]:
        """Search for articles matching a query.

        NYT Search returns 10 results per page, max ~200 pages.
        We default to 10 pages (100 articles) to respect rate limits.
        """
        cache_key = f"search_{query}_{begin_date}_{end_date}_{section}_{max_pages}"
        cache_path = self.cache_dir / f"{_safe_filename(cache_key)}.json"
        if cache_path.exists():
            logger.info(f"Loading cached search: {query}")
            raw_docs = json.loads(cache_path.read_text())
            return [self._normalize(doc) for doc in raw_docs]

        all_docs: list[dict] = []
        for page in range(max_pages):
            params: dict[str, Any] = {"q": query, "page": page}
            if begin_date:
                params["begin_date"] = begin_date.strftime("%Y%m%d")
            if end_date:
                params["end_date"] = end_date.strftime("%Y%m%d")
            if section:
                params["fq"] = f'section_name:("{section}")'

            data = self._get(SEARCH_URL, params=params)
            docs = data.get("response", {}).get("docs", [])
            all_docs.extend(docs)

            # Stop if we got fewer than 10 (no more pages)
            if len(docs) < 10:
                break

        cache_path.write_text(json.dumps(all_docs, default=str, indent=2))
        logger.info(f"Cached {len(all_docs)} search results for: {query}")

        return [self._normalize(doc) for doc in all_docs]

    # ── Filtering helpers ─────────────────────────────────────────────

    @staticmethod
    def filter_political(articles: list[NYTArticle]) -> list[NYTArticle]:
        """Filter to politics/election-related articles."""
        political_sections = {"u.s.", "politics", "washington", "us"}
        political_keywords = {
            "united states politics and government",
            "elections",
            "presidential election",
            "midterm elections",
            "campaigns and elections",
            "senate",
            "house of representatives",
            "congress",
        }
        results = []
        for a in articles:
            section_match = a.section.lower() in political_sections
            keyword_match = bool(set(k.lower() for k in a.keywords) & political_keywords)
            if section_match or keyword_match:
                results.append(a)
        return results

    # ── Request internals ─────────────────────────────────────────────

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict:
        """Make a rate-limited GET request to the NYT API."""
        if not self.api_key:
            raise RuntimeError(
                "NYT API key not configured. Get one at https://developer.nytimes.com/ "
                "and set NYT_API_KEY in .env"
            )

        # Rate limiting
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            sleep_time = MIN_REQUEST_INTERVAL - elapsed
            logger.debug(f"Rate limit: sleeping {sleep_time:.1f}s")
            time.sleep(sleep_time)

        params = params or {}
        params["api-key"] = self.api_key

        resp = self._client.get(url, params=params)
        self._last_request_time = time.monotonic()

        if resp.status_code == 429:
            logger.warning("NYT rate limit hit, waiting 60s...")
            time.sleep(60)
            return self._get(url, params={k: v for k, v in params.items() if k != "api-key"})

        resp.raise_for_status()
        return resp.json()

    # ── Normalization ─────────────────────────────────────────────────

    @staticmethod
    def _normalize(doc: dict[str, Any]) -> NYTArticle:
        """Convert a raw NYT API doc into a normalized NYTArticle."""
        # Headlines can be nested
        headline_obj = doc.get("headline", {})
        if isinstance(headline_obj, dict):
            headline = headline_obj.get("main", "")
        else:
            headline = str(headline_obj)

        # Parse pub_date
        pub_date_raw = doc.get("pub_date", "")
        try:
            pub_date = datetime.fromisoformat(pub_date_raw.replace("Z", "+00:00")).date()
        except (ValueError, AttributeError):
            pub_date = date.today()

        # Keywords from the keyword objects
        keywords_raw = doc.get("keywords", [])
        keywords = []
        for kw in keywords_raw:
            if isinstance(kw, dict):
                keywords.append(kw.get("value", ""))
            else:
                keywords.append(str(kw))

        return NYTArticle(
            article_id=doc.get("_id", doc.get("uri", "")),
            pub_date=pub_date,
            headline=headline,
            abstract=doc.get("abstract", ""),
            lead_paragraph=doc.get("lead_paragraph", ""),
            section=doc.get("section_name", ""),
            keywords=[k for k in keywords if k],
            word_count=int(doc.get("word_count", 0) or 0),
            web_url=doc.get("web_url", ""),
            raw=doc,
        )


def _safe_filename(s: str) -> str:
    """Convert a string to a safe filename."""
    import hashlib
    return hashlib.sha256(s.encode()).hexdigest()[:20]
