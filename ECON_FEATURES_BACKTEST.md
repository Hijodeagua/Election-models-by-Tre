# Should the Senate forecast use economic or structural features?

*Research branch, November 2026. Nothing here changes the live forecast.*

## The question

The daily and weekly EconVitals briefings track national macro indicators:
GDP, core PCE, the activity and inflation surprise indexes, consumer
confidence, unemployment. Would feeding features like that into the Senate
model make it better?

The live model corrects each race's polling average with one **constant
bias** (≈ −2.5 points, the historical Democratic overstatement, applied at
half weight) and blends it with a fundamentals prior (presidential lean plus
the national swing). This backtest asks whether that bias should instead be a
function of features the model does not use, and scores every candidate
**out of sample**.

## Why national macro features are not testable here

Features like GDP growth or consumer sentiment take **one value per cycle**.
The calibration set has four cycles (2018, 2020, 2022, 2024). Four
observations cannot separate "the economy" from the national environment the
model already prices through the generic ballot and presidential approval,
which are themselves downstream of the economy. Any fitted coefficient would
be noise dressed as signal. The honest conclusion is that national macro
features belong in the national-environment term, where they already are.

What *can* be tested is anything that varies **across states within a
cycle**, because the 98 calibration races give real degrees of freedom. Two
candidates:

| Feature | What it tests | Source |
|---|---|---|
| `lean` — the state's Dem − Rep presidential margin in the most recent election *before* the race | "Polls miss toward the state's lean" (Republicans understated in red states, Democrats in blue ones) | County returns summed by state; 2016 for the 2018/2020 cycles, 2020 for 2022/2024 |
| `Δunemp` / `rel_unemp` — the change in state unemployment over the year to September, and the state rate minus the U.S. rate, both signed by the president's party | Retrospective economic voting beyond what polls capture | BLS LAUS, September values |

## Method

`scripts/backtest_econ_features.py` fits nested OLS models of the poll
error (actual − poll margin, Dem − Rep points) on the 98 races:

- **M0** constant bias (what the forecast does today)
- **M1** bias + lean
- **M2** M1 + Δunemp
- **M3** M2 + rel_unemp

Each is scored with **leave-one-cycle-out** validation: fit on three cycles,
predict the fourth, pool the 98 held-out residuals. RMSE scores the margin;
Brier and log-loss score win probabilities built the same way the live model
does (bias-corrected margin, calibrated total sigma 5.9, Student-t with 5
degrees of freedom).

Results live in `config/econ_features_backtest.json`. Unit tests for the
statistics are in `tests/test_backtest_econ_features.py`.

## Results

Full run (BLS panel fetched by the workflow, all 98 races):

| Model | Held-out RMSE | Brier | Log-loss | Win accuracy |
|---|---|---|---|---|
| M0 constant bias | 6.14 | 0.0681 | 0.2111 | 0.90 |
| M1 + lean | 5.46 | 0.0537 | 0.1696 | 0.91 |
| M2 + Δunemp | 5.37 | 0.0452 | 0.1519 | 0.93 |
| M3 + rel. unemp | **5.30** | **0.0427** | **0.1479** | 0.95 |

Taken at face value, every added feature helps. Two things say not to take it
at face value.

**The unemployment sign is backwards.** `Δunemp` is signed so that a positive
coefficient means rising unemployment moved votes *away* from the
president's party, as retrospective voting predicts. The fitted coefficient
is **−0.98** (t = −3.5): where unemployment rose most under the president,
the president's party *beat* its polls by more. That is not economic voting;
it is something else wearing its clothes.

**That something else is 2020.** September unemployment rose in every state
that year, by 0.2 to 8.7 points (mean +3.5), against changes of under a point
in 2018, 2022 and 2024. Within 2020, Δunemp was a Republican president's
feature, and 2020 was also the cycle in which polls overstated Democrats by
6.5 points on average. So Δunemp is largely a proxy for "this race was in
2020", and the cross-state spread of the pandemic shock happened to line up
with the cross-state spread of that year's polling miss. The robustness refit
without 2020 (72 races) settles it:

| Model (no 2020) | Held-out RMSE | Brier | Log-loss |
|---|---|---|---|
| M0 constant bias | 5.70 | 0.0541 | 0.1805 |
| M1 + lean | 5.66 | **0.0467** | **0.1567** |
| M2 + Δunemp | 8.23 | 0.1041 | 0.3209 |
| M3 + rel. unemp | 8.37 | 0.1057 | 0.3380 |

Without 2020 the unemployment models are *much worse* out of sample, and
the Δunemp coefficient falls to −0.71 with t = −0.9. `rel_unemp` (state minus
national rate) has the theoretically right sign in both fits, +0.80, but
never clears t = 2 and adds nothing once Δunemp is gone.

**Lean survives.** Without 2020 the lean coefficient is +0.14 (t = 4.3) and
it still improves held-out Brier and log-loss, though the RMSE gain shrinks
to almost nothing. In-sample on all four cycles it is **+0.16 points of
poll error per point of presidential margin** (t = 6.2): in a state Trump
carried by 20, polls have understated the Republican by about 3 points more
than the constant bias assumes. With lean in the model the constant shrinks
from −2.5 to −1.9.

By cycle, held-out RMSE for the lean model against the constant:

| Cycle | M0 | M1 |
|---|---|---|
| 2018 | 7.34 | 6.66 |
| 2020 | 6.60 | 4.95 |
| 2022 | 6.40 | 4.83 |
| 2024 | 3.77 | 5.37 |

Three of four cycles improve substantially. 2024 gets worse: polls that year
were unusually accurate and a model trained on 2018–2022 over-corrected. That
is a reason to apply any lean term at reduced weight, as the model already
does with the constant bias.

## Caveats

- **The live model is not M0.** It already blends polls with a fundamentals
  prior built on the same presidential lean, at weight k/(k+n) with k = 3.
  With the 10–30 polls typical of a competitive race in the final three weeks
  that prior carries 10–25% of the weight, so part of the lean effect is
  captured today. The calibration rows do not store each race's poll count or
  that cycle's national swing, so this backtest cannot reproduce the blend
  exactly. The next step, if the result holds up, is to add the blended
  forecast to the calibration rows and re-score M1 against *that* baseline.
- **98 races, four cycles.** The lean effect is large and consistent enough
  to survive this, but the 2024 reversal shows how much a single cycle can
  move things.
- **2016 county returns** come from a community-maintained file with small
  known discrepancies (Georgia reads R+5.7 against an official R+5.1). Fine
  for a control variable; recompute from official returns before any
  production use.

## Recommendation

1. **Do not recalculate the live forecast before this election.** Two days
   out, polls dominate; nothing here would move a call.
2. **National macro features (EconVitals-style): no.** Not identifiable with
   four cycles, and already represented through approval and the generic
   ballot.
3. **State unemployment: no.** The apparent gain is a 2020 artefact with the
   wrong sign; without that cycle it hurts badly. Do not add it.
4. **A lean-dependent bias: promising, worth a proper trial next cycle.**
   Re-score it against the real blended baseline (see caveats). If it still
   wins on held-out Brier, fold `lean × 0.16` into the bias term at the same
   half weight the constant gets today, and let the next calibration run
   refit it.
