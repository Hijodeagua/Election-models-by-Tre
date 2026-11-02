"""Poll identity across sources.

The same poll reaches us through different feeds with different pollster
spellings ("Siena/NYT", "NY Times/Siena", "New York Times/Siena College"), so
de-duplication keys on what cannot differ: the race, the field end date (±1
day, since release lists record the publication day) and the rounded
toplines in rank order.
"""

from __future__ import annotations

from datetime import timedelta

from src.data.base import Poll


def poll_fingerprint(poll: Poll) -> tuple:
    tops = tuple(sorted((round(a.pct) for a in poll.answers), reverse=True))
    return ((poll.subject or "").lower(), poll.end_date, tops)


def merge_new_polls(base: list[Poll], extra: list[Poll]) -> list[Poll]:
    """Polls from ``extra`` whose fingerprint is not already in ``base``
    (tolerating a one-day difference in end date). Order preserved."""
    seen: set[tuple] = set()
    for p in base:
        subj, end, tops = poll_fingerprint(p)
        for delta in (-1, 0, 1):
            seen.add((subj, end + timedelta(days=delta), tops))
    out: list[Poll] = []
    for p in extra:
        fp = poll_fingerprint(p)
        if fp in seen:
            continue
        seen.add(fp)
        out.append(p)
    return out
