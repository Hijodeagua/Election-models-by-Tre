"""Nightly table/chart refresh pipeline.

Runs the existing data refresh and Datawrapper publishing scripts with a safer
orchestration layer for local verification and GitHub Actions.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_CHART_ENV_MAP: dict[str, str] = {
    "approval": "DW_CHART_APPROVAL_ID",
    "approval_pro": "DW_CHART_APPROVAL_PRO_ID",
    "generic_ballot": "DW_CHART_GB_ID",
    "senate": "DW_CHART_SENATE_ID",
    "house_effects": "DW_CHART_HOUSE_EFFECTS_ID",
}
# Charts required when running "all" (approval_pro and house_effects are optional extras)
_REQUIRED_CHARTS = {"approval", "generic_ballot", "senate"}


def _run(command: list[str]) -> None:
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def _missing_publish_env(chart: str) -> list[str]:
    missing = []
    if not os.environ.get("DATAWRAPPER_API_TOKEN"):
        missing.append("DATAWRAPPER_API_TOKEN")
    charts_to_check = _REQUIRED_CHARTS if chart == "all" else {chart}
    for c in charts_to_check:
        env_var = _CHART_ENV_MAP.get(c)
        if env_var and not os.environ.get(env_var):
            missing.append(env_var)
    return missing


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh and publish nightly table/chart outputs.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify the pipeline without writing refreshed data or calling Datawrapper.",
    )
    parser.add_argument(
        "--skip-refresh",
        action="store_true",
        help="Use existing fallback data instead of refreshing external sources.",
    )
    parser.add_argument(
        "--chart",
        choices=["approval", "approval_pro", "generic_ballot", "senate", "house_effects", "all"],
        default="all",
        help="Limit publishing/verification to one output.",
    )
    parser.add_argument(
        "--trend-days",
        type=int,
        default=90,
        help="Days of trend history to include in trend outputs.",
    )
    args = parser.parse_args()

    python = sys.executable

    if not args.skip_refresh:
        refresh_cmd = [python, "scripts/refresh_data.py"]
        if args.dry_run:
            refresh_cmd.append("--dry-run")
        _run(refresh_cmd)

    publish_cmd = [
        python,
        "scripts/publish.py",
        "--chart",
        args.chart,
        "--trend-days",
        str(args.trend_days),
    ]

    if args.dry_run:
        publish_cmd.append("--dry-run")
    else:
        missing = _missing_publish_env(args.chart)
        if missing:
            names = ", ".join(missing)
            raise SystemExit(
                f"Missing environment variables required to publish '{args.chart}': {names}."
            )

    _run(publish_cmd)


if __name__ == "__main__":
    main()
