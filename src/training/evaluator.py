"""Evaluator — computes prediction error for a given parameter set.

Given a set of polling average parameters and a list of TrainingRace objects,
computes the weighted polling average for each race and measures error against
the actual election result.

This is the objective function that Optuna minimizes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

from src.training.data_loader import TrainingRace

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    """Summary metrics for a parameter set evaluated on training races."""

    rmse: float              # root mean squared error of vote share prediction
    mae: float               # mean absolute error
    mean_error: float        # signed bias (positive = model overestimates Dems)
    win_accuracy: float      # % of races where model correctly predicts winner
    n_races: int
    params: dict[str, float]

    def __str__(self) -> str:
        return (
            f"RMSE={self.rmse:.2f}  MAE={self.mae:.2f}  "
            f"Bias={self.mean_error:+.2f}  WinAcc={self.win_accuracy:.1%}  "
            f"N={self.n_races}"
        )


class PollingAverageEvaluator:
    """Evaluate polling average parameters against historical race results."""

    def __init__(self, training_races: list[TrainingRace]) -> None:
        self.training_races = training_races
        if not training_races:
            raise ValueError("No training races provided")

    def evaluate(self, params: dict[str, float]) -> EvaluationResult:
        """Compute error metrics for the given parameter set.

        Args:
            params: Dict of parameter name → value. Expected keys:
                recency_half_life_days, lv_weight_multiplier,
                rv_weight_multiplier, adults_weight_multiplier,
                partisan_bias_penalty, sample_size_exponent,
                pollster_quality_exponent.

        Returns:
            EvaluationResult with RMSE, MAE, bias, and win accuracy.
        """
        # Import here to avoid circular imports
        from src.models.polling_average import PollingAverageEngine, PollingAverageParams

        engine_params = PollingAverageParams(**{
            k: v for k, v in params.items()
            if k in PollingAverageParams.__dataclass_fields__
        })
        engine = PollingAverageEngine(params=engine_params)

        errors: list[float] = []
        correct_winner: list[bool] = []

        for race in self.training_races:
            # Determine choices — look for dem/rep candidate names or party labels
            dem_choices = _dem_choices(race)
            rep_choices = _rep_choices(race)
            choices = dem_choices + rep_choices

            result = engine.compute_average(race.polls, choices=choices if choices else None)

            if not result.averages:
                continue

            # Find predicted dem share
            pred_dem = _find_dem_share(result.averages, race.dem_candidate)
            if pred_dem is None:
                continue

            error = pred_dem - race.dem_two_party_share
            errors.append(error)

            # Win prediction: Dem wins if predicted dem share > 50
            predicted_winner = "D" if pred_dem > 50 else "R"
            correct_winner.append(predicted_winner == race.winner_party)

        if not errors:
            return EvaluationResult(
                rmse=999.0, mae=999.0, mean_error=0.0,
                win_accuracy=0.0, n_races=0, params=params,
            )

        errors_arr = np.array(errors)
        return EvaluationResult(
            rmse=round(float(np.sqrt(np.mean(errors_arr ** 2))), 3),
            mae=round(float(np.mean(np.abs(errors_arr))), 3),
            mean_error=round(float(np.mean(errors_arr)), 3),
            win_accuracy=round(float(np.mean(correct_winner)), 4),
            n_races=len(errors),
            params=params,
        )


def _dem_choices(race: TrainingRace) -> list[str]:
    """Get candidate name variants for the Dem candidate in this race."""
    if not race.dem_candidate:
        return ["Democrat", "Democratic", "DEM", "D"]
    last = race.dem_candidate.split()[-1]
    return [race.dem_candidate, last, "Democrat", "DEM", "D"]


def _rep_choices(race: TrainingRace) -> list[str]:
    """Get candidate name variants for the Rep candidate."""
    if not race.rep_candidate:
        return ["Republican", "GOP", "REP", "R"]
    last = race.rep_candidate.split()[-1]
    return [race.rep_candidate, last, "Republican", "GOP", "REP", "R"]


def _find_dem_share(averages: dict[str, float], dem_candidate: str) -> float | None:
    """Find the Dem candidate's share in an averages dict."""
    # Try exact match first
    if dem_candidate and dem_candidate in averages:
        return averages[dem_candidate]

    # Try last name
    if dem_candidate:
        last = dem_candidate.split()[-1]
        if last in averages:
            return averages[last]

    # Try party labels
    for label in ("Democrat", "Democratic", "DEM", "D"):
        if label in averages:
            return averages[label]

    return None
