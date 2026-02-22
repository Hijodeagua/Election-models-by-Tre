"""Presidential approval model.

Tracks presidential job approval over time using weighted polling averages.
Supports overall approval and issue-level breakdowns.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from src.data.base import Poll, PollType
from src.models.polling_average import AverageResult, PollingAverageEngine


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
    """Presidential approval tracker using weighted polling averages."""

    def __init__(self, engine: PollingAverageEngine | None = None) -> None:
        self.engine = engine or PollingAverageEngine()

    def current_approval(self, polls: list[Poll]) -> ApprovalSnapshot:
        """Compute the current approval average from recent polls."""
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

    @staticmethod
    def _result_to_snapshot(result: AverageResult) -> ApprovalSnapshot:
        approve = result.averages.get("Approve", 0.0)
        disapprove = result.averages.get("Disapprove", 0.0)
        ci = result.confidence_interval
        return ApprovalSnapshot(
            as_of=result.as_of,
            approve=approve,
            disapprove=disapprove,
            net_approval=round(approve - disapprove, 1),
            num_polls=result.num_polls,
            ci_approve=ci.get("Approve") if ci else None,
            ci_disapprove=ci.get("Disapprove") if ci else None,
        )
