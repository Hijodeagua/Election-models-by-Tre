#!/usr/bin/env python3
"""One table per pollster: career score, recency-weighted score, 2024 score.

Three fits of the same par-error metric, printed side by side:

``career``    every cycle counted equally. This is the number the forecast uses
              — decaying old cycles lost on both holdout splits, because an old
              poll is bad evidence about today's race and good evidence about a
              house's methodology.
``recent``    the same fit with a four-cycle half-life, so the last decade
              carries most of the weight. It is here because it is the thing
              people mean by "how are they doing lately", not because it
              predicts better.
``2024``      the 2024 cycle alone. Small samples, so it is shrunk hard toward
              the field and should be read as a single cycle's result, not a
              rating.

All three are on the same 0–100 scale, where 50 is exactly the field's average
on the same races and every 15 points is one percentage point of margin.

    python scripts/pollster_scorecard.py                    # top 40, text
    python scripts/pollster_scorecard.py --format md --all  # markdown, everyone
    python scripts/pollster_scorecard.py --format csv --out scorecard.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.analysis.pollster_grades as PG  # noqa: E402
from src.analysis.pollster_grades import (  # noqa: E402
    build_brand_records,
    normalize_poll_row,
    score_from_par,
)

RAW = ROOT / "data" / "raw" / "raw_polls.csv"
RAW_2024 = ROOT / "data" / "raw" / "raw_polls_2024.csv"

# The nine competitive 2026 Senate races. A house's record in these states is
# the part of its history that bears on the forecast.
BATTLEGROUND_2026 = ["GA", "MI", "NC", "ME", "NH", "OH", "TX", "IA", "AK"]

RECENT_HALF_LIFE = 4.0   # cycles
MIN_2024_POLLS = 5.0     # below this a single cycle says nothing


def load(paths: list[Path]) -> list:
    polls = []
    for p in paths:
        with p.open(newline="", encoding="utf-8-sig") as fh:
            polls += [q for q in (normalize_poll_row(r) for r in csv.DictReader(fh)) if q]
    return polls


def fit(polls, *, half_life=None, min_weighted=PG.MIN_POLLS_TO_GRADE) -> dict:
    """Fit brand records under a temporary recency setting."""
    saved = PG.RECENCY_HALF_LIFE_CYCLES
    PG.RECENCY_HALF_LIFE_CYCLES = half_life
    try:
        return {r.pollster: r for r in build_brand_records(polls, min_weighted=min_weighted)}
    finally:
        PG.RECENCY_HALF_LIFE_CYCLES = saved


def rows(polls) -> list[dict]:
    career = fit(polls)
    recent = fit(polls, half_life=RECENT_HALF_LIFE)
    y2024 = fit([p for p in polls if p.cycle == 2024], min_weighted=MIN_2024_POLLS)
    bg = fit([p for p in polls if p.location in set(BATTLEGROUND_2026)], min_weighted=5.0)

    out = []
    for name, rec in career.items():
        r24 = y2024.get(name)
        out.append({
            "pollster": name,
            "grade": rec.grade,
            "career": score_from_par(rec.par_error_shrunk),
            "recent": score_from_par(recent[name].par_error_shrunk) if name in recent else None,
            "y2024": score_from_par(r24.par_error_shrunk) if r24 else None,
            "battleground": score_from_par(bg[name].par_error_shrunk) if name in bg else None,
            "lean": round(rec.lean_shrunk, 2),
            "lean_2024": round(r24.lean_shrunk, 2) if r24 else None,
            "direction": rec.lean_direction,
            "abs_error": round(rec.raw_abs_error, 2),
            "n_polls": rec.n_polls,
            "n_2024": r24.n_polls if r24 else 0,
            "call_edge": round(100 * rec.call_edge, 1),
            "cycles": f"{rec.cycles[0]}–{rec.last_cycle}",
        })
    return out


HEADERS = [
    ("pollster", "Pollster", 34, "s"),
    ("grade", "Grade", 5, "s"),
    ("career", "Career", 6, "n"),
    ("recent", "Recent", 6, "n"),
    ("y2024", "2024", 6, "n"),
    ("battleground", "B'grnd", 6, "n"),
    ("lean", "Lean", 5, "n"),
    ("lean_2024", "'24 ln", 6, "n"),
    ("direction", "Direction", 9, "s"),
    ("n_polls", "Polls", 5, "d"),
    ("n_2024", "'24", 4, "d"),
    ("cycles", "Cycles", 9, "s"),
]


def render(data: list[dict], fmt: str) -> str:
    buf = io.StringIO()
    if fmt == "csv":
        w = csv.DictWriter(buf, fieldnames=list(data[0]))
        w.writeheader()
        w.writerows(data)
        return buf.getvalue()

    def fmt_cell(row, key, kind):
        v = row[key]
        if v is None:
            return "—"
        if kind == "n":
            return f"{v:.1f}"
        return str(v)

    if fmt == "md":
        buf.write("| " + " | ".join(h[1] for h in HEADERS) + " |\n")
        buf.write("|" + "|".join("---" for _ in HEADERS) + "|\n")
        for row in data:
            buf.write("| " + " | ".join(fmt_cell(row, k, t) for k, _, _, t in HEADERS) + " |\n")
        return buf.getvalue()

    def pad(text, w, kind):
        text = text[:w]
        return f"{text:<{w}}" if kind == "s" else f"{text:>{w}}"

    buf.write("  ".join(pad(label, w, t) for _, label, w, t in HEADERS).rstrip() + "\n")
    for row in data:
        buf.write("  ".join(
            pad(fmt_cell(row, k, t), w, t) for k, _, w, t in HEADERS).rstrip() + "\n")
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-polls", type=Path, default=RAW)
    ap.add_argument("--extra", type=Path, nargs="*", default=None)
    ap.add_argument("--format", choices=["text", "md", "csv"], default="text")
    ap.add_argument("--sort", choices=["career", "recent", "y2024", "battleground", "n_polls"],
                    default="recent")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--all", action="store_true", help="every graded pollster")
    ap.add_argument("--only-2024", action="store_true", help="only firms that polled in 2024")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    extra = args.extra if args.extra is not None else ([RAW_2024] if RAW_2024.exists() else [])
    polls = load([args.raw_polls, *extra])
    cycles = sorted({p.cycle for p in polls})
    print(f"{len(polls):,} scored polls, cycles {cycles[0]}–{cycles[-1]}", file=sys.stderr)

    data = rows(polls)
    if args.only_2024:
        data = [d for d in data if d["n_2024"]]
    data.sort(key=lambda d: (d[args.sort] is None, -(d[args.sort] or 0)))
    if not args.all:
        data = data[:args.top]

    text = render(data, args.format)
    if args.out:
        args.out.write_text(text)
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
