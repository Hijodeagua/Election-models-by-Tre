"""Rolling-origin cross-validation for polling-average parameter training.

Locks the backtest protocol the methodology review calls for (gap 5) and the
July 2026 audit prioritizes (item 5):

- **Selection**: Optuna minimizes the *mean per-cycle RMSE* across every
  election cycle except the final holdout cycle. Averaging per cycle (not per
  race) keeps one poll-rich cycle from dominating the objective, and scoring
  each cycle separately is the rolling-origin discipline — a parameter set
  must work across environments, not just on the pooled race soup.
- **Holdout**: the most recent cycle is never seen during selection. Best
  params are evaluated on it exactly once; those out-of-cycle metrics ship
  inside ``trained_params.json``.
- **Gate**: trained parameters are saved only if they beat the hand-set
  defaults on the holdout cycle RMSE and keep win accuracy above a floor.
  A failed gate keeps the defaults in production.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.training.data_loader import TrainingRace
from src.training.evaluator import EvaluationResult, PollingAverageEvaluator

logger = logging.getLogger(__name__)

TRAINED_PARAMS_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "trained_params.json"
)

# Gate thresholds: trained params must not lose to the defaults on the holdout
# cycle by more than this RMSE margin, and must keep win accuracy above the
# floor (METHODOLOGY_REVIEW "minimum publishable" gate is Brier-based; RMSE +
# call accuracy is the analogue for a margin objective).
GATE_RMSE_TOLERANCE = 0.0
GATE_WIN_ACCURACY_FLOOR = 0.75


@dataclass
class CVReport:
    """Everything a reviewer needs to judge a training run."""

    selection_cycles: list[int]
    holdout_cycle: int
    n_races_total: int
    # Per-selection-cycle metrics of the winning parameter set
    per_cycle: dict[int, dict[str, float]] = field(default_factory=dict)
    mean_selection_rmse: float = 0.0
    # Out-of-cycle metrics on the untouched holdout cycle
    holdout_trained: dict[str, float] = field(default_factory=dict)
    holdout_default: dict[str, float] = field(default_factory=dict)
    passed_gate: bool = False
    gate_reason: str = ""


def split_by_cycle(races: list[TrainingRace]) -> dict[int, list[TrainingRace]]:
    """Group training races by election cycle (year)."""
    by_cycle: dict[int, list[TrainingRace]] = {}
    for race in races:
        by_cycle.setdefault(race.year, []).append(race)
    return dict(sorted(by_cycle.items()))


def _metrics(result: EvaluationResult) -> dict[str, float]:
    return {
        "rmse": result.rmse,
        "mae": result.mae,
        "mean_error": result.mean_error,
        "win_accuracy": result.win_accuracy,
        "n_races": result.n_races,
    }


def mean_cycle_rmse(
    params: dict[str, float], evaluators: dict[int, PollingAverageEvaluator]
) -> float:
    """Mean RMSE across cycles, equal weight per cycle. Cycles where no race
    could be scored are skipped rather than polluting the mean with the
    999-sentinel."""
    rmses = []
    for evaluator in evaluators.values():
        result = evaluator.evaluate(params)
        if result.n_races > 0:
            rmses.append(result.rmse)
    if not rmses:
        return 999.0
    return float(sum(rmses) / len(rmses))


def run_cv_optimization(
    races: list[TrainingRace],
    n_trials: int = 200,
    holdout_cycle: int | None = None,
    save_path: Path | None = None,
    seed: int = 42,
) -> tuple[dict[str, float], CVReport]:
    """Rolling-origin CV parameter search with a holdout gate.

    Args:
        races: All training races (multiple cycles required).
        n_trials: Optuna trial budget.
        holdout_cycle: Cycle to hold out entirely from selection.
            Default: the most recent cycle present.
        save_path: Where to write trained_params.json on a passed gate
            (default: config/trained_params.json). Nothing is written when
            the gate fails.
        seed: Sampler seed for reproducibility.

    Returns:
        (best_params, CVReport). ``best_params`` is the Optuna winner whether
        or not the gate passed; check ``report.passed_gate`` before using it.
    """
    import optuna

    from src.models.polling_average import PollingAverageParams
    from src.training.optimizer import PARAM_SPACE

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    by_cycle = split_by_cycle(races)
    if len(by_cycle) < 3:
        raise ValueError(
            f"Rolling-origin CV needs at least 3 cycles, got {sorted(by_cycle)} — "
            "widen --min-year/--max-year."
        )

    holdout_cycle = holdout_cycle or max(by_cycle)
    if holdout_cycle not in by_cycle:
        raise ValueError(f"Holdout cycle {holdout_cycle} not in data ({sorted(by_cycle)})")

    selection_cycles = [c for c in by_cycle if c != holdout_cycle]
    selection_evaluators = {
        c: PollingAverageEvaluator(by_cycle[c]) for c in selection_cycles
    }
    holdout_evaluator = PollingAverageEvaluator(by_cycle[holdout_cycle])

    logger.info(
        "CV selection on cycles %s (%d races), holdout %d (%d races)",
        selection_cycles,
        sum(len(by_cycle[c]) for c in selection_cycles),
        holdout_cycle,
        len(by_cycle[holdout_cycle]),
    )

    def objective(trial: Any) -> float:
        params = {
            name: trial.suggest_float(name, low, high)
            for name, (low, high) in PARAM_SPACE.items()
        }
        return mean_cycle_rmse(params, selection_evaluators)

    study = optuna.create_study(
        direction="minimize", sampler=optuna.samplers.TPESampler(seed=seed)
    )
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    best_params = study.best_params

    # Out-of-cycle evaluation — the only time the holdout is touched.
    holdout_trained = holdout_evaluator.evaluate(best_params)
    default_params = {
        k: v
        for k, v in PollingAverageParams().__dict__.items()
        if k in PARAM_SPACE
    }
    holdout_default = holdout_evaluator.evaluate(default_params)

    report = CVReport(
        selection_cycles=selection_cycles,
        holdout_cycle=holdout_cycle,
        n_races_total=len(races),
        per_cycle={
            c: _metrics(ev.evaluate(best_params))
            for c, ev in selection_evaluators.items()
        },
        mean_selection_rmse=round(study.best_value, 3),
        holdout_trained=_metrics(holdout_trained),
        holdout_default=_metrics(holdout_default),
    )

    # Gate
    if holdout_trained.n_races == 0:
        report.gate_reason = "no holdout races could be scored"
    elif holdout_trained.rmse > holdout_default.rmse + GATE_RMSE_TOLERANCE:
        report.gate_reason = (
            f"trained RMSE {holdout_trained.rmse:.2f} does not beat default "
            f"{holdout_default.rmse:.2f} on holdout cycle {holdout_cycle}"
        )
    elif holdout_trained.win_accuracy < GATE_WIN_ACCURACY_FLOOR:
        report.gate_reason = (
            f"holdout win accuracy {holdout_trained.win_accuracy:.1%} below "
            f"floor {GATE_WIN_ACCURACY_FLOOR:.0%}"
        )
    else:
        report.passed_gate = True
        report.gate_reason = (
            f"beats default on holdout {holdout_cycle} "
            f"(RMSE {holdout_trained.rmse:.2f} vs {holdout_default.rmse:.2f}, "
            f"win acc {holdout_trained.win_accuracy:.1%})"
        )

    logger.info("Gate %s: %s", "PASSED" if report.passed_gate else "FAILED", report.gate_reason)

    if report.passed_gate:
        path = save_path or TRAINED_PARAMS_PATH
        payload = {
            "params": best_params,
            "protocol": "rolling-origin CV, per-cycle mean RMSE, final-cycle holdout",
            "cv": asdict(report),
        }
        path.write_text(json.dumps(payload, indent=2) + "\n")
        logger.info("Saved trained params + CV report to %s", path)

    return best_params, report
