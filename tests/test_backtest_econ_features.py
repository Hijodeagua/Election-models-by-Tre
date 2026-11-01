"""Tests for scripts/backtest_econ_features.py (pure parts; no network)."""

from __future__ import annotations

import numpy as np
import pytest

from scripts import backtest_econ_features as bt


def test_ols_recovers_known_coefficients():
    rng = np.random.default_rng(0)
    x = rng.normal(size=500)
    y = 1.5 - 2.0 * x + rng.normal(scale=0.01, size=500)
    X = np.column_stack([np.ones_like(x), x])
    beta, se = bt.ols(X, y)
    assert beta == pytest.approx([1.5, -2.0], abs=0.01)
    assert (se > 0).all() and (se < 0.01).all()


def test_t_cdf_matches_symmetry_and_tails():
    assert bt.t_cdf(np.array([0.0]), 5)[0] == pytest.approx(0.5, abs=1e-3)
    lo, hi = bt.t_cdf(np.array([-2.0, 2.0]), 5)
    assert lo + hi == pytest.approx(1.0, abs=1e-3)
    # t(5) two-sided 95% point is 2.571
    assert bt.t_cdf(np.array([2.571]), 5)[0] == pytest.approx(0.975, abs=2e-3)


def test_win_prob_is_monotone_and_centred():
    m = np.array([-10.0, 0.0, 10.0])
    p = bt.win_prob(m, sigma=5.9, dof=5)
    assert p[1] == pytest.approx(0.5, abs=1e-3)
    assert p[0] < p[1] < p[2]
    g = bt.win_prob(m, sigma=5.9, dof=None)
    assert g[1] == pytest.approx(0.5, abs=1e-9)


def test_loco_never_sees_the_held_out_cycle():
    # Error is exactly 3 in cycle A and −3 in cycle B: a constant-bias model
    # trained on the other cycle must predict the wrong sign, so held-out RMSE
    # is 6, not 0. That only happens if LOCO really holds the cycle out.
    years = np.array([2018] * 10 + [2020] * 10, dtype=float)
    err = np.where(years == 2018, 3.0, -3.0)
    X = np.ones((20, 1))
    scores = bt.loco_scores(X, err, poll=np.zeros(20), won=(err > 0).astype(float),
                            years=years, sigma=5.9, dof=5)
    assert scores["rmse"] == pytest.approx(6.0)
    assert scores["win_accuracy"] == 0.0


def test_presidential_margins_handles_both_schemas(monkeypatch):
    csv_2016 = (
        ",votes_dem,votes_gop,total_votes,state_abbr,county_name\n"
        "0,60,40,100,GA,A\n1,10,30,50,GA,B\n2,70,20,100,VT,C\n"
    )
    csv_2024 = (
        "state_name,county_fips,county_name,votes_gop,votes_dem,total_votes\n"
        "Georgia,13001,A,40,60,100\nGeorgia,13003,B,30,10,50\nVermont,50001,C,20,70,100\n"
    )
    monkeypatch.setattr(bt, "fetch_text", lambda url, name: csv_2016 if "2016" in url else csv_2024)
    m16 = bt.presidential_margins(2016)
    m24 = bt.presidential_margins(2024)
    # GA: (70 − 70) / 150 = 0 ; VT: 50/100 = +50
    assert m16 == {"GA": 0.0, "VT": 50.0}
    assert m24 == m16


def test_feature_signing_follows_the_presidents_party():
    # The president's party pays for rising unemployment. With a Republican
    # president (2018, sign −1) a +1pt rise should read as +1 for Democrats.
    assert bt.IN_PARTY[2018] == -1 and bt.IN_PARTY[2022] == +1
    sign = bt.IN_PARTY[2018]
    assert -sign * (5.0 - 4.0) == 1.0
    sign = bt.IN_PARTY[2022]
    assert -sign * (5.0 - 4.0) == -1.0
