"""Unit tests for hold math helpers."""

import pytest

from src.cno_odds.hold import (
    _find_opposing,
    _same_side,
    compute_hold,
    compute_rows,
)


# ── compute_hold ──────────────────────────────────────────────────────────────

def test_hold_basic():
    # DK -110 ≈ 1.909, Novig +100 = 2.0 → ~2.4% hold
    hold = compute_hold(1.909, 2.0)
    assert 2.0 < hold < 3.0


def test_hold_zero():
    # Both sides at 2.0 → perfectly efficient, 0% hold
    assert abs(compute_hold(2.0, 2.0)) < 0.001


def test_hold_negative():
    # Novig better than fair → sub-zero hold (positive EV round-trip)
    assert compute_hold(2.1, 2.1) < 0


# ── _same_side ────────────────────────────────────────────────────────────────

def test_same_side_h2h_match():
    assert _same_side({"name": "NYY"}, {"name": "NYY"}, "h2h") is True


def test_same_side_h2h_no_match():
    assert _same_side({"name": "BOS"}, {"name": "NYY"}, "h2h") is False


def test_same_side_spreads_name_and_point():
    a = {"name": "NYY", "point": -1.5}
    b = {"name": "NYY", "point": -1.5}
    assert _same_side(a, b, "spreads") is True


def test_same_side_spreads_wrong_point():
    a = {"name": "NYY", "point": -1.5}
    b = {"name": "NYY", "point": -2.5}
    assert _same_side(a, b, "spreads") is False


# ── _find_opposing ────────────────────────────────────────────────────────────

def test_find_opposing_h2h():
    dk = {"name": "NYY", "price": 1.83}
    novig = [{"name": "NYY", "price": 1.85}, {"name": "BOS", "price": 2.10}]
    result = _find_opposing(dk, novig, "h2h")
    assert result["name"] == "BOS"


def test_find_opposing_spreads_exact():
    dk = {"name": "NYY", "price": 1.91, "point": -1.5}
    novig = [
        {"name": "NYY", "price": 1.95, "point": -1.5},
        {"name": "BOS", "price": 1.92, "point": 1.5},
    ]
    result = _find_opposing(dk, novig, "spreads")
    assert result is not None
    assert result["name"] == "BOS"
    assert result["point"] == 1.5


def test_find_opposing_spreads_mismatch_skipped():
    # BOS is at +2.5, not +1.5 — different line, must not pair
    dk = {"name": "NYY", "price": 1.91, "point": -1.5}
    novig = [
        {"name": "NYY", "price": 1.95, "point": -1.5},
        {"name": "BOS", "price": 1.92, "point": 2.5},
    ]
    assert _find_opposing(dk, novig, "spreads") is None


def test_find_opposing_totals_match():
    dk = {"name": "Over", "price": 1.91, "point": 8.5}
    novig = [
        {"name": "Over", "price": 1.93, "point": 8.5},
        {"name": "Under", "price": 1.90, "point": 8.5},
    ]
    result = _find_opposing(dk, novig, "totals")
    assert result["name"] == "Under"


def test_find_opposing_totals_mismatched_point():
    dk = {"name": "Over", "price": 1.91, "point": 8.5}
    novig = [{"name": "Under", "price": 1.90, "point": 9.0}]
    assert _find_opposing(dk, novig, "totals") is None


# ── compute_rows integration ──────────────────────────────────────────────────

def _make_game(**bm_extra):
    bookmakers = [
        {
            "key": "draftkings",
            "markets": [{"key": "h2h", "outcomes": [
                {"name": "Yankees", "price": 1.83},
                {"name": "Red Sox", "price": 2.10},
            ]}],
        },
        {
            "key": "novig",
            "markets": [{"key": "h2h", "outcomes": [
                {"name": "Yankees", "price": 1.90},
                {"name": "Red Sox", "price": 2.05},
            ]}],
        },
    ]
    bookmakers.extend(bm_extra.get("extra_bm", []))
    return {
        "id": "g1",
        "sport_key": "baseball_mlb",
        "sport_title": "MLB",
        "commence_time": "2025-05-21T17:00:00Z",
        "home_team": "Yankees",
        "away_team": "Red Sox",
        "bookmakers": bookmakers,
    }


_CFG = {
    "markets": ["h2h"],
    "target_books": {"primary": "draftkings", "exchange": "novig"},
    "thresholds": {"min_books_for_consensus": 4},
}


def test_compute_rows_two_sides_per_game():
    rows = compute_rows([_make_game()], _CFG)
    assert len(rows) == 2


def test_compute_rows_sorted_by_hold():
    rows = compute_rows([_make_game()], _CFG)
    holds = [r["hold_pct"] for r in rows]
    assert holds == sorted(holds)


def test_compute_rows_skips_game_without_dk():
    game = _make_game()
    game["bookmakers"] = [b for b in game["bookmakers"] if b["key"] != "draftkings"]
    rows = compute_rows([game], _CFG)
    assert rows == []


def test_compute_rows_skips_3way_h2h():
    game = _make_game()
    game["bookmakers"][0]["markets"][0]["outcomes"].append({"name": "Draw", "price": 4.0})
    rows = compute_rows([game], _CFG)
    assert rows == []


def test_compute_rows_consensus_none_when_too_few_books():
    rows = compute_rows([_make_game()], _CFG)
    for r in rows:
        assert r["consensus_implied_pct"] is None
