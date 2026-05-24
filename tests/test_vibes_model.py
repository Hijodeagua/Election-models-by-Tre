"""Tests for the vibes model (src/models/vibes.py)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.models.vibes import (
    ArticleSignal,
    SentimentBucket3,
    SentimentBucket5,
    SentimentBucket7,
    VibesModel,
    VibesScore,
    _assign_bucket3,
    _assign_bucket5,
    _assign_bucket7,
    _keyword_score,
    BUCKET3_MARGIN_ADJUSTMENT,
    BUCKET5_MARGIN_ADJUSTMENT,
    BUCKET7_MARGIN_ADJUSTMENT,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _article(
    headline: str = "",
    snippet: str = "",
    days_ago: int = 3,
    race: str = "GA-Senate-2026",
    state: str = "Georgia",
    year: int = 2026,
    raw_sentiment: float | None = None,
) -> ArticleSignal:
    pub = date.today() - timedelta(days=days_ago)
    return ArticleSignal(
        article_id=f"test-{days_ago}-{headline[:8]}",
        headline=headline,
        snippet=snippet,
        publication_date=pub,
        race=race,
        state=state,
        year=year,
        raw_sentiment=raw_sentiment,
    )


# ── Keyword scorer ─────────────────────────────────────────────────────────────

class TestKeywordScorer:
    def test_neutral_returns_zero(self):
        assert _keyword_score("The senator held a press conference") == 0.0

    def test_positive_term_positive_score(self):
        score = _keyword_score("Democrat leads in new poll")
        assert score > 0.0

    def test_negative_term_negative_score(self):
        score = _keyword_score("Democrat struggles amid scandal")
        assert score < 0.0

    def test_score_in_range(self):
        texts = [
            "Senator leads overwhelmingly in new poll",
            "Democrat embattled over ethics scandal and indicted",
            "Campaign releases new ad",
        ]
        for text in texts:
            s = _keyword_score(text)
            assert -1.0 <= s <= 1.0, f"Score {s} out of range for: {text}"

    def test_mixed_terms_middling(self):
        score = _keyword_score("Senator leads but faces backlash over gaffe")
        assert -0.5 < score < 0.5


# ── Bucket assignment ──────────────────────────────────────────────────────────

class TestBucketAssignment:
    def test_bucket3_positive(self):
        assert _assign_bucket3(0.5) == SentimentBucket3.POSITIVE

    def test_bucket3_neutral(self):
        assert _assign_bucket3(0.0) == SentimentBucket3.NEUTRAL
        assert _assign_bucket3(0.10) == SentimentBucket3.NEUTRAL
        assert _assign_bucket3(-0.10) == SentimentBucket3.NEUTRAL

    def test_bucket3_negative(self):
        assert _assign_bucket3(-0.5) == SentimentBucket3.NEGATIVE

    def test_bucket5_covers_all_tiers(self):
        assert _assign_bucket5(0.8) == SentimentBucket5.STRONGLY_POSITIVE
        assert _assign_bucket5(0.3) == SentimentBucket5.LEAN_POSITIVE
        assert _assign_bucket5(0.0) == SentimentBucket5.NEUTRAL
        assert _assign_bucket5(-0.3) == SentimentBucket5.LEAN_NEGATIVE
        assert _assign_bucket5(-0.8) == SentimentBucket5.STRONGLY_NEGATIVE

    def test_bucket7_covers_all_tiers(self):
        assert _assign_bucket7(0.9) == SentimentBucket7.VERY_STRONG_POSITIVE
        assert _assign_bucket7(0.5) == SentimentBucket7.STRONG_POSITIVE
        assert _assign_bucket7(0.2) == SentimentBucket7.LEAN_POSITIVE
        assert _assign_bucket7(0.0) == SentimentBucket7.NEUTRAL
        assert _assign_bucket7(-0.2) == SentimentBucket7.LEAN_NEGATIVE
        assert _assign_bucket7(-0.5) == SentimentBucket7.STRONG_NEGATIVE
        assert _assign_bucket7(-0.9) == SentimentBucket7.VERY_STRONG_NEGATIVE

    def test_bucket3_boundary_positive(self):
        # Exactly at threshold → neutral
        assert _assign_bucket3(0.15) == SentimentBucket3.NEUTRAL
        # Just above → positive
        assert _assign_bucket3(0.16) == SentimentBucket3.POSITIVE


# ── Margin adjustments ─────────────────────────────────────────────────────────

class TestMarginAdjustments:
    def test_all_bucket3_have_adjustments(self):
        for bucket in SentimentBucket3:
            assert bucket in BUCKET3_MARGIN_ADJUSTMENT

    def test_all_bucket5_have_adjustments(self):
        for bucket in SentimentBucket5:
            assert bucket in BUCKET5_MARGIN_ADJUSTMENT

    def test_all_bucket7_have_adjustments(self):
        for bucket in SentimentBucket7:
            assert bucket in BUCKET7_MARGIN_ADJUSTMENT

    def test_positive_buckets_positive_adjustment(self):
        assert BUCKET3_MARGIN_ADJUSTMENT[SentimentBucket3.POSITIVE] > 0
        assert BUCKET5_MARGIN_ADJUSTMENT[SentimentBucket5.STRONGLY_POSITIVE] > 0
        assert BUCKET7_MARGIN_ADJUSTMENT[SentimentBucket7.VERY_STRONG_POSITIVE] > 0

    def test_negative_buckets_negative_adjustment(self):
        assert BUCKET3_MARGIN_ADJUSTMENT[SentimentBucket3.NEGATIVE] < 0
        assert BUCKET5_MARGIN_ADJUSTMENT[SentimentBucket5.STRONGLY_NEGATIVE] < 0
        assert BUCKET7_MARGIN_ADJUSTMENT[SentimentBucket7.VERY_STRONG_NEGATIVE] < 0

    def test_neutral_buckets_zero_adjustment(self):
        assert BUCKET3_MARGIN_ADJUSTMENT[SentimentBucket3.NEUTRAL] == 0.0
        assert BUCKET5_MARGIN_ADJUSTMENT[SentimentBucket5.NEUTRAL] == 0.0
        assert BUCKET7_MARGIN_ADJUSTMENT[SentimentBucket7.NEUTRAL] == 0.0

    def test_monotone_5_modal(self):
        # Strongly positive > lean positive > neutral > lean negative > strongly negative
        vals = [
            BUCKET5_MARGIN_ADJUSTMENT[SentimentBucket5.STRONGLY_POSITIVE],
            BUCKET5_MARGIN_ADJUSTMENT[SentimentBucket5.LEAN_POSITIVE],
            BUCKET5_MARGIN_ADJUSTMENT[SentimentBucket5.NEUTRAL],
            BUCKET5_MARGIN_ADJUSTMENT[SentimentBucket5.LEAN_NEGATIVE],
            BUCKET5_MARGIN_ADJUSTMENT[SentimentBucket5.STRONGLY_NEGATIVE],
        ]
        assert vals == sorted(vals, reverse=True)


# ── VibesModel.score_article ───────────────────────────────────────────────────

class TestVibesModelScoreArticle:
    def setup_method(self):
        self.model = VibesModel()

    def test_uses_raw_sentiment_when_provided(self):
        article = _article(headline="irrelevant text", raw_sentiment=0.75)
        assert self.model.score_article(article) == 0.75

    def test_raw_sentiment_clamped(self):
        article = _article(raw_sentiment=2.5)
        assert self.model.score_article(article) == 1.0

    def test_falls_back_to_keyword_scorer(self):
        article = _article(headline="Democrat leads in Georgia Senate race")
        score = self.model.score_article(article)
        assert isinstance(score, float)
        assert -1.0 <= score <= 1.0


# ── VibesModel.score_race ──────────────────────────────────────────────────────

class TestVibesModelScoreRace:
    def setup_method(self):
        self.model = VibesModel()

    def test_empty_articles_returns_neutral_score(self):
        score = self.model.score_race([], "GA-Senate-2026", "Georgia", 2026)
        assert isinstance(score, VibesScore)
        assert score.raw_score == 0.0
        assert score.article_count == 0
        assert score.bucket3 == SentimentBucket3.NEUTRAL
        assert score.confidence == 0.0

    def test_all_positive_articles_positive_score(self):
        articles = [
            _article(headline="Democrat leads overwhelmingly in Georgia Senate race", days_ago=i)
            for i in range(1, 6)
        ]
        score = self.model.score_race(articles, "GA-Senate-2026", "Georgia", 2026)
        assert score.raw_score > 0.0
        assert score.article_count == 5

    def test_all_negative_articles_negative_score(self):
        articles = [
            _article(headline="Democrat embattled over scandal in Georgia Senate", days_ago=i)
            for i in range(1, 6)
        ]
        score = self.model.score_race(articles, "GA-Senate-2026", "Georgia", 2026)
        assert score.raw_score < 0.0

    def test_confidence_grows_with_article_count(self):
        low_articles = [_article(days_ago=i) for i in range(1, 3)]
        high_articles = [_article(days_ago=i) for i in range(1, 20)]
        low_score = self.model.score_race(low_articles, "GA-Senate-2026", "Georgia", 2026)
        high_score = self.model.score_race(high_articles, "GA-Senate-2026", "Georgia", 2026)
        assert high_score.confidence > low_score.confidence

    def test_confidence_capped_at_one(self):
        articles = [_article(days_ago=i) for i in range(1, 100)]
        score = self.model.score_race(articles, "GA-Senate-2026", "Georgia", 2026)
        assert score.confidence <= 1.0

    def test_filters_by_race_id(self):
        ga = _article(race="GA-Senate-2026", headline="Democrat leads")
        az = _article(race="AZ-Senate-2026", headline="Democrat leads")
        score = self.model.score_race([ga, az], "GA-Senate-2026", "Georgia", 2026)
        assert score.article_count == 1

    def test_filters_by_date_window(self):
        recent = _article(days_ago=10, headline="Democrat leads")
        old = _article(days_ago=200, headline="Democrat leads")
        score = self.model.score_race(
            [recent, old], "GA-Senate-2026", "Georgia", 2026, window_days=90
        )
        assert score.article_count == 1

    def test_recency_downweights_old_articles(self):
        """Two identical articles: one recent, one old. Recent should dominate score."""
        recent_pos = _article(days_ago=2, headline="Democrat leads", raw_sentiment=0.8)
        old_neg = _article(days_ago=89, headline="scandal", raw_sentiment=-0.8)
        score = self.model.score_race(
            [recent_pos, old_neg], "GA-Senate-2026", "Georgia", 2026, window_days=90
        )
        # With half-life=30 days, old article has weight exp(-ln2*89/30) ≈ 0.13 vs 1.0 for recent
        assert score.raw_score > 0.0, "Recent positive article should dominate old negative one"

    def test_vibes_score_has_all_bucket_types(self):
        articles = [_article(headline="Democrat leads", days_ago=i) for i in range(1, 4)]
        score = self.model.score_race(articles, "GA-Senate-2026", "Georgia", 2026)
        assert isinstance(score.bucket3, SentimentBucket3)
        assert isinstance(score.bucket5, SentimentBucket5)
        assert isinstance(score.bucket7, SentimentBucket7)

    def test_margin_adjustment_property_uses_5modal(self):
        articles = [_article(raw_sentiment=0.9, days_ago=i) for i in range(1, 4)]
        score = self.model.score_race(articles, "GA-Senate-2026", "Georgia", 2026)
        assert score.margin_adjustment == score.margin_adjustment_5

    def test_pre_scored_articles_aggregate_correctly(self):
        articles = [
            _article(raw_sentiment=0.4, days_ago=1),
            _article(raw_sentiment=0.4, days_ago=2),
        ]
        score = self.model.score_race(articles, "GA-Senate-2026", "Georgia", 2026)
        # Both articles should produce a positive score around 0.4
        assert score.raw_score > 0.3


# ── VibesModel.calibrate_buckets ──────────────────────────────────────────────

class TestVibesModelCalibration:
    def setup_method(self):
        self.model = VibesModel()

    def _make_historical_scores(self, raw_scores: list[float]) -> list[VibesScore]:
        return [
            self.model.score_race(
                [_article(raw_sentiment=s, days_ago=5)],
                "GA-Senate-2022",
                "Georgia",
                2022,
                as_of=date(2022, 11, 1),
            )
            for s in raw_scores
        ]

    def test_calibration_empty_returns_no_data(self):
        result = self.model.calibrate_buckets([], [])
        assert result.n_races == 0

    def test_calibration_mismatched_lengths(self):
        result = self.model.calibrate_buckets([], [1.0, 2.0])
        assert result.n_races == 0

    def test_calibration_produces_rmse_per_granularity(self):
        scores = self._make_historical_scores([0.6, 0.3, 0.0, -0.3, -0.6])
        residuals = [3.0, 1.5, 0.0, -1.5, -3.0]
        result = self.model.calibrate_buckets(scores, residuals)
        assert result.n_races == 5
        assert result.rmse_3 >= 0.0
        assert result.rmse_5 >= 0.0
        assert result.rmse_7 >= 0.0
        assert result.best_granularity in (3, 5, 7)

    def test_calibration_refined_tables_have_all_buckets(self):
        scores = self._make_historical_scores([0.6, 0.3, 0.0, -0.3, -0.6])
        residuals = [3.0, 1.5, 0.0, -1.5, -3.0]
        result = self.model.calibrate_buckets(scores, residuals)
        for b in SentimentBucket3:
            assert b.value in result.refined_bucket3
        for b in SentimentBucket5:
            assert b.value in result.refined_bucket5
        for b in SentimentBucket7:
            assert b.value in result.refined_bucket7

    def test_calibration_notes_string(self):
        scores = self._make_historical_scores([0.5, -0.5])
        residuals = [2.0, -2.0]
        result = self.model.calibrate_buckets(scores, residuals)
        assert isinstance(result.notes, str)
        assert len(result.notes) > 0


# ── Integration: vibes → senate margin ────────────────────────────────────────

class TestVibesSenateIntegration:
    """Verify VibesScore.margin_adjustment is usable by SenateModel."""

    def test_positive_vibes_positive_margin_adjustment(self):
        model = VibesModel()
        articles = [
            _article(raw_sentiment=0.7, days_ago=i)
            for i in range(1, 8)
        ]
        score = model.score_race(articles, "GA-Senate-2026", "Georgia", 2026)
        assert score.margin_adjustment > 0.0

    def test_negative_vibes_negative_margin_adjustment(self):
        model = VibesModel()
        articles = [
            _article(raw_sentiment=-0.7, days_ago=i)
            for i in range(1, 8)
        ]
        score = model.score_race(articles, "GA-Senate-2026", "Georgia", 2026)
        assert score.margin_adjustment < 0.0

    def test_margin_adjustment_bounded(self):
        model = VibesModel()
        articles = [_article(raw_sentiment=0.99, days_ago=i) for i in range(1, 20)]
        score = model.score_race(articles, "GA-Senate-2026", "Georgia", 2026)
        # Even max vibes should not produce absurd margin shifts
        assert abs(score.margin_adjustment_7) <= 5.0
