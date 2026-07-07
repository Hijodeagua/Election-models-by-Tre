"""Optuna hyperparameter optimizer + MLflow experiment tracker.

Finds the polling average engine parameters that minimize RMSE
against historical election results.

Usage:
    python scripts/train_parameters.py
    # Or programmatically:
    from src.training.optimizer import run_optimization
    best_params = run_optimization(training_races, n_trials=200)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.training.data_loader import TrainingRace
from src.training.evaluator import EvaluationResult, PollingAverageEvaluator

logger = logging.getLogger(__name__)

BEST_PARAMS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "trained_params.json"


class _NoOpMLflow:
    """Drop-in stand-in when mlflow isn't installed: every call is a no-op."""

    def __getattr__(self, name: str) -> Any:
        if name == "start_run":
            return self._start_run
        return lambda *a, **k: None

    def _start_run(self, *a: Any, **k: Any) -> Any:
        import contextlib

        return contextlib.nullcontext()

# Search space bounds for each parameter
PARAM_SPACE: dict[str, tuple[float, float]] = {
    "recency_half_life_days":    (5.0,  45.0),
    "lv_weight_multiplier":      (1.0,   3.0),
    "rv_weight_multiplier":      (0.5,   1.5),
    "adults_weight_multiplier":  (0.2,   1.0),
    "partisan_bias_penalty":     (0.1,   0.9),
    "sample_size_exponent":      (0.25,  0.75),
    "pollster_quality_exponent": (0.5,   2.0),
}


def run_optimization(
    training_races: list[TrainingRace],
    n_trials: int = 200,
    experiment_name: str = "polling-average-optimization",
    save_best: bool = True,
) -> dict[str, float]:
    """Run Optuna optimization with MLflow tracking.

    Args:
        training_races: Loaded from TrainingDataLoader.
        n_trials: Number of Optuna trials (200 is a good starting point).
        experiment_name: MLflow experiment name.
        save_best: If True, write best params to config/trained_params.json.

    Returns:
        Best parameter dict found.
    """
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError as exc:
        raise ImportError(
            "Optimization requires optuna. Install with: pip install optuna"
        ) from exc

    # MLflow is optional — experiment tracking is nice locally but should not
    # block training in CI, where nothing serves the tracking UI anyway.
    try:
        import mlflow
    except ImportError:
        mlflow = _NoOpMLflow()  # type: ignore[assignment]
        logger.info("mlflow not installed — skipping experiment tracking")

    evaluator = PollingAverageEvaluator(training_races)

    mlflow.set_experiment(experiment_name)

    def objective(trial: Any) -> float:
        params = {
            name: trial.suggest_float(name, low, high)
            for name, (low, high) in PARAM_SPACE.items()
        }

        result = evaluator.evaluate(params)

        # Log every trial to MLflow
        with mlflow.start_run(nested=True):
            mlflow.log_params(params)
            mlflow.log_metrics({
                "rmse": result.rmse,
                "mae": result.mae,
                "mean_error": result.mean_error,
                "win_accuracy": result.win_accuracy,
                "n_races": result.n_races,
            })

        return result.rmse

    logger.info(f"Starting Optuna optimization: {n_trials} trials on {len(training_races)} races")

    with mlflow.start_run(run_name=f"optuna-{n_trials}-trials"):
        mlflow.log_param("n_trials", n_trials)
        mlflow.log_param("n_training_races", len(training_races))

        study = optuna.create_study(
            direction="minimize",
            sampler=optuna.samplers.TPESampler(seed=42),
            pruner=optuna.pruners.MedianPruner(n_startup_trials=20),
        )
        study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

        best_params = study.best_params
        best_rmse = study.best_value

        # Evaluate best params fully for logging
        best_result = evaluator.evaluate(best_params)
        logger.info(f"Best result: {best_result}")

        mlflow.log_params({f"best_{k}": v for k, v in best_params.items()})
        mlflow.log_metrics({
            "best_rmse": best_rmse,
            "best_mae": best_result.mae,
            "best_win_accuracy": best_result.win_accuracy,
        })

        # Log parameter importance
        try:
            importances = optuna.importance.get_param_importances(study)
            mlflow.log_metrics({f"importance_{k}": v for k, v in importances.items()})
            logger.info("Parameter importances: " + str(importances))
        except Exception:
            pass

    if save_best:
        _save_best_params(best_params, best_result)

    logger.info(f"Optimization complete. Best RMSE: {best_rmse:.3f}")
    return best_params


def load_trained_params() -> dict[str, float] | None:
    """Load previously trained parameters, or None if not yet trained."""
    if BEST_PARAMS_PATH.exists():
        data = json.loads(BEST_PARAMS_PATH.read_text())
        return data.get("params")
    return None


def _save_best_params(params: dict[str, float], result: EvaluationResult) -> None:
    """Persist best parameters to config/trained_params.json."""
    output = {
        "params": params,
        "metrics": {
            "rmse": result.rmse,
            "mae": result.mae,
            "mean_error": result.mean_error,
            "win_accuracy": result.win_accuracy,
            "n_races": result.n_races,
        },
    }
    BEST_PARAMS_PATH.write_text(json.dumps(output, indent=2))
    logger.info(f"Saved best params to {BEST_PARAMS_PATH}")
