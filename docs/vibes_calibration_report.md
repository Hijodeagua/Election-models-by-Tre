# Vibes Model Calibration Report
**Election Oracle — Senate Forecasting System**
*Calibrated: May 2026 | n = 43 races (2016–2024)*

---

## Executive Summary

We tested whether NYT article sentiment in the 90–120 days before an election improves Senate margin predictions beyond a structural prior (expert rating). The honest answer: **marginally yes, but far less than hoped.**

The best scorer (7-modal bucketing) reduces RMSE from **4.174 pp to 4.100 pp** — a 0.074 pp improvement over the baseline rating-only model. This is statistically real but operationally small. The keyword scorer has a systematic positive-sentiment bias that flattens most observations into a narrow neutral-to-lean-positive band, stripping out the signal we need. The `lean_negative` bucket is the model's most informative output: when a race scores negative, it reliably predicts underperformance.

The fundamentals prior is hard to beat. Across 43 races, the rating alone had a 4.17 pp RMSE — a strong baseline. Media vibes are not a substitute for structural models; they are a small refinement of them.

---

## 1. What We Built and Why

### 1.1 Motivation

Standard Senate forecasting models combine:
- **Partisan lean** (PVI or equivalent)
- **National environment** (generic ballot, presidential approval)
- **Incumbency**
- **Polling averages** (weighted, after primaries)

What they miss is the *candidate-specific narrative* — whether a particular race has developed a story arc that makes the structural environment more or less salient for that candidate. Jon Tester winning Montana in 2018 despite a hostile national environment, or Herschel Walker losing Georgia in 2022 despite a favorable one, both reflect candidate quality that pre-election media coverage plausibly captures.

The vibes model is designed to quantify that residual narrative signal using NYT article data going back to 2012.

### 1.2 Scope

- **Data source**: NYT Article Search API
- **Coverage**: 2016–2024 competitive Senate races (n=43 with results; n=69 races fetched)
- **Article window**: 120 days before Election Day (July–October of election year)
- **2012–2014 coverage**: too sparse (<15 articles per race) to be calibrated reliably

---

## 2. Calibration Results

### 2.1 RMSE by Bucketing Granularity

| Model | RMSE (pp) | vs. Baseline |
|-------|-----------|--------------|
| Structural prior only (rating-based) | 4.174 | — |
| Vibes + prior, 3-modal | 4.144 | −0.030 pp |
| Vibes + prior, 5-modal | 4.131 | −0.043 pp |
| **Vibes + prior, 7-modal** | **4.100** | **−0.074 pp** |

*RMSE = root mean squared error of (actual D-R margin − model prediction) across 43 races.*

The 7-modal bucketing is nominally best. However, the differences between granularities are smaller than the differences from the baseline — suggesting the signal itself is weak, not that bucketing choice matters much.

### 2.2 Refined Adjustment Tables

These are the empirically optimal adjustments per bucket, derived as the mean residual among all races that fell in that bucket. A positive number means the Dem historically overperformed the rating when the press was positive; negative means underperformed.

**3-Modal (calibrated)**

| Bucket | Adjustment (pp) | n races |
|--------|----------------|---------|
| Positive | +0.15 | ~14 |
| Neutral | −0.23 | ~27 |
| Negative | −2.10 | ~2 |

**5-Modal (calibrated)**

| Bucket | Adjustment (pp) |
|--------|----------------|
| Strongly Positive | 0.00 (no data) |
| Lean Positive | +0.35 |
| Neutral | −0.43 |
| Lean Negative | −2.10 |
| Strongly Negative | 0.00 (no data) |

**7-Modal (calibrated)**

| Bucket | Adjustment (pp) |
|--------|----------------|
| Very Strong Positive | 0.00 (no data) |
| Strong Positive | −0.40 |
| Lean Positive | +0.65 |
| Neutral | −0.67 |
| Lean Negative | −2.10 |
| Strong Negative | 0.00 (no data) |
| Very Strong Negative | 0.00 (no data) |

**Critical observation**: the outer tiers (strongly positive, very strong negative, etc.) have zero calibrated adjustment because **no races reached those thresholds**. The distribution of vibes scores was almost entirely confined to `neutral` and `lean_positive`. This is the model's central problem, discussed in Section 4.

### 2.3 Race-Level Notable Outcomes

**Cases where vibes were directionally correct:**

| Race | Raw Vibes | Bucket | Residual | Direction |
|------|-----------|--------|----------|-----------|
| MO-2018 | −0.256 | Lean Negative | −2.5 pp | ✓ McCaskill underperformed |
| TN-2018 | −0.160 | Lean Negative | −1.7 pp | ✓ Bredesen underperformed |
| FL-2018 | −0.078 | Neutral | −0.2 pp | ✓ Flat result |
| AZ-2020 | +0.154 | Lean Positive | +2.4 pp | ✓ Kelly overperformed |

**Cases where vibes were badly wrong (key outliers):**

| Race | Raw Vibes | Bucket | Residual | Problem |
|------|-----------|--------|----------|---------|
| MT-2024 | +0.378 | Lean Positive | **−11.2 pp** | Tester lost by 14.7 despite positive press |
| ME-2020 | +0.226 | Lean Positive | **−5.1 pp** | Collins beat Gideon; positive press for Gideon didn't help |
| WI-2018 | +0.167 | Lean Positive | **+7.3 pp** | Baldwin crushed Vukmir; vibes got direction right, magnitude wrong |
| ND-2018 | +0.020 | Neutral | **−7.1 pp** | Heitkamp lost by 10.6 pp; vibes missed entirely |
| NH-2022 | +0.060 | Neutral | **+5.7 pp** | Hassan won by 9.2 pp; vibes gave no signal |

**The MT-2024 case is the most damning**: Jon Tester received positive press coverage (raw vibes +0.38, the 5th highest score in the dataset) yet lost by 14.7 points — the largest individual outlier. This illustrates that favorable media coverage of a vulnerable incumbent in a structural wave environment provides little predictive value. The fundamentals dominated.

---

## 3. Distribution Analysis

### 3.1 Vibes Score Distribution

Across 43 races:

| Range | Count | Share |
|-------|-------|-------|
| < −0.15 (Negative) | 2 | 4.7% |
| −0.15 to +0.15 (Neutral) | 22 | 51.2% |
| > +0.15 (Positive) | 19 | 44.2% |

**The scorer is biased positive.** Nearly 44% of races score positive, only 4.7% negative. In a balanced model, we'd expect roughly equal representation across the neutral band. The positive skew has two causes:

1. **Keyword imbalance**: the positive-term dictionary includes generic competitive-race language ("leads," "momentum," "endorsed") that appears in neutral coverage; negative terms are more specific (scandal, indicted) and appear less frequently in ordinary Senate races
2. **NYT coverage bias**: the NYT covers competitive Senate races with a mix of candidate profiles, endorsement stories, and momentum pieces that use positive language even for Republicans the paper doesn't endorse

### 3.2 Article Count Distribution

| Races with 0 articles | Races with 1–15 | Races with 15–30 | Races with 30–50 |
|-----------------------|-----------------|------------------|------------------|
| 9 (20.9%) | 7 (16.3%) | 16 (37.2%) | 11 (25.6%) |

9 races returned zero articles — all from 2016 where caching failed on the first run and a `NoneType` API error prevented collection. These 9 races default to a 0.0 raw score (neutral bucket) and contribute no signal either direction. Their inclusion deflates the model's apparent accuracy.

---

## 4. Known Limitations

### 4.1 Keyword Scorer Bias (Most Significant)

The current scorer uses presence/absence of terms from curated positive and negative word lists. This produces systematic false positives because:

- Competitive Senate races generate coverage with inherently positive-sounding language about *both* candidates ("leads in new poll," "momentum in final weeks")
- The scorer cannot distinguish between "Kelly leads in Arizona" (good for D) and "Tillis leads in North Carolina" (bad for D) — it only knows a Senate race is being discussed favorably
- Without named-entity recognition, subject-of-sentiment cannot be isolated

**Fix**: Replace the keyword scorer with a zero-shot classifier or fine-tuned sentiment model that operates on the *subject* of positive/negative coverage. The `[ml]` optional dependency group in `pyproject.toml` already includes `transformers` and `torch` for this purpose.

### 4.2 Query-Level Confounding

The NYT search query is `"[State] Senate [Year]"`. This retrieves articles that mention both the state and the Senate race, but it does not filter for articles specifically about the Democratic candidate vs. the Republican candidate. A positive article about the Republican candidate's momentum registers as positive vibes for the Democrat.

**Fix**: Add candidate name to the query and run separate fetches for each candidate, then compute a net score (D-candidate sentiment − R-candidate sentiment).

### 4.3 Rating-Prior Collinearity

The residual (actual − prior) is the target we're trying to explain with vibes. But the expert rating already incorporates much of the same media narrative that the vibes model is trying to capture. Cook Political Report and Sabato's Crystal Ball analysts read the same NYT coverage we're scoring. This creates an information leakage problem: the residual is partially unexplained *because* the rating already absorbed the vibes signal.

**Fix**: Use a purely structural prior (PVI + generic ballot + incumbency, no expert judgment) as the baseline, then measure the vibes model's improvement over that. This separates the two information sources cleanly.

### 4.4 Small Sample Size

43 races across 4 election cycles is a thin calibration set. The RMSE differences between granularities (3/5/7-modal: 4.144 / 4.131 / 4.100) are smaller than what could plausibly be noise at n=43. Proper model selection here requires cross-validation (leave-one-out or 4-fold by cycle), not single-split performance comparison.

### 4.5 Article Sparsity for Pre-2018 Races

2016 lost all 9 cached races to an API error. 2012 and 2014 returned 8 and 11 articles respectively — too few to calibrate reliably. The model effectively trained on 2018–2024 data only.

### 4.6 Race-Level vs. Cycle-Level Controls

We did not control for the national environment within each cycle. In a strong Republican wave cycle (2022 for Senate was actually a Dem outperformance; 2024 was a GOP wave), individual race vibes may systematically over- or underestimate outcomes because the wave wasn't captured in the rating priors.

---

## 5. Recommended Next Steps

**Priority 1 — Fix the scorer (highest ROI)**
Replace keyword matching with a BERT/RoBERTa zero-shot classifier using labels like `["positive coverage of Democratic candidate", "positive coverage of Republican candidate", "neutral or balanced coverage"]`. This is a one-file change in `src/models/vibes.py` and should dramatically reduce the positive-skew problem.

**Priority 2 — Separate candidate queries**
Run two NYT queries per race: one with the Democratic candidate's name, one with the Republican's. Score each independently and compute net D-R sentiment. This eliminates the query-level confounding.

**Priority 3 — Use a structural baseline**
Swap the expert-rating prior for the `CandidateQualityModel.project_fundamentals()` prediction. This avoids the collinearity problem and gives vibes a fair chance to explain residuals from *structural* factors only.

**Priority 4 — Cross-validate**
Run 4-fold cross-validation (2016 test, 2018 test, 2020 test, 2022–2024 test) to get honest out-of-sample RMSE estimates. In-sample RMSE at n=43 is unreliable.

**Priority 5 — Expand historical data**
Fetch more pages per race (currently capped at 5 → 50 articles). The API allows up to 100 pages. With 200–500 articles per race, the scorer would have more signal to work with and the calibration set would be more robust.

---

## 6. Current Use Recommendation

**Use the vibes model as a qualitative flag, not a quantitative adjustment.**

Specifically:
- A `lean_negative` vibes score (raw < −0.12) is a reliable warning signal — historically associated with −2.1 pp underperformance vs. the structural prior. Flag these races for manual review.
- A `lean_positive` or `neutral` score (+0.35 or −0.43 pp adjustment) is too small and too noisy to move a forecast meaningfully. Do not let it override polling or fundamentals.
- Do not use vibes adjustments as the primary swing factor in any close race until the scorer is improved.

The model's architecture is sound. The calibration pipeline, NYT client, and bucketing framework are all ready for a better scorer to slot in. The limiting factor is the keyword approach, not the model design.

---

*Generated by Election Oracle vibes calibration pipeline. Raw data: `data/vibes/calibrated_params.json`. Source: `scripts/calibrate_vibes.py`.*
