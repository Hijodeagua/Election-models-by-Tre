#!/usr/bin/env python3
"""Would economic and structural features improve the Senate forecast?

A backtest on the 98 calibration races (2018–2024) behind
config/forecast_calibration.json. The forecast currently corrects the polling
average with one constant bias (≈ −2.5, Dem overstatement) and blends it with
a fundamentals prior. This script asks whether that bias is better modelled as
a function of features the live model does not use:

  lean       the state's Dem − Rep presidential margin in the most recent
             presidential election BEFORE the race (2016 for 2018/2020 races,
             2020 for 2022/2024). Tests the "polls miss Republicans in red
             states" story.
  Δunemp     change in the state unemployment rate over the 12 months to
             September of the election year, signed by the president's party
             (+ when it should help Democrats). Tests retrospective economic
             voting beyond what polls already capture.
  rel_unemp  state unemployment minus the national rate in September, signed
             the same way. Tests whether relatively weak state economies
             punish the president's party locally.

Models are nested OLS fits of the poll error (actual − poll margin):

  M0  constant bias                      (what the forecast does today)
  M1  bias + lean
  M2  bias + lean + Δunemp
  M3  bias + lean + Δunemp + rel_unemp

Each is scored out-of-sample with leave-one-cycle-out: fit on three cycles,
predict the fourth, pool the 98 held-out residuals. RMSE compares margin
accuracy; Brier and log-loss compare win probabilities (bias-corrected
margin, calibrated total sigma, Student-t tails as in the live model).

Unemployment comes from BLS LAUS via the public v1 API (no key; 25 series
per request, 10-year window). If the API is unreachable the unemployment
models are skipped and the output says so; the fetched panel is saved to
data/historical/state_unemployment_sep.json so later runs are offline.

Outputs config/econ_features_backtest.json. Nothing here changes the live
forecast — the point is to decide whether a recalculation is warranted.
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

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CALIB = ROOT / "config" / "forecast_calibration.json"
OUT = ROOT / "config" / "econ_features_backtest.json"
RAW = ROOT / "data" / "raw"
UNEMP_PANEL = ROOT / "data" / "historical" / "state_unemployment_sep.json"

PRES_URL = (
    "https://raw.githubusercontent.com/tonmcg/US_County_Level_Election_Results_08-24/"
    "master/{year}_US_County_Level_Presidential_Results.csv"
)
BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# President's party in each calibration cycle (+1 Democrat, −1 Republican).
IN_PARTY = {2018: -1, 2020: -1, 2022: +1, 2024: +1}
# Most recent presidential election strictly before each cycle.
LEAN_YEAR = {2018: 2016, 2020: 2016, 2022: 2020, 2024: 2020}

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}
NAME_TO_ABBR = {v: k for k, v in STATE_NAMES.items()}
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


def log(msg: str) -> None:
    print(f"[econ-backtest] {msg}", file=sys.stderr)


# --------------------------------------------------------------------------
# Data
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
    except Exception as exc:  # noqa: BLE001
        if cache.exists():
            log(f"{url[:70]}… failed ({exc}); using cached {cache.name}")
            return cache.read_text()
        raise


def presidential_margins(year: int) -> dict[str, float]:
    """State Dem − Rep margin (pct points) summed from county returns.

    The 2016 file uses state_abbr; 2020/2024 use state_name.
    """
    text = fetch_text(PRES_URL.format(year=year), f"pres_county_{year}.csv")
    tally: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for row in csv.DictReader(io.StringIO(text)):
        key = row.get("state_abbr") or NAME_TO_ABBR.get(row.get("state_name", ""), "")
        if not key:
            continue
        t = tally[key]
        t[0] += float(row["votes_dem"])
        t[1] += float(row["votes_gop"])
        t[2] += float(row["total_votes"])
    return {s: round(100.0 * (d - r) / tot, 2) for s, (d, r, tot) in tally.items() if tot}


def bls_september_panel(abbrs: list[str], years: list[int]) -> dict | None:
    """September unemployment rate by state and year, plus the U.S. rate.

    Returns {"states": {abbr: {year: rate}}, "us": {year: rate}} or None
    when the API cannot be reached. Cached to data/historical/ on success.
    """
    if UNEMP_PANEL.exists():
        panel = json.loads(UNEMP_PANEL.read_text())
        have = {int(y) for y in panel.get("us", {})}
        if all(y in have and y - 1 in have for y in years):
            log(f"using cached unemployment panel {UNEMP_PANEL.relative_to(ROOT)}")
            return panel

    start, end = min(years) - 1, max(years)
    series = {f"LASST{FIPS[a]}0000000000003": a for a in abbrs if a in FIPS}
    series["LNS14000000"] = "US"
    ids = list(series)
    states: dict[str, dict[int, float]] = defaultdict(dict)
    us: dict[int, float] = {}
    for i in range(0, len(ids), 25):
        body = json.dumps(
            {"seriesid": ids[i : i + 25], "startyear": str(start), "endyear": str(end)}
        ).encode()
        req = urllib.request.Request(
            BLS_URL, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.load(resp)
        except Exception as exc:  # noqa: BLE001
            log(f"BLS request failed: {exc}")
            return None
        if payload.get("status") != "REQUEST_SUCCEEDED":
            log(f"BLS status {payload.get('status')}: {payload.get('message')}")
            return None
        for s in payload.get("Results", {}).get("series", []):
            key = series[s["seriesID"]]
            for d in s.get("data", []):
                if d.get("period") != "M09":
                    continue
                target = us if key == "US" else states[key]
                target[int(d["year"])] = float(d["value"])
    if not us:
        log("BLS returned no September data")
        return None
    panel = {
        "fetched": date.today().isoformat(),
        "source": (
            "BLS LAUS (LASST…03, seasonally adjusted) and CPS LNS14000000, September values"
        ),
        "states": {a: {str(y): v for y, v in sorted(m.items())} for a, m in states.items()},
        "us": {str(y): v for y, v in sorted(us.items())},
    }
    UNEMP_PANEL.parent.mkdir(parents=True, exist_ok=True)
    UNEMP_PANEL.write_text(json.dumps(panel, indent=1) + "\n")
    log(f"saved unemployment panel for {len(states)} states to {UNEMP_PANEL.relative_to(ROOT)}")
    return panel


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------
def ols(design: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Coefficients and classical standard errors."""
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    resid = y - design @ beta
    n, k = design.shape
    dof = max(n - k, 1)
    sigma2 = float(resid @ resid) / dof
    cov = sigma2 * np.linalg.pinv(design.T @ design)
    return beta, np.sqrt(np.diag(cov))


def t_cdf(x: np.ndarray, dof: float) -> np.ndarray:
    """Student-t CDF via Simpson integration (no SciPy in the workflow)."""
    x = np.atleast_1d(x).astype(float)
    grid = np.linspace(-60.0, float(x.max()) + 1e-9, 6001)
    c = math.gamma((dof + 1) / 2) / (math.sqrt(dof * math.pi) * math.gamma(dof / 2))
    pdf = c * (1 + grid**2 / dof) ** (-(dof + 1) / 2)
    cdf = np.concatenate([[0.0], np.cumsum((pdf[1:] + pdf[:-1]) / 2 * np.diff(grid))])
    return np.clip(np.interp(x, grid, cdf), 0.0, 1.0)


def win_prob(margin: np.ndarray, sigma: float, dof: float | None) -> np.ndarray:
    if dof:
        scale = sigma * math.sqrt((dof - 2) / dof)
        return 1 - t_cdf(-margin / scale, dof)
    return 0.5 * (1 + np.vectorize(math.erf)(margin / (sigma * math.sqrt(2))))


def loco_scores(
    design: np.ndarray,
    y: np.ndarray,
    poll: np.ndarray,
    won: np.ndarray,
    years: np.ndarray,
    sigma: float,
    dof: float | None,
) -> dict:
    """Leave-one-cycle-out: pooled held-out residuals and probability scores."""
    pred = np.zeros_like(y)
    for yr in np.unique(years):
        train, test = years != yr, years == yr
        beta, _ = ols(design[train], y[train])
        pred[test] = design[test] @ beta
    resid = y - pred
    p = np.clip(win_prob(poll + pred, sigma, dof), 1e-6, 1 - 1e-6)
    return {
        "rmse": round(float(np.sqrt(np.mean(resid**2))), 3),
        "mae": round(float(np.mean(np.abs(resid))), 3),
        "brier": round(float(np.mean((p - won) ** 2)), 4),
        "log_loss": round(float(-np.mean(won * np.log(p) + (1 - won) * np.log(1 - p))), 4),
        "win_accuracy": round(float(np.mean((p >= 0.5) == won)), 3),
        "by_cycle_rmse": {
            int(yr): round(float(np.sqrt(np.mean(resid[years == yr] ** 2))), 2)
            for yr in np.unique(years)
        },
    }


def fit_model(name: str, cols: list[str], frame: dict, meta: dict) -> dict:
    design = np.column_stack([np.ones(len(frame["error"]))] + [frame[c] for c in cols])
    beta, se = ols(design, frame["error"])
    names = ["intercept"] + cols
    in_sample = {
        n: {
            "coef": round(float(b), 3),
            "se": round(float(s), 3),
            "t": round(float(b / s), 2) if s > 0 else None,
        }
        for n, b, s in zip(names, beta, se, strict=True)
    }
    return {
        "name": name,
        "features": cols,
        "in_sample": in_sample,
        "loco": loco_scores(
            design,
            frame["error"],
            frame["poll"],
            frame["won"],
            frame["year"],
            meta["sigma"],
            meta["dof"],
        ),
    }


# --------------------------------------------------------------------------
def main() -> int:
    calib = json.loads(CALIB.read_text())
    rows = calib["rows"]
    sigma = float(calib.get("total_sigma") or 5.9)
    dof = 5  # the live forecast's tail_dof (config/senate_2026.json)

    pres = {y: presidential_margins(y) for y in sorted(set(LEAN_YEAR.values()))}
    years = sorted({r["year"] for r in rows})
    panel = bls_september_panel(sorted({r["state"] for r in rows}), years)

    frame: dict[str, list] = defaultdict(list)
    dropped = 0
    for r in rows:
        lean = pres[LEAN_YEAR[r["year"]]].get(r["state"])
        if lean is None:
            dropped += 1
            continue
        sign = IN_PARTY[r["year"]]
        frame["error"].append(r["error"])
        frame["poll"].append(r["poll_margin"])
        frame["won"].append(1.0 if r["dem_won"] else 0.0)
        frame["year"].append(r["year"])
        frame["state"].append(r["state"])
        frame["lean"].append(lean)
        if panel:
            st = panel["states"].get(r["state"], {})
            y0, y1 = str(r["year"] - 1), str(r["year"])
            if y0 in st and y1 in st and y1 in panel["us"]:
                # Rising unemployment should hurt the president's party, so the
                # Dem-signed feature is −sign × Δu (positive when it helps Dems).
                frame["d_unemp"].append(-sign * (st[y1] - st[y0]))
                frame["rel_unemp"].append(-sign * (st[y1] - panel["us"][y1]))
            else:
                frame["d_unemp"].append(np.nan)
                frame["rel_unemp"].append(np.nan)
    arr = {k: np.array(v, dtype=float if k != "state" else object) for k, v in frame.items()}
    if dropped:
        log(f"dropped {dropped} races with no presidential lean")

    meta = {"sigma": sigma, "dof": dof}
    models = [
        fit_model("M0 constant bias", [], arr, meta),
        fit_model("M1 + lean", ["lean"], arr, meta),
    ]
    unemp_status = (
        "skipped — BLS unreachable; run the econ-backtest workflow "
        "(GitHub Actions can reach api.bls.gov)"
    )
    if panel:
        ok = ~np.isnan(arr["d_unemp"])
        sub = {k: v[ok] for k, v in arr.items()}
        n_ok = int(ok.sum())
        unemp_status = (
            f"ran on {n_ok} of {len(ok)} races with a September unemployment pair"
        )
        # Refit the nested models on the same subset so the comparison is fair.
        models_u = [
            fit_model("M0 constant bias (unemp subset)", [], sub, meta),
            fit_model("M1 + lean (unemp subset)", ["lean"], sub, meta),
            fit_model("M2 + Δunemp", ["lean", "d_unemp"], sub, meta),
            fit_model("M3 + rel. unemp", ["lean", "d_unemp", "rel_unemp"], sub, meta),
        ]
        models.extend(models_u)

    base = models[0]["loco"]
    verdicts = []
    for m in models[1:]:
        if "subset" in m["name"]:
            ref = next(
                x["loco"]
                for x in models
                if x["name"].startswith("M0") and "subset" in x["name"]
            )
        else:
            ref = models[0]["loco"]
        verdicts.append(
            {
                "model": m["name"],
                "rmse_change": round(m["loco"]["rmse"] - ref["rmse"], 3),
                "brier_change": round(m["loco"]["brier"] - ref["brier"], 4),
                "log_loss_change": round(m["loco"]["log_loss"] - ref["log_loss"], 4),
            }
        )

    out = {
        "generated": date.today().isoformat(),
        "question": (
            "Does modelling the poll-error bias with structural/economic features "
            "beat a constant, out of sample?"
        ),
        "n_races": int(len(arr["error"])),
        "cycles": years,
        "sigma": sigma,
        "tail_dof": dof,
        "lean_source": {y: f"county returns {y} summed by state" for y in pres},
        "unemployment": unemp_status,
        "baseline_loco": base,
        "models": models,
        "verdicts": verdicts,
        "reading_guide": (
            "Negative rmse/brier/log_loss changes mean the richer model predicted the "
            "held-out cycle better than a constant bias. Coefficients are on the poll "
            "error (actual − poll, Dem − Rep points): lean is per point of prior "
            "presidential margin; d_unemp and rel_unemp are per percentage point of "
            "unemployment, signed so a positive coefficient means the economy moved "
            "votes toward the party the theory predicts."
        ),
    }
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    log(f"wrote {OUT.relative_to(ROOT)}")

    # Console summary
    print(f"\nEconomic-features backtest — {out['n_races']} Senate races, cycles {years}")
    print(f"Unemployment: {unemp_status}\n")
    header = f"{'model':36s} {'RMSE':>6s} {'Brier':>7s} {'LogL':>7s} {'acc':>5s}"
    print(f"{header}   in-sample coefficients")
    for m in models:
        sc = m["loco"]
        coefs = ", ".join(
            f"{k}={v['coef']:+.2f} (t={v['t']})" for k, v in m["in_sample"].items()
        )
        line = (
            f"{m['name']:36s} {sc['rmse']:6.2f} {sc['brier']:7.4f} "
            f"{sc['log_loss']:7.4f} {sc['win_accuracy']:5.2f}"
        )
        print(f"{line}   {coefs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
