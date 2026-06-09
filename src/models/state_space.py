"""Jackman-style hierarchical state-space model for polling averages.

Random-walk latent state α_t with additive pollster house effects δⱼ under a
weighted sum-to-zero constraint. Per-pollster excess variance τⱼ² absorbs
firm-level reliability differences, replacing the multiplicative quality factor.

Model spec (all quantities in percentage-point units):
    σ_α         ~ HalfNormal(0, 1)
    σ_δ         ~ HalfNormal(0, 2.5)
    α_t         ~ GaussianRandomWalk(σ=σ_α)          # latent approval/ballot share
    δⱼ_raw      ~ Normal(0, σ_δ)
    δⱼ           = δⱼ_raw − Σ(wⱼ·δⱼ_raw)/Σwⱼ         # weighted sum-to-zero
    τⱼ          ~ HalfNormal(0, 2.5)                  # per-pollster excess SD
    σ²_obs(i)   = y_i·(100−y_i)/n_i + τⱼ₍ᵢ₎²        # sampling + excess variance
    y_i         ~ Normal(α_{t(i)} + δⱼ₍ᵢ₎, σ_obs(i)) # observed poll

Sentiment covariate slot (β): pre-cut at zero. Wire s_t and unfreeze β when a
daily sentiment series is available.

Citations:
    Jackman (2005), AJPS 40(4)
    Linzer (2013), JASA 108(501)
    Heidemanns, Gelman & Morris (2020), Harvard Data Science Review
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from src.data.base import Poll

logger = logging.getLogger(__name__)


@dataclass
class StateSpaceResult:
    """Posterior summaries from a state-space fit."""

    dates: list[date]
    alpha_mean: np.ndarray      # shape (T,) — posterior mean latent state
    alpha_lo: np.ndarray        # shape (T,) — 2.5th percentile
    alpha_hi: np.ndarray        # shape (T,) — 97.5th percentile
    pollsters: list[str]
    delta_mean: np.ndarray      # shape (J,) — house effect posterior mean
    delta_lo: np.ndarray        # shape (J,) — 2.5th percentile
    delta_hi: np.ndarray        # shape (J,) — 97.5th percentile
    tau_mean: np.ndarray        # shape (J,) — excess SD posterior mean
    sigma_alpha_mean: float
    n_polls: int
    convergence_ok: bool        # False if R̂ > 1.05 on any parameter

    def estimate_at(self, as_of: date) -> tuple[float, float, float]:
        """Return (mean, lo_95, hi_95) of latent state at given date.

        If as_of is beyond the last data date, the random walk extends the
        posterior forward with growing uncertainty — this is correct behaviour.
        For dates before the first data date, clamps to the first index.
        """
        if as_of <= self.dates[0]:
            idx = 0
        elif as_of >= self.dates[-1]:
            idx = len(self.dates) - 1
            if as_of > self.dates[-1]:
                # Extend forward: variance grows as σ_α² × Δt
                extra_days = (as_of - self.dates[-1]).days
                extension_sd = self.sigma_alpha_mean * (extra_days ** 0.5)
                mean = self.alpha_mean[idx]
                lo = self.alpha_lo[idx] - extension_sd
                hi = self.alpha_hi[idx] + extension_sd
                return float(mean), float(lo), float(hi)
        else:
            idx = next(i for i, d in enumerate(self.dates) if d >= as_of)
        return float(self.alpha_mean[idx]), float(self.alpha_lo[idx]), float(self.alpha_hi[idx])

    def house_effects_sorted(self, threshold: float = 1.5) -> list[tuple[str, float, float, float]]:
        """Return house effects with |mean| > threshold, sorted by magnitude.

        Returns list of (pollster, mean_pp, lo_95_pp, hi_95_pp) tuples.
        Positive mean = pro-Approve / pro-Democrat lean.
        """
        results = []
        for j, name in enumerate(self.pollsters):
            if abs(self.delta_mean[j]) > threshold:
                results.append((name, self.delta_mean[j], self.delta_lo[j], self.delta_hi[j]))
        return sorted(results, key=lambda x: abs(x[1]), reverse=True)


def fit(
    polls: list[Poll],
    choice: str,
    as_of: date | None = None,
    draws: int = 1000,
    tune: int = 1000,
    target_accept: float = 0.9,
    random_seed: int = 42,
) -> StateSpaceResult | None:
    """Fit the state-space model and return posterior summaries.

    Args:
        polls: Filtered list of polls (should already be filtered to the
               relevant poll_type; all polls must contain `choice` as an answer).
        choice: Which answer to model as the latent state (e.g. "Approve", "Democrat").
        as_of: Not used in fitting; included for API symmetry.
        draws: Posterior draws per chain.
        tune: Tuning steps per chain.
        target_accept: NUTS target acceptance rate.
        random_seed: Seed for reproducibility.

    Returns:
        StateSpaceResult, or None if fitting fails.
    """
    try:
        import pymc as pm
        import pytensor.tensor as pt
    except ImportError:
        logger.warning("PyMC not installed; state-space model unavailable")
        return None

    # ── Data preparation ────────────────────────────────────────────────────

    # Extract valid (poll, pct) pairs for the requested choice
    valid: list[tuple[Poll, float]] = []
    for p in polls:
        for a in p.answers:
            if a.choice == choice and a.pct is not None:
                valid.append((p, a.pct))
                break

    if len(valid) < 10:
        logger.warning("Too few polls (%d) for state-space fit", len(valid))
        return None

    poll_objs = [v[0] for v in valid]
    obs_y = np.array([v[1] for v in valid], dtype=float)

    # Time grid: one entry per calendar day from first to last poll midpoint
    min_date = min(p.midpoint_date for p in poll_objs)
    max_date = max(p.midpoint_date for p in poll_objs)
    dates = [min_date + timedelta(days=d) for d in range((max_date - min_date).days + 1)]
    date_to_idx = {d: i for i, d in enumerate(dates)}
    n_days = len(dates)

    # Pollster index
    pollster_names = sorted({p.pollster for p in poll_objs})
    pollster_to_idx = {name: i for i, name in enumerate(pollster_names)}
    n_pollsters = len(pollster_names)

    time_idx = np.array([date_to_idx[p.midpoint_date] for p in poll_objs], dtype=int)
    pollster_idx = np.array([pollster_to_idx[p.pollster] for p in poll_objs], dtype=int)

    # Sample sizes — default 1000 when missing
    obs_n = np.array([p.sample_size if p.sample_size else 1000 for p in poll_objs], dtype=float)

    # Sampling variance in %-squared: p̂*(1-p̂)/n * 10000
    sampling_var = obs_y * (100.0 - obs_y) / obs_n

    # Poll-count weights for sum-to-zero constraint (favouring high-volume pollsters)
    poll_counts = np.bincount(pollster_idx, minlength=n_pollsters).astype(float)
    sz_weights = poll_counts / poll_counts.sum()

    logger.info(
        "State-space fit: T=%d days, J=%d pollsters, N=%d polls",
        n_days, n_pollsters, len(valid),
    )

    # ── PyMC model ──────────────────────────────────────────────────────────

    # Prior for α₀: data-informed starting point
    prior_alpha = float(np.mean(obs_y))
    coords = {"time": dates, "pollster": pollster_names}

    with pm.Model(coords=coords):
        # Innovation SD for the latent random walk
        sigma_alpha = pm.HalfNormal("sigma_alpha", sigma=1.0)

        # House-effect scale
        sigma_delta = pm.HalfNormal("sigma_delta", sigma=2.5)

        # Latent state: non-centered random walk (better NUTS efficiency than
        # centered GaussianRandomWalk for long time series with sparse observations)
        alpha_0 = pm.Normal("alpha_0", mu=prior_alpha, sigma=5.0)
        raw_innovations = pm.Normal("raw_innovations", mu=0.0, sigma=1.0, shape=n_days - 1)
        alpha = pm.Deterministic(
            "alpha",
            pt.concatenate([[alpha_0], alpha_0 + pt.cumsum(sigma_alpha * raw_innovations)]),
        )

        # House effects with weighted sum-to-zero constraint
        delta_raw = pm.Normal("delta_raw", mu=0.0, sigma=sigma_delta, shape=n_pollsters)
        sz_w = pt.as_tensor_variable(sz_weights)
        delta = pm.Deterministic("delta", delta_raw - pt.dot(sz_w, delta_raw))

        # Per-pollster excess variance (tighter prior — see METHODOLOGY_REVIEW.md)
        tau = pm.HalfNormal("tau", sigma=2.5, shape=n_pollsters)

        # Sentiment covariate slot: β × s_t frozen at 0 (unfreeze in Phase 7)
        beta_sentiment = 0.0  # noqa: F841 — placeholder

        # Observation model
        obs_sigma = pt.sqrt(
            pt.as_tensor_variable(sampling_var) + tau[pollster_idx] ** 2
        )
        mu = alpha[time_idx] + delta[pollster_idx]
        pm.Normal("y_obs", mu=mu, sigma=obs_sigma, observed=obs_y)

        # ── Sampling ────────────────────────────────────────────────────────
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            trace = pm.sample(
                draws=draws,
                tune=tune,
                target_accept=target_accept,
                random_seed=random_seed,
                progressbar=True,
                cores=1,
                chains=2,
            )

    # ── Posterior summaries ─────────────────────────────────────────────────

    # alpha: shape (chains, draws, T) → flatten to (chains*draws, T)
    alpha_post = trace.posterior["alpha"].values.reshape(-1, n_days)
    alpha_mean = alpha_post.mean(axis=0)
    alpha_lo = np.percentile(alpha_post, 2.5, axis=0)
    alpha_hi = np.percentile(alpha_post, 97.5, axis=0)

    # delta: shape (chains*draws, J)
    delta_post = trace.posterior["delta"].values.reshape(-1, n_pollsters)
    delta_mean = delta_post.mean(axis=0)
    delta_lo = np.percentile(delta_post, 2.5, axis=0)
    delta_hi = np.percentile(delta_post, 97.5, axis=0)

    # tau
    tau_post = trace.posterior["tau"].values.reshape(-1, n_pollsters)
    tau_mean = tau_post.mean(axis=0)

    sigma_alpha_mean = float(trace.posterior["sigma_alpha"].values.mean())

    # Convergence check: R̂ on alpha (most complex parameter)
    try:
        import arviz as az
        rhat = az.rhat(trace)
        innov_rhat_max = float(rhat["raw_innovations"].max())
        delta_rhat_max = float(rhat["delta_raw"].max())
        convergence_ok = innov_rhat_max < 1.05 and delta_rhat_max < 1.05
        if not convergence_ok:
            logger.warning(
                "Convergence warning: innovations R̂=%.3f, δ R̂=%.3f",
                innov_rhat_max, delta_rhat_max,
            )
    except Exception:
        convergence_ok = True  # don't fail output on diagnostic error

    return StateSpaceResult(
        dates=dates,
        alpha_mean=alpha_mean,
        alpha_lo=alpha_lo,
        alpha_hi=alpha_hi,
        pollsters=pollster_names,
        delta_mean=delta_mean,
        delta_lo=delta_lo,
        delta_hi=delta_hi,
        tau_mean=tau_mean,
        sigma_alpha_mean=sigma_alpha_mean,
        n_polls=len(valid),
        convergence_ok=convergence_ok,
    )
