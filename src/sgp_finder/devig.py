"""Odds conversions and no-vig (fair probability) methods.

De-vig operates on a FULL market: all outcome prices of one bookmaker's market
(2-way Over/Under or spread sides; n-way for soccer 1X2). Multiplicative is the
default; Shin's method is optional and falls back to multiplicative when the
market has no overround (e.g. exchange prices).
"""

from __future__ import annotations


def american_to_decimal(american: float | int | str) -> float:
    """'+100' → 2.0, '-150' → 1.6667, 300 → 4.0. Accepts int, float or string."""
    if isinstance(american, str):
        american = american.strip().replace("+", "")
        if not american:
            raise ValueError("empty american odds")
        american = float(american)
    a = float(american)
    if a == 0:
        raise ValueError("american odds cannot be 0")
    if a > 0:
        return 1.0 + a / 100.0
    return 1.0 + 100.0 / abs(a)


def decimal_to_american(decimal: float) -> str:
    """Convert decimal odds to an American odds string (+110, -150)."""
    if decimal >= 2.0:
        return f"+{round((decimal - 1) * 100)}"
    if decimal <= 1.0:
        return "N/A"  # degenerate price (locked/suspended market)
    return str(round(-100.0 / (decimal - 1)))


def implied(decimal: float) -> float:
    """Raw implied probability (vig retained)."""
    return 1.0 / decimal


def devig_multiplicative(prices: list[float]) -> list[float]:
    """Proportional no-vig: p_i = (1/o_i) / Σ(1/o_j) over the full market."""
    raw = [1.0 / o for o in prices]
    total = sum(raw)
    if total <= 0:
        raise ValueError("market has no probability mass")
    return [r / total for r in raw]


def devig_shin(prices: list[float], tol: float = 1e-10, max_iter: int = 200) -> list[float]:
    """Shin's method: models the overround as insider-trading proportion z.

    Solves Σ_i p_i(z) = 1 with
        p_i(z) = [sqrt(z² + 4(1−z)·π_i²/S) − z] / (2(1−z)),  π_i = 1/o_i, S = Σπ_i.

    Pushes more of the vig onto longshots than the multiplicative method
    (favourite–longshot bias). Falls back to multiplicative when the market
    has no overround (S ≤ 1, e.g. exchange prices).
    """
    pi = [1.0 / o for o in prices]
    s = sum(pi)
    if s <= 1.0:
        return devig_multiplicative(prices)

    def probs(z: float) -> list[float]:
        return [
            ((z * z + 4.0 * (1.0 - z) * p * p / s) ** 0.5 - z) / (2.0 * (1.0 - z))
            for p in pi
        ]

    lo, hi = 0.0, 1.0 - 1e-9
    # Σp(0) = S/√S = √S > 1; Σp(z) decreases towards Σπ²/S < 1 as z → 1
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        if sum(probs(mid)) > 1.0:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    p = probs((lo + hi) / 2.0)
    total = sum(p)
    return [x / total for x in p]  # exact renormalisation of residual error


def devig(prices: list[float], method: str = "multiplicative") -> list[float]:
    """Dispatch to the configured de-vig method."""
    if method == "multiplicative":
        return devig_multiplicative(prices)
    if method == "shin":
        return devig_shin(prices)
    raise ValueError(f"unknown devig method: {method}")
