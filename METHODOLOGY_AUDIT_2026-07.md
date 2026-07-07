# Methodology Audit — July 2026

_Independent code-level verification of the seven findings in the June 2026
data-science briefing ("Election Oracle — DS Status & Methodology-Improvement
Briefing"). Each claim was checked against the implementation on this branch
(206/206 tests passing). Verdicts: **CONFIRMED**, **PARTIALLY CONFIRMED**, or
**CORRECTED** where the briefing's framing doesn't match the code._

---

## Verdict summary

| # | Finding | Verdict | Key nuance |
|---|---------|---------|------------|
| 1 | Evaluator two-party unit mismatch | **CONFIRMED** — plus a second bug in the win rule | No `trained_params.json` exists, so no corrupted fit is in production; the bug poisons any *future* training run |
| 2 | Republican derived as `100 − dem` | **CONFIRMED** (opt-in paths only) | The approval state-space path is the worst instance; the *published* tracker path is unaffected |
| 3 | Static seat conversion | **CONFIRMED** | Constants published daily in `generic_ballot.json`, labeled illustrative |
| 4 | Unknown-pollster default inconsistency | **PARTIALLY CONFIRMED / reframed** | Production already uses the documented 1.408 default; the real defect is a **training/serving ratings skew** |
| 5 | Rank-1 correlation, Gaussian tails | **CONFIRMED** | σ's are empirically calibrated, which mitigates but doesn't fix tail thinness |
| 6 | No poll deduplication | **PARTIALLY CONFIRMED** | Exact-row dedup exists; tracking-poll overlap and multi-population releases are not handled |
| 7 | Hand-set governance knobs | **CONFIRMED** | One knob (`calibration_bias_weight`) has documented reasoning; none have sensitivity analysis |

Also verified: the look-ahead guard (`src/models/polling_average.py:163`), the
calibration file's headline numbers (bias −2.497, σ_nat 2.873, σ_race 5.139,
Brier 0.0602, win-accuracy 0.898, n=98), the CI skip of the state-space model
(`scripts/export_json.py:72`), and the absence of rolling-origin CV in the
optimizer (`src/training/optimizer.py:70–89` scores in-sample RMSE on the full
race pool).

---

## Finding 1 — Evaluator unit mismatch: CONFIRMED (high priority)

**Evidence.** `src/training/evaluator.py:90` computes
`error = pred_dem - race.dem_two_party_share`. The left side is a weighted
average of **raw** poll percentages: `PollingAverageEngine.compute_average`
averages `answer.pct` as-is (`src/models/polling_average.py:189–198`), and the
training loader passes FTE archive percentages through unmodified
(`src/training/data_loader.py:197`). The right side is the two-party-normalized
result, `d/(d+r)·100` (`src/data/mit_results.py:342,390`).

A raw Dem share carries undecided/third-party (typically 4–10pp of the sample),
so it runs systematically below the two-party result even when the poll is
perfectly accurate. Every parameter set is scored against an objective with
this bias baked in, and the bias is not constant — it varies with how each
parameter set weights polls with different undecided shares — so it distorts
*which* parameters win, not just the reported RMSE level.

**Second bug, same root cause.** `evaluator.py:94` scores the winner call as
`pred_dem > 50` on the raw share. A candidate polling 48–44 with 8% undecided
is counted as a predicted **loss**. `win_accuracy` therefore misclassifies most
close races toward "R wins" and is not a usable metric as computed.

**Correction to the briefing.** The briefing warns "the current
`trained_params.json` may be fit against a biased objective." **That file does
not exist in the repo** — `PollingAverageParams.load_trained()`
(`polling_average.py:63–69`) falls back to hand-set defaults, and `config/`
contains no `trained_params.json`. So production has never run on parameters
from the corrupted objective. The fix is a prerequisite for the first real
training run, not a hotfix to shipped numbers.

**Fix.** Two-party-normalize the prediction before differencing:
`pred_2p = dem/(dem+rep)·100` (both averages are already available from
`result.averages`), and change the win rule to `pred_2p > 50`. Alternatively
store `actual_dem_share` (raw) as the target — but two-party is the cleaner
regression target, as the loader's own comment notes.

---

## Finding 2 — Complement-derived opponent: CONFIRMED, worst in approval

Three instances, none in the published tracker path:

- `src/models/generic_ballot.py:115` — `rep_mean = 100.0 - dem_mean` in
  `current_estimate_ss` (state-space path). With ~5–8% undecided/other, this
  overstates the Republican share and inflates the margin, which then feeds
  the seat translation as `margin = 2·dem_mean − 100`.
- `src/models/approval.py:128,136` — the state-space approval path derives
  `dis_mean = 100.0 - mean` and mirrors the Approve CI. Approve+Disapprove
  totals ~85–95 in practice, so published Disapprove would be overstated by
  5–15pp **and its CI is fabricated**. This is the most severe instance.
- `src/models/candidate_quality.py:149,182` — same pattern in expected/actual
  share computation.

**What the briefing missed:** the production path is clean. `current_ballot` →
`_result_to_snapshot` (`generic_ballot.py:135–172`) averages Dem and Rep
choices separately, and the CI export (`scripts/export_json.py`) only calls the
weighted-average paths. So today's published numbers do not carry this bias —
but the bias sits exactly on the state-space path that Tier 2 of the roadmap
wants to promote to production. **Fixing this is a hard gate for Tier 2**, not
an independent cleanup: fit Disapprove as its own series (or model the pair
jointly), don't complement it.

---

## Finding 3 — Static seat conversion: CONFIRMED

`generic_ballot.py:25–26` (`5.5` seats/point, baseline `218`), clamp to
`[150, 285]` at lines 120 and 149. The module's own TODO acknowledges the
limitation, the CLI prints "[illustrative — not a probability]"
(`scripts/run_models.py:128`), and the review (Error 2 / gap 2) already flags
it. All three of the briefing's sub-points hold: no historical
generic-ballot-overstates-Dems correction, no incumbency/uncontested-seat
structure, no uncertainty band. Note the seat numbers *are* exported twice
daily into `generic_ballot.json` via `current_ballot`, so the illustrative
framing must survive into the web UI for this to stay honest.

---

## Finding 4 — Pollster-rating default: REFRAMED — the real bug is training/serving skew

**The narrow claim is true but mostly moot in production.** The engine's dict
fallback is `1.5` (`polling_average.py:232`) versus the documented
survivorship-adjusted default, which computes to **1.408**
(`src/data/pollster_ratings.py:67–74`). However, both production entry points
(`scripts/export_json.py`, `scripts/run_models.py`) build engines via
`_build_engine_from_polls` (`run_models.py:68–78`), which calls
`build_ratings_dict` over every pollster present in the feed — so unknown
pollsters **do** receive 1.408 in the published pipeline. The 1.5 fallback only
fires for engines constructed without explicit ratings.

**Where that actually bites: the training path.** The evaluator constructs the
engine bare (`evaluator.py:69`), which loads `config/pollster_ratings.json` —
a hand-maintained 21-pollster table (last updated 2026-02-22) on a **different
scale** from the Phase 2 PPM-derived ratings production uses:

| Pollster | JSON (training/default path) | PPM-derived (production path) |
|---|---|---|
| Marist College | 2.9 | 1.768 |
| Fox News | 2.6 | 1.558 |
| Rasmussen Reports | 1.5 | 1.168 |
| Trafalgar Group | 1.3 | 1.048 |
| Morning Consult | 2.2 | 1.258 |

Worse, historical FTE-archive pollsters absent from the 21-name JSON all get a
flat 1.5 in training, so quality weighting is nearly uniform there. The trained
`pollster_quality_exponent` is therefore fit under a rating distribution that
does not exist in production — a classic training/serving skew that would
silently invalidate the parameter transfer even after Finding 1 is fixed.

**Fix.** Single source of truth: generate `config/pollster_ratings.json` from
`build_ratings_dict()` (or make `_load_pollster_ratings` delegate to it), and
change the dict-miss fallback from `1.5` to `_UNKNOWN_DEFAULT`.

---

## Finding 5 — Rank-1 correlation, Gaussian tails: CONFIRMED

`src/models/senate_simulation.py:240–244`: one shared national draw
`N(0, σ_nat)` plus independent per-race `N(0, σ_race)`. No regional or
demographic covariance blocks; Gaussian tails throughout.

Mitigating context the briefing under-credits: both σ's are refit monthly from
98 historical races (`.github/workflows/calibrate.yml` →
`config/forecast_calibration.json`, σ_nat 2.873 / σ_race 5.139), and the
simulation covers only the configured competitive races, so the damage is
bounded relative to a 50-state presidential model. Still, correlated regional
misses (the 2016-style Midwest cluster) are underrepresented, thinning the
seat-distribution tails and overtightening the control probability. The
calibration file already contains `state_pollster_bias` and
`cross_office_state_bias` tables — the raw material for an empirical low-rank
covariance is sitting on disk. Student-t national/race draws are a two-line
change worth backtesting.

---

## Finding 6 — Poll deduplication: PARTIALLY CONFIRMED

There is more dedup than the briefing implies, but it only catches the trivial
case. `VoteHubCsvLoader` builds an ID from (pollster, dates, subject, sponsor,
population) and drops exact repeats (`src/data/votehub_csv.py:215–223`);
`mit_results.py:317–350` dedups the results side; the training loader groups by
FTE `poll_id`.

Not handled, confirmed by inspection of the ingestion path
(`scripts/refresh_data.py`, `votehub_csv.py`):

- **Overlapping tracking-poll windows** — every release of a daily/weekly
  tracker (Rasmussen, Morning Consult) enters with full weight; recency decay
  dilutes but does not remove the overweighting, and these are precisely the
  firms with the largest house effects.
- **Multi-population releases** — the same fieldwork released as both LV and RV
  rows enters twice (the ID key deliberately separates populations).
- **Sponsor variants** of the same fieldwork.

The review's own "Data policy" section lists this as an open question, so the
briefing's claim that no policy exists is accurate. Suggested rule: one poll
per (pollster, overlapping field period, race), preferring LV, newest release.

---

## Finding 7 — Hand-set governance knobs: CONFIRMED

All four cited knobs verified, plus three more in the same family:

| Knob | Value | Where |
|---|---|---|
| `calibration_bias_weight` | 0.5 | `config/senate_2026.json` + `export_json.py:518` |
| `blend_k` (fundamentals) | 3.0 | `senate_2026.json` + `export_json.py:448` |
| `market_weight` | 0.25 | `senate_simulation.py:45` (export uses the default) |
| `senate_responsiveness` | 1.0 | `senate_2026.json` |
| `generic_weight` / `approval_weight` | 0.6 / 0.4 | `senate_2026.json` |
| `approval_to_margin_coef` | 0.3 | `senate_2026.json` |
| `pres_weight_recent` | 0.75 | `senate_2026.json` |

Credit where due: `calibration_bias_weight` carries an explicit rationale in
the config (halved to avoid double-counting the Dem-overstatement the
fundamentals blend also corrects) — that's a judgment call, documented. But
none of the seven has a sensitivity analysis, and each moves the headline
control probability. Minimum bar: a script that sweeps each knob ±50% and
reports Δ(dem_control_prob), committed alongside the calibration output.

---

## Pipeline facts that change the roadmap's framing

1. **"Too heavy for CI" looks stale.** The Phase 3 verification recorded
   ~100 seconds for a full state-space fit (683 polls, 2 chains). The refresh
   workflow runs twice daily on a schedule — an extra ~3–4 minutes (approval +
   generic ballot, plus PyMC import) is well within budget. Tier 2 may need no
   caching cleverness at all; try simply enabling it in
   `scripts/export_json.py` behind a runtime guard and measuring.
2. **Tier 1's "re-run parameter training" is really "run the first valid
   training."** With no `trained_params.json` on disk, nothing trained is in
   production; defaults are. Fix Findings 1 and 4 first, then train with
   rolling-origin CV from the start (train cycles ≤ N−1, test N) rather than
   retrofitting it later — the optimizer currently overfits by construction.
3. **The vibes overlay is currently a no-op.** `export_json.py` notes the vibes
   data is a neutral placeholder until the NYT pipeline runs with a key, so
   `dem_control_prob_with_vibes` equals the base forecast today. "Hold until
   validated" is right, and cheap — it's not actually doing anything yet.

## Publish / hold — audit position

Concur with the briefing's split, with two sharpened caveats:

- **Publish:** approval tracker, generic-ballot tracker (as "polling
  averages"), Senate per-race averages, Senate-control NOWCAST with its
  reliability curve. The calibration backing (98 races, Brier 0.060) is real.
  Caveat 1: the NOWCAST's tails are thin (Finding 5) — present the control
  probability with the seat *distribution*, not just the headline number.
- **Hold:** House/Governor/2028 stubs; any seat-probability claim from the
  generic ballot until the slope is refit with uncertainty (Finding 3); the
  vibes signal (unvalidated and currently placeholder-fed). Caveat 2: do not
  promote the state-space estimates to the published path until the
  complement-derivation in `approval.py`/`generic_ballot.py` (Finding 2) is
  fixed — otherwise Tier 2 ships a new bias while removing an old one.

---

## Implementation status (July 2026, this branch)

Items 1–3 and 6 of the priority order below are **implemented**:

- **Evaluator** (`evaluator.py`): predictions are two-party-normalized before
  differencing, and the winner call uses the two-party share.
- **Ratings unified**: the engine's default ratings now come from
  `build_ratings_dict()` (same source as production), the dict-miss fallback
  is `_UNKNOWN_DEFAULT` (1.408), `config/pollster_ratings.json` is a generated
  snapshot of that pool, and `PollsterWeightManager` uses the same default.
- **Complement derivation removed**: the state-space paths fit Disapprove and
  the Republican series as their own latent states with real CIs;
  `candidate_quality.py` documents its two-party-share contract.
- **Dedup rule** (`src/data/base.py: dedupe_polls`, applied in both CSV
  loaders): collapses multi-population releases of the same fieldwork
  (LV > RV > A) and overlapping tracking-poll windows (keep newest release).
  Effect on the live approval feed: 2,906 → 1,825 rows.
- **New finding fixed — subject leakage**: the approval feed also carries
  Congress (703), Supreme Court (338), and JD Vance (33) polls, and the
  published presidential average was mixing them in. `PresidentialApprovalModel`
  now screens to presidential subjects (blank subjects pass for legacy feeds).
  Published approval moved from 37.9/58.1 to 39.8/57.6 (n=751), and the
  corrected net approval flows through the national environment into the
  Senate control simulation (0.287 → 0.280).

**Second wave (same branch): items 4, 5, 7 and 8 are now implemented too.**

- **Item 4 — state-space in production.** `export_json.py --state-space` fits
  the Jackman model for Approve/Disapprove and Dem/Rep and publishes a
  `state_space` block (current + full posterior trend + house effects +
  convergence) in `approval.json` / `generic_ballot.json`; the twice-daily
  refresh workflow now passes the flag, with graceful `available:false`
  degradation if PyMC or the fit fails. Measured runtime: ~6.5 min for both
  approval fits (1000+1000 draws, converged) — "too heavy for CI" was stale.
- **Item 5 — rolling-origin CV training.** `src/training/cross_validation.py`
  locks the protocol: Optuna minimizes mean per-cycle RMSE on all cycles
  except a final holdout; the holdout is scored once; `trained_params.json`
  is written only when the winner beats the hand-set defaults there (pass/
  fail gate). MLflow is now optional. The poll archive is unreachable from
  this sandbox (CI can reach it), so the actual run is wired as
  `.github/workflows/train_parameters.yml` (on-demand + quarterly).
- **Item 7 — sensitivity sweep.** `scripts/sensitivity_sweep.py` runs every
  governance knob through the production forecast path; results committed in
  `config/sensitivity_analysis.json`. Ranked by impact on P(Dem control):
  `senate_responsiveness` (spread 0.33 across 0.5–1.5 — by far the most
  consequential hand-set choice), `calibration_bias_weight` (0.16),
  `pres_weight_recent` (0.09), `tail_dof` (0.06), `blend_k` (0.04),
  `market_weight` (0.02), generic/approval mix (0.002).
- **Item 8 — fat tails + seat slope.** `SenateControlSimulator` supports
  variance-matched Student-t error via a shared chi-square scale shock
  (a fat-tail event is a correlated across-the-board miss), with the analytic
  marginal, effective-margin inversion and simulation all consistent.
  Backtested on the 98 calibration races: t(5) Brier 0.0591 / log-loss 0.1905
  vs Gaussian 0.0602 / 0.1952 — enabled in production (`tail_dof: 5`), and the
  comparison now recomputes monthly inside `calibrate_forecast.py`
  (`tail_comparison` block). The seat conversion is now fitted from
  1998–2024 national results (`scripts/fit_seat_conversion.py` →
  `config/seat_conversion.json`): **3.03 ± 0.43** seats/point around a
  **212-seat** neutral baseline with a ±8.6-seat residual SD published as an
  80% band — the hand-set 5.5/218 overstated responsiveness by ~80%.
  Headline effect: P(Dem control) 0.280 → **0.255** under t(5).

Still open: the regional/demographic **error covariance** upgrade (Finding 5's
low-rank factor structure). The calibration archive's `state_pollster_bias` /
`cross_office_state_bias` tables are the raw material, but with only ~13
competitive races per cycle a fitted covariance would be noise-dominated;
revisit when the archive spans another cycle. The generic-ballot-overstates-
Dems polling bias also remains uncorrected in the seat translation (needs
archived GB averages per cycle) — seat outputs stay labeled illustrative.

## Revised priority order

1. Fix evaluator two-party normalization **and** the `> 50` win rule
   (`evaluator.py:90,94`).
2. Unify pollster ratings behind `build_ratings_dict` and retire the stale
   JSON scale (training/serving skew, Finding 4-as-reframed).
3. Fix complement-derived Disapprove/Rep in the state-space snapshot paths
   (`approval.py:128`, `generic_ballot.py:115`) — gate for Tier 2.
4. Enable the state-space model in the twice-daily refresh; measure runtime
   before assuming it needs a cache.
5. Run the first parameter training with rolling-origin CV; commit
   `trained_params.json` only with out-of-cycle metrics attached.
6. Dedup rule for tracking polls and multi-population releases (Finding 6).
7. Sensitivity sweep for the seven governance knobs (Finding 7).
8. Empirical covariance / Student-t tails in the simulation (Finding 5);
   refit the seat slope with uncertainty (Finding 3).
