"""Weighted polling average engine.

Methodology:
    1. Recency weighting      — exponential decay (configurable half-life)
    2. Pollster quality        — from pollster_ratings.json (0–3 scale)
    3. Sample size adjustment  — sqrt scaling
    4. Population screen       — LV > RV > Adults
    5. Partisan penalty        — downweight partisan-sponsored polls
    6. House-effect correction — systematic pollster lean (future)
    7. Trend smoothing         — LOESS or Bayesian state-space (future)
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from config.settings import Settings, settings
from src.data.base import Poll, Population


@dataclass
class WeightedPollRecord:
    """A poll with its computed weight and adjusted values."""

    poll: Poll
    weight: float
    choice_values: dict[str, float]  # choice -> percentage


@dataclass
class AverageResult:
    """Output of the weighted polling average computation."""

    subject: str
    as_of: date
    num_polls: int
    averages: dict[str, float]  # choice -> weighted average pct
    margin: float | None  # top choice minus second choice
    confidence_interval: dict[str, tuple[float, float]] | None  # choice -> (low, high)
    weighted_polls: list[WeightedPollRecord]


class PollingAverageEngine:
    """Compute weighted polling averages from a list of Poll objects."""

    def __init__(
        self,
        config: Settings | None = None,
        pollster_ratings: dict[str, float] | None = None,
    ) -> None:
        self.config = config or settings
        self.pollster_ratings = pollster_ratings or self._load_pollster_ratings()

    @staticmethod
    def _load_pollster_ratings() -> dict[str, float]:
        """Load pollster ratings from config/pollster_ratings.json."""
        path = Path(__file__).resolve().parent.parent.parent / "config" / "pollster_ratings.json"
        if path.exists():
            data = json.loads(path.read_text())
            return data.get("ratings", {})
        return {}

    def compute_average(
        self,
        polls: list[Poll],
        as_of: date | None = None,
        choices: list[str] | None = None,
    ) -> AverageResult:
        """Compute a weighted average across the given polls.

        Args:
            polls: List of normalized Poll objects.
            as_of: Reference date for recency weighting (default: today).
            choices: Which answer choices to average (e.g., ['Approve', 'Disapprove']).
                     If None, auto-detects from the most common choices.

        Returns:
            AverageResult with weighted averages and metadata.
        """
        as_of = as_of or date.today()

        if not polls:
            return AverageResult(
                subject="",
                as_of=as_of,
                num_polls=0,
                averages={},
                margin=None,
                confidence_interval=None,
                weighted_polls=[],
            )

        # Auto-detect choices from polls if not specified
        if choices is None:
            choices = self._detect_choices(polls)

        # Compute weights and build records
        weighted: list[WeightedPollRecord] = []
        for poll in polls:
            w = self._compute_weight(poll, as_of)
            if w <= 0:
                continue

            choice_vals = {}
            for answer in poll.answers:
                if answer.choice in choices:
                    choice_vals[answer.choice] = answer.pct

            if choice_vals:
                weighted.append(WeightedPollRecord(poll=poll, weight=w, choice_values=choice_vals))

        if not weighted:
            return AverageResult(
                subject=polls[0].subject if polls else "",
                as_of=as_of,
                num_polls=0,
                averages={},
                margin=None,
                confidence_interval=None,
                weighted_polls=[],
            )

        # Weighted average per choice
        averages: dict[str, float] = {}
        for choice in choices:
            total_weight = 0.0
            weighted_sum = 0.0
            for rec in weighted:
                if choice in rec.choice_values:
                    weighted_sum += rec.weight * rec.choice_values[choice]
                    total_weight += rec.weight
            if total_weight > 0:
                averages[choice] = round(weighted_sum / total_weight, 1)

        # Margin: first choice minus second choice
        margin = None
        sorted_choices = sorted(averages.items(), key=lambda x: x[1], reverse=True)
        if len(sorted_choices) >= 2:
            margin = round(sorted_choices[0][1] - sorted_choices[1][1], 1)

        # Bootstrap confidence intervals
        ci = self._bootstrap_ci(weighted, choices) if len(weighted) >= 5 else None

        return AverageResult(
            subject=polls[0].subject,
            as_of=as_of,
            num_polls=len(weighted),
            averages=averages,
            margin=margin,
            confidence_interval=ci,
            weighted_polls=weighted,
        )

    # ── Weight computation ────────────────────────────────────────────

    def _compute_weight(self, poll: Poll, as_of: date) -> float:
        """Combine all weighting factors into a single poll weight."""
        w = 1.0

        # 1. Recency — exponential decay
        age_days = (as_of - poll.midpoint_date).days
        if age_days < 0:
            age_days = 0  # future-dated poll (rare)
        half_life = self.config.recency_half_life_days
        w *= math.exp(-math.log(2) * age_days / half_life)

        # 2. Pollster quality rating (0–3 scale, default 1.5 for unknown)
        rating = self.pollster_ratings.get(poll.pollster, 1.5)
        w *= rating / 3.0  # normalize to 0–1 range

        # 3. Sample size (sqrt scaling, capped)
        if poll.sample_size and poll.sample_size >= self.config.min_sample_size:
            w *= math.sqrt(poll.sample_size / 1000)
        elif poll.sample_size and poll.sample_size < self.config.min_sample_size:
            w *= 0.5  # penalty for tiny samples

        # 4. Population screen
        if poll.population == Population.LIKELY_VOTERS:
            w *= self.config.lv_weight_multiplier
        elif poll.population == Population.REGISTERED_VOTERS:
            w *= self.config.rv_weight_multiplier
        elif poll.population == Population.ADULTS:
            w *= self.config.adults_weight_multiplier

        # 5. Partisan penalty
        if poll.partisan:
            w *= self.config.partisan_bias_penalty

        return w

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _detect_choices(polls: list[Poll]) -> list[str]:
        """Find the most common answer choices across polls."""
        from collections import Counter

        counter: Counter[str] = Counter()
        for poll in polls:
            for answer in poll.answers:
                counter[answer.choice] += 1
        # Return choices that appear in at least 30% of polls
        threshold = max(1, len(polls) * 0.3)
        return [choice for choice, count in counter.most_common() if count >= threshold]

    @staticmethod
    def _bootstrap_ci(
        weighted: list[WeightedPollRecord],
        choices: list[str],
        n_boot: int = 1000,
        ci_level: float = 0.95,
    ) -> dict[str, tuple[float, float]]:
        """Compute bootstrap confidence intervals for each choice."""
        rng = np.random.default_rng(seed=42)
        n = len(weighted)
        alpha = (1 - ci_level) / 2

        results: dict[str, tuple[float, float]] = {}
        for choice in choices:
            boot_means: list[float] = []
            vals = np.array([r.choice_values.get(choice, np.nan) for r in weighted])
            weights = np.array([r.weight for r in weighted])
            mask = ~np.isnan(vals)
            if mask.sum() < 3:
                continue
            vals = vals[mask]
            weights = weights[mask]

            for _ in range(n_boot):
                idx = rng.choice(len(vals), size=len(vals), replace=True)
                boot_w = weights[idx]
                boot_v = vals[idx]
                if boot_w.sum() > 0:
                    boot_means.append(float(np.average(boot_v, weights=boot_w)))

            if boot_means:
                lo = round(float(np.percentile(boot_means, alpha * 100)), 1)
                hi = round(float(np.percentile(boot_means, (1 - alpha) * 100)), 1)
                results[choice] = (lo, hi)

        return results
