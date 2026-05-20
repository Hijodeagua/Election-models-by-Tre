"""Pollster quality ratings for the polling average engine.

Quality is expressed on a 0–3 scale. Phase 2 methodology: direct Silver Bulletin
PPM (Pollster-introduced error Magnitude) lookup, converted via
    quality = clip(1.5 - PPM × 0.3, 0.0, 3.0)
where PPM is centered (positive = worse than pool average, negative = better).

This is an intentional holding pattern. The compression (0.3 multiplier) keeps
the rated pool in roughly [1.0, 2.0] — quality differentiation is modest by design
until Phase 3's τⱼ² estimates validate what the data actually support. The RCP and
VoteHub grade components were near-collinear with SB error and have been removed.
"""

from __future__ import annotations

# Raw Silver Bulletin absolute-error estimates (pp).
# Source: Silver Bulletin pollster ratings page (2024 cycle data).
_SB_RAW_ERRORS: dict[str, float] = {
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

# Center errors around pool mean to produce PPM (positive = worse than average)
_pool_mean = sum(_SB_RAW_ERRORS.values()) / len(_SB_RAW_ERRORS)
_SB_PPM: dict[str, float] = {k: round(v - _pool_mean, 3) for k, v in _SB_RAW_ERRORS.items()}

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


def _canonical(name: str) -> str:
    return _ALIASES.get(name, name)


def _ppm_to_quality(ppm: float) -> float:
    """Convert centered PPM to 0–3 quality. Negative PPM (better) → higher quality."""
    return max(0.0, min(3.0, 1.5 - ppm * 0.3))


def _compute_unknown_default() -> float:
    """25th-percentile quality of the rated pool (survivorship-adjusted prior)."""
    qualities = sorted(_ppm_to_quality(ppm) for ppm in _SB_PPM.values())
    idx = len(qualities) // 4
    return round(qualities[idx], 3)


_UNKNOWN_DEFAULT: float = _compute_unknown_default()


def hybrid_quality(pollster: str, vh_grade: str = "") -> float:
    """Return pollster quality on 0–3 scale via direct SB PPM lookup.

    Unknown pollsters return _UNKNOWN_DEFAULT (25th percentile of rated pool).
    vh_grade is accepted for API compatibility but is no longer used.
    """
    canonical = _canonical(pollster)
    ppm = _SB_PPM.get(canonical)
    if ppm is None:
        return _UNKNOWN_DEFAULT
    return round(_ppm_to_quality(ppm), 3)


def build_ratings_dict(pollsters: list[str] | None = None) -> dict[str, float]:
    """Return {pollster_name: quality_0_to_3} for all known pollsters.
    If pollsters list provided, include unknowns with default score."""
    result: dict[str, float] = {name: hybrid_quality(name) for name in _SB_PPM}

    if pollsters is not None:
        for p in pollsters:
            canonical = _canonical(p)
            if canonical not in result:
                result[canonical] = hybrid_quality(canonical)

    return result
