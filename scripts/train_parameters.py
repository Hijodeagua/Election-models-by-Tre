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
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._console import enable_utf8_output

enable_utf8_output()

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
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Optuna sampler seed. Re-run with several seeds to check whether "
             "the winner is a real optimum or a flat-objective coin flip.",
    )
    parser.add_argument(
        "--save-path", default=None,
        help="Write the passed run here instead of config/trained_params.json "
             "(use for seed-stability runs so production params stay put)",
    )
    parser.add_argument(
        "--drop-small-cycles", type=int, default=0, metavar="N",
        help="Exclude cycles with fewer than N races. The CV objective weights "
             "every cycle equally, so a 3-race odd-year governor cycle otherwise "
             "counts as much as a 54-race midterm.",
    )
    parser.add_argument(
        "--no-save", action="store_true",
        help="Score and report only — write the result to a temp file that is "
             "not part of the repo",
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

    if args.drop_small_cycles:
        from collections import Counter

        per_cycle = Counter(r.year for r in training_races)
        dropped = {y for y, n in per_cycle.items() if n < args.drop_small_cycles}
        if dropped:
            training_races = [r for r in training_races if r.year not in dropped]
            logger.info(
                "Dropped cycles with <%d races: %s — %d races remain",
                args.drop_small_cycles,
                sorted(dropped),
                len(training_races),
            )

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
    from src.training.optimizer import PARAM_SPACE

    if args.no_save:
        save_path = Path(tempfile.gettempdir()) / "trained_params_discarded.json"
    elif args.save_path:
        save_path = Path(args.save_path)
    else:
        save_path = None

    best_params, report = run_cv_optimization(
        training_races,
        n_trials=args.n_trials,
        holdout_cycle=args.holdout_cycle,
        save_path=save_path,
        seed=args.seed,
    )

    print("\n── Rolling-origin CV result ─────────────────────")
    print(f"  selection cycles : {report.selection_cycles}")
    print(f"  mean sel. RMSE   : {report.mean_selection_rmse:.3f}")
    print(f"  holdout cycle    : {report.holdout_cycle}")
    print(f"  holdout trained  : {report.holdout_trained}")
    print(f"  holdout default  : {report.holdout_default}")
    print(f"  trials / seed    : {report.n_trials} / {report.seed}")
    verdict = "PASSED" if report.passed_gate else "FAILED"
    print(f"  gate             : {verdict} — {report.gate_reason}")

    # Print the winner either way: on a failed gate these values are the whole
    # diagnostic (what did the objective chase, and did it hit a wall doing it).
    print("\n── Best Parameters ──────────────────────────────")
    for k, v in best_params.items():
        low, high = PARAM_SPACE.get(k, (float("-inf"), float("inf")))
        pinned = report.at_bounds.get(k)
        flag = f"   <- pinned at {pinned} of [{low:g}, {high:g}]" if pinned else ""
        print(f"  {k}: {v:.4f}{flag}")
    if report.at_bounds:
        print(
            "\n  WARNING: "
            f"{len(report.at_bounds)} of {len(best_params)} parameters are pinned "
            "against a search bound — those values are the edge of PARAM_SPACE, "
            "not a fitted optimum. Widen src/training/optimizer.py:PARAM_SPACE "
            "and re-run before treating them as fitted."
        )

    if report.passed_gate:
        target = save_path or Path("config/trained_params.json")
        print(f"\nSaved to {target} (with CV report).")
        print(
            "Next: python scripts/param_diff.py --after "
            f"{target} — see what it does to the published numbers before committing."
        )
    else:
        print(
            "\nGate failed — nothing written; the hand-set defaults stay in production.\n"
            "  A failed gate is a result, not an error: the winner beat the defaults on "
            "the selection cycles and lost on the untouched holdout, which is what\n"
            "  overfitting looks like. Check whether a parameter is pinned above, and "
            "whether the selection cycles are comparable in size (an odd-year\n"
            "  governor-only cycle carries the same weight as a full midterm in the "
            "per-cycle mean)."
        )
        raise SystemExit(2)


if __name__ == "__main__":
    main()
