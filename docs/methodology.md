# Election Oracle — Methodology Reference

**Version**: 0.2 (May 2026)
**Models covered**: Presidential Approval, Generic Ballot, Senate Map, Vibes
**Maturity levels**: `TRACKER` → `NOWCAST` → `FORECAST`

---

## Table of Contents

1. [Model Maturity Framework](#1-model-maturity-framework)
2. [Polling Average Engine](#2-polling-average-engine)
3. [Presidential Approval Model](#3-presidential-approval-model)
4. [Generic Ballot Model](#4-generic-ballot-model)
5. [Senate Map Model](#5-senate-map-model)
6. [Vibes Model](#6-vibes-model)
7. [House Model](#7-house-model)
8. [Fundamentals & Candidate Quality](#8-fundamentals--candidate-quality)
9. [Data Sources](#9-data-sources)
10. [Known Gaps & Roadmap](#10-known-gaps--roadmap)

---

## 1. Model Maturity Framework

Every model output is tagged with a maturity level so readers know what a number is claiming.

| Level | Meaning | Example output |
|-------|---------|----------------|
| `TRACKER` | Descriptive average of current polls. No forward-looking claim. | "Trump approval: 43.2%" |
| `NOWCAST` | Current-environment estimate blending polls + fundamentals. | "Dems projected to win 48 Senate seats" |
| `FORECAST` | Probabilistic outcome projection with simulation + calibration. | "Democrats have a 62% chance of retaining the Senate" |
| `STUB` | Not ready for any public output. | — |

The distinction between `TRACKER` and `NOWCAST` matters: a tracker will move with every new poll; a nowcast damps individual polls against structural priors and changes more slowly and intentionally.

---

## 2. Polling Average Engine

**Source**: `src/models/polling_average.py` — `PollingAverageEngine`

### 2.1 Weight Formula

Each poll receives a composite weight before averaging:

```
w = w_recency × w_quality × w_samplesize × w_population × w_partisan
```

**Recency** — exponential decay with configurable half-life (default 14 days):

```
w_recency = exp(−ln(2) × age_days / half_life)
```

*Why exponential?* It reflects the intuition that a poll from 7 days ago is roughly half as informative about today's electorate as a poll from yesterday, and a poll from 28 days ago is a quarter as informative. Linear decay would be too generous to old polls; hard cutoffs would be too harsh.

**Pollster quality** — from `config/pollster_ratings.json` (0–3 scale; unknown pollsters default to 1.5):

```
w_quality = (rating / 3.0) ^ quality_exponent
```

The exponent is trainable via Optuna. At `quality_exponent = 1.0` (default), the weight scales linearly with quality. Values > 1 amplify quality differences (good for high-quality environments); values < 1 flatten them (useful when few high-quality pollsters are active).

**Sample size** — square-root scaling (statistical theory: margin-of-error ∝ 1/√n):

```
w_samplesize = (sample_size / 1000) ^ 0.5
```

Polls below the minimum sample threshold (`min_sample_size`, default 100) receive a flat 0.5× penalty rather than being excluded, so rare small-sample polls still contribute weakly.

**Population screen** — hierarchy differs for approval vs. horse-race polls:

| Population | Horse-race weight | Approval weight | Rationale |
|------------|------------------|-----------------|-----------|
| Likely Voters (LV) | 1.5× | 0.6× | LV screens create selection bias irrelevant to approval dynamics |
| Registered Voters (RV) | 1.0× | 1.0× | Neutral baseline |
| Adults (A) | 0.6× | 1.5× | Adults capture broadest public sentiment for approval; too liberal for horse-race |

The approval inversion is supported by Pew/Kennedy & Deane (2017), who found LV screens produce systematically higher presidential approval ratings than adult samples without meaningful improvement in accuracy.

**Partisan penalty** — polls from partisan sponsors receive a 0.5× multiplier by default. The penalty is not a ban; it reflects the documented lean toward sponsors in partisan internal polling (Hersh & Nall 2016).

### 2.2 Bootstrap Confidence Intervals

When ≥ 5 polls are available, 80% bootstrap confidence intervals are computed by resampling with replacement 1,000 times, preserving poll weights in each resample. The 10th and 90th percentiles of the resampled mean distribution define the interval.

*Why 80% rather than 95%?* Polling averages are reported as estimates, not experiment results. An 80% CI is more actionable for forecasting — it shows a plausible range rather than an extreme bound that's almost never violated.

### 2.3 House-Effect Correction (Future)

Systematic pollster lean (house effects) is tracked in the state-space model (`src/models/state_space.py`) but not yet applied as a correction to the polling average engine. Phase 6 of the roadmap adds this as a pre-processing step.

---

## 3. Presidential Approval Model

**Source**: `src/models/approval.py` — `PresidentialApprovalModel`
**Maturity**: `TRACKER`

### 3.1 Current Approval

`current_approval(polls)` passes all `PollType.APPROVAL` polls through the polling average engine with `choices=["Approve", "Disapprove"]`. Population weights use the inverted hierarchy (Adults > RV > LV). Returns an `ApprovalSnapshot` always — the caller decides whether to publish based on `MIN_POLLS_FOR_ESTIMATE = 3`.

### 3.2 Approval Trend

`approval_trend(polls, start, end, step_days)` steps through calendar days and computes a snapshot at each point, using only polls whose field period ended before or on that date. This prevents future data from leaking into historical trend points — a common bug in polling average implementations.

### 3.3 State-Space Model

`current_estimate_ss(polls)` fits a Jackman-style hierarchical state-space model using PyMC (optional dependency group `[bayesian]`). This is the gold-standard approach for polling averages:

- Latent state `α_t` follows a Gaussian random walk (innovation SD `σ_α ~ HalfNormal(0, 1)`)
- House effects `δⱼ` are estimated per pollster with a weighted sum-to-zero constraint
- Per-pollster excess variance `τⱼ ~ HalfNormal(0, 2.5)` captures firm-level reliability beyond sampling error
- The observation model includes both sampling variance (`p*(1-p)/n`) and excess variance

The non-centered parameterization of the random walk (`α₀ + cumsum(σ_α × z)` where `z ~ Normal(0,1)`) improves NUTS sampler efficiency for long time series with sparse observations.

**Status**: State-space is implemented and convergence-checked (R̂ < 1.05 required) but runs alongside — not instead of — the weighted average. It becomes the primary method in Phase 4.

---

## 4. Generic Ballot Model

**Source**: `src/models/generic_ballot.py` — `GenericBallotModel`
**Maturity**: `TRACKER`

### 4.1 Current Ballot

Identical pipeline to approval, using `PollType.GENERIC_BALLOT` polls and standard LV > RV > Adults hierarchy. Multiple Dem label variants (`Democrat`, `Democratic`, `Democrats`) are normalized before averaging.

### 4.2 Seat Translation

A rough OLS relationship translates the national D-R generic ballot margin into estimated Democratic House seats:

```
projected_dem_seats = 218 + margin × 5.5
```

Clamped to [150, 285] to prevent absurd outputs.

**Caveat**: This is illustrative only. The 5.5 seats-per-point estimate is a rough average across 1998–2022 cycles. The actual relationship is non-linear (particularly at extreme margins), sensitive to district map, and has changed over time as geographic sorting has accelerated. Do not use this number for probability claims.

### 4.3 State-Space Model

`current_estimate_ss()` uses the same Jackman model as approval, fitting on the dominant Dem label in the dataset.

---

## 5. Senate Map Model

**Source**: `src/models/senate.py` — `SenateModel`
**Maturity**: `NOWCAST`

### 5.1 Architecture

The model blends four inputs for each of the 33 Class-II races up in 2026:

```
final_margin = blend(poll_margin, prior_margin) + vibes_adjustment
```

Where:
- `prior_margin` = structural prior from expert rating (see §5.2)
- `poll_margin` = D-R margin from the polling average engine
- `blend` = a poll-count-weighted interpolation (see §5.3)
- `vibes_adjustment` = signed pp shift from the vibes model (see §6)

### 5.2 Rating-Based Prior

Expert race ratings (Cook Political Report / Sabato's Crystal Ball equivalent) are mapped to a prior D-R margin:

| Rating | Prior Margin (pp) | SD (pp) |
|--------|------------------|---------|
| Solid D | +18.0 | 5.0 |
| Likely D | +9.0 | 6.5 |
| Lean D | +3.5 | 7.5 |
| Tossup | 0.0 | 8.0 |
| Lean R | −3.5 | 7.5 |
| Likely R | −9.0 | 6.5 |
| Solid R | −18.0 | 5.0 |

Prior margins are the median actual margins in 2006–2022 Senate races within each rating category. The SD represents the typical residual uncertainty after conditioning on the rating.

### 5.3 Poll Blending

```python
blend = min(1.0, poll_weight × n_polls / (n_polls + 5))
combined_margin = blend × poll_margin + (1 − blend) × prior_margin
```

Where `poll_weight = 0.1` before both primaries are decided, and `1.0` after.

**Why 0.1× before primaries?** Early generic Senate polls — before a nominee is selected — measure hypothetical matchups against unknown opponents. A poll showing "Generic Democrat +3 in Georgia" in January of an election year tells you very little about the eventual race between specific candidates. The 0.1× weight allows such polls to move the needle slightly (enough to reflect genuine wave environments) without overriding the structural prior. Once primaries resolve and real candidates are polling, the weight returns to full.

The denominator `n_polls + 5` implements a Bayesian-style shrinkage toward the prior. With 5 polls, the model is 50% polls and 50% prior; with 20 polls, it's 80% polls; with 50 polls, it's 91% polls. The "5 poll equivalent prior" reflects the fact that a single expert rating encodes roughly 5 polls worth of structural signal.

### 5.4 Win Probabilities

```python
SD = 3.5 + 7.0 × exp(−0.15 × n_polls)
P(D wins) = Φ(margin / SD)
```

The SD starts at ~10.5 pp (zero polls) and asymptotes to ~3.5 pp (many polls). This reflects:
- **Irreducible uncertainty**: even with perfect polling, Senate races have ~3.5 pp unexplained variance from late-breaking events, turnout surprises, and non-sampled factors
- **Polling reduces uncertainty**: each additional poll shrinks the uncertainty toward the floor

*Note*: This is a simplified normal approximation. A proper simulation would also account for correlated errors across states (national wave uncertainty shared by all seats), which is not yet implemented. The win probabilities will be overconfident in high-wave environments.

---

## 6. Vibes Model

**Source**: `src/models/vibes.py` — `VibesModel`
**Data**: `src/data/nyt.py` — `NYTArticleSource`
**Maturity**: Experimental (NOWCAST-class when scorer is improved)

### 6.1 Theoretical Basis

The vibes model operationalizes the concept of *candidate quality residual* — the portion of a Senate outcome unexplained by structural factors. Candidates who generate favorable media narratives (fundraising records, crossover appeal, strong debate performances) tend to outperform their structural baseline; those generating negative narratives (scandals, gaffes, endorsement problems) underperform.

This follows the methodology described in Sides & Vavreck (2013) *The Gamble* and extended in Morris (2020) *G. Elliott Morris's Senate Forecasting Model*. The key insight is that media volume and tone are correlated with candidate quality but measured independently of polls or ratings.

### 6.2 Data Collection

Articles are fetched from the NYT Article Search API using the query:

```
"[State]" Senate [Year]
```

Filtered to sections: `U.S.`, `Politics`, `National Desk`.

Parameters:
- **Window**: 120 days before Election Day (approximately July 1 – October 31)
- **Pages**: Up to 5 per race (50 articles maximum per API query)
- **Rate limit**: 12-second inter-page sleep (NYT allows 10 req/min; 12s provides 2× headroom)
- **Cache**: SHA-256 keyed disk cache at `data/cache/nyt/`; re-runs are free

**Limitation**: The query does not filter by candidate name. Articles about both candidates — and sometimes articles only tangentially related to the race — are included. This is the model's most important known flaw.

### 6.3 Keyword Sentiment Scoring

Each article receives a raw score in [−1, +1] via a keyword presence model:

```
score = (pos_hits − neg_hits) / (pos_hits + neg_hits + ε)
```

Positive terms include: `leads`, `leading`, `momentum`, `endorsed`, `popular`, `fundraising record`, `coalition`, `breakthrough`

Negative terms include: `scandal`, `indicted`, `charged`, `embattled`, `ethics`, `gaffe`, `backlash`, `trailing`, `struggles`, `cash-strapped`

A negation window (preceding `not`, `no`, `never`) flips the sign of the next matched term. Amplifiers (`strongly`, `decisively`, `overwhelmingly`) add 0.5× weight to adjacent matched terms.

**Known problem**: The positive-term list contains language that appears in neutral competitive-race coverage regardless of which candidate is being discussed. This produces a rightward bias in raw scores — 44% of races scored positive, only 5% scored negative, in a calibration set where outcomes were roughly symmetric around the prior. The scorer needs named-entity resolution to be useful at this granularity.

### 6.4 Recency Weighting and Race-Level Aggregation

Individual article scores are aggregated into a race-level score using exponential recency weighting:

```
w_i = exp(−ln(2) × age_days / half_life)     half_life = 30 days
race_score = Σ(w_i × score_i) / Σ(w_i)
```

The 30-day half-life weights articles from the final month of the campaign approximately 4× more than articles from 3 months out. This reflects the intuition that late-breaking campaign developments are more predictive than early coverage.

**Confidence score**: `min(1.0, n_articles / 5)` — reaches 1.0 at 5 or more articles. Used by downstream consumers to decide how much weight to apply.

### 6.5 Bucketing

The continuous race-level score is discretized into categorical buckets at three granularities for robustness testing:

| Granularity | Thresholds |
|-------------|------------|
| 3-modal | Negative: < −0.15 \| Neutral: [−0.15, +0.15] \| Positive: > +0.15 |
| 5-modal | Strongly Neg: < −0.45 \| Lean Neg: [−0.45, −0.12] \| Neutral: [−0.12, +0.12] \| Lean Pos: [+0.12, +0.45] \| Strongly Pos: > +0.45 |
| 7-modal | Boundaries at ±0.10, ±0.35, ±0.65 |

Thresholds were set prior to calibration based on expected score distribution. With better scoring they should be recalibrated — currently nearly all observations fall in the neutral-to-lean-positive band, making the outer tiers (strongly positive/negative) unoccupied and uncalibrated.

### 6.6 Margin Adjustments

Each bucket maps to a signed margin adjustment (pp toward Dem). Two versions:

**Prior (literature-informed, used before calibration)**:
- 5-modal: ±2.5 pp (strongly), ±1.0 pp (lean), 0.0 (neutral)

**Calibrated (from 43-race empirical fit)**:

| 5-modal bucket | Calibrated adjustment |
|----------------|----------------------|
| Strongly Positive | 0.00 (no data) |
| Lean Positive | +0.35 pp |
| Neutral | −0.43 pp |
| Lean Negative | −2.10 pp |
| Strongly Negative | 0.00 (no data) |

The neutral bucket's −0.43 pp adjustment is notable: races scoring neutral slightly underperformed their structural prior on average. This may reflect the positive-skew problem (some races that should have scored negative ended up neutral).

### 6.7 Calibration Methodology

**Residual definition**: `residual = actual_margin − prior_margin`

Where `prior_margin` is the RATING_MARGIN_PRIOR for the race's expert rating at the time of the election.

**Optimal bucket adjustment**: For each bucket, the optimal adjustment is the mean residual across all races in that bucket:

```
adj_b = mean({residual_i : bucket(race_i) == b})
```

This is the Bayes-optimal constant prediction (minimizes MSE) when the within-bucket residuals are approximately i.i.d.

**RMSE comparison**: `sqrt(mean((residual_i − adj_{bucket(i)})²))` for each granularity. Lower is better.

**Limitation**: This is in-sample RMSE at n=43. Out-of-sample performance (proper cross-validation) will be higher.

---

## 7. House Model

**Source**: `src/models/house.py` — `HouseModel`
**Maturity**: `NOWCAST`

### 7.1 National Projection

Projects Democratic House seats from the generic ballot:

```
projected_dem_seats = 218 + gb_margin × 5.5
seat_range_low  = projected − 12
seat_range_high = projected + 12
```

The ±12 seat uncertainty band reflects the historical root-mean-squared error of the generic-ballot-to-seats regression across 1998–2022 midterms. It is a fixed SE, not a model-estimated one — a proper uncertainty band would account for heteroskedasticity (larger errors in near-even elections).

### 7.2 District-Level Tracking

`district_average(polls, state, district)` computes a polling average for a specific district by filtering on subjects containing `"{state}-{district}"`. No structural prior for districts is implemented yet.

---

## 8. Fundamentals & Candidate Quality

**Source**: `src/models/candidate_quality.py` — `CandidateQualityModel`
**Source**: `src/analysis/fundamentals.py` — `FundamentalsSnapshot`
**Maturity**: `NOWCAST`

### 8.1 Fundamentals Baseline

The structural predictor of Senate outcomes from non-polling inputs:

```
expected_dem_share = 50.0
  + partisan_lean × 0.85          # state PVI → vote share
  + gb_margin × 0.40              # national environment
  + incumbency_effect             # D incumbent +3.0, R incumbent −3.0
  + approval_delta × 0.15         # (approval − 50) × same-party direction
  + midterm_penalty               # −2.5 pp for president's party in midterms
```

Coefficients are rough OLS estimates from 2006–2022 Senate races. They have not been formally re-estimated and should be treated as informed priors rather than precise parameters.

**Partisan lean** (`partisan_lean`): Cook Partisan Voting Index or equivalent. Positive = Democratic lean. The 0.85 coefficient means a D+5 state predicts roughly 4.3 pp of Dem vote share above baseline.

**Generic ballot** (`generic_ballot_margin`): The national D-R generic ballot margin at the time of the election. The 0.40 coefficient captures the translation from national preference to state-level outcomes — attenuated relative to 1.0 because Senate voters split their tickets more than House voters.

**Incumbency**: +3.0 pp for Democratic incumbents, −3.0 for Republican (net +3 for the incumbent regardless of party). The open-seat effect is 0.0 — open seats revert to structural baseline.

**Presidential approval**: `(approval − 50) × 0.15`. A president at 45% approval (−5 from 50) creates a 0.75 pp headwind for same-party Senate candidates. The effect is modest but directionally consistent with the literature (Jacobson 2015).

### 8.2 Candidate Quality (WAR)

Candidate quality (`CandidateQuality`) is computed post-election as:

```
quality_score = actual_vote_share − expected_vote_share
```

A positive score means the candidate outperformed what a generic candidate of their party would have achieved in the same structural environment. This is equivalent to Wins Above Replacement in baseball analytics.

The vibes model is designed to provide a *pre-election proxy* for this quality score, using media sentiment as the leading indicator. The calibration (§6.7) shows the current proxy explains very little of the variance in quality scores — the improved scorer is essential before WAR estimates are meaningful.

---

## 9. Data Sources

| Source | What it provides | Module | Polling types |
|--------|-----------------|--------|---------------|
| VoteHub | Aggregated polling database | `src/data/votehub.py` | All |
| RealClearPolitics | Polling averages and raw polls | `src/data/rcp.py` | All |
| 270toWin / FiftyPlusOne | State-level race polling | `src/data/fiftyplusone.py` | Head-to-head |
| Congress.gov | Incumbent metadata | `src/data/congress_gov.py` | — |
| NYT Article Search API | Pre-election media sentiment | `src/data/nyt.py` | — |

All sources normalize to the `Poll` dataclass (`src/data/base.py`) with a common `PollType`, `Population`, and `PollAnswer` schema.

---

## 10. Known Gaps & Roadmap

| Phase | Feature | Status |
|-------|---------|--------|
| 1 | Polling average engine + data sources | ✅ Complete |
| 2 | Approval + generic ballot trackers | ✅ Complete |
| 3 | State-space model (PyMC) | ✅ Implemented, validation ongoing |
| 4 | Replace weighted avg with state-space as primary | 🔲 Pending |
| 5 | Senate map NOWCAST | ✅ Complete |
| 6 | House-effect correction pipeline | 🔲 Pending |
| 7 | Vibes model — improved scorer (transformers) | 🔲 Pending |
| 8 | Full simulation (correlated state errors, 10k draws) | 🔲 Pending |
| 9 | Win probability calibration (Brier scores vs. historical) | 🔲 Pending |
| 10 | Public dashboard (Streamlit) | 🔲 Partial (approval chart live) |

### Biggest open methodological questions

1. **Correlated Senate errors**: swing states share wave risk. The current model treats each race independently. A proper simulation draws a national-environment shock from a distribution and applies it proportionally across all races before drawing individual errors. Without this, the Senate majority probability will be poorly calibrated.

2. **Primary-complete flag**: `primaries_complete` on each `SenateRaceInfo` is hardcoded to `False`. This should be set automatically via a primaries database or manual update process as races develop.

3. **Rating freshness**: `SENATE_RACES_2026` ratings reflect early 2026 conditions. They should be updated as new information arrives (polling, candidate announcements, fundraising). A ratings-update pipeline is not yet implemented.

4. **Vibes scorer**: As documented in the calibration report, the keyword scorer needs replacement with a named-entity-aware classifier before vibes adjustments are publishable.

---

*Methodology subject to revision as models are validated and improved. For questions or critiques, open an issue at the project repository.*
