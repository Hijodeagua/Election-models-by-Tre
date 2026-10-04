"""Build the district-level baseline for the House forecast.

Reads FiveThirtyEight's archived House results (``election_results_house.csv``
in the fivethirtyeight/election-results GitHub repo, 1976–2024) and writes
``data/fallback/house_districts_2024.csv``: one row per congressional district
with the 2024 two-party Dem−Rep margin, the winner's party, and whether the
margin had to be imputed because the seat was uncontested.

Why 2024 district margins: the House forecast is a uniform-swing-plus-noise
model. Each district starts from its last result, the national environment
moves every district by the same amount, and district-level noise (calibrated
below) is layered on top. 2024 is the most recent cycle on broadly the same map
that the 2026 election is run on (mid-decade redraws are handled separately in
config/house_2026.json).

Handling:
  * Fusion ballot lines (NY's Working Families / Conservative) are summed per
    candidate; a candidate counts as Democratic/Republican if any of their lines
    is DEM/REP.
  * Ranked-choice races (AK, ME-2) use the final round.
  * Louisiana publishes no separate "general" stage in 2024 (all-party primary
    on election day), so its jungle-primary rows are used.
  * Uncontested seats (no D or no R on the ballot) take the district's 2022
    margin if that race was contested, else a ±UNCONTESTED_CAP placeholder.
    These are all safe seats; the placeholder only has to keep them from
    flipping under simulated noise.
  * Territories (PR, GU, VI, DC delegates) are dropped.

Also prints the empirical district-level swing dispersion (SD of each
district's margin change net of the national mean) between consecutive cycles
on the same map, which grounds ``district_sigma`` in the config.

Usage:
    python scripts/build_house_districts.py                 # downloads
    python scripts/build_house_districts.py --source path/to/election_results_house.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from collections import defaultdict
from pathlib import Path

import httpx
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_PATH = PROJECT_ROOT / "data" / "fallback" / "house_districts_2024.csv"
SOURCE_URLS = [
    "https://raw.githubusercontent.com/fivethirtyeight/election-results/main/election_results_house.csv",
    "https://raw.githubusercontent.com/fivethirtyeight/election-results/master/election_results_house.csv",
]
NON_STATES = {"PR", "GU", "VI", "DC", "AS", "MP"}
UNCONTESTED_CAP = 35.0
BASE_CYCLE = 2024
IMPUTE_CYCLE = 2022
# States whose districts changed between the two cycles compared for the
# swing-dispersion statistic (new maps make the comparison meaningless there).
REDRAWN_BETWEEN = {
    (2022, 2024): {"NC", "AL", "LA", "NY", "GA"},
    (2018, 2020): {"NC"},
    (2016, 2018): {"PA"},
}

OUTPUT_COLUMNS = [
    "state", "district", "dem_pct", "rep_pct", "margin", "winner_party",
    "contested", "imputed_from", "source_cycle", "margin_2022",
]
# States whose districts were redrawn between 2022 and 2024, so the 2022
# result is not the same seat and is left blank.
REDRAWN_2024 = {"NC", "AL", "LA", "NY", "GA"}


def _fetch(source: str | None) -> str:
    if source:
        return Path(source).read_text(encoding="utf-8")
    last_exc: Exception | None = None
    for url in SOURCE_URLS:
        try:
            resp = httpx.get(url, timeout=120.0, follow_redirects=True)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:  # noqa: BLE001 - try the next mirror
            last_exc = exc
    raise SystemExit(f"could not download House results: {last_exc}")


def district_results(rows: list[dict], cycle: int) -> dict[tuple[str, str], dict]:
    """Per-district {dem_pct, rep_pct, winner_party, contested} for one cycle."""
    by_district: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        if int(r["cycle"]) != cycle or r["special"] == "true":
            continue
        if r["state_abbrev"] in NON_STATES:
            continue
        by_district[(r["state_abbrev"], r["office_seat_name"])].append(r)

    out: dict[tuple[str, str], dict] = {}
    for key, recs in by_district.items():
        stages = {r["stage"] for r in recs}
        if "general" in stages:
            recs = [r for r in recs if r["stage"] == "general"]
        elif "jungle primary" in stages:  # Louisiana
            recs = [r for r in recs if r["stage"] == "jungle primary"]
        else:
            continue
        rounds = [int(r["ranked_choice_round"]) for r in recs if r["ranked_choice_round"]]
        if rounds:
            final = max(rounds)
            recs = [
                r for r in recs
                if r["ranked_choice_round"] and int(r["ranked_choice_round"]) == final
            ]
        cands: dict[str, dict] = defaultdict(lambda: {"pct": 0.0, "parties": set(), "win": False})
        for r in recs:
            c = cands[r["candidate_name"]]
            c["pct"] += float(r["percent"] or 0.0)
            c["parties"].add(r["ballot_party"])
            c["win"] |= r["winner"] == "true"
        dem = sum(c["pct"] for c in cands.values() if "DEM" in c["parties"])
        rep = sum(c["pct"] for c in cands.values() if "REP" in c["parties"])
        winners = [c for c in cands.values() if c["win"]]
        winner_party = None
        if winners:
            parties = winners[0]["parties"]
            winner_party = "D" if "DEM" in parties else "R" if "REP" in parties else "I"
        contested = dem > 0.0 and rep > 0.0
        out[key] = {
            "dem_pct": round(dem, 2),
            "rep_pct": round(rep, 2),
            "winner_party": winner_party,
            "contested": contested,
        }
    return out


def two_party_margin(dem_pct: float, rep_pct: float) -> float:
    total = dem_pct + rep_pct
    return 0.0 if total <= 0 else (dem_pct - rep_pct) / total * 100.0


def build(rows: list[dict]) -> list[dict]:
    base = district_results(rows, BASE_CYCLE)
    prior = district_results(rows, IMPUTE_CYCLE)
    out: list[dict] = []
    for key in sorted(base, key=lambda k: (k[0], _district_num(k[1]))):
        rec = base[key]
        imputed_from = ""
        if rec["contested"]:
            margin = two_party_margin(rec["dem_pct"], rec["rep_pct"])
        else:
            prev = prior.get(key)
            if prev and prev["contested"]:
                margin = two_party_margin(prev["dem_pct"], prev["rep_pct"])
                imputed_from = str(IMPUTE_CYCLE)
            else:
                sign = 1.0 if rec["winner_party"] == "D" else -1.0
                margin = sign * UNCONTESTED_CAP
                imputed_from = "cap"
            # Keep the imputed margin on the winner's side of zero.
            if rec["winner_party"] == "D":
                margin = max(margin, UNCONTESTED_CAP / 2)
            elif rec["winner_party"] == "R":
                margin = min(margin, -UNCONTESTED_CAP / 2)
        prev = prior.get(key)
        margin_2022 = ""
        if prev and prev["contested"] and key[0] not in REDRAWN_2024:
            margin_2022 = round(two_party_margin(prev["dem_pct"], prev["rep_pct"]), 2)
        out.append(
            {
                "state": key[0],
                "district": key[1],
                "dem_pct": rec["dem_pct"],
                "rep_pct": rec["rep_pct"],
                "margin": round(margin, 2),
                "winner_party": rec["winner_party"] or "",
                "contested": "true" if rec["contested"] else "false",
                "imputed_from": imputed_from,
                "source_cycle": BASE_CYCLE,
                "margin_2022": margin_2022,
            }
        )
    return out


def _district_num(label: str) -> int:
    digits = "".join(ch for ch in label if ch.isdigit())
    return int(digits) if digits else 0


def swing_dispersion(rows: list[dict], a: int, b: int) -> tuple[int, float, float]:
    """(n, mean swing, SD of district swing net of the mean) between cycles a→b
    for districts contested in both and not in a redrawn state."""
    ra, rb = district_results(rows, a), district_results(rows, b)
    skip = REDRAWN_BETWEEN.get((a, b), set())
    diffs = []
    for key, va in ra.items():
        vb = rb.get(key)
        if not vb or key[0] in skip or not (va["contested"] and vb["contested"]):
            continue
        if min(va["dem_pct"], va["rep_pct"], vb["dem_pct"], vb["rep_pct"]) < 5.0:
            continue
        diffs.append(
            two_party_margin(vb["dem_pct"], vb["rep_pct"])
            - two_party_margin(va["dem_pct"], va["rep_pct"])
        )
    arr = np.array(diffs)
    return len(arr), float(arr.mean()), float(arr.std(ddof=1))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the House district baseline CSV.")
    parser.add_argument(
        "--source", help="Local copy of election_results_house.csv (else download)."
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    text = _fetch(args.source)
    rows = list(csv.DictReader(io.StringIO(text)))
    districts = build(rows)

    n_d = sum(1 for d in districts if d["winner_party"] == "D")
    n_r = sum(1 for d in districts if d["winner_party"] == "R")
    n_imp = sum(1 for d in districts if d["imputed_from"])
    print(
        f"{len(districts)} districts for {BASE_CYCLE}: D {n_d} / R {n_r}; "
        f"{n_imp} margins imputed"
    )
    if len(districts) != 435:
        print(f"  WARNING: expected 435 districts, got {len(districts)}")

    for a, b in ((2022, 2024), (2018, 2020), (2016, 2018)):
        n, mean, sd = swing_dispersion(rows, a, b)
        print(f"  district swing {a}->{b}: n={n} mean={mean:+.2f} SD(net of mean)={sd:.2f}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(districts)
    shown = (
        args.output.relative_to(PROJECT_ROOT)
        if args.output.is_relative_to(PROJECT_ROOT)
        else args.output
    )
    print(f"Wrote {shown}")


if __name__ == "__main__":
    main()
