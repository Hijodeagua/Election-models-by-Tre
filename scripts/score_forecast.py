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
SNAP_DIR = ROOT / "data" / "forecast_snapshots" / "final_2026"
RESULTS = ROOT / "data" / "results" / "senate_2026.json"
OUT = ROOT / "web" / "public" / "data" / "scorecard.json"
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


def build_scorecard(snapshot: dict, meta: dict, results: dict) -> dict:
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
            "model": {
                "dem_win_prob": p_model,
                "dem_win_prob_polls": p_polls,
                "median_margin": median,
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
            dem_won = res.get("winner_party") == "D" or (
                res.get("margin") is not None
                and res["margin"] > 0
                and res.get("winner_party") != "R"
            )
            actual_margin = res.get("margin")
            row["result"] = {
                "winner": res.get("winner"),
                "winner_party": res.get("winner_party"),
                "dem_won": dem_won,
                "margin": actual_margin,
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

    return {
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


def main() -> int:
    snapshot, meta = load_snapshot()
    results = json.loads(RESULTS.read_text()).get("results", {}) if RESULTS.exists() else {}
    card = build_scorecard(snapshot, meta, results)
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
