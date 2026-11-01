#!/usr/bin/env python3
"""Per-state context for the /predictions map: historical lean, recent Senate
results, the model's fundamentals prior, a win-margin distribution for every
race on the board, and (best-effort) the state's unemployment rate.

Writes web/public/data/state_features.json. Runs in the refresh workflow
after export_json.py, because it reads senate.json / senate_forecast.json for
the simulation histograms and the national environment.

Sources (all public, fetched over HTTPS and cached in data/raw/):
  * Presidential margins 2020/2024 — county returns aggregated to state,
    from github.com/tonmcg/US_County_Level_Election_Results_08-24.
  * Senate results 2016–2024 — FiveThirtyEight's election-results repo (the
    same file src/data/mit_results.py uses for calibration).
  * State unemployment rate — BLS LAUS via the public v1 API (no key).
    Optional: any failure leaves the field null, never fails the run.

The distribution for a race the simulation does not cover is the model's own
fundamentals-only prior: presidential lean blended 2024/2020, shifted by the
national swing, with the calibrated total sigma as a variance-matched
Student-t — exactly what senate_simulation would use with zero polls.
"""

from __future__ import annotations

import csv
import io
import json
import math
import sys
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
WEB_DATA = ROOT / "web" / "public" / "data"
BOARD = ROOT / "web" / "content" / "predictions.json"
CYCLE_CFG = ROOT / "config" / "senate_2026.json"
OUT = WEB_DATA / "state_features.json"

PRES_URL = (
    "https://raw.githubusercontent.com/tonmcg/US_County_Level_Election_Results_08-24/"
    "master/{year}_US_County_Level_Presidential_Results.csv"
)
SENATE_URL = (
    "https://raw.githubusercontent.com/fivethirtyeight/election-results/main/"
    "election_results_senate.csv"
)
BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09",
    "DE": "10", "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18",
    "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24", "MA": "25",
    "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32",
    "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46", "TN": "47",
    "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54", "WI": "55",
    "WY": "56",
}

# Histogram bins shared with the simulation export: 2-point bins centred on
# odd integers from -29 to +29 (Dem − Rep margin).
BIN_MIDS = list(range(-29, 30, 2))


def log(msg: str) -> None:
    print(f"[state_features] {msg}", file=sys.stderr)


# --------------------------------------------------------------------------
# Downloads (cached)
# --------------------------------------------------------------------------
def fetch_text(url: str, cache_name: str, timeout: float = 60.0) -> str:
    RAW.mkdir(parents=True, exist_ok=True)
    cache = RAW / cache_name
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "election-oracle/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
        cache.write_text(text)
        return text
    except Exception as exc:  # noqa: BLE001 — any network failure falls back to cache
        if cache.exists():
            log(f"{url[:70]}… failed ({exc}); using cached {cache.name}")
            return cache.read_text()
        raise


def presidential_margins(year: int) -> dict[str, float]:
    text = fetch_text(PRES_URL.format(year=year), f"pres_county_{year}.csv")
    tally: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for row in csv.DictReader(io.StringIO(text)):
        t = tally[row["state_name"]]
        t[0] += int(float(row["votes_dem"]))
        t[1] += int(float(row["votes_gop"]))
        t[2] += int(float(row["total_votes"]))
    return {s: round(100.0 * (d - r) / tot, 1) for s, (d, r, tot) in tally.items() if tot}


# --------------------------------------------------------------------------
# Senate history
# --------------------------------------------------------------------------
def senate_history(abbr: str, rows: list[dict]) -> list[dict]:
    """Up to three most recent Senate contests in the state, most recent first.

    One entry per (cycle, special). The deciding stage wins: runoff over
    general, the final ranked-choice round over the first, and Louisiana's
    jungle primary when nobody advanced.
    """
    contests: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        if r["state_abbrev"] != abbr or not r["votes"]:
            continue
        fix = PARTY_FIXES.get((r["cycle"], r["candidate_name"]))
        if fix:
            r = {**r, "ballot_party": fix}
        contests[(r["cycle"], r["special"])].append(r)

    out = []
    for (cycle, special), rs in contests.items():
        stages = {r["stage"] for r in rs}
        stage = "runoff" if "runoff" in stages else "general" if "general" in stages else "jungle primary"
        rs = [r for r in rs if r["stage"] == stage]
        rounds = sorted({r["ranked_choice_round"] for r in rs}, key=lambda x: int(x or 0))
        rs = [r for r in rs if r["ranked_choice_round"] == rounds[-1]]
        rs = sorted(rs, key=lambda r: -float(r["votes"]))
        if not rs:
            continue
        top = rs[0]
        second = rs[1] if len(rs) > 1 else None
        top_pct = float(top["percent"])
        second_pct = float(second["percent"]) if second else 0.0
        out.append(
            {
                "cycle": int(cycle),
                "special": special == "true",
                "seat": top["office_seat_name"],
                "stage": stage,
                "winner": top["candidate_name"],
                "winner_party": party_code(top["ballot_party"]),
                "runner_up": second["candidate_name"] if second else None,
                "runner_up_party": party_code(second["ballot_party"]) if second else None,
                "margin": round(top_pct - second_pct, 1),
                "winner_pct": round(top_pct, 1),
            }
        )
    out.sort(key=lambda c: (c["cycle"], c["special"]), reverse=True)
    return out[:3]


# Ballot-party corrections where the source file disagrees with how the
# candidate actually ran.
PARTY_FIXES = {("2024", "Dan Osborn"): "IND"}


def party_code(p: str) -> str:
    return {"DEM": "D", "REP": "R"}.get(p, "I" if p in ("IND", "") else "O")


# --------------------------------------------------------------------------
# Student-t helpers (pure stdlib so the workflow needs no SciPy)
# --------------------------------------------------------------------------
def t_pdf(x: float, dof: float) -> float:
    c = math.gamma((dof + 1) / 2) / (math.sqrt(dof * math.pi) * math.gamma(dof / 2))
    return c * (1 + x * x / dof) ** (-(dof + 1) / 2)


def t_cdf(x: float, dof: float) -> float:
    """CDF by Simpson's rule from a far-left tail; plenty accurate here."""
    lo = -60.0
    if x <= lo:
        return 0.0
    n = 2000
    h = (x - lo) / n
    s = t_pdf(lo, dof) + t_pdf(x, dof)
    for i in range(1, n):
        s += (4 if i % 2 else 2) * t_pdf(lo + i * h, dof)
    return max(0.0, min(1.0, s * h / 3))


def prior_distribution(center: float, sigma: float, dof: float | None) -> tuple[list[dict], float]:
    """Histogram on BIN_MIDS and P(D) for a margin ~ center + sigma·ε."""
    if dof:
        scale = sigma * math.sqrt((dof - 2) / dof)  # variance-matched t
        cdf = lambda m: t_cdf((m - center) / scale, dof)  # noqa: E731
    else:
        cdf = lambda m: 0.5 * (1 + math.erf((m - center) / (sigma * math.sqrt(2))))  # noqa: E731
    hist = []
    for mid in BIN_MIDS:
        lo, hi = mid - 1, mid + 1
        p = cdf(hi) - cdf(lo)
        if mid == BIN_MIDS[0]:
            p = cdf(hi)
        elif mid == BIN_MIDS[-1]:
            p = 1 - cdf(lo)
        hist.append({"mid": float(mid), "pct": round(p, 5)})
    return hist, round(1 - cdf(0.0), 4)


# --------------------------------------------------------------------------
# BLS unemployment (best-effort)
# --------------------------------------------------------------------------
def bls_unemployment(abbrs: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    series = {f"LASST{FIPS[a]}0000000000003": a for a in abbrs if a in FIPS}
    ids = list(series)
    for i in range(0, len(ids), 25):  # v1 API: ≤25 series per request
        body = json.dumps({"seriesid": ids[i : i + 25]}).encode()
        req = urllib.request.Request(
            BLS_URL, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.load(resp)
        except Exception as exc:  # noqa: BLE001
            log(f"BLS request failed: {exc}")
            return out
        if payload.get("status") != "REQUEST_SUCCEEDED":
            log(f"BLS status {payload.get('status')}: {payload.get('message')}")
            return out
        for s in payload.get("Results", {}).get("series", []):
            abbr = series.get(s["seriesID"])
            data = [d for d in s.get("data", []) if d.get("period", "").startswith("M")]
            if not abbr or not data:
                continue
            latest = data[0]
            year_ago = next(
                (d for d in data if d["period"] == latest["period"] and int(d["year"]) == int(latest["year"]) - 1),
                None,
            )
            out[abbr] = {
                "rate": float(latest["value"]),
                "period": f"{latest['periodName']} {latest['year']}",
                "year_ago": float(year_ago["value"]) if year_ago else None,
            }
    return out


# --------------------------------------------------------------------------
def main() -> int:
    board = json.loads(BOARD.read_text())["races"]
    cycle_cfg = json.loads(CYCLE_CFG.read_text())
    senate = json.loads((WEB_DATA / "senate.json").read_text()) if (WEB_DATA / "senate.json").exists() else {"races": []}
    forecast = json.loads((WEB_DATA / "senate_forecast.json").read_text()) if (WEB_DATA / "senate_forecast.json").exists() else {}

    env = forecast.get("national_environment") or {}
    swing = float(env.get("national_swing") or 0.0) * float(env.get("senate_responsiveness") or 1.0)
    w_recent = float(cycle_cfg.get("fundamentals", {}).get("pres_weight_recent", 0.75))
    nat_sigma = float(forecast.get("national_sigma") or 3.0)
    race_sigma = float(forecast.get("race_sigma") or 5.0)
    total_sigma = math.hypot(nat_sigma, race_sigma)
    dof = forecast.get("tail_dof")

    pres24 = presidential_margins(2024)
    pres20 = presidential_margins(2020)
    senate_rows = list(csv.DictReader(io.StringIO(fetch_text(SENATE_URL, "senate_results_538.csv"))))
    model = {r["state"]: r for r in senate.get("races", [])}

    abbrs = [r["abbr"] for r in board]
    unemployment = bls_unemployment(abbrs)
    if unemployment:
        log(f"BLS unemployment fetched for {len(unemployment)} states")
    else:
        log("BLS unemployment unavailable — leaving null")

    states: dict[str, dict] = {}
    for race in board:
        abbr, name = race["abbr"], race["state"]
        p24, p20 = pres24.get(name), pres20.get(name)
        lean = None
        if p24 is not None and p20 is not None:
            lean = round(w_recent * p24 + (1 - w_recent) * p20, 1)
        prior = round(lean + swing, 1) if lean is not None else None

        m = model.get(name)
        fc = (m or {}).get("forecast") or {}
        if m and fc.get("margin_hist"):
            dist = {
                "source": "simulation",
                "hist": fc["margin_hist"],
                "dem_win_prob": fc.get("dem_win_prob"),
                "median": fc.get("median_margin"),
                "p10": fc.get("margin_p10"),
                "p90": fc.get("margin_p90"),
                "num_simulations": fc.get("num_simulations"),
            }
        elif prior is not None:
            hist, p_dem = prior_distribution(prior, total_sigma, dof)
            dist = {
                "source": "fundamentals_prior",
                "hist": hist,
                "dem_win_prob": p_dem,
                "median": prior,
                "p10": round(prior - 1.282 * total_sigma, 1),
                "p90": round(prior + 1.282 * total_sigma, 1),
                "num_simulations": None,
            }
        else:
            dist = None

        states[abbr] = {
            "state": name,
            "pres_2024": p24,
            "pres_2020": p20,
            "pres_lean": lean,
            "fundamentals_prior": prior,
            "senate_history": senate_history(abbr, senate_rows),
            "unemployment": unemployment.get(abbr),
            "distribution": dist,
        }

    payload = {
        "as_of": date.today().isoformat(),
        "national_swing": round(swing, 2),
        "pres_weight_recent": w_recent,
        "total_sigma": round(total_sigma, 3),
        "tail_dof": dof,
        "sources": {
            "presidential": "County returns (tonmcg/US_County_Level_Election_Results_08-24), summed by state",
            "senate": "FiveThirtyEight election-results (state-level, 2016–2024)",
            "unemployment": "BLS Local Area Unemployment Statistics, seasonally adjusted" if unemployment else None,
        },
        "states": states,
    }
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1) + "\n")
    log(f"wrote {OUT.relative_to(ROOT)} for {len(states)} states")
    return 0


if __name__ == "__main__":
    sys.exit(main())
