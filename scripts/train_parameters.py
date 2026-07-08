"""Train polling average engine parameters against historical data.

Downloads 538 archived polls and MIT election results, then runs Optuna
under a rolling-origin cross-validation protocol (see
src/training/cross_validation.py):

- selection minimizes the mean per-cycle RMSE across all cycles except the
  final holdout cycle;
- the holdout cycle is scored exactly once with the winning parameters;
- trained_params.json is written ONLY if the winner beats the hand-set
  defaults on the holdout (the pass/fail gate) — a failed gate leaves the
  defaults in production.

Trained parameters are saved to config/trained_params.json (with the CV
report embedded) and automatically loaded by the polling average engine.

Usage:
    python scripts/train_parameters.py
    python scripts/train_parameters.py --n-trials 500
    python scripts/train_parameters.py --min-year 2014 --offices senate governor
    python scripts/train_parameters.py --no-cv     # legacy pooled objective

MLflow tracking is optional; if installed, trials are logged as before.
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
        "--holdout-cycle", type=int, default=None,
        help="Cycle held out of selection entirely (default: most recent cycle)",
    )
    parser.add_argument(
        "--no-cv", action="store_true",
        help="Legacy pooled-RMSE objective without holdout gate (not recommended)",
    )
    args = parser.parse_args()

    try:
        import optuna  # noqa: F401  # availability check before optimization
    except ImportError as exc:
        logger.error("Missing dependency. Install with: pip install optuna")
        raise SystemExit(1) from exc

    from src.training.data_loader import TrainingDataLoader

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

    if args.no_cv:
        from src.training.optimizer import run_optimization

        best_params = run_optimization(
            training_races=training_races,
            n_trials=args.n_trials,
            save_best=True,
        )
        print("\n── Best Parameters (pooled objective — no holdout gate) ──")
        for k, v in best_params.items():
            print(f"  {k}: {v:.4f}")
        return

    from src.training.cross_validation import run_cv_optimization

    best_params, report = run_cv_optimization(
        training_races,
        n_trials=args.n_trials,
        holdout_cycle=args.holdout_cycle,
    )

    print("\n── Rolling-origin CV result ─────────────────────")
    print(f"  selection cycles : {report.selection_cycles}")
    print(f"  mean sel. RMSE   : {report.mean_selection_rmse:.3f}")
    print(f"  holdout cycle    : {report.holdout_cycle}")
    print(f"  holdout trained  : {report.holdout_trained}")
    print(f"  holdout default  : {report.holdout_default}")
    print(f"  gate             : {'PASSED' if report.passed_gate else 'FAILED'} — {report.gate_reason}")
    if report.passed_gate:
        print("\n── Best Parameters ──────────────────────────────")
        for k, v in best_params.items():
            print(f"  {k}: {v:.4f}")
        print("\nSaved to config/trained_params.json (with CV report).")
    else:
        print("\nGate failed — trained_params.json NOT written; defaults stay in production.")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
