"""Trend detection and smoothing for polling time series."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np


@dataclass
class TrendPoint:
    """A single point on a smoothed trend line."""

    date: date
    value: float
    ci_low: float | None = None
    ci_high: float | None = None


def moving_average(
    dates: list[date],
    values: list[float],
    window_days: int = 14,
) -> list[TrendPoint]:
    """Simple moving average over a time series.

    Args:
        dates: Dates corresponding to each value.
        values: Observed values.
        window_days: Window width in days.

    Returns:
        Smoothed trend points for each input date.
    """
    if not dates:
        return []

    arr_vals = np.array(values)
    results: list[TrendPoint] = []

    for d in dates:
        mask = np.array([
            abs((d - other).days) <= window_days // 2
            for other in dates
        ])
        window_vals = arr_vals[mask]
        if len(window_vals) > 0:
            results.append(TrendPoint(
                date=d,
                value=round(float(np.mean(window_vals)), 1),
            ))

    return results
