# NYT Senate Article Corpus — Prediction Extraction Report
**Election Oracle — Media Intelligence Layer**
*Generated: May 2026 | Coverage: 2012–2026 | Exploratory methodology draft*

---

## 1. Article Corpus Overview

### 1.1 Scale

| Metric | Count |
|--------|-------|
| Total article records (including cross-race duplicates) | 2,940 |
| Unique articles (deduplicated by article ID) | 1,534 |
| Articles successfully classified by LLM | 1,529 |
| Multi-race articles (appear in 2+ race queries) | 635 (41%) |
| Single-race articles (appear in exactly 1 race) | 899 (59%) |
| Article-race records after joining (multi-race preserved) | 2,932 |
| Articles with byline | 2,858 (97%) |
| Articles with lead paragraph | 0 — see note below |

**Note on lead paragraphs:** The NYT Article Search API does not return `lead_paragraph` regardless of the `fl` field-select parameter. Full article body is only available via individual article fetches (separate endpoint, paywalled). All classification was performed on headline + snippet (~1–2 sentences). This is sufficient for directional prediction extraction but limits nuance in sentiment scoring.

**Note on multi-race handling:** 635 unique articles were returned by multiple state queries. These are kept at full weight in each race they appeared in — a national Senate environment article returned for 8 state queries contributes signal in all 8 races. Classification is performed once per unique article; race assignment is preserved from the original fetch. The 2,932 figure is the working dataset for race-level analysis.

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

2012 and 2014 coverage is thin (8 and 11 records) and unreliable for calibration. Effective calibration window is 2016–2024.

### 1.3 Multi-Race Articles

Examples of the most duplicated articles:

- *"As Trump Slumps, Republican Donors Look to Save the Senate"* — appeared in all 9 competitive 2020 races
- *"4 Weeks Out, Senate Control Hangs in the Balance..."* — appeared in all 8 competitive 2022 races
- *"How Ginsburg's Death Has Reshaped the Money Race for Senate"* — appeared in 8 competitive 2020 races

These are national Senate environment articles. Keeping them at full weight reflects the view that national environment is relevant to every competitive race. Downweighting by inverse appearance count is a future option.

---

## 2. Article Classification

All 1,534 unique articles were classified by Claude Haiku. Each article returns 9 structured fields: prediction signal, confidence, article type, primary subject, news hook, Democrat sentiment, Republican sentiment, and a 2-sentence summary. LLM output is validated against known enum values; unexpected values are normalized to defaults.

### 2.1 Article Type Breakdown

*Based on unique classified articles (n=1,529).*

| Type | Count |
|------|-------|
| Other / uncategorized | 685 |
| Candidate profile | 224 |
| Horse race | 163 |
| Policy | 87 |
| Fundraising | 82 |
| Campaign event | 71 |
| Poll coverage | 50 |
| Debate | 40 |
| Endorsement | 39 |
| Scandal | 37 |
| Ad buy | 26 |

Note: `article_type` and `news_hook` are separate fields in the schema. Earlier versions of this report mixed them; the table above shows only `article_type` values.

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

### 2.3 Primary Subject

| Subject | Count |
|---------|-------|
| Race general | 981 |
| Republican candidate | 243 |
| Democrat candidate | 195 |
| Both candidates | 109 |

64% of articles are about the race generally, not a specific candidate. This is the core problem with generic sentiment scoring: most articles don't have a clear subject.

---

## 3. Directional Predictions

### 3.1 Summary

Of 2,932 article-race records, **116 (4.0%) contain a directional prediction** in a historically calibrated race — a journalist or analyst explicitly forecasting who will win, not just reporting facts. Across all 1,529 classified articles, 57 unique articles (3.7%) contain predictions.

| Predicted winner | Count (article-race records) |
|-----------------|------------------------------|
| Democrat | 69 (59%) |
| Republican | 44 (38%) |
| Tossup explicit | 3 (3%) |

| Confidence | Count |
|-----------|-------|
| Clear | 32 (28%) |
| Moderate | 83 (71%) |
| Slight | 1 (1%) |

### 3.2 Race-Level Press Consensus vs. Actual Outcome

For races with at least one directional prediction, we compare the press consensus against the actual result and the expert rating. Tossup ratings are shown as `-` and excluded from rating accuracy (a tossup is an abstention, not a directional call).

| Race | n | %D | %R | Actual | Press | Rating | Press | Rating |
|------|---|----|----|--------|-------|--------|-------|--------|
| AZ-Senate-2020 | 14 | 100% | 0% | D+2.4 | D | Tossup | Y | - |
| AZ-Senate-2022 | 2 | 50% | 50% | D+4.9 | ~Tossup | Lean D | - | Y |
| AZ-Senate-2024 | 2 | 50% | 50% | R+5.3 | ~Tossup | Lean R | - | Y |
| CO-Senate-2020 | 7 | 100% | 0% | D+9.3 | D | Lean D | Y | Y |
| FL-Senate-2016 | 1 | 0% | 100% | R+7.7 | R | Likely R | Y | Y |
| FL-Senate-2018 | 2 | 50% | 50% | R+0.2 | ~Tossup | Tossup | - | - |
| GA-Senate-2020 | 11 | 100% | 0% | D+1.2 | D | Tossup | Y | - |
| GA-Senate-2022 | 4 | 25% | 75% | D+2.8 | R | Tossup | N | - |
| IA-Senate-2020 | 1 | 100% | 0% | R+6.6 | D | Lean R | N | Y |
| IN-Senate-2018 | 1 | 0% | 100% | R+5.7 | R | Lean R | Y | Y |
| MD-Senate-2024 | 1 | 0% | 100% | D+28.4 | R | Solid D | N | Y |
| ME-Senate-2020 | 6 | 100% | 0% | R+8.6 | D | Lean R | N | Y |
| MI-Senate-2020 | 4 | 100% | 0% | D+1.7 | D | Lean D | Y | Y |
| MI-Senate-2024 | 3 | 67% | 33% | D+18.8 | D | Likely D | Y | Y |
| MO-Senate-2018 | 3 | 33% | 67% | R+6.0 | R | Lean R | Y | Y |
| MT-Senate-2018 | 1 | 0% | 100% | D+3.5 | R | Lean D | N | Y |
| MT-Senate-2020 | 4 | 100% | 0% | R+10.2 | D | Lean R | N | Y |
| MT-Senate-2024 | 2 | 100% | 0% | R+14.7 | D | Lean R | N | Y |
| NC-Senate-2020 | 6 | 83% | 17% | R+1.7 | D | Tossup | N | - |
| NC-Senate-2022 | 2 | 50% | 50% | R+3.2 | ~Tossup | Lean R | - | Y |
| ND-Senate-2018 | 4 | 25% | 75% | R+10.6 | R | Lean R | Y | Y |
| NH-Senate-2022 | 4 | 75% | 25% | D+9.2 | D | Lean D | Y | Y |
| NV-Senate-2016 | 1 | 100% | 0% | D+2.4 | D | Tossup | Y | - |
| NV-Senate-2018 | 2 | 50% | 50% | D+5.0 | ~Tossup | Lean D | - | Y |
| NV-Senate-2022 | 3 | 0% | 100% | D+0.8 | R | Tossup | N | - |
| NV-Senate-2024 | 1 | 100% | 0% | R+0.8 | D | Lean D | N | N |
| OH-Senate-2022 | 3 | 33% | 67% | R+6.2 | R | Lean R | Y | Y |
| OH-Senate-2024 | 5 | 20% | 80% | R+6.0 | R | Lean R | Y | Y |
| PA-Senate-2022 | 1 | 100% | 0% | D+4.9 | D | Tossup | Y | - |
| PA-Senate-2024 | 4 | 25% | 75% | R+0.6 | R | Tossup | Y | - |
| TN-Senate-2018 | 2 | 0% | 100% | R+10.7 | R | Likely R | Y | Y |
| TX-Senate-2018 | 2 | 50% | 50% | R+2.6 | ~Tossup | Lean R | - | Y |
| WI-Senate-2018 | 2 | 50% | 50% | D+10.8 | ~Tossup | Lean D | - | Y |
| WI-Senate-2022 | 2 | 50% | 50% | R+1.0 | ~Tossup | Tossup | - | - |
| WI-Senate-2024 | 3 | 100% | 0% | R+1.6 | D | Tossup | N | - |

**Press directional accuracy: 16/27 (59%)** — races where press took a non-tossup position.
**Rating directional accuracy: 23/24 (96%)** — non-tossup ratings only; tossup ratings excluded as abstentions.

**These figures are not directly comparable.** Press predictions are self-selected (journalists only write forecasts for races they find interesting); expert ratings are systematic and cover all races. The corrected comparison reverses the earlier draft's conclusion: expert ratings are highly accurate on the races where they take a clear position, while press consensus is only modestly better than chance (59%). This is expected — Cook Political Report and Sabato are specifically optimized to forecast direction; news coverage is not.

**Notable misses for press consensus:**
- **MT-Senate-2024**: 2/2 articles predicted D; Tester lost by 14.7 pp
- **ME-Senate-2020**: 6/6 articles predicted D; Collins won by 8.6 pp
- **NC-Senate-2020**: 5/6 articles predicted D; Tillis won by 1.7 pp
- **MD-Senate-2024**: Single article predicted R for a D+28.4 race — likely a misclassified article

---

## 4. Journalist Accuracy

Filtered to journalists with 3 or more directional predictions in calibrated races. Multi-author bylines appear as combined strings (e.g., "Jonathan Martin And Alexander Burns") and are treated as a single byline unit.

**These are anecdotal observations, not rankings.** Sample sizes of 3–13 predictions are too small to draw reliable conclusions. Include them only as a starting point for tracking.

| Journalist | Predictions | Races | Correct | Accuracy |
|-----------|-------------|-------|---------|----------|
| Jonathan Martin And Matt Flegenheimer | 4 | 4 | 4 | 100% |
| Adam Nagourney, Ruth Igielnik And Camille Baker | 4 | 3 | 4 | 100% |
| Alexander Burns And Jonathan Martin | 3 | 2 | 3 | 100% |
| Nick Corasaniti And Isabella Grullon Paz | 3 | 3 | 3 | 100% |
| Giovanni Russonello | 7 | 5 | 5 | 71% |
| Jonathan Martin And Alexander Burns | 10 | 7 | 7 | 70% |
| Astead W. Herndon | 6 | 4 | 4 | 67% |
| Jonathan Martin And Maggie Haberman | 3 | 3 | 2 | 67% |
| Alexander Burns And Maggie Haberman | 3 | 3 | 2 | 67% |
| Blake Hounshell | 3 | 2 | 2 | 67% |
| Jonathan Weisman And Katie Glueck | 3 | 3 | 2 | 67% |
| Jonathan Martin | 13 | 10 | 7 | 54% |
| Jonathan Martin And Matt Stevens | 6 | 6 | 3 | 50% |
| Shane Goldmacher | 6 | 6 | 3 | 50% |
| Jonathan Weisman | 7 | 6 | 3 | 43% |
| Trip Gabriel | 7 | 6 | 3 | 43% |
| Alexander Burns And Matt Stevens | 3 | 3 | 1 | 33% |
| Jonathan Weisman And Ruth Igielnik | 6 | 6 | 1 | 17% |

### 4.1 Confidence Calibration

Directional D/R predictions only. Confidence is also inverted here — "moderate" predictions are not more accurate than "clear" ones, and confidence labels should not be used as weighting factors until sample sizes grow.

| Confidence | n | Accuracy | Expected |
|-----------|---|----------|---------|
| Clear | 32 | 69% | >80% |
| Moderate | 83 | 58% | ~70% |
| Slight | 1 | 100% | ~60% |

---

## 5. Candidate-Aware Sentiment

### 5.1 Overall Sentiment Distribution

Democrat and Republican sentiment are **independent scales** — an article can be positive for both (tight tossup, both candidates generating favorable coverage), negative for both, or any combination. Do not collapse to a single `dem - rep` diff score; that collapses `(pos, pos)` and `(neutral, neutral)` into the same value, losing the tossup signal.

| Sentiment | Democrat | Republican |
|-----------|----------|------------|
| Positive | 217 (14%) | 72 (5%) |
| Neutral | 1,190 (78%) | 1,220 (80%) |
| Negative | 122 (8%) | 237 (15%) |

### 5.2 Sentiment Pair Distribution — Full Corpus (2,932 article-race records)

Multi-race articles appear once per race. D-win % is across calibrated 2016–2024 races only.

| | **Rep: Positive** | **Rep: Neutral** | **Rep: Negative** |
|---|---|---|---|
| **Dem: Positive** | 1 (100% D) | 281 (38% D) | 178 (54% D) |
| **Dem: Neutral** | 81 (24% D) | 1,880 (38% D) | 282 (43% D) |
| **Dem: Negative** | 88 (31% D) | 135 (37% D) | 6 (20% D) |

Signal is directional but noisy. `(dem:pos, rep:neg)` shows 54% D-wins — suggestive but based on articles spread across many races. `(dem:neg, rep:pos)` shows 24% D-wins — the clearest R signal. `(neu,neu)` at 38% D is the baseline for comparison. Race-level aggregation (not article-level) is the right unit of analysis and has not yet been done.

---

## 6. Signal in Reactive Reporting

Of the 1,472 articles without explicit predictions, a meaningful subset contains **structural event signals** — endorsements, scandals, fundraising, debate coverage, and ad buys — directionally relevant even without a journalist calling a winner.

### 6.1 Candidate-Specific Signal Articles

Filtering to articles where `primary_subject` is Democrat, Republican, or both, and `article_type` is a signal-rich category:

| Type | Candidate-Specific | Race-General / Contaminated |
|------|-------------------|----------------------------|
| Scandal | 35 | 2 |
| Fundraising | 31 | 49 |
| Endorsement | 22 | 16 |
| Ad buy | 20 | 6 |
| Debate | 20 | 19 |
| Poll coverage | 13 | 28 |
| **Total** | **141** | **120** |

141 candidate-specific reactive articles are available in `predictions.json` without re-extraction. Filter on `primary_subject in (Democrat, Republican, both)` and `article_type in (scandal, endorsement, fundraising, ad_buy, debate)`.

### 6.2 The 2016 Contamination Problem

2016 has significant signal contamination from presidential primary coverage. The query `"New Hampshire Senate 2016"` returned articles about Rubio, Cruz, Sanders, and Clinton running for president — all sitting senators, frequently mentioned alongside "Senate." This affects all 2016 NH, FL, OH, MO, IN, and PA queries.

The `primary_subject` field partially mitigates this: presidential primary articles tend to get tagged `race_general` rather than `Democrat`/`Republican` since they're not about Senate candidates specifically. However, some contamination remains.

**2018–2026 is clean.** No other cycle had major sitting senators as presidential candidates during the article window.

### 6.3 What Each Signal Type Tells You

| Type | Signal | Reliability |
|------|--------|------------|
| Scandal | Negative event attached to a specific candidate | High — scandals are real events |
| Fundraising | Which campaign is outraising which | Medium — money signals insider confidence |
| Endorsement | Institutional backing | Medium — depends on endorser significance |
| Ad buy | Where campaigns are spending or retreating | Medium-high — campaigns have private polling |
| Debate | Post-debate coverage tone | Low-medium — effects are short-lived |
| Poll coverage | Specific poll numbers if extractable | High if margin is explicit |

### 6.4 Three-Signal Framework (Proposed)

Rather than a single vibes score, track three independent signals per race:

1. **Prediction consensus** — weighted average of explicit directional predictions, journalist-accuracy-weighted when data is sufficient
2. **Sentiment pair score** — from the 3x3 `(dem_sentiment, rep_sentiment)` matrix, calibrated at the race level against actual outcomes
3. **Event signal** — net count of negative candidate-specific events vs. positive ones, from the 141 reactive signal articles

These three inputs are correlated but not identical. A race can have neutral sentiment and no predictions but two scandal articles about the Republican candidate — that's a meaningful R signal the other two scores miss.

---

## 7. Data Quality and Known Issues

| Issue | Impact | Status |
|-------|--------|--------|
| lead_paragraph unavailable via Article Search API | Headline + snippet only | Known; full-text would require per-article fetches |
| 2012/2014 coverage sparse (19 total records) | Cannot calibrate pre-2016 | Accepted |
| 2016 corpus contaminated by presidential primary content | Vibes scores less reliable for 2016 | Partially mitigated by primary_subject filter |
| LLM output enum normalization | Unexpected values normalized to defaults | Fixed; validation now applied at extraction |
| Bylines are combined strings for multi-author articles | Journalist tracking is byline-unit not individual | Accepted; would require NER to split |
| 5 articles unclassified (empty API response) | 0.3% of unique articles | Negligible |
| Confidence calibration inverted | Do not weight by confidence | Under investigation |
| Predictions.json not committed to git | Cannot reproduce without re-running extraction | See reproducibility note below |

**Reproducibility:** `data/vibes/predictions.json` and `data/vibes/article_signals.json` are generated artifacts not committed to the repository. To reproduce: (1) set `NYT_API_KEY` and `ANTHROPIC_API_KEY` in `.env`; (2) run `python -m scripts.fetch_vibes_articles`; (3) run `python -m scripts.extract_predictions`; (4) run `python -m scripts.analyze_journalist_accuracy`. Total cost: ~$0.30 Anthropic API, ~40 minutes NYT fetch time.

---

## 8. Recommended Next Steps

**Priority 1 — Race-level sentiment aggregation**
Aggregate `(dem_sentiment, rep_sentiment)` pairs at the race level across the 120-day pre-election window, then calibrate each of the 9 matrix cells against actual outcomes. This is the proper replacement for the keyword vibes score.

**Priority 2 — Three-signal composite**
Implement the three-signal framework above. The 141 candidate-specific reactive articles are already in `predictions.json` — no re-extraction needed for signal #3.

**Priority 3 — Manual validation sample**
Manually inspect a random sample of 30–50 extracted predictions and 30–50 sentiment classifications to audit LLM accuracy. Headline/snippet-only classification is likely noisier than full-text; quantifying this error rate matters before building on the output.

**Priority 4 — Fix 2016 contamination**
Add negative query terms to 2016 queries (`-Trump -Clinton -Sanders -Cruz -Rubio`) to exclude presidential primary articles. Re-fetch and re-classify 2016 only.

**Priority 5 — Track 2026 monthly**
Run the full fetch + extract pipeline monthly through November. Primaries complete June–August; journalist predictions for close races (AZ, GA, NH) should appear by September.

---

*Exploratory methodology draft — not for external distribution in current form.*
*Source scripts: `scripts/extract_predictions.py`, `scripts/analyze_journalist_accuracy.py`*
*Raw data: `data/vibes/predictions.json` (generated artifact, not committed)*
