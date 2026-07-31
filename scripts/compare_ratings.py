#!/usr/bin/env python3
"""Compare our fitted grades against the outside pollster ratings we can reach.

Silver Bulletin ships in the repo as an absolute-error table (28 firms).
ElectIndex publishes a 2026 rating file on GitHub (0-3 quality, 87 name rows).
VoteHub is deliberately absent: its schema has a Grade column and our loader
reads it, but every row of every snapshot we hold has it empty, because the
client never requests a rating field and refresh_data.py writes it back blank.
There is nothing to compare against until that is fixed.

    python scripts/compare_ratings.py
    python scripts/compare_ratings.py --json out.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.analysis.pollster_grades import (  # noqa: E402
    build_brand_records, normalize_poll_row, score_from_par, split_brands)
from src.data.pollster_ratings import _SB_RAW_ERRORS, _canonical  # noqa: E402

RAW = ROOT / "data" / "raw" / "raw_polls.csv"
RAW_2024 = ROOT / "data" / "raw" / "raw_polls_2024.csv"
# ElectIndex publish their 2026 model inputs, including a 0-3 pollster rating
# and a hand-coded partisan lean. It is the one outside rating table besides
# Silver Bulletin that this project can fetch. CC-BY per their repository.
EI_URL = ("https://raw.githubusercontent.com/ElectIndex/26_us_forecast_data/"
          "main/pollster_ratings.csv")
EI_CACHE = ROOT / "data" / "raw" / "electindex_pollster_ratings.csv"


def fetch_ei(dest: Path) -> Path | None:
    if dest.exists() and dest.stat().st_size > 500:
        return dest
    try:
        import httpx

        dest.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=60.0, follow_redirects=True) as c:
            r = c.get(EI_URL)
            r.raise_for_status()
            dest.write_bytes(r.content)
        return dest
    except Exception as exc:                       # offline is not fatal here
        print(f"  ElectIndex table unavailable ({exc.__class__.__name__}) — skipping")
        return None


def load(p):
    with open(p, newline="", encoding="utf-8-sig") as fh:
        return [q for q in (normalize_poll_row(r) for r in csv.DictReader(fh)) if q]


ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--json", type=Path, default=None, help="write the full payload")
args = ap.parse_args()

paths = [RAW] + ([RAW_2024] if RAW_2024.exists() else [])
polls = [p for path in paths for p in load(path)]
recs = {r.pollster: r for r in build_brand_records(polls)}
EI = fetch_ei(EI_CACHE)


def spearman(pairs):
    """Rank correlation, which is what a comparison of ratings actually asks."""
    xs, ys = zip(*pairs)
    def rank(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        out = [0.0] * len(v)
        i = 0
        while i < len(s):                      # average ties
            j = i
            while j + 1 < len(s) and v[s[j + 1]] == v[s[i]]:
                j += 1
            for k in range(i, j + 1):
                out[s[k]] = (i + j) / 2 + 1
            i = j + 1
        return out
    rx, ry = rank(list(xs)), rank(list(ys))
    mx, my = mean(rx), mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 0.0


# ── name matching ────────────────────────────────────────────────────────────
# Outside tables name the masthead; we grade the brand. Match on the brand
# components so "New York Times/Siena College" finds both of our records.
def targets(name):
    out = []
    for b in split_brands(name):
        if b in recs:
            out.append(b)
    return out


def norm(s):
    s = re.sub(r"\s*\((D|R|I)\)\s*", "", s)
    s = s.replace(" University", "").replace(" College", "").replace(" Law School", "")
    return re.sub(r"[^a-z0-9]", "", s.lower())


by_norm = {}
for name in recs:
    by_norm.setdefault(norm(name), name)


def resolve(external):
    hits = targets(external)
    if hits:
        return hits
    for part in split_brands(external) or [external]:
        m = by_norm.get(norm(part))
        if m:
            return [m]
    return []


# ── Silver Bulletin ──────────────────────────────────────────────────────────
sb_rows, sb_missing = [], []
for name, err in sorted(_SB_RAW_ERRORS.items(), key=lambda kv: kv[1]):
    hits = resolve(_canonical(name))
    if not hits:
        sb_missing.append(name)
        continue
    for h in hits:
        r = recs[h]
        sb_rows.append({
            "external": name, "ours": h, "sb_error": err,
            "score": score_from_par(r.par_error_shrunk), "grade": r.grade,
            "par": round(r.par_error_shrunk, 2), "abs": round(r.raw_abs_error, 2),
            # par = own error minus the field's on the same races, so the gap
            # between raw error and par is exactly how hard those races were.
            "difficulty": round(r.raw_abs_error - r.par_error, 2),
            "lean": round(r.lean_shrunk, 2), "n": r.n_polls,
        })

# One row per our-brand, keeping the best-matching external entry.
seen = {}
for row in sb_rows:
    seen.setdefault(row["ours"], row)
sb_rows = sorted(seen.values(), key=lambda r: r["sb_error"])

print(f"SILVER BULLETIN — {len(_SB_RAW_ERRORS)} firms in the shipped table, "
      f"{len(sb_rows)} matched to one of our {len(recs)} brands")
if sb_missing:
    print("  unmatched:", ", ".join(sb_missing))
print(f"\n  {'firm':32}{'SB err':>8}{'our abs':>9}{'our par':>9}{'score':>7}{'gr':>4}"
      f"{'difficulty':>12}{'polls':>7}")
for r in sb_rows:
    print(f"  {r['ours'][:31]:32}{r['sb_error']:8.1f}{r['abs']:9.2f}{r['par']:+9.2f}"
          f"{r['score']:7.1f}{r['grade']:>4}{r['difficulty']:12.2f}{r['n']:7d}")

pairs_sb_par = [(r["sb_error"], r["par"]) for r in sb_rows]
pairs_sb_abs = [(r["sb_error"], r["abs"]) for r in sb_rows]
pairs_sb_diff = [(r["sb_error"], r["difficulty"]) for r in sb_rows]
pairs_par_diff = [(r["par"], r["difficulty"]) for r in sb_rows]
print(f"\n  rank correlation, SB error vs our par error   {spearman(pairs_sb_par):+.3f}")
print(f"  rank correlation, SB error vs our RAW error   {spearman(pairs_sb_abs):+.3f}")
print(f"  rank correlation, SB error vs race difficulty {spearman(pairs_sb_diff):+.3f}")
print(f"  rank correlation, our par  vs race difficulty {spearman(pairs_par_diff):+.3f}")

# Biggest disagreements: standardise both and take the gap.
def z(vals):
    m, s = mean(vals), (sum((v - mean(vals)) ** 2 for v in vals) / len(vals)) ** 0.5
    return [(v - m) / s for v in vals]


zs = z([r["sb_error"] for r in sb_rows])          # higher = worse per SB
zp = z([r["par"] for r in sb_rows])               # higher = worse per us
for r, a, b in zip(sb_rows, zs, zp):
    r["gap"] = round(a - b, 2)                    # positive = we like them more
print("\n  biggest disagreements (positive = we rate them better than SB does)")
for r in sorted(sb_rows, key=lambda r: -abs(r["gap"]))[:12]:
    verdict = "we're kinder" if r["gap"] > 0 else "we're harsher"
    print(f"  {r['ours'][:31]:32}{r['gap']:+6.2f}  {verdict:14}"
          f"SB {r['sb_error']:.1f} · our par {r['par']:+.2f} · difficulty {r['difficulty']:.2f}")

# ── ElectIndex (public 2026 rating file, quality 0–3) ────────────────────────
ei_rows = []
if EI is not None and EI.exists():
    ei_seen = {}
    for row in csv.DictReader(EI.open(encoding="utf-8-sig")):
        try:
            rating = float(row["rating"])
        except (TypeError, ValueError):
            continue
        for h in resolve(row["pollster"]):
            r = recs[h]
            ei_seen.setdefault(h, {
                "external": row["pollster"], "ours": h, "ei": rating,
                "ei_lean": (row.get("lean") or "").strip() or None,
                "score": score_from_par(r.par_error_shrunk), "grade": r.grade,
                "par": round(r.par_error_shrunk, 2), "abs": round(r.raw_abs_error, 2),
                "difficulty": round(r.raw_abs_error - r.par_error, 2),
                "lean": round(r.lean_shrunk, 2), "n": r.n_polls,
            })
    ei_rows = sorted(ei_seen.values(), key=lambda r: -r["ei"])
    print(f"\n\nELECTINDEX — {len(ei_rows)} of their rows matched to our brands")
    print(f"  rank correlation, their rating vs our score   "
          f"{spearman([(r['ei'], r['score']) for r in ei_rows]):+.3f}")
    print(f"  rank correlation, their rating vs our RAW err "
          f"{spearman([(r['ei'], -r['abs']) for r in ei_rows]):+.3f}")
    print(f"  rank correlation, their rating vs difficulty  "
          f"{spearman([(r['ei'], -r['difficulty']) for r in ei_rows]):+.3f}")
    zi = z([-r["ei"] for r in ei_rows])
    zp2 = z([r["par"] for r in ei_rows])
    for r, a, b in zip(ei_rows, zi, zp2):
        r["gap"] = round(a - b, 2)
    print("\n  biggest disagreements (positive = we rate them better)")
    for r in sorted(ei_rows, key=lambda r: -abs(r["gap"]))[:12]:
        print(f"  {r['ours'][:31]:32}{r['gap']:+6.2f}  their {r['ei']:.1f} · "
              f"our score {r['score']:.1f} · difficulty {r['difficulty']:.2f} · n={r['n']}")

# ── why they differ ─────────────────────────────────────────────────────────
# Our metric has no methodology term in it at all: a poll is judged only against
# the result. Both outside tables are built to reward disclosure. The archive
# carries 538's AAPOR-Transparency-Initiative / Roper-contributor flag, so the
# hypothesis is directly testable — split the disagreements on it.
tflag = {}
_counts = {}
with RAW.open(newline="", encoding="utf-8-sig") as fh:
    for row in csv.DictReader(fh):
        v = (row.get("aapor_roper") or "").strip().lower()
        for b in split_brands(row["pollster"]):
            c = _counts.setdefault(b, [0, 0])
            c[0 if v in {"true", "yes", "1"} else 1] += 1
for b, (yes, no) in _counts.items():
    tflag[b] = None if yes + no == 0 else yes > no

transparency = {}
for key, rows in (("sb", sb_rows), ("ei", ei_rows)):
    yes = [r["gap"] for r in rows if tflag.get(r["ours"]) is True]
    no = [r["gap"] for r in rows if tflag.get(r["ours"]) is False]
    for r in rows:
        r["aapor"] = tflag.get(r["ours"])
    if yes and no:
        transparency[key] = {
            "member_gap": round(mean(yes), 2), "member_n": len(yes),
            "nonmember_gap": round(mean(no), 2), "nonmember_n": len(no),
            "separation": round(mean(no) - mean(yes), 2),
        }
print("\n\nWHY THEY DIFFER — gap is how much better we rate a firm than they do (z)")
for key, lab in (("sb", "Silver Bulletin"), ("ei", "ElectIndex")):
    t = transparency.get(key)
    if t:
        print(f"  {lab:18} AAPOR/Roper members {t['member_gap']:+.2f} (n={t['member_n']})"
              f" · non-members {t['nonmember_gap']:+.2f} (n={t['nonmember_n']})"
              f" · separation {t['separation']:+.2f} z")

payload = {
    "transparency": transparency,
    "sb": {"rows": sb_rows, "n_table": len(_SB_RAW_ERRORS), "unmatched": sb_missing,
           "rho_par": round(spearman(pairs_sb_par), 3),
           "rho_abs": round(spearman(pairs_sb_abs), 3),
           "rho_difficulty": round(spearman(pairs_sb_diff), 3),
           "rho_par_difficulty": round(spearman(pairs_par_diff), 3)},
    "ei": {"rows": ei_rows,
           "rho_score": round(spearman([(r["ei"], r["score"]) for r in ei_rows]), 3) if ei_rows else None,
           "rho_abs": round(spearman([(r["ei"], -r["abs"]) for r in ei_rows]), 3) if ei_rows else None,
           "rho_difficulty": round(spearman([(r["ei"], -r["difficulty"]) for r in ei_rows]), 3) if ei_rows else None},
    "n_brands": len(recs),
}
if args.json:
    args.json.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"\nwrote {args.json}")
