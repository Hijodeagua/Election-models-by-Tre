"""Non-polling fundamentals for election modeling.

Economic indicators, presidential approval, and structural factors
that historically predict election outcomes independently of polling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class FundamentalsSnapshot:
    """Key non-polling predictors for a midterm election."""

    president_party: str  # "D" or "R"
    midterm_penalty: float  # Historical avg loss for president's party
    gdp_growth_q2: float | None  # Q2 GDP growth rate (annualized)
    unemployment_rate: float | None
    consumer_sentiment: float | None
    presidential_approval: float | None


# Historical midterm penalty: the president's party almost always loses seats.
# Average House seat loss in midterms (1946–2022): ~26 seats.
AVERAGE_MIDTERM_PENALTY = -26.0


def estimate_structural_lean(fundamentals: FundamentalsSnapshot) -> float:
    """Estimate structural advantage/disadvantage from fundamentals.

    Returns a rough seat estimate relative to baseline (positive = president's party gains).
    This is a simplified model — a real implementation would use regression.
    """
    lean = AVERAGE_MIDTERM_PENALTY

    # Approval adjustment: each point above/below 50% ≈ 1.5 seats
    if fundamentals.presidential_approval is not None:
        lean += (fundamentals.presidential_approval - 50.0) * 1.5

    # GDP adjustment: strong growth helps the incumbent party
    if fundamentals.gdp_growth_q2 is not None:
        lean += fundamentals.gdp_growth_q2 * 3.0

    return round(lean, 0)


# ── Economic terms used by the Senate and House forecasts ────────────────────


def economic_components(
    snapshot: Any,
    cfg: dict[str, Any],
    president_party: str,
    state: str | None = None,
) -> dict[str, Any]:
    """Dem−Rep margin effects from the economy, signed against the president's
    party (a bad economy helps the out-party).

    ``snapshot`` is a :class:`src.data.economic.EconomicSnapshot`; ``cfg`` is
    the config ``economy`` block:

    * inflation: ``(cpi_yoy − inflation_baseline) × inflation_coef`` — national
    * gas: ``(state gas price − national) × gas_deviation_coef`` — per state
    * unemployment: ``(state rate − national) × unemployment_deviation_coef``

    Each coefficient is the effect on the *president's party's* margin, so a
    negative coefficient means the term hurts the president's party; the
    returned effects are flipped to Dem−Rep when the president is Republican.
    Missing data contributes 0 and is reported in ``available``.
    """
    sign = 1.0 if president_party.upper() == "D" else -1.0
    out: dict[str, Any] = {
        "president_party": president_party.upper(),
        "cpi_yoy": None, "inflation_effect": 0.0,
        "gas_deviation": None, "gas_effect": 0.0,
        "unemployment_deviation": None, "unemployment_effect": 0.0,
        "available": [],
    }
    if snapshot is None or not cfg:
        out["total"] = 0.0
        return out
    cpi = getattr(snapshot, "cpi_yoy", None)
    if cpi is not None:
        baseline = float(cfg.get("inflation_baseline", 2.5))
        pres = (cpi - baseline) * float(cfg.get("inflation_coef", 0.0))
        out.update(cpi_yoy=cpi, inflation_effect=round(sign * pres, 3))
        out["available"].append("inflation")
    gas_dev = snapshot.gas_deviation(state) if state else None
    if gas_dev is not None:
        pres = gas_dev * float(cfg.get("gas_deviation_coef", 0.0))
        out.update(gas_deviation=gas_dev, gas_effect=round(sign * pres, 3))
        out["available"].append("gas")
    un_dev = snapshot.unemployment_deviation(state) if state else None
    if un_dev is not None:
        pres = un_dev * float(cfg.get("unemployment_deviation_coef", 0.0))
        out.update(unemployment_deviation=un_dev, unemployment_effect=round(sign * pres, 3))
        out["available"].append("unemployment")
    out["total"] = round(
        out["inflation_effect"] + out["gas_effect"] + out["unemployment_effect"], 3
    )
    return out


def schedule_lookup(schedule: dict[str, Any], years: float | None) -> tuple[str, float]:
    """Categorical lookup: keys like ``"0"``, ``"1-6"``, ``"16+"`` → value.
    Returns ``(category label, value)``; unknown/None years → ("none", 0.0)."""
    if years is None:
        return "none", 0.0
    y = float(years)
    for key, val in schedule.items():
        if str(key).startswith("_"):
            continue
        k = str(key)
        if k.endswith("+"):
            if y >= float(k[:-1]):
                return k, float(val)
        elif "-" in k:
            lo, hi = k.split("-", 1)
            if float(lo) <= y <= float(hi) + 0.999:
                return k, float(val)
        elif y == float(k) or (float(k) == 0 and y < 1):
            return k, float(val)
    return "none", 0.0
