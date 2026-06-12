"""Gaussian-copula joint probability tests."""

import numpy as np
import pytest

from src.sgp_finder.copula import (
    RHO_CAP,
    build_corr_matrix,
    correlation_premium,
    effective_legs,
    joint_prob,
    joint_prob_mc,
    naive_product,
    nearest_psd,
)


def _r(rho, n=2):
    m = np.eye(n)
    for i in range(n):
        for j in range(n):
            if i != j:
                m[i, j] = rho
    return m


def test_rho_zero_is_independence_two_legs():
    p = [0.55, 0.40]
    assert joint_prob(p, _r(0.0)) == pytest.approx(0.55 * 0.40, abs=1e-6)


def test_rho_zero_is_independence_three_legs():
    p = [0.55, 0.40, 0.62]
    assert joint_prob(p, _r(0.0, 3)) == pytest.approx(naive_product(p), abs=1e-5)


def test_rho_one_is_min_leg_two_legs():
    p = [0.55, 0.40]
    # comonotone limit: P(both) → min(p). RHO_CAP keeps R non-singular.
    assert joint_prob(p, _r(RHO_CAP)) == pytest.approx(min(p), abs=5e-3)


def test_rho_one_is_min_leg_three_legs():
    p = [0.7, 0.55, 0.6]
    assert joint_prob(p, _r(RHO_CAP, 3)) == pytest.approx(min(p), abs=1e-2)


def test_positive_rho_between_product_and_min():
    p = [0.6, 0.5, 0.45]
    j = joint_prob(p, _r(0.4, 3))
    assert naive_product(p) < j < min(p)


def test_negative_rho_below_product():
    p = [0.5, 0.5]
    j = joint_prob(p, _r(-0.5))
    assert j < 0.25


def test_matches_monte_carlo_three_legs():
    p = [0.62, 0.48, 0.55]
    pairwise = {(0, 1): 0.85, (0, 2): 0.10, (1, 2): 0.25}
    r, _ = build_corr_matrix(pairwise, 3)
    analytic = joint_prob(p, r)
    mc = joint_prob_mc(p, r, n_samples=600_000)
    assert analytic == pytest.approx(mc, abs=2.5e-3)


def test_build_corr_matrix_caps_rho():
    # 2×2 so the capped value is PSD as-is and survives untouched by repair
    r, _ = build_corr_matrix({(0, 1): 1.5}, 2)
    assert r[0, 1] == pytest.approx(RHO_CAP)
    r, _ = build_corr_matrix({(0, 1): -2.0}, 2)
    assert r[0, 1] == pytest.approx(-RHO_CAP)


def test_nearest_psd_repairs_impossible_matrix():
    # ρ12=0.9, ρ13=0.9, ρ23=−0.5 is geometrically impossible
    bad = np.array([[1.0, 0.9, 0.9], [0.9, 1.0, -0.5], [0.9, -0.5, 1.0]])
    fixed, repaired = nearest_psd(bad)
    assert repaired
    assert np.linalg.eigvalsh(fixed).min() >= -1e-10
    assert np.allclose(np.diag(fixed), 1.0)
    # repaired matrix still usable downstream
    j = joint_prob([0.5, 0.5, 0.5], fixed)
    assert 0.0 < j < 0.5


def test_nearest_psd_leaves_valid_matrix_alone():
    good = _r(0.3, 3)
    fixed, repaired = nearest_psd(good)
    assert not repaired
    assert np.allclose(fixed, good)


def test_correlation_premium():
    p = [0.6, 0.6]
    j = joint_prob(p, _r(0.7))
    assert correlation_premium(j, p) == pytest.approx(j / 0.36)
    assert correlation_premium(j, p) > 1.0


def test_effective_legs_independent_is_n():
    p = [0.5, 0.6, 0.7]
    j = naive_product(p)
    assert effective_legs(j, p) == pytest.approx(3.0, abs=1e-9)


def test_effective_legs_comonotone_equal_legs_is_one():
    p = [0.5, 0.5, 0.5]
    assert effective_legs(0.5, p) == pytest.approx(1.0, abs=1e-9)


def test_effective_legs_between():
    p = [0.6, 0.55, 0.5]
    j = joint_prob(p, _r(0.5, 3))
    eff = effective_legs(j, p)
    assert 1.0 < eff < 3.0
