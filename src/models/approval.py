"""Presidential approval model.

Tracks presidential job approval over time using weighted polling averages.
Supports overall approval and issue-level breakdowns.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from src.data.base import Poll, PollType
from src.models import ModelMaturity
from src.models.polling_average import AverageResult, PollingAverageEngine

if TYPE_CHECKING:
    from src.models.state_space import StateSpaceResult

MIN_POLLS_FOR_ESTIMATE = 3  # publish "no estimate" below this threshold


@dataclass
class ApprovalSnapshot:
    """A point-in-time approval reading."""

    as_of: date
    approve: float
    disapprove: float
    net_approval: float
    num_polls: int
    ci_approve: tuple[float, float] | None = None
    ci_disapprove: tuple[float, float] | None = None


class PresidentialApprovalModel:
    """Presidential approval tracker using weighted polling averages.

    Maturity: TRACKER — reports current polling average only.
    Not yet a forward-looking forecast.
    """

    maturity = ModelMaturity.TRACKER

    def __init__(self, engine: PollingAverageEngine | None = None) -> None:
        self.engine = engine or PollingAverageEngine()

    def current_approval(self, polls: list[Poll]) -> ApprovalSnapshot:
        """Compute the current approval average from recent polls.

        Always returns an ApprovalSnapshot; num_polls will be 0 when no valid
        polls are available.  Use MIN_POLLS_FOR_ESTIMATE to decide whether the
        result is publishable-quality.
        """
        approval_polls = [p for p in polls if p.poll_type == PollType.APPROVAL]
        result = self.engine.compute_average(
            approval_polls,
            choices=["Approve", "Disapprove"],
        )
        return self._result_to_snapshot(result)

    def approval_trend(
        self,
        polls: list[Poll],
        start: date | None = None,
        end: date | None = None,
        step_days: int = 1,
    ) -> list[ApprovalSnapshot]:
        """Compute daily approval snapshots over a date range.

        Args:
            polls: All approval polls in the range.
            start: First date (default: earliest poll).
            end: Last date (default: today).
            step_days: Days between snapshots.
        """
        approval_polls = [p for p in polls if p.poll_type == PollType.APPROVAL]
        if not approval_polls:
            return []

        if start is None:
            start = min(p.start_date for p in approval_polls)
        if end is None:
            end = date.today()

        snapshots: list[ApprovalSnapshot] = []
        current = start
        while current <= end:
            result = self.engine.compute_average(
                approval_polls,
                as_of=current,
                choices=["Approve", "Disapprove"],
            )
            if result.num_polls > 0:
                snapshots.append(self._result_to_snapshot(result))
            current += timedelta(days=step_days)

        return snapshots

    def current_estimate_ss(
        self,
        polls: list[Poll],
        as_of: date | None = None,
        draws: int = 1000,
        tune: int = 1000,
    ) -> tuple[ApprovalSnapshot, "StateSpaceResult"] | None:
        """State-space estimate. Replaces current_approval() once validated.

        Returns (ApprovalSnapshot, StateSpaceResult) or None on failure.
        The ApprovalSnapshot CI fields contain 95% posterior credible intervals.
        """
        from src.models import state_space

        as_of = as_of or date.today()
        approval_polls = [p for p in polls if p.poll_type == PollType.APPROVAL]
        if len(approval_polls) < MIN_POLLS_FOR_ESTIMATE:
            return None

        result = state_space.fit(
            approval_polls, choice="Approve", as_of=as_of,
            draws=draws, tune=tune,
        )
        if result is None:
            return None

        mean, lo, hi = result.estimate_at(as_of)

        # Disapprove derived as complement (Approve + Disapprove ≈ 100 in most polls).
        # Fitting separately would double runtime; accepted approximation for Phase 3.
        dis_mean = 100.0 - mean
        snap = ApprovalSnapshot(
            as_of=as_of,
            approve=round(mean, 1),
            disapprove=round(dis_mean, 1),
            net_approval=round(mean - dis_mean, 1),
            num_polls=result.n_polls,
            ci_approve=(round(lo, 1), round(hi, 1)),
            ci_disapprove=(round(100.0 - hi, 1), round(100.0 - lo, 1)),
        )
        return snap, result

    @staticmethod
    def _result_to_snapshot(result: AverageResult) -> ApprovalSnapshot:
        approve = result.averages.get("Approve", 0.0)
        disapprove = result.averages.get("Disapprove", 0.0)
        ci = result.confidence_interval or {}
        return ApprovalSnapshot(
            as_of=result.as_of,
            approve=approve,
            disapprove=disapprove,
            net_approval=round(approve - disapprove, 1),
            num_polls=result.num_polls,
            ci_approve=ci.get("Approve"),
            ci_disapprove=ci.get("Disapprove"),
        )
