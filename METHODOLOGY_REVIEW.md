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

---

## Architectural review — v2 pivot (May 2026)

Three design errors were identified in the v1 stack. All are being addressed in a phased
migration. This section records the diagnosis and the chosen remediation so that future
maintainers understand why the architecture looks the way it does.

### Error 1 — Silver Bulletin prior double-counts the polls

Silver Bulletin's daily model estimate is a fitted function of the same VoteHub/public
polls that the weighted-average engine ingests. The v1 "70/30 blend" (`bayesian.py`,
`alpha = n / (n + k)`) combined two functionals of overlapping data, violating the
conditional independence assumption required for a valid Bayesian update (Robert 2012,
*Bayesian Core*). The blend result was not a posterior update — it was a shrinkage of one
estimate toward a partially correlated second estimate.

**Interim fix (Phase 1d):** Output label changed to
`POLLS + SB anchor  —  not a Bayesian update; awaiting hierarchical fit`.

**Full fix (Phase 4):** `bayesian.py` deleted; Silver Bulletin becomes a side-by-side
benchmark with divergence attribution when |gap| > 1pp.

### Error 2 — 50/30/20 hybrid grade reused one signal three times

The three grading components (RCP historical accuracy, Silver Bulletin PPM, VoteHub letter
grade) all descend from the same election-outcome ground truth. The cross-correlations
between independently-built rating systems are ρ ≳ 0.6. Treating them as independent and
summing their 50/30/20 contributions significantly overstated precision.

**Fix (Phase 2):** Replaced with a single SB PPM lookup via
`quality = clip(1.5 - PPM × 0.3, 0.0, 3.0)`. The compression is intentional: the 0.3
multiplier keeps the rated pool in [0.96, 1.86] on the 0–3 scale. Quality differentiation
is modest by design until Phase 3's τⱼ² estimates validate what the polling data actually
support. Additionally, the function now requires ≥ 2 of 3 sources to produce a blended
score; pollsters with fewer sources receive the 25th-percentile default (_UNKNOWN_DEFAULT)
rather than a single-source rating treated as a full assessment.

**Note on _UNKNOWN_DEFAULT:** Set to the 25th percentile of the rated pool (~1.41). This
is the survivorship-adjusted prior: firms that appear in Silver Bulletin's table are
disproportionately those that have polled enough to be rated, so the unrated entrant is
more likely to be a new or lower-volume firm, not a randomly sampled member of the full
distribution. A midpoint default (1.5) would overestimate the prior for this population.

### Error 3 — Multiplicative downweighting cannot fix additive house effects

Rasmussen Reports runs +4–6pp pro-Approve on presidential approval; multiplying its weight
by a quality penalty of ~0.4 does not remove the bias — it slows the bias's entry into the
weighted average while still allowing it to pull the estimate in the wrong direction
(Shirani-Mehr, Rothschild, Goel & Gelman 2018, *JASA* 113(522)). The correct architecture
is additive house-effect intercepts identified jointly with the latent state (Jackman 2005,
*AJPS* 40(4); Linzer 2013, *JASA* 108(501)).

**Fix (Phase 3):** `src/models/state_space.py` — Jackman-style hierarchical model with
random-walk latent state α_t and pollster house effects δⱼ under a weighted sum-to-zero
constraint. τⱼ² (per-pollster excess variance) subsumes the quality-multiplier mechanism.

### Error 4 — Population weights inverted for approval

LV × 1.5 / Adults × 0.6 is correct for horse-race polls but wrong for approval. Likely
Voters are screened for electoral participation, not general public opinion, creating
selection bias in both directions depending on the partisan composition of the active
electorate. Pew/Kennedy & Deane (2017) documented a 14pp gap between LV and Adults on
Trump approval in 2017. Silver Bulletin themselves invert this hierarchy for approval
modeling.

**Fix (Phase 1a):** Approval-specific weights added to `PollingAverageParams`:
`approval_lv_weight_multiplier = 0.6`, `approval_rv_weight_multiplier = 1.0`,
`approval_adults_weight_multiplier = 1.5`. The engine branches on `poll.poll_type`.

---

## Planned phases (as of May 2026)

| Phase | Status | Description |
|---|---|---|
| 1 | ✅ Done | Population weight inversion; survivorship default; honest labels |
| 2 | ✅ Done | Drop 50/30/20 blend; use direct SB PPM |
| 3 | ✅ Done | Jackman state-space model (PyMC); house effects; sentiment slot |
| 4 | 🔲 Pending | Delete `bayesian.py`; SB as benchmark with divergence attribution |
| 5 | 🔲 Pending | Calibration metrics: CRPS, interval score, PIT, coverage, Ljung-Box |
| 6 | 🔲 Pending | Empirically tune σ_α via rolling-origin CRPS minimization |

### Phase 3 verification results (May 2026)

Fit on 683 approval polls (Jan 2025 – May 2026):
- **Convergence**: R̂ < 1.01 on all parameters; 2 divergences / 4000 transitions (negligible)
- **Runtime**: ~100 seconds (2 chains × 1000+1000 draws, single core)
- **95% CI width**: 3.1pp at 2026-05-20 (within reasonable range for dense 683-poll window)
- **Innovation SD**: σ_α = 0.232 pp/day
- **House effects** (correct signs for known partisan firms):
  - InsiderAdvantage: +6.6pp [+4.1, +8.4] — pro-Approve ✓
  - American Research Group: −5.3pp [−6.4, −4.1] — pro-Disapprove ✓
  - AP-NORC: −4.1pp [−5.3, −2.8] — pro-Disapprove ✓
  - Quinnipiac: −4.0pp [−4.8, −3.1] — pro-Disapprove ✓
  - Gallup: −3.7pp [−4.8, −2.5] — pro-Disapprove ✓
- **State-space vs weighted average**: 39.5% vs 40.1% (−0.6pp); state-space lower because
  it corrects for pro-Approve firms (InsiderAdvantage/HarrisX) that dominated recent window
- **State-space vs Silver Bulletin**: 39.5% vs 38.4% (+1.1pp, within noise)
