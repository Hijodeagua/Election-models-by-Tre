# Methodology Review — Election Oracle

_Synthesized from four independent GPT code reviews, May 2026._

---

## Verdict: Keep iterating on this repo

No rewrite needed. The architecture is already modular (data / models / analysis /
media / dashboard), the test suite is broad and green, config is pydantic-driven,
and the parameter optimizer path (Optuna + MLflow) is a meaningful maturity signal.
The next 20% of work — validation, calibration, simulation governance — will create
80% of the credibility needed to publish.

---

## What's already strong

| Area | Status |
|---|---|
| Modular source separation | ✅ Clean domain split across packages |
| Weighted polling engine | ✅ Recency decay, quality, sample size, LV/RV/Adults, partisan penalty |
| Bootstrap CIs | ✅ Present on all polling averages |
| Parameter optimization | ✅ Optuna loop with RMSE/MAE/bias/win-accuracy evaluator |
| Config-driven knobs | ✅ `settings.py` + `trained_params.json` — no magic numbers in engine |
| Test coverage | ✅ 131 passing tests across 5 files |
| Media sentiment fallback | ✅ Transformer + keyword fallback for production uptime |

---

## Critical gaps to fix before publishing forecasts

### 1. Tracker vs forecast distinction is blurry

Most outputs today are **polling averages** (trackers), not probabilistic forecasts.
A true forecast requires:

- Uncertainty propagation through to seat/outcome projections
- Correlated state/district error draws (not independent bootstrap)
- Scenario simulation (e.g., 10 000 election-day draws)
- Calibrated win probabilities (Brier score / log-loss / reliability curves)

**Action**: Use the `ModelMaturity` enum added in `src/models/__init__.py` to label
every output in dashboard and Substack posts. Do not call tracker outputs "forecasts."

### 2. Generic ballot seat conversion is too static

`SEATS_PER_MARGIN_POINT = 5.5` and `BASELINE_DEM_SEATS = 218` are rough OLS
estimates over 1998–2022 midterms. They do not vary by cycle, candidate environment,
or incumbency conditions. Using them for probability claims will produce overconfident
intervals in wave years.

**Action** (done): The constants are now configurable parameters on `GenericBallotModel`
(`seats_per_margin_point`, `baseline_dem_seats`). Next step: fit them from historical
data in `scripts/download_training_data.py` and load them the same way
`trained_params.json` is loaded, with uncertainty bands.

### 3. Uncertainty treatment is too shallow

Bootstrap CIs on polling averages are good but cover only sampling noise.
Missing layers:

- **Pollster house effects** — systematic lean per pollster, estimated and
  applied as a correction, not just a quality downweight
- **Non-response / late swing** — structural error that widens intervals
  approaching election day
- **Fundamentals uncertainty** — economic and incumbency priors have their
  own variance that should flow through to projections

### 4. Coverage imbalance creates false confidence

`HouseModel`, `GovernorModel`, and `PresidentialPrimaryTracker` are stubs.
All three are now labeled `ModelMaturity.STUB`. Do not publish output from them
until they have at least poll-averaging parity with `SenateModel`.

### 5. Backtesting is under-specified

Notebook backtests exist but there is no locked rolling-origin protocol,
no acceptance thresholds, and no cycle-by-cycle decomposition.
Before publishing win probabilities, define:

- Train/test split strategy: **rolling-origin by election cycle**
  (train on cycles ≤ N-1, evaluate on cycle N)
- Metrics: Brier score, log-loss, mean absolute error on margin, call accuracy
- Pass/fail thresholds before a model update is published

---

## Model tier definitions

Use these labels in all public outputs.

| Tier | Description | Ready to publish? |
|---|---|---|
| **TRACKER** | Weighted polling average, no projection | ✅ Yes — with "polling average" framing |
| **NOWCAST** | Current-environment blend (polls + fundamentals) | ⚠️ Build out fundamentals first |
| **FORECAST** | Probabilistic outcome + simulation + calibration | ❌ Not yet |
| **STUB** | Placeholder, do not publish | ❌ No |

---

## Key decisions to make before the next build phase

**Product scope**
- What does each model *promise*? Approval tracker only? Generic ballot nowcast?
  Senate win probabilities?
- What is your update cadence (daily / weekly) and freeze rule approaching
  election day?

**Data policy**
- Canonical poll deduplication rule (overlapping field dates, house-effects
  duplicates, sponsor duplicates)
- Internals / partisan polls: include with penalty, or exclude?
- Missing-data policy for sparse states / districts

**Statistical design**
- How are you separating national environment (approval, generic ballot, econ),
  state fundamentals (PVI / incumbency), and polling signal?
- Do you want a formal simulation engine (correlated state error draws)?
- Calibration metric and threshold per model update

**Operations**
- "No publish" guardrails: stale data, failed ingestion, too few polls
  (`MIN_POLLS_FOR_ESTIMATE` is now checked in approval and generic ballot)
- Model versioning: run metadata + artifact storage per publish event
- "Last updated" and confidence flags in dashboard / Substack outputs

---

## Recommended next steps (ordered by impact)

1. **Define one product per model** — write a one-paragraph product brief for
   approval, generic ballot, and Senate before adding more features.

2. **Finish Senate deeply before broadening** — bring Senate to NOWCAST maturity
   (polls + PVI/incumbency prior) before touching House/Governor.

3. **Lock a rolling-origin backtest** — at minimum two election cycles with
   Brier score tracking. Wire results into `src/training/evaluator.py`.

4. **Replace static seat slope** — fit `seats_per_margin_point` from historical
   data in the training pipeline; store alongside `trained_params.json`.

5. **Add house-effect correction** — estimate and store per-pollster lean in
   `config/pollster_ratings.json` (separate from quality score); apply as
   additive correction in `PollingAverageEngine._compute_weight`.

6. **Build the publication pipeline** — Datawrapper → Substack automation is
   already in the project plan; prioritize it once Senate reaches TRACKER
   stability so publishing cadence is consistent from day one.

---

## What a "minimum publishable" bar looks like

| Gate | Requirement |
|---|---|
| Approval tracker | ≥ 3 polls, stale-data flag after 7 days, CI displayed |
| Generic ballot tracker | ≥ 3 polls, seat range labeled "illustrative" |
| Senate tracker | Per-race average with ≥ 1 poll; "insufficient data" otherwise |
| Any win-probability claim | ≥ 2-cycle rolling backtest with Brier < 0.25 |
