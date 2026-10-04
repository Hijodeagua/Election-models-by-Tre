# Senate Forecast Reassessment — October 2026

_Prompted by the question "are we undercounting the Democrats' odds?" Answer:
yes, for three concrete reasons found in the code and one defensible modelling
choice, plus two places the fix cuts the other way. Everything below was
verified against the pipeline on 2026-10-04 (30 days before the election)._

## Headline

| | Before | After |
|---|---|---|
| P(Democratic Senate control) | 45% | **53%** |
| Mean Democratic seats | 50.2 | 50.4 |
| Polymarket, chamber control | 64.5% | 64.5% |

The model still sits well under the market. The remaining gap is mostly
Maine, Alaska and Iowa (see "What still holds the number down").

## What was wrong

### 1. Texas and Maine were blended against the wrong markets (bug)

`PolymarketClient.fetch_markets` accepted any event whose title contained
`("texas", "senate")`. Polymarket's search ranked **"Which party will win the
Texas State Senate in 2026?"** — the state legislature — above the U.S. Senate
winner market, so the committed snapshot carried a 3.65% "Democrat" price for
Texas. At 25% market weight that dragged Talarico from a 55% polls-only
probability to 42%. Maine had the same problem in the other direction (an 84%
state-senate price lifting Jackson).

Fix: events whose title or slug mention a state legislature are rejected
(`NON_FEDERAL_EVENT_TOKENS`), candidate-named outcomes ("Talarico"/"Paxton")
now resolve to a party through the configured nominee names, the two bad rows
are removed from `data/fallback/market_odds.csv`, and the refresh job passes
nominee names to the client. Until the next successful market fetch Texas and
Maine run polls-only, which is the honest state.

### 2. Michigan and New Hampshire were ignoring every poll (bug)

`config/senate_2026.json` still named Haley Stevens (MI) and Scott Brown (NH).
Neither appears in the polls, the CSV path carries no party tags, so
`_resolve_nominee` returned nothing, `dem_margin` was `None`, and the forecast
fell back to the **fundamentals prior alone**: MI D+8.8 and NH D+13.1, versus
polling averages of roughly D+3 (El-Sayed) and D+6 (Pappas). Forty-one and
twenty-four polls were being discarded.

Fix: nominee names updated (El-Sayed, Sununu); when exactly one side of a
head-to-head resolves, the other nominee is now the top remaining name
(`_top_other_candidate`, guarded against "Undecided"); the forecast inputs use
the resolved names rather than the raw config names, so the page shows the
right candidates.

This fix **lowers** Democratic odds in both states (MI 87% → 73%, NH 95% →
88%). It is kept because it is correct.

### 3. The systematic poll-bias term was the wrong cycle's bias (modelling)

The calibration fits a pooled 2018–2024 mean error of **−2.5 pts** (polls too
Democratic), applied at half weight (−1.24 pts on every race). That pooled
figure is dominated by 2020:

| Cycle | Mean error (actual − poll) | n |
|---|---|---|
| 2018 (midterm) | +0.12 | 22 |
| 2020 | −6.48 | 26 |
| 2022 (midterm) | −0.93 | 25 |
| 2024 | −2.18 | 25 |
| **Midterms only** | **−0.44** | 47 |
| Midterms, competitive races (|margin| < 15) | +0.45 | 31 |

Polling error does not carry a predictable sign from one cycle to the next
(the national-error σ already prices a correlated miss), and the two midterms
in our own calibration set show essentially no bias. A new config switch
`forecast.bias_cycle_type = "midterm"` averages only the matching cycles. The
applied bias is now −0.44 × 0.5 = **−0.22 pts** (was −1.24). This is the
largest single driver of the headline move and it is grounded in the
project's own backtest data, not a judgment call.

### 4. No forward-looking uncertainty 30 days out (modelling)

The simulation was a pure nowcast: σ calibrated on polls from the final 21
days, applied a month early. A campaign-drift term now widens the national
error by `0.35·√(days to election)` in quadrature (≈1.9 pts today, ≈1 pt a
week out, 0 on election day). Its net effect on P(control) today is nil
(sensitivity sweep: 53.4% with no drift vs 53.2% with it) — the wider national
error pulls favourites toward 50% but also raises cross-race correlation
(σ_nat 2.90 → 3.48; implied correlation 0.24 → 0.31), and the two roughly
cancel. It is kept because it is the honest treatment of a month-out forecast.

The re-run sensitivity sweep (`config/sensitivity_analysis.json`) now ranks
`bias_cycle_type` as the single most consequential knob: pooled bias 43%,
midterm-only 53%, presidential-only 34%. `senate_responsiveness` (how much of
the national swing reaches the fundamentals prior) is second at ±8 pts across
its grid.

## Per-race effect

| Race | Polls-only P(D) before → after | Blended before → after | Note |
|---|---|---|---|
| Georgia | 91% → 92% | 93% → 94% | |
| Michigan | 92% → 73% | 87% → 73% | was fundamentals-only; now polls (El-Sayed +3.3) |
| North Carolina | 93% → 94% | 94% → 95% | |
| Maine | 65% → 71% | 70% → 71% | wrong market removed |
| New Hampshire | 98% → 88% | 95% → 88% | was fundamentals-only; now polls |
| Ohio | 62% → 69% | 61% → 67% | bias change |
| Texas | 55% → 62% | **42% → 62%** | wrong market removed + bias |
| Iowa | 46% → 54% | 45% → 52% | bias change |
| Alaska | 31% → 40% | 31% → 40% | one poll from March; fundamentals-driven |

## What still holds the number down (not changed, flagged)

* **Maine**: the fundamentals prior (state lean D+7.5 plus the D+9 national
  swing) pulls the race to D+3.1 from a D+1.1 polling average, but Collins'
  incumbency over-performance is not modelled anywhere. Markets price it.
* **Alaska**: a single March poll (Peltola +5) blended 25/75 with a
  fundamentals prior of R+3. Any new poll will move this a lot. Ranked-choice
  voting is not modelled.
* **Iowa / Ohio / Texas**: genuinely close; the model and markets broadly agree
  on Ohio and Iowa.
* **Correlation**: ρ ≈ 0.31 between races is still at the low end of
  published estimates. Democrats need 7 of 9; higher correlation would help
  them. The within-cycle residual σ (5.14) is fitted on all races including
  lopsided ones; restricting to |margin| < 15 gives 4.90, a modest tightening
  not applied here.
* **Race list**: only the nine polled races are simulated. Nebraska (Osborn,
  independent), Florida (special), Kansas and Mississippi have no polls in the
  feed and are treated as safe Republican holds.

## House forecast (new)

A district-level House model now ships alongside (`src/models/house_forecast.py`,
`config/house_2026.json`, `data/fallback/house_districts_2024.csv`, page
`/house-forecast`). Today it reads **P(Democratic House majority) ≈ 96%, mean
≈ 234 seats (80% range 222–245)** from a two-party generic ballot of D+6.3 and
net approval of −23.7, after a −1 pt generic-ballot bias and a net −2 seat
redistricting adjustment. Method and caveats are in the config comments and on
the page; the redistricting entries in particular are **estimates to verify**
before anything is published.

## Files touched

* `src/data/markets.py`, `scripts/refresh_data.py`, `data/fallback/market_odds.csv`
* `config/senate_2026.json`, `scripts/export_json.py`
* `scripts/sensitivity_sweep.py` (two new knobs), `config/sensitivity_analysis.json`
* New: `src/models/house_forecast.py`, `scripts/build_house_districts.py`,
  `config/house_2026.json`, `data/fallback/house_districts_2024.csv`,
  `web/app/house-forecast/`, `web/app/components/SeatHistogram.tsx`,
  `web/app/components/SeatsVotesChart.tsx`
* Tests: `tests/test_markets.py` (+4), `tests/test_senate_forecast_inputs.py`,
  `tests/test_house_forecast.py`

## Features and importances (both forecasts)

### Where candidate names and incumbency enter

Candidate names are **identifiers, not features**. In the Senate pipeline they
are used only to (1) match poll answers to the Democratic/Republican side when
computing a race's Dem−Rep margin, (2) match Wikipedia poll-table columns, and
(3) resolve candidate-named market outcomes to a party. A wrong name therefore
changes *which* numbers are read, never how they are weighted (the MI/NH bug
above). In the House model names are not used at all; `winner_2024` labels
the seat for flip counts.

**Incumbency is not a feature in either forecast.** The Senate fundamentals
prior is state presidential lean (2024 ×0.75 + 2020 ×0.25) plus the national
swing; the House baseline is the district's 2024 margin, which embeds the 2024
incumbent's advantage but does not know whether that incumbent is running
again. `src/models/candidate_quality.py` has an incumbency/WAR model with
hand-set coefficients (±3 pts) but it is not wired into either forecast and
has never been fit.

### Senate — importance of each input (P(Dem control), today)

Per-race leverage = P(control | Dem wins race) − P(control | Dem loses race);
P(tipping) = share of simulations in which the race is the 51st seat.

| Race | P(D) | Leverage | P(tipping) |
|---|---|---|---|
| Iowa | 0.52 | 0.49 | **0.17** |
| Texas | 0.62 | 0.51 | **0.16** |
| Ohio | 0.67 | 0.51 | 0.15 |
| Alaska | 0.40 | 0.46 | 0.15 |
| Maine | 0.71 | 0.51 | 0.14 |
| Michigan | 0.73 | 0.51 | 0.13 |
| New Hampshire | 0.88 | 0.49 | 0.06 |
| Georgia | 0.94 | 0.49 | 0.03 |
| North Carolina | 0.95 | 0.49 | 0.02 |

Leverage is ~0.5 everywhere because Democrats need 7 of 9: every race is
pivotal when lost. The tipping-point column is the useful ranking — the
forecast is decided in Iowa, Texas, Ohio, Alaska and Maine.

Component ablations (baseline 0.532):

| Change | P(control) |
|---|---|
| bias pooled 2018–24 (−1.24) instead of midterm (−0.22) | 0.431 |
| bias 0 | 0.553 |
| race σ 4.0 / 6.5 (base 5.14) | 0.570 / 0.488 |
| Gaussian tails (base t5) | 0.500 |
| no market blend / market weight 0.5 | 0.542 / 0.522 |
| independent races (σ_nat → 0) | 0.546 |
| no campaign drift | 0.534 |

Ranked: bias cycle choice ≫ race-level σ ≈ tail shape > market weight >
correlation structure > drift. From the knob sweep, `senate_responsiveness`
(how much national swing reaches thin-poll races) is the other large one
(0.45–0.63 across 0.5–1.5).

### House — importance of each input (P(Dem majority) 0.958, 233.5 seats)

| Change | P(majority) | Mean seats |
|---|---|---|
| generic ballot two-party D+2 / D+4 / D+8 / D+10 (base D+6.3) | 0.77 / 0.89 / 0.97 / 0.99 | 224 / 228 / 236 / 241 |
| generic-ballot bias 0 / −2 / −3 (base −1) | 0.975 / 0.927 / 0.877 | 236.5 / 230.6 / 227.6 |
| generic-ballot σ 1.5 / 3.5 / 5.0 (base 2.5) | 0.980 / 0.926 / 0.873 | — |
| redistricting none / net −5 (+FL −3) / net −6 (CA fails) | 0.973 / 0.925 / 0.878 | 235.5 / 230.5 / 227.5 |
| campaign drift 0 / 0.6 (base 0.3) | 0.973 / 0.915 | — |
| approval weight 0 / 0.5 (base 0.25) | 0.953 / 0.962 | 232.9 / 234.2 |
| district σ 4.5 / 8.5 (base 6.5) | 0.967 / 0.951 | — |
| Gaussian national tails | 0.946 | — |

Ranked: level of the generic ballot ≫ generic-ballot bias ≈ national σ ≈
redistricting assumptions > drift > tails > approval weight > district σ. The
seat count is ~3 seats per national point; the probability is driven almost
entirely by how far the national margin sits from the ~even-vote tipping
point and how wide the national error is. District-level noise barely matters
for the chamber call because it averages out over 435 seats.

## Update: fundamentals features now used (and their actual values)

The first pass left incumbency, candidate record and the 2022 results out.
They are now in both forecasts, built on the feature set in
`src/models/candidate_quality.py` (lean, generic ballot, incumbency,
approval × president's party, midterm), with every input value exported
rather than only the blended result.

### Senate prior: `prior = lean + swing + incumbency + experience (+ midterm)`

| Term | Definition | Coefficient (config `fundamentals`) |
|---|---|---|
| lean | 0.8 × (0.75·pres 2024 + 0.25·pres 2020) + 0.2 × 2022 statewide result | `pres_weight_recent` 0.75, `statewide_2022_weight` 0.2 |
| swing | national environment: 0.6·generic ballot + 0.4·(0.3 × net approval, flipped to the out-party), minus the 2024 House baseline | unchanged |
| incumbency | ±3.0 for the incumbent's party; ×0.5 if appointed | `incumbency_advantage` 3.0 (candidate_quality.py's 3.0 is vote-share, ≈6 margin) |
| experience | (0.75·wins − 0.5·losses) for D minus the same for R, capped ±3; an incumbent's wins for this seat are excluded | `experience_per_statewide_win`, `_loss`, `experience_cap` |
| midterm | president's-party penalty | `midterm_penalty` 0 (generic ballot already carries it; switchable) |
| blend | final = (1−w)·polls + w·prior, w = 3/(3+n) | `blend_k` 3 |

Actual values used on 2026-10-04 (Dem−Rep points):

| Race | Pres '24 | Pres '20 | 2022 statewide | Lean | Swing | Incumbent | Experience D W–L / R W–L | Prior | Polls (n) | Prior wt | Final | P(D) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Georgia | −2.2 | +0.2 | +2.8 (Sen runoff) | −0.7 | +9.2 | D ×1 **+3.0** | 0–0 / 0–0 → 0 | +11.5 | +8.5 (17) | 15% | **+8.9** | 0.94 |
| Michigan | −1.4 | +2.8 | +10.6 (Gov) | +1.8 | +9.2 | open | 0–0 / 0–1 → +0.5 | +11.5 | +2.9 (41) | 7% | **+3.5** | 0.73 |
| North Carolina | −3.3 | −1.3 | −3.2 (Sen) | −2.9 | +9.2 | open | 6–0 / 0–0 → +3.0 (cap) | +9.3 | +9.7 (39) | 7% | **+9.7** | 0.95 |
| Maine | +6.9 | +9.1 | +13.1 (Gov) | +8.6 | +9.2 | R ×5 **−3.0** | 0–0 / 0–1 → +0.5 | +15.3 | +1.1 (20) | 13% | **+2.9** | 0.70 |
| New Hampshire | +2.8 | +7.4 | +9.1 (Sen) | +5.0 | +9.2 | open | 0–0 / 1–1 → −0.25 | +13.9 | +5.7 (24) | 11% | **+6.6** | 0.88 |
| Ohio | −11.2 | −8.0 | −6.1 (Sen) | −9.5 | +9.2 | R appointed **−1.5** | 5–2 / 4–0 → −0.25 | −2.1 | +3.1 (29) | 9% | **+2.6** | 0.66 |
| Texas | −13.6 | −5.6 | −10.9 (Gov) | −11.5 | +9.2 | open (Cornyn lost primary) | 0–0 / 3–0 → −2.25 | −4.5 | +2.1 (45) | 6% | **+1.7** | 0.61 |
| Iowa | −13.2 | −8.2 | −12.2 (Sen) | −12.0 | +9.2 | open | 0–0 / 0–0 → 0 | −2.8 | +1.2 (25) | 11% | **+0.8** | 0.52 |
| Alaska | −13.1 | −10.1 | +10.0 (House AL, RCV) | −7.9 | +9.2 | R ×2 **−3.0** | 2–1 / 0–0 → +1.0 | −0.7 | +5.0 (1) | 75% | **+0.7** | 0.54 |

Headline: **P(Dem control) 53% → 56%**, mean 50.4 → 50.6 seats. The 2022
results and Cooper's record push Democrats up; Collins', Sullivan's and
Husted's incumbency and Paxton's record push them down. Alaska moves most
(40% → 54%) because its single poll leaves the prior at 75% weight and the
2022 column is Peltola's own at-large win — that is the one 2022 entry worth
arguing about, and it is visible on the page.

Importance of the new knobs (sensitivity sweep, P(control)):

| Knob | Grid → P(control) | Spread |
|---|---|---|
| `statewide_2022_weight` | 0 → 0.50, 0.2* → 0.56, 0.4 → 0.62 | 0.12 |
| `midterm_penalty` | 0* → 0.56, 2.5 → 0.61, 5 → 0.66 | 0.09 |
| `incumbency_advantage` | 0 → 0.61, 3* → 0.56, 6 → 0.52 | 0.09 |
| `experience_per_statewide_win` | 0 → 0.55, 0.75* → 0.56, 1.5 → 0.58 | 0.03 |

They now rank third to fifth of all knobs, behind `bias_cycle_type` (0.19)
and `senate_responsiveness` (0.18). Everything in this block is hand-set:
the fit of these coefficients on historical races is the next job, and the
training loader (`src/training/`) has the race/result data for it but no
incumbency or candidate-record columns yet.

### House: lean = 0.75·margin 2024 + 0.25·margin 2022, open seats lose the incumbent's 2.5 pts

`data/fallback/house_districts_2024.csv` now carries the 2022 two-party
margin for 337 districts (blank where uncontested or the state was redrawn
for 2024). `config/house_2026.json › district_lean` lists 30 open seats
(hand-entered, flagged verify). Per district the export carries
`margin_2024`, `margin_2022`, `lean`, `open_seat`, `open_seat_reason`,
`incumbent_party`, `incumbency_adjust`, `expected_margin`, `dem_win_prob`.

Competitive open seats as used:

| District | 2024 | 2022 | Lean | Open-seat adj. | Expected | P(D) |
|---|---|---|---|---|---|---|
| ME-2 | D+0.7 | D+6.1 | D+2.1 | −2.5 (Golden retiring) | D+7.4 | 0.88 |
| NE-2 | R+1.9 | R+2.7 | R+2.1 | +2.5 (Bacon retiring) | D+8.3 | 0.90 |
| MI-10 | R+6.4 | R+0.5 | R+4.9 | +2.5 (James → Gov) | D+5.5 | 0.81 |
| AZ-1 | R+3.8 | R+0.9 | R+3.1 | +2.5 (Schweikert → Gov) | D+7.3 | 0.87 |
| IA-2 | R+15.8 | R+8.3 | R+13.9 | +2.5 (Hinson → Sen) | R+3.5 | 0.28 |

Headline: **P(Dem House majority) 95.8% → 96.6%**, mean 233.5 → 234.6 seats.
Small, as expected: open seats and the 2022 blend move individual districts
by 2–5 points but the chamber call is set by the national margin.
