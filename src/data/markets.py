"""Prediction-market odds — Polymarket and Kalshi clients with CSV fallback.

Market prices are *not* polls: they are crowd-implied probabilities, so they
bypass the polling engine entirely and map to :class:`MarketOdds` records.

Both APIs are free and keyless for read-only market data:

* Polymarket Gamma API — ``https://gamma-api.polymarket.com/markets``
* Kalshi public API   — ``https://api.elections.kalshi.com/trade-api/v2/markets``

The clients are best-effort: any network failure returns an empty list and the
pipeline falls back to the committed snapshot in
``data/fallback/market_odds.csv`` (refreshed by the daily GitHub Actions cron
via ``scripts/refresh_data.py --source markets``).
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

POLYMARKET_BASE = "https://gamma-api.polymarket.com"
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"

# Aggregate chamber-control markets use this race key instead of a state.
SENATE_CONTROL_RACE = "senate-control-2026"

MARKET_ODDS_COLUMNS = ["as_of", "source", "race", "outcome", "probability", "url", "is_seed"]


@dataclass
class MarketOdds:
    """A single outcome price from a prediction market.

    ``probability`` is the implied probability on a 0–1 scale (e.g. a 62¢
    YES contract → 0.62). ``race`` uses the same state naming as Senate poll
    subjects ("Georgia Senate 2026") or :data:`SENATE_CONTROL_RACE` for the
    chamber-control aggregate. ``outcome`` is the party or candidate the
    probability refers to.
    """

    as_of: date
    source: str  # "polymarket" | "kalshi"
    race: str
    outcome: str
    probability: float
    url: str | None = None
    is_seed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "source": self.source,
            "race": self.race,
            "outcome": self.outcome,
            "probability": self.probability,
            "url": self.url,
            "is_seed": self.is_seed,
        }


# ── Offline CSV fallback ──────────────────────────────────────────────────────


class MarketOddsCsvSource:
    """Load the committed market-odds snapshot from ``data/fallback``."""

    def __init__(self, fallback_dir: Path) -> None:
        self.path = fallback_dir / "market_odds.csv"

    def load(self) -> list[MarketOdds]:
        if not self.path.exists():
            return []
        rows = list(csv.DictReader(io.StringIO(self.path.read_text(encoding="utf-8"))))
        odds: list[MarketOdds] = []
        for row in rows:
            try:
                odds.append(
                    MarketOdds(
                        as_of=date.fromisoformat(row["as_of"]),
                        source=row["source"],
                        race=row["race"],
                        outcome=row["outcome"],
                        probability=float(row["probability"]),
                        url=row.get("url") or None,
                        is_seed=row.get("is_seed", "").strip().lower() == "true",
                    )
                )
            except (KeyError, ValueError) as exc:
                logger.warning("skipping malformed market_odds row %r: %s", row, exc)
        return odds


def write_market_odds_csv(odds: list[MarketOdds], path: Path) -> None:
    """Serialise odds to the fallback CSV format (used by refresh_data.py)."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=MARKET_ODDS_COLUMNS)
    writer.writeheader()
    for o in odds:
        row = o.to_dict()
        row["is_seed"] = "true" if o.is_seed else "false"
        row["url"] = o.url or ""
        writer.writerow(row)
    path.write_text(buf.getvalue(), encoding="utf-8")


# ── Live clients (best-effort) ────────────────────────────────────────────────


class PolymarketClient:
    """Read-only Gamma API client. No key required."""

    name = "polymarket"

    def __init__(self, base_url: str = POLYMARKET_BASE, timeout: float = 15.0) -> None:
        self.base_url = base_url
        self.timeout = timeout

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
    def _get(self, path: str, params: dict[str, Any]) -> Any:
        resp = httpx.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def fetch_markets(self, query: str, race: str, as_of: date | None = None) -> list[MarketOdds]:
        """Search active markets matching ``query`` and map outcomes to odds.

        Gamma returns ``outcomes`` / ``outcomePrices`` as JSON-encoded string
        arrays; we pair them positionally.
        """
        as_of = as_of or date.today()
        try:
            markets = self._get(
                "/markets", {"closed": "false", "limit": 20, "search": query}
            )
        except Exception as exc:  # network failures fall back to CSV snapshot
            logger.warning("polymarket fetch failed for %r: %s", query, exc)
            return []

        odds: list[MarketOdds] = []
        for market in markets if isinstance(markets, list) else []:
            outcomes = _json_list(market.get("outcomes"))
            prices = _json_list(market.get("outcomePrices"))
            slug = market.get("slug", "")
            for outcome, price in zip(outcomes, prices, strict=False):
                try:
                    prob = float(price)
                except (TypeError, ValueError):
                    continue
                odds.append(
                    MarketOdds(
                        as_of=as_of,
                        source=self.name,
                        race=race,
                        outcome=str(outcome),
                        probability=round(prob, 4),
                        url=f"https://polymarket.com/market/{slug}" if slug else None,
                    )
                )
        return odds


class KalshiClient:
    """Read-only Kalshi public-market client. No key required for market data."""

    name = "kalshi"

    def __init__(self, base_url: str = KALSHI_BASE, timeout: float = 15.0) -> None:
        self.base_url = base_url
        self.timeout = timeout

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
    def _get(self, path: str, params: dict[str, Any]) -> Any:
        resp = httpx.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def fetch_markets(
        self, series_ticker: str, race: str, outcome: str, as_of: date | None = None
    ) -> list[MarketOdds]:
        """Fetch open markets for a series and convert last price (¢) to 0–1."""
        as_of = as_of or date.today()
        try:
            payload = self._get(
                "/markets", {"series_ticker": series_ticker, "status": "open", "limit": 20}
            )
        except Exception as exc:
            logger.warning("kalshi fetch failed for %r: %s", series_ticker, exc)
            return []

        odds: list[MarketOdds] = []
        for market in payload.get("markets", []) if isinstance(payload, dict) else []:
            last_price = market.get("last_price")
            if last_price is None:
                continue
            ticker = market.get("ticker", "")
            odds.append(
                MarketOdds(
                    as_of=as_of,
                    source=self.name,
                    race=race,
                    outcome=market.get("yes_sub_title") or outcome,
                    probability=round(float(last_price) / 100.0, 4),
                    url=f"https://kalshi.com/markets/{ticker}" if ticker else None,
                )
            )
        return odds


def _json_list(raw: Any) -> list[Any]:
    """Gamma encodes list fields as JSON strings; tolerate both forms."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        import json

        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except ValueError:
            return []
    return []


# ── Convenience lookups for the export pipeline ───────────────────────────────


def odds_for_race(odds: list[MarketOdds], race: str) -> dict[str, dict[str, float]]:
    """Group odds for a race by source → outcome → probability.

    When a source has multiple snapshots for the same outcome the most recent
    ``as_of`` wins.
    """
    grouped: dict[str, dict[str, tuple[date, float]]] = {}
    for o in odds:
        if o.race != race:
            continue
        bucket = grouped.setdefault(o.source, {})
        existing = bucket.get(o.outcome)
        if existing is None or o.as_of >= existing[0]:
            bucket[o.outcome] = (o.as_of, o.probability)
    return {
        source: {outcome: prob for outcome, (_, prob) in outcomes.items()}
        for source, outcomes in grouped.items()
    }
