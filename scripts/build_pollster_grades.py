#!/usr/bin/env python3
"""Fit Policy y Peaches pollster grades and write config/pollster_grades.json.

Source data is FiveThirtyEight's ``raw_polls.csv`` — every poll they rated,
matched to the certified result. It is published under CC BY 4.0 at
https://github.com/fivethirtyeight/data/tree/master/pollster-ratings and is
the only public archive that pairs polls with outcomes at this scale.

We use their *data*; the rating is ours. Grades here come from leave-one-out
par error fitted in ``src/analysis/pollster_grades.py``, not from anyone
else's published letter.

    python scripts/build_pollster_grades.py                   # fetch + fit
    python scripts/build_pollster_grades.py --validate        # + holdout test
    python scripts/build_pollster_grades.py --raw-polls FILE   # use a local copy

The archive currently ends with the 2022 cycle. If you have 2024 rows in the
same schema, pass them with ``--extra`` and they are folded in.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis.pollster_grades import (  # noqa: E402
    build_records,
    normalize_poll_row,
    quality_from_par,
    unknown_default,
)

RAW_POLLS_URL = (
    "https://raw.githubusercontent.com/fivethirtyeight/data/master/"
    "pollster-ratings/raw_polls.csv"
)
ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "raw" / "raw_polls.csv"
OUT = ROOT / "config" / "pollster_grades.json"

# Region-scoped leans. Quality comes from the national fit — coverage is what
# matters there — but the lean correction is fitted on the states being
# forecast, which beats a national lean out of sample. See relative_lean().
REGIONS: dict[str, list[str]] = {
    "battleground_2026": ["GA", "MI", "NC", "ME", "NH", "OH", "TX", "IA", "AK"],
}


def fetch_raw_polls(dest: Path) -> Path:
    """Download the archive to ``dest`` unless it is already cached."""
    if dest.exists() and dest.stat().st_size > 1_000_000:
        print(f"  using cached {dest} ({dest.stat().st_size:,} bytes)")
        return dest
    import httpx

    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {RAW_POLLS_URL}")
    with httpx.Client(timeout=120.0, follow_redirects=True) as c:
        r = c.get(RAW_POLLS_URL)
        r.raise_for_status()
        dest.write_bytes(r.content)
    print(f"  wrote {dest} ({dest.stat().st_size:,} bytes)")
    return dest


def read_polls(paths: list[Path]) -> list:
    polls, skipped = [], 0
    for p in paths:
        with p.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                poll = normalize_poll_row(row)
                if poll is None:
                    skipped += 1
                else:
                    polls.append(poll)
    print(f"  {len(polls):,} usable D-vs-R general-election polls ({skipped:,} rows skipped)")
    return polls


def validate(polls: list) -> dict:
    """Out-of-sample test: fit on early cycles, score the held-out ones.

    For each held-out race we build three weighted averages of its polls —
    weighted by our fitted quality, by a flat weight, and by the Silver
    Bulletin table the model ships with — and compare their absolute error.
    A rating that does not beat flat weighting out of sample is not earning
    its place in the pipeline.
    """
    from src.data.pollster_ratings import _SB_RAW_ERRORS, _canonical, hybrid_quality

    cutoff = 2018
    train = [p for p in polls if p.cycle <= cutoff]
    test = [p for p in polls if p.cycle > cutoff]
    print(f"\n  holdout: fit on cycles ≤{cutoff} ({len(train):,} polls), "
          f"score {sorted({p.cycle for p in test})} ({len(test):,} polls)")

    fitted = {r.pollster: r for r in build_records(train)}
    default_q = unknown_default(list(fitted.values()))

    by_race: dict[str, list] = {}
    for p in test:
        by_race.setdefault(p.race_id, []).append(p)
    races = {k: v for k, v in by_race.items() if len(v) >= 3}
    print(f"  {len(races):,} held-out races with 3+ polls")

    def sb_quality(name: str) -> float:
        return hybrid_quality(name) if _canonical(name) in _SB_RAW_ERRORS else 1.408

    def our_lean(p) -> float:
        return fitted[p.pollster].lean_shrunk if p.pollster in fitted else 0.0

    # (weight function, per-poll house-effect correction)
    schemes = {
        "flat (no rating)": (lambda p: 1.0, lambda p: 0.0),
        "Silver Bulletin (shipped)": (lambda p: (sb_quality(p.pollster) / 3.0) ** 2, lambda p: 0.0),
        "ours — weight only": (
            lambda p: ((fitted[p.pollster].quality if p.pollster in fitted else default_q) / 3.0) ** 2,
            lambda p: 0.0,
        ),
        "ours — house-effect correction only": (lambda p: 1.0, our_lean),
        "ours — weight + house effect": (
            lambda p: ((fitted[p.pollster].quality if p.pollster in fitted else default_q) / 3.0) ** 2,
            our_lean,
        ),
    }
    out = {}
    for label, (wf, cf) in schemes.items():
        errs, signed = [], []
        for race_polls in races.values():
            w = [wf(p) for p in race_polls]
            tw = sum(w)
            if tw <= 0:
                continue
            est = sum((p.dem_margin_poll - cf(p)) * x for p, x in zip(race_polls, w)) / tw
            actual = race_polls[0].dem_margin_actual
            errs.append(abs(est - actual))
            signed.append(est - actual)
        mean_signed = sum(signed) / len(signed)
        out[label] = {
            "mean_abs_error": round(sum(errs) / len(errs), 4),
            "mean_signed_error": round(mean_signed, 4),
            # A rating cannot fix a whole-cycle miss — that is what the bias term
            # is for. Stripping the common shift isolates what the rating can do.
            "mean_abs_error_debiased": round(
                sum(abs(s - mean_signed) for s in signed) / len(signed), 4
            ),
            "n_races": len(errs),
        }
    # Where the lean is fitted matters more than how it is weighted. Score the
    # same held-out races restricted to the region, comparing a national lean
    # against one fitted on the region's own history.
    region_states = set(REGIONS["battleground_2026"])
    bg_fit = {r.pollster: r for r in build_records(
        [p for p in train if p.location in region_states], min_weighted=5.0)}
    pool_lean = (sum(r.lean_shrunk * r.n_weighted for r in fitted.values())
                 / sum(r.n_weighted for r in fitted.values()))
    bg_races = [v for v in races.values() if all(p.location in region_states for p in v)]
    if bg_races:
        def _score(lean_fn):
            errs = []
            for rp in bg_races:
                w = [((fitted[p.pollster].quality if p.pollster in fitted else default_q) / 3.0) ** 2
                     for p in rp]
                corr = [p.dem_margin_poll - lean_fn(p) for p in rp]
                errs.append(abs(sum(c * x for c, x in zip(corr, w)) / sum(w) - rp[0].dem_margin_actual))
            return round(sum(errs) / len(errs), 4)
        out["_region_lean"] = {
            "n_races": len(bg_races),
            "no correction": _score(lambda p: 0.0),
            "national lean": _score(
                lambda p: (fitted[p.pollster].lean_shrunk - pool_lean) if p.pollster in fitted else 0.0),
            "region-fitted lean": _score(
                lambda p: ((bg_fit.get(p.pollster) or fitted.get(p.pollster)).lean_shrunk - pool_lean)
                if (p.pollster in bg_fit or p.pollster in fitted) else 0.0),
        }

    # Coverage matters as much as accuracy: a rating that only knows 28 houses
    # cannot weight most of the field.
    names = {p.pollster for p in test}
    out["_coverage"] = {
        "test_pollsters": len(names),
        "known_to_ours": sum(1 for n in names if n in fitted),
        "known_to_silver_bulletin": sum(1 for n in names if _canonical(n) in _SB_RAW_ERRORS),
    }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-polls", type=Path, default=None, help="local raw_polls.csv")
    ap.add_argument("--extra", type=Path, nargs="*", default=[], help="additional CSVs in the same schema")
    ap.add_argument("--validate", action="store_true", help="run the holdout comparison")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    print("Building Policy y Peaches pollster grades")
    src = args.raw_polls or fetch_raw_polls(CACHE)
    polls = read_polls([src, *args.extra])
    records = build_records(polls)
    default_q = unknown_default(records)
    cycles = sorted({p.cycle for p in polls})
    print(f"  graded {len(records)} pollsters over cycles {cycles[0]}–{cycles[-1]}")

    payload = {
        "_meta": {
            "description": "Policy y Peaches pollster grades. Leave-one-out par error "
                           "on general-election polls matched to certified results, "
                           "recency-weighted and shrunk toward the pool. Fitted by "
                           "scripts/build_pollster_grades.py — do not hand-edit.",
            "method": "par_error = mean(|poll error| - |field error on the same race, "
                      "excluding this poll|), time-to-election adjusted, half-life 4 cycles, "
                      "empirical-Bayes shrinkage k=20 polls",
            "source": "FiveThirtyEight raw_polls.csv (CC BY 4.0)",
            "cycles": cycles,
            "n_polls": len(polls),
            "n_pollsters": len(records),
            "unknown_default": default_q,
            "scale": "quality 0-3, 1.5 = par; grade = percentile of the graded pool",
        },
        "ratings": {r.pollster: r.quality for r in records},
        "grades": [r.to_dict() for r in records],
        "regions": {},
    }
    for region, states in REGIONS.items():
        sub = [p for p in polls if p.location in set(states)]
        recs = build_records(sub, min_weighted=5.0)
        payload["regions"][region] = {
            "states": states,
            "n_polls": len(sub),
            "n_races": len({p.race_id for p in sub}),
            "leans": {r.pollster: r.lean_shrunk for r in recs},
            "records": [r.to_dict() for r in recs],
        }
        print(f"  region {region}: {len(recs)} firms fitted on {len(sub):,} polls "
              f"across {len({p.race_id for p in sub})} races")
    if args.validate:
        payload["validation"] = validate(polls)
        print("\n  holdout results:")
        for k, v in payload["validation"].items():
            print(f"    {k:28} {v}")

    args.out.write_text(json.dumps(payload, indent=2))
    print(f"\n  wrote {args.out}")

    print(f"\n  {'pollster':34}{'grade':>6}{'par':>8}{'lean':>8}{'polls':>7}{'cycles':>9}")
    for r in records[:20]:
        print(f"  {r.pollster[:33]:34}{r.grade:>6}{r.par_error_shrunk:+8.2f}"
              f"{r.lean_shrunk:+8.2f}{r.n_polls:7d}{f'{r.cycles[0]}-{r.last_cycle}':>9}")


if __name__ == "__main__":
    main()
