"""Economic fundamentals — national inflation, gas prices, state unemployment.

Sources (all best-effort; the committed snapshot in
``data/fallback/economic.csv`` is what the pipeline reads):

* **CPI (inflation)** — the ``datasets/cpi-us`` GitHub mirror of BLS CPI-U
  (all items, monthly). Keyless, reachable from CI and most sandboxes.
  ``cpi_yoy`` = year-over-year % change of the latest month.
* **Gas prices** — EIA weekly retail regular gasoline, national
  (``EMM_EPMR_PTE_NUS_DPG``), per state where EIA publishes one (CA, CO, FL,
  MA, MN, NY, OH, TX, WA) and otherwise the state's PADD sub-district.
  Needs ``EIA_API_KEY`` (free). Series: ``gas_price`` (US / state).
* **Unemployment** — BLS LAUS state unemployment rate (seasonally adjusted)
  and the national rate, via the BLS public API v1 (keyless, rate-limited).
  Series: ``unemployment`` (US / state).

``EconomicSnapshot`` exposes the values the models use: national CPI YoY,
national gas price, and per-state gas-price and unemployment *deviations*
from the national figure (state − national). Missing series are ``None``
and contribute nothing; the forecast exports which ones were available.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CPI_MIRROR_URLS = [
    "https://raw.githubusercontent.com/datasets/cpi-us/main/data/cpiai.csv",
    "https://raw.githubusercontent.com/datasets/cpi-us/master/data/cpiai.csv",
]
EIA_BASE = "https://api.eia.gov/v2"
BLS_BASE = "https://api.bls.gov/publicAPI/v1/timeseries/data/"

ECONOMIC_COLUMNS = ["as_of", "series", "state", "value", "unit", "source"]

# EIA weekly retail regular gasoline series. States without their own series
# map to a PADD sub-district (EIA publishes 1A/1B/1C/2/3/4/5).
EIA_GAS_SERIES = {
    "US": "EMM_EPMR_PTE_NUS_DPG",
    "CA": "EMM_EPMR_PTE_SCA_DPG", "CO": "EMM_EPMR_PTE_SCO_DPG", "FL": "EMM_EPMR_PTE_SFL_DPG",
    "MA": "EMM_EPMR_PTE_SMA_DPG", "MN": "EMM_EPMR_PTE_SMN_DPG", "NY": "EMM_EPMR_PTE_SNY_DPG",
    "OH": "EMM_EPMR_PTE_SOH_DPG", "TX": "EMM_EPMR_PTE_STX_DPG", "WA": "EMM_EPMR_PTE_SWA_DPG",
    "PADD1A": "EMM_EPMR_PTE_R1X_DPG", "PADD1B": "EMM_EPMR_PTE_R1Y_DPG",
    "PADD1C": "EMM_EPMR_PTE_R1Z_DPG", "PADD2": "EMM_EPMR_PTE_R20_DPG",
    "PADD3": "EMM_EPMR_PTE_R30_DPG", "PADD4": "EMM_EPMR_PTE_R40_DPG",
    "PADD5": "EMM_EPMR_PTE_R50_DPG",
}
STATE_PADD = {
    **{s: "PADD1A" for s in ("CT", "ME", "MA", "NH", "RI", "VT")},
    **{s: "PADD1B" for s in ("DE", "DC", "MD", "NJ", "NY", "PA")},
    **{s: "PADD1C" for s in ("FL", "GA", "NC", "SC", "VA", "WV")},
    **{
        s: "PADD2"
        for s in (
            "IL", "IN", "IA", "KS", "KY", "MI", "MN", "MO",
            "NE", "ND", "OH", "OK", "SD", "TN", "WI",
        )
    },
    **{s: "PADD3" for s in ("AL", "AR", "LA", "MS", "NM", "TX")},
    **{s: "PADD4" for s in ("CO", "ID", "MT", "UT", "WY")},
    **{s: "PADD5" for s in ("AK", "AZ", "CA", "HI", "NV", "OR", "WA")},
}
# BLS LAUS state unemployment rate, seasonally adjusted: LASST{fips}0000000000003.
STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10",
    "DC": "11", "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19",
    "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35",
    "NY": "36", "NC": "37", "ND": "38", "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44",
    "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56",
}


@dataclass
class EconomicRow:
    as_of: date
    series: str  # cpi_yoy | cpi_index | gas_price | unemployment
    state: str  # "US" or a state abbreviation
    value: float
    unit: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(), "series": self.series, "state": self.state,
            "value": self.value, "unit": self.unit, "source": self.source,
        }


@dataclass
class EconomicSnapshot:
    """What the models read. ``None`` = not available in the snapshot."""

    as_of: date | None
    cpi_yoy: float | None
    gas_price_us: float | None
    unemployment_us: float | None
    gas_price_by_state: dict[str, float] = field(default_factory=dict)
    unemployment_by_state: dict[str, float] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)

    def gas_deviation(self, state: str | None) -> float | None:
        if not state or self.gas_price_us is None:
            return None
        v = self.gas_price_by_state.get(state.upper())
        return None if v is None else round(v - self.gas_price_us, 3)

    def unemployment_deviation(self, state: str | None) -> float | None:
        if not state or self.unemployment_us is None:
            return None
        v = self.unemployment_by_state.get(state.upper())
        return None if v is None else round(v - self.unemployment_us, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "cpi_yoy": self.cpi_yoy, "gas_price_us": self.gas_price_us,
            "unemployment_us": self.unemployment_us,
            "states_with_gas": sorted(self.gas_price_by_state),
            "states_with_unemployment": sorted(self.unemployment_by_state),
            "sources": self.sources,
        }


# ── CSV snapshot ─────────────────────────────────────────────────────────────


def load_economic_csv(path: Path) -> list[EconomicRow]:
    if not path.exists():
        return []
    out: list[EconomicRow] = []
    for row in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))):
        try:
            out.append(EconomicRow(
                as_of=date.fromisoformat(row["as_of"]), series=row["series"],
                state=(row.get("state") or "US").upper(), value=float(row["value"]),
                unit=row.get("unit", ""), source=row.get("source", ""),
            ))
        except (KeyError, ValueError) as exc:
            logger.warning("skipping malformed economic row %r: %s", row, exc)
    return out


def write_economic_csv(rows: list[EconomicRow], path: Path) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=ECONOMIC_COLUMNS)
    w.writeheader()
    for r in rows:
        w.writerow(r.to_dict())
    path.write_text(buf.getvalue(), encoding="utf-8")


def snapshot_from_rows(rows: list[EconomicRow]) -> EconomicSnapshot:
    """Latest value per (series, state)."""
    latest: dict[tuple[str, str], EconomicRow] = {}
    for r in rows:
        key = (r.series, r.state)
        if key not in latest or r.as_of >= latest[key].as_of:
            latest[key] = r

    def _get(series: str, state: str = "US") -> float | None:
        r = latest.get((series, state))
        return None if r is None else r.value

    gas = {st: r.value for (s, st), r in latest.items() if s == "gas_price" and st != "US"}
    unemp = {st: r.value for (s, st), r in latest.items() if s == "unemployment" and st != "US"}
    sources = {s: r.source for (s, st), r in latest.items() if st == "US" and r.source}
    as_of = max((r.as_of for r in latest.values()), default=None)
    return EconomicSnapshot(
        as_of=as_of, cpi_yoy=_get("cpi_yoy"), gas_price_us=_get("gas_price"),
        unemployment_us=_get("unemployment"), gas_price_by_state=gas,
        unemployment_by_state=unemp, sources=sources,
    )


# ── live fetchers (best-effort) ───────────────────────────────────────────────


def fetch_cpi(timeout: float = 30.0) -> list[EconomicRow]:
    """Latest CPI-U index and year-over-year inflation from the GitHub mirror."""
    for url in CPI_MIRROR_URLS:
        try:
            resp = httpx.get(url, timeout=timeout, follow_redirects=True)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("CPI mirror %s failed: %s", url, exc)
            continue
        idx: dict[str, float] = {}
        for row in csv.DictReader(io.StringIO(resp.text)):
            if row.get("Index"):
                idx[row["Date"][:7]] = float(row["Index"])
        if not idx:
            continue
        last = max(idx)
        y, mth = last.split("-")
        prev = f"{int(y) - 1}-{mth}"
        if prev not in idx:
            continue
        yoy = (idx[last] / idx[prev] - 1.0) * 100.0
        as_of = date.fromisoformat(f"{last}-01")
        src = f"datasets/cpi-us (BLS CPI-U all items, {last} vs {prev})"
        return [
            EconomicRow(as_of, "cpi_yoy", "US", round(yoy, 2), "pct", src),
            EconomicRow(as_of, "cpi_index", "US", idx[last], "index", "datasets/cpi-us"),
        ]
    return []


def fetch_gas_prices(api_key: str, states: list[str], timeout: float = 30.0) -> list[EconomicRow]:
    """EIA weekly regular gasoline: national plus each requested state (own
    series where EIA has one, else its PADD sub-district)."""
    if not api_key:
        logger.info("EIA_API_KEY not set — skipping gas prices")
        return []
    wanted = {"US": EIA_GAS_SERIES["US"]}
    for st in states:
        st = st.upper()
        wanted[st] = EIA_GAS_SERIES.get(st) or EIA_GAS_SERIES.get(STATE_PADD.get(st, ""), "")
    out: list[EconomicRow] = []
    cache: dict[str, tuple[date, float]] = {}
    for st, series in wanted.items():
        if not series:
            continue
        if series not in cache:
            try:
                resp = httpx.get(
                    f"{EIA_BASE}/petroleum/pri/gnd/data/",
                    params={
                        "api_key": api_key, "frequency": "weekly", "data[0]": "value",
                        "facets[series][]": series, "sort[0][column]": "period",
                        "sort[0][direction]": "desc", "length": 1,
                    },
                    timeout=timeout,
                )
                resp.raise_for_status()
                rec = (resp.json().get("response", {}).get("data") or [None])[0]
                if not rec:
                    continue
                cache[series] = (date.fromisoformat(rec["period"]), float(rec["value"]))
            except Exception as exc:  # noqa: BLE001
                logger.warning("EIA fetch failed for %s: %s", series, exc)
                continue
        as_of, val = cache[series]
        note = "EIA weekly regular retail" + (
            "" if st in EIA_GAS_SERIES else f" ({STATE_PADD.get(st)})"
        )
        out.append(EconomicRow(as_of, "gas_price", st, val, "usd/gal", note))
    return out


def fetch_unemployment(
    states: list[str], api_key: str = "", timeout: float = 30.0
) -> list[EconomicRow]:
    """BLS LAUS seasonally adjusted unemployment: national (LNS14000000) and
    each requested state."""
    ids = {"US": "LNS14000000"}
    for st in states:
        fips = STATE_FIPS.get(st.upper())
        if fips:
            ids[st.upper()] = f"LASST{fips}0000000000003"
    out: list[EconomicRow] = []
    series_ids = list(ids.values())
    # v1 allows 25 series per request without a key.
    for start in range(0, len(series_ids), 25):
        payload: dict[str, Any] = {"seriesid": series_ids[start:start + 25]}
        if api_key:
            payload["registrationkey"] = api_key
        try:
            resp = httpx.post(BLS_BASE, json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("BLS fetch failed: %s", exc)
            continue
        by_id = {s["seriesID"]: s for s in data.get("Results", {}).get("series", [])}
        for st, sid in ids.items():
            s = by_id.get(sid)
            if not s or not s.get("data"):
                continue
            rec = s["data"][0]
            try:
                as_of = date(int(rec["year"]), int(rec["period"][1:]), 1)
                out.append(
                    EconomicRow(
                        as_of, "unemployment", st, float(rec["value"]), "pct", "BLS LAUS (SA)"
                    )
                )
            except (KeyError, ValueError):
                continue
    return out
