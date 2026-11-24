"""Letter grades for the post-election scorecard.

Pure functions, no I/O: scripts/score_forecast.py feeds them the frozen
snapshot, the results and the poll list, and writes what they return into
web/public/data/scorecard.json.

Three things get graded:
  forecasters  everyone who put a number or a rating on a Senate race before
               the polls closed (our simulation, the polls-only version,
               Polymarket, Kalshi, DDHQ, Cook, Sabato, Inside Elections,
               Tre's picks), on the races each of them covered
  pollsters    each pollster's polls from the final three weeks against the
               certified margin in that race
  the tracker  the generic-ballot average and its seat translation against
               the national House result

The rubrics are fixed thresholds, printed on the site next to the grades, so
a grade can be reproduced from the numbers beside it.
"""

from __future__ import annotations

import math
import re
from datetime import date

from src.data.names import pollster_key

# Lower is better for every rubric: (upper bound, letter).
BRIER_RUBRIC = [
    (0.05, "A"), (0.075, "A-"), (0.10, "B+"), (0.125, "B"), (0.15, "B-"),
    (0.18, "C+"), (0.22, "C"), (0.25, "D"),
]
# Mean absolute miss on the margin, in points.
MARGIN_RUBRIC = [
    (2.5, "A"), (3.5, "A-"), (4.5, "B+"), (5.5, "B"), (6.5, "B-"),
    (7.5, "C+"), (9.0, "C"), (11.0, "D"),
]
# Share of calls missed.
CALLS_RUBRIC = [
    (0.03, "A"), (0.06, "A-"), (0.09, "B+"), (0.12, "B"), (0.15, "B-"),
    (0.20, "C+"), (0.25, "C"), (0.35, "D"),
]
GRADE_POINTS = {
    "A": 4.0, "A-": 3.7, "B+": 3.3, "B": 3.0, "B-": 2.7,
    "C+": 2.3, "C": 2.0, "D": 1.0, "F": 0.0,
}

# What a qualitative rating is taken to mean as a win probability for the
# favoured side. Toss-ups are 50/50 and are not counted as a call either way.
RATING_PROB = {"solid": 0.98, "likely": 0.90, "lean": 0.75, "tilt": 0.60, "tossup": 0.50}

POLL_WINDOW_START = "2026-10-13"  # final three weeks
ELECTION_DAY = "2026-11-03"
MIN_POLLS_FOR_GRADE = 3


def letter(value: float | None, rubric: list[tuple[float, str]]) -> str | None:
    if value is None:
        return None
    for bound, grade in rubric:
        if value <= bound:
            return grade
    return "F"


def gpa_letter(grades: list[str | None]) -> str | None:
    """Average a list of letters back to the nearest letter."""
    pts = [GRADE_POINTS[g] for g in grades if g in GRADE_POINTS]
    if not pts:
        return None
    avg = sum(pts) / len(pts)
    return min(GRADE_POINTS, key=lambda g: (abs(GRADE_POINTS[g] - avg), -GRADE_POINTS[g]))


def rating_to_prob(text: str | None) -> float | None:
    """'Leans D (10/6, reaffirmed 10/27)' → 0.75; 'Solid R (10/30)' → 0.02;
    'Toss Up (10/30)' → 0.5. P(Democrat or the challenger in the D column)."""
    if not text:
        return None
    m = re.match(r"\s*(solid|safe|likely|leans?|tilts?|toss[\s-]?up)\s*([dr])?", text.lower())
    if not m:
        return None
    word = m.group(1)
    if word.startswith("toss"):
        return RATING_PROB["tossup"]
    side = m.group(2)
    if side is None:
        return None
    key = {"safe": "solid", "leans": "lean", "tilts": "tilt"}.get(word, word)
    p = RATING_PROB[key]
    return p if side == "d" else round(1 - p, 4)


def _clip(p: float) -> float:
    return min(max(p, 1e-4), 1 - 1e-4)


def _brier(pairs: list[tuple[float, bool]]) -> float | None:
    if not pairs:
        return None
    return sum((p - (1.0 if w else 0.0)) ** 2 for p, w in pairs) / len(pairs)


def score_forecaster(
    key: str,
    label: str,
    kind: str,
    probs: dict[str, float],
    outcomes: dict[str, bool],
    model_probs: dict[str, float],
    margins: dict[str, float] | None = None,
    actual_margins: dict[str, float] | None = None,
    note: str | None = None,
) -> dict:
    """Score one forecaster on the called races it covered.

    ``probs`` is P(D) by state. A probability of exactly 0.5 is no call: it
    counts toward Brier and log-loss but not toward calls right.
    """
    states = [s for s in probs if s in outcomes and probs[s] is not None]
    pairs = [(probs[s], outcomes[s]) for s in states]
    calls = [(p, w) for p, w in pairs if p != 0.5]
    right = sum(1 for p, w in calls if (p > 0.5) == w)
    brier = _brier(pairs)
    ll = (
        -sum(math.log(_clip(p) if w else _clip(1 - p)) for p, w in pairs) / len(pairs)
        if pairs else None
    )
    same = [(model_probs[s], outcomes[s]) for s in states if model_probs.get(s) is not None]
    model_same = _brier(same) if len(same) == len(pairs) else None
    mae = bias = None
    n_margin = 0
    if margins and actual_margins:
        errs = [
            actual_margins[s] - margins[s]
            for s in margins
            if margins[s] is not None and actual_margins.get(s) is not None
        ]
        if errs:
            n_margin = len(errs)
            mae = sum(abs(e) for e in errs) / len(errs)
            bias = sum(errs) / len(errs)
    return {
        "key": key,
        "label": label,
        "kind": kind,
        "n": len(pairs),
        "calls_made": len(calls),
        "calls_right": right,
        "misses": sorted(s for s in states if probs[s] != 0.5 and (probs[s] > 0.5) != outcomes[s]),
        "brier": None if brier is None else round(brier, 4),
        "log_loss": None if ll is None else round(ll, 4),
        # Our simulation's Brier on exactly the races this forecaster covered,
        # so a short, easy slate does not read as a better record.
        "model_brier_same_races": None if model_same is None else round(model_same, 4),
        "margin_n": n_margin,
        "margin_mae": None if mae is None else round(mae, 2),
        "margin_bias": None if bias is None else round(bias, 2),
        "grade": letter(brier, BRIER_RUBRIC),
        "note": note,
    }


def grade_forecasters(rows: list[dict]) -> list[dict]:
    """``rows`` are the scorecard's per-race rows (called races carry a result)."""
    called = [r for r in rows if r.get("result")]
    outcomes = {r["state"]: bool(r["result"]["dem_won"]) for r in called}
    actual = {
        r["state"]: r["result"]["margin"] for r in called if r["result"].get("margin") is not None
    }

    def col(path: tuple[str, str]) -> dict[str, float]:
        a, b = path
        return {r["state"]: r[a].get(b) for r in called if r[a].get(b) is not None}

    model = col(("model", "dem_win_prob"))
    picks = {
        r["state"]: (1.0 if r["pick"]["party"] == "D" else 0.0)
        for r in called
        if r["pick"].get("party") in ("D", "R")
    }
    specs = [
        ("model", "Our simulation", "model", model, col(("model", "median_margin")),
         "Polls, fundamentals and a 25% market blend, 50,000 simulations."),
        ("polls_only", "Our polls-only number", "model", col(("model", "dem_win_prob_polls")),
         col(("model", "poll_margin")), "The polling average alone, where a race had polls."),
        ("polymarket", "Polymarket", "market", col(("others", "polymarket")), None,
         "Price on the Democrat, last look before the polls closed."),
        ("kalshi", "Kalshi", "market", col(("others", "kalshi")), None,
         "Price on the Democrat, Nov 1–2 research snapshot."),
        ("ddhq", "Decision Desk HQ", "forecaster", col(("others", "ddhq")), None,
         "Published win probability, Nov 1–2 research snapshot."),
        ("cook", "Cook Political Report", "rater", col(("others", "cook")), None,
         "Rating read as a probability; toss-ups are not a call."),
        ("sabato", "Sabato's Crystal Ball", "rater", col(("others", "sabato")), None,
         "Rating read as a probability; toss-ups are not a call."),
        ("inside_elections", "Inside Elections", "rater", col(("others", "inside_elections")),
         None, "Rating read as a probability; toss-ups are not a call."),
        ("picks", "Tre's picks", "picks", picks, col(("pick", "dem_margin")),
         "Hand calls, scored as 100% confidence in the side picked."),
    ]
    out = []
    for key, label, kind, probs, margins, note in specs:
        if not probs:
            continue
        out.append(
            score_forecaster(key, label, kind, probs, outcomes, model, margins, actual, note)
        )
    out.sort(key=lambda f: (f["brier"] is None, f["brier"] or 0))
    return out


# --------------------------------------------------------------------------
# Pollsters
# --------------------------------------------------------------------------
_PARTISAN_TAG = re.compile(r"\s*\((D|R|I)[^)]*\)")


def _display_name(name: str) -> str:
    return re.sub(r"\s{2,}", " ", _PARTISAN_TAG.sub("", name)).strip()


def _same_pollster(a: str, b: str) -> bool:
    ka, kb = set(a.split()), set(b.split())
    return bool(ka) and bool(kb) and (ka <= kb or kb <= ka)


def final_polls(states: list[dict], skip_states: set[str]) -> list[dict]:
    """Head-to-head polls that ended in the final three weeks, one row per
    poll. The same poll often arrives twice (field dates from one feed, the
    release date from another, sometimes under the sponsor's name), so rows
    in a state with matching toplines, compatible pollster names and end
    dates within three days are collapsed to the first one."""
    out: list[dict] = []
    for st in states:
        state = st["state"]
        if state in skip_states:
            continue
        kept: list[dict] = []
        for p in sorted(st.get("polls", []), key=lambda p: (p["end_date"], p["pollster"])):
            if p.get("margin") is None or p.get("dem_pct") is None or p.get("rep_pct") is None:
                continue
            if not (POLL_WINDOW_START <= p["end_date"] <= ELECTION_DAY):
                continue
            key = pollster_key(p["pollster"])
            end = date.fromisoformat(p["end_date"])
            tops = (round(p["dem_pct"]), round(p["rep_pct"]))
            dupe = any(
                k["_tops"] == tops
                and abs((end - k["_end"]).days) <= 3
                and _same_pollster(key, k["_key"])
                for k in kept
            )
            if dupe:
                continue
            kept.append({**p, "state": state, "_key": key, "_end": end, "_tops": tops})
        out.extend(kept)
    return out


def grade_pollsters(
    states: list[dict], actual_margins: dict[str, float], skip_states: set[str]
) -> dict:
    """Grade each pollster's final-three-weeks polls against the result.

    error = actual − poll (Dem − Rep margin), so a positive bias means the
    pollster understated Democrats. ``vs_field`` compares each poll's miss
    with the average miss of every final poll in the same race: negative is
    better than the pack, which matters in a year when the whole field
    missed in one direction.
    """
    polls = [p for p in final_polls(states, skip_states) if p["state"] in actual_margins]
    for p in polls:
        p["_err"] = actual_margins[p["state"]] - p["margin"]
    by_state: dict[str, list[float]] = {}
    for p in polls:
        by_state.setdefault(p["state"], []).append(abs(p["_err"]))
    field_abs = {s: sum(v) / len(v) for s, v in by_state.items()}

    groups: dict[str, list[dict]] = {}
    for p in polls:
        groups.setdefault(p["_key"], []).append(p)

    rows = []
    for group in groups.values():
        errs = [p["_err"] for p in group]
        names = [p["pollster"] for p in group]
        name = _display_name(max(set(names), key=names.count))
        tags = {m.group(1) for n in names for m in [_PARTISAN_TAG.search(n)] if m}
        mae = sum(abs(e) for e in errs) / len(errs)
        right = sum(
            1 for p in group
            if p["margin"] != 0 and (p["margin"] > 0) == (actual_margins[p["state"]] > 0)
        )
        calls = sum(1 for p in group if p["margin"] != 0)
        worst = max(group, key=lambda p: abs(p["_err"]))
        rows.append({
            "pollster": name,
            "partisan_tag": sorted(tags)[0] if len(tags) == 1 else None,
            "partisan": any(p.get("partisan") for p in group),
            "prior_grade": next((p["grade"] for p in group if p.get("grade")), None),
            "n_polls": len(group),
            "n_races": len({p["state"] for p in group}),
            "states": sorted({p["state"] for p in group}),
            "mae": round(mae, 2),
            "bias": round(sum(errs) / len(errs), 2),
            "vs_field": round(
                sum(abs(p["_err"]) - field_abs[p["state"]] for p in group) / len(group), 2
            ),
            "leaders_right": right,
            "leaders_called": calls,
            "worst": {
                "state": worst["state"], "poll_margin": worst["margin"],
                "actual_margin": actual_margins[worst["state"]],
                "error": round(worst["_err"], 2),
            },
            "grade": letter(mae, MARGIN_RUBRIC) if len(group) >= MIN_POLLS_FOR_GRADE else None,
        })
    rows.sort(key=lambda r: (r["grade"] is None, r["mae"], -r["n_polls"]))

    all_errs = [p["_err"] for p in polls]
    field = {
        "n_polls": len(polls),
        "n_pollsters": len(rows),
        "n_graded": sum(1 for r in rows if r["grade"]),
        "n_races": len(by_state),
        "mae": round(sum(abs(e) for e in all_errs) / len(all_errs), 2) if all_errs else None,
        "bias": round(sum(all_errs) / len(all_errs), 2) if all_errs else None,
    }
    return {
        "window": {"start": POLL_WINDOW_START, "end": ELECTION_DAY},
        "min_polls_for_grade": MIN_POLLS_FOR_GRADE,
        "field": field,
        "pollsters": rows,
    }


# --------------------------------------------------------------------------
# Generic ballot
# --------------------------------------------------------------------------
def grade_generic_ballot(final_avg: dict | None, house: dict | None) -> dict:
    """The tracker's last pre-election average against the House result."""
    out: dict = {"available": bool(final_avg), "forecast": None, "result": None, "grades": {}}
    if not final_avg:
        return out
    out["forecast"] = {
        "as_of": final_avg.get("as_of"),
        "dem_pct": final_avg.get("dem_pct"),
        "rep_pct": final_avg.get("rep_pct"),
        "margin": final_avg.get("margin"),
        "dem_seats": final_avg.get("estimated_dem_seats"),
        "dem_seats_lo": final_avg.get("estimated_dem_seats_lo"),
        "dem_seats_hi": final_avg.get("estimated_dem_seats_hi"),
        "num_polls": final_avg.get("num_polls"),
    }
    if not house:
        return out
    fc = out["forecast"]
    margin_err = seats_err = None
    if house.get("national_margin") is not None and fc["margin"] is not None:
        margin_err = round(house["national_margin"] - fc["margin"], 1)
    if house.get("dem_seats") is not None and fc["dem_seats"] is not None:
        seats_err = house["dem_seats"] - fc["dem_seats"]
    in_range = None
    if house.get("dem_seats") is not None and fc["dem_seats_lo"] is not None:
        in_range = fc["dem_seats_lo"] <= house["dem_seats"] <= fc["dem_seats_hi"]
    out["result"] = {
        "status": house.get("status", "provisional"),
        "as_of": house.get("as_of"),
        "dem_seats": house.get("dem_seats"),
        "rep_seats": house.get("rep_seats"),
        "uncalled_seats": house.get("uncalled_seats"),
        "national_margin": house.get("national_margin"),
        "margin_note": house.get("margin_note"),
        "sources": house.get("sources", []),
        "margin_error": margin_err,
        "seats_error": seats_err,
        "seats_in_range": in_range,
        "winner_right": (
            None if house.get("dem_seats") is None or fc["dem_seats"] is None
            else (fc["dem_seats"] >= 218) == (house["dem_seats"] >= 218)
        ),
    }
    # Seats go on the margin rubric at two seats to the point.
    out["grades"] = {
        "margin": letter(None if margin_err is None else abs(margin_err), MARGIN_RUBRIC),
        "seats": letter(None if seats_err is None else abs(seats_err) / 2.0, MARGIN_RUBRIC),
    }
    out["grades"]["overall"] = gpa_letter(list(out["grades"].values()))
    return out


# --------------------------------------------------------------------------
# Report card for our own Senate forecast
# --------------------------------------------------------------------------
def seat_percentile(distribution: dict, seats: int) -> dict | None:
    """Where the actual seat count fell in the simulated distribution."""
    if not distribution:
        return None
    total = sum(distribution.values())
    if not total:
        return None
    below = sum(v for k, v in distribution.items() if int(k) < seats)
    at = distribution.get(str(seats), 0)
    return {
        "share_at_or_above": round((total - below) / total, 4),
        "share_exact": round(at / total, 4),
        "percentile": round((below + at / 2) / total, 4),
    }


def report_card(card: dict, forecast: dict) -> dict:
    """Four subject grades and an overall for the simulation."""
    m = card["model"]
    ch = card["chamber"]
    subjects = []

    miss_rate = None if not m["n"] else 1 - (m["accuracy"] or 0)
    subjects.append({
        "key": "calls", "label": "Winner calls",
        "grade": letter(miss_rate, CALLS_RUBRIC),
        "value": f"{round((m['accuracy'] or 0) * m['n'])}/{m['n']}" if m["n"] else None,
        "detail": "races where the side we had above 50% won",
    })
    subjects.append({
        "key": "probabilities", "label": "Probabilities",
        "grade": letter(m["brier"], BRIER_RUBRIC),
        "value": None if m["brier"] is None else f"{m['brier']:.3f}",
        "detail": "Brier score; 0 is perfect, 0.25 is a coin flip",
    })
    subjects.append({
        "key": "margins", "label": "Margins",
        "grade": letter(m["margins"]["mae"], MARGIN_RUBRIC),
        "value": None if m["margins"]["mae"] is None else f"{m['margins']['mae']:.1f} pts",
        "detail": "average miss on the median margin",
    })

    # Chamber: was the favoured party right, and was the real seat count
    # somewhere the simulation thought plausible?
    chamber_grade = None
    chamber_value = None
    chamber_detail = "all races must be called"
    if ch.get("final") and ch.get("predicted_dem_control_prob") is not None:
        p = ch["predicted_dem_control_prob"]
        right = (p >= 0.5) == bool(ch["dem_control_actual"])
        pct = seat_percentile(forecast.get("seat_distribution") or {}, ch["dem_seats_so_far"])
        tail = None if pct is None else min(pct["percentile"], 1 - pct["percentile"])
        # Right party and the count inside the middle 80% is an A; the grade
        # slides as the count lands further out in the tail.
        if not right:
            chamber_grade = "D" if tail is not None and tail >= 0.1 else "F"
        elif tail is None or tail >= 0.25:
            chamber_grade = "A"
        elif tail >= 0.10:
            chamber_grade = "A-"
        elif tail >= 0.05:
            chamber_grade = "B"
        elif tail >= 0.01:
            chamber_grade = "C+"
        else:
            chamber_grade = "C"
        chamber_value = f"{ch['dem_seats_so_far']} D seats"
        chamber_detail = (
            f"we had D control at {int(p * 100 + 0.5)}% and {ch['predicted_mean_dem_seats']:.1f} "
            "seats on average"
        )
        ch["seat_percentile"] = pct
    subjects.append({
        "key": "chamber", "label": "Chamber call",
        "grade": chamber_grade, "value": chamber_value, "detail": chamber_detail,
    })

    return {
        "overall": gpa_letter([s["grade"] for s in subjects]),
        "subjects": subjects,
        "rubrics": {
            "brier": [{"max": b, "grade": g} for b, g in BRIER_RUBRIC],
            "margin_points": [{"max": b, "grade": g} for b, g in MARGIN_RUBRIC],
            "calls_missed_share": [{"max": b, "grade": g} for b, g in CALLS_RUBRIC],
            "rating_probabilities": RATING_PROB,
        },
    }
