"""FRED / ALFRED client for state-level economic series.

Why state-level: national economic series take one value per election cycle, so
using them as model features gives ~5 observations for the archive we have.
State series vary per race, which is the only way an economic feature can be
fitted against 155 training races rather than 5 cycles.

Two transports, because a key is optional:

- **API** (``FRED_API_KEY`` set): ``api.stlouisfed.org``. Supports ALFRED
  *vintages* via ``realtime_start``/``realtime_end`` — the value as published on
  a past date, before revisions. Anything feeding a backtest must use this;
  fitting "GDP growth before the 2018 election" on today's revised figures is
  look-ahead bias.
- **Keyless CSV** (no key): ``fred.stlouisfed.org/graph/fredgraph.csv``. Current
  vintage only. Fine for charts and exploration, not for a backtest.

Series IDs follow FRED's documented state naming conventions (``TXUR``,
``TXSTHPI``, …). A few states or concepts deviate, and FRED renames series
occasionally, so nothing here assumes an ID is real: ``fetch_panel`` collects
per-series failures instead of raising, and ``scripts/download_economic_data.py
--probe`` prints exactly which IDs resolved before you spend a full pull on them.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.settings import settings

logger = logging.getLogger(__name__)

API_BASE = "https://api.stlouisfed.org/fred"
CSV_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# FRED allows 120 requests/minute per key. A state panel is ~250 requests, so
# pace them rather than getting throttled halfway through.
_MIN_REQUEST_INTERVAL = 0.55

# FRED writes missing observations as a bare period.
_MISSING = "."

STATE_ABBRS = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
    "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY",
]


@dataclass(frozen=True)
class Concept:
    """One economic concept and how to build its per-state series ID."""

    name: str
    id_template: str  # e.g. "{abbr}UR"
    frequency: str  # documentation only — what FRED publishes
    units: str
    note: str = ""

    def series_id(self, abbr: str) -> str:
        return self.id_template.format(abbr=abbr.upper())


# The Tier 1 panel. Every one of these varies by state *and* by month/quarter,
# which is what makes it usable as a per-race feature.
STATE_CONCEPTS: dict[str, Concept] = {
    c.name: c
    for c in (
        Concept(
            "unemployment_rate", "{abbr}UR", "monthly", "percent",
            "Seasonally adjusted state unemployment rate; history from 1976.",
        ),
        Concept(
            "nonfarm_payrolls", "{abbr}NA", "monthly", "thousands of persons",
            "Total nonfarm payroll employment — use the 12-month change, not the level.",
        ),
        Concept(
            "house_price_index", "{abbr}STHPI", "quarterly", "index 1980Q1=100",
            "FHFA all-transactions house price index.",
        ),
        Concept(
            "personal_income", "{abbr}OTOT", "quarterly", "millions of dollars, SAAR",
            "Total state personal income; deflate or use growth rates.",
        ),
        Concept(
            "per_capita_income", "{abbr}PCPI", "annual", "dollars",
            "Annual only — too coarse for within-cycle movement, kept for levels.",
        ),
    )
}


@dataclass(frozen=True)
class Observation:
    """One dated value in a series. ``value`` is None where FRED has no data."""

    date: date
    value: float | None


@dataclass
class SeriesFailure:
    """A series that could not be fetched, and why."""

    series_id: str
    reason: str


class FredClient:
    """Fetch FRED/ALFRED series with disk caching and per-series error capture."""

    def __init__(
        self,
        api_key: str | None = None,
        cache_dir: Path | None = None,
        realtime: date | None = None,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
        min_request_interval: float = _MIN_REQUEST_INTERVAL,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.fred_api_key
        self.cache_dir = cache_dir or (settings.raw_data_dir / "fred")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.realtime = realtime
        self._client = client or httpx.Client(
            timeout=timeout, follow_redirects=True,
            headers={"User-Agent": "election-oracle/0.1 (+policyypeaches.substack.com)"},
        )
        self._last_request = 0.0
        self._min_request_interval = min_request_interval

        if self.realtime and not self.is_configured:
            raise ValueError(
                "Vintage data (realtime=) needs a FRED API key — the keyless CSV "
                "endpoint only serves the current vintage. Set FRED_API_KEY in .env "
                "or drop --realtime."
            )

    @property
    def is_configured(self) -> bool:
        """True when an API key is available (required for vintages)."""
        return bool(self.api_key)

    # ── Public API ────────────────────────────────────────────────────

    def fetch_series(self, series_id: str, force: bool = False) -> list[Observation]:
        """Fetch one series, from cache unless ``force``.

        Raises on failure — use ``fetch_panel`` to collect failures instead.
        """
        cache_path = self._cache_path(series_id)
        if cache_path.exists() and not force:
            logger.debug("Cached %s", series_id)
            return self._parse_cache(cache_path.read_text())

        rows = self._download(series_id)
        cache_path.write_text(self._to_cache(rows))
        logger.info(
            "Fetched %s: %d observations%s",
            series_id, len(rows), f" @ {self.realtime}" if self.realtime else "",
        )
        return rows

    def fetch_panel(
        self, series_ids: Iterable[str], force: bool = False
    ) -> tuple[dict[str, list[Observation]], list[SeriesFailure]]:
        """Fetch many series; a bad ID costs one entry, not the whole run."""
        data: dict[str, list[Observation]] = {}
        failures: list[SeriesFailure] = []
        for series_id in series_ids:
            try:
                data[series_id] = self.fetch_series(series_id, force=force)
            except Exception as exc:  # noqa: BLE001 — one bad ID must not end the pull
                logger.warning("  %s failed: %s", series_id, exc)
                failures.append(SeriesFailure(series_id, str(exc)))
        return data, failures

    def probe(self, series_ids: Iterable[str]) -> dict[str, str]:
        """Check which IDs exist without pulling full history.

        Returns series_id → "ok (n obs, first–last)" or the failure reason. Run
        this before a full panel pull: FRED renames series, and the naming
        conventions in STATE_CONCEPTS do not hold for every state.
        """
        results: dict[str, str] = {}
        for series_id in series_ids:
            try:
                rows = self.fetch_series(series_id)
            except Exception as exc:  # noqa: BLE001 — probing is the point
                results[series_id] = f"FAILED: {exc}"
                continue
            dated = [o for o in rows if o.value is not None]
            if not dated:
                results[series_id] = "empty (no values)"
            else:
                results[series_id] = (
                    f"ok ({len(dated)} obs, {dated[0].date}–{dated[-1].date})"
                )
        return results

    # ── Internals ─────────────────────────────────────────────────────

    def _cache_path(self, series_id: str) -> Path:
        # Vintages cache separately: the same series has a different history
        # depending on the date you ask as of.
        suffix = f"@{self.realtime.isoformat()}" if self.realtime else ""
        return self.cache_dir / f"{series_id}{suffix}.csv"

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request = time.monotonic()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=2, max=16),
        reraise=True,
    )
    def _get(self, url: str, params: dict[str, str]) -> httpx.Response:
        self._throttle()
        resp = self._client.get(url, params=params)
        # 400 from the API means a bad series ID — a retry cannot fix it.
        if resp.status_code >= 500 or resp.status_code == 429:
            resp.raise_for_status()
        return resp

    def _download(self, series_id: str) -> list[Observation]:
        if self.is_configured:
            return self._download_api(series_id)
        return self._download_csv(series_id)

    def _download_api(self, series_id: str) -> list[Observation]:
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
        }
        if self.realtime:
            stamp = self.realtime.isoformat()
            params["realtime_start"] = stamp
            params["realtime_end"] = stamp

        resp = self._get(f"{API_BASE}/series/observations", params)
        if resp.status_code != 200:
            raise FileNotFoundError(
                f"FRED API {resp.status_code} for {series_id}: "
                f"{_api_error(resp)}"
            )
        payload = resp.json()
        return [
            Observation(_parse_date(row["date"]), _parse_value(row["value"]))
            for row in payload.get("observations", [])
        ]

    def _download_csv(self, series_id: str) -> list[Observation]:
        resp = self._get(CSV_BASE, {"id": series_id})
        text = resp.text
        if resp.status_code != 200 or text.lstrip().startswith("<"):
            raise FileNotFoundError(
                f"FRED CSV {resp.status_code} for {series_id} — unknown series ID, "
                "or the keyless endpoint rejected the request. Series names follow "
                "state conventions that do not hold universally; run --probe."
            )
        return _parse_fredgraph_csv(text, series_id)

    # ── Cache format (series-agnostic: date,value) ────────────────────

    @staticmethod
    def _to_cache(rows: list[Observation]) -> str:
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(["date", "value"])
        for obs in rows:
            writer.writerow([obs.date.isoformat(), "" if obs.value is None else obs.value])
        return out.getvalue()

    @staticmethod
    def _parse_cache(text: str) -> list[Observation]:
        reader = csv.DictReader(io.StringIO(text))
        rows = []
        for row in reader:
            raw = (row.get("value") or "").strip()
            rows.append(
                Observation(
                    _parse_date(row["date"]),
                    float(raw) if raw not in ("", _MISSING) else None,
                )
            )
        return rows


# ── Helpers ───────────────────────────────────────────────────────────

def _api_error(resp: httpx.Response) -> str:
    try:
        return str(json.loads(resp.text).get("error_message", resp.text[:200]))
    except (ValueError, TypeError):
        return resp.text[:200]


def _parse_date(raw: str) -> date:
    return datetime.strptime(raw.strip(), "%Y-%m-%d").date()


def _parse_value(raw: str) -> float | None:
    raw = (raw or "").strip()
    if raw in ("", _MISSING):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_fredgraph_csv(text: str, series_id: str) -> list[Observation]:
    """Parse the keyless CSV export: a date column plus one value column."""
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or len(header) < 2:
        raise ValueError(f"Unexpected FRED CSV shape for {series_id}: {header}")
    rows = []
    for row in reader:
        if len(row) < 2 or not row[0].strip():
            continue
        rows.append(Observation(_parse_date(row[0]), _parse_value(row[1])))
    return rows


def latest_before(observations: list[Observation], cutoff: date) -> Observation | None:
    """Most recent observation dated on or before ``cutoff`` with a value.

    Note this is the *observation* date, not the publication date: monthly state
    unemployment lands ~3 weeks after the reference month, so a value dated
    October is not knowable on election day. Pair with ``realtime=`` for a
    backtest that respects what was published when.
    """
    dated = [o for o in observations if o.value is not None and o.date <= cutoff]
    return max(dated, key=lambda o: o.date) if dated else None


def change_over(
    observations: list[Observation], cutoff: date, months: int = 12
) -> tuple[Observation | None, Observation | None]:
    """(value at cutoff, value ~``months`` earlier) for computing a change."""
    now = latest_before(observations, cutoff)
    if now is None:
        return None, None
    year = cutoff.year - months // 12
    month = cutoff.month - months % 12
    if month <= 0:
        month += 12
        year -= 1
    day = min(cutoff.day, 28)
    return now, latest_before(observations, date(year, month, day))


def state_series_ids(
    concepts: Iterable[str] | None = None, states: Iterable[str] | None = None
) -> dict[tuple[str, str], str]:
    """(state, concept) → FRED series ID for the requested slice of the panel."""
    names = list(concepts) if concepts else list(STATE_CONCEPTS)
    abbrs = [s.upper() for s in states] if states else list(STATE_ABBRS)
    unknown = set(names) - set(STATE_CONCEPTS)
    if unknown:
        raise ValueError(f"Unknown concepts: {sorted(unknown)}")
    return {
        (abbr, name): STATE_CONCEPTS[name].series_id(abbr)
        for abbr in abbrs
        for name in names
    }
