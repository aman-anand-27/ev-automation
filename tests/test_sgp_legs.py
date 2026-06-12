"""Leg extraction and handicap line-matching tests (real probe-data fixture)."""

import json
from pathlib import Path

import pytest
import yaml

from src.sgp_finder.legs import extract_legs, market_group, sharp_fair

_FIXTURE = Path(__file__).parent / "fixtures" / "mlb_game.json"
_CFG = Path(__file__).parents[1] / "config" / "sgp.yaml"


@pytest.fixture()
def game():
    return json.loads(_FIXTURE.read_text())


@pytest.fixture()
def cfg():
    return yaml.safe_load(_CFG.read_text())


@pytest.fixture()
def resolution():
    return {"target_book": "sport888", "target_label": "888sport"}


# ── market_group: exact line matching ────────────────────────────────────────

def _totals_pool(points):
    pool = []
    for p in points:
        pool.append({"name": "Over", "price": 1.9, "point": p})
        pool.append({"name": "Under", "price": 1.9, "point": p})
    return pool


def test_totals_group_requires_same_point():
    pool = _totals_pool([8.5])
    leg = {"name": "Over", "price": 1.91, "point": 8.5}
    group = market_group(pool, leg, "totals")
    assert group is not None
    assert {o["name"] for o in group} == {"Over", "Under"}

    mismatched = {"name": "Over", "price": 1.91, "point": 9.0}
    assert market_group(pool, mismatched, "totals") is None


def test_spreads_group_requires_exact_flip():
    pool = [
        {"name": "Pirates", "price": 2.5, "point": -1.5},
        {"name": "Marlins", "price": 1.6, "point": 1.5},
        {"name": "Pirates", "price": 1.9, "point": -1.0},
    ]
    leg = {"name": "Pirates", "price": 2.4, "point": -1.5}
    group = market_group(pool, leg, "spreads")
    assert group is not None and len(group) == 2
    assert group[1]["name"] == "Marlins" and group[1]["point"] == 1.5

    # -1.0 Pirates has no +1.0 Marlins side in the pool → not fully priced
    leg_unmatched = {"name": "Pirates", "price": 1.9, "point": -1.0}
    assert market_group(pool, leg_unmatched, "spreads") is None

    # cross-handicap (-2.5) is a different bet — silently skipped
    leg_other_line = {"name": "Pirates", "price": 3.1, "point": -2.5}
    assert market_group(pool, leg_other_line, "spreads") is None


def test_team_totals_group_keys_on_team_and_point():
    pool = [
        {"name": "Over", "description": "Miami Marlins", "price": 1.81, "point": 3.5},
        {"name": "Under", "description": "Miami Marlins", "price": 2.07, "point": 3.5},
        {"name": "Over", "description": "Pittsburgh Pirates", "price": 2.05, "point": 4.5},
    ]
    leg = {"name": "Over", "description": "Miami Marlins", "point": 3.5}
    group = market_group(pool, leg, "team_totals")
    assert group is not None
    assert all(o["description"] == "Miami Marlins" for o in group)

    # Pirates Over 4.5 has no Under side → None
    leg2 = {"name": "Over", "description": "Pittsburgh Pirates", "point": 4.5}
    assert market_group(pool, leg2, "team_totals") is None


def test_h2h_three_way_group_includes_draw():
    pool = [
        {"name": "Canada", "price": 1.85},
        {"name": "Bosnia & Herzegovina", "price": 4.94},
        {"name": "Draw", "price": 3.56},
    ]
    leg = {"name": "Canada", "price": 1.85}
    group = market_group(pool, leg, "h2h")
    assert group is not None and len(group) == 3


# ── sharp_fair: anchor first, exchange-consensus fallback ────────────────────

def test_sharp_fair_prefers_pinnacle(game, cfg):
    sharp_bms = [bm for bm in game["bookmakers"] if bm["key"] != "sport888"]
    leg = {"name": "Over", "price": 1.91, "point": 8.5}
    p, source = sharp_fair(leg, "totals", sharp_bms, "pinnacle", "multiplicative")
    assert source == "pinnacle"
    # pinnacle 1.95/1.93 → Over fair ≈ 0.4974
    assert p == pytest.approx(0.4974, abs=1e-3)


def test_sharp_fair_falls_back_to_exchanges(game):
    sharp_bms = [bm for bm in game["bookmakers"]
                 if bm["key"] in ("matchbook", "betfair_ex_eu")]
    leg = {"name": "Over", "price": 1.91, "point": 8.5}
    res = sharp_fair(leg, "totals", sharp_bms, "pinnacle", "multiplicative")
    assert res is not None
    p, source = res
    assert source.startswith("exchange_consensus(")
    assert 0.3 < p < 0.7


def test_sharp_fair_none_when_line_unpriced(game):
    sharp_bms = [bm for bm in game["bookmakers"] if bm["key"] == "pinnacle"]
    leg = {"name": "Over", "price": 1.91, "point": 23.5}  # nobody prices this
    assert sharp_fair(leg, "totals", sharp_bms, "pinnacle", "multiplicative") is None


# ── extract_legs end-to-end on the fixture ───────────────────────────────────

def test_extract_legs_fixture(game, cfg, resolution):
    legs = extract_legs(game, resolution, cfg)
    assert legs, "expected candidate legs from the fixture game"
    assert len(legs) <= cfg["legs"]["top_k_per_game"]
    markets = {l["market"] for l in legs}
    assert markets <= {"h2h", "spreads", "totals"}
    for leg in legs:
        assert 0.0 < leg["fair_p"] < 1.0
        assert leg["target_price"] > 1.0
        assert leg["ev"] >= cfg["legs"]["min_leg_ev"]
        assert leg["fair_source"] == "pinnacle"  # anchor present in fixture
    # sorted by EV descending
    evs = [l["ev"] for l in legs]
    assert evs == sorted(evs, reverse=True)


def test_extract_legs_no_target_book(game, cfg):
    legs = extract_legs(game, {"target_book": "bet365"}, cfg)
    assert legs == []
