"""Kalshi public market-data client — keyless read-only endpoints.

API docs: https://trading-api.readme.io/
    GET https://api.elections.kalshi.com/trade-api/v2/events
        ?status=open&with_nested_markets=true&limit=200&cursor=...

Public market data (events, markets, prices) needs no authentication; only
trading does. Prices are in cents (0–100) → divide by 100 for probability.
We use the yes_bid/yes_ask midpoint when both sides are quoted, otherwise
last_price.

Same resilience contract as PolymarketClient: malformed entries are skipped,
network failures bubble up to the caller (refresh_data.py treats them as
best-effort).
"""

from __future__ import annotations

import contextlib
import logging
import re
from datetime import date
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.data.market_odds import KIND_CONTROL, KIND_RACE, MarketOdds, detect_state

logger = logging.getLogger(__name__)

KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

_SENATE_RE = re.compile(r"\bsenate\b", re.IGNORECASE)
_CONTROL_RE = re.compile(r"\b(control|majority|balance of power)\b", re.IGNORECASE)
_DEM_RE = re.compile(r"\b(democrat(?:s|ic)?|dem)\b", re.IGNORECASE)
_REP_RE = re.compile(r"\b(republican(?:s)?|gop|rep)\b", re.IGNORECASE)


def _price_to_prob(market: dict) -> float | None:
    """Best available probability from a Kalshi market dict (cents → 0–1)."""
    bid, ask = market.get("yes_bid"), market.get("yes_ask")
    try:
        if bid and ask:
            return round((float(bid) + float(ask)) / 2 / 100.0, 4)
        last = market.get("last_price")
        if last:
            return round(float(last) / 100.0, 4)
    except (TypeError, ValueError):
        pass
    return None


class KalshiClient:
    """Read-only client for Kalshi public market data (no key needed)."""

    name = "kalshi"

    def __init__(self, base_url: str = KALSHI_BASE_URL, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> KalshiClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _get(self, path: str, params: dict[str, Any]) -> dict:
        resp = self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    # ── Public API ────────────────────────────────────────────────────

    def fetch_senate_odds(self, year: int = 2026, max_pages: int = 10) -> list[MarketOdds]:
        """Fetch open Senate events (per-race + chamber control)."""
        odds: list[MarketOdds] = []
        cursor = ""
        for _ in range(max_pages):
            params: dict[str, Any] = {
                "status": "open",
                "with_nested_markets": "true",
                "limit": 200,
            }
            if cursor:
                params["cursor"] = cursor
            payload = self._get("/events", params=params)
            for event in payload.get("events", []):
                title = str(event.get("title", ""))
                if not _SENATE_RE.search(title):
                    continue
                parsed = self._event_to_odds(event, year)
                if parsed is not None:
                    odds.append(parsed)
            cursor = payload.get("cursor") or ""
            if not cursor:
                break
        return odds

    # ── Parsing ───────────────────────────────────────────────────────

    def _event_to_odds(self, event: dict, year: int) -> MarketOdds | None:
        title = str(event.get("title", ""))
        ticker = str(event.get("event_ticker", ""))
        # Kalshi event tickers end in the expiry year (e.g., ...-26).
        if str(year)[-2:] not in ticker and str(year) not in title:
            return None

        state = detect_state(title)
        kind = KIND_CONTROL if (_CONTROL_RE.search(title) and not state) else KIND_RACE
        if kind == KIND_RACE and not state:
            return None

        dem_prob = rep_prob = None
        volume = 0.0
        for market in event.get("markets", []):
            prob = _price_to_prob(market)
            if prob is None:
                continue
            with contextlib.suppress(TypeError, ValueError):
                volume += float(market.get("volume") or 0)
            label = " ".join(
                str(market.get(k, "")) for k in ("yes_sub_title", "subtitle", "title", "ticker")
            )
            if _DEM_RE.search(label):
                dem_prob = prob
            elif _REP_RE.search(label):
                rep_prob = prob

        if dem_prob is None and rep_prob is None:
            return None
        return MarketOdds(
            source=self.name,
            market_id=ticker,
            title=title,
            kind=kind,
            state=state,
            dem_win_prob=dem_prob,
            rep_win_prob=rep_prob,
            volume=volume or None,
            as_of=date.today(),
            url=f"https://kalshi.com/markets/{ticker.lower()}" if ticker else "",
        )
