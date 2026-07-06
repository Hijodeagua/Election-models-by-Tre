# Election Oracle — Data Science Status & Methodology-Improvement Briefing

_Opus DS Review — 2026-07-06_

**Role for the receiving agent:** You are a senior data scientist auditing an
election-forecasting codebase. Below is the current state and a prioritized set
of methodological improvements, grounded in the actual implementation. Treat the
"Findings" as claims to verify against the code, not gospel — several are subtle
and worth confirming before acting.

---

## A. Overall assessment

The project is **methodologically self-aware and unusually honest** — the
`METHODOLOGY_REVIEW.md` diagnoses four real statistical errors with correct
citations, and the `ModelMaturity` tiering prevents over-claiming. The
engineering is clean (modular, typed, ~206 tests, config-driven, CI-refreshed).
This is a strong TRACKER-grade system.

But from a forecasting standpoint it is **mid-transition**: the sound theory
(Jackman state-space model) exists in code but is **not in the production
path**, and the published numbers still rely on the very mechanism the review
says is inadequate. The calibration layer is the most mature forecasting
component and the best foundation to build on. The gap between "what the docs
say the method is" and "what the daily pipeline actually runs" is the single
most important thing to close.

---

## B. Status from a DS lens

**Sound:**
- Weighted-average engine with trainable exponents (`polling_average.py`) —
  recency, quality, sample size, population, partisan penalty are all principled
  and configurable.
- Empirical calibration (`config/forecast_calibration.json`): 98 Senate races,
  2018–2024, fitted bias −2.50, national σ 2.87 / race σ 5.14,
  **Brier 0.060, win-accuracy 89.8%**, plus a reliability curve and
  per-pollster/per-state bias tables. This is real backtesting.
- Correlated-error Monte Carlo (national + idiosyncratic factor) with market
  blending via an effective-margin inversion — conceptually correct.
- Look-ahead guard in `compute_average` (`poll.end_date > as_of` filter,
  `polling_average.py:163`) — avoids future-data leakage at historical
  snapshots. Good hygiene.

**Shaky / incomplete:**
- **The state-space model is opt-in and skipped in CI** (`meta.json`:
  `"state_space": "skipped — too heavy for CI"`). So the published
  approval/generic-ballot numbers use the plain weighted average — which per the
  review's own **Error 3** *cannot remove additive house effects*. The fix is
  written but not shipped.
- Uncertainty is **sampling-noise-only** for trackers (bootstrap over polls).
  No house-effect, non-response, or time-to-election variance flows into the
  published CIs.
- Parameter training has **no rolling-origin CV in the loop** — the Optuna
  evaluator scores on the same race pool, inviting overfitting.

---

## C. Concrete findings in the code (verify each)

1. **Evaluator unit mismatch (likely real bug).** `training/evaluator.py`
   compares `pred_dem` (a *raw* Dem % from `averages`, lines 86–90) against
   `race.dem_two_party_share` (two-party normalized). With third-party/undecided
   in the raw number, this bakes a systematic negative bias into every fitted
   parameter set. → Two-party-normalize `pred_dem` before differencing, or store
   raw share in the training data. **High priority — it corrupts the
   optimizer's objective.**

2. **Republican derived as complement.** In the generic-ballot state-space path
   (`generic_ballot.py:114`, `rep_mean = 100 - dem_mean`) and elsewhere, the
   "other side" is `100 − dem`. That absorbs undecided/third-party into the two
   majors and inflates the margin. Model both choices, or normalize two-party
   explicitly.

3. **Static seat conversion.** `generic_ballot.py`: `SEATS_PER_MARGIN_POINT=5.5`,
   `BASELINE_DEM_SEATS=218`, clamp [150,285]. Already flagged as illustrative —
   but note it also (a) applies no correction for the historical
   **generic-ballot-overstates-Dems** bias, (b) ignores incumbency/uncontested-
   seat structure, and (c) has no uncertainty band. Fit it from historical data
   with a proper uniform-swing-plus-noise model.

4. **Unknown-pollster default inconsistency.** The engine hardcodes `1.5` for
   unrated pollsters (`polling_average.py:232`), but `METHODOLOGY_REVIEW.md`
   specifies a survivorship-adjusted 25th-percentile default (~1.41) requiring
   ≥2 sources. The production weight path may not match the documented ratings
   policy. Reconcile.

5. **Rank-1 correlation only.** `senate_simulation.py` models cross-race
   correlation as a *single* national normal factor + independent per-race
   noise, with Gaussian (not fat) tails. Real polling error has
   **regional/demographic covariance** and heavier tails. Consider a low-rank
   factor model or an empirical covariance from the archive, and Student-t draws.

6. **No visible poll deduplication.** Overlapping field dates, multiple releases
   of the same poll, and sponsor duplicates aren't handled in the ingestion path
   (the review lists this as an open data-policy question). Duplicates silently
   over-weight a pollster.

7. **Hand-set governance knobs.** `calibration_bias_weight=0.5`, `blend_k=3.0`,
   `market_weight=0.25`, `senate_responsiveness=1.0` are all reasonable but
   chosen, not learned. Each is a place overconfidence can enter. At minimum,
   sensitivity-analyze them.

---

## D. Prioritized improvement roadmap

**Tier 1 — correctness (do first):**
1. Fix the evaluator two-party unit mismatch (Finding 1) and re-run parameter
   training; the current `trained_params.json` may be fit against a biased
   objective.
2. Normalize two-party consistently across generic ballot / senate (Finding 2).
3. Reconcile the unknown-pollster default between engine and ratings policy
   (Finding 4).

**Tier 2 — get the good model into production:**
4. Make the Jackman state-space model the published estimate for approval and
   generic ballot (currently opt-in). Solve the CI-cost problem: cache the
   trace, cut draws, run it on the monthly schedule rather than per-refresh, or
   precompute nightly. Until this ships, the published numbers carry the
   additive house-effect bias the review already diagnosed.
5. Propagate house-effect and time-to-election variance into published CIs, so
   intervals reflect more than sampling noise.

**Tier 3 — validation & calibration (the credibility layer):**
6. Lock a **rolling-origin backtest** (train on cycles ≤ N−1, test on N) as an
   automated protocol with pass/fail gates — not just notebooks. Wire into
   `training/evaluator.py`.
7. Add the Phase 5 metrics the roadmap already names: **CRPS, PIT histograms,
   interval/coverage scores, log-loss**, alongside the existing Brier. Report
   reliability curves per model, per cycle.
8. Fit the seat-conversion slope + baseline from history *with* uncertainty
   (Finding 3) and let it vary by national environment.

**Tier 4 — structural realism:**
9. Upgrade the correlation model (Finding 5): empirical covariance / factor
   structure + fat tails.
10. Add a deduplication rule and a documented internals/partisan-poll policy
    (Finding 6).
11. Empirically tune σ_α (Phase 6) via rolling-origin CRPS minimization rather
    than the current HalfNormal(1) prior default.

---

## E. What a DS would tell Tre to publish vs. hold

- **Publish now:** approval tracker, generic-ballot tracker (as "polling
  averages"), Senate per-race averages, and the Senate-control NOWCAST **with
  its reliability curve shown** — the calibration backing is genuinely there.
- **Hold:** any House/Governor/2028 output (STUBs); any seat *probability* claim
  from the generic ballot until the slope is refit; the "vibes" signal until
  it's validated against outcomes (no win/AUC evidence exists yet).

---

_Snapshot context: data as of the 2026-07-06 refresh — 2,907 approval polls,
526 generic-ballot polls, 23 Senate polls; Senate-control NOWCAST P(Dem control)
≈ 28.7%, mean 49.5 Dem seats. Test suite ~206 functions across 14 files._
