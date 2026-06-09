"""Polymarket Gamma API client — keyless public market data.

Gamma API docs: https://docs.polymarket.com/
    GET https://gamma-api.polymarket.com/events?closed=false&limit=100&offset=N

Returns Senate-related markets normalised into MarketOdds. Prices on a
binary market are read from the market's ``outcomePrices`` (a JSON-encoded
list of strings aligned with ``outcomes``); price ≈ implied probability.

This client never raises on partial/malformed market payloads — bad entries
are skipped with a warning so a single odd market can't break the refresh.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.data.market_odds import KIND_CONTROL, KIND_RACE, MarketOdds, detect_state

logger = logging.getLogger(__name__)

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"

_SENATE_RE = re.compile(r"\bsenate\b", re.IGNORECASE)
_CONTROL_RE = re.compile(r"\b(control|majority|balance of power)\b", re.IGNORECASE)
_DEM_RE = re.compile(r"\b(democrat(?:s|ic)?|dem)\b", re.IGNORECASE)
_REP_RE = re.compile(r"\b(republican(?:s)?|gop|rep)\b", re.IGNORECASE)


class PolymarketClient:
    """Read-only client for Polymarket's public Gamma API (no key needed)."""

    name = "polymarket"

    def __init__(self, base_url: str = GAMMA_BASE_URL, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PolymarketClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _get(self, path: str, params: dict[str, Any]) -> Any:
        resp = self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    # ── Public API ────────────────────────────────────────────────────

    def fetch_senate_odds(self, year: int = 2026, max_pages: int = 5) -> list[MarketOdds]:
        """Fetch open Senate markets (per-race + chamber control) for `year`."""
        events: list[dict] = []
        for page in range(max_pages):
            batch = self._get(
                "/events",
                params={
                    "closed": "false",
                    "limit": 100,
                    "offset": page * 100,
                    "order": "volume",
                    "ascending": "false",
                },
            )
            if not isinstance(batch, list) or not batch:
                break
            events.extend(batch)
            if len(batch) < 100:
                break

        odds: list[MarketOdds] = []
        for event in events:
            title = str(event.get("title", ""))
            haystack = title + str(event.get("slug", ""))
            if not _SENATE_RE.search(title) or str(year) not in haystack:
                continue
            parsed = self._event_to_odds(event)
            if parsed is not None:
                odds.append(parsed)
        return odds

    # ── Parsing ───────────────────────────────────────────────────────

    def _event_to_odds(self, event: dict) -> MarketOdds | None:
        title = str(event.get("title", ""))
        state = detect_state(title)
        kind = KIND_CONTROL if (_CONTROL_RE.search(title) and not state) else KIND_RACE
        if kind == KIND_RACE and not state:
            return None  # Senate-adjacent novelty market; ignore

        dem_prob, rep_prob, volume = None, None, None
        try:
            volume = float(event.get("volume") or 0.0) or None
            for market in event.get("markets", []):
                d, r = _market_party_probs(market)
                dem_prob = d if d is not None else dem_prob
                rep_prob = r if r is not None else rep_prob
        except (TypeError, ValueError) as exc:
            logger.warning("Polymarket parse failed for %r: %s", title, exc)
            return None

        if dem_prob is None and rep_prob is None:
            return None
        return MarketOdds(
            source=self.name,
            market_id=str(event.get("id", event.get("slug", ""))),
            title=title,
            kind=kind,
            state=state,
            dem_win_prob=dem_prob,
            rep_win_prob=rep_prob,
            volume=volume,
            as_of=date.today(),
            url=f"https://polymarket.com/event/{event.get('slug', '')}",
        )


def _market_party_probs(market: dict) -> tuple[float | None, float | None]:
    """Extract (dem_prob, rep_prob) from one market's outcomes/prices."""
    outcomes_raw = market.get("outcomes")
    prices_raw = market.get("outcomePrices")
    outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else (outcomes_raw or [])
    prices = json.loads(prices_raw) if isinstance(prices_raw, str) else (prices_raw or [])
    if len(outcomes) != len(prices):
        return None, None

    question = str(market.get("question", market.get("groupItemTitle", "")))
    dem_prob = rep_prob = None
    for outcome, price in zip(outcomes, prices, strict=False):
        p = float(price)
        label = str(outcome)
        # Binary party market ("Democratic"/"Republican") or a party question
        # with Yes/No outcomes ("Will Democrats win ...?" → Yes price).
        if _DEM_RE.search(label):
            dem_prob = p
        elif _REP_RE.search(label):
            rep_prob = p
        elif label.lower() == "yes":
            if _DEM_RE.search(question):
                dem_prob = p
            elif _REP_RE.search(question):
                rep_prob = p
    return dem_prob, rep_prob
