"""Candidate legs: target-book outcomes priced against sharp fair probabilities.

A leg is one target-book outcome (e.g. 888sport "Pirates -1.5 @ 2.40") whose
EXACT line the sharp side also prices. Fair probability comes from de-vigging
the sharp anchor's full market at that line (Pinnacle first; exchange-consensus
median as fallback). Handicaps must match exactly — a -1.5 target line against
a -1.0 sharp line is a different bet and is skipped. Pinnacle's alternate
lines (per-event extras) are merged into its spreads/totals pools so target
main lines can still match when the sharp main line moved.
"""

from __future__ import annotations

from statistics import median

from .devig import decimal_to_american, devig, implied

# Markets a leg may come from (target side). Alternates are pools, not legs.
LEG_MARKETS = ["h2h", "spreads", "totals", "team_totals", "btts"]

# Alternate markets fold into the featured category they extend — for line
# matching AND for the 3-distinct-markets rule.
MARKET_CATEGORY = {
    "alternate_spreads": "spreads",
    "alternate_totals": "totals",
}


def market_category(market_key: str) -> str:
    return MARKET_CATEGORY.get(market_key, market_key)


def _pool(bookmaker: dict, category: str) -> list[dict]:
    """All outcomes of a market category, with alternates merged and deduped."""
    seen: set[tuple] = set()
    pool: list[dict] = []
    for mkt in bookmaker.get("markets", []):
        if market_category(mkt["key"]) != category:
            continue
        for o in mkt["outcomes"]:
            ident = (o["name"], o.get("description"), round(o.get("point", 0.0), 2))
            if ident not in seen:
                seen.add(ident)
                pool.append(o)
    return pool


def _same_outcome(o: dict, ref: dict) -> bool:
    return (
        o["name"] == ref["name"]
        and o.get("description") == ref.get("description")
        and abs(o.get("point", 0.0) - ref.get("point", 0.0)) < 0.01
    )


def market_group(pool: list[dict], leg_outcome: dict, category: str) -> list[dict] | None:
    """The full set of outcomes forming the (sub-)market that contains the leg.

    De-vig needs every side of the market at the leg's exact line:
      h2h        → all outcomes (2-way, or 3-way for soccer 1X2);
      spreads    → leg side + opposing team at the FLIPPED handicap;
      totals     → Over and Under at the SAME point;
      team_totals→ Over/Under at same point for the SAME team (description);
      btts       → Yes and No.
    Returns None when any side is missing (line not fully priced — skip).
    """
    mine = next((o for o in pool if _same_outcome(o, leg_outcome)), None)
    if mine is None:
        return None

    if category == "h2h":
        group = pool
        return group if len(group) >= 2 else None

    if category == "spreads":
        target_point = -leg_outcome.get("point", 0.0)
        opp = next(
            (o for o in pool
             if o["name"] != leg_outcome["name"]
             and abs(o.get("point", 0.0) - target_point) < 0.01),
            None)
        return [mine, opp] if opp else None

    if category == "totals":
        other_name = "Under" if leg_outcome["name"] == "Over" else "Over"
        opp = next(
            (o for o in pool
             if o["name"] == other_name
             and abs(o.get("point", 0.0) - leg_outcome.get("point", 0.0)) < 0.01),
            None)
        return [mine, opp] if opp else None

    if category == "team_totals":
        other_name = "Under" if leg_outcome["name"] == "Over" else "Over"
        opp = next(
            (o for o in pool
             if o["name"] == other_name
             and o.get("description") == leg_outcome.get("description")
             and abs(o.get("point", 0.0) - leg_outcome.get("point", 0.0)) < 0.01),
            None)
        return [mine, opp] if opp else None

    if category == "btts":
        other_name = "No" if leg_outcome["name"] == "Yes" else "Yes"
        opp = next((o for o in pool if o["name"] == other_name), None)
        return [mine, opp] if opp else None

    return None


def sharp_fair(leg_outcome: dict, category: str, sharp_bms: list[dict],
               anchor_key: str, devig_method: str) -> tuple[float, str] | None:
    """Fair probability of the leg from the sharp side.

    Pinnacle (anchor) first: de-vig its full market at the leg's line.
    Fallback: per-exchange de-vig at the line, median across exchanges.
    Returns (p_fair, source) or None when no sharp book prices the line.
    """
    by_key = {bm["key"]: bm for bm in sharp_bms}

    anchor = by_key.get(anchor_key)
    if anchor:
        group = market_group(_pool(anchor, category), leg_outcome, category)
        if group:
            probs = devig([o["price"] for o in group], devig_method)
            idx = next(i for i, o in enumerate(group) if _same_outcome(o, leg_outcome))
            return probs[idx], anchor_key

    fallback: list[float] = []
    used: list[str] = []
    for bm in sharp_bms:
        if bm["key"] == anchor_key:
            continue
        group = market_group(_pool(bm, category), leg_outcome, category)
        if group:
            probs = devig([o["price"] for o in group], devig_method)
            idx = next(i for i, o in enumerate(group) if _same_outcome(o, leg_outcome))
            fallback.append(probs[idx])
            used.append(bm["key"])
    if fallback:
        return median(fallback), f"exchange_consensus({','.join(used)})"
    return None


def leg_label(outcome: dict, category: str) -> str:
    if category == "h2h":
        return outcome["name"] if outcome["name"] == "Draw" else f"{outcome['name']} ML"
    if category == "spreads":
        return f"{outcome['name']} {outcome.get('point', 0.0):+g}"
    if category == "totals":
        return f"{outcome['name']} {outcome.get('point', 0.0):g}"
    if category == "team_totals":
        return (f"{outcome.get('description', '?')} TT "
                f"{outcome['name']} {outcome.get('point', 0.0):g}")
    if category == "btts":
        return f"BTTS {outcome['name']}"
    return outcome["name"]


def extract_legs(game: dict, resolution: dict, cfg: dict) -> list[dict]:
    """All qualifying candidate legs for one game, best leg-EV first, top-K capped."""
    target_key = resolution["target_book"]
    sharp_keys = {cfg["sharp_books"]["anchor"], *cfg["sharp_books"]["exchanges"]}
    devig_method = cfg["devig"]["method"]
    min_ev = cfg["legs"]["min_leg_ev"]
    top_k = cfg["legs"]["top_k_per_game"]

    bms = game.get("bookmakers", [])
    target_bm = next((bm for bm in bms if bm["key"] == target_key), None)
    sharp_bms = [bm for bm in bms if bm["key"] in sharp_keys]
    if not target_bm or not sharp_bms:
        return []

    legs: list[dict] = []
    target_categories = {market_category(m["key"]) for m in target_bm.get("markets", [])}
    for category in [c for c in LEG_MARKETS if c in target_categories]:
        for outcome in _pool(target_bm, category):
            fair = sharp_fair(outcome, category, sharp_bms,
                              cfg["sharp_books"]["anchor"], devig_method)
            if fair is None:
                continue  # sharp side doesn't price this exact line
            p_fair, source = fair
            price = outcome["price"]
            if price <= 1.0:
                continue  # suspended/degenerate
            ev_leg = p_fair * (price - 1.0) - (1.0 - p_fair)
            if ev_leg < min_ev:
                continue
            legs.append({
                "market": category,
                "label": leg_label(outcome, category),
                "name": outcome["name"],
                "point": outcome.get("point"),
                "team": outcome.get("description")
                if category == "team_totals"
                else (outcome["name"] if category in ("h2h", "spreads")
                      and outcome["name"] != "Draw" else None),
                "target_price": price,
                "target_american": decimal_to_american(price),
                "target_implied": round(implied(price), 5),
                "fair_p": round(p_fair, 5),
                "fair_decimal": round(1.0 / p_fair, 4),
                "fair_american": decimal_to_american(1.0 / p_fair),
                "fair_source": source,
                "ev": round(ev_leg, 5),
            })

    legs.sort(key=lambda l: l["ev"], reverse=True)
    return legs[:top_k]
