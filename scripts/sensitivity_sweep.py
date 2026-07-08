"""Sensitivity analysis for the hand-set governance knobs (audit item 7).

Every knob below was chosen, not learned — each is a place overconfidence can
enter the Senate forecast. This script re-runs the production forecast path
(same code as export_json.py) across a grid of knob values and reports how the
headline number — P(Dem Senate control) — and mean seats respond.

Output: printed table + config/sensitivity_analysis.json (committed so the
sweep travels with the calibration it was run against).

Usage:
    python scripts/sensitivity_sweep.py
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.export_json import (
    _approval_payload,
    _generic_ballot_payload,
    _load_polls,
    _senate_forecast_payload,
    _senate_payload,
)
from src.data.base import PollType

OUTPUT_PATH = PROJECT_ROOT / "config" / "sensitivity_analysis.json"

# Each entry: (knob label, baseline description, list of (value label, overrides dict)).
# Baselines marked with * in the output.
SWEEPS: list[tuple[str, str, list[tuple[str, dict]]]] = [
    (
        "calibration_bias_weight",
        "scales the fitted −2.5pp poll bias before applying (base 0.5)",
        [
            ("0.0", {"forecast": {"calibration_bias_weight": 0.0}}),
            ("0.25", {"forecast": {"calibration_bias_weight": 0.25}}),
            ("0.5*", {}),
            ("0.75", {"forecast": {"calibration_bias_weight": 0.75}}),
            ("1.0", {"forecast": {"calibration_bias_weight": 1.0}}),
        ],
    ),
    (
        "blend_k",
        "fundamentals weight k/(k+n) anchoring thin-poll races (base 3.0)",
        [
            ("1.5", {"fundamentals": {"blend_k": 1.5}}),
            ("3.0*", {}),
            ("4.5", {"fundamentals": {"blend_k": 4.5}}),
            ("6.0", {"fundamentals": {"blend_k": 6.0}}),
        ],
    ),
    (
        "pres_weight_recent",
        "weight on 2024 vs 2020 presidential lean (base 0.75)",
        [
            ("0.5", {"fundamentals": {"pres_weight_recent": 0.5}}),
            ("0.75*", {}),
            ("1.0", {"fundamentals": {"pres_weight_recent": 1.0}}),
        ],
    ),
    (
        "market_weight",
        "weight on prediction-market odds in the blend (base 0.25)",
        [
            ("0.0", {"market_weight": 0.0}),
            ("0.125", {"market_weight": 0.125}),
            ("0.25*", {}),
            ("0.375", {"market_weight": 0.375}),
            ("0.5", {"market_weight": 0.5}),
        ],
    ),
    (
        "senate_responsiveness",
        "how much national swing reaches Senate fundamentals (base 1.0)",
        [
            ("0.5", {"national_environment": {"senate_responsiveness": 0.5}}),
            ("0.75", {"national_environment": {"senate_responsiveness": 0.75}}),
            ("1.0*", {}),
            ("1.25", {"national_environment": {"senate_responsiveness": 1.25}}),
            ("1.5", {"national_environment": {"senate_responsiveness": 1.5}}),
        ],
    ),
    (
        "generic/approval weights",
        "mix of generic ballot vs approval in national environment (base 0.6/0.4)",
        [
            ("0.8/0.2", {"national_environment": {"generic_weight": 0.8, "approval_weight": 0.2}}),
            ("0.6/0.4*", {}),
            ("0.4/0.6", {"national_environment": {"generic_weight": 0.4, "approval_weight": 0.6}}),
        ],
    ),
    (
        "tail_dof",
        "Student-t dof for polling error (base t(5), backtest-selected; audit item 8)",
        [
            ("gaussian", {"forecast": {"tail_dof": None}}),
            ("t(10)", {"forecast": {"tail_dof": 10}}),
            ("t(5)*", {}),
            ("t(3)", {"forecast": {"tail_dof": 3}}),
        ],
    ),
]


def main() -> None:
    print(f"Sensitivity sweep — {date.today()} (offline CSV pipeline)")

    approval_polls = _load_polls(PollType.APPROVAL, "votehub_approval.csv")
    gb_polls = _load_polls(PollType.GENERIC_BALLOT, "votehub_generic_ballot.csv")
    senate_polls = _load_polls(PollType.HEAD_TO_HEAD, "votehub_senate.csv")

    approval_payload = _approval_payload(approval_polls, trend_days=30)
    gb_payload = _generic_ballot_payload(gb_polls, trend_days=30)
    senate_payload = _senate_payload(senate_polls)

    approval_current = approval_payload.get("current")
    approval_net = approval_current.net_approval if approval_current else None
    gb_current = gb_payload.get("current")
    generic_margin = gb_current.margin if gb_current else None

    def run(overrides: dict) -> tuple[float, float]:
        fc = _senate_forecast_payload(
            senate_payload, approval_net, generic_margin,
            overrides=overrides, quiet=True,
        )
        return fc["dem_control_prob"], fc["mean_dem_seats"]

    base_prob, base_seats = run({})
    print(f"\nBaseline: P(Dem control) = {base_prob:.3f}, mean Dem seats = {base_seats:.2f}\n")

    results = []
    for knob, description, grid in SWEEPS:
        print(f"── {knob} — {description}")
        rows = []
        for label, overrides in grid:
            prob, seats = (base_prob, base_seats) if not overrides else run(overrides)
            delta = prob - base_prob
            rows.append({
                "value": label,
                "dem_control_prob": round(prob, 4),
                "delta_vs_base": round(delta, 4),
                "mean_dem_seats": round(seats, 2),
            })
            print(f"    {label:12} P(control)={prob:.3f}  Δ={delta:+.3f}  seats={seats:.2f}")
        spread = max(r["dem_control_prob"] for r in rows) - min(
            r["dem_control_prob"] for r in rows
        )
        results.append({
            "knob": knob,
            "description": description,
            "spread_across_grid": round(spread, 4),
            "grid": rows,
        })
        print(f"    {'spread':12} {spread:.3f}\n")

    results.sort(key=lambda r: -r["spread_across_grid"])
    payload = {
        "generated": datetime.now().astimezone().isoformat(),
        "baseline": {"dem_control_prob": base_prob, "mean_dem_seats": base_seats},
        "note": (
            "Δ P(Dem control) across each knob's grid, all else at baseline. "
            "Knobs sorted by spread — the widest spreads are where a hand-set "
            "choice moves the headline most and deserve empirical grounding first."
        ),
        "knobs": results,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Ranked by spread: {[r['knob'] for r in results]}")
    print(f"Wrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
