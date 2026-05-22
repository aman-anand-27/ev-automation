"""Unit tests for qualification threshold logic."""

from src.cno_odds.qualify import qualify_rows

_CFG = {
    "thresholds": {
        "hold_max_pct": 3.0,
        "dk_consensus_tolerance_pp": 1.5,
        "novig_best_rank": 2,
        "min_books_for_consensus": 4,
    }
}


def _row(**overrides) -> dict:
    base = {
        "hold_pct": 1.5,
        "dk_implied_pct": 55.0,
        "consensus_implied_pct": 54.5,
        "novig_rank": 1,
        "qualified": False,
        "disqualify_reasons": [],
    }
    base.update(overrides)
    return base


def test_qualifies_all_conditions_met():
    rows = qualify_rows([_row()], _CFG)
    assert rows[0]["qualified"] is True
    assert rows[0]["disqualify_reasons"] == []


def test_disqualifies_high_hold():
    rows = qualify_rows([_row(hold_pct=3.1)], _CFG)
    assert rows[0]["qualified"] is False
    assert any("hold" in r for r in rows[0]["disqualify_reasons"])


def test_disqualifies_no_consensus():
    rows = qualify_rows([_row(consensus_implied_pct=None)], _CFG)
    assert rows[0]["qualified"] is False
    assert any("consensus" in r for r in rows[0]["disqualify_reasons"])


def test_disqualifies_dk_off_market():
    # diff = 2.5pp > 1.5pp tolerance
    rows = qualify_rows([_row(dk_implied_pct=57.0, consensus_implied_pct=54.5)], _CFG)
    assert rows[0]["qualified"] is False
    assert any("DK" in r for r in rows[0]["disqualify_reasons"])


def test_qualifies_dk_at_tolerance_boundary():
    # diff = exactly 1.5pp → should qualify
    rows = qualify_rows([_row(dk_implied_pct=56.0, consensus_implied_pct=54.5)], _CFG)
    assert rows[0]["qualified"] is True


def test_disqualifies_novig_rank_too_low():
    rows = qualify_rows([_row(novig_rank=3)], _CFG)
    assert rows[0]["qualified"] is False
    assert any("Novig" in r for r in rows[0]["disqualify_reasons"])


def test_qualifies_novig_at_rank_boundary():
    # rank=2, max_rank=2 → should qualify
    rows = qualify_rows([_row(novig_rank=2)], _CFG)
    assert rows[0]["qualified"] is True


def test_all_failures_reported():
    row = _row(hold_pct=5.0, novig_rank=5, consensus_implied_pct=None)
    rows = qualify_rows([row], _CFG)
    assert rows[0]["qualified"] is False
    assert len(rows[0]["disqualify_reasons"]) == 3


def test_mutates_rows_in_place():
    row = _row()
    returned = qualify_rows([row], _CFG)
    assert returned[0] is row  # same object
