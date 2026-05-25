# NYT Senate Article Corpus — Prediction Extraction Report
**Election Oracle — Media Intelligence Layer**
*Generated: May 2026 | Coverage: 2012–2026 | n = 1,534 unique articles*

---

## 1. Article Corpus Overview

### 1.1 Scale

| Metric | Count |
|--------|-------|
| Total article records (including cross-race duplicates) | 2,940 |
| Unique articles (deduplicated by article ID) | 1,534 |
| Multi-race articles (appear in 2+ race queries) | 635 (41%) |
| Single-race articles (appear in exactly 1 race) | 899 (59%) |
| Articles with byline | 2,858 (97%) |
| Articles with lead paragraph | 0 — see note below |

**Note on lead paragraphs:** The NYT Article Search API does not return `lead_paragraph` in its response regardless of the `fl` field-select parameter. Full article body is only available via individual article fetches (separate endpoint, paywalled). All classification was performed on headline + snippet (~1–2 sentences). This is sufficient for directional prediction extraction but limits nuance in sentiment scoring.

### 1.2 Coverage by Election Cycle

| Cycle | Total Records | Race-Specific | Multi-Race |
|-------|--------------|---------------|------------|
| 2012 | 8 | 2 | 6 |
| 2014 | 11 | 3 | 8 |
| 2016 | 328 | 122 | 206 |
| 2018 | 331 | 71 | 260 |
| 2020 | 718 | 299 | 419 |
| 2022 | 640 | 169 | 471 |
| 2024 | 580 | 132 | 448 |
| 2026 | 324 | 101 | 223 |

2012 and 2014 coverage is thin (8 and 11 records respectively) and unreliable for calibration. Effective calibration window is 2016–2024.

### 1.3 Multi-Race Articles

635 unique articles (41%) were returned by more than one state query. These are national-scope pieces — Senate environment coverage that isn't specific to a single race. Examples from the most-duplicated articles:

- *"As Trump Slumps, Republican Donors Look to Save the Senate"* — appeared in all 9 competitive 2020 races (x9)
- *"4 Weeks Out, Senate Control Hangs in the Balance in Tumultuous..."* — appeared in all 8 competitive 2022 races (x8)
- *"How Ginsburg's Death Has Reshaped the Money Race for Senate"* — appeared in 8 competitive 2020 races (x8)

**Design decision:** These articles are kept at full weight in all races they appear in. The reasoning: if the national Senate environment is bad for Democrats, that's a signal relevant to every competitive race. Downweighting them is a future option but not applied here.

---

## 2. Article Classification

All 1,534 unique articles were classified by Claude Haiku in a single pass. Each article returns 9 structured fields: prediction, confidence, article type, primary subject, news hook, Democrat sentiment, Republican sentiment, and a 2-sentence summary.

### 2.1 Article Type Breakdown

| Type | Count | % |
|------|-------|---|
| Other / uncategorized | 685 | 45% |
| Candidate profile | 224 | 15% |
| Horse race | 163 | 11% |
| Policy | 87 | 6% |
| Fundraising | 82 | 5% |
| Campaign event | 71 | 5% |
| Poll coverage | 50 | 3% |
| Debate | 40 | 3% |
| Endorsement | 39 | 3% |
| Scandal | 37 | 2% |
| Ad buy | 26 | 2% |

The 45% "other" reflects that national Senate overview articles don't fit neatly into a single-race category. Among race-specific content, candidate profiles (15%) and horse-race analysis (11%) dominate.

### 2.2 News Hook Breakdown

| Hook | Count |
|------|-------|
| Campaign event | 752 |
| Other | 461 |
| Ad buy | 95 |
| New poll | 55 |
| Endorsement | 47 |
| Debate | 45 |
| Gaffe | 34 |
| Early voting | 27 |

Campaign events (rallies, appearances, announcements) are the most common trigger for Senate coverage — roughly 5x more common than new polls. This is relevant for the vibes model: most articles are reactive to candidate activity, not independent journalist assessments.

### 2.3 Primary Subject

| Subject | Count | % |
|---------|-------|---|
| Race general (neither candidate specifically) | 981 | 64% |
| Republican candidate | 243 | 16% |
| Democrat candidate | 195 | 13% |
| Both candidates equally | 109 | 7% |

64% of articles are about the race generally rather than a specific candidate. This confirms the keyword scorer's fundamental problem: most coverage doesn't have a clear subject, so positive/negative language doesn't reliably point to a party.

---

## 3. Directional Predictions

### 3.1 Summary

Of 1,534 unique articles classified, only **57 (3.7%) contain a directional prediction** — a journalist or analyst explicitly forecasting who will win, not just reporting facts or poll numbers. This rate is expected: Senate race journalism is predominantly reactive reporting, not forecasting.

| Predicted winner | Count |
|-----------------|-------|
| Democrat | 36 (63%) |
| Republican | 19 (33%) |
| Tossup explicit | 3 (5%) |

| Confidence | Count |
|-----------|-------|
| Clear ("likely", "expected to win") | 19 (33%) |
| Moderate ("slight edge", "leans toward") | 35 (61%) |
| Slight ("marginal", "could go either way") | 3 (5%) |

The D-skew (63% of predictions favor Democrats) is consistent with the NYT's coverage of competitive Senate races, which have historically trended Democratic in competitive cycles covered here (2018, 2020, 2022).

### 3.2 Race-Level Press Consensus vs. Actual Outcome

For races where at least one directional prediction was extracted, we compare the press consensus (majority call) against the actual certified result and the expert rating:

| Race | n | %D | %R | Actual | Press Call | Rating | Press | Rating |
|------|---|----|----|--------|-----------|--------|-------|--------|
| AZ-Senate-2020 | 14 | 100% | 0% | D+2.4 | D | Tossup | Y | N |
| AZ-Senate-2024 | 1 | 0% | 100% | R+5.3 | R | Lean R | Y | Y |
| CO-Senate-2020 | 1 | 100% | 0% | D+9.3 | D | Lean D | Y | Y |
| FL-Senate-2016 | 1 | 0% | 100% | R+7.7 | R | Likely R | Y | Y |
| GA-Senate-2020 | 4 | 100% | 0% | D+1.2 | D | Tossup | Y | N |
| GA-Senate-2022 | 2 | 0% | 100% | D+2.8 | R | Tossup | N | N |
| IN-Senate-2018 | 1 | 0% | 100% | R+5.7 | R | Lean R | Y | Y |
| MD-Senate-2024 | 1 | 0% | 100% | D+28.4 | R | Solid D | N | Y |
| ME-Senate-2020 | 1 | 100% | 0% | R+8.6 | D | Lean R | N | Y |
| MI-Senate-2020 | 1 | 100% | 0% | D+1.7 | D | Lean D | Y | Y |
| MI-Senate-2024 | 3 | 67% | 33% | D+18.8 | D | Likely D | Y | Y |
| NC-Senate-2020 | 2 | 50% | 50% | R+1.7 | Tossup | Tossup | — | Y |
| NC-Senate-2022 | 1 | 0% | 100% | R+3.2 | R | Lean R | Y | Y |
| ND-Senate-2018 | 1 | 0% | 100% | R+10.6 | R | Lean R | Y | Y |
| NH-Senate-2022 | 3 | 100% | 0% | D+9.2 | D | Lean D | Y | Y |
| NV-Senate-2016 | 1 | 100% | 0% | D+2.4 | D | Tossup | Y | N |
| NV-Senate-2018 | 1 | 100% | 0% | D+5.0 | D | Lean D | Y | Y |
| NV-Senate-2022 | 2 | 0% | 100% | D+0.8 | R | Tossup | N | N |
| OH-Senate-2022 | 3 | 33% | 67% | R+6.2 | R | Lean R | Y | Y |
| OH-Senate-2024 | 1 | 0% | 100% | R+6.0 | R | Lean R | Y | Y |
| PA-Senate-2024 | 1 | 0% | 100% | R+0.6 | R | Tossup | Y | Y |
| TN-Senate-2018 | 1 | 0% | 100% | R+10.7 | R | Likely R | Y | Y |
| WI-Senate-2018 | 2 | 50% | 50% | D+10.8 | Tossup | Lean D | — | Y |
| WI-Senate-2022 | 1 | 0% | 100% | R+1.0 | R | Tossup | Y | Y |
| WI-Senate-2024 | 1 | 100% | 0% | R+1.6 | D | Tossup | N | Y |

**Press directional accuracy: 18/23 (78%)** on races where it took a clear position.
**Rating directional accuracy: 20/43 (47%)** across all calibrated races.

The press only made clear calls in 25 of 43 calibrated races (58%), calling 2 tossups (NC-2020, WI-2018). On the races it did call, it outperformed the expert rating significantly — though this comparison is not apples-to-apples since the press self-selects the clearer races to predict.

**Notable misses:**
- **GA-Senate-2022**: All press predictions called R; Warnock won by 2.8 pp in runoff
- **NV-Senate-2022**: Press called R; Cortez Masto held by 0.8 pp
- **MD-Senate-2024**: Only article predicted R for a D+28 race (clearly a misclassified article)
- **WI-Senate-2024**: Single article called D; Hovde nearly won (R+1.6)

---

## 4. Journalist Accuracy

Filtered to journalists with 3 or more directional predictions in calibrated races. Small sample — treat as indicative, not definitive.

| Journalist | Predictions | Races | Correct | Accuracy |
|-----------|-------------|-------|---------|----------|
| Jonathan Martin | 3 | 3 | 3 | 100% |
| Giovanni Russonello | 3 | 2 | 3 | 100% |
| Astead W. Herndon | 3 | 2 | 3 | 100% |
| Trip Gabriel | 3 | 3 | 3 | 100% |
| Jonathan Weisman | 4 | 4 | 3 | 75% |
| Blake Hounshell | 3 | 2 | 2 | 67% |

Only 6 journalists reached the 3-prediction threshold. Sample sizes are too small to draw strong conclusions — 3/3 is 100% but could easily be luck. As more 2026 data is collected, this table will become more meaningful.

**Priority tracking for 2026:** Jonathan Martin (now at Politico but covered extensively for NYT), Astead Herndon, and Trip Gabriel are the reporters to watch given their track records in this dataset.

### 4.1 Confidence Calibration

| Confidence | n | Accuracy | Expected |
|-----------|---|----------|---------|
| Clear | 19 | 74% | >80% |
| Moderate | 31 | 81% | ~70% |
| Slight | 3 | 100% | ~60% |

Confidence labels are inverted from expectations: "moderate" predictions outperform "clear" ones. Two interpretations: (1) the LLM is over-labeling things as "clear" when genuine uncertainty remains, or (2) journalists who write in heavily confident terms are overconfident. Either way, confidence weighting should not be applied naively — equal weighting across confidence levels is safer until sample sizes grow.

---

## 5. Candidate-Aware Sentiment

### 5.1 Overall Sentiment Distribution

Democrat and Republican sentiment are **independent scales** — an article can be positive for both, negative for both, or any combination. Do not collapse to a single `dem - rep` diff score; `(pos, pos)` and `(neutral, neutral)` both produce zero but represent fundamentally different articles.

| Sentiment | Democrat | Republican |
|-----------|----------|------------|
| Positive | 217 (14%) | 72 (5%) |
| Neutral | 1,190 (78%) | 1,220 (80%) |
| Negative | 122 (8%) | 237 (15%) |

Republican coverage is more negative (15%) than Democrat coverage (8%), and Democrat coverage is more positive (14% vs 5%). This likely reflects the NYT's competitive-race coverage patterns: Democrat candidates in close races tend to receive profile pieces and momentum stories, while Republican candidates in those same races receive more scrutiny coverage.

### 5.2 Sentiment Pair Distribution (3×3 Matrix)

Each cell shows article count and the D-win rate in historically calibrated races.

| | **Rep: Positive** | **Rep: Neutral** | **Rep: Negative** |
|---|---|---|---|
| **Dem: Positive** | 1 (100% D) | 136 (44% D) | 80 (57% D) |
| **Dem: Neutral** | 41 (26% D) | 998 (37% D) | 151 (40% D) |
| **Dem: Negative** | 30 (40% D) | 86 (43% D) | 6 (20% D) |

**Key signals:**
- `(Dem: pos, Rep: neg)` → 57% D-win rate — strongest pro-Democrat cell
- `(Dem: neg, Rep: pos)` → 26% D-win rate — strongest pro-Republican cell
- `(Dem: pos, Rep: pos)` → 100% D-win rate, but n=1; meaningless
- `(Dem: neg, Rep: neg)` → 20% D-win rate (n=6) — chaotic race narrative correlates with R wins

**Caveat:** These D-win rates are noisy at the article level because many articles appear across multiple races. Race-level aggregation (averaging sentiment pairs per race then comparing to outcome) would give cleaner signal. This is the recommended next step before incorporating sentiment into the vibes model.

---

## 6. Data Quality Notes

| Issue | Impact | Status |
|-------|--------|--------|
| lead_paragraph unavailable via Article Search API | Classification based on headline + snippet only | Known limitation; full-text fetch would require per-article API calls |
| 2012/2014 coverage extremely sparse (19 total records) | Cannot calibrate pre-2016 | Accepted; model trains on 2016–2024 |
| 3% prediction rate | Only 57 articles contain explicit forecasts | Expected; most Senate journalism is reactive reporting |
| Multi-race articles at full weight in all races | National coverage counted equally in each competitive race | Design decision; downweighting is a future option |
| Confidence calibration inverted | "Clear" predictions (74%) underperform "moderate" (81%) | Do not weight by confidence until n grows |
| 5 articles unclassified | Empty API responses from Anthropic | Negligible (0.3% of corpus) |

---

## 6. Signal in Reactive Reporting

The 1,472 articles without explicit predictions are not all noise. A subset contains **structural event signals** — endorsements, scandals, fundraising, debate coverage, and ad buys — that are directionally meaningful even without a journalist calling a winner.

### 6.1 How Much Is Actually Useful

Of the 261 reactive articles in signal-rich categories (poll coverage, endorsement, scandal, fundraising, debate, ad buy):

| Signal Type | Total Reactive | Candidate-Specific | Useful |
|-------------|---------------|-------------------|--------|
| Scandal | 37 | 35 | Yes |
| Fundraising | 80 | 31 | Yes |
| Endorsement | 38 | 22 | Yes |
| Ad buy | 26 | 20 | Yes |
| Debate | 39 | 20 | Yes |
| Poll coverage | 41 | 13 | Partial |
| **Total** | **261** | **141** | |

**141 candidate-specific reactive articles** have directional signal. The remaining 120 in those categories are either national environment coverage (`primary_subject = race_general`) or 2016 presidential primary contamination.

### 6.2 The 2016 Contamination Problem

2016 has 59 signal-rich reactive articles, of which 30 are candidate-specific — but many of those "candidates" are Rubio, Cruz, Sanders, and Clinton running for president, not Senate. The query `"New Hampshire Senate 2016"` pulled presidential primary articles because:
- NH held the first presidential primary
- Several candidates (Rubio, Sanders) were sitting senators
- Presidential primary articles frequently mention "Senate" in describing candidates' records

Examples of contamination pulled into NH-Senate-2016:
- *"Des Moines Register Endorses Marco Rubio and Hillary Clinton"* (Iowa presidential endorsement)
- *"Bernie Sanders Challenges Hillary Clinton to Debate in New York"* (presidential debate)
- *"Paul Kirk, Ex-DNC Chairman, Endorses Bernie Sanders"* (presidential endorsement)

**Impact:** 2016 Senate vibes scores are substantially contaminated. This is already reflected in the calibration report (2016 had 9 races with zero articles due to API errors, and the articles that were fetched are lower quality). Treat 2016 as a weak calibration year.

**2018–2026 is clean.** Presidential primary contamination doesn't exist outside 2016 because no other cycle had sitting senators as major presidential candidates during the article window.

### 6.3 Sentiment in Candidate-Specific Reactive Articles

Among the 141 clean reactive signal articles:

| Sentiment | Democrat | Republican |
|-----------|----------|------------|
| Positive | 34 (24%) | 8 (6%) |
| Neutral | 88 (62%) | 83 (59%) |
| Negative | 19 (13%) | 50 (35%) |

Republican candidates receive negative coverage at 35% vs. 13% for Democrats in this signal-specific subset. This is the scandal + scrutiny effect: Republican Senate candidates in competitive races (Rubio's credit card, Herschel Walker, J.D. Vance) received proportionally more negative candidate-specific coverage. This is meaningful signal — not NYT bias per se, but the press tracking real negative events.

### 6.4 What Each Signal Type Tells You

| Type | Signal | Reliability |
|------|--------|------------|
| **Scandal** | Negative event attached to a candidate. Even without a prediction, "Senator X faces ethics probe" is directional. | High — scandals are real events |
| **Fundraising** | Which campaign is outraising which. Consistent outraising by one side signals structural confidence. | Medium — money doesn't always win, but it reflects insider belief |
| **Endorsement** | Institutional backing. NYT endorsements, union endorsements, and notable local official endorsements are more predictive than celebrity endorsements. | Medium — depends heavily on endorser significance |
| **Ad buy** | Where campaigns are spending. Pulling ad money from a state signals internal retreat; big buys signal confidence. | Medium-high — campaigns have private polling |
| **Debate** | Post-debate coverage tone signals who performed better in a moment that often shifts undecideds. | Low-medium — debate effects are short-lived |
| **Poll coverage** | Specific poll numbers if extractable. More useful than headline sentiment alone. | High if margin is explicit |

### 6.5 Recommendation: Reactive Signal Score

Rather than a single vibes score, the model should track three independent signals per race:

1. **Prediction consensus score** — weighted average of explicit directional predictions (journalist-accuracy-weighted when data is sufficient)
2. **Sentiment pair score** — from the 3×3 `(dem_sentiment, rep_sentiment)` matrix, calibrated at the race level
3. **Event signal score** — net count of negative candidate-specific events (scandal, debate loss, funding retreat) vs. positive ones (major endorsement, ad buy surge, fundraising dominance)

These three inputs are correlated but not identical. A race can have neutral sentiment and no predictions but two scandal articles about the Republican candidate — that's a meaningful R signal that the other two scores miss.

**For now:** The reactive signal articles are stored in `data/vibes/predictions.json` with `has_prediction = false` but with `article_type`, `primary_subject`, `dem_sentiment`, and `rep_sentiment` populated. Filter to `primary_subject in (Democrat, Republican, both)` and `article_type in (scandal, endorsement, fundraising, ad_buy, debate)` to get the 141 useful records. No re-extraction needed.

---

## 7. Recommended Next Steps

**Priority 1 — Race-level sentiment aggregation**
Aggregate `(dem_sentiment, rep_sentiment)` pairs at the race level (average across all articles for that race in the 120-day window), then calibrate each of the 9 matrix cells against actual outcomes. This replaces the keyword vibes score with a candidate-aware version.

**Priority 2 — Build the three-signal composite**
Implement the three-signal framework: (1) prediction consensus score, (2) sentiment pair score, (3) event signal score from the 141 candidate-specific reactive articles. Each is calibrated independently; combine with empirically-derived weights. No re-extraction needed for signal #3 — the data is already in `predictions.json`.

**Priority 3 — Journalist-weighted prediction score**
Once enough 2026 data arrives, weight directional predictions by journalist historical accuracy. The 4 journalists at 100% in this dataset need to make more predictions to validate their track records. 10+ predictions each is the minimum credible threshold.

**Priority 4 — Fix the 2016 contamination**
Add candidate name filters to 2016 queries: `"[State] Senate [Year] -Trump -Clinton -Sanders -Cruz -Rubio"` to exclude presidential primary articles. Re-fetch 2016 with the updated query and re-classify. This may improve 2016 calibration meaningfully.

**Priority 5 — Track 2026 monthly**
The 2026 cycle has 324 articles across 10 races. Primaries complete in June–August; run the full fetch + extract pipeline monthly through November. By September, journalist predictions for close races (AZ, GA, NH) should start appearing and can be tracked in real time.

---

*Generated by Election Oracle prediction extraction pipeline.*
*Source scripts: `scripts/extract_predictions.py`, `scripts/analyze_journalist_accuracy.py`*
*Raw data: `data/vibes/predictions.json`*
