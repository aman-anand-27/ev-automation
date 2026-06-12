"""3-leg enumeration, correlation classification, and SGP scoring tests."""

import pytest
import yaml
from pathlib import Path

from src.sgp_finder.correlation import classify, merged_library, pair_rho
from src.sgp_finder.sgp import build_game_sgps, score_triple

_CFG = Path(__file__).parents[1] / "config" / "sgp.yaml"


@pytest.fixture(scope="module")
def cfg():
    return yaml.safe_load(_CFG.read_text())


@pytest.fixture(scope="module")
def lib(cfg):
    return merged_library(cfg["correlation"], "baseball_mlb")


@pytest.fixture(scope="module")
def sgp_cfg(cfg):
    return cfg["sgp"]


def _leg(market, name, point=None, team=None, p=0.5, price=2.0):
    return {
        "market": market, "name": name, "point": point,
        "team": team if team is not None
        else (name if market in ("h2h", "spreads") and name != "Draw" else None),
        "label": f"{name} {market}",
        "fair_p": p, "target_price": price, "target_implied": 1.0 / price,
    }


PIRATES_ML = _leg("h2h", "Pirates", p=0.42, price=2.55)
MARLINS_ML = _leg("h2h", "Marlins", p=0.58, price=1.62)
PIRATES_SPREAD = _leg("spreads", "Pirates", point=-1.5, p=0.40, price=2.40)
MARLINS_SPREAD = _leg("spreads", "Marlins", point=1.5, p=0.60, price=1.57)
OVER = _leg("totals", "Over", point=8.5, p=0.50, price=1.91)
UNDER = _leg("totals", "Under", point=8.5, p=0.50, price=1.85)
TT_OVER = _leg("team_totals", "Over", point=3.5, team="Marlins", p=0.47, price=1.81)


# ── classification & polarity ────────────────────────────────────────────────

def test_classify_kinds():
    assert classify(PIRATES_ML) == {"kind": "ml", "entity": "Pirates", "pol": 1}
    assert classify(OVER)["pol"] == 1 and classify(UNDER)["pol"] == -1
    assert classify(TT_OVER) == {"kind": "tt", "entity": "Marlins", "pol": 1}
    d = classify(_leg("h2h", "Draw"))
    assert d["kind"] == "draw"
    b = classify(_leg("btts", "No"))
    assert b["kind"] == "btts" and b["pol"] == -1


def test_pair_rho_same_team_ml_spread(lib):
    rho, key = pair_rho(PIRATES_ML, PIRATES_SPREAD, lib)
    assert key == "same_team_ml_spread" and rho == pytest.approx(0.85)


def test_pair_rho_opposing_ml_spread_negative(lib):
    rho, key = pair_rho(PIRATES_ML, MARLINS_SPREAD, lib)
    assert key == "opp_team_ml_spread" and rho == pytest.approx(-0.85)


def test_pair_rho_under_flips_sign_exactly(lib):
    rho_over, _ = pair_rho(PIRATES_ML, OVER, lib)
    rho_under, _ = pair_rho(PIRATES_ML, UNDER, lib)
    assert rho_under == pytest.approx(-rho_over)


def test_pair_rho_same_market_blocked(lib):
    rho, key = pair_rho(PIRATES_ML, MARLINS_ML, lib)
    assert rho is None and key == "same_market"
    rho, key = pair_rho(OVER, UNDER, lib)
    assert rho is None


def test_pair_rho_team_total_relations(lib):
    rho_same, key = pair_rho(TT_OVER, MARLINS_ML, lib)
    assert key == "tt_vs_same_ml" and rho_same > 0
    rho_opp, key = pair_rho(TT_OVER, PIRATES_ML, lib)
    assert key == "tt_vs_opp_ml" and rho_opp < 0
    rho_tot, key = pair_rho(TT_OVER, OVER, lib)
    assert key == "tt_vs_total" and rho_tot > 0
    # TT Over vs game UNDER flips negative
    rho_tot_u, _ = pair_rho(TT_OVER, UNDER, lib)
    assert rho_tot_u == pytest.approx(-rho_tot)


def test_merged_library_sport_overrides(cfg):
    mlb = merged_library(cfg["correlation"], "baseball_mlb")
    soccer = merged_library(cfg["correlation"], "soccer_fifa_world_cup")
    assert mlb["ml_vs_total"] == pytest.approx(0.05)      # MLB override
    assert soccer["ml_vs_total"] == pytest.approx(0.15)   # soccer override
    assert soccer["same_team_ml_spread"] == pytest.approx(0.90)
    assert mlb["tt_vs_total"] == pytest.approx(0.55)      # default passthrough


# ── score_triple / enumeration rules ─────────────────────────────────────────

def test_score_triple_classic(lib, sgp_cfg):
    s = score_triple([MARLINS_ML, MARLINS_SPREAD, OVER], lib, sgp_cfg)
    assert s is not None
    # correlation premium: same-team ML+spread is strongly positive
    assert s["premium"] > 1.0
    assert s["p_naive"] < s["p_fair"] <= min(0.58, 0.60, 0.50) + 1e-9
    assert s["effective_legs"] < 3.0
    assert s["offered_decimal_est"] > 1.0
    assert s["break_even_boost"] is not None


def test_score_triple_rejects_same_market(lib, sgp_cfg):
    assert score_triple([PIRATES_ML, MARLINS_ML, OVER], lib, sgp_cfg) is None


def test_score_triple_rejects_contradictory(lib, sgp_cfg):
    # Pirates ML + Marlins -1.5 cover: ρ=-0.85 ≤ exclusion threshold
    assert score_triple([PIRATES_ML, MARLINS_SPREAD, OVER], lib, sgp_cfg) is None


def test_score_triple_requires_three_distinct_markets(lib, sgp_cfg):
    # two totals legs (same market) can't appear even at different points
    over_9 = _leg("totals", "Over", point=9.5, p=0.42, price=2.2)
    assert score_triple([OVER, over_9, PIRATES_ML], lib, sgp_cfg) is None


def test_build_game_sgps_exactly_three_legs(lib, sgp_cfg):
    legs = [MARLINS_ML, PIRATES_ML, MARLINS_SPREAD, PIRATES_SPREAD, OVER, UNDER,
            TT_OVER]
    sgps = build_game_sgps(legs, lib, sgp_cfg)
    assert sgps, "expected at least one valid SGP"
    assert len(sgps) <= sgp_cfg["max_per_game"]
    for s in sgps:
        assert len(s["legs"]) == 3
        assert len({l["market"] for l in s["legs"]}) == 3
        for p in s["pairs"]:
            assert p["rho"] > sgp_cfg["exclude_pair_rho_below"]
    # sorted by break-even boost ascending (None last)
    bes = [s["break_even_boost"] for s in sgps if s["break_even_boost"] is not None]
    assert bes == sorted(bes)


def test_build_game_sgps_low_diversification_flagged(lib, sgp_cfg):
    # same-team ML+spread+TT — heavily correlated triple should be flagged
    s = score_triple([MARLINS_ML, MARLINS_SPREAD, TT_OVER], lib, sgp_cfg)
    assert s is not None
    assert s["effective_legs"] < 2.5
