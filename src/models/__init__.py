"""Election models — polling averages, approval, generic ballot, race forecasts."""

from enum import Enum


class ModelMaturity(str, Enum):
    """Publication tier for a model output.

    Used to label dashboard and Substack outputs so readers understand
    what each number claims to be.

    TRACKER  — descriptive average of current polls, no forward projection.
    NOWCAST  — current-environment estimate blending polls + fundamentals.
    FORECAST — probabilistic outcome projection with simulation + calibration.
    STUB     — placeholder; not yet ready for any public output.
    """

    TRACKER = "tracker"
    NOWCAST = "nowcast"
    FORECAST = "forecast"
    STUB = "stub"
