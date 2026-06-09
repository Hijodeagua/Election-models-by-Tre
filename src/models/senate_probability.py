"""Per-race Senate win probabilities.

Layers, in order of preference:
    1. Polling margin → win probability via a normal-CDF translation
       (sigma = historical polling error for Senate races).
    2. Structural rating prior from config/senate_2026.json when a race has
       no usable polling (RatingScale implied probabilities).
    3. A prediction-market blend: the final probability is a weighted
       average of the model probability and the Polymarket/Kalshi consensus.
       This is how market data feeds the model itself (not just the chart) —
       the blend weight is the trainable parameter.

All probabilities are Democratic win probabilities on 0–1.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from src.data.forecasters import RatingScale
from src.data.market_odds import KIND_RACE, MarketOdds

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SENATE_CONFIG_PATH = PROJECT_ROOT / "config" / "senate_2026.json"

# Historical RMSE of Senate polling averages vs. results is roughly 5 points
# on the margin; we use it as the sigma of the normal error model.
DEFAULT_POLL_SIGMA = 5.0

# Weight given to the market consensus when blending with the model
# probability. 0 = pure model, 1 = pure markets.
DEFAULT_MARKET_BLEND_WEIGHT = 0.25

_DEM_LABELS = ("democrat", "democratic", "dem")
_REP_LABELS = ("republican", "gop", "rep")


def load_senate_config(path: Path | None = None) -> dict:
    """Load the 2026 Senate landscape config."""
    cfg_path = path or SENATE_CONFIG_PATH
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def margin_to_win_prob(dem_margin: float, sigma: float = DEFAULT_POLL_SIGMA) -> float:
    """P(Dem wins) given a Dem-minus-Rep polling margin, normal error model."""
    z = dem_margin / (sigma * math.sqrt(2))
    return round(0.5 * (1.0 + math.erf(z)), 4)


def oriented_dem_margin(
    candidates: dict[str, float],
    race_cfg: dict | None = None,
) -> float | None:
    """Convert a candidate→pct average into a Dem-minus-Rep margin.

    Candidate party is inferred from (a) generic party labels in the answer
    text, then (b) the dem_candidate/rep_candidate last names in the race
    config. Returns None when neither side can be identified.
    """
    if not candidates:
        return None
    race_cfg = race_cfg or {}
    dem_name = str(race_cfg.get("dem_candidate", "")).lower()
    rep_name = str(race_cfg.get("rep_candidate", "")).lower()

    dem_pct = rep_pct = None
    for name, pct in candidates.items():
        low = name.lower()
        if any(lbl in low for lbl in _DEM_LABELS) or (dem_name and dem_name in low):
            dem_pct = pct
        elif any(lbl in low for lbl in _REP_LABELS) or (rep_name and rep_name in low):
            rep_pct = pct
    if dem_pct is None or rep_pct is None:
        return None
    return round(dem_pct - rep_pct, 1)


def market_consensus(odds: list[MarketOdds], state: str) -> float | None:
    """Volume-weighted Dem win probability across markets for one race."""
    quotes: list[tuple[float, float]] = []  # (prob, weight)
    for o in odds:
        if o.kind != KIND_RACE or o.state.lower() != state.lower():
            continue
        prob = o.dem_win_prob
        if prob is None and o.rep_win_prob is not None:
            prob = 1.0 - o.rep_win_prob
        if prob is None:
            continue
        quotes.append((prob, max(o.volume or 0.0, 1.0)))
    if not quotes:
        return None
    total_w = sum(w for _, w in quotes)
    return round(sum(p * w for p, w in quotes) / total_w, 4)


@dataclass
class RaceProbability:
    """Win-probability breakdown for one Senate race."""

    state: str
    rating: str | None
    dem_margin: float | None  # polled Dem-minus-Rep margin (None = unpolled)
    poll_prob: float | None  # from polling margin alone
    prior_prob: float  # from the structural rating
    model_prob: float  # polls if available, else prior
    market_prob: float | None  # Polymarket/Kalshi consensus
    blended_prob: float  # model blended with markets — the headline number
    market_weight: float
    num_polls: int = 0
    sources: list[str] = field(default_factory=list)


def race_probability(
    state: str,
    candidates: dict[str, float],
    num_polls: int,
    race_cfg: dict,
    market_odds: list[MarketOdds],
    sigma: float = DEFAULT_POLL_SIGMA,
    market_weight: float = DEFAULT_MARKET_BLEND_WEIGHT,
    margin_adjustment: float = 0.0,
) -> RaceProbability:
    """Compute the full probability stack for one race.

    margin_adjustment shifts the polled Dem margin before conversion —
    used by the vibes layer (src/models/vibes_adjustment.py).
    """
    rating_raw = race_cfg.get("rating")
    try:
        prior_prob = RatingScale(rating_raw).dem_win_probability if rating_raw else 0.5
    except ValueError:
        prior_prob = 0.5

    dem_margin = oriented_dem_margin(candidates, race_cfg)
    poll_prob = (
        margin_to_win_prob(dem_margin + margin_adjustment, sigma)
        if dem_margin is not None
        else None
    )
    model_prob = poll_prob if poll_prob is not None else prior_prob

    sources = ["polls"] if poll_prob is not None else ["rating_prior"]
    market_prob = market_consensus(market_odds, state)
    if market_prob is not None:
        blended = (1.0 - market_weight) * model_prob + market_weight * market_prob
        sources.append("markets")
    else:
        blended = model_prob

    return RaceProbability(
        state=state,
        rating=rating_raw,
        dem_margin=dem_margin,
        poll_prob=poll_prob,
        prior_prob=prior_prob,
        model_prob=round(model_prob, 4),
        market_prob=market_prob,
        blended_prob=round(min(max(blended, 0.005), 0.995), 4),
        market_weight=market_weight,
        num_polls=num_polls,
        sources=sources,
    )
