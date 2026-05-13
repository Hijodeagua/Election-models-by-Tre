"""The three vibes metrics for candidate media coverage.

Metric 1: Simple positive/negative percentage of coverage.
Metric 2: Five-bucket categorical classification.
Metric 3: Scandal / big-problem flags with severity scoring.

All metrics are computed from a list of ScoredMentions for a candidate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any

from src.media.sentiment import ScoredMention, SentimentScore


# ── Metric 2: Five-bucket classification ──────────────────────────────


class VibeBucket(str, Enum):
    OVERWHELMINGLY_POSITIVE = "overwhelmingly_positive"
    MORE_POSITIVE = "more_positive"
    NEUTRAL_MIXED = "neutral_mixed"
    MORE_NEGATIVE = "more_negative"
    OVERWHELMINGLY_NEGATIVE = "overwhelmingly_negative"

    @property
    def numeric(self) -> int:
        """Numeric encoding: -2 to +2."""
        return {
            VibeBucket.OVERWHELMINGLY_NEGATIVE: -2,
            VibeBucket.MORE_NEGATIVE: -1,
            VibeBucket.NEUTRAL_MIXED: 0,
            VibeBucket.MORE_POSITIVE: 1,
            VibeBucket.OVERWHELMINGLY_POSITIVE: 2,
        }[self]


# ── Metric 3: Scandal detection ──────────────────────────────────────


@dataclass
class ScandalFlag:
    """A detected scandal or major problem in coverage."""

    description: str  # e.g., "indictment", "ethics investigation"
    severity: float  # 0–1 scale
    mention_count: int
    first_seen: str  # article_id or date string
    sample_text: str = ""


# Scandal trigger patterns with severity weights
_SCANDAL_TRIGGERS: list[tuple[str, str, float]] = [
    (r"\bindict(?:ed|ment|s)?\b", "indictment", 1.0),
    (r"\barraign(?:ed|ment)\b", "arraignment", 1.0),
    (r"\b(?:criminal|fraud) charges?\b", "criminal charges", 1.0),
    (r"\bimpeach(?:ed|ment)?\b", "impeachment", 0.95),
    (r"\bresign(?:s|ed|ation)\b", "resignation", 0.9),
    (r"\bscandal\b", "scandal", 0.85),
    (r"\bethics (?:violation|complaint|investigation)\b", "ethics violation", 0.8),
    (r"\bsexual (?:harassment|assault|misconduct)\b", "sexual misconduct", 0.95),
    (r"\b(?:FBI|DOJ|federal) investigat(?:ion|ing)\b", "federal investigation", 0.9),
    (r"\bcover[- ]?up\b", "cover-up", 0.85),
    (r"\bperjur(?:y|ed)\b", "perjury", 0.9),
    (r"\bembezzle(?:d|ment)?\b", "embezzlement", 0.9),
    (r"\bbrib(?:e[ds]?|ery)\b", "bribery", 0.9),
    (r"\bplaguris(?:m|ed)\b", "plagiarism", 0.6),
    (r"\bconflict of interest\b", "conflict of interest", 0.65),
    (r"\btax (?:fraud|evasion)\b", "tax fraud", 0.85),
    (r"\bcampaign finance (?:violation|scandal)\b", "campaign finance violation", 0.75),
    (r"\bextramarital|affair\b", "affair", 0.6),
]


# ── Core vibes output ─────────────────────────────────────────────────


@dataclass
class CandidateVibes:
    """Complete vibes assessment for one candidate over a time period."""

    candidate: str
    race: str
    period_start: date
    period_end: date

    # Metric 1: simple pos/neg breakdown
    positive_pct: float
    negative_pct: float
    neutral_pct: float
    total_mentions: int

    # Metric 2: five-bucket
    bucket: VibeBucket
    bucket_numeric: int  # -2 to +2

    # Metric 3: scandal flags
    scandal_flags: list[ScandalFlag] = field(default_factory=list)
    scandal_severity: float = 0.0  # 0–1 composite score

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "race": self.race,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "positive_pct": self.positive_pct,
            "negative_pct": self.negative_pct,
            "neutral_pct": self.neutral_pct,
            "total_mentions": self.total_mentions,
            "bucket": self.bucket.value,
            "bucket_numeric": self.bucket_numeric,
            "scandal_severity": self.scandal_severity,
            "num_scandals": len(self.scandal_flags),
        }


# ── Computation ───────────────────────────────────────────────────────


def compute_vibes(
    scored_mentions: list[ScoredMention],
    candidate: str,
    race: str = "",
    period_start: date | None = None,
    period_end: date | None = None,
) -> CandidateVibes:
    """Compute all three vibes metrics for a candidate from scored mentions.

    Args:
        scored_mentions: Mentions already scored by a SentimentScorer.
        candidate: Canonical candidate name.
        race: Race identifier (e.g., "PA-Senate-2022").
        period_start: Start of analysis window.
        period_end: End of analysis window.
    """
    today = date.today()
    period_start = period_start or today
    period_end = period_end or today

    # Filter to this candidate's mentions
    candidate_scored = [
        sm for sm in scored_mentions
        if sm.mention.candidate == candidate
    ]

    total = len(candidate_scored)
    if total == 0:
        return CandidateVibes(
            candidate=candidate,
            race=race,
            period_start=period_start,
            period_end=period_end,
            positive_pct=0.0,
            negative_pct=0.0,
            neutral_pct=0.0,
            total_mentions=0,
            bucket=VibeBucket.NEUTRAL_MIXED,
            bucket_numeric=0,
        )

    # ── Metric 1: pos/neg percentages ─────────────────────────────
    pos_count = sum(1 for sm in candidate_scored if sm.score.label == "positive")
    neg_count = sum(1 for sm in candidate_scored if sm.score.label == "negative")
    neu_count = total - pos_count - neg_count

    pos_pct = round(pos_count / total * 100, 1)
    neg_pct = round(neg_count / total * 100, 1)
    neu_pct = round(neu_count / total * 100, 1)

    # ── Metric 2: five-bucket classification ──────────────────────
    bucket = _classify_bucket(pos_pct, neg_pct)

    # ── Metric 3: scandal detection ───────────────────────────────
    scandal_flags = _detect_scandals(candidate_scored)
    scandal_severity = _composite_scandal_severity(scandal_flags)

    return CandidateVibes(
        candidate=candidate,
        race=race,
        period_start=period_start,
        period_end=period_end,
        positive_pct=pos_pct,
        negative_pct=neg_pct,
        neutral_pct=neu_pct,
        total_mentions=total,
        bucket=bucket,
        bucket_numeric=bucket.numeric,
        scandal_flags=scandal_flags,
        scandal_severity=scandal_severity,
    )


def _classify_bucket(pos_pct: float, neg_pct: float) -> VibeBucket:
    """Classify into one of five buckets based on pos/neg split.

    Thresholds:
        >70% positive → overwhelmingly positive
        >55% positive → more positive
        >55% negative → more negative
        >70% negative → overwhelmingly negative
        else → neutral/mixed
    """
    if pos_pct >= 70:
        return VibeBucket.OVERWHELMINGLY_POSITIVE
    elif pos_pct >= 55:
        return VibeBucket.MORE_POSITIVE
    elif neg_pct >= 70:
        return VibeBucket.OVERWHELMINGLY_NEGATIVE
    elif neg_pct >= 55:
        return VibeBucket.MORE_NEGATIVE
    else:
        return VibeBucket.NEUTRAL_MIXED


def _detect_scandals(scored_mentions: list[ScoredMention]) -> list[ScandalFlag]:
    """Scan mentions for scandal trigger patterns."""
    compiled = [(re.compile(p, re.IGNORECASE), desc, sev) for p, desc, sev in _SCANDAL_TRIGGERS]
    detected: dict[str, ScandalFlag] = {}

    for sm in scored_mentions:
        text = sm.mention.context_window
        for pat, desc, severity in compiled:
            if pat.search(text):
                if desc in detected:
                    detected[desc].mention_count += 1
                else:
                    detected[desc] = ScandalFlag(
                        description=desc,
                        severity=severity,
                        mention_count=1,
                        first_seen=sm.mention.article_id,
                        sample_text=sm.mention.sentence[:200],
                    )

    return sorted(detected.values(), key=lambda f: f.severity, reverse=True)


def _composite_scandal_severity(flags: list[ScandalFlag]) -> float:
    """Compute a 0–1 composite scandal score.

    Combines the max severity with a frequency bonus.
    """
    if not flags:
        return 0.0

    max_severity = max(f.severity for f in flags)
    total_mentions = sum(f.mention_count for f in flags)

    # Frequency bonus: each additional scandal mention adds diminishing weight
    frequency_bonus = min(0.2, total_mentions * 0.02)

    return round(min(1.0, max_severity * 0.8 + frequency_bonus), 3)
