#!/usr/bin/env python3
"""Cut the pollster track record by state, by era, and by time to election.

The grades in config/pollster_grades.json are a single number per pollster over
the whole archive. This script is the reporting layer underneath them: the same
par-error metric, computed on subsets, so you can ask how a house performed in
the states that matter this cycle rather than on average everywhere.

Par error is leave-one-out within a race, so subsetting by state or by cycle is
safe — races stay whole and a pollster is still scored against the field that
polled the same contest.

    python scripts/pollster_report.py                       # summary to stdout
    python scripts/pollster_report.py --json out.json       # full payload
    python scripts/pollster_report.py --states GA,MI,TX     # custom state set

Source data is FiveThirtyEight's raw_polls.csv (CC BY 4.0), fetched by
scripts/build_pollster_grades.py. It ends with the 2022 cycle.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis.pollster_grades import (  # noqa: E402
    GradeBook,
    build_brand_records,
    normalize_poll_row,
)

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "raw_polls.csv"
# The 2024 cycle, assembled by scripts/build_2024_raw_polls.py. 538's archive
# stops at 2022, so without this every "last decade" cut ends two years early.
RAW_2024 = ROOT / "data" / "raw" / "raw_polls_2024.csv"

# The nine competitive Senate races of 2026 — the states a 2026 grade should be
# judged on, rather than the national average across all fifty.
NINE_2026 = ["GA", "MI", "NC", "ME", "NH", "OH", "TX", "IA", "AK"]

# Presidential-era battlegrounds, for the wider "does it hold up under pressure"
# cut. Close states are harder to poll and that is the point of measuring here.
PRES_BATTLEGROUNDS = NINE_2026 + ["AZ", "WI", "PA", "NV", "FL", "MN", "VA", "CO"]

ERAS: list[tuple[str, int, int]] = [
    ("1998–2024 (all)", 1998, 2024),
    ("1998–2012 (early)", 1998, 2012),
    ("2014–2024 (last decade)", 2014, 2024),
    ("2018–2024 (last half-decade)", 2018, 2024),
    ("2024 only", 2024, 2024),
]

MIN_POLLS_CELL = 5


def load_polls(path: Path) -> list:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [p for p in (normalize_poll_row(r) for r in csv.DictReader(fh)) if p]


def subset(polls, states=None, lo=None, hi=None):
    out = polls
    if states:
        s = set(states)
        out = [p for p in out if p.location in s]
    if lo is not None:
        out = [p for p in out if lo <= p.cycle <= (hi if hi is not None else 9999)]
    return out


def cell(polls, min_polls: int = MIN_POLLS_CELL) -> dict[str, dict]:
    """Fit records on a subset and return them keyed by pollster."""
    recs = build_brand_records(polls, min_weighted=float(min_polls))
    return {r.pollster: r.to_dict() for r in recs}


def time_curve(polls) -> list[dict]:
    """Mean absolute error by weeks to election — the 'time of year' effect."""
    buckets: dict[int, list[float]] = defaultdict(list)
    for p in polls:
        buckets[min(p.time_to_election // 7, 8)].append(p.abs_error)
    out = []
    for b in sorted(buckets):
        v = buckets[b]
        if len(v) < 30:
            continue
        lo, hi = b * 7, (b + 1) * 7 - 1
        out.append({
            "bucket": b,
            "label": f"{lo}–{hi} days out" if b < 8 else "56+ days out",
            "n": len(v),
            "mean_abs_error": round(sum(v) / len(v), 3),
            "median_abs_error": round(sorted(v)[len(v) // 2], 3),
        })
    return out


def per_state(polls, pollsters: list[str], states: list[str]) -> dict:
    """A pollster × state matrix of par error, lean and volume."""
    grid: dict[str, dict[str, dict]] = {}
    for st in states:
        recs = cell(subset(polls, states=[st]), min_polls=3)
        for name, rec in recs.items():
            if name in pollsters:
                grid.setdefault(name, {})[st] = {
                    "n": rec["n_polls"], "par": rec["par_error_shrunk"],
                    "lean": rec["lean_shrunk"], "abs": rec["raw_abs_error"],
                }
    return grid


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-polls", type=Path, default=RAW)
    ap.add_argument("--extra", type=Path, nargs="*", default=None,
                    help=f"additional CSVs in the same schema (default: {RAW_2024.name} if present)")
    ap.add_argument("--states", type=str, default=",".join(NINE_2026))
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    if not args.raw_polls.exists():
        sys.exit(f"missing {args.raw_polls} — run scripts/build_pollster_grades.py first")
    states = [s.strip().upper() for s in args.states.split(",") if s.strip()]
    extra = args.extra if args.extra is not None else ([RAW_2024] if RAW_2024.exists() else [])
    polls = load_polls(args.raw_polls)
    for path in extra:
        polls += load_polls(path)
        print(f"  + {path.name}")
    cycles = sorted({p.cycle for p in polls})
    print(f"{len(polls):,} scored polls, cycles {cycles[0]}–{cycles[-1]}")
    print(f"battleground set: {', '.join(states)}\n")

    gb = GradeBook()
    live_names = {n for n in gb.records}

    payload: dict = {
        "meta": {"n_polls": len(polls), "cycles": [cycles[0], cycles[-1]],
                 "states": states, "eras": [e[0] for e in ERAS],
                 "source": "FiveThirtyEight raw_polls.csv (CC BY 4.0)"},
        "national": {}, "battleground": {}, "eras": {}, "state_grid": {},
        "time_curve": {}, "coverage": {},
    }

    bg = subset(polls, states=states)
    payload["coverage"] = {
        "battleground_polls": len(bg),
        "battleground_races": len({p.race_id for p in bg}),
        "battleground_pollsters": len({p.pollster for p in bg}),
        "all_polls": len(polls),
    }
    print(f"in the battleground set: {len(bg):,} polls · "
          f"{len({p.race_id for p in bg})} races · {len({p.pollster for p in bg})} pollsters\n")

    payload["national"] = cell(polls)
    payload["battleground"] = cell(bg)
    payload["time_curve"] = {
        "all": time_curve(polls),
        "battleground": time_curve(bg),
    }

    for label, lo, hi in ERAS:
        payload["eras"][label] = {
            "all": cell(subset(polls, lo=lo, hi=hi)),
            "battleground": cell(subset(bg, lo=lo, hi=hi)),
            "n_polls": len(subset(polls, lo=lo, hi=hi)),
            "n_battleground": len(subset(bg, lo=lo, hi=hi)),
        }

    # Pollsters worth a per-state row: enough battleground history to say anything.
    counts = Counter(p.pollster for p in bg)
    focus = [n for n, c in counts.most_common() if c >= 10]
    payload["state_grid"] = per_state(bg, focus, states)
    payload["focus"] = focus

    # ── stdout summary ───────────────────────────────────────────────────────
    bgr = payload["battleground"]
    ranked = sorted(bgr.values(), key=lambda r: r["par_error_shrunk"])
    print(f"BATTLEGROUND TRACK RECORD — {len(ranked)} pollsters with {MIN_POLLS_CELL}+ polls")
    print(f"{'pollster':38}{'grade':>6}{'par':>8}{'lean':>8}{'abs err':>9}{'polls':>7}{'races':>7}{'cycles':>11}")
    for r in ranked[:args.top]:
        live = "*" if r["pollster"] in live_names else " "
        span = f"{r['cycles'][0]}-{r['last_cycle']}"
        print(f"{live}{r['pollster'][:36]:37}{r['grade']:>6}{r['par_error_shrunk']:+8.2f}"
              f"{r['lean_shrunk']:+8.2f}{r['raw_abs_error']:9.2f}{r['n_polls']:7d}{r['n_races']:7d}"
              f"{span:>11}")

    # The field's own miss, cycle by cycle. This is the number the forecast's
    # bias term is supposed to absorb, and it is the origin the pollster
    # quadrant is centred on — a firm at zero there is average, not calibrated.
    print("\nFIELD-WIDE SIGNED ERROR BY CYCLE  (+ overstated Democrats)")
    payload["field_bias"] = {"by_cycle": [], "by_era": {}, "by_office": {}}
    for c in sorted({p.cycle for p in polls}):
        sub = [p for p in polls if p.cycle == c]
        if len(sub) < 100:
            continue
        row = {"cycle": c, "n": len(sub),
               "signed": round(sum(p.signed_error for p in sub) / len(sub), 3),
               "abs": round(sum(p.abs_error for p in sub) / len(sub), 3)}
        payload["field_bias"]["by_cycle"].append(row)
        bar = int(abs(row["signed"]) * 6)
        side = ("D" if row["signed"] > 0 else "R") * bar
        print(f"  {c}  {row['signed']:+6.2f}  abs {row['abs']:5.2f}  n={row['n']:5d}  "
              + (" " * (30 - bar) + side if row["signed"] < 0 else " " * 30 + side))
    for lab, lo, hi in ERAS:
        sub = subset(polls, lo=lo, hi=hi)
        if sub:
            payload["field_bias"]["by_era"][lab] = round(
                sum(p.signed_error for p in sub) / len(sub), 3)
    print("  era means: " + " · ".join(
        f"{k} {v:+.2f}" for k, v in payload["field_bias"]["by_era"].items()))
    for lab, t in (("President", "Pres-G"), ("Senate", "Sen-G"),
                   ("Governor", "Gov-G"), ("House", "House-G")):
        sub = [p for p in polls if p.race_type == t]
        if sub:
            payload["field_bias"]["by_office"][lab] = round(
                sum(p.signed_error for p in sub) / len(sub), 3)
    print("  by office: " + " · ".join(
        f"{k} {v:+.2f}" for k, v in payload["field_bias"]["by_office"].items())
        + "   (small because the eras cancel — do not read as 'no bias')")

    print(f"\nTIME TO ELECTION — mean absolute error, all {len(polls):,} polls")
    for b in payload["time_curve"]["all"]:
        print(f"  {b['label']:16} n={b['n']:5d}  {b['mean_abs_error']:5.2f}")

    print("\nERA COMPARISON — battleground par error for the biggest houses")
    hdr = f"{'pollster':32}" + "".join(f"{lab.split(' ')[0]:>13}" for lab, _, _ in ERAS)
    print(hdr)
    for name in focus[:14]:
        cells = []
        for lab, _, _ in ERAS:
            r = payload["eras"][lab]["battleground"].get(name)
            cells.append(f"{r['par_error_shrunk']:+.2f}" if r else "-")
        print(f"{name[:30]:32}" + "".join(f"{c:>13}" for c in cells))

    if args.json:
        args.json.write_text(json.dumps(payload, indent=1))
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
