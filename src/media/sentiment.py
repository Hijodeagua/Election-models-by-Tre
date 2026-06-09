"""Sentiment scoring for candidate mentions.

Two backends:
    1. TransformerScorer — uses a HuggingFace model
       (cardiffnlp/twitter-roberta-base-sentiment-latest)
       for production-quality scoring. Requires `transformers` and `torch`.
    2. KeywordScorer — lightweight fallback using curated political-news word lists.
       No ML dependencies. Useful for testing and as a baseline.

Both return a SentimentScore with positive/negative/neutral probabilities.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.media.mentions import CandidateMention


@dataclass
class SentimentScore:
    """Sentiment classification for a single text span."""

    positive: float  # 0–1 probability
    negative: float
    neutral: float

    @property
    def compound(self) -> float:
        """Single score from -1 (most negative) to +1 (most positive)."""
        return self.positive - self.negative

    @property
    def label(self) -> str:
        """Dominant sentiment label."""
        scores = {"positive": self.positive, "negative": self.negative, "neutral": self.neutral}
        return max(scores, key=scores.get)  # type: ignore[arg-type]


@dataclass
class ScoredMention:
    """A candidate mention with its sentiment score attached."""

    mention: CandidateMention
    score: SentimentScore


# ── Abstract base ─────────────────────────────────────────────────────


class SentimentScorer(ABC):
    """Interface for sentiment scoring backends."""

    @abstractmethod
    def score_text(self, text: str) -> SentimentScore:
        """Score a single text span."""
        ...

    def score_mention(self, mention: CandidateMention) -> ScoredMention:
        """Score a candidate mention using its context window."""
        score = self.score_text(mention.context_window)
        return ScoredMention(mention=mention, score=score)

    def score_mentions(self, mentions: list[CandidateMention]) -> list[ScoredMention]:
        """Score a batch of mentions."""
        return [self.score_mention(m) for m in mentions]


# ── Transformer backend ──────────────────────────────────────────────


class TransformerScorer(SentimentScorer):
    """HuggingFace transformer-based sentiment scorer.

    Default model: cardiffnlp/twitter-roberta-base-sentiment-latest
    Labels: negative (0), neutral (1), positive (2)
    """

    def __init__(
        self, model_name: str = "cardiffnlp/twitter-roberta-base-sentiment-latest"
    ) -> None:
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            raise ImportError(
                "TransformerScorer requires `transformers` and `torch`. "
                "Install with: pip install election-oracle[ml]"
            ) from exc

        self._tokenizer = AutoTokenizer.from_pretrained(model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self._model.eval()
        self._torch = torch

    def score_text(self, text: str) -> SentimentScore:
        """Score text using the transformer model."""
        inputs = self._tokenizer(
            text, return_tensors="pt", truncation=True, max_length=512
        )
        with self._torch.no_grad():
            outputs = self._model(**inputs)

        probs = self._torch.nn.functional.softmax(outputs.logits, dim=-1)[0]
        # cardiffnlp order: negative=0, neutral=1, positive=2
        return SentimentScore(
            negative=float(probs[0]),
            neutral=float(probs[1]),
            positive=float(probs[2]),
        )


# ── Keyword-based fallback ───────────────────────────────────────────

# Curated for political news — not generic sentiment words.
# Weighted heavier on campaign-relevant framing.
_POSITIVE_PATTERNS: list[tuple[str, float]] = [
    (r"\b(?:surge[ds]?|surging)\b", 1.0),
    (r"\b(?:lead[s]?|leading|ahead)\b", 0.8),
    (r"\b(?:endorse[ds]?|endorsement|backed by)\b", 1.0),
    (r"\b(?:momentum|energize[ds]?|enthusiasm)\b", 0.9),
    (r"\b(?:popular|favorab(?:le|ility)|well-liked)\b", 0.8),
    (r"\b(?:win[s]?|winning|won|victory|victorious)\b", 1.0),
    (r"\b(?:strong|strengthen(?:s|ed)?|outperform(?:s|ed)?)\b", 0.7),
    (r"\b(?:fundrais(?:ing|ed)|outrais(?:e[ds]?|ing))\b", 0.6),
    (r"\b(?:bipartisan|unif(?:y|ied|ying)|coalition)\b", 0.5),
    (r"\b(?:praised|applauded|celebrated)\b", 0.7),
    (r"\b(?:record turnout|energized base|grassroots)\b", 0.6),
]

_NEGATIVE_PATTERNS: list[tuple[str, float]] = [
    (r"\b(?:scandal[s]?|scandalous)\b", 1.5),
    (r"\b(?:indict(?:ed|ment|s)?|charged with|arraign(?:ed|ment))\b", 1.5),
    (r"\b(?:investigat(?:ion|ed|ing)|probe[ds]?|subpoena)\b", 1.2),
    (r"\b(?:gaffe[s]?|blunder[s]?|stumble[ds]?)\b", 1.0),
    (r"\b(?:controver(?:sy|sial)|backlash|outrage[ds]?)\b", 1.0),
    (r"\b(?:trail(?:s|ing)|behind|losing|lost)\b", 0.8),
    (r"\b(?:attack(?:s|ed)?|slam(?:s|med)?|blast(?:s|ed)?)\b", 0.6),
    (r"\b(?:unpopular|unfavorab(?:le|ility))\b", 0.9),
    (r"\b(?:resign(?:s|ed|ation)?|step(?:s|ped)? down)\b", 1.2),
    (r"\b(?:ethical|ethics) (?:violation|complaint|issue)\b", 1.1),
    (r"\b(?:lawsuit[s]?|sued|litigation)\b", 0.8),
    (r"\b(?:denied|deny|denies|allegations?)\b", 0.7),
    (r"\b(?:embattled|troubled|beleaguered|dogged)\b", 1.0),
    (r"\b(?:flip-flop(?:s|ped)?|waffled?|reversal)\b", 0.6),
    (r"\b(?:extremis[mt]|radical|far-(?:left|right))\b", 0.7),
    (r"\b(?:divisive|polariz(?:ing|ed))\b", 0.5),
]


class KeywordScorer(SentimentScorer):
    """Lightweight keyword-based sentiment scorer tuned for political news.

    Uses curated regex patterns with campaign-relevant weighting.
    Not as accurate as a transformer, but zero-dependency and interpretable.
    """

    def __init__(self) -> None:
        self._pos_compiled = [(re.compile(p, re.IGNORECASE), w) for p, w in _POSITIVE_PATTERNS]
        self._neg_compiled = [(re.compile(p, re.IGNORECASE), w) for p, w in _NEGATIVE_PATTERNS]

    def score_text(self, text: str) -> SentimentScore:
        pos_score = sum(w for pat, w in self._pos_compiled if pat.search(text))
        neg_score = sum(w for pat, w in self._neg_compiled if pat.search(text))
        total = pos_score + neg_score

        if total == 0:
            return SentimentScore(positive=0.1, negative=0.1, neutral=0.8)

        # Normalize to probabilities
        pos_prob = pos_score / (total + 1.0)
        neg_prob = neg_score / (total + 1.0)
        neu_prob = 1.0 - pos_prob - neg_prob
        return SentimentScore(
            positive=round(pos_prob, 3),
            negative=round(neg_prob, 3),
            neutral=round(max(0.0, neu_prob), 3),
        )


def get_scorer(backend: str = "keyword") -> SentimentScorer:
    """Factory to get a sentiment scorer by backend name."""
    if backend == "transformer":
        return TransformerScorer()
    elif backend == "keyword":
        return KeywordScorer()
    else:
        raise ValueError(f"Unknown sentiment backend: {backend}")
