"""Leg-pair classification → pairwise ρ from the tunable correlation library.

Every leg is classified to (kind, entity, polarity):
  kind     — ml / spread / total / tt / btts / draw
  entity   — the team a side is tied to (None for totals/btts/draw)
  polarity — +1 for the positive pole (Over / Yes and all team sides),
             −1 for the complement pole (Under / No)

The library (config/sgp.yaml → correlation:) stores ρ for positive poles.
Complement sides flip the sign EXACTLY: under the Gaussian copula the latent
variable of "Under hits" is the negation of "Over hits" at the same line, so
ρ(X, Under) = −ρ(X, Over) is an identity, not a heuristic.

Same-market pairs (both teams' ML, Over+Under, two spreads…) return rho=None —
they are not SGP-able and the enumerator must drop the combo.
"""

from __future__ import annotations


def classify(leg: dict) -> dict:
    cat = leg["market"]
    if cat == "h2h":
        if leg["name"] == "Draw":
            return {"kind": "draw", "entity": None, "pol": 1}
        return {"kind": "ml", "entity": leg["name"], "pol": 1}
    if cat == "spreads":
        return {"kind": "spread", "entity": leg["name"], "pol": 1}
    if cat == "totals":
        return {"kind": "total", "entity": None,
                "pol": 1 if leg["name"] == "Over" else -1}
    if cat == "team_totals":
        return {"kind": "tt", "entity": leg.get("team"),
                "pol": 1 if leg["name"] == "Over" else -1}
    if cat == "btts":
        return {"kind": "btts", "entity": None,
                "pol": 1 if leg["name"] == "Yes" else -1}
    raise ValueError(f"unclassifiable leg market: {cat}")


def merged_library(corr_cfg: dict, sport_key: str) -> dict:
    """Sport section overrides the default section; soccer_* keys share 'soccer'."""
    base = dict(corr_cfg.get("default", {}))
    section = "soccer" if sport_key.startswith("soccer_") else sport_key
    base.update(corr_cfg.get(section, {}) or {})
    return base


def _lookup(lib: dict, key: str) -> float:
    return float(lib.get(key, lib.get("default", 0.0)))


def pair_rho(leg_a: dict, leg_b: dict, lib: dict) -> tuple[float | None, str]:
    """(ρ, relation_key) for two legs; (None, 'same_market') for unbuildable pairs."""
    if leg_a["market"] == leg_b["market"]:
        return None, "same_market"

    a, b = classify(leg_a), classify(leg_b)
    # canonical order so the table below covers each unordered pair once
    if a["kind"] > b["kind"]:
        a, b = b, a
    ka, kb = a["kind"], b["kind"]

    if (ka, kb) == ("ml", "spread"):
        key = "same_team_ml_spread" if a["entity"] == b["entity"] else "opp_team_ml_spread"
        return _lookup(lib, key), key
    if (ka, kb) == ("ml", "total"):
        return _lookup(lib, "ml_vs_total") * b["pol"], "ml_vs_total"
    if (ka, kb) == ("spread", "total"):
        return _lookup(lib, "spread_vs_total") * b["pol"], "spread_vs_total"
    if (ka, kb) == ("draw", "ml"):
        return _lookup(lib, "draw_vs_ml"), "draw_vs_ml"
    if (ka, kb) == ("draw", "spread"):
        return _lookup(lib, "draw_vs_spread"), "draw_vs_spread"
    if (ka, kb) == ("draw", "total"):
        return _lookup(lib, "draw_vs_total") * b["pol"], "draw_vs_total"
    if (ka, kb) == ("ml", "tt"):
        key = "tt_vs_same_ml" if a["entity"] == b["entity"] else "tt_vs_opp_ml"
        return _lookup(lib, key) * b["pol"], key
    if (ka, kb) == ("spread", "tt"):
        key = "tt_vs_same_spread" if a["entity"] == b["entity"] else "tt_vs_opp_spread"
        return _lookup(lib, key) * b["pol"], key
    if (ka, kb) == ("total", "tt"):
        return _lookup(lib, "tt_vs_total") * a["pol"] * b["pol"], "tt_vs_total"
    if (ka, kb) == ("tt", "tt"):
        return _lookup(lib, "tt_vs_tt") * a["pol"] * b["pol"], "tt_vs_tt"
    if (ka, kb) == ("btts", "total"):
        return _lookup(lib, "btts_vs_total") * a["pol"] * b["pol"], "btts_vs_total"
    if (ka, kb) == ("btts", "ml"):
        return _lookup(lib, "btts_vs_ml") * a["pol"], "btts_vs_ml"
    if (ka, kb) == ("btts", "spread"):
        return _lookup(lib, "btts_vs_spread") * a["pol"], "btts_vs_spread"
    if (ka, kb) == ("btts", "draw"):
        return _lookup(lib, "btts_vs_draw") * a["pol"], "btts_vs_draw"
    if (ka, kb) == ("btts", "tt"):
        return _lookup(lib, "btts_vs_tt") * a["pol"] * b["pol"], "btts_vs_tt"
    if (ka, kb) == ("draw", "tt"):
        # a draw neither requires nor forbids one team's scoring — near-zero prior
        return _lookup(lib, "default"), "default"

    return _lookup(lib, "default"), "default"
