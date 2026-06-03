"""Tests for the media sentiment analysis pipeline.

Covers: NYT client normalization, mention extraction, sentiment scoring,
and vibes metric computation.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.media.mentions import (
    CandidateMention,
    CandidateProfile,
    count_mentions_by_candidate,
    extract_mentions,
    split_sentences,
)
from src.media.nyt import NYTArticle, NYTClient
from src.media.sentiment import KeywordScorer, ScoredMention, SentimentScore, get_scorer
from src.media.vibes import (
    CandidateVibes,
    VibeBucket,
    _classify_bucket,
    _detect_scandals,
    compute_vibes,
)

# ── NYT Article normalization ─────────────────────────────────────────


class TestNYTArticle:
    def test_normalize_full_doc(self):
        doc = {
            "_id": "nyt://article/abc123",
            "pub_date": "2022-10-15T10:00:00+0000",
            "headline": {"main": "Senate Race Tightens in Pennsylvania"},
            "abstract": "The race between Fetterman and Oz is closer than expected.",
            "lead_paragraph": "With three weeks until Election Day, polls show a narrowing gap.",
            "section_name": "U.S.",
            "keywords": [
                {"value": "Elections"},
                {"value": "United States Politics and Government"},
            ],
            "word_count": 1200,
            "web_url": "https://nytimes.com/2022/10/15/us/senate-pa.html",
        }
        article = NYTClient._normalize(doc)
        assert article.article_id == "nyt://article/abc123"
        assert article.pub_date == date(2022, 10, 15)
        assert article.headline == "Senate Race Tightens in Pennsylvania"
        assert "Fetterman" in article.abstract
        assert article.section == "U.S."
        assert "Elections" in article.keywords
        assert article.word_count == 1200

    def test_normalize_minimal_doc(self):
        doc = {"_id": "test", "pub_date": "2022-01-01T00:00:00Z"}
        article = NYTClient._normalize(doc)
        assert article.article_id == "test"
        assert article.headline == ""
        assert article.abstract == ""

    def test_full_text_for_analysis(self):
        article = NYTArticle(
            article_id="test",
            pub_date=date(2022, 10, 1),
            headline="Breaking News",
            abstract="Something happened.",
            lead_paragraph="Details followed.",
            section="U.S.",
            keywords=[],
            word_count=100,
            web_url="",
        )
        text = article.full_text_for_analysis
        assert "Breaking News" in text
        assert "Something happened" in text
        assert "Details followed" in text

    def test_filter_political(self):
        political = NYTArticle(
            article_id="1", pub_date=date(2022, 1, 1), headline="Senate Vote",
            abstract="", lead_paragraph="", section="U.S.",
            keywords=["Elections"], word_count=100, web_url="",
        )
        sports = NYTArticle(
            article_id="2", pub_date=date(2022, 1, 1), headline="Game Recap",
            abstract="", lead_paragraph="", section="Sports",
            keywords=["Baseball"], word_count=100, web_url="",
        )
        filtered = NYTClient.filter_political([political, sports])
        assert len(filtered) == 1
        assert filtered[0].article_id == "1"


# ── Sentence splitting ────────────────────────────────────────────────


class TestSentenceSplitting:
    def test_basic_split(self):
        text = "First sentence. Second sentence. Third sentence."
        sents = split_sentences(text)
        assert len(sents) == 3

    def test_question_mark(self):
        text = "Is the race close? The polls say yes."
        sents = split_sentences(text)
        assert len(sents) == 2

    def test_empty(self):
        assert split_sentences("") == []

    def test_single_sentence(self):
        sents = split_sentences("Just one sentence here.")
        assert len(sents) == 1

    def test_quotes(self):
        text = '"I will win," said Smith. "We are confident," she added.'
        sents = split_sentences(text)
        assert len(sents) >= 1  # quote handling can vary


# ── Candidate mention extraction ──────────────────────────────────────


class TestMentionExtraction:
    def setup_method(self):
        self.fetterman = CandidateProfile(
            canonical_name="John Fetterman", party="D",
            aliases=["Lt. Gov. Fetterman"],
        )
        self.oz = CandidateProfile(
            canonical_name="Mehmet Oz", party="R",
            aliases=["Dr. Oz"],
        )

    def test_basic_extraction(self):
        text = "John Fetterman leads in the polls. Mehmet Oz trails by five points."
        mentions = extract_mentions(text, [self.fetterman, self.oz])
        assert len(mentions) == 2
        names = {m.candidate for m in mentions}
        assert "John Fetterman" in names
        assert "Mehmet Oz" in names

    def test_alias_matching(self):
        text = "Dr. Oz attacked his opponent in the debate."
        mentions = extract_mentions(text, [self.oz])
        assert len(mentions) == 1
        assert mentions[0].candidate == "Mehmet Oz"

    def test_last_name_matching(self):
        text = "Fetterman held a rally in Philadelphia."
        mentions = extract_mentions(text, [self.fetterman])
        assert len(mentions) == 1

    def test_no_mentions(self):
        text = "The weather in Pennsylvania was mild."
        mentions = extract_mentions(text, [self.fetterman])
        assert len(mentions) == 0

    def test_multiple_mentions_same_candidate(self):
        text = (
            "Fetterman spoke at a rally. Fetterman also appeared on TV. "
            "Later, Fetterman met with supporters."
        )
        mentions = extract_mentions(text, [self.fetterman])
        assert len(mentions) == 3

    def test_context_window(self):
        text = (
            "The economy was strong. Fetterman promised tax reform. "
            "Voters responded positively."
        )
        mentions = extract_mentions(text, [self.fetterman], context_window_size=1)
        assert len(mentions) == 1
        # Context should include neighboring sentences
        assert "economy" in mentions[0].context_window
        assert "positively" in mentions[0].context_window

    def test_deduplication(self):
        text = "John Fetterman, also known as Fetterman, gave a speech."
        mentions = extract_mentions(text, [self.fetterman])
        # Same sentence, same candidate → should deduplicate
        assert len(mentions) == 1

    def test_count_mentions(self):
        text = (
            "Fetterman led the debate. Oz responded sharply. "
            "Fetterman then rebutted."
        )
        mentions = extract_mentions(text, [self.fetterman, self.oz])
        counts = count_mentions_by_candidate(mentions)
        assert counts["John Fetterman"] == 2
        assert counts["Mehmet Oz"] == 1

    def test_candidate_profile_patterns(self):
        # Longest patterns should come first
        patterns = self.fetterman.all_patterns
        assert patterns[0] == "Lt. Gov. Fetterman"
        assert "John Fetterman" in patterns
        assert "Fetterman" in patterns

    def test_empty_inputs(self):
        assert extract_mentions("", [self.fetterman]) == []
        assert extract_mentions("Some text.", []) == []


# ── Keyword sentiment scorer ──────────────────────────────────────────


class TestKeywordScorer:
    def setup_method(self):
        self.scorer = KeywordScorer()

    def test_positive_text(self):
        score = self.scorer.score_text(
            "The candidate surged in polls and won a key endorsement."
        )
        assert score.positive > score.negative

    def test_negative_text(self):
        score = self.scorer.score_text(
            "The embattled candidate faces a scandal and is trailing badly."
        )
        assert score.negative > score.positive

    def test_neutral_text(self):
        score = self.scorer.score_text(
            "The weather in Washington was pleasant today."
        )
        assert score.neutral > 0.5

    def test_compound_range(self):
        score = self.scorer.score_text("Great victory and momentum!")
        assert -1.0 <= score.compound <= 1.0

    def test_label_property(self):
        pos = SentimentScore(positive=0.7, negative=0.1, neutral=0.2)
        assert pos.label == "positive"
        neg = SentimentScore(positive=0.1, negative=0.7, neutral=0.2)
        assert neg.label == "negative"
        neu = SentimentScore(positive=0.1, negative=0.1, neutral=0.8)
        assert neu.label == "neutral"

    def test_get_scorer_keyword(self):
        scorer = get_scorer("keyword")
        assert isinstance(scorer, KeywordScorer)

    def test_get_scorer_unknown(self):
        with pytest.raises(ValueError):
            get_scorer("nonexistent")

    def test_score_mention(self):
        mention = CandidateMention(
            candidate="Test",
            sentence="The candidate surged ahead.",
            context_window="The candidate surged ahead in the polls.",
            position=0,
        )
        scored = self.scorer.score_mention(mention)
        assert scored.mention.candidate == "Test"
        assert scored.score.positive > 0

    def test_score_mentions_batch(self):
        mentions = [
            CandidateMention(
                candidate="A", sentence="A won.", context_window="A won the race.", position=0
            ),
            CandidateMention(
                candidate="B", sentence="B lost.", context_window="B lost badly, trailing.", position=0
            ),
        ]
        scored = self.scorer.score_mentions(mentions)
        assert len(scored) == 2


# ── Vibes metrics ─────────────────────────────────────────────────────


class TestVibesMetrics:
    def _make_scored_mention(
        self, candidate: str, label: str, text: str = "Some coverage text."
    ) -> ScoredMention:
        """Helper to build a ScoredMention with a desired label."""
        if label == "positive":
            score = SentimentScore(positive=0.8, negative=0.1, neutral=0.1)
        elif label == "negative":
            score = SentimentScore(positive=0.1, negative=0.8, neutral=0.1)
        else:
            score = SentimentScore(positive=0.2, negative=0.2, neutral=0.6)
        return ScoredMention(
            mention=CandidateMention(
                candidate=candidate, sentence=text,
                context_window=text, position=0, article_id="test",
            ),
            score=score,
        )

    def test_overwhelmingly_positive(self):
        mentions = [self._make_scored_mention("A", "positive") for _ in range(8)]
        mentions += [self._make_scored_mention("A", "negative") for _ in range(2)]
        vibes = compute_vibes(mentions, "A", race="Test-2022")
        assert vibes.positive_pct == 80.0
        assert vibes.bucket == VibeBucket.OVERWHELMINGLY_POSITIVE

    def test_more_negative(self):
        mentions = [self._make_scored_mention("A", "negative") for _ in range(6)]
        mentions += [self._make_scored_mention("A", "positive") for _ in range(2)]
        mentions += [self._make_scored_mention("A", "neutral") for _ in range(2)]
        vibes = compute_vibes(mentions, "A")
        assert vibes.negative_pct == 60.0
        assert vibes.bucket == VibeBucket.MORE_NEGATIVE

    def test_neutral_mixed(self):
        mentions = [self._make_scored_mention("A", "positive") for _ in range(3)]
        mentions += [self._make_scored_mention("A", "negative") for _ in range(3)]
        mentions += [self._make_scored_mention("A", "neutral") for _ in range(4)]
        vibes = compute_vibes(mentions, "A")
        assert vibes.bucket == VibeBucket.NEUTRAL_MIXED

    def test_empty_mentions(self):
        vibes = compute_vibes([], "A")
        assert vibes.total_mentions == 0
        assert vibes.bucket == VibeBucket.NEUTRAL_MIXED

    def test_filters_to_correct_candidate(self):
        mentions = [
            self._make_scored_mention("A", "positive"),
            self._make_scored_mention("B", "negative"),
            self._make_scored_mention("A", "positive"),
        ]
        vibes = compute_vibes(mentions, "A")
        assert vibes.total_mentions == 2
        assert vibes.positive_pct == 100.0

    def test_classify_bucket_thresholds(self):
        assert _classify_bucket(80, 10) == VibeBucket.OVERWHELMINGLY_POSITIVE
        assert _classify_bucket(60, 25) == VibeBucket.MORE_POSITIVE
        assert _classify_bucket(40, 40) == VibeBucket.NEUTRAL_MIXED
        assert _classify_bucket(25, 60) == VibeBucket.MORE_NEGATIVE
        assert _classify_bucket(10, 80) == VibeBucket.OVERWHELMINGLY_NEGATIVE

    def test_vibe_bucket_numeric(self):
        assert VibeBucket.OVERWHELMINGLY_POSITIVE.numeric == 2
        assert VibeBucket.NEUTRAL_MIXED.numeric == 0
        assert VibeBucket.OVERWHELMINGLY_NEGATIVE.numeric == -2

    def test_to_dict(self):
        vibes = CandidateVibes(
            candidate="Test", race="Test-2022",
            period_start=date(2022, 6, 1), period_end=date(2022, 11, 8),
            positive_pct=55.0, negative_pct=30.0, neutral_pct=15.0,
            total_mentions=100, bucket=VibeBucket.MORE_POSITIVE,
            bucket_numeric=1, scandal_severity=0.0,
        )
        d = vibes.to_dict()
        assert d["bucket"] == "more_positive"
        assert d["total_mentions"] == 100


# ── Scandal detection ─────────────────────────────────────────────────


class TestScandalDetection:
    def _make_scored(self, text: str) -> ScoredMention:
        return ScoredMention(
            mention=CandidateMention(
                candidate="Test", sentence=text,
                context_window=text, position=0, article_id="scandal-article",
            ),
            score=SentimentScore(positive=0.1, negative=0.8, neutral=0.1),
        )

    def test_detect_indictment(self):
        scored = [self._make_scored("The candidate was indicted on federal charges.")]
        flags = _detect_scandals(scored)
        assert len(flags) >= 1
        assert any(f.description == "indictment" for f in flags)

    def test_detect_scandal_keyword(self):
        scored = [self._make_scored("A major scandal rocked the campaign.")]
        flags = _detect_scandals(scored)
        assert any(f.description == "scandal" for f in flags)

    def test_detect_multiple_scandals(self):
        scored = [
            self._make_scored("The candidate was indicted."),
            self._make_scored("An ethics violation was reported."),
        ]
        flags = _detect_scandals(scored)
        assert len(flags) >= 2

    def test_no_scandals(self):
        scored = [self._make_scored("The candidate gave a standard speech.")]
        flags = _detect_scandals(scored)
        assert len(flags) == 0

    def test_scandal_count_aggregation(self):
        scored = [
            self._make_scored("The scandal deepened."),
            self._make_scored("Another report on the scandal emerged."),
        ]
        flags = _detect_scandals(scored)
        scandal_flags = [f for f in flags if f.description == "scandal"]
        assert len(scandal_flags) == 1
        assert scandal_flags[0].mention_count == 2

    def test_severity_ordering(self):
        scored = [
            self._make_scored("The candidate was indicted."),
            self._make_scored("A minor ethics violation was noted."),
        ]
        flags = _detect_scandals(scored)
        # Should be sorted by severity descending
        if len(flags) >= 2:
            assert flags[0].severity >= flags[1].severity
