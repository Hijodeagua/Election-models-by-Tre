"""Pull the state-level economic panel (Tier 1) from FRED.

State series are the only economic data that can legitimately enter the race
model: they vary per state *and* per month, so a coefficient is fitted against
races rather than against the five cycles the poll archive covers. National
series (mortgage rates, CPI, gas) take one value per election — useful for
charts, not as features.

Outputs:
  data/raw/fred/<series>.csv          one cache file per series (vintage-suffixed)
  data/processed/state_economics.csv  tidy long panel: state, concept, date, value
  data/processed/state_economics_aligned.csv   with --election-date: one row per
      state × concept as of that date, plus the 12-month change

Run --probe first. FRED's state naming conventions (TXUR, TXSTHPI, …) do not
hold for every state and concept, and FRED renames series; the probe tells you
which of the ~255 IDs are real before you pull full histories.

Usage:
    python scripts/download_economic_data.py --probe
    python scripts/download_economic_data.py
    python scripts/download_economic_data.py --concepts unemployment_rate house_price_index
    python scripts/download_economic_data.py --states GA IA ME MI NH NC OH TX
    python scripts/download_economic_data.py --election-date 2026-11-03
    python scripts/download_economic_data.py --realtime 2022-11-08   # needs FRED_API_KEY

A key is optional: without one this uses FRED's keyless CSV export (current
vintage only). With FRED_API_KEY set it uses the API, which is the only way to
get ALFRED vintages — required for any backtest, since revised data leaks the
future into a past election.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._console import enable_utf8_output

enable_utf8_output()

from config.settings import settings
from src.data.fred import (
    STATE_CONCEPTS,
    FredClient,
    change_over,
    state_series_ids,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PANEL_PATH = PROJECT_ROOT / "data" / "processed" / "state_economics.csv"
ALIGNED_PATH = PROJECT_ROOT / "data" / "processed" / "state_economics_aligned.csv"


def _parse_date(raw: str) -> date:
    return datetime.strptime(raw, "%Y-%m-%d").date()


def main() -> None:
    parser = argparse.ArgumentParser(description="Download state-level economic series")
    parser.add_argument(
        "--concepts", nargs="+", default=None, choices=sorted(STATE_CONCEPTS),
        help=f"Default: all of {', '.join(sorted(STATE_CONCEPTS))}",
    )
    parser.add_argument(
        "--states", nargs="+", default=None,
        help="Two-letter abbreviations (default: all 50 + DC)",
    )
    parser.add_argument(
        "--probe", action="store_true",
        help="Report which series IDs resolve, then exit without writing the panel",
    )
    parser.add_argument("--force", action="store_true", help="Re-download cached series")
    parser.add_argument(
        "--realtime", default=None, metavar="YYYY-MM-DD",
        help="ALFRED vintage: values as published on this date (needs FRED_API_KEY). "
             "Use for backtests — current-vintage data is revised and leaks the future.",
    )
    parser.add_argument(
        "--election-date", default=None, metavar="YYYY-MM-DD",
        help="Also write a race-joinable snapshot: latest value per state/concept "
             "on or before this date, plus the 12-month change",
    )
    args = parser.parse_args()

    realtime = _parse_date(args.realtime) if args.realtime else None
    try:
        client = FredClient(realtime=realtime)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    ids = state_series_ids(args.concepts, args.states)
    mode = "API (vintage-capable)" if client.is_configured else "keyless CSV (current vintage)"
    logger.info("FRED transport: %s", mode)
    if not client.is_configured:
        logger.info(
            "No FRED_API_KEY set — fine for charts. Get a free key at "
            "https://fredaccount.stlouisfed.org/apikeys for vintage (ALFRED) data."
        )
    logger.info("%d series across %d concepts", len(ids), len({c for _, c in ids}))

    if args.probe:
        results = client.probe(sorted(set(ids.values())))
        ok = [s for s, r in results.items() if r.startswith("ok")]
        print("\n── Probe ────────────────────────────────────────────────")
        for series_id, result in sorted(results.items()):
            print(f"  {series_id:14} {result}")
        print(f"\n  {len(ok)}/{len(results)} series resolved.")
        bad = [s for s in results if s not in ok]
        if bad:
            print("  Unresolved: " + ", ".join(sorted(bad)))
            print("  " + _diagnose([results[s] for s in bad], client.is_configured))
        return

    data, failures = client.fetch_panel(sorted(set(ids.values())), force=args.force)

    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with PANEL_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["state", "concept", "series_id", "date", "value"])
        for (abbr, concept), series_id in sorted(ids.items()):
            for obs in data.get(series_id, []):
                if obs.value is None:
                    continue
                writer.writerow([abbr, concept, series_id, obs.date.isoformat(), obs.value])
                rows += 1

    print("\n── State economic panel ─────────────────────────────────")
    print(f"  transport      : {mode}")
    if realtime:
        print(f"  vintage        : {realtime}")
    print(f"  series fetched : {len(data)}/{len(set(ids.values()))}")
    print(f"  rows written   : {rows:,} → {PANEL_PATH.relative_to(PROJECT_ROOT)}")

    for concept in sorted({c for _, c in ids}):
        spec = STATE_CONCEPTS[concept]
        dated = [
            obs.date
            for (abbr, c), sid in ids.items()
            if c == concept
            for obs in data.get(sid, [])
            if obs.value is not None
        ]
        coverage = f"{min(dated)}–{max(dated)}" if dated else "no data"
        print(f"    {concept:20} {spec.frequency:10} {coverage}")

    if failures:
        print(f"\n  {len(failures)} series failed:")
        for failure in failures[:10]:
            print(f"    {failure.series_id}: {failure.reason[:90]}")
        if len(failures) > 10:
            print(f"    … and {len(failures) - 10} more")
        print("  Re-run with --probe to see the full list.")

    if args.election_date:
        cutoff = _parse_date(args.election_date)
        written = _write_aligned(ids, data, cutoff)
        print(
            f"\n  aligned to {cutoff}: {written} rows → "
            f"{ALIGNED_PATH.relative_to(PROJECT_ROOT)}"
        )
        print(
            "  NOTE: dates are observation dates, not publication dates. State "
            "unemployment for October is published ~3 weeks later, so it is not\n"
            "  knowable on election day — use --realtime for a backtest."
        )

    print(f"\n  cache: {client.cache_dir.relative_to(PROJECT_ROOT)}")


def _diagnose(reasons: list[str], has_key: bool) -> str:
    """Tell a blocked network apart from a wrong series ID.

    Both surface as a failed probe, but the fixes are opposite: one is your
    connection or key, the other is the ID in STATE_CONCEPTS.
    """
    blob = " ".join(reasons).lower()
    network = any(
        marker in blob
        for marker in ("403", "forbidden", "timeout", "connect", "transport", "ssl", "proxy")
    )
    if network and not has_key:
        return (
            "These look like connection or access failures, not bad IDs — FRED was "
            "unreachable or refused the keyless endpoint. Set FRED_API_KEY in .env "
            "and re-probe before editing any series ID."
        )
    if network:
        return (
            "These look like connection failures rather than bad IDs (a proxy, VPN or "
            "rate limit). Re-probe before editing any series ID."
        )
    return (
        "These read as unknown series: fix them in src/data/fred.py:STATE_CONCEPTS "
        "(search fred.stlouisfed.org for the state's actual ID)."
    )


def _write_aligned(
    ids: dict[tuple[str, str], str], data: dict, cutoff: date
) -> int:
    """One row per state × concept: level at the cutoff plus its 12-month change."""
    ALIGNED_PATH.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with ALIGNED_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "state", "concept", "series_id", "as_of_date", "value",
            "year_ago_date", "year_ago_value", "change_12m", "change_pct_12m",
        ])
        for (abbr, concept), series_id in sorted(ids.items()):
            observations = data.get(series_id)
            if not observations:
                continue
            now, prior = change_over(observations, cutoff, months=12)
            if now is None or now.value is None:
                continue
            change = pct = None
            if prior is not None and prior.value is not None:
                change = round(now.value - prior.value, 4)
                if prior.value:
                    pct = round(100.0 * change / prior.value, 4)
            writer.writerow([
                abbr, concept, series_id, now.date.isoformat(), now.value,
                prior.date.isoformat() if prior else "",
                prior.value if prior else "",
                change if change is not None else "",
                pct if pct is not None else "",
            ])
            written += 1
    return written


if __name__ == "__main__":
    if not settings.raw_data_dir.exists():
        settings.raw_data_dir.mkdir(parents=True, exist_ok=True)
    main()
