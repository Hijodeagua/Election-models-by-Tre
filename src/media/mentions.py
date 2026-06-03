"""Candidate mention extraction and sentence-level windowing.

Given an article and a set of candidate names, extracts the sentences
that mention each candidate so sentiment can be scored at the
candidate level rather than the article level.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class CandidateMention:
    """A single mention of a candidate within an article."""

    candidate: str
    sentence: str
    context_window: str  # surrounding sentences for broader context
    position: int  # character offset in the source text
    article_id: str = ""


@dataclass
class CandidateProfile:
    """Defines how to find a candidate in text."""

    canonical_name: str  # e.g., "John Fetterman"
    party: str  # "D" or "R"
    aliases: list[str] = field(default_factory=list)
    # Auto-generated: last name, first+last, title variants
    # e.g., ["Fetterman", "John Fetterman", "Lt. Gov. Fetterman"]

    @property
    def all_patterns(self) -> list[str]:
        """All name patterns to search for, longest first."""
        patterns = [self.canonical_name] + self.aliases
        # Add last name as fallback
        parts = self.canonical_name.split()
        if len(parts) >= 2:
            patterns.append(parts[-1])  # last name
        # Deduplicate and sort longest-first to avoid partial matches
        seen: set[str] = set()
        unique = []
        for p in patterns:
            if p.lower() not in seen:
                seen.add(p.lower())
                unique.append(p)
        return sorted(unique, key=len, reverse=True)


# ── Sentence splitting ────────────────────────────────────────────────

_SENTENCE_SPLIT = re.compile(
    r'(?<=[.!?])\s+(?=[A-Z"“])'
)


def split_sentences(text: str) -> list[str]:
    """Split text into sentences. Simple regex-based — good enough for news prose."""
    if not text:
        return []
    sentences = _SENTENCE_SPLIT.split(text.strip())
    return [s.strip() for s in sentences if s.strip()]


# ── Mention extraction ────────────────────────────────────────────────


def extract_mentions(
    text: str,
    candidates: list[CandidateProfile],
    article_id: str = "",
    context_window_size: int = 1,
) -> list[CandidateMention]:
    """Extract all candidate mentions from text with surrounding context.

    Args:
        text: The article text (headline + abstract + lead paragraph).
        candidates: List of candidate profiles to search for.
        article_id: ID of the source article.
        context_window_size: Number of sentences before/after the mention
            to include as context.

    Returns:
        List of CandidateMention objects, one per mention instance.
    """
    if not text or not candidates:
        return []

    sentences = split_sentences(text)
    mentions: list[CandidateMention] = []
    seen_sentence_candidate: set[tuple[int, str]] = set()

    for candidate in candidates:
        for pattern in candidate.all_patterns:
            pat = re.compile(re.escape(pattern), re.IGNORECASE)

            for i, sentence in enumerate(sentences):
                if not pat.search(sentence):
                    continue

                # Deduplicate: same sentence + same candidate
                key = (i, candidate.canonical_name)
                if key in seen_sentence_candidate:
                    continue
                seen_sentence_candidate.add(key)

                # Build context window
                start = max(0, i - context_window_size)
                end = min(len(sentences), i + context_window_size + 1)
                context = " ".join(sentences[start:end])

                # Character position in original text
                position = text.find(sentence)

                mentions.append(CandidateMention(
                    candidate=candidate.canonical_name,
                    sentence=sentence,
                    context_window=context,
                    position=max(0, position),
                    article_id=article_id,
                ))

    return mentions


def count_mentions_by_candidate(
    mentions: list[CandidateMention],
) -> dict[str, int]:
    """Count total mentions per candidate."""
    counts: dict[str, int] = {}
    for m in mentions:
        counts[m.candidate] = counts.get(m.candidate, 0) + 1
    return counts
