"""Boost math: boosted odds, EV, break-even boost, and the min-odds gate.

Every recommendation is a boosted 3-leg SGP with two user parameters:
  boost_pct — profit boost always applied (typical 30 / 50 / 100);
  min_odds  — the boost token's minimum-odds requirement, in AMERICAN odds.

The same formulas are mirrored client-side in the dashboard JS so boost_pct
and min_odds changes recompute without a re-fetch.
"""

from __future__ import annotations

from .devig import american_to_decimal


def apply_boost(offered_decimal: float, boost_pct: float) -> float:
    """Profit boost on decimal odds: o' = 1 + (o − 1)·(1 + boost/100)."""
    return 1.0 + (offered_decimal - 1.0) * (1.0 + boost_pct / 100.0)


def ev(p_fair: float, decimal_odds: float) -> float:
    """Expected value per 1 unit stake: p·(o − 1) − (1 − p)."""
    return p_fair * (decimal_odds - 1.0) - (1.0 - p_fair)


def break_even_boost(p_fair: float, offered_decimal: float) -> float | None:
    """Boost % at which the SGP turns +EV (the headline metric).

    Solve p·(o'−1) = 1−p with o'−1 = (o−1)(1+b/100):
        b = 100 · [ (1/p − 1) / (o − 1) − 1 ]

    ≤ 0 means +EV with no boost at all. None when undefined (degenerate
    offered price or p_fair outside (0, 1))."""
    if offered_decimal <= 1.0 or not 0.0 < p_fair < 1.0:
        return None
    return 100.0 * ((1.0 / p_fair - 1.0) / (offered_decimal - 1.0) - 1.0)


def passes_min_odds(
    offered_decimal: float,
    min_odds_american: float | int | str,
    boost_pct: float = 0.0,
    gate_on_boosted: bool = False,
) -> bool:
    """Min-odds gate for boost eligibility.

    By default the gate keys on the PRE-boost (natural) SGP price, which is how
    bet365 boost tokens normally read. Set gate_on_boosted=True if a promo's
    terms apply the floor to the boosted price instead.
    """
    threshold = american_to_decimal(min_odds_american)
    price = apply_boost(offered_decimal, boost_pct) if gate_on_boosted else offered_decimal
    return price >= threshold
