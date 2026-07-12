"""Fit the generic-ballot → House-seats conversion from history (audit item 8).

Replaces the hand-set SEATS_PER_MARGIN_POINT=5.5 / BASELINE_DEM_SEATS=218 with
an OLS fit of Dem seats on the national two-party vote margin over 1998–2024,
including the uncertainty the old constants lacked:

    seats ≈ intercept + slope × (Dem−Rep two-party margin, pts)

The residual SD becomes the published seat band, and the slope/intercept
standard errors are stored so a future cycle-aware model can widen further.

Known limitation, documented rather than hidden: the model applies a *polling*
generic-ballot margin to a curve fitted on *actual vote* margins. The
historical generic-ballot-overstates-Democrats bias is NOT corrected here —
that needs archived GB averages per cycle (future work; see
METHODOLOGY_AUDIT_2026-07.md).

Usage:
    python scripts/fit_seat_conversion.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

HISTORY_PATH = PROJECT_ROOT / "config" / "house_national_history.json"
OUTPUT_PATH = PROJECT_ROOT / "config" / "seat_conversion.json"


def main() -> None:
    history = json.loads(HISTORY_PATH.read_text())
    cycles = history["cycles"]

    margin = np.array([2.0 * c["dem_two_party_pct"] - 100.0 for c in cycles])
    seats = np.array([float(c["dem_seats"]) for c in cycles])
    n = len(cycles)

    # OLS with standard errors
    x = np.column_stack([np.ones(n), margin])
    coef, *_ = np.linalg.lstsq(x, seats, rcond=None)
    intercept, slope = float(coef[0]), float(coef[1])
    resid = seats - x @ coef
    dof = n - 2
    resid_sd = float(np.sqrt(resid @ resid / dof))
    cov = resid_sd**2 * np.linalg.inv(x.T @ x)
    intercept_se, slope_se = float(np.sqrt(cov[0, 0])), float(np.sqrt(cov[1, 1]))
    r2 = 1.0 - float(resid @ resid) / float(((seats - seats.mean()) ** 2).sum())

    result = {
        "_meta": {
            "description": (
                "OLS fit of Dem House seats on national two-party vote margin. "
                "Loaded by GenericBallotModel in place of the hand-set "
                "5.5/218 constants; resid_sd drives the published seat band."
            ),
            "fitted": datetime.now().astimezone().isoformat(),
            "source": "config/house_national_history.json",
            "caveat": (
                "Fitted on actual vote margins; the generic-ballot polling "
                "margin fed into it retains its historical pro-Dem bias. "
                "Seat outputs remain labeled illustrative/directional."
            ),
        },
        "n_cycles": n,
        "years": [c["year"] for c in cycles],
        "seats_per_margin_point": round(slope, 3),
        "slope_se": round(slope_se, 3),
        "baseline_dem_seats": round(intercept, 1),
        "intercept_se": round(intercept_se, 2),
        "resid_sd_seats": round(resid_sd, 2),
        "r_squared": round(r2, 3),
    }
    OUTPUT_PATH.write_text(json.dumps(result, indent=2) + "\n")

    print(f"Fit on {n} cycles ({cycles[0]['year']}–{cycles[-1]['year']}):")
    print(f"  seats = {intercept:.1f} (±{intercept_se:.1f}) "
          f"+ {slope:.2f} (±{slope_se:.2f}) × margin")
    print(f"  residual SD = {resid_sd:.1f} seats, R² = {r2:.3f}")
    print("  (old hand-set values: 218 + 5.5 × margin, no uncertainty)")
    print(f"Wrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
