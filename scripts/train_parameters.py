"""Train polling average engine parameters against historical data.

Downloads 538 archived polls and MIT election results, then runs Optuna
to find the parameter set that minimizes prediction error.

Trained parameters are saved to config/trained_params.json and
automatically loaded by the polling average engine on next run.

Usage:
    python scripts/train_parameters.py
    python scripts/train_parameters.py --n-trials 500
    python scripts/train_parameters.py --min-year 2014 --offices senate governor

Then start the MLflow UI to explore results:
    mlflow ui
    # Open http://localhost:5000
"""

from __future__ import annotations

import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train polling average engine parameters")
    parser.add_argument("--n-trials", type=int, default=200, help="Optuna trials (default: 200)")
    parser.add_argument("--min-year", type=int, default=2010, help="Earliest training cycle")
    parser.add_argument("--max-year", type=int, default=2022, help="Latest training cycle")
    parser.add_argument(
        "--offices", nargs="+", default=["senate", "governor"],
        choices=["senate", "governor", "house"],
        help="Which race types to train on",
    )
    parser.add_argument(
        "--lookback-days", type=int, default=60,
        help="Only use polls within this many days before election day",
    )
    parser.add_argument(
        "--experiment", type=str, default="polling-average-optimization",
        help="MLflow experiment name",
    )
    args = parser.parse_args()

    # Check dependencies
    try:
        import optuna
        import mlflow
    except ImportError:
        logger.error(
            "Missing dependencies. Install with:\n"
            "  pip install optuna mlflow"
        )
        raise SystemExit(1)

    from src.training.data_loader import TrainingDataLoader
    from src.training.optimizer import run_optimization

    logger.info("Loading training data...")
    loader = TrainingDataLoader(lookback_days=args.lookback_days)
    training_races = loader.load(
        offices=args.offices,
        min_year=args.min_year,
        max_year=args.max_year,
    )

    if not training_races:
        logger.error(
            "No training races loaded. Check that data sources are accessible "
            "and try running: python scripts/download_training_data.py first"
        )
        raise SystemExit(1)

    logger.info(f"Loaded {len(training_races)} training races")
    logger.info(f"Running {args.n_trials} Optuna trials...")
    logger.info("Track progress: mlflow ui  →  http://localhost:5000")

    best_params = run_optimization(
        training_races=training_races,
        n_trials=args.n_trials,
        experiment_name=args.experiment,
        save_best=True,
    )

    print("\n── Best Parameters ──────────────────────────────")
    for k, v in best_params.items():
        print(f"  {k}: {v:.4f}")
    print("\nSaved to config/trained_params.json")
    print("The polling average engine will use these automatically.")
    print("\nView full experiment results:\n  mlflow ui")


if __name__ == "__main__":
    main()
