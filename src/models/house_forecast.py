"""House control forecast — uniform swing + noise over 435 districts.

Maturity: FORECAST-LITE. Every district starts from its last (2024) two-party
margin; the national environment (generic ballot + presidential approval) moves
all districts by the same swing; a correlated national error and an independent
per-district error are layered on top; seats are counted against the majority
line. Mid-decade redistricting is applied as a configured net seat shift.

Method
------
1. Expected national margin ``m`` = weighted generic ballot (two-party) and
   approval-implied margin, plus the historical generic-ballot bias.
2. Swing ``s = m − baseline_margin`` (the 2024 national two-party margin).
3. Per simulation: national error ``e_nat ~ t(ν)·σ_nat`` where σ_nat combines
   the generic-ballot error and campaign drift to election day; per district
   ``e_i ~ t(ν)·σ_district``. Simulated district margin
   ``= margin_2024_i + s + e_nat + e_i``.
4. Dem seats = count(margin > 0) + redistricting shift (Normal per state).
5. P(Dem majority) = share of simulations with seats ≥ 218.

Inputs live in ``config/house_2026.json`` and
``data/fallback/house_districts_2024.csv`` (built by
``scripts/build_house_districts.py``).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import norm
from scipy.stats import t as student_t

from src.models import ModelMaturity

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "house_2026.json"
FALLBACK_DIR = PROJECT_ROOT / "data" / "fallback"

DEFAULT_NUM_SIMULATIONS = 50000


@dataclass
class DistrictInput:
    state: str
    district: str
    margin_2024: float  # two-party Dem−Rep, points
    winner_2024: str  # "D" | "R" | "I"
    contested: bool = True
    imputed_from: str = ""
    # 2022 two-party margin on the same lines (None if uncontested / redrawn).
    margin_2022: float | None = None
    # True when the 2024 winner is not on the 2026 ballot.
    open_seat: bool = False
    open_seat_reason: str = ""

    @property
    def label(self) -> str:
        num = "".join(ch for ch in self.district if ch.isdigit())
        return f"{self.state}-{num or 'AL'}"


@dataclass
class DistrictForecast:
    label: str
    state: str
    district: str
    margin_2024: float
    winner_2024: str
    expected_margin: float
    dem_win_prob: float
    margin_p10: float
    margin_p90: float
    # Feature values behind expected_margin (all Dem−Rep points):
    # lean = w24·margin_2024 + w22·margin_2022, then incumbency_adjust (open
    # seats lose the incumbent party's advantage), then the national swing.
    margin_2022: float | None = None
    lean: float = 0.0
    open_seat: bool = False
    open_seat_reason: str = ""
    incumbent_party: str = ""
    incumbency_adjust: float = 0.0


@dataclass
class HouseForecast:
    as_of: date
    num_simulations: int
    dem_majority_prob: float
    mean_dem_seats: float
    median_dem_seats: float
    seats_p10: float
    seats_p90: float
    seat_distribution: dict[int, int]
    dem_majority_threshold: int
    total_seats: int
    # National environment
    expected_national_margin: float  # after bias, two-party D−R
    generic_ballot_two_party: float | None
    approval_implied_margin: float | None
    generic_ballot_bias: float
    baseline_margin: float
    national_swing: float
    national_sigma: float  # total incl. drift
    polling_sigma: float
    campaign_drift_sigma: float
    days_to_election: int
    district_sigma: float
    tail_dof: float | None
    redistricting_shift_mean: float
    redistricting_states: list[dict[str, Any]]
    # Districts
    districts: list[DistrictForecast] = field(default_factory=list)
    competitive: list[DistrictForecast] = field(default_factory=list)
    seats_by_margin: list[dict[str, float]] = field(default_factory=list)
    tipping_point_margin: float | None = None
    # District-lean coefficients actually applied.
    lean_weight_2024: float = 1.0
    lean_weight_2022: float = 0.0
    incumbency_advantage: float = 0.0
    num_open_seats: int = 0
    # Similarity structure applied to the district error.
    similarity_share: float = 0.0
    similarity_weights: dict[str, float] = field(default_factory=dict)
    lean_scale: float = 0.0


def load_house_config(path: Path | None = None) -> dict[str, Any]:
    with (path or CONFIG_PATH).open(encoding="utf-8") as fh:
        return json.load(fh)


def load_districts(
    path: Path | None = None, open_seats: list[dict[str, Any]] | None = None
) -> list[DistrictInput]:
    """Read the district baseline CSV written by scripts/build_house_districts.py.

    ``open_seats`` (from config: ``[{"label": "ME-2", "reason": ...}, ...]``)
    flags districts whose 2024 winner is not running in 2026.
    """
    path = path or FALLBACK_DIR / "house_districts_2024.csv"
    open_by_label = {o["label"].upper(): o.get("reason", "") for o in (open_seats or [])}
    out: list[DistrictInput] = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            m22 = row.get("margin_2022", "")
            d = DistrictInput(
                state=row["state"],
                district=row["district"],
                margin_2024=float(row["margin"]),
                winner_2024=row.get("winner_party") or "",
                contested=(row.get("contested", "true").lower() == "true"),
                imputed_from=row.get("imputed_from", "") or "",
                margin_2022=float(m22) if m22 not in ("", None) else None,
            )
            if d.label.upper() in open_by_label:
                d.open_seat = True
                d.open_seat_reason = open_by_label[d.label.upper()]
            out.append(d)
    unknown = set(open_by_label) - {d.label.upper() for d in out}
    if unknown:
        raise ValueError(f"open_seats labels not found in district file: {sorted(unknown)}")
    return out


def two_party_margin(dem_pct: float, rep_pct: float) -> float:
    """Dem−Rep margin on the two-party share (undecided/third-party removed)."""
    total = dem_pct + rep_pct
    return 0.0 if total <= 0 else (dem_pct - rep_pct) / total * 100.0


def _t_scale(sigma: float, dof: float | None) -> float:
    """Variance-matched Student-t scale: Var(t_ν·s) = σ² ⇒ s = σ·√((ν−2)/ν)."""
    if dof is None:
        return sigma
    if dof <= 2.0:
        raise ValueError(f"tail dof must be > 2 for finite variance, got {dof}")
    return sigma * float(np.sqrt((dof - 2.0) / dof))


class HouseForecastSimulator:
    """Monte Carlo over districts under a shared national swing."""

    maturity = ModelMaturity.NOWCAST

    def __init__(
        self,
        baseline_margin: float,
        national_sigma: float,
        district_sigma: float,
        tail_dof: float | None = 5.0,
        dem_majority_threshold: int = 218,
        total_seats: int = 435,
        redistricting: list[dict[str, Any]] | None = None,
        lean_weight_2024: float = 1.0,
        lean_weight_2022: float = 0.0,
        incumbency_advantage: float = 0.0,
        similarity_share: float = 0.0,
        similarity_weights: dict[str, float] | None = None,
        lean_scale: float = 10.0,
        regions: dict[str, str] | None = None,
    ) -> None:
        if national_sigma < 0 or district_sigma < 0:
            raise ValueError("sigmas must be non-negative")
        if lean_weight_2024 <= 0 or lean_weight_2022 < 0:
            raise ValueError("lean weights must be positive (2024) / non-negative (2022)")
        if not 0.0 <= similarity_share < 1.0:
            raise ValueError("similarity_share must be in [0, 1)")
        self.lean_weight_2024 = lean_weight_2024
        self.lean_weight_2022 = lean_weight_2022
        self.incumbency_advantage = incumbency_advantage
        # Similarity-structured district error (Silver-style): districts in the
        # same state / region / with similar lean share part of their error.
        self.similarity_share = similarity_share
        self.similarity_weights = similarity_weights or {"state": 0.5, "region": 0.2, "lean": 0.3}
        self.lean_scale = lean_scale
        self.regions = regions or {}
        self.baseline_margin = baseline_margin
        self.national_sigma = national_sigma
        self.district_sigma = district_sigma
        self.tail_dof = tail_dof
        self.dem_majority_threshold = dem_majority_threshold
        self.total_seats = total_seats
        self.redistricting = [r for r in (redistricting or []) if r.get("include", True)]

    # ── Helpers ─────────────────────────────────────────────────────────────

    def district_lean(self, d: DistrictInput) -> tuple[float, float]:
        """(lean, incumbency_adjust) for one district before the national swing.

        lean blends the 2024 and 2022 two-party margins (2024 alone when 2022
        is unavailable). An open seat loses ``incumbency_advantage`` points for
        the 2024 winner's party, since both margins embed that incumbent's
        personal advantage.
        """
        if d.margin_2022 is None or self.lean_weight_2022 <= 0:
            lean = d.margin_2024
        else:
            w24, w22 = self.lean_weight_2024, self.lean_weight_2022
            lean = (w24 * d.margin_2024 + w22 * d.margin_2022) / (w24 + w22)
        adjust = 0.0
        if d.open_seat and self.incumbency_advantage:
            if d.winner_2024 == "D":
                adjust = -self.incumbency_advantage
            elif d.winner_2024 == "R":
                adjust = self.incumbency_advantage
        return float(lean), float(adjust)

    def _base_margins(self, districts: list[DistrictInput]) -> np.ndarray:
        return np.array([sum(self.district_lean(d)) for d in districts])

    def similarity_matrix(self, districts: list[DistrictInput]) -> np.ndarray:
        """Unit-diagonal similarity K between districts: a weighted mix of
        same-state, same-region and lean-proximity (``exp(−|Δlean|/scale)``)
        kernels, each PSD, so K is PSD."""
        n = len(districts)
        w = self.similarity_weights
        wsum = sum(w.values()) or 1.0
        states = np.array([d.state for d in districts])
        regions = np.array([self.regions.get(d.state, d.state) for d in districts])
        lean = np.array([self.district_lean(d)[0] for d in districts])
        k = np.zeros((n, n))
        if w.get("state", 0) > 0:
            k += w["state"] * (states[:, None] == states[None, :])
        if w.get("region", 0) > 0:
            k += w["region"] * (regions[:, None] == regions[None, :])
        if w.get("lean", 0) > 0:
            k += w["lean"] * np.exp(-np.abs(lean[:, None] - lean[None, :]) / self.lean_scale)
        k /= wsum
        np.fill_diagonal(k, 1.0)
        return k

    def _district_chol(self, districts: list[DistrictInput]) -> np.ndarray | None:
        """Cholesky factor of the unit-variance district error correlation
        ``share·K + (1−share)·I`` (None when no similarity structure)."""
        if self.similarity_share <= 0.0:
            return None
        k = self.similarity_matrix(districts)
        cov = self.similarity_share * k + (1.0 - self.similarity_share) * np.eye(len(districts))
        try:
            return np.linalg.cholesky(cov)
        except np.linalg.LinAlgError:
            return np.linalg.cholesky(0.5 * cov + 0.5 * np.eye(len(districts)))

    def _t_mix(self, rng: np.random.Generator, n: int) -> np.ndarray:
        """Shared per-simulation scale that turns Gaussian draws into a
        variance-matched multivariate t (one shock hits every district)."""
        if self.tail_dof is None:
            return np.ones((n, 1))
        nu = self.tail_dof
        w = rng.chisquare(nu, size=(n, 1))
        return np.sqrt(nu / w) * np.sqrt((nu - 2.0) / nu)

    @property
    def redistricting_shift_mean(self) -> float:
        return float(sum(r.get("dem_seat_shift", 0.0) for r in self.redistricting))

    def _draw_t(self, rng: np.random.Generator, sigma: float, size: tuple[int, ...]) -> np.ndarray:
        if sigma == 0.0:
            return np.zeros(size)
        if self.tail_dof is None:
            return rng.normal(0.0, sigma, size=size)
        return rng.standard_t(self.tail_dof, size=size) * _t_scale(sigma, self.tail_dof)

    def district_win_prob(self, margin_2024: float, expected_margin: float) -> float:
        """Analytic marginal P(Dem) for one district: both error components
        combined (variance-add; the t marginal is approximated by a t with the
        same dof on the combined scale)."""
        mu = margin_2024 + (expected_margin - self.baseline_margin)
        sigma = float(np.hypot(self.national_sigma, self.district_sigma))
        if self.tail_dof is None:
            return float(norm.cdf(mu / sigma))
        return float(student_t.cdf(mu / _t_scale(sigma, self.tail_dof), df=self.tail_dof))

    def expected_seats_at(self, districts: list[DistrictInput], national_margin: float) -> float:
        """Expected Dem seats if the national margin were exactly
        ``national_margin`` (district noise only) plus the redistricting mean —
        the seats-votes curve of the current map."""
        swing = national_margin - self.baseline_margin
        margins = self._base_margins(districts) + swing
        scale = _t_scale(self.district_sigma, self.tail_dof) if self.district_sigma else None
        if scale is None:
            wins = (margins > 0).astype(float)
        elif self.tail_dof is None:
            wins = norm.cdf(margins / self.district_sigma)
        else:
            wins = student_t.cdf(margins / scale, df=self.tail_dof)
        return float(wins.sum() + self.redistricting_shift_mean)

    # ── Simulation ──────────────────────────────────────────────────────────

    def simulate(
        self,
        districts: list[DistrictInput],
        expected_national_margin: float,
        num_simulations: int = DEFAULT_NUM_SIMULATIONS,
        seed: int | None = None,
        as_of: date | None = None,
        curve_margins: list[float] | None = None,
        **provenance: Any,
    ) -> HouseForecast:
        if num_simulations < 1:
            raise ValueError("num_simulations must be >= 1")
        if not districts:
            raise ValueError("no districts supplied")
        rng = np.random.default_rng(seed)
        as_of = as_of or date.today()

        base = self._base_margins(districts)
        swing = expected_national_margin - self.baseline_margin
        national = self._draw_t(rng, self.national_sigma, (num_simulations, 1))
        chol = self._district_chol(districts)
        if chol is None:
            district = self._draw_t(rng, self.district_sigma, (num_simulations, base.size))
        else:
            # Correlated district error: z ~ N(0, share·K + (1−share)·I), one
            # shared t-scale per simulation, times σ_district. Drawn in chunks
            # to bound memory at 435 districts × many simulations.
            district = np.empty((num_simulations, base.size))
            step = 20000
            for start in range(0, num_simulations, step):
                stop = min(start + step, num_simulations)
                z = rng.standard_normal(size=(stop - start, base.size))
                district[start:stop] = (z @ chol.T) * self._t_mix(rng, stop - start)
            district *= self.district_sigma
        sim_margins = base[None, :] + swing + national + district
        dem_wins = sim_margins > 0.0
        self.last_dem_wins = dem_wins
        seats = dem_wins.sum(axis=1).astype(float)

        # Redistricting: net Dem seat shift per state, drawn each simulation.
        for entry in self.redistricting:
            mean = float(entry.get("dem_seat_shift", 0.0))
            sd = float(entry.get("sd", 0.0))
            seats += rng.normal(mean, sd, size=num_simulations) if sd > 0 else mean
        seats = np.clip(np.rint(seats), 0, self.total_seats).astype(int)

        dem_majority = seats >= self.dem_majority_threshold
        uniq, counts = np.unique(seats, return_counts=True)
        dist = {int(s): int(c) for s, c in zip(uniq, counts, strict=True)}

        win_share = dem_wins.mean(axis=0)
        p10 = np.percentile(sim_margins, 10, axis=0)
        p90 = np.percentile(sim_margins, 90, axis=0)
        forecasts: list[DistrictForecast] = []
        for j, d in enumerate(districts):
            lean, adjust = self.district_lean(d)
            forecasts.append(
                DistrictForecast(
                    label=d.label,
                    state=d.state,
                    district=d.district,
                    margin_2024=round(d.margin_2024, 2),
                    winner_2024=d.winner_2024,
                    expected_margin=round(float(base[j] + swing), 2),
                    dem_win_prob=round(float(win_share[j]), 4),
                    margin_p10=round(float(p10[j]), 2),
                    margin_p90=round(float(p90[j]), 2),
                    margin_2022=None if d.margin_2022 is None else round(d.margin_2022, 2),
                    lean=round(lean, 2),
                    open_seat=d.open_seat,
                    open_seat_reason=d.open_seat_reason,
                    incumbent_party="" if d.open_seat else d.winner_2024,
                    incumbency_adjust=round(adjust, 2),
                )
            )
        competitive = sorted(
            (f for f in forecasts if 0.10 <= f.dem_win_prob <= 0.90),
            key=lambda f: abs(f.dem_win_prob - 0.5),
        )

        # Tipping point: the national margin at which expected seats cross the
        # majority line (bisection on the seats-votes curve).
        tipping = self._tipping_point(districts)
        curve = [
            {"margin": float(m), "dem_seats": round(self.expected_seats_at(districts, m), 1)}
            for m in (curve_margins or [])
        ]

        return HouseForecast(
            as_of=as_of,
            num_simulations=num_simulations,
            dem_majority_prob=round(float(dem_majority.mean()), 4),
            mean_dem_seats=round(float(seats.mean()), 2),
            median_dem_seats=float(np.median(seats)),
            seats_p10=float(np.percentile(seats, 10)),
            seats_p90=float(np.percentile(seats, 90)),
            seat_distribution=dist,
            dem_majority_threshold=self.dem_majority_threshold,
            total_seats=self.total_seats,
            expected_national_margin=round(expected_national_margin, 3),
            generic_ballot_two_party=provenance.get("generic_ballot_two_party"),
            approval_implied_margin=provenance.get("approval_implied_margin"),
            generic_ballot_bias=float(provenance.get("generic_ballot_bias", 0.0)),
            baseline_margin=self.baseline_margin,
            national_swing=round(swing, 3),
            national_sigma=round(self.national_sigma, 3),
            polling_sigma=float(provenance.get("polling_sigma", self.national_sigma)),
            campaign_drift_sigma=float(provenance.get("campaign_drift_sigma", 0.0)),
            days_to_election=int(provenance.get("days_to_election", 0)),
            district_sigma=self.district_sigma,
            tail_dof=self.tail_dof,
            redistricting_shift_mean=self.redistricting_shift_mean,
            redistricting_states=[dict(r) for r in self.redistricting],
            districts=forecasts,
            competitive=competitive,
            seats_by_margin=curve,
            tipping_point_margin=tipping,
            lean_weight_2024=self.lean_weight_2024,
            lean_weight_2022=self.lean_weight_2022,
            incumbency_advantage=self.incumbency_advantage,
            num_open_seats=sum(1 for d in districts if d.open_seat),
            similarity_share=self.similarity_share,
            similarity_weights=dict(self.similarity_weights),
            lean_scale=self.lean_scale,
        )

    def _tipping_point(self, districts: list[DistrictInput]) -> float | None:
        lo, hi = -30.0, 30.0
        f_lo = self.expected_seats_at(districts, lo) - self.dem_majority_threshold
        f_hi = self.expected_seats_at(districts, hi) - self.dem_majority_threshold
        if f_lo > 0 or f_hi < 0:
            return None
        for _ in range(60):
            mid = (lo + hi) / 2.0
            if self.expected_seats_at(districts, mid) - self.dem_majority_threshold > 0:
                hi = mid
            else:
                lo = mid
        return round((lo + hi) / 2.0, 2)


def expected_national_margin(
    cfg: dict[str, Any],
    generic_two_party: float | None,
    approval_net: float | None,
) -> dict[str, float | None]:
    """Blend the two-party generic ballot and approval-implied margin per the
    config weights (re-normalised over the signals present) and add the
    historical generic-ballot bias. Returns the components for transparency."""
    env = cfg.get("national_environment", {})
    pres_party = env.get("president_party", "R").upper()
    coef = env.get("approval_to_margin_coef", 0.3)
    appr_term = None
    if approval_net is not None:
        pres_margin = coef * approval_net
        appr_term = -pres_margin if pres_party == "R" else pres_margin
    parts = []
    if generic_two_party is not None:
        parts.append((env.get("generic_weight", 0.75), generic_two_party))
    if appr_term is not None:
        parts.append((env.get("approval_weight", 0.25), appr_term))
    if not parts:
        return {"expected": None, "raw": None, "approval_implied": appr_term}
    wsum = sum(w for w, _ in parts) or 1.0
    raw = sum(w * v for w, v in parts) / wsum
    bias = env.get("generic_ballot_bias", 0.0)
    return {
        "expected": round(raw + bias, 3),
        "raw": round(raw, 3),
        "approval_implied": None if appr_term is None else round(appr_term, 3),
        "bias": bias,
    }
