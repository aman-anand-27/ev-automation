"""Hold math: pair DK vs Novig outcomes, compute consensus implied prob and Novig rank."""

from datetime import datetime, timezone
from statistics import median
from typing import Optional


def decimal_to_american(decimal: float) -> str:
    """Convert decimal odds to American odds string (+110, -150, etc.)."""
    if decimal >= 2.0:
        return f"+{round((decimal - 1) * 100)}"
    return str(round(-100.0 / (decimal - 1)))


def compute_hold(dk_price: float, novig_price: float) -> float:
    """Two-way hold %: (1/dk + 1/novig − 1) × 100."""
    return (1.0 / dk_price + 1.0 / novig_price - 1.0) * 100.0


def _same_side(outcome: dict, ref: dict, market_key: str) -> bool:
    """Return True if outcome is on the same side/line as ref."""
    if market_key == "h2h":
        return outcome["name"] == ref["name"]
    # spreads and totals must match both name and point
    return outcome["name"] == ref["name"] and abs(
        outcome.get("point", 0.0) - ref.get("point", 0.0)
    ) < 0.01


def _find_opposing(
    dk_outcome: dict, novig_outcomes: list[dict], market_key: str
) -> Optional[dict]:
    """Find the Novig outcome on the opposite side from dk_outcome.

    Spreads: DK TeamA -1.5 must pair with Novig TeamB +1.5 (exact flip).
    Totals: DK Over 8.5 must pair with Novig Under 8.5 (same point, opposite label).
    Cross-handicap pairs are silently skipped — they are different bets.
    """
    if market_key == "h2h":
        for o in novig_outcomes:
            if o["name"] != dk_outcome["name"]:
                return o
        return None

    if market_key == "spreads":
        target_point = -dk_outcome.get("point", 0.0)
        for o in novig_outcomes:
            if o["name"] != dk_outcome["name"] and abs(o.get("point", 0.0) - target_point) < 0.01:
                return o
        return None

    if market_key == "totals":
        target_name = "Under" if dk_outcome["name"] == "Over" else "Over"
        target_point = dk_outcome.get("point", 0.0)
        for o in novig_outcomes:
            if o["name"] == target_name and abs(o.get("point", 0.0) - target_point) < 0.01:
                return o
        return None

    return None


def _side_label(outcome: dict, market_key: str) -> str:
    if market_key == "h2h":
        return outcome["name"]
    if market_key == "spreads":
        p = outcome.get("point", 0.0)
        return f"{outcome['name']} {p:+.1f}"
    if market_key == "totals":
        p = outcome.get("point", 0.0)
        return f"{outcome['name']} {p}"
    return outcome["name"]


def _consensus_details(
    bookmakers: list[dict],
    dk_side: dict,
    market_key: str,
    exclude_keys: set,
) -> list[dict]:
    """Return per-book price details for all available consensus books on DK's side.

    Each entry: {book, price_dec, american, implied_pct}
    """
    details: list[dict] = []
    for bm in bookmakers:
        if bm["key"] in exclude_keys:
            continue
        for mkt in bm.get("markets", []):
            if mkt["key"] != market_key:
                continue
            for o in mkt["outcomes"]:
                if _same_side(o, dk_side, market_key):
                    details.append({
                        "book": bm["key"],
                        "price_dec": o["price"],
                        "american": decimal_to_american(o["price"]),
                        "implied_pct": round(1.0 / o["price"] * 100.0, 3),
                    })
                    break
    return details


def _novig_rank(
    bookmakers: list[dict],
    novig_opp: dict,
    market_key: str,
    exchange_key: str,
) -> int:
    """Rank Novig on the opposing side vs all other books (1 = best = highest price)."""
    other_prices: list[float] = []
    for bm in bookmakers:
        if bm["key"] == exchange_key:
            continue
        for mkt in bm.get("markets", []):
            if mkt["key"] != market_key:
                continue
            for o in mkt["outcomes"]:
                if _same_side(o, novig_opp, market_key):
                    other_prices.append(o["price"])
                    break
    novig_price = novig_opp["price"]
    return 1 + sum(1 for p in other_prices if p > novig_price)


def _is_live(game: dict) -> bool:
    """Return True if the game is currently in-progress."""
    if game.get("in_progress"):
        return True
    try:
        commence = datetime.fromisoformat(game["commence_time"].replace("Z", "+00:00"))
        return commence < datetime.now(timezone.utc)
    except Exception:
        return False


def compute_rows(games: list[dict], cfg: dict) -> list[dict]:
    """Build all DK×Novig market pairs with hold math, consensus, and Novig rank.

    Returns rows sorted by hold ascending. Each row has qualified=False and
    disqualify_reasons=[] — these are filled in by qualify.py.
    """
    primary = cfg["target_books"]["primary"]
    exchange = cfg["target_books"]["exchange"]
    exclude_keys = {primary, exchange}
    min_books = cfg["thresholds"]["min_books_for_consensus"]
    sharp_keys = set(cfg.get("sharp_books", []))
    rows: list[dict] = []

    for game in games:
        bookmakers = game.get("bookmakers", [])
        bm_by_key = {bm["key"]: bm for bm in bookmakers}

        dk_bm = bm_by_key.get(primary)
        novig_bm = bm_by_key.get(exchange)
        if not dk_bm or not novig_bm:
            continue

        dk_mkts = {m["key"]: m for m in dk_bm.get("markets", [])}
        novig_mkts = {m["key"]: m for m in novig_bm.get("markets", [])}
        is_live = _is_live(game)

        for market_key in cfg.get("markets", []):
            dk_mkt = dk_mkts.get(market_key)
            novig_mkt = novig_mkts.get(market_key)
            if not dk_mkt or not novig_mkt:
                continue

            dk_outcomes = dk_mkt["outcomes"]
            novig_outcomes = novig_mkt["outcomes"]

            # 3-way h2h markets (e.g. soccer) don't form clean two-sided round-trips
            if market_key == "h2h" and len(dk_outcomes) != 2:
                continue

            for dk_out in dk_outcomes:
                novig_opp = _find_opposing(dk_out, novig_outcomes, market_key)
                if not novig_opp:
                    continue

                dk_price = dk_out["price"]
                novig_price = novig_opp["price"]
                hold_pct = compute_hold(dk_price, novig_price)
                dk_impl_pct = 1.0 / dk_price * 100.0

                # Per-book consensus details (all books except DK & Novig)
                all_details = _consensus_details(
                    bookmakers, dk_out, market_key, exclude_keys
                )
                book_count = len(all_details)

                # Overall consensus (median across all available books)
                if book_count >= min_books:
                    consensus_impl_pct = median(d["implied_pct"] for d in all_details)
                    consensus_american = decimal_to_american(100.0 / consensus_impl_pct)
                else:
                    consensus_impl_pct = None
                    consensus_american = None

                # Sharp-book consensus (median across sharp books only)
                sharp_details = [d for d in all_details if d["book"] in sharp_keys]
                if sharp_details:
                    sharp_impl_pct = median(d["implied_pct"] for d in sharp_details)
                    sharp_american = decimal_to_american(100.0 / sharp_impl_pct)
                else:
                    sharp_american = None

                # Tooltip: each book and its American odds, one per line
                consensus_tooltip = "\n".join(
                    f"{d['book']}: {d['american']}" for d in all_details
                )

                rank = _novig_rank(bookmakers, novig_opp, market_key, exchange)

                rows.append({
                    "game_id": game["id"],
                    "sport": game["sport_title"],
                    "game": f"{game['away_team']} @ {game['home_team']}",
                    "commence_time": game["commence_time"],
                    "market": market_key,
                    "side": _side_label(dk_out, market_key),
                    "dk_price": dk_price,
                    "novig_price": novig_price,
                    "dk_american": decimal_to_american(dk_price),
                    "novig_american": decimal_to_american(novig_price),
                    "consensus_american": consensus_american,
                    "sharp_american": sharp_american,
                    "consensus_tooltip": consensus_tooltip,
                    "hold_pct": round(hold_pct, 3),
                    "dk_implied_pct": round(dk_impl_pct, 3),
                    "consensus_implied_pct": round(consensus_impl_pct, 3)
                    if consensus_impl_pct is not None
                    else None,
                    "consensus_book_count": book_count,
                    "novig_rank": rank,
                    "is_live": is_live,
                    "qualified": False,
                    "disqualify_reasons": [],
                })

    rows.sort(key=lambda r: r["hold_pct"])
    return rows
