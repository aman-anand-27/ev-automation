"""Boost/EV math, break-even-boost solver, and min-odds gate tests."""

import pytest

from src.sgp_finder.boost import apply_boost, break_even_boost, ev, passes_min_odds


def test_apply_boost():
    # +200 with a 50% profit boost → +300
    assert apply_boost(3.0, 50) == pytest.approx(4.0)
    assert apply_boost(2.5, 0) == pytest.approx(2.5)
    assert apply_boost(2.0, 100) == pytest.approx(3.0)


def test_ev_signs():
    assert ev(0.5, 2.0) == pytest.approx(0.0)          # fair coin at even money
    assert ev(0.55, 2.0) == pytest.approx(0.10)        # edge → positive
    assert ev(0.45, 2.0) == pytest.approx(-0.10)       # short → negative


def test_break_even_boost_closed_form():
    # p=0.25 fair (+300 true), offered +250 (3.5 dec):
    # b = 100·((1/0.25 − 1)/(3.5 − 1) − 1) = 100·(3/2.5 − 1) = 20
    assert break_even_boost(0.25, 3.5) == pytest.approx(20.0)


def test_break_even_boost_zero_at_fair_price():
    assert break_even_boost(0.25, 4.0) == pytest.approx(0.0)


def test_break_even_boost_negative_when_already_plus_ev():
    assert break_even_boost(0.30, 4.0) < 0


def test_break_even_boost_consistency_with_ev():
    p, offered = 0.18, 4.8
    b = break_even_boost(p, offered)
    assert ev(p, apply_boost(offered, b)) == pytest.approx(0.0, abs=1e-12)
    assert ev(p, apply_boost(offered, b + 10)) > 0
    assert ev(p, apply_boost(offered, b - 10)) < 0


def test_break_even_boost_undefined():
    assert break_even_boost(0.5, 1.0) is None
    assert break_even_boost(0.0, 3.0) is None
    assert break_even_boost(1.0, 3.0) is None


def test_min_odds_gate_american_thresholds():
    # +100 → 2.0 decimal; +300 → 4.0 decimal
    assert passes_min_odds(2.0, "+100")
    assert not passes_min_odds(1.99, "+100")
    assert passes_min_odds(4.0, "+300")
    assert not passes_min_odds(3.9, "+300")
    assert passes_min_odds(3.9, 100)


def test_min_odds_gate_negative_american():
    # -150 → 1.6667
    assert passes_min_odds(1.67, "-150")
    assert not passes_min_odds(1.66, "-150")


def test_min_odds_gate_pre_boost_by_default():
    # offered +150 (2.5) fails a +300 gate even though boosted (50%) is 3.25
    assert not passes_min_odds(2.5, "+300", boost_pct=50)


def test_min_odds_gate_on_boosted_configurable():
    # same SGP passes when the promo gates on the boosted price: 1+(1.5·2)=4.0
    assert passes_min_odds(2.5, "+300", boost_pct=100, gate_on_boosted=True)
    assert not passes_min_odds(2.5, "+300", boost_pct=10, gate_on_boosted=True)
