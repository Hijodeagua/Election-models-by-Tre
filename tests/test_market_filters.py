"""Market matching guards: legislature markets are never U.S. Senate odds,
three-way winner markets keep the independent leg, and the committed odds
snapshot never points a Senate race at a state-senate event."""

from __future__ import annotations

import csv
from pathlib import Path

from src.data.markets import NON_WINNER_EVENT_TOKENS, PolymarketClient

ROOT = Path(__file__).resolve().parent.parent


def _event(title, slug, outcomes, prices, question="Which party wins?"):
    return {"title": title, "slug": slug, "markets": [
        {"question": question, "outcomes": str(outcomes).replace("'", '"'),
         "outcomePrices": str([str(p) for p in prices]).replace("'", '"')},
    ]}


def test_state_legislature_markets_are_rejected(monkeypatch):
    assert "state senate" in NON_WINNER_EVENT_TOKENS and "legislature" in NON_WINNER_EVENT_TOKENS
    payload = {"events": [
        _event("Which party will win the Texas State Senate in 2026?",
               "which-party-will-win-the-texas-state-senate-in-2026",
               ["Democrat", "Republican"], [0.034, 0.9575]),
        _event("Texas Senate Election Winner", "texas-senate-election-winner",
               ["Democrat", "Republican"], [0.62, 0.38]),
    ]}
    client = PolymarketClient()
    monkeypatch.setattr(client, "_get", lambda *a, **k: payload)
    odds = client.fetch_markets("Texas Senate 2026", race="Texas Senate 2026",
                                required_tokens=("texas", "senate"))
    assert [(o.outcome, o.probability) for o in odds] == [("Democrat", 0.62), ("Republican", 0.38)]
    assert all("state-senate" not in (o.url or "") for o in odds)


def test_three_way_winner_market_keeps_the_independent(monkeypatch):
    payload = {"events": [
        _event("Nebraska Senate Election Winner", "nebraska-senate-election-winner",
               ["Democrat", "Republican", "Dan Osborn"], [0.015, 0.70, 0.285]),
    ]}
    client = PolymarketClient()
    monkeypatch.setattr(client, "_get", lambda *a, **k: payload)
    odds = client.fetch_markets("Nebraska Senate 2026", race="Nebraska Senate 2026",
                                required_tokens=("nebraska", "senate"),
                                independent_candidate="Dan Osborn")
    assert {o.outcome: o.probability for o in odds} == {
        "Democrat": 0.015, "Republican": 0.70, "Independent": 0.285,
    }
    # Without the independent hint the two party legs sum to 0.715 and the
    # event is rejected as before.
    assert client.fetch_markets("q", race="r", required_tokens=("nebraska",)) == []


def test_committed_odds_snapshot_has_no_state_senate_urls():
    rows = list(csv.DictReader((ROOT / "data" / "fallback" / "market_odds.csv").open()))
    bad = [r for r in rows if "Senate 2026" in r["race"] and "state-senate" in (r["url"] or "")]
    assert bad == []
