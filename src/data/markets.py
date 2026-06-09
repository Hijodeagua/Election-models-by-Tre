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


def _party_from_text(*texts: str) -> str | None:
    """Detect which party a market/outcome refers to from its labels."""
    joined = " ".join(t for t in texts if t).lower()
    if "democrat" in joined:
        return "Democrat"
    if "republican" in joined or "gop" in joined:
        return "Republican"
    return None


def _with_complement(odds: MarketOdds) -> list[MarketOdds]:
    """Add the implied other-party probability for a single-party market.

    Two-party approximation: P(other) = 1 − P(this). Slightly off in races
    with viable independents, which is fine for the comparison display.
    """
    other = "Republican" if odds.outcome == "Democrat" else "Democrat"
    complement = MarketOdds(
        as_of=odds.as_of,
        source=odds.source,
        race=odds.race,
        outcome=other,
        probability=round(1.0 - odds.probability, 4),
        url=odds.url,
    )
    return [odds, complement]


class PolymarketClient:
    """Read-only Gamma API client. No key required.

    Markets are discovered through ``/public-search`` (the ``/markets``
    endpoint has no free-text search parameter), then outcome prices are read
    from the markets nested in each matching event. Gamma encodes
    ``outcomes`` / ``outcomePrices`` as JSON-string arrays paired by position.
    """

    name = "polymarket"

    def __init__(self, base_url: str = POLYMARKET_BASE, timeout: float = 15.0) -> None:
        self.base_url = base_url
        self.timeout = timeout

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
    def _get(self, path: str, params: dict[str, Any]) -> Any:
        resp = httpx.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def fetch_markets(
        self,
        query: str,
        race: str,
        required_tokens: tuple[str, ...] = (),
        as_of: date | None = None,
    ) -> list[MarketOdds]:
        """Search active events for ``query`` and extract party probabilities.

        ``required_tokens`` (lower-cased) must all appear in the event title —
        e.g. ``("arizona", "senate")`` — to avoid picking up unrelated markets.
        """
        as_of = as_of or date.today()
        try:
            payload = self._get(
                "/public-search",
                {"q": query, "limit_per_type": 10, "events_status": "active"},
            )
        except Exception as exc:  # network failures fall back to CSV snapshot
            logger.warning("polymarket search failed for %r: %s", query, exc)
            return []

        events = payload.get("events") or [] if isinstance(payload, dict) else []
        for event in events:
            title = str(event.get("title", ""))
            if not all(tok in title.lower() for tok in required_tokens):
                continue
            slug = event.get("slug", "")
            url = f"https://polymarket.com/event/{slug}" if slug else None
            odds: list[MarketOdds] = []
            for market in event.get("markets") or []:
                outcomes = _json_list(market.get("outcomes"))
                prices = _json_list(market.get("outcomePrices"))
                question = str(market.get("question", ""))
                for outcome, price in zip(outcomes, prices, strict=False):
                    try:
                        prob = float(price)
                    except (TypeError, ValueError):
                        continue
                    # "Democrat"/"Republican" outcome labels, or Yes/No
                    # markets whose question names the party.
                    party = _party_from_text(str(outcome)) or (
                        _party_from_text(question) if str(outcome) == "Yes" else None
                    )
                    if party is None:
                        continue
                    odds.append(
                        MarketOdds(
                            as_of=as_of,
                            source=self.name,
                            race=race,
                            outcome=party,
                            probability=round(prob, 4),
                            url=url,
                        )
                    )
            if odds:
                return odds  # first matching event wins
        return []


class KalshiClient:
    """Read-only Kalshi public-market client. No key required for market data.

    2026 Senate race series follow the ``SENATE{state}`` pattern (event
    ``SENATE{state}-26``); chamber control lives in the ``CONTROLS`` series.
    Newer series carry a ``KX`` prefix, so both spellings are tried.
    Prices are in cents (0–100).
    """

    name = "kalshi"

    def __init__(self, base_url: str = KALSHI_BASE, timeout: float = 15.0) -> None:
        self.base_url = base_url
        self.timeout = timeout

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
    def _get(self, path: str, params: dict[str, Any]) -> Any:
        resp = httpx.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _markets_for_event(self, event_ticker: str) -> list[dict[str, Any]]:
        payload = self._get("/markets", {"event_ticker": event_ticker, "limit": 100})
        return payload.get("markets", []) if isinstance(payload, dict) else []

    @staticmethod
    def _market_price_cents(market: dict[str, Any]) -> float | None:
        """Best available YES price in cents.

        Thinly traded markets often have ``last_price: null`` — fall back to
        the bid/ask midpoint when both sides are quoted.
        """
        last_price = market.get("last_price")
        if last_price:
            return float(last_price)
        bid, ask = market.get("yes_bid"), market.get("yes_ask")
        if bid and ask:
            return (float(bid) + float(ask)) / 2.0
        return None

    def fetch_race_odds(
        self,
        state_abbr: str,
        race: str,
        as_of: date | None = None,
        year_suffix: str = "26",
    ) -> list[MarketOdds]:
        """Fetch the party-winner odds for one state's Senate race.

        2026 races live at event tickers like ``SENATEGA-26`` with one market
        per party (``...-D`` / ``...-R``); the KX-prefixed spelling is tried
        as a fallback for newer listings.
        """
        abbr = state_abbr.upper()
        candidates = [f"SENATE{abbr}-{year_suffix}", f"KXSENATE{abbr}-{year_suffix}"]
        return self._fetch(candidates, race, as_of=as_of)

    def fetch_control_odds(
        self, race: str, as_of: date | None = None, year: str = "2026"
    ) -> list[MarketOdds]:
        """Fetch Senate chamber-control odds (CONTROLS-{year} event)."""
        return self._fetch(
            [f"CONTROLS-{year}", f"KXCONTROLS-{year}"],
            race,
            as_of=as_of,
            title_filter="senate",
        )

    def _fetch(
        self,
        event_tickers: list[str],
        race: str,
        as_of: date | None = None,
        title_filter: str | None = None,
    ) -> list[MarketOdds]:
        as_of = as_of or date.today()
        for event_ticker in event_tickers:
            try:
                markets = self._markets_for_event(event_ticker)
            except Exception as exc:
                logger.warning("kalshi fetch failed for %r: %s", event_ticker, exc)
                continue
            odds: list[MarketOdds] = []
            for market in markets:
                title = str(market.get("title", ""))
                subtitle = str(market.get("yes_sub_title", ""))
                if title_filter and title_filter not in (title + " " + subtitle).lower():
                    continue
                price = self._market_price_cents(market)
                party = _party_from_text(subtitle, title)
                if price is None or party is None:
                    continue
                ticker = market.get("ticker", "")
                odds.append(
                    MarketOdds(
                        as_of=as_of,
                        source=self.name,
                        race=race,
                        outcome=party,
                        probability=round(price / 100.0, 4),
                        url=f"https://kalshi.com/markets/{ticker}" if ticker else None,
                    )
                )
            if odds:
                # Single-party markets imply the complement for the other side.
                parties = {o.outcome for o in odds}
                if len(parties) == 1:
                    odds = _with_complement(odds[0])
                return odds
        return []


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
