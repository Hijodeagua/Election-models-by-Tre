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
    print("=== Kalshi: open events mentioning 'senate' ===")
    base = "https://api.elections.kalshi.com/trade-api/v2"
    cursor = None
    found = 0
    try:
        for _page in range(8):
            params: dict[str, str | int] = {"status": "open", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            resp = httpx.get(f"{base}/events", params=params, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            for event in payload.get("events", []):
                title = str(event.get("title", ""))
                if "senate" in title.lower():
                    found += 1
                    print(
                        f"  event_ticker={event.get('event_ticker')} "
                        f"series_ticker={event.get('series_ticker')} "
                        f"title={title!r}"
                    )
            cursor = payload.get("cursor")
            if not cursor:
                break
        print(f"  total senate events found: {found}")
    except Exception as exc:
        print(f"  [ERR] events scan: {exc}")

    print("=== Kalshi: sample markets for first senate series ===")
    try:
        resp = httpx.get(
            f"{base}/markets",
            params={"series_ticker": "KXSENATERACEGA", "limit": 10},
            timeout=30,
        )
        print(f"  KXSENATERACEGA [{resp.status_code}] {resp.text[:300]}")
    except Exception as exc:
        print(f"  [ERR]: {exc}")


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
    print("=== RCP with browser UA ===")
    url = "https://www.realclearpolling.com/polls/approval/president/donald-trump"
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
    probe_kalshi()
    probe_silver_bulletin()
    probe_rcp()
    probe_polymarket_missing_races()


if __name__ == "__main__":
    main()
