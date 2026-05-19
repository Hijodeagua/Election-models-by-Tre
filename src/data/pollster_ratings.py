from __future__ import annotations

_RCP_BY_CYCLE: dict[int, dict[str, float]] = {
    2022: {
        "UMass Lowell": 1.2, "CNN": 1.2, "New York Times/Siena College": 1.5,
        "Suffolk University": 1.7, "Fox News": 1.9, "SurveyUSA": 2.5,
        "Susquehanna": 2.6, "Marist College": 2.8, "Univision": 3.0,
        "Emerson College": 3.5, "Data for Progress": 3.6, "CBS News/YouGov": 3.7,
        "Siena College": 4.0, "Remington Research": 4.2, "Rasmussen Reports": 5.1,
        "Trafalgar Group": 5.4, "InsiderAdvantage": 5.8,
    },
    2020: {
        "InsiderAdvantage": 2.4, "Susquehanna": 2.5, "Trafalgar Group": 2.7,
        "Rasmussen Reports": 3.2, "UMass Lowell": 3.8, "HarrisX": 4.0,
        "SurveyUSA": 4.2, "CBS News/YouGov": 4.4, "CNBC/Change Research": 4.4,
        "Emerson College": 4.8, "Reuters/Ipsos": 5.1, "New York Times/Siena College": 5.1,
        "Fox News": 5.4, "ABC News/Washington Post": 5.4, "NBC News/Marist": 5.7,
        "PPP": 7.1, "Mason-Dixon": 7.1, "CNN": 7.3,
        "Quinnipiac University": 7.3, "Monmouth University": 7.6,
    },
    2018: {
        "CBS News/YouGov": 1.8, "Suffolk University": 2.1, "Emerson College": 3.3,
        "Quinnipiac University": 3.5, "Fox News": 3.6, "Monmouth University": 4.0,
        "CNN": 4.5, "HarrisX": 4.6, "Trafalgar Group": 4.9,
        "New York Times/Siena College": 5.0, "SurveyUSA": 5.3,
        "NBC News/Marist": 5.4, "Rasmussen Reports": 6.7,
    },
    2016: {
        "Trafalgar Group": 2.2, "InsiderAdvantage": 3.3, "PPP": 3.6,
        "NBC News/Marist": 3.9, "New York Times/Siena College": 4.1,
        "CNN": 4.3, "Emerson College": 4.3, "Quinnipiac University": 4.3,
        "YouGov": 4.7, "SurveyUSA": 5.2, "CBS News/YouGov": 5.2,
        "Monmouth University": 5.2, "Suffolk University": 6.5,
        "Remington Research": 6.7, "Mason-Dixon": 7.3,
    },
}

_CYCLE_WEIGHTS = {2022: 0.40, 2020: 0.25, 2018: 0.20, 2016: 0.15}

_SB_ERRORS: dict[str, float] = {
    "UMass Lowell": 2.5, "Marist College": 2.8, "Marquette Law School": 2.9,
    "New York Times/Siena College": 3.0, "Pew Research Center": 2.8,
    "ABC News/Washington Post": 3.3, "YouGov": 3.3, "CNN": 3.5,
    "Fox News": 3.5, "Quinnipiac University": 3.5, "CBS News/YouGov": 3.5,
    "Monmouth University": 3.5, "NBC News/Marist": 3.5, "Reuters/Ipsos": 3.0,
    "Siena College": 3.0, "Suffolk University": 3.0, "Gallup": 3.0,
    "SurveyUSA": 4.0, "Emerson College": 3.8, "HarrisX": 4.0,
    "TIPP Insights": 4.0, "Morning Consult": 4.5,
    "Rasmussen Reports": 4.8, "InsiderAdvantage": 5.0,
    "Trafalgar Group": 5.2, "PPP": 4.5, "Data for Progress": 4.5,
    "Remington Research": 5.5,
}

_VH_GRADE_QUALITY: dict[str, float] = {
    "A+": 1.0, "A": 0.95, "A-": 0.90,
    "B+": 0.82, "B": 0.75, "B-": 0.68,
    "C+": 0.62, "C": 0.55, "C-": 0.48,
    "D+": 0.38, "D": 0.30, "D-": 0.22,
    "-": 0.15, "": 0.15,
}

_ALIASES: dict[str, str] = {
    "The New York Times/Siena College": "New York Times/Siena College",
    "NYT/Siena": "New York Times/Siena College",
    "Siena College/NYT": "New York Times/Siena College",
    "FOX News": "Fox News",
    "Fox News/Beacon Research": "Fox News",
    "Monmouth": "Monmouth University",
    "NBC News/WSJ/Marist": "NBC News/Marist",
    "NBC News/Hart Research": "NBC News/Marist",
    "Marist": "Marist College",
    "ABC News/Wash Post": "ABC News/Washington Post",
    "Quinnipiac": "Quinnipiac University",
    "PPP (D)": "PPP",
    "Data for Progress (D)": "Data for Progress",
    "Trafalgar Group (R)": "Trafalgar Group",
    "EPIC-MRA": "EPIC-MRA",
    "Ipsos": "Reuters/Ipsos",
    "Reuters": "Reuters/Ipsos",
    "CBS News": "CBS News/YouGov",
}


# Error bounds for linear normalization: maps error range onto [0, 1]
# Floor = best realistic error, Ceiling = unreliable threshold
_ERROR_FLOOR = 1.0
_ERROR_CEILING = 8.0


def _error_to_quality(error: float) -> float:
    """Convert avg-error to 0–1 quality score. Lower error → higher quality."""
    return max(0.0, (_ERROR_CEILING - error) / (_ERROR_CEILING - _ERROR_FLOOR))


def _canonical(name: str) -> str:
    return _ALIASES.get(name, name)


def rcp_weighted_error(pollster: str) -> float | None:
    """Return recency-weighted avg error from RCP data, or None if unknown."""
    canonical = _canonical(pollster)
    weight_sum = 0.0
    error_sum = 0.0
    for cycle, w in _CYCLE_WEIGHTS.items():
        cycle_data = _RCP_BY_CYCLE.get(cycle, {})
        if canonical in cycle_data:
            error_sum += w * cycle_data[canonical]
            weight_sum += w
    if weight_sum == 0.0:
        return None
    return error_sum / weight_sum


def hybrid_quality(pollster: str, vh_grade: str = "") -> float:
    """Return hybrid pollster quality on 0–3 scale.

    Blend: 50% RCP historical error + 30% Silver Bulletin + 20% VoteHub grade.
    Missing sources have their weight redistributed to present sources.
    Unknown pollsters default to 1.5 (midpoint).
    """
    canonical = _canonical(pollster)

    base_weights = {"rcp": 0.50, "sb": 0.30, "vh": 0.20}
    scores: dict[str, float] = {}

    rcp_err = rcp_weighted_error(canonical)
    if rcp_err is not None:
        scores["rcp"] = _error_to_quality(rcp_err)

    if canonical in _SB_ERRORS:
        scores["sb"] = _error_to_quality(_SB_ERRORS[canonical])

    vh_q = _VH_GRADE_QUALITY.get(vh_grade)
    if vh_q is not None and vh_grade not in ("", "-"):
        scores["vh"] = vh_q

    if not scores:
        return 1.5  # midpoint default for fully unknown pollsters

    total_weight = sum(base_weights[src] for src in scores)
    blended = sum(base_weights[src] * q for src, q in scores.items()) / total_weight

    return round(blended * 3.0, 3)


def build_ratings_dict(pollsters: list[str] | None = None) -> dict[str, float]:
    """Return {pollster_name: quality_0_to_3} for all known pollsters.
    If pollsters list provided, include unknowns with default score."""
    known: set[str] = set()
    for cycle_data in _RCP_BY_CYCLE.values():
        known.update(cycle_data.keys())
    known.update(_SB_ERRORS.keys())

    result: dict[str, float] = {name: hybrid_quality(name) for name in known}

    if pollsters is not None:
        for p in pollsters:
            canonical = _canonical(p)
            if canonical not in result:
                result[canonical] = hybrid_quality(canonical)

    return result
