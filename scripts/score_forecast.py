#!/usr/bin/env python3
"""Score the site against actual results: how good were the model and the picks?

Everything is scored against a FROZEN pre-election snapshot, not the live
files, so later data refreshes (and picks entered after the fact) cannot
flatter the record. The snapshot is the last commit before polls began
closing (2026-11-03 23:00 UTC); its three files are copied to
data/forecast_snapshots/final_2026/ the first time this runs and read from
there afterwards.

Inputs
  data/forecast_snapshots/final_2026/{senate_forecast,senate,predictions}.json
  data/results/senate_2026.json           (scripts/fetch_results.py)

Output
  web/public/data/scorecard.json — per-race rows plus aggregate scores for
  the model, Tre's picks and the prediction markets, and the chamber call.

Scores
  accuracy   share of called races where the side with P > 0.5 (or the pick) won
  brier      mean (P(D) − 1[D won])²  — lower is better, 0.25 is a coin flip
  log_loss   mean −log P(actual winner)
  mae        mean |median margin − actual margin|, in points
  bias       mean (actual − predicted margin): positive = Dems did better than said
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.grade_forecast import (  # noqa: E402
    MARGIN_RUBRIC,
    grade_forecasters,
    grade_generic_ballot,
    grade_pollsters,
    letter,
    rating_to_prob,
    report_card,
)

SNAP_DIR = ROOT / "data" / "forecast_snapshots" / "final_2026"
RESULTS = ROOT / "data" / "results" / "senate_2026.json"
HOUSE_RESULTS = ROOT / "data" / "results" / "house_2026.json"
WEB_DATA = ROOT / "web" / "public" / "data"
OUT = WEB_DATA / "scorecard.json"
POLLSTERS = WEB_DATA / "pollsters.json"
GENERIC_BALLOT = WEB_DATA / "generic_ballot.json"
# The frozen forecast, republished so the forecast pages can show what was
# said before the polls closed instead of the still-refreshing live files.
FINAL_COPIES = {"senate_forecast": "final_senate_forecast.json", "senate": "final_senate.json"}
ELECTION_DAY = "2026-11-03"
FREEZE_AT = "2026-11-03T23:00:00Z"  # first poll closings (6pm ET)
SNAP_FILES = {
    "senate_forecast": "web/public/data/senate_forecast.json",
    "senate": "web/public/data/senate.json",
    "predictions": "web/content/predictions.json",
}
# Holdovers from config: Dems hold 34 seats not on the ballot.
DEM_HOLDOVERS = 34


def log(msg: str) -> None:
    print(f"[scorecard] {msg}", file=sys.stderr)


# --------------------------------------------------------------------------
# Snapshot
# --------------------------------------------------------------------------
def _git(*args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def load_snapshot() -> tuple[dict, dict]:
    """Return (files, meta). Freezes from git history on first use."""
    meta_path = SNAP_DIR / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        files = {k: json.loads((SNAP_DIR / f"{k}.json").read_text()) for k in SNAP_FILES}
        return files, meta

    ref = _git("rev-list", "-1", f"--before={FREEZE_AT}", "HEAD")
    files: dict = {}
    if ref:
        for key, path in SNAP_FILES.items():
            raw = _git("show", f"{ref}:{path}")
            files[key] = json.loads(raw) if raw else {}
        when = _git("show", "-s", "--format=%cI", ref) or ""
        meta = {"ref": ref, "committed_at": when, "frozen_at": FREEZE_AT, "mode": "git"}
    else:
        for key, path in SNAP_FILES.items():
            p = ROOT / path
            files[key] = json.loads(p.read_text()) if p.exists() else {}
        meta = {"ref": None, "committed_at": None, "frozen_at": FREEZE_AT, "mode": "live-fallback"}
        log("git history unavailable — scoring the live files (not frozen)")

    # Only persist the freeze once the freeze time has passed; before that,
    # every run would otherwise pin an early snapshot.
    now = datetime.now(UTC)
    freeze = datetime.fromisoformat(FREEZE_AT.replace("Z", "+00:00"))
    if now >= freeze and meta["mode"] == "git":
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        for key, data in files.items():
            (SNAP_DIR / f"{key}.json").write_text(json.dumps(data, indent=1) + "\n")
        meta["saved_at"] = now.isoformat(timespec="seconds")
        meta_path.write_text(json.dumps(meta, indent=1) + "\n")
        log(f"froze snapshot {ref[:10]} into {SNAP_DIR.relative_to(ROOT)}")
    else:
        meta["note"] = "provisional — freeze time not reached, snapshot not persisted"
    return files, meta


# --------------------------------------------------------------------------
# Scoring helpers
# --------------------------------------------------------------------------
def _clip(p: float) -> float:
    return min(max(p, 1e-4), 1 - 1e-4)


def score_probabilities(pairs: list[tuple[float, bool]]) -> dict:
    """pairs of (P(D wins), D actually won)."""
    if not pairs:
        return {"n": 0, "accuracy": None, "brier": None, "log_loss": None}
    acc = sum(1 for p, w in pairs if (p >= 0.5) == w) / len(pairs)
    brier = sum((p - (1.0 if w else 0.0)) ** 2 for p, w in pairs) / len(pairs)
    ll = -sum(math.log(_clip(p) if w else _clip(1 - p)) for p, w in pairs) / len(pairs)
    return {
        "n": len(pairs),
        "accuracy": round(acc, 3),
        "brier": round(brier, 4),
        "log_loss": round(ll, 4),
    }


def score_margins(pairs: list[tuple[float, float]]) -> dict:
    """pairs of (predicted Dem−Rep margin, actual)."""
    if not pairs:
        return {"n": 0, "mae": None, "bias": None, "rmse": None}
    errs = [a - p for p, a in pairs]
    return {
        "n": len(pairs),
        "mae": round(sum(abs(e) for e in errs) / len(errs), 2),
        "bias": round(sum(errs) / len(errs), 2),
        "rmse": round(math.sqrt(sum(e * e for e in errs) / len(errs)), 2),
    }


def calibration_bins(pairs: list[tuple[float, bool]]) -> list[dict]:
    edges = [0, 0.2, 0.4, 0.6, 0.8, 1.0001]
    out = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        sel = [(p, w) for p, w in pairs if lo <= p < hi]
        if not sel:
            continue
        out.append(
            {
                "bin": f"{int(lo * 100)}-{int(min(hi, 1) * 100)}%",
                "n": len(sel),
                "predicted": round(sum(p for p, _ in sel) / len(sel), 3),
                "actual": round(sum(1 for _, w in sel if w) / len(sel), 3),
            }
        )
    return out


def pick_dem_margin(pick: str | None, margin: float | None) -> float | None:
    if pick == "D" and margin is not None:
        return margin
    if pick == "R" and margin is not None:
        return -margin
    return None


def actual_margin_for(fc: dict, res: dict, status: dict | None) -> tuple[float | None, str | None]:
    """The margin the forecast should be held to, and what it measures.

    Normally Dem − Rep. Where an independent sits in the challenger column
    (no Democrat on the ballot, or a third-place one), the forecast margin is
    independent − Republican, and the results feed has no such number — only
    the winner's lead over the runner-up, which is the same thing whenever
    those two finished first and second.
    """
    if fc.get("challenger_party") != "I":
        return res.get("margin"), ("dem_minus_rep" if res.get("margin") is not None else None)
    lead = (status or {}).get("leader_margin")
    if lead is None:
        return None, None
    return (-lead if res.get("winner_party") == "R" else lead), "challenger_minus_rep"


def other_forecasts(fc: dict) -> dict:
    """What everyone else said about a race before the polls closed, as P(D)."""
    cons = fc.get("consensus") or {}
    live = fc.get("market_dem_prob") or {}
    poly = live.get("polymarket", cons.get("polymarket_p_dem"))
    kalshi = live.get("kalshi", cons.get("kalshi_p_dem"))
    return {
        "polymarket": poly,
        "kalshi": kalshi,
        "ddhq": cons.get("ddhq_p_dem"),
        "cook": rating_to_prob(cons.get("cook")),
        "sabato": rating_to_prob(cons.get("sabato")),
        "inside_elections": rating_to_prob(cons.get("inside_elections")),
        "ratings": {
            k: cons.get(k) for k in ("cook", "sabato", "inside_elections") if cons.get(k)
        },
    }


def build_scorecard(
    snapshot: dict,
    meta: dict,
    results: dict,
    status: dict | None = None,
    pollster_states: list[dict] | None = None,
    generic_final: dict | None = None,
    house: dict | None = None,
) -> dict:
    status = status or {}
    forecast = snapshot.get("senate_forecast") or {}
    senate = {r["state"]: r for r in (snapshot.get("senate") or {}).get("races", [])}
    picks = {r["state"]: r for r in (snapshot.get("predictions") or {}).get("races", [])}
    fc_races = {r["state"]: r for r in forecast.get("races", [])}

    rows = []
    model_pairs: list[tuple[float, bool]] = []
    polls_pairs: list[tuple[float, bool]] = []
    market_pairs: list[tuple[float, bool]] = []
    pick_pairs: list[tuple[float, bool]] = []
    model_margins: list[tuple[float, float]] = []
    pick_margins: list[tuple[float, float]] = []
    poll_margins: list[tuple[float, float]] = []
    dem_wins_called = 0

    for state, fc in fc_races.items():
        res = results.get(state)
        pick = picks.get(state)
        p_model = fc.get("dem_win_prob_sim")
        if p_model is None:
            p_model = fc.get("dem_win_prob_blended")
        p_polls = fc.get("dem_win_prob_polls")
        p_market = (fc.get("market_dem_prob") or {}).get("polymarket")
        median = fc.get("median_margin")
        poll_margin = (senate.get(state) or {}).get("dem_margin")
        row = {
            "state": state,
            "called": res is not None,
            "race": {
                "dem_candidate": fc.get("dem_candidate"),
                "rep_candidate": fc.get("rep_candidate"),
                "challenger_party": fc.get("challenger_party") or "D",
                "held_by": fc.get("held_by"),
                "open_seat": bool(fc.get("open_seat")),
                "treatment": fc.get("treatment"),
            },
            "others": other_forecasts(fc),
            "model": {
                "dem_win_prob": p_model,
                "dem_win_prob_polls": p_polls,
                "median_margin": median,
                "margin_p10": fc.get("margin_p10"),
                "margin_p90": fc.get("margin_p90"),
                "poll_margin": poll_margin,
                "num_polls": fc.get("num_polls"),
                "call": None if p_model is None else ("D" if p_model >= 0.5 else "R"),
            },
            "market": {"polymarket_dem_prob": p_market},
            "pick": {
                "party": pick.get("pick") if pick else None,
                "margin": pick.get("margin") if pick else None,
                "dem_margin": (
                    pick_dem_margin(pick.get("pick"), pick.get("margin")) if pick else None
                ),
                "on_board": pick is not None,
            },
            "result": None,
        }
        if res is not None:
            actual_margin, margin_basis = actual_margin_for(fc, res, status.get(state))
            dem_won = res.get("winner_party") == "D" or (
                actual_margin is not None
                and actual_margin > 0
                and res.get("winner_party") != "R"
            )
            row["result"] = {
                "winner": res.get("winner"),
                "winner_party": res.get("winner_party"),
                "dem_won": dem_won,
                "margin": actual_margin,
                "margin_basis": margin_basis,
                "dem_pct": res.get("dem_pct"),
                "rep_pct": res.get("rep_pct"),
                "flipped": (
                    fc.get("held_by") in ("D", "R")
                    and res.get("winner_party") is not None
                    and res.get("winner_party") != fc.get("held_by")
                ),
                "source": res.get("source"),
            }
            if dem_won:
                dem_wins_called += 1
            if p_model is not None:
                model_pairs.append((p_model, dem_won))
                row["model"]["correct"] = (p_model >= 0.5) == dem_won
            if p_polls is not None:
                polls_pairs.append((p_polls, dem_won))
            if p_market is not None:
                market_pairs.append((p_market, dem_won))
                row["market"]["correct"] = (p_market >= 0.5) == dem_won
            if median is not None and actual_margin is not None:
                model_margins.append((median, actual_margin))
                row["model"]["margin_error"] = round(actual_margin - median, 2)
                lo, hi = fc.get("margin_p10"), fc.get("margin_p90")
                if lo is not None and hi is not None:
                    row["model"]["in_80_band"] = lo <= actual_margin <= hi
            if poll_margin is not None and actual_margin is not None:
                poll_margins.append((poll_margin, actual_margin))
            if pick and pick.get("pick") in ("D", "R"):
                pick_won = (pick["pick"] == "D") == dem_won
                pick_pairs.append((1.0 if pick["pick"] == "D" else 0.0, dem_won))
                row["pick"]["correct"] = pick_won
                pm = row["pick"]["dem_margin"]
                if pm is not None and actual_margin is not None:
                    pick_margins.append((pm, actual_margin))
                    row["pick"]["margin_error"] = round(actual_margin - pm, 2)
        rows.append(row)

    n_total = len(fc_races)
    n_called = sum(1 for r in rows if r["called"])
    picks_made = sum(1 for r in rows if r["pick"]["party"] in ("D", "R", "I"))
    chamber = {
        "predicted_dem_control_prob": forecast.get("dem_control_prob"),
        "predicted_mean_dem_seats": forecast.get("mean_dem_seats"),
        "dem_seats_so_far": DEM_HOLDOVERS + dem_wins_called,
        "races_outstanding": n_total - n_called,
        "final": n_called == n_total and n_total > 0,
        "dem_control_actual": (
            (DEM_HOLDOVERS + dem_wins_called >= 51) if n_called == n_total else None
        ),
    }

    card = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "snapshot": meta,
        "status": "final" if chamber["final"] else ("partial" if n_called else "awaiting_results"),
        "num_races": n_total,
        "num_called": n_called,
        "picks_made": picks_made,
        "model": {
            **score_probabilities(model_pairs),
            "margins": score_margins(model_margins),
            "polls_only": score_probabilities(polls_pairs),
            "poll_average_margins": score_margins(poll_margins),
            "calibration": calibration_bins(model_pairs),
        },
        "picks": {**score_probabilities(pick_pairs), "margins": score_margins(pick_margins)},
        "market": score_probabilities(market_pairs),
        "chamber": chamber,
        "races": rows,
    }

    banded = [r["model"]["in_80_band"] for r in rows if "in_80_band" in r["model"]]
    card["model"]["band_coverage"] = {
        "n": len(banded),
        "inside": sum(banded),
        "share": round(sum(banded) / len(banded), 3) if banded else None,
    }
    card["model"]["poll_average_grade"] = letter(
        card["model"]["poll_average_margins"]["mae"], MARGIN_RUBRIC
    )
    card["report_card"] = report_card(card, forecast)
    card["forecasters"] = grade_forecasters(rows)
    actual_margins = {
        r["state"]: r["result"]["margin"]
        for r in rows
        if r["result"] and r["result"]["margin"] is not None
    }
    # Independent-challenger races are left out of the pollster grades: their
    # polls and their results are not measured on the same two candidates.
    skip = {r["state"] for r in rows if r["race"]["challenger_party"] == "I"}
    card["pollster_grades"] = (
        grade_pollsters(pollster_states, actual_margins, skip) if pollster_states else None
    )
    card["generic_ballot"] = grade_generic_ballot(generic_final, house)
    return card


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def final_generic_ballot(data: dict) -> dict | None:
    """The tracker's last average on or before election day."""
    pre = [t for t in data.get("trend", []) if t.get("as_of", "") <= ELECTION_DAY]
    return max(pre, key=lambda t: t["as_of"]) if pre else None


def main() -> int:
    snapshot, meta = load_snapshot()
    raw = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    card = build_scorecard(
        snapshot,
        meta,
        raw.get("results", {}),
        status=raw.get("status", {}),
        pollster_states=_read_json(POLLSTERS).get("states"),
        generic_final=final_generic_ballot(_read_json(GENERIC_BALLOT)),
        house=_read_json(HOUSE_RESULTS) or None,
    )
    if meta.get("mode") == "git" and "note" not in meta:
        for key, name in FINAL_COPIES.items():
            (WEB_DATA / name).write_text(
                json.dumps(snapshot[key], indent=1, ensure_ascii=False) + "\n"
            )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(card, indent=1, ensure_ascii=False) + "\n")
    log(
        f"wrote {OUT.relative_to(ROOT)}: {card['status']}, "
        f"{card['num_called']}/{card['num_races']} called, "
        f"model acc {card['model']['accuracy']} brier {card['model']['brier']}, "
        f"picks acc {card['picks']['accuracy']} ({card['picks_made']} made)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
