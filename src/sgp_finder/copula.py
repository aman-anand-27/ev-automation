"""Gaussian copula for joint probability of correlated same-game legs.

Each leg's fair probability p_i maps to a latent threshold z_i = Φ⁻¹(p_i).
The legs jointly hit iff every latent normal falls below its threshold, so
P(all hit) is the orthant probability of a multivariate normal with
correlation matrix R — the standard sharp way to price correlated parlays
without play-by-play data.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import multivariate_normal, norm

# Pairwise ρ magnitudes are capped strictly below 1: |ρ|=1 makes R singular and
# a "parlay" of one effective leg, which the redundancy flag should expose
# instead of the math silently degenerating.
RHO_CAP = 0.99

_P_EPS = 1e-9


def nearest_psd(r: np.ndarray, eps: float = 1e-8) -> tuple[np.ndarray, bool]:
    """Project a symmetric matrix to the nearest positive semi-definite
    correlation matrix (eigenvalue clipping + diagonal rescale).

    Heuristic pairwise ρ values can form a non-PSD matrix for 3 legs
    (e.g. ρ12=0.9, ρ13=0.9, ρ23=−0.5 is geometrically impossible).
    Returns (repaired matrix, whether repair was needed).
    """
    r = np.asarray(r, dtype=float)
    eigval, eigvec = np.linalg.eigh(r)
    if eigval.min() >= 0:
        return r, False
    clipped = np.clip(eigval, eps, None)
    fixed = eigvec @ np.diag(clipped) @ eigvec.T
    d = np.sqrt(np.diag(fixed))
    fixed = fixed / np.outer(d, d)
    np.fill_diagonal(fixed, 1.0)
    return fixed, True


def build_corr_matrix(pairwise: dict[tuple[int, int], float], n: int) -> tuple[np.ndarray, bool]:
    """Build an n×n correlation matrix from {(i, j): ρ} pairs (i < j).

    Missing pairs default to 0. ρ magnitudes are capped at RHO_CAP and the
    matrix is repaired to PSD if the heuristic values are inconsistent.
    """
    r = np.eye(n)
    for (i, j), rho in pairwise.items():
        rho = max(-RHO_CAP, min(RHO_CAP, rho))
        r[i, j] = r[j, i] = rho
    return nearest_psd(r)


def joint_prob(probs: list[float], r: np.ndarray) -> float:
    """P(all legs hit) under the Gaussian copula with correlation matrix R.

    Exact bivariate-normal CDF for 2 legs; scipy's Genz numerical MVN CDF for
    3+ legs (our SGPs are always exactly 3). Clamped to [prod, min] bounds is
    NOT applied — the copula value is reported as computed.
    """
    p = np.clip(np.asarray(probs, dtype=float), _P_EPS, 1.0 - _P_EPS)
    n = len(p)
    if n == 1:
        return float(p[0])
    z = norm.ppf(p)
    r = np.asarray(r, dtype=float)
    val = multivariate_normal.cdf(
        z, mean=np.zeros(n), cov=r, allow_singular=True,
        # tight Genz tolerances: EV decisions ride on ~0.1pp differences
        abseps=1e-7, releps=1e-7,
    )
    return float(min(1.0, max(0.0, val)))


def joint_prob_mc(probs: list[float], r: np.ndarray, n_samples: int = 400_000,
                  seed: int = 7) -> float:
    """Monte-Carlo cross-check of joint_prob (used by tests; deterministic seed)."""
    p = np.clip(np.asarray(probs, dtype=float), _P_EPS, 1.0 - _P_EPS)
    z = norm.ppf(p)
    rng = np.random.default_rng(seed)
    r = np.asarray(r, dtype=float)
    # Eigen-decomposition sampling tolerates the PSD-boundary cases Cholesky rejects
    eigval, eigvec = np.linalg.eigh(r)
    a = eigvec @ np.diag(np.sqrt(np.clip(eigval, 0, None)))
    # macOS Accelerate BLAS raises spurious FP-flag warnings in matmul
    # (numpy 2.x known issue); the computed values are correct.
    with np.errstate(all="ignore"):
        draws = rng.standard_normal((n_samples, len(p))) @ a.T
    return float(np.mean(np.all(draws <= z, axis=1)))


def naive_product(probs: list[float]) -> float:
    """Independence assumption: Π p_i (what a naive parlay calc does)."""
    out = 1.0
    for p in probs:
        out *= p
    return out


def correlation_premium(p_joint: float, probs: list[float]) -> float:
    """Correlated joint ÷ naive product. >1 means correlation helps the parlay."""
    naive = naive_product(probs)
    return p_joint / naive if naive > 0 else float("inf")


def effective_legs(p_joint: float, probs: list[float]) -> float:
    """Redundancy metric: how many independent legs this parlay behaves like.

        effective = n · ln(P_joint) / ln(Π p_i)

    Independent legs → n; perfectly correlated equal legs → 1. A 3-leg SGP
    with effective ≈ 1.3 is near-deterministic given one leg — don't be fooled
    by the parlay framing.
    """
    p = np.clip(np.asarray(probs, dtype=float), _P_EPS, 1.0 - _P_EPS)
    log_naive = float(np.sum(np.log(p)))
    if log_naive == 0.0:  # all legs certain
        return float(len(p))
    pj = min(max(p_joint, _P_EPS), 1.0 - _P_EPS)
    return float(len(p) * np.log(pj) / log_naive)
