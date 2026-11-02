#!/usr/bin/env python3
"""Convert the researched poll sheet (senate_polls_2026.csv) into the feed
format the export reads: data/fallback/senate_polls_researched.csv.

The sheet is the authoritative record for the 22 races it covers: when the
export merges it, a sheet row replaces any feed/supplement row for the same
race and pollster with the same field dates or an end date within 7 days
(supplements carry release dates, not field dates). Rows flagged
UNCONFIRMED are written with the flag and excluded from averages.

Usage:
    python scripts/load_researched_polls.py            # data/research/senate_polls_2026.csv
    python scripts/load_researched_polls.py other.csv
"""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "fallback" / "senate_polls_researched.csv"
CONFIG = ROOT / "config" / "senate_2026.json"

COLUMNS = [
    "Date Range", "Grade", "Pollster", "Subject", "Sponsor", "Sample Size", "Sample Type",
    "Population", "Weight", "Leading Result", "Leading %", "Trailing Result", "Trailing %",
    "Spread", "Leading Party", "Trailing Party", "Field Start", "Field End", "Quality Flags",
    "Sponsor Partisan", "Source URL",
]
MON = [
    "Jan.", "Feb.", "Mar.", "Apr.", "May.", "Jun.",
    "Jul.", "Aug.", "Sep.", "Oct.", "Nov.", "Dec.",
]


def _range(start: str, end: str) -> str:
    sy, sm, sd = (int(x) for x in start.split("-"))
    ey, em, ed = (int(x) for x in end.split("-"))
    if sm == em:
        return f"{MON[sm - 1]} {sd}-{ed}"
    return f"{MON[sm - 1]} {sd}-{MON[em - 1]} {ed}"


def convert(sheet_path: Path) -> tuple[str, list[str]]:
    cfg = json.loads(CONFIG.read_text())
    by_abbr = {e["abbr"]: e for e in cfg["competitive_races"]}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLUMNS)
    notes: list[str] = []
    n = 0
    rows = list(csv.DictReader(sheet_path.open(encoding="utf-8")))
    # Newest first: the feed loader infers years by walking dates backwards.
    rows.sort(key=lambda r: (r["field_end"] or "", r["field_start"] or ""), reverse=True)
    for row in rows:
        e = by_abbr[row["state"]]
        start = row["field_start"] or row["field_end"]
        end = row["field_end"]
        if not end:
            notes.append(f"skipped {row['state']} {row['pollster']}: no field_end")
            continue
        chal, rep = e["dem_candidate"], e["rep_candidate"]
        chal_party = "Independent" if e.get("challenger_party") == "I" else "Democrat"
        try:
            c_pct, r_pct = float(row["d_or_i_pct"]), float(row["r_pct"])
        except ValueError:
            notes.append(f"skipped {row['state']} {row['pollster']}: no toplines")
            continue
        lead, trail = ((chal, c_pct, chal_party), (rep, r_pct, "Republican"))
        if r_pct > c_pct:
            lead, trail = trail, lead
        flags = row.get("quality_flags", "")
        w.writerow([
            _range(start, end), "", row["pollster"], e["race"], "", row.get("n", ""), "",
            (row.get("population") or "").lower()[:2], "",
            lead[0], f"{lead[1]:.1f}%", trail[0], f"{trail[1]:.1f}%", f"{lead[1] - trail[1]:.1f}",
            lead[2], trail[2], start, end, flags, row.get("sponsor_partisan_flag", ""),
            row.get("url", ""),
        ])
        n += 1
    notes.append(f"wrote {n} polls")
    return buf.getvalue(), notes


DEFAULT_SHEET = ROOT / "data" / "research" / "senate_polls_2026.csv"


def main(argv: list[str]) -> int:
    sheet = Path(argv[1]) if len(argv) > 1 else DEFAULT_SHEET
    text, notes = convert(sheet)
    OUT.write_text(text, encoding="utf-8")
    for line in notes:
        print(f"[researched] {line}")
    print(f"[researched] → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
