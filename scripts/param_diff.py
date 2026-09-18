"""Before/after diff of the published forecast under two parameter sets.

Trained parameters land silently: production engines are built bare
(``run_models._build_engine_from_polls``), so ``PollingAverageParams.load_trained()``
picks up ``config/trained_params.json`` the moment it exists and every published
number moves without a code change. This script makes that move visible before
you commit it.

Both arms run the *production* export path (the same `_*_payload` functions
`export_json.py` writes from, as `sensitivity_sweep.py` does), with the only
difference being which parameter set the engine loads. It writes nothing to
`web/public/data/` — it is read-only apart from an optional `--json` report.

Beyond the headline numbers it reports the two diagnostics that a shorter
recency half-life puts at risk:

- **effective N** (Kish: ``(Σw)² / Σw²``) — how many polls actually carry the
  average. A 5-day half-life on a feed whose newest poll is 12 days old can
  collapse 400 polls onto a handful.
- **trend volatility** — mean absolute day-over-day move in the published
  trend. This is the "jumpier chart" cost, in points per day.

Usage:
    python scripts/param_diff.py
    python scripts/param_diff.py --after config/trained_params_wide.json
    python scripts/param_diff.py --before config/trained_params.json \
        --after config/trained_params_wide.json
    python scripts/param_diff.py --json data/processed/param_diff.json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._console import enable_utf8_output

enable_utf8_output()

from scripts.export_json import (
    _approval_payload,
    _generic_ballot_payload,
    _load_polls,
    _senate_forecast_payload,
    _senate_payload,
)
from src.data.base import Poll, PollType
from src.models.approval import PresidentialApprovalModel
from src.models.generic_ballot import GENERIC_BALLOT_CHOICES
from src.models.polling_average import PollingAverageEngine, PollingAverageParams

# BOUND_TOLERANCE is shared so the diff and the CV report flag the same pins.
from src.training.cross_validation import BOUND_TOLERANCE
from src.training.optimizer import PARAM_SPACE

DEFAULT_AFTER = PROJECT_ROOT / "config" / "trained_params.json"
TREND_DAYS = 60


# ── Parameter sets ────────────────────────────────────────────────────────────

def _load_param_set(spec: str) -> tuple[PollingAverageParams, dict[str, float]]:
    """Resolve a CLI spec to (params, trained-value dict).

    ``defaults`` gives the hand-set dataclass defaults; anything else is read as
    a trained_params.json path (either ``{"params": {...}}`` or a flat dict).
    """
    if spec == "defaults":
        defaults = PollingAverageParams()
        return defaults, {k: getattr(defaults, k) for k in PARAM_SPACE}

    path = Path(spec)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        raise SystemExit(f"Parameter file not found: {path}")

    data = json.loads(path.read_text())
    values = data.get("params", data)
    unknown = set(values) - set(PollingAverageParams.__dataclass_fields__)
    if unknown:
        raise SystemExit(f"{path.name} has unknown parameter keys: {sorted(unknown)}")
    return PollingAverageParams(**values), values


@contextmanager
def _serving(params: PollingAverageParams) -> Iterator[None]:
    """Make every bare-constructed engine serve ``params`` for this block.

    Production never passes params explicitly, so patching the loader is the
    only way to swap them without editing the export path.
    """
    original = PollingAverageParams.__dict__["load_trained"]
    PollingAverageParams.load_trained = classmethod(lambda cls: params)  # type: ignore[assignment]
    try:
        yield
    finally:
        PollingAverageParams.load_trained = original  # type: ignore[assignment]


# ── Diagnostics ───────────────────────────────────────────────────────────────

def _effective_n(polls: list[Poll], choices: list[str] | None) -> dict[str, Any]:
    """Kish effective sample size over the poll weights, plus concentration.

    ``top_weight_share`` is the single heaviest poll's share of total weight —
    the blunt read on "is one poll driving this average".
    """
    if not polls:
        return {"n_polls": 0, "n_eff": 0.0, "top_weight_share": None}

    engine = PollingAverageEngine()
    result = engine.compute_average(polls, choices=choices)
    weights = [record.weight for record in result.weighted_polls]
    total = sum(weights)
    if not weights or total <= 0:
        return {"n_polls": result.num_polls, "n_eff": 0.0, "top_weight_share": None}

    n_eff = total**2 / sum(w**2 for w in weights)
    return {
        "n_polls": result.num_polls,
        "n_eff": round(n_eff, 2),
        "top_weight_share": round(max(weights) / total, 4),
        "top_polls": [
            {
                "pollster": record.poll.pollster,
                "end_date": record.poll.end_date.isoformat(),
                "weight_share": round(record.weight / total, 4),
            }
            for record in sorted(result.weighted_polls, key=lambda r: -r.weight)[:5]
        ],
    }


def _volatility(values: list[float]) -> float | None:
    """Mean absolute day-over-day move in a published trend series."""
    if len(values) < 2:
        return None
    steps = [abs(b - a) for a, b in zip(values[:-1], values[1:], strict=True)]
    return round(sum(steps) / len(steps), 3)


def _ci_width(ci: tuple[float, float] | None) -> float | None:
    return round(ci[1] - ci[0], 2) if ci else None


# ── One arm of the diff ───────────────────────────────────────────────────────

def _run_arm(
    params: PollingAverageParams,
    approval_polls: list[Poll],
    gb_polls: list[Poll],
    senate_polls: list[Poll],
) -> dict[str, Any]:
    """Run the full production export path under one parameter set."""
    with _serving(params):
        approval = _approval_payload(approval_polls, trend_days=TREND_DAYS)
        gb = _generic_ballot_payload(gb_polls, trend_days=TREND_DAYS)
        senate = _senate_payload(senate_polls)

        approval_now = approval.get("current")
        gb_now = gb.get("current")
        forecast = _senate_forecast_payload(
            senate,
            approval_now.net_approval if approval_now else None,
            gb_now.margin if gb_now else None,
            quiet=True,
        )

        # Effective N is measured on the same pools the models screen to, so it
        # matches the published averages rather than the raw feed.
        screened_approval = PresidentialApprovalModel()._presidential_polls(approval_polls)
        approval_diag = _effective_n(screened_approval, ["Approve", "Disapprove"])
        gb_diag = _effective_n(
            [p for p in gb_polls if p.poll_type == PollType.GENERIC_BALLOT],
            GENERIC_BALLOT_CHOICES,
        )

    return {
        "approval": {
            "approve": approval_now.approve if approval_now else None,
            "disapprove": approval_now.disapprove if approval_now else None,
            "net": approval_now.net_approval if approval_now else None,
            "ci_width_approve": _ci_width(approval_now.ci_approve if approval_now else None),
            "volatility": _volatility([s.net_approval for s in approval["trend"]]),
            **approval_diag,
        },
        "generic_ballot": {
            "dem": gb_now.dem_pct if gb_now else None,
            "rep": gb_now.rep_pct if gb_now else None,
            "margin": gb_now.margin if gb_now else None,
            "dem_seats": gb_now.estimated_dem_seats if gb_now else None,
            "ci_width_dem": _ci_width(gb_now.ci_dem if gb_now else None),
            "volatility": _volatility([s.margin for s in gb["trend"]]),
            **gb_diag,
        },
        "forecast": {
            "dem_control_prob": forecast["dem_control_prob"],
            "mean_dem_seats": forecast["mean_dem_seats"],
            "median_dem_seats": forecast.get("median_dem_seats"),
        },
        "races": {
            race["state"]: {
                "num_polls": race.get("num_polls"),
                "dem_margin": race.get("dem_margin"),
                "dem_win_prob": race.get("dem_win_prob"),
            }
            for race in senate["races"]
        },
    }


# ── Reporting ─────────────────────────────────────────────────────────────────

def _fmt(value: float | None, spec: str = "+.2f") -> str:
    if value is not None:
        return format(value, spec)
    # Keep the column aligned when a metric is unavailable (e.g. the generic
    # ballot ships no CI today) by padding the dash to the spec's width.
    width = spec.lstrip("+").split(".")[0]
    return "—".rjust(int(width)) if width.isdigit() else "—"


def _delta(before: float | None, after: float | None, spec: str = "+.2f") -> str:
    if before is None or after is None:
        return "—"
    return format(after - before, spec)


def _bound_flag(name: str, value: float) -> str:
    """Mark a value pinned against its search-space bound."""
    low, high = PARAM_SPACE[name]
    margin = (high - low) * BOUND_TOLERANCE
    if value <= low + margin:
        return f"  ← at floor {low:g}"
    if value >= high - margin:
        return f"  ← at ceiling {high:g}"
    return ""


def _print_params(before: dict[str, float], after: dict[str, float]) -> None:
    print("\n── Parameters ───────────────────────────────────────────────────")
    print(f"  {'param':28} {'before':>10} {'after':>10} {'Δ':>10}")
    for name in PARAM_SPACE:
        b, a = before.get(name), after.get(name)
        flag = _bound_flag(name, a) if a is not None else ""
        print(
            f"  {name:28} {_fmt(b, '10.4f')} {_fmt(a, '10.4f')} "
            f"{_delta(b, a, '+10.4f')}{flag}"
        )


def _print_feed(title: str, rows: list[tuple[str, str]], before: dict, after: dict) -> None:
    print(f"\n── {title} ──────────────────────────────────────────────────")
    print(f"  {'metric':22} {'before':>10} {'after':>10} {'Δ':>10}")
    for key, spec in rows:
        b, a = before.get(key), after.get(key)
        # Deltas carry the row's own precision — a 4dp probability must not be
        # reported as "-0.00".
        print(f"  {key:22} {_fmt(b, spec)} {_fmt(a, spec)} {_delta(b, a, '+' + spec)}")


def _print_heaviest(feed: str, before: dict, after: dict) -> None:
    """Name the polls carrying each arm — the concrete face of a low effective N."""
    for label, arm in (("before", before), ("after", after)):
        top = arm.get("top_polls") or []
        if not top:
            continue
        heaviest = ", ".join(
            f"{p['pollster']} {p['end_date']} ({p['weight_share']:.1%})" for p in top[:3]
        )
        print(f"  heaviest {feed} polls ({label}): {heaviest}")


def _print_races(before: dict, after: dict) -> None:
    print("\n── Senate races (sorted by |Δ P(D win)|) ────────────────────────")
    print(f"  {'state':18} {'polls':>6} {'margin →':>18} {'P(D win) →':>20}")
    states = sorted(
        set(before) | set(after),
        key=lambda s: -abs(
            (after.get(s, {}).get("dem_win_prob") or 0)
            - (before.get(s, {}).get("dem_win_prob") or 0)
        ),
    )
    for state in states:
        b, a = before.get(state, {}), after.get(state, {})
        bp, ap = b.get("dem_win_prob"), a.get("dem_win_prob")
        flip = ""
        if bp is not None and ap is not None and (bp >= 0.5) != (ap >= 0.5):
            flip = "  ⚑ FLIP"
        print(
            f"  {state:18} {a.get('num_polls', b.get('num_polls', 0)):>6} "
            f"{_fmt(b.get('dem_margin'))} → {_fmt(a.get('dem_margin'))}   "
            f"{_fmt(bp, '.3f')} → {_fmt(ap, '.3f')} ({_delta(bp, ap, '+.3f')}){flip}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diff the published forecast between two polling-average parameter sets"
    )
    parser.add_argument(
        "--before", default="defaults",
        help="Baseline arm: 'defaults' (hand-set) or a trained_params.json path",
    )
    parser.add_argument(
        "--after", default=str(DEFAULT_AFTER),
        help="Candidate arm: a trained_params.json path (default: config/trained_params.json)",
    )
    parser.add_argument("--json", dest="json_out", default=None, help="Write the report here")
    args = parser.parse_args()

    before_params, before_values = _load_param_set(args.before)
    after_params, after_values = _load_param_set(args.after)

    print(f"Parameter diff — {date.today()} (offline CSV pipeline)")
    print(f"  before : {args.before}")
    print(f"  after  : {args.after}")

    approval_polls = _load_polls(PollType.APPROVAL, "votehub_approval.csv")
    gb_polls = _load_polls(PollType.GENERIC_BALLOT, "votehub_generic_ballot.csv")
    senate_polls = _load_polls(PollType.HEAD_TO_HEAD, "votehub_senate.csv")

    before_arm = _run_arm(before_params, approval_polls, gb_polls, senate_polls)
    after_arm = _run_arm(after_params, approval_polls, gb_polls, senate_polls)

    _print_params(before_values, after_values)

    feed_rows = [
        ("n_polls", "10.0f"),
        ("n_eff", "10.2f"),
        ("top_weight_share", "10.4f"),
        ("volatility", "10.3f"),
    ]
    _print_feed(
        "Approval",
        [("approve", "10.2f"), ("disapprove", "10.2f"), ("net", "10.2f"),
         ("ci_width_approve", "10.2f"), *feed_rows],
        before_arm["approval"], after_arm["approval"],
    )
    _print_heaviest("approval", before_arm["approval"], after_arm["approval"])

    _print_feed(
        "Generic ballot",
        [("dem", "10.2f"), ("rep", "10.2f"), ("margin", "10.2f"),
         ("dem_seats", "10.0f"), ("ci_width_dem", "10.2f"), *feed_rows],
        before_arm["generic_ballot"], after_arm["generic_ballot"],
    )
    _print_heaviest("generic ballot", before_arm["generic_ballot"], after_arm["generic_ballot"])

    _print_races(before_arm["races"], after_arm["races"])

    _print_feed(
        "Headline forecast",
        [("dem_control_prob", "10.4f"), ("mean_dem_seats", "10.2f"),
         ("median_dem_seats", "10.1f")],
        before_arm["forecast"], after_arm["forecast"],
    )

    if args.json_out:
        out = Path(args.json_out)
        if not out.is_absolute():
            out = PROJECT_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "generated": datetime.now().astimezone().isoformat(),
                    "before": {"spec": args.before, "params": before_values, **before_arm},
                    "after": {"spec": args.after, "params": after_values, **after_arm},
                },
                indent=2,
                default=_json_default,
            )
            + "\n"
        )
        print(f"\nWrote {out}")


def _json_default(obj: object) -> object:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, date | datetime):
        return obj.isoformat()
    raise TypeError(f"Not JSON serialisable: {type(obj)!r}")


if __name__ == "__main__":
    main()
