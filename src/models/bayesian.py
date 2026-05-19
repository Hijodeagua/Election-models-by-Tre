from __future__ import annotations

from src.models.approval import ApprovalSnapshot
from src.models.generic_ballot import GenericBallotSnapshot


def _alpha_beta(n: int, k: float) -> tuple[float, float]:
    alpha = n / (n + k)
    return alpha, 1.0 - alpha


def bayesian_blend_approval(
    poll_snap: ApprovalSnapshot | None,
    prior_snap: ApprovalSnapshot | None,
    k: float = 6.0,
) -> tuple[ApprovalSnapshot | None, float, float]:
    """Blend poll average with Silver Bulletin prior.

    Returns (blended_snapshot, alpha, beta) where alpha+beta=1.
    - If poll_snap is None: return prior as-is, alpha=0, beta=1
    - If prior_snap is None: return poll as-is, alpha=1, beta=0

    The blended snapshot uses poll_snap.as_of as the reference date.
    num_polls = poll_snap.num_polls.

    CIs: if both snapshots have CIs, blend them:
        ci = (alpha*ci_poll_lo + beta*ci_prior_lo, alpha*ci_poll_hi + beta*ci_prior_hi)
    If only one has CI, use it as-is scaled by its alpha/beta.
    """
    if poll_snap is None and prior_snap is None:
        return None, 0.0, 1.0

    if poll_snap is None:
        return prior_snap, 0.0, 1.0

    if prior_snap is None:
        return poll_snap, 1.0, 0.0

    alpha, beta = _alpha_beta(poll_snap.num_polls, k)

    approve = alpha * poll_snap.approve + beta * prior_snap.approve
    disapprove = alpha * poll_snap.disapprove + beta * prior_snap.disapprove

    def _blend_ci(
        poll_ci: tuple[float, float] | None,
        prior_ci: tuple[float, float] | None,
    ) -> tuple[float, float] | None:
        if poll_ci is not None and prior_ci is not None:
            return (
                alpha * poll_ci[0] + beta * prior_ci[0],
                alpha * poll_ci[1] + beta * prior_ci[1],
            )
        if poll_ci is not None:
            return (alpha * poll_ci[0], alpha * poll_ci[1])
        if prior_ci is not None:
            return (beta * prior_ci[0], beta * prior_ci[1])
        return None

    blended = ApprovalSnapshot(
        as_of=poll_snap.as_of,
        approve=round(approve, 4),
        disapprove=round(disapprove, 4),
        net_approval=round(approve - disapprove, 4),
        num_polls=poll_snap.num_polls,
        ci_approve=_blend_ci(poll_snap.ci_approve, prior_snap.ci_approve),
        ci_disapprove=_blend_ci(poll_snap.ci_disapprove, prior_snap.ci_disapprove),
    )
    return blended, alpha, beta


def bayesian_blend_generic_ballot(
    poll_snap: GenericBallotSnapshot | None,
    prior_snap: GenericBallotSnapshot | None,
    k: float = 6.0,
) -> tuple[GenericBallotSnapshot | None, float, float]:
    """Same as bayesian_blend_approval but for generic ballot."""
    if poll_snap is None and prior_snap is None:
        return None, 0.0, 1.0

    if poll_snap is None:
        if prior_snap is None:
            return None, 0.0, 1.0
        snap = GenericBallotSnapshot(
            as_of=prior_snap.as_of,
            dem_pct=prior_snap.dem_pct,
            rep_pct=prior_snap.rep_pct,
            margin=prior_snap.margin,
            num_polls=prior_snap.num_polls,
            estimated_dem_seats=None,
            estimated_rep_seats=None,
            ci_dem=prior_snap.ci_dem,
            ci_rep=prior_snap.ci_rep,
        )
        return snap, 0.0, 1.0

    if prior_snap is None:
        return poll_snap, 1.0, 0.0

    alpha, beta = _alpha_beta(poll_snap.num_polls, k)

    dem_pct = alpha * poll_snap.dem_pct + beta * prior_snap.dem_pct
    rep_pct = alpha * poll_snap.rep_pct + beta * prior_snap.rep_pct

    def _blend_ci(
        poll_ci: tuple[float, float] | None,
        prior_ci: tuple[float, float] | None,
    ) -> tuple[float, float] | None:
        if poll_ci is not None and prior_ci is not None:
            return (
                alpha * poll_ci[0] + beta * prior_ci[0],
                alpha * poll_ci[1] + beta * prior_ci[1],
            )
        if poll_ci is not None:
            return (alpha * poll_ci[0], alpha * poll_ci[1])
        if prior_ci is not None:
            return (beta * prior_ci[0], beta * prior_ci[1])
        return None

    blended = GenericBallotSnapshot(
        as_of=poll_snap.as_of,
        dem_pct=round(dem_pct, 4),
        rep_pct=round(rep_pct, 4),
        margin=round(dem_pct - rep_pct, 4),
        num_polls=poll_snap.num_polls,
        estimated_dem_seats=poll_snap.estimated_dem_seats,
        estimated_rep_seats=poll_snap.estimated_rep_seats,
        ci_dem=_blend_ci(poll_snap.ci_dem, prior_snap.ci_dem),
        ci_rep=_blend_ci(poll_snap.ci_rep, prior_snap.ci_rep),
    )
    return blended, alpha, beta
