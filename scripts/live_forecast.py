"""Election-night live forecast: rerun the frozen pre-election simulation
conditioned on the races that have been called so far.

Every hour (``.github/workflows/live_forecast.yml``) this:

  1. loads the pre-election snapshot (``data/forecast_snapshots/final_2026``),
     the same one the scorecard is graded against, and rebuilds each race's
     input from its frozen blended win probability, so the only thing that
     changes between runs is the set of calls;
  2. reads the called results (``scripts/fetch_results.py`` output plus the
     manual override file), records when each call was first seen in
     ``data/results/call_log.json``;
  3. reruns the Monte Carlo conditioned on those calls: draws that disagree
     with a call are dropped, so the shared national error, and with it every
     uncalled race, updates toward what the calls imply;
  4. writes ``web/public/data/live_forecast.json`` with the live chamber odds,
     seats called so far, the calls of the past hour, the uncalled races'
     pre-election vs live odds, and the history of P(D control) over the night.

Run ``python scripts/live_forecast.py`` after ``fetch_results.py``. Safe to
re-run: the history only grows when the numbers or the call count change.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.models.senate_simulation import (  # noqa: E402
    RaceInput,
    SenateControlSimulator,
)

SNAPSHOT_DIR = ROOT / "data" / "forecast_snapshots" / "final_2026"
LIVE_FORECAST_FALLBACK = ROOT / "web" / "public" / "data" / "senate_forecast.json"
RESULTS = ROOT / "data" / "results" / "senate_2026.json"
MANUAL = ROOT / "data" / "results" / "senate_2026_manual.json"
CALL_LOG = ROOT / "data" / "results" / "call_log.json"
OUT = ROOT / "web" / "public" / "data" / "live_forecast.json"

NUM_SIMULATIONS = 200_000
SEED = 20261103
NEW_CALL_WINDOW = timedelta(hours=1)
HISTORY_CAP = 1000


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_snapshot(snapshot_dir: Path) -> tuple[dict, dict]:
    """The frozen forecast and its metadata (falls back to the live file)."""
    fc = snapshot_dir / "senate_forecast.json"
    meta_path = snapshot_dir / "meta.json"
    if fc.exists():
        meta = _read_json(meta_path) if meta_path.exists() else {}
        meta.setdefault("mode", "git")
        return _read_json(fc), meta
    return _read_json(LIVE_FORECAST_FALLBACK), {"mode": "live-fallback", "ref": None}


def load_status(results_path: Path) -> dict[str, dict]:
    """Per-race reporting status (AP via NYT) written by fetch_results.py."""
    if not results_path.exists():
        return {}
    return _read_json(results_path).get("status") or {}


def load_results(results_path: Path, manual_path: Path) -> dict[str, dict]:
    """Called results by state: fetched file, with manual entries overriding."""
    out: dict[str, dict] = {}
    for path, source in ((results_path, "fetched"), (manual_path, "manual")):
        if not path.exists():
            continue
        for state, res in (_read_json(path).get("results") or {}).items():
            if not isinstance(res, dict) or not res.get("winner_party"):
                continue
            out[state] = {**res, "source": res.get("source") or source}
    return out


def build_inputs(snapshot: dict) -> list[RaceInput]:
    """One RaceInput per frozen race, carrying its frozen blended P(win).

    ``margin=None`` with a single market price makes ``_blended_prob`` return
    exactly that price, so the conditioned rerun starts from the same per-race
    probabilities the pre-election forecast published.
    """
    inputs: list[RaceInput] = []
    for r in snapshot["races"]:
        p = r.get("dem_win_prob_blended")
        if p is None:
            p = r.get("dem_win_prob_sim")
        if p is None:
            continue
        inputs.append(
            RaceInput(
                state=r["state"],
                race=r.get("race") or f"{r['state']} Senate 2026",
                dem_candidate=r.get("dem_candidate") or "",
                rep_candidate=r.get("rep_candidate") or "",
                margin=None,
                num_polls=int(r.get("num_polls") or 0),
                market_dem_prob={"frozen": float(p)},
                challenger_party=r.get("challenger_party") or "D",
            )
        )
    return inputs


def conditions_from_results(snapshot: dict, results: dict[str, dict]) -> dict[str, bool]:
    """state → did the race's challenger side (D, or I in an I race) win."""
    party_of = {r["state"]: (r.get("challenger_party") or "D") for r in snapshot["races"]}
    conds: dict[str, bool] = {}
    for state, res in results.items():
        if state not in party_of:
            continue
        conds[state] = res["winner_party"] == party_of[state]
    return conds


def update_call_log(
    results: dict[str, dict], now: datetime, log_path: Path
) -> tuple[list[dict], list[str]]:
    """Record when each call was first seen; returns (log, retracted states).

    A state that was logged but is no longer in the results (the source
    withdrew the call, or an earlier run mis-parsed the page) is dropped from
    the log so it is not shown as called.
    """
    log: list[dict] = []
    if log_path.exists():
        log = _read_json(log_path).get("calls") or []
    retracted = sorted(c["state"] for c in log if c["state"] not in results)
    if retracted:
        log = [c for c in log if c["state"] in results]
    seen = {c["state"] for c in log}
    for state, res in sorted(results.items()):
        if state in seen:
            continue
        log.append(
            {
                "state": state,
                "winner": res.get("winner"),
                "winner_party": res["winner_party"],
                "first_seen": now.isoformat(timespec="seconds"),
                "source": res.get("source"),
            }
        )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps({"calls": log}, indent=1) + "\n", encoding="utf-8")
    return log, retracted


def simulator_from_snapshot(snapshot: dict) -> SenateControlSimulator:
    return SenateControlSimulator(
        dem_safe_seats=int(snapshot["dem_safe_seats"]),
        rep_safe_seats=int(snapshot["rep_safe_seats"]),
        dem_majority_threshold=int(snapshot.get("dem_majority_threshold") or 51),
        national_sigma=float(snapshot["national_sigma"]),
        race_sigma=float(snapshot["race_sigma"]),
        market_weight=float(snapshot.get("market_weight") or 0.0),
        bias=float(snapshot.get("bias") or 0.0),
        tail_dof=snapshot.get("tail_dof"),
    )


def _winner_pre_prob(race: dict, winner_party: str) -> float | None:
    """Pre-election probability the frozen forecast gave the eventual winner."""
    p = race.get("dem_win_prob_sim")
    if p is None:
        p = race.get("dem_win_prob_blended")
    if p is None:
        return None
    side = race.get("challenger_party") or "D"
    if winner_party == side:
        return float(p)
    if winner_party == "R":
        return round(1.0 - float(p), 4)
    return None  # a third party nobody modelled


def build_live_forecast(
    snapshot: dict,
    snapshot_meta: dict,
    results: dict[str, dict],
    call_log: list[dict],
    now: datetime,
    previous: dict | None,
    num_simulations: int = NUM_SIMULATIONS,
    seed: int = SEED,
    retracted: list[str] | None = None,
    status: dict[str, dict] | None = None,
) -> dict:
    status = status or {}
    inputs = build_inputs(snapshot)
    conditions = conditions_from_results(snapshot, results)
    sim = simulator_from_snapshot(snapshot)
    live = sim.simulate(
        inputs, num_simulations=num_simulations, seed=seed, conditions=conditions or None
    )
    live_by_state = {r.state: r for r in live.races}
    frozen_by_state = {r["state"]: r for r in snapshot["races"]}
    first_seen = {c["state"]: c["first_seen"] for c in call_log}

    seats = {"D": int(snapshot["dem_safe_seats"]), "R": int(snapshot["rep_safe_seats"]), "I": 0}
    called: list[dict] = []
    for state in sorted(results):
        res = results[state]
        fr = frozen_by_state.get(state)
        if fr is None:
            continue
        party = res["winner_party"]
        if party in seats:
            seats[party] += 1
        pre = _winner_pre_prob(fr, party)
        st = status.get(state) or {}
        gained = res.get("gained")
        if gained is None:
            gained = bool(fr.get("held_by")) and party != fr.get("held_by")
        called.append(
            {
                "state": state,
                "winner": res.get("winner"),
                "winner_party": party,
                "margin": res.get("margin"),
                "pre_election_prob": pre,
                "upset": pre is not None and pre < 0.5,
                "flip": bool(gained),
                "called_at": res.get("called_at") or first_seen.get(state),
                "first_seen": first_seen.get(state),
                "eevp": st.get("eevp", res.get("eevp")),
                "source": res.get("source"),
            }
        )

    remaining: list[dict] = []
    for fr in snapshot["races"]:
        state = fr["state"]
        if state in results:
            continue
        lv = live_by_state.get(state)
        pre_p = fr.get("dem_win_prob_sim")
        live_p = lv.dem_win_prob_sim if lv is not None else None
        st = status.get(state) or {}
        remaining.append(
            {
                "state": state,
                "dem_candidate": fr.get("dem_candidate"),
                "rep_candidate": fr.get("rep_candidate"),
                "challenger_party": fr.get("challenger_party") or "D",
                "held_by": fr.get("held_by"),
                "pre_election_prob": pre_p,
                "live_prob": live_p,
                "live_median_margin": lv.median_margin if lv is not None else None,
                "status": st.get("status") or "no_results",
                "eevp": st.get("eevp"),
                "leader": st.get("leader"),
                "leader_party": st.get("leader_party"),
                "leader_margin": st.get("leader_margin"),
                "count_margin": st.get("margin"),
            }
        )
    remaining.sort(key=lambda r: abs((r["live_prob"] if r["live_prob"] is not None else 0.5) - 0.5))

    cutoff = now - NEW_CALL_WINDOW
    new_calls = []
    for c in called:
        stamp = c.get("called_at") or c.get("first_seen")
        if not stamp:
            continue
        try:
            when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if when > cutoff:
            new_calls.append(c["state"])

    history = list((previous or {}).get("history") or [])
    if retracted:
        # Earlier points were computed with calls that have since gone away:
        # drop the ones that counted more calls than exist now.
        history = [h for h in history if (h.get("num_called") or 0) <= len(called)]
    point = {
        "at": now.isoformat(timespec="seconds"),
        "dem_control_prob": live.dem_control_prob,
        "mean_dem_seats": live.mean_dem_seats,
        "num_called": len(called),
    }
    last = history[-1] if history else None
    if last is None or any(last.get(k) != point[k] for k in ("dem_control_prob", "num_called")):
        history.append(point)
    history = history[-HISTORY_CAP:]

    return {
        "generated": now.isoformat(timespec="seconds"),
        "snapshot": {
            "ref": snapshot_meta.get("ref"),
            "committed_at": snapshot_meta.get("committed_at"),
            "frozen_at": snapshot_meta.get("frozen_at"),
            "mode": snapshot_meta.get("mode"),
        },
        "num_races": len(snapshot["races"]),
        "num_called": len(called),
        "new_calls": new_calls,
        "retracted": retracted or [],
        "results_source": next((c.get("source") for c in called if c.get("source")), None)
        or ("ap-via-nyt" if status else None),
        "reporting": sum(1 for r in remaining if r["status"] == "reporting"),
        "seats_so_far": seats,
        "dem_majority_threshold": int(snapshot.get("dem_majority_threshold") or 51),
        "pre_election": {
            "dem_control_prob": snapshot.get("dem_control_prob"),
            "mean_dem_seats": snapshot.get("mean_dem_seats"),
            "mean_ind_seats": snapshot.get("mean_ind_seats"),
        },
        "live": {
            "dem_control_prob": live.dem_control_prob,
            "mean_dem_seats": live.mean_dem_seats,
            "median_dem_seats": live.median_dem_seats,
            "mean_ind_seats": live.mean_ind_seats,
            "seat_distribution": {str(k): v for k, v in live.seat_distribution.items()},
            "num_simulations": num_simulations,
            "kept_simulations": live.kept_simulations,
            "condition_mode": live.condition_mode,
        },
        "called": called,
        "remaining": remaining,
        "history": history,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--snapshot-dir", type=Path, default=SNAPSHOT_DIR)
    ap.add_argument("--results", type=Path, default=RESULTS)
    ap.add_argument("--manual", type=Path, default=MANUAL)
    ap.add_argument("--call-log", type=Path, default=CALL_LOG)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--num-simulations", type=int, default=NUM_SIMULATIONS)
    ap.add_argument("--now", type=str, default=None, help="ISO timestamp (tests)")
    args = ap.parse_args(argv)

    now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    snapshot, meta = load_snapshot(args.snapshot_dir)
    results = load_results(args.results, args.manual)
    status = load_status(args.results)
    call_log, retracted = update_call_log(results, now, args.call_log)
    previous = _read_json(args.out) if args.out.exists() else None
    payload = build_live_forecast(
        snapshot, meta, results, call_log, now, previous,
        num_simulations=args.num_simulations, retracted=retracted, status=status,
    )
    if retracted:
        print(f"retracted calls (no longer in results): {', '.join(retracted)}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    lv, pre = payload["live"], payload["pre_election"]
    print(
        f"live forecast: {payload['num_called']}/{payload['num_races']} called "
        f"({len(payload['new_calls'])} new in the past hour); "
        f"P(D control) {pre['dem_control_prob']} → {lv['dem_control_prob']}; "
        f"seats so far D {payload['seats_so_far']['D']} R {payload['seats_so_far']['R']} "
        f"I {payload['seats_so_far']['I']}; mode={lv['condition_mode']} "
        f"kept={lv['kept_simulations']}"
    )
    for c in payload["called"]:
        flag = " UPSET" if c["upset"] else ""
        print(
            f"  {c['state']:<16} {c['winner_party']}  "
            f"pre-election {c['pre_election_prob']}{flag}"
        )
    out_path = args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out
    print(f"  → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
