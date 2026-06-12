"""No-vig math and odds-conversion tests for the SGP finder."""

import pytest

from src.sgp_finder.devig import (
    american_to_decimal,
    decimal_to_american,
    devig,
    devig_multiplicative,
    devig_shin,
    implied,
)


def test_american_to_decimal_positive():
    assert american_to_decimal("+100") == pytest.approx(2.0)
    assert american_to_decimal("+300") == pytest.approx(4.0)
    assert american_to_decimal(150) == pytest.approx(2.5)


def test_american_to_decimal_negative():
    assert american_to_decimal("-150") == pytest.approx(1.0 + 100.0 / 150.0)
    assert american_to_decimal(-200) == pytest.approx(1.5)


def test_american_to_decimal_rejects_zero_and_empty():
    with pytest.raises(ValueError):
        american_to_decimal(0)
    with pytest.raises(ValueError):
        american_to_decimal("")


def test_decimal_to_american_roundtrip():
    assert decimal_to_american(2.0) == "+100"
    assert decimal_to_american(4.0) == "+300"
    assert decimal_to_american(1.5) == "-200"
    assert decimal_to_american(0.99) == "N/A"


def test_implied():
    assert implied(2.0) == pytest.approx(0.5)


def test_multiplicative_two_way():
    # -110/-110 → 50/50 after stripping vig
    o = american_to_decimal(-110)
    p = devig_multiplicative([o, o])
    assert p[0] == pytest.approx(0.5)
    assert sum(p) == pytest.approx(1.0)


def test_multiplicative_three_way_soccer():
    prices = [2.4, 3.3, 3.1]  # 1X2 with overround
    p = devig_multiplicative(prices)
    assert sum(p) == pytest.approx(1.0)
    # ordering preserved: shortest price → highest prob
    assert p[0] > p[2] > p[1]


def test_multiplicative_no_vig_market_unchanged():
    p = devig_multiplicative([2.0, 2.0])
    assert p == pytest.approx([0.5, 0.5])


def test_shin_sums_to_one_and_orders():
    prices = [1.5, 2.86]  # fav/dog with vig
    p = devig_shin(prices)
    assert sum(p) == pytest.approx(1.0)
    assert p[0] > p[1]


def test_shin_pushes_vig_to_longshot_vs_multiplicative():
    # Shin gives the favourite MORE fair probability than multiplicative
    # (the overround is attributed disproportionately to the longshot).
    prices = [1.2, 5.5]  # booksum ≈ 1.015 → real overround
    mult = devig_multiplicative(prices)
    shin = devig_shin(prices)
    assert shin[0] > mult[0]
    assert shin[1] < mult[1]


def test_shin_falls_back_when_no_overround():
    prices = [2.1, 2.1]  # booksum < 1 (exchange-like)
    assert devig_shin(prices) == pytest.approx(devig_multiplicative(prices))


def test_devig_dispatcher():
    prices = [1.9, 1.9]
    assert devig(prices) == pytest.approx(devig_multiplicative(prices))
    assert devig(prices, "shin") == pytest.approx(devig_shin(prices))
    with pytest.raises(ValueError):
        devig(prices, "nope")
