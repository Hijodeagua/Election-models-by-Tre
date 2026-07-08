"""Diagnostic probe for live data sources — run in CI, read the logs.

The development container has no outbound network, so this script exists to
answer "what do the live APIs actually look like today?" from a GitHub
Actions runner. It only prints; it never writes data files.

Usage:
    python scripts/probe_sources.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


def _show(label: str, resp: httpx.Response, body_chars: int = 300) -> None:
    body = resp.text[:body_chars].replace("\n", " ")
    print(f"  [{resp.status_code}] {label}\n      {body}")


def probe_votehub() -> None:
    print("=== VoteHub endpoint candidates ===")
    candidates = [
        "https://votehub.com/polls/api/polls?poll_type=approval",
        "https://votehub.com/polls/api/v1/polls?poll_type=approval",
        "https://votehub.com/api/polls?poll_type=approval",
        "https://api.votehub.com/polls?poll_type=approval",
        "https://polls.votehub.com/api/polls?poll_type=approval",
        "https://archive.votehub.com/api/polls?poll_type=approval",
    ]
    for url in candidates:
        try:
            resp = httpx.get(url, timeout=20, follow_redirects=True,
                             headers={"User-Agent": BROWSER_UA})
            _show(url, resp)
        except Exception as exc:
            print(f"  [ERR] {url}: {exc}")
    # The docs page itself usually names the base URL — grep it for links.
    try:
        resp = httpx.get("https://votehub.com/polls/api/", timeout=20,
                         follow_redirects=True, headers={"User-Agent": BROWSER_UA})
        import re

        urls = sorted(set(re.findall(r"https?://[^\s\"'<>]+", resp.text)))
        hits = [u for u in urls if "poll" in u.lower() or "api" in u.lower()]
        print(f"  docs page [{resp.status_code}] — URLs mentioning api/poll:")
        for u in hits[:30]:
            print(f"      {u}")
    except Exception as exc:
        print(f"  [ERR] docs page: {exc}")


def probe_kalshi() -> None:
    """Round 2: hit specific 2026 event tickers gently (1 req/s to dodge 429s)."""
    import time

    base = "https://api.elections.kalshi.com/trade-api/v2"

    print("=== Kalshi: markets by event_ticker (2026 races) ===")
    event_tickers = [
        "SENATEGA-26", "SENATEAZ-26", "SENATENV-26", "SENATEMI-26",
        "SENATEPA-26", "CONTROLS-2026", "SENATEGA-28",
    ]
    for ticker in event_tickers:
        try:
            resp = httpx.get(
                f"{base}/markets", params={"event_ticker": ticker, "limit": 20}, timeout=30
            )
            markets = resp.json().get("markets", []) if resp.status_code == 200 else []
            summary = [
                {
                    "ticker": m.get("ticker"),
                    "title": m.get("title"),
                    "yes_sub_title": m.get("yes_sub_title"),
                    "status": m.get("status"),
                    "last_price": m.get("last_price"),
                }
                for m in markets[:6]
            ]
            print(f"  {ticker} [{resp.status_code}] {json.dumps(summary)[:600]}")
        except Exception as exc:
            print(f"  [ERR] {ticker}: {exc}")
        time.sleep(1.2)

    print("=== Kalshi: events by series_ticker ===")
    for series in ("SENATEGA", "CONTROLS"):
        try:
            resp = httpx.get(
                f"{base}/events", params={"series_ticker": series, "limit": 20}, timeout=30
            )
            events = resp.json().get("events", []) if resp.status_code == 200 else []
            print(
                f"  {series} [{resp.status_code}] "
                f"{[(e.get('event_ticker'), e.get('status')) for e in events]}"
            )
        except Exception as exc:
            print(f"  [ERR] {series}: {exc}")
        time.sleep(1.2)


def probe_silver_bulletin() -> None:
    print("=== Silver Bulletin CSV link discovery ===")
    pages = [
        "https://www.natesilver.net/p/trump-approval-ratings-nate-silver-polls",
        "https://www.natesilver.net/p/generic-ballot-polls-nate-silver",
    ]
    import re

    for page in pages:
        try:
            resp = httpx.get(page, timeout=30, follow_redirects=True,
                             headers={"User-Agent": BROWSER_UA})
            urls = sorted(set(re.findall(r"https?://[^\s\"'<>)]+", resp.text)))
            csvs = [u for u in urls if ".csv" in u.lower() or "dwcdn" in u.lower()]
            print(f"  {page} [{resp.status_code}] — csv/datawrapper links:")
            for u in csvs[:20]:
                print(f"      {u}")
        except Exception as exc:
            print(f"  [ERR] {page}: {exc}")


def probe_rcp() -> None:
    print("=== RCP via RCPClient (full browser header set) ===")
    from src.data.base import PollType
    from src.data.rcp import RCPClient

    with RCPClient() as client:
        for pt in (PollType.APPROVAL, PollType.GENERIC_BALLOT):
            try:
                polls = client.fetch_polls(poll_type=pt)
                newest = max((p.end_date for p in polls), default=None)
                print(f"  {pt.value}: {len(polls)} polls, newest end_date={newest}")
            except Exception as exc:
                print(f"  [ERR] {pt.value}: {exc}")


def probe_votehub_freshness() -> None:
    """The July 2026 stall: VoteHub kept returning 200 with no new polls.
    Print the newest end_date per feed so the stall is visible in one line."""
    print("=== VoteHub feed freshness ===")
    for pt in ("approval", "generic-ballot", "head-to-head"):
        try:
            resp = httpx.get(
                "https://api.votehub.com/polls", params={"poll_type": pt}, timeout=30
            )
            rows = resp.json() if resp.status_code == 200 else []
            newest = max((r.get("end_date", "") for r in rows), default="—")
            print(f"  {pt}: [{resp.status_code}] {len(rows)} polls, newest end_date={newest}")
        except Exception as exc:
            print(f"  [ERR] {pt}: {exc}")


def probe_wikipedia_national() -> None:
    """Prove the stale-feed fallback works from CI: fetch + parse both articles."""
    print("=== Wikipedia national polling articles (stale-feed fallback) ===")
    from src.data.base import PollType
    from src.data.wikipedia_national import WikipediaNationalSource

    with WikipediaNationalSource() as src:
        for pt in (PollType.APPROVAL, PollType.GENERIC_BALLOT):
            try:
                polls = src.fetch_polls(poll_type=pt)
                newest = max((p.end_date for p in polls), default=None)
                print(f"  {pt.value}: {len(polls)} polls parsed, newest end_date={newest}")
            except Exception as exc:
                print(f"  [ERR] {pt.value}: {exc}")


def probe_ballotpedia() -> None:
    """Reachability check only — Ballotpedia is a possible second fallback,
    but has no API and stricter reuse terms; see wikipedia_national.py."""
    print("=== Ballotpedia reachability ===")
    for url in (
        "https://ballotpedia.org/Ballotpedia:Polling_index",
        "https://ballotpedia.org/United_States_Congress_elections,_2026",
    ):
        try:
            resp = httpx.get(url, timeout=30, follow_redirects=True,
                             headers={"User-Agent": BROWSER_UA})
            print(f"  [{resp.status_code}] {url} ({len(resp.text)} bytes)")
        except Exception as exc:
            print(f"  [ERR] {url}: {exc}")


def probe_polymarket_missing_races() -> None:
    print("=== Polymarket: searches that returned nothing ===")
    for query in ("Arizona Senate", "Nevada Senate", "Pennsylvania Senate"):
        try:
            resp = httpx.get(
                "https://gamma-api.polymarket.com/public-search",
                params={"q": query, "limit_per_type": 10, "events_status": "active"},
                timeout=30,
            )
            events = resp.json().get("events") or []
            titles = [e.get("title") for e in events]
            print(f"  {query!r} -> {json.dumps(titles[:10])}")
        except Exception as exc:
            print(f"  [ERR] {query}: {exc}")


def main() -> None:
    probe_votehub()
    probe_votehub_freshness()
    probe_kalshi()
    probe_silver_bulletin()
    probe_rcp()
    probe_wikipedia_national()
    probe_ballotpedia()
    probe_polymarket_missing_races()


if __name__ == "__main__":
    main()
