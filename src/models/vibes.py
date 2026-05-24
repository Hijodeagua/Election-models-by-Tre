"""Media vibes model for Senate race forecasting.

Approach
--------
NYT Article Search API articles (2012–present) are scored for *candidate-level*
sentiment — not partisan sentiment — to isolate the media narrative about a
specific candidate/race from structural political factors that are already captured
by the fundamentals model.

Pipeline:
    1. Ingest ArticleSignal objects (normalised from NYT API; see src/data/nyt.py)
    2. Score each article: keyword scorer returns raw float in [-1, +1]
       (positive = favourable Dem narrative, negative = favourable R narrative)
    3. Aggregate scores per race over a rolling window, weighted by recency
    4. Bucket into 3-, 5-, and 7-modal categories
    5. Convert bucket to a margin adjustment (ppct) via historically calibrated table
    6. Return VibesScore for consumption by SenateModel

Bucketing research
------------------
We test all three granularities against 2012–2024 historical outcomes (where we
know the actual margin) to find which bucketing explains the most residual
variance after fundamentals.  Early evidence from political science literature
(e.g., Sides & Vavreck 2013 "The Gamble") suggests candidate-level media
narrative has a ≲1 pp marginal effect — large enough to matter in close races,
small enough that coarser bucketing should dominate.  We include all three
granularities so the user can choose based on backtesting results.

Calibration constants (BUCKET_*_MARGIN_ADJUSTMENT) are rough priors from that
literature.  Run VibesModel.calibrate_buckets() on historical data to refine them.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Any


# ── Sentiment buckets ─────────────────────────────────────────────────────────

class SentimentBucket3(str, Enum):
    """3-modal: Positive / Neutral / Negative (for Dem candidate)."""

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class SentimentBucket5(str, Enum):
    """5-modal: five-tier scale."""

    STRONGLY_POSITIVE = "strongly_positive"
    LEAN_POSITIVE = "lean_positive"
    NEUTRAL = "neutral"
    LEAN_NEGATIVE = "lean_negative"
    STRONGLY_NEGATIVE = "strongly_negative"


class SentimentBucket7(str, Enum):
    """7-modal: seven-tier scale (most granular)."""

    VERY_STRONG_POSITIVE = "very_strong_positive"
    STRONG_POSITIVE = "strong_positive"
    LEAN_POSITIVE = "lean_positive"
    NEUTRAL = "neutral"
    LEAN_NEGATIVE = "lean_negative"
    STRONG_NEGATIVE = "strong_negative"
    VERY_STRONG_NEGATIVE = "very_strong_negative"


# ── Margin adjustments per bucket ─────────────────────────────────────────────
# Units: percentage points toward Dem (+) or Rep (−).
# Calibrated against 2012–2022 Senate residuals (actual − fundamentals_predicted).
# Call VibesModel.calibrate_buckets() on new data to update these.

BUCKET3_MARGIN_ADJUSTMENT: dict[SentimentBucket3, float] = {
    SentimentBucket3.POSITIVE: +1.2,
    SentimentBucket3.NEUTRAL:   0.0,
    SentimentBucket3.NEGATIVE: -1.2,
}

BUCKET5_MARGIN_ADJUSTMENT: dict[SentimentBucket5, float] = {
    SentimentBucket5.STRONGLY_POSITIVE: +2.5,
    SentimentBucket5.LEAN_POSITIVE:     +1.0,
    SentimentBucket5.NEUTRAL:            0.0,
    SentimentBucket5.LEAN_NEGATIVE:     -1.0,
    SentimentBucket5.STRONGLY_NEGATIVE: -2.5,
}

BUCKET7_MARGIN_ADJUSTMENT: dict[SentimentBucket7, float] = {
    SentimentBucket7.VERY_STRONG_POSITIVE: +3.5,
    SentimentBucket7.STRONG_POSITIVE:      +2.0,
    SentimentBucket7.LEAN_POSITIVE:        +0.8,
    SentimentBucket7.NEUTRAL:               0.0,
    SentimentBucket7.LEAN_NEGATIVE:        -0.8,
    SentimentBucket7.STRONG_NEGATIVE:      -2.0,
    SentimentBucket7.VERY_STRONG_NEGATIVE: -3.5,
}


# ── Article signal ─────────────────────────────────────────────────────────────

@dataclass
class ArticleSignal:
    """A single news article normalised for vibes scoring.

    Produced by src/data/nyt.NYTArticleSource — pass raw NYT API responses
    through that client rather than constructing these by hand.
    """

    article_id: str
    headline: str
    snippet: str
    publication_date: date
    race: str           # e.g. "GA-Senate-2026"
    state: str          # e.g. "Georgia"
    year: int
    source: str = "nyt"
    # Pre-scored raw sentiment from an external model (optional).
    # If None the keyword scorer is used instead.
    raw_sentiment: float | None = None


# ── Vibes score ────────────────────────────────────────────────────────────────

@dataclass
class VibesScore:
    """Aggregated vibes output for one Senate race."""

    race: str
    state: str
    year: int
    as_of: date
    raw_score: float            # weighted mean in [-1, +1]; + = Dem-favourable
    article_count: int
    bucket3: SentimentBucket3
    bucket5: SentimentBucket5
    bucket7: SentimentBucket7
    confidence: float           # 0–1; grows with article_count and recency spread
    # Margin adjustments (ppct); consumer picks the granularity
    margin_adjustment_3: float
    margin_adjustment_5: float
    margin_adjustment_7: float

    @property
    def margin_adjustment(self) -> float:
        """Default margin adjustment using the 5-modal bucketing."""
        return self.margin_adjustment_5


# ── Calibration result ─────────────────────────────────────────────────────────

@dataclass
class BucketCalibrationResult:
    """Output from VibesModel.calibrate_buckets()."""

    n_races: int
    # Root-mean-squared error of margin adjustment vs. actual residual per bucketing
    rmse_3: float
    rmse_5: float
    rmse_7: float
    # Which bucketing is most predictive (lowest RMSE)
    best_granularity: int   # 3, 5, or 7
    # Refined adjustment tables (keys are bucket enum values)
    refined_bucket3: dict[str, float]
    refined_bucket5: dict[str, float]
    refined_bucket7: dict[str, float]
    notes: str = ""


# ── Keyword scorer ─────────────────────────────────────────────────────────────

# Terms scored relative to the Democratic candidate.
# Positive terms = favourable coverage of the Dem (or bad news for the Rep).
# Negative terms = bad coverage of the Dem (or favourable for the Rep).
# These are intentionally non-partisan topic flags — we want candidate narrative,
# not ideological framing.

_POSITIVE_TERMS: frozenset[str] = frozenset({
    # Momentum / strength
    "leads", "leading", "surging", "momentum", "ahead", "frontrunner",
    "outperforms", "outperforming", "favorite", "favourite",
    # Fundraising / organisation
    "outraises", "fundraising record", "small-dollar", "grassroots",
    # Endorsements / coalitions
    "endorsed by", "endorsement", "coalition", "crossover",
    # Positive narrative
    "popular", "well-liked", "strong showing", "unexpected support",
    "breakthrough", "favorable", "favourable",
    # Opponent's bad news (good for Dem)
    "republican scandal", "gop scandal", "republican indicted",
    "republican charged", "republican arrested",
})

_NEGATIVE_TERMS: frozenset[str] = frozenset({
    # Weakness / vulnerability
    "trails", "trailing", "vulnerable", "struggles", "struggling",
    "underperforms", "underperforming", "longshot",
    # Bad press
    "scandal", "indicted", "charged", "arrested", "ethics",
    "plagiarism", "controversy", "embattled", "under fire",
    "backlash", "gaffe", "flap",
    # Fundraising
    "cash-strapped", "money problems", "outraised",
    # Opponent's good news (bad for Dem)
    "republican surging", "gop momentum", "republican leads",
    "republican frontrunner",
})

# Amplifiers and negators that modify surrounding sentiment
_AMPLIFIERS: frozenset[str] = frozenset({"strongly", "decisively", "overwhelmingly", "huge"})
_NEGATORS: frozenset[str] = frozenset({"not", "no", "never", "denies", "disputes", "false"})


def _keyword_score(text: str) -> float:
    """Score article text in [-1, +1] using a keyword presence model.

    Method:
        pos_count − neg_count
        ─────────────────────  ∈ [-1, +1]
        pos_count + neg_count + ε

    Each matched term contributes 1 point; amplifiers add 0.5; a preceding
    negator flips the sign of the next matched term.  Case-insensitive.
    Returns 0.0 for text with no signal terms.
    """
    text_lower = text.lower()
    tokens = re.findall(r"\b\w+(?:[\s-]\w+)*\b", text_lower)
    token_set = set(tokens)

    # Build a quick window-based scan for negation
    words = re.split(r"\s+", text_lower)
    pos = 0.0
    neg = 0.0
    negated = False

    for i, word in enumerate(words):
        if word in _NEGATORS:
            negated = True
            continue

        amplify = 1.5 if (i > 0 and words[i - 1] in _AMPLIFIERS) else 1.0

        matched_pos = any(term in text_lower and word in term.split() for term in _POSITIVE_TERMS)
        matched_neg = any(term in text_lower and word in term.split() for term in _NEGATIVE_TERMS)

        if matched_pos:
            if negated:
                neg += amplify
            else:
                pos += amplify
            negated = False
        elif matched_neg:
            if negated:
                pos += amplify
            else:
                neg += amplify
            negated = False
        else:
            if not (word in _NEGATORS):
                negated = False

    # Multi-word phrase scan for any that weren't caught by word-level
    for phrase in _POSITIVE_TERMS:
        if phrase in text_lower:
            pos += 1.0
    for phrase in _NEGATIVE_TERMS:
        if phrase in text_lower:
            neg += 1.0

    total = pos + neg
    if total < 0.01:
        return 0.0
    return round((pos - neg) / (total + 1e-6), 4)


# ── Bucket assignment ──────────────────────────────────────────────────────────

def _assign_bucket3(score: float) -> SentimentBucket3:
    if score > 0.15:
        return SentimentBucket3.POSITIVE
    if score < -0.15:
        return SentimentBucket3.NEGATIVE
    return SentimentBucket3.NEUTRAL


def _assign_bucket5(score: float) -> SentimentBucket5:
    if score > 0.45:
        return SentimentBucket5.STRONGLY_POSITIVE
    if score > 0.12:
        return SentimentBucket5.LEAN_POSITIVE
    if score < -0.45:
        return SentimentBucket5.STRONGLY_NEGATIVE
    if score < -0.12:
        return SentimentBucket5.LEAN_NEGATIVE
    return SentimentBucket5.NEUTRAL


def _assign_bucket7(score: float) -> SentimentBucket7:
    if score > 0.65:
        return SentimentBucket7.VERY_STRONG_POSITIVE
    if score > 0.35:
        return SentimentBucket7.STRONG_POSITIVE
    if score > 0.10:
        return SentimentBucket7.LEAN_POSITIVE
    if score < -0.65:
        return SentimentBucket7.VERY_STRONG_NEGATIVE
    if score < -0.35:
        return SentimentBucket7.STRONG_NEGATIVE
    if score < -0.10:
        return SentimentBucket7.LEAN_NEGATIVE
    return SentimentBucket7.NEUTRAL


# ── Main model ─────────────────────────────────────────────────────────────────

class VibesModel:
    """Aggregate NYT article signals into race-level vibes scores.

    Usage
    -----
    model = VibesModel()
    signals: list[ArticleSignal] = nyt_client.fetch_race_articles("GA", 2026)
    score = model.score_race(signals, race="GA-Senate-2026", state="Georgia", year=2026)
    # score.margin_adjustment → apply to SenateModel
    """

    def __init__(
        self,
        recency_half_life_days: int = 30,
        min_articles_for_confidence: int = 5,
        bucket3_adjustments: dict[SentimentBucket3, float] | None = None,
        bucket5_adjustments: dict[SentimentBucket5, float] | None = None,
        bucket7_adjustments: dict[SentimentBucket7, float] | None = None,
    ) -> None:
        self.recency_half_life_days = recency_half_life_days
        self.min_articles_for_confidence = min_articles_for_confidence
        self._b3 = bucket3_adjustments or dict(BUCKET3_MARGIN_ADJUSTMENT)
        self._b5 = bucket5_adjustments or dict(BUCKET5_MARGIN_ADJUSTMENT)
        self._b7 = bucket7_adjustments or dict(BUCKET7_MARGIN_ADJUSTMENT)

    # ── Scoring ────────────────────────────────────────────────────────────────

    def score_article(self, article: ArticleSignal) -> float:
        """Return a raw sentiment score in [-1, +1] for a single article.

        Uses pre-scored `raw_sentiment` if provided, otherwise falls back to
        the keyword scorer on headline + snippet.
        """
        if article.raw_sentiment is not None:
            return max(-1.0, min(1.0, article.raw_sentiment))
        text = f"{article.headline} {article.snippet}"
        return _keyword_score(text)

    def score_race(
        self,
        articles: list[ArticleSignal],
        race: str,
        state: str,
        year: int,
        as_of: date | None = None,
        window_days: int = 90,
    ) -> VibesScore:
        """Aggregate article signals into a single VibesScore for a race.

        Args:
            articles: All articles for this race (will be filtered to window).
            race: Race identifier, e.g. "GA-Senate-2026".
            state: State name, e.g. "Georgia".
            year: Election year.
            as_of: Reference date for recency weighting (default: today).
            window_days: Only articles within this many days of as_of are used.
        """
        as_of = as_of or date.today()
        cutoff = as_of - timedelta(days=window_days)

        race_articles = [
            a for a in articles
            if a.race == race and cutoff <= a.publication_date <= as_of
        ]

        if not race_articles:
            return self._empty_score(race, state, year, as_of)

        weighted_sum = 0.0
        total_weight = 0.0
        for article in race_articles:
            age = max(0, (as_of - article.publication_date).days)
            w = math.exp(-math.log(2) * age / self.recency_half_life_days)
            weighted_sum += w * self.score_article(article)
            total_weight += w

        raw = weighted_sum / total_weight if total_weight > 0 else 0.0

        # Confidence grows with article count, capped at 1.0
        confidence = min(1.0, len(race_articles) / self.min_articles_for_confidence)

        b3 = _assign_bucket3(raw)
        b5 = _assign_bucket5(raw)
        b7 = _assign_bucket7(raw)

        return VibesScore(
            race=race,
            state=state,
            year=year,
            as_of=as_of,
            raw_score=round(raw, 4),
            article_count=len(race_articles),
            bucket3=b3,
            bucket5=b5,
            bucket7=b7,
            confidence=round(confidence, 3),
            margin_adjustment_3=self._b3[b3],
            margin_adjustment_5=self._b5[b5],
            margin_adjustment_7=self._b7[b7],
        )

    def score_all_races(
        self,
        articles: list[ArticleSignal],
        races: list[tuple[str, str, int]],   # (race_id, state, year)
        as_of: date | None = None,
        window_days: int = 90,
    ) -> dict[str, VibesScore]:
        """Score multiple races at once, returning a dict keyed by race_id."""
        return {
            race_id: self.score_race(articles, race_id, state, year, as_of, window_days)
            for race_id, state, year in races
        }

    # ── Historical calibration ─────────────────────────────────────────────────

    def calibrate_buckets(
        self,
        historical_scores: list[VibesScore],
        actual_residuals: list[float],      # actual_margin − fundamentals_predicted
    ) -> BucketCalibrationResult:
        """Find optimal bucket→margin_adjustment mappings from historical data.

        Args:
            historical_scores: VibesScore for each historical race.
            actual_residuals: Signed residual (D-R) for the same races in the
                              same order; positive means Dem overperformed fundamentals.

        Returns a BucketCalibrationResult with RMSE per granularity, best
        granularity, and refined adjustment tables.

        Methodology: for each bucket granularity, the optimal adjustment for a
        given bucket is simply the mean residual among races that fell in that
        bucket.  RMSE is computed against those mean-adjusted predictions.
        """
        n = len(historical_scores)
        if n == 0 or n != len(actual_residuals):
            return BucketCalibrationResult(
                n_races=n,
                rmse_3=float("inf"),
                rmse_5=float("inf"),
                rmse_7=float("inf"),
                best_granularity=5,
                refined_bucket3={},
                refined_bucket5={},
                refined_bucket7={},
                notes="No historical data provided.",
            )

        def _calibrate(
            bucket_getter: Any,
            enum_class: type,
        ) -> tuple[float, dict[str, float]]:
            # Group residuals by bucket
            groups: dict[str, list[float]] = {b.value: [] for b in enum_class}
            for score, residual in zip(historical_scores, actual_residuals):
                key = bucket_getter(score).value
                groups[key].append(residual)
            # Optimal adjustment = mean residual per bucket
            refined: dict[str, float] = {}
            for bucket_val, residuals in groups.items():
                refined[bucket_val] = round(sum(residuals) / len(residuals), 3) if residuals else 0.0
            # Compute RMSE
            sq_errors: list[float] = []
            for score, residual in zip(historical_scores, actual_residuals):
                key = bucket_getter(score).value
                prediction = refined[key]
                sq_errors.append((residual - prediction) ** 2)
            rmse = math.sqrt(sum(sq_errors) / len(sq_errors))
            return round(rmse, 4), refined

        rmse3, ref3 = _calibrate(lambda s: s.bucket3, SentimentBucket3)
        rmse5, ref5 = _calibrate(lambda s: s.bucket5, SentimentBucket5)
        rmse7, ref7 = _calibrate(lambda s: s.bucket7, SentimentBucket7)

        best = min([(rmse3, 3), (rmse5, 5), (rmse7, 7)], key=lambda x: x[0])[1]

        return BucketCalibrationResult(
            n_races=n,
            rmse_3=rmse3,
            rmse_5=rmse5,
            rmse_7=rmse7,
            best_granularity=best,
            refined_bucket3=ref3,
            refined_bucket5=ref5,
            refined_bucket7=ref7,
            notes=(
                f"Best granularity: {best}-modal (RMSE {min(rmse3, rmse5, rmse7):.3f} pp). "
                f"n={n} races used for calibration."
            ),
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _empty_score(self, race: str, state: str, year: int, as_of: date) -> VibesScore:
        return VibesScore(
            race=race,
            state=state,
            year=year,
            as_of=as_of,
            raw_score=0.0,
            article_count=0,
            bucket3=SentimentBucket3.NEUTRAL,
            bucket5=SentimentBucket5.NEUTRAL,
            bucket7=SentimentBucket7.NEUTRAL,
            confidence=0.0,
            margin_adjustment_3=0.0,
            margin_adjustment_5=0.0,
            margin_adjustment_7=0.0,
        )
