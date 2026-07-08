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

# The approval feed carries more than presidential approval (Congress, Supreme
# Court, VP favorability all arrive as PollType.APPROVAL). Only polls whose
# subject matches this keyword — or with no subject, for legacy feeds that
# predate the Subject column — belong in the presidential average.
PRESIDENTIAL_SUBJECT_KEYWORD = "trump"


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

    def __init__(
        self,
        engine: PollingAverageEngine | None = None,
        subject_keyword: str = PRESIDENTIAL_SUBJECT_KEYWORD,
    ) -> None:
        self.engine = engine or PollingAverageEngine()
        self.subject_keyword = subject_keyword

    def _presidential_polls(self, polls: list[Poll]) -> list[Poll]:
        """Approval polls about the president (blank subjects pass for legacy feeds)."""
        return [
            p for p in polls
            if p.poll_type == PollType.APPROVAL
            and (not p.subject or self.subject_keyword in p.subject.lower())
        ]

    def current_approval(self, polls: list[Poll]) -> ApprovalSnapshot | None:
        """Return current approval average, or None if too few polls."""
        approval_polls = self._presidential_polls(polls)
        if len(approval_polls) < MIN_POLLS_FOR_ESTIMATE:
            return None
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
        approval_polls = self._presidential_polls(polls)
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
    ) -> tuple[ApprovalSnapshot, StateSpaceResult] | None:
        """State-space estimate. Replaces current_approval() once validated.

        Returns (ApprovalSnapshot, StateSpaceResult) or None on failure.
        The ApprovalSnapshot CI fields contain 95% posterior credible intervals.
        """
        from src.models import state_space

        as_of = as_of or date.today()
        approval_polls = self._presidential_polls(polls)
        if len(approval_polls) < MIN_POLLS_FOR_ESTIMATE:
            return None

        result = state_space.fit(
            approval_polls, choice="Approve", as_of=as_of,
            draws=draws, tune=tune,
        )
        if result is None:
            return None

        # Disapprove is fitted as its own latent series, NOT derived as
        # 100 − Approve: real polls leave 5–15pp undecided/no-opinion, so the
        # complement overstates disapproval and fabricates its CI. The second
        # fit doubles runtime, which is acceptable for this opt-in path.
        dis_result = state_space.fit(
            approval_polls, choice="Disapprove", as_of=as_of,
            draws=draws, tune=tune,
        )
        if dis_result is None:
            return None

        mean, lo, hi = result.estimate_at(as_of)
        dis_mean, dis_lo, dis_hi = dis_result.estimate_at(as_of)

        snap = ApprovalSnapshot(
            as_of=as_of,
            approve=round(mean, 1),
            disapprove=round(dis_mean, 1),
            net_approval=round(mean - dis_mean, 1),
            num_polls=result.n_polls,
            ci_approve=(round(lo, 1), round(hi, 1)),
            ci_disapprove=(round(dis_lo, 1), round(dis_hi, 1)),
        )
        return snap, result

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
