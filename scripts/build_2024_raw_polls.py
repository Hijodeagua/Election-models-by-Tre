#!/usr/bin/env python3
"""Build a 2024-cycle poll file in FiveThirtyEight's ``raw_polls.csv`` schema.

538's rated-poll archive stops at the 2022 cycle — they shut down in March 2025
without ever publishing a 2024 update, so there is no off-the-shelf file that
pairs 2024 polls with certified results. This script assembles one.

Sources, all public and all reachable as plain files:

``--polls``    538's own ``president_polls.csv``, poll-level with candidate
               percentages. The last public snapshot we can reach was taken on
               2024-10-17, so it covers the cycle up to and including polls that
               finished fielding on Oct. 16. CC BY 4.0.
``--rcp-dir``  RealClearPolitics poll-level data for the national race and the
               seven core battlegrounds, collected through Nov. 4. Used *only*
               for polls that finished after the 538 snapshot, so the two
               sources never cover the same poll. This is what keeps the final
               three weeks — where most of 2024's polling error actually lived —
               from being a blind spot.
``--results``  538's ``election-results`` repository: certified returns for
               president, Senate and governor, 1998 to present.

Every row carries a ``source`` column so the 2024 grade can be recomputed on
the 538 rows alone. It is not a throwaway check — the RCP set is a curated
subset of the field and leans differently from it, so the two-source and
one-source fits are reported side by side rather than blended silently.

    python scripts/build_2024_raw_polls.py                  # fetch + build
    python scripts/build_2024_raw_polls.py --no-rcp         # 538 rows only

Output is ``data/raw/raw_polls_2024.csv``, which drops straight into
``scripts/build_pollster_grades.py --extra``.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RAW_DIR = ROOT / "data" / "raw" / "2024"
OUT = ROOT / "data" / "raw" / "raw_polls_2024.csv"

ELECTION_DAY = date(2024, 11, 5)

# Poll-level 538 presidential file, mirrored in a public replication repo. The
# 538 endpoint it came from (projects.fivethirtyeight.com) went dark with the
# site; this snapshot is the last one published under CC BY 4.0.
POLLS_URL = (
    "https://raw.githubusercontent.com/redpinecube/election-forecasting-2024/"
    "main/data/raw_data/president_polls.csv"
)
RESULTS_URL = (
    "https://raw.githubusercontent.com/fivethirtyeight/election-results/"
    "main/election_results_presidential.csv"
)
RCP_BASE = "https://raw.githubusercontent.com/stiles/polls/main/data/polls"
RCP_FILES = {
    "general": "US",
    "arizona": "AZ",
    "georgia": "GA",
    "michigan": "MI",
    "nevada": "NV",
    "north_carolina": "NC",
    "pennsylvania": "PA",
    "wisconsin": "WI",
}

STATE_ABBREV = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN",
    "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
    "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH",
    "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH",
    "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
    "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
    # Congressional districts keep 538's archive coding, not the polls-page one.
    "Maine CD-1": "M1", "Maine CD-2": "M2",
    "Nebraska CD-1": "N1", "Nebraska CD-2": "N2", "Nebraska CD-3": "N3",
}

# Which question to keep when a poll reports several populations. 538's own
# archive prefers likely voters; anything else would grade a firm on the
# sample it did not headline.
POPULATION_RANK = {"lv": 0, "v": 1, "rv": 2, "a": 3}

# RealClearPolitics mastheads mapped onto the name 538 rates the firm under, so
# a firm's October polls and its November polls land in the same record. Only
# firms we can identify with confidence are mapped; anything else keeps its RCP
# name and simply fails to merge, which is the safe direction to fail.
RCP_TO_RATING_NAME = {
    "Atlas Intel": "AtlasIntel",
    "TIPP": "TIPP Insights",
    "AmGreatness/TIPP": "TIPP Insights",
    "I&I/TIPP": "TIPP Insights",
    "Rasmussen Reports": "Rasmussen Reports",
    "Bloomberg": "Morning Consult",
    "Morning Consult": "Morning Consult",
    "Emerson": "Emerson College",
    "The Hill/Emerson": "Emerson College",
    "InsiderAdvantage": "InsiderAdvantage",
    "Trafalgar Group (R)": "Trafalgar Group",
    "Marist": "Marist College",
    "NPR/PBS/Marist": "Marist College",
    "ABC News/Ipsos": "Ipsos",
    "Reuters/Ipsos": "Ipsos",
    "Ipsos": "Ipsos",
    "Forbes/HarrisX": "Harris Insights & Analytics",
    "HarrisX": "Harris Insights & Analytics",
    "Harvard-Harris": "Harris Insights & Analytics",
    "CNN": "CNN",
    "UMass Lowell": "University of Massachusetts Lowell Center for Public Opinion",
    "Echelon Insights": "Echelon Insights",
    "Economist/YouGov": "YouGov",
    "Yahoo News": "YouGov",
    "CBS News": "YouGov",
    "Mitchell Research": "Mitchell Research & Communications",
    "MNS/Mitchell Research": "Mitchell Research & Communications",
    "MIRS/MI News Source": "Mitchell Research & Communications",
    "Susquehanna": "Susquehanna Polling & Research Inc.",
    "Federalist/Susquehanna": "Susquehanna Polling & Research Inc.",
    "Quinnipiac": "Quinnipiac University",
    "High Point/SurveyUSA": "High Point University Survey Research Center",
    "WRAL-TV/SurveyUSA": "SurveyUSA",
    "SurveyUSA": "SurveyUSA",
    "Elon University": "Elon University",
    "Franklin & Marshall": "Franklin & Marshall College Center for Opinion Research",
    "NY Times/Siena": "The New York Times/Siena College",
    "Marquette": "Marquette University Law School",
    "FOX News": "Beacon Research/Shaw & Co. Research",
    "NBC News": "Hart Research Associates/Public Opinion Strategies",
    "ABC News/Wash Post": "ABC News/The Washington Post",
    "USA Today/Suffolk": "Suffolk University",
    "PPP (D)": "Public Policy Polling",
    "Data for Progress (D)": "Data for Progress",
    "Cygnal (R)": "Cygnal",
    "Carolina Journal/Cygnal": "Cygnal",
    "Remington Research (R)": "Remington Research Group",
    "East Carolina U.": "East Carolina University Center for Survey Research",
    "Noble Predictive Insights": "Noble Predictive Insights",
    "Pew Research": "Pew Research Center",
    "Atlanta Journal-Constitution": "University of Georgia School of Public and International Affairs",
    "GSG/NSOR": "Global Strategy Group/North Star Opinion Research",
    "AmGreatness/NSOR": "North Star Opinion Research",
}

FIELDS = [
    "poll_id", "question_id", "race_id", "cycle", "location", "type_simple",
    "race", "pollster", "pollster_rating_id", "methodology", "partisan",
    "polldate", "electiondate", "time_to_election", "samplesize",
    "cand1_name", "cand1_party", "cand1_pct", "cand1_actual",
    "cand2_name", "cand2_party", "cand2_pct", "cand2_actual",
    "margin_poll", "margin_actual", "source",
]


def fetch(url: str, dest: Path, min_bytes: int = 2_000) -> Path:
    if dest.exists() and dest.stat().st_size >= min_bytes:
        return dest
    import httpx

    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {url}")
    with httpx.Client(timeout=180.0, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        dest.write_bytes(r.content)
    return dest


def certified_margins(path: Path) -> dict[str, tuple[float, float]]:
    """Democratic and Republican share of the total vote, by location.

    Percentages are of *all* votes cast, matching 538's ``cand1_actual``, so a
    poll that leaves out third parties is not credited with their share.
    """
    rows = [
        r for r in csv.DictReader(path.open(encoding="utf-8-sig"))
        if r["cycle"] == "2024" and r["stage"] == "general"
        and r["office_name"] == "U.S. President"
    ]
    out: dict[str, tuple[float, float]] = {}
    dem_votes = rep_votes = all_votes = 0.0
    for r in rows:
        loc = r["state_abbrev"]
        if not loc:
            continue
        party, pct, votes = r["ballot_party"], r["percent"], r["votes"]
        try:
            pct_f = float(pct)
        except ValueError:
            pct_f = None
        if party in {"DEM", "REP"} and pct_f is not None:
            d, rp = out.get(loc, (None, None))
            out[loc] = (pct_f, rp) if party == "DEM" else (d, pct_f)
        # The results file has no national row, so build one from the states.
        # Districts and Puerto Rico would double-count or add non-electors.
        if loc in {"M1", "M2", "N1", "N2", "N3", "PR"}:
            continue
        try:
            v = float(votes)
        except (TypeError, ValueError):
            continue
        all_votes += v
        if party == "DEM":
            dem_votes += v
        elif party == "REP":
            rep_votes += v
    out["US"] = (100 * dem_votes / all_votes, 100 * rep_votes / all_votes)
    return {k: v for k, v in out.items() if v[0] is not None and v[1] is not None}


def _parse_date(s: str) -> date:
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable date {s!r}")


def _median_date(start: str, end: str) -> date:
    """538 dates a poll by the midpoint of its field period."""
    s, e = _parse_date(start), _parse_date(end)
    return s + (e - s) / 2


def read_fte(
    path: Path, actual: dict[str, tuple[float, float]]
) -> tuple[list[dict], date]:
    """Harris-versus-Trump general questions, plus the snapshot's last field date.

    One question per poll and state. Hypothetical matchups are dropped, which
    also removes every Biden-era Harris question: grading a July hypothetical
    against November's result would score a firm on a race that did not exist
    when it fielded.

    The returned date is the latest *end* of a field period in the file, which
    is where the RCP supplement has to start so no poll is counted twice.
    """
    by_question: dict[str, list[dict]] = {}
    for r in csv.DictReader(path.open(encoding="utf-8-sig")):
        by_question.setdefault(r["question_id"], []).append(r)

    best: dict[tuple[str, str], tuple[int, dict]] = {}
    skipped_no_result: set[str] = set()
    last_field_end = date(2024, 1, 1)
    for rows in by_question.values():
        head = rows[0]
        if head["stage"] != "general" or head["cycle"] != "2024":
            continue
        if head["hypothetical"].strip().lower() == "true":
            continue
        dem = [r for r in rows if r["party"] == "DEM" and r["candidate_name"] == "Kamala Harris"]
        rep = [r for r in rows if r["party"] == "REP" and r["candidate_name"] == "Donald Trump"]
        if len(dem) != 1 or len(rep) != 1:
            continue
        loc = "US" if not head["state"].strip() else STATE_ABBREV.get(head["state"].strip())
        if loc is None:
            continue
        if loc not in actual:
            skipped_no_result.add(loc)
            continue
        try:
            dem_pct, rep_pct = float(dem[0]["pct"]), float(rep[0]["pct"])
        except ValueError:
            continue
        last_field_end = max(last_field_end, _parse_date(head["end_date"]))
        rank = POPULATION_RANK.get(head["population"], 9)
        key = (head["poll_id"], loc)
        if key in best and best[key][0] <= rank:
            continue
        polldate = _median_date(head["start_date"], head["end_date"])
        d_act, r_act = actual[loc]
        best[key] = (rank, {
            "poll_id": head["poll_id"],
            "question_id": head["question_id"],
            "race_id": f"P24-{loc}",
            "cycle": "2024",
            "location": loc,
            "type_simple": "Pres-G",
            "race": f"2024_Pres-G_{loc}",
            "pollster": head["pollster_rating_name"] or head["pollster"],
            "pollster_rating_id": head["pollster_rating_id"],
            "methodology": head["methodology"],
            "partisan": head["partisan"],
            "polldate": polldate.isoformat(),
            "electiondate": ELECTION_DAY.isoformat(),
            "time_to_election": (ELECTION_DAY - polldate).days,
            "samplesize": head["sample_size"],
            "cand1_name": "Kamala Harris", "cand1_party": "DEM",
            "cand1_pct": f"{dem_pct:.2f}", "cand1_actual": f"{d_act:.4f}",
            "cand2_name": "Donald Trump", "cand2_party": "REP",
            "cand2_pct": f"{rep_pct:.2f}", "cand2_actual": f"{r_act:.4f}",
            "margin_poll": f"{dem_pct - rep_pct:.2f}",
            "margin_actual": f"{d_act - r_act:.4f}",
            "source": "538",
        })
    if skipped_no_result:
        print(f"  no certified result for {sorted(skipped_no_result)} — dropped")
    return [v[1] for v in best.values()], last_field_end


def read_rcp(
    dirpath: Path, actual: dict[str, tuple[float, float]], after: date
) -> list[dict]:
    """RCP polls that finished after the 538 snapshot, so nothing double-counts."""
    out: list[dict] = []
    unmapped: dict[str, int] = {}
    for stem, loc in RCP_FILES.items():
        path = dirpath / f"{stem}.csv"
        if not path.exists():
            continue
        for r in csv.DictReader(path.open(encoding="utf-8-sig")):
            # RCP files carry their own running average as pseudo-rows.
            if r["type"] == "poll_rcp_avg":
                continue
            try:
                end = datetime.strptime(r["polling_end_date"], "%Y-%m-%d").date()
            except ValueError:
                continue
            if end <= after or end > ELECTION_DAY:
                continue
            try:
                dem_pct, rep_pct = float(r["harris_value"]), float(r["trump_value"])
            except ValueError:
                continue
            name = (r["pollster"] or "").replace("&amp;", "&").strip()
            # RCP marks its own asterisked footnotes and party tags inline.
            name = name.rstrip("*").strip()
            partisan = ""
            for tag, code in (("(R)", "R"), ("(D)", "D")):
                if name.endswith(tag):
                    partisan = code
            mapped = RCP_TO_RATING_NAME.get(name)
            if mapped is None:
                mapped = RCP_TO_RATING_NAME.get(name.removesuffix("(R)").removesuffix("(D)").strip())
            if mapped is None:
                unmapped[name] = unmapped.get(name, 0) + 1
                mapped = name
            polldate = _median_date(r["polling_start_date"], r["polling_end_date"])
            d_act, r_act = actual[loc]
            sample = "".join(ch for ch in (r["sampleSize"] or "") if ch.isdigit())
            out.append({
                "poll_id": f"rcp-{r['id']}",
                "question_id": f"rcp-{r['id']}",
                "race_id": f"P24-{loc}",
                "cycle": "2024",
                "location": loc,
                "type_simple": "Pres-G",
                "race": f"2024_Pres-G_{loc}",
                "pollster": mapped,
                "pollster_rating_id": "",
                "methodology": "",
                "partisan": partisan,
                "polldate": polldate.isoformat(),
                "electiondate": ELECTION_DAY.isoformat(),
                "time_to_election": (ELECTION_DAY - polldate).days,
                "samplesize": sample,
                "cand1_name": "Kamala Harris", "cand1_party": "DEM",
                "cand1_pct": f"{dem_pct:.2f}", "cand1_actual": f"{d_act:.4f}",
                "cand2_name": "Donald Trump", "cand2_party": "REP",
                "cand2_pct": f"{rep_pct:.2f}", "cand2_actual": f"{r_act:.4f}",
                "margin_poll": f"{dem_pct - rep_pct:.2f}",
                "margin_actual": f"{d_act - r_act:.4f}",
                "source": "rcp",
            })
    if unmapped:
        print("  RCP mastheads with no 538 equivalent (kept under their own name): "
              + ", ".join(f"{k} ({v})" for k, v in sorted(unmapped.items())))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--polls", type=Path, default=RAW_DIR / "president_polls_2024.csv")
    ap.add_argument("--results", type=Path, default=RAW_DIR / "election_results_presidential.csv")
    ap.add_argument("--rcp-dir", type=Path, default=RAW_DIR / "rcp")
    ap.add_argument("--no-rcp", action="store_true", help="538 rows only")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    print("Building the 2024 poll file")
    fetch(POLLS_URL, args.polls, min_bytes=1_000_000)
    fetch(RESULTS_URL, args.results, min_bytes=100_000)
    actual = certified_margins(args.results)
    d, r = actual["US"]
    print(f"  certified results for {len(actual)} locations "
          f"(national: D {d:.2f} R {r:.2f}, margin {d - r:+.2f})")

    rows, last_end = read_fte(args.polls, actual)
    print(f"  538 snapshot: {len(rows):,} Harris-Trump questions across "
          f"{len({x['location'] for x in rows})} locations, "
          f"{len({x['pollster'] for x in rows})} firms, "
          f"last field date {last_end} ({(ELECTION_DAY - last_end).days} days out)")

    if not args.no_rcp:
        for stem in RCP_FILES:
            fetch(f"{RCP_BASE}/{stem}.csv", args.rcp_dir / f"{stem}.csv")
        extra = read_rcp(args.rcp_dir, actual, after=last_end)
        print(f"  RCP fills the gap after {last_end}: {len(extra)} polls, "
              f"{len({x['pollster'] for x in extra})} firms")
        rows += extra

    rows.sort(key=lambda x: (x["location"], x["polldate"], x["pollster"]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"\n  wrote {args.out} ({len(rows):,} rows, {args.out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
