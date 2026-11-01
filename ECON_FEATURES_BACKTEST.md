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

## Results so far (lean only; unemployment pending)

| Model | Held-out RMSE | Brier | Log-loss | Win accuracy |
|---|---|---|---|---|
| M0 constant bias | 6.14 | 0.0681 | 0.2111 | 0.90 |
| M1 + lean | **5.46** | **0.0537** | **0.1696** | 0.91 |

In-sample, the lean coefficient is **+0.16 points of poll error per point of
presidential margin** (standard error 0.026, t = 6.2). Read it this way: in a
state Trump carried by 20, the polls have understated the Republican by about
3 points *more* than the constant bias assumes; in a state Harris carried by
10 they have understated the Democrat by about 1.6 points relative to it. With
lean in the model, the constant shrinks from −2.5 to −1.9.

By cycle, held-out RMSE:

| Cycle | M0 | M1 |
|---|---|---|
| 2018 | 7.34 | 6.66 |
| 2020 | 6.60 | 4.95 |
| 2022 | 6.40 | 4.83 |
| 2024 | 3.77 | 5.37 |

Three of four cycles improve substantially. 2024 gets worse: polls that year
were unusually accurate and a model trained on 2018–2022 over-corrected. That
is the right kind of failure to know about before trusting the feature, and a
reason to apply any lean term at reduced weight, as the model already does
with the constant bias.

**Unemployment models (M2, M3) have not run.** The BLS API is not reachable
from the development container. Launch the *Economic-features backtest*
workflow in GitHub Actions on this branch; it fetches the September
unemployment panel, saves it to `data/historical/state_unemployment_sep.json`,
re-runs the script and commits the refreshed JSON here. Then compare M2/M3
against the M0/M1 rows marked *(unemp subset)* in the output. Their
coefficients are signed so a positive value means the economy moved votes in
the direction the theory predicts; the bar for adoption should be a held-out
Brier improvement over M1, not just a significant t-statistic.

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
3. **A lean-dependent bias: promising, worth a proper trial next cycle.**
   Run the workflow to settle the unemployment question, then re-score
   against the real blended baseline. If it still wins on held-out Brier, fold
   `lean × 0.16` into the bias term at the same half weight the constant gets
   today, and let the next calibration run refit it.
