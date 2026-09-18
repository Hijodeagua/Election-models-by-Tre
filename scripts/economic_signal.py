"""Does state economic data explain what the polling average misses?

This is the pre-registration step before any economic feature enters the
forecast. The question is narrow and falsifiable: after the weighted polling
average has had its say, is the *residual* — how much better or worse a party
did than its polls — predictable from the state's economy?

Method:

1. Residual per race, from the same code path the training objective uses
   (``PollingAverageEvaluator.per_race``), so the analysis cannot drift from
   what the model is scored on. Residual is in Dem−Rep margin points, positive
   where Democrats beat their polls.
2. Sign-flipped into *president's party* terms, because that is the actual
   theory: a bad economy costs the incumbent president's party. A positive
   coefficient on a good-economy feature means the president's party beat its
   polls where the economy was strong.
3. Each state's economy as published *before* that election (the ALFRED vintage
   panel), joined by postal code. Revised data would leak the future.
4. Five pre-registered features, every one reported whether or not it looks
   good — with a Bonferroni threshold, because five tests on one dataset find
   something by luck about a quarter of the time.
5. A holdout cycle, which is the only test that decides anything: does adding
   the feature reduce out-of-cycle RMSE? The same discipline the polling
   parameters are held to, and it is what stopped a 7-parameter fit from
   shipping in Sep 2026.

Inputs: the aligned vintage panels. Generate them first:

    foreach ($d in "2018-11-06","2020-11-03","2022-11-08") {
      python scripts/download_economic_data.py --realtime $d
    }

Usage:
    python scripts/economic_signal.py
    python scripts/economic_signal.py --offices senate
    python scripts/economic_signal.py --holdout-cycle 2020 --lookback-days 21
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._console import enable_utf8_output

enable_utf8_output()

from scripts.download_economic_data import aligned_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_PATH = PROJECT_ROOT / "data" / "processed" / "economic_signal.json"

# Party holding the presidency in each cycle — the party the economy is
# theorized to reward or punish. Midterm and presidential years alike.
PRESIDENT_PARTY: dict[int, str] = {
    2016: "D", 2017: "R", 2018: "R", 2019: "R", 2020: "R",
    2021: "D", 2022: "D", 2023: "D", 2024: "D",
    2025: "R", 2026: "R",
}

# The pre-registered feature list: (label, concept, which column).
# per_capita_income is deliberately excluded — annual frequency, and it carries
# the same information as personal_income growth.
FEATURES: list[tuple[str, str, str]] = [
    ("unemp_level", "unemployment_rate", "value"),
    ("unemp_change_12m", "unemployment_rate", "change_12m"),
    ("payrolls_growth_12m", "nonfarm_payrolls", "change_pct_12m"),
    ("hpi_growth_12m", "house_price_index", "change_pct_12m"),
    ("income_growth_12m", "personal_income", "change_pct_12m"),
]

# Features where a HIGHER value means a WORSE economy. Used only to label the
# expected sign in the report; the regression is untouched.
PAIN_FEATURES = {"unemp_level", "unemp_change_12m"}


def election_day(year: int) -> date:
    """First Tuesday after the first Monday in November."""
    day = date(year, 11, 1)
    while day.weekday() != 0:  # Monday
        day += timedelta(days=1)
    return day + timedelta(days=1)


@dataclass
class RaceRow:
    """One race: its polling residual plus that state's pre-election economy."""

    race_id: str
    year: int
    state: str
    office: str
    n_polls: int
    pred_margin: float
    actual_margin: float
    residual: float        # actual − predicted, Dem−Rep points
    residual_pres: float   # same, in president's-party terms
    features: dict[str, float]


def load_aligned(year: int) -> dict[tuple[str, str], dict[str, float]] | None:
    """(state, concept) → {value, change_12m, change_pct_12m} for a cycle.

    Reads the vintage panel for that election — values as published then.
    Returns None when that vintage has not been pulled, so the cycles you do
    have still get analysed instead of the whole run dying on a missing file.
    """
    cutoff = election_day(year)
    path = aligned_path(cutoff, cutoff)
    if not path.exists():
        return None

    out: dict[tuple[str, str], dict[str, float]] = {}
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            values: dict[str, float] = {}
            for col in ("value", "change_12m", "change_pct_12m"):
                raw = (row.get(col) or "").strip()
                if raw:
                    values[col] = float(raw)
            out[(row["state"], row["concept"])] = values
    return out


def build_rows(
    predictions: list[Any],
) -> tuple[list[RaceRow], dict[str, int], list[int]]:
    """Join residuals to each cycle's vintage panel.

    Returns (rows, skip counts, cycles missing a panel).
    """
    panels: dict[int, dict[tuple[str, str], dict[str, float]] | None] = {}
    rows: list[RaceRow] = []
    skipped: dict[str, int] = defaultdict(int)
    missing_panels: set[int] = set()

    for pred in predictions:
        race = pred.race
        if race.year not in PRESIDENT_PARTY:
            skipped["no president-party mapping"] += 1
            continue
        if race.year not in panels:
            panels[race.year] = load_aligned(race.year)
        panel = panels[race.year]
        if panel is None:
            missing_panels.add(race.year)
            skipped[f"no economic vintage for {race.year}"] += 1
            continue

        features: dict[str, float] = {}
        for label, concept, column in FEATURES:
            entry = panel.get((race.state, concept))
            if entry is None or column not in entry:
                continue
            features[label] = entry[column]

        if len(features) < len(FEATURES):
            skipped[f"incomplete economic data ({race.state} {race.year})"] += 1
            continue

        # Residual: how much better the Democrat did than the polling average.
        residual = pred.actual_margin - pred.pred_margin
        sign = 1.0 if PRESIDENT_PARTY[race.year] == "D" else -1.0
        rows.append(RaceRow(
            race_id=race.race_id,
            year=race.year,
            state=race.state,
            office=race.office,
            n_polls=pred.n_polls,
            pred_margin=round(pred.pred_margin, 3),
            actual_margin=round(pred.actual_margin, 3),
            residual=round(residual, 3),
            residual_pres=round(residual * sign, 3),
            features=features,
        ))
    return rows, dict(skipped), sorted(missing_panels)


def regress(rows: list[RaceRow], label: str) -> dict[str, Any]:
    """Univariate OLS of the president's-party residual on one feature.

    Standard errors are clustered by cycle: races in the same year share a
    national environment, so treating them as independent overstates
    significance. With only a handful of cycles the cluster-robust SEs are
    themselves shaky — read them as indicative, not as a verdict.
    """
    import numpy as np
    import statsmodels.api as sm

    y = np.array([r.residual_pres for r in rows])
    x = np.array([r.features[label] for r in rows])
    groups = np.array([r.year for r in rows])

    design = sm.add_constant(x)
    model = sm.OLS(y, design)
    n_clusters = len(set(groups.tolist()))
    if n_clusters >= 2:
        fit = model.fit(cov_type="cluster", cov_kwds={"groups": groups})
    else:
        fit = model.fit()

    return {
        "feature": label,
        "coef": round(float(fit.params[1]), 4),
        "std_err": round(float(fit.bse[1]), 4),
        "t": round(float(fit.tvalues[1]), 3),
        "p_value": round(float(fit.pvalues[1]), 4),
        "r_squared": round(float(fit.rsquared), 4),
        "n": int(len(rows)),
        "n_clusters": n_clusters,
        "expected_sign": "negative" if label in PAIN_FEATURES else "positive",
    }


def holdout_test(rows: list[RaceRow], label: str, holdout: int) -> dict[str, Any]:
    """Out-of-cycle RMSE with and without the feature.

    Fit on every other cycle, score the holdout once. A feature earns its place
    only by lowering RMSE here — in-sample significance is not evidence.
    """
    import numpy as np
    import statsmodels.api as sm

    train = [r for r in rows if r.year != holdout]
    test = [r for r in rows if r.year == holdout]
    if len(train) < 10 or len(test) < 5:
        return {"feature": label, "usable": False, "reason": "too few races"}

    y_train = np.array([r.residual_pres for r in train])
    y_test = np.array([r.residual_pres for r in test])
    x_train = np.array([r.features[label] for r in train])
    x_test = np.array([r.features[label] for r in test])

    fit = sm.OLS(y_train, sm.add_constant(x_train)).fit()
    pred = fit.params[0] + fit.params[1] * x_test

    # Baseline: predict no residual at all, which is what the model does today.
    rmse_base = float(np.sqrt(np.mean(y_test**2)))
    rmse_feat = float(np.sqrt(np.mean((y_test - pred) ** 2)))
    return {
        "feature": label,
        "usable": True,
        "holdout_cycle": holdout,
        "n_train": len(train),
        "n_test": len(test),
        "rmse_without": round(rmse_base, 3),
        "rmse_with": round(rmse_feat, 3),
        "improvement": round(rmse_base - rmse_feat, 3),
        "helps": rmse_feat < rmse_base,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test whether state economic data explains polling residuals"
    )
    parser.add_argument("--min-year", type=int, default=2010)
    parser.add_argument("--max-year", type=int, default=2024)
    parser.add_argument(
        "--offices", nargs="+", default=["senate", "governor"],
        choices=["senate", "governor", "house"],
    )
    parser.add_argument("--lookback-days", type=int, default=60)
    parser.add_argument(
        "--holdout-cycle", type=int, default=None,
        help="Cycle scored out-of-sample (default: the most recent present)",
    )
    parser.add_argument(
        "--params", default="defaults",
        help="'defaults' or a trained_params.json path — which polling average "
             "produces the residuals",
    )
    args = parser.parse_args()

    from src.models.polling_average import PollingAverageParams
    from src.training.data_loader import TrainingDataLoader
    from src.training.evaluator import PollingAverageEvaluator
    from src.training.optimizer import PARAM_SPACE

    if args.params == "defaults":
        params = {k: getattr(PollingAverageParams(), k) for k in PARAM_SPACE}
    else:
        path = Path(args.params)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.exists():
            raise SystemExit(f"Parameter file not found: {path}")
        params = json.loads(path.read_text()).get("params", {})

    logger.info("Loading training races...")
    loader = TrainingDataLoader(lookback_days=args.lookback_days)
    races = loader.load(
        offices=args.offices, min_year=args.min_year, max_year=args.max_year
    )
    if not races:
        raise SystemExit(
            "No training races loaded. Run: python scripts/download_training_data.py"
        )

    predictions = PollingAverageEvaluator(races).per_race(params)
    logger.info("Scored %d of %d races", len(predictions), len(races))

    rows, skipped, missing_panels = build_rows(predictions)
    if missing_panels:
        print("\n  Cycles with no economic vintage pulled (excluded):")
        for year in missing_panels:
            cutoff = election_day(year)
            print(
                f"    {year}: python scripts/download_economic_data.py "
                f"--realtime {cutoff.isoformat()}"
            )
    if not rows:
        raise SystemExit(
            "No races could be joined to economic data.\n"
            f"  Skips: {skipped}\n"
            "  Pull the vintages listed above and re-run."
        )

    holdout = args.holdout_cycle or max(r.year for r in rows)

    print("\n── Sample ───────────────────────────────────────────────")
    print(f"  races with residual + economy : {len(rows)}")
    by_cycle: dict[int, int] = defaultdict(int)
    for row in rows:
        by_cycle[row.year] += 1
    print(f"  per cycle                     : "
          f"{', '.join(f'{y}={n}' for y, n in sorted(by_cycle.items()))}")
    print(f"  holdout cycle                 : {holdout}")
    print(f"  params                        : {args.params}")
    if skipped:
        total = sum(skipped.values())
        print(f"  skipped                       : {total} "
              f"({len(skipped)} distinct reasons)")

    residuals = [r.residual_pres for r in rows]
    mean_resid = sum(residuals) / len(residuals)
    rmse_resid = (sum(r**2 for r in residuals) / len(residuals)) ** 0.5
    print(f"\n  residual (president's party, margin points): "
          f"mean {mean_resid:+.2f}, RMSE {rmse_resid:.2f}")
    print("  That RMSE is the target. A feature is only interesting if it cuts it.")

    bonferroni = 0.05 / len(FEATURES)
    print("\n── Univariate fits (cycle-clustered SEs) ────────────────")
    print(f"  {'feature':22} {'coef':>9} {'se':>8} {'t':>7} {'p':>8} {'R²':>7} {'sign':>9}")
    fits = []
    for label, _, _ in FEATURES:
        fit = regress(rows, label)
        fits.append(fit)
        flag = ""
        if fit["p_value"] < bonferroni:
            flag = "  ** survives Bonferroni"
        elif fit["p_value"] < 0.05:
            flag = "  * nominal only"
        print(
            f"  {label:22} {fit['coef']:>9.4f} {fit['std_err']:>8.4f} "
            f"{fit['t']:>7.2f} {fit['p_value']:>8.4f} {fit['r_squared']:>7.4f} "
            f"{fit['expected_sign']:>9}{flag}"
        )
    print(f"\n  Bonferroni threshold for {len(FEATURES)} tests: p < {bonferroni:.3f}")
    print(f"  Clusters (cycles): {fits[0]['n_clusters']} — "
          "cluster-robust inference is unreliable below ~10, so treat p-values "
          "as directional.")

    print(f"\n── Holdout test on {holdout} (the one that decides) ─────")
    print(f"  {'feature':22} {'RMSE without':>13} {'RMSE with':>11} {'Δ':>8}")
    holdouts = []
    for label, _, _ in FEATURES:
        result = holdout_test(rows, label, holdout)
        holdouts.append(result)
        if not result.get("usable"):
            print(f"  {label:22} unusable: {result['reason']}")
            continue
        verdict = "helps" if result["helps"] else ""
        print(
            f"  {label:22} {result['rmse_without']:>13.3f} "
            f"{result['rmse_with']:>11.3f} {result['improvement']:>+8.3f}  {verdict}"
        )

    winners = [h for h in holdouts if h.get("helps")]
    print("\n── Verdict ──────────────────────────────────────────────")
    if not winners:
        print(
            "  No feature lowered out-of-cycle RMSE. State economies do not explain\n"
            "  what these polling averages miss, on this sample. That is a real\n"
            "  result: it says do not add the feature, and it cost one evening\n"
            "  instead of a bad coefficient in production."
        )
    else:
        print(
            f"  {len(winners)} feature(s) lowered holdout RMSE: "
            f"{', '.join(w['feature'] for w in winners)}.\n"
            "  Before wiring anything in: re-run with --holdout-cycle set to a\n"
            "  different year. A feature that only helps on one holdout is noise,\n"
            "  and the sample here is small enough that one cycle can carry it."
        )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({
        "generated": datetime.now().astimezone().isoformat(),
        "params": args.params,
        "offices": args.offices,
        "lookback_days": args.lookback_days,
        "n_races": len(rows),
        "races_per_cycle": dict(sorted(by_cycle.items())),
        "holdout_cycle": holdout,
        "residual_rmse": round(rmse_resid, 3),
        "residual_mean": round(mean_resid, 3),
        "bonferroni_threshold": round(bonferroni, 4),
        "univariate": fits,
        "holdout": holdouts,
        "skipped": skipped,
        "cycles_without_panel": missing_panels,
        "note": (
            "Residuals are actual minus polling-average margin in president's-party "
            "terms. Economic values are ALFRED vintages as published before each "
            "election. The holdout RMSE decides; p-values are directional given the "
            "small number of cycles."
        ),
        "rows": [
            {
                "race_id": r.race_id, "year": r.year, "state": r.state,
                "office": r.office, "n_polls": r.n_polls,
                "pred_margin": r.pred_margin, "actual_margin": r.actual_margin,
                "residual": r.residual, "residual_pres": r.residual_pres,
                **{f"econ_{k}": v for k, v in r.features.items()},
            }
            for r in rows
        ],
    }, indent=2) + "\n")
    print(f"\n  Wrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
