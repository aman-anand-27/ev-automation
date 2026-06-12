"""Sharp SGP Finder orchestrator: resolve regions → legs → SGPs → dashboard.

One sport per run (credit discipline):
    ODDS_API_KEY=... python -m src.sgp_finder.main --sport mlb
    ODDS_CACHE_DIR=.odds_cache ... (replay cached responses, zero credits)
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .correlation import merged_library
from .fetch import OddsClient, resolve_and_fetch
from .legs import extract_legs, market_category
from .render import render
from .sgp import build_game_sgps

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_CFG_PATH = Path(__file__).parents[2] / "config" / "sgp.yaml"


def _commence(game: dict) -> datetime:
    return datetime.fromisoformat(game["commence_time"].replace("Z", "+00:00"))


def _points(bm: dict, category: str) -> set[float]:
    """Distinct |handicap| / total points the book prices for a category."""
    pts: set[float] = set()
    for mkt in bm.get("markets", []):
        if market_category(mkt["key"]) != category:
            continue
        for o in mkt["outcomes"]:
            if "point" in o:
                pts.add(round(abs(o["point"]), 2))
    return pts


def _needs_extras(game: dict, target_key: str, anchor_key: str) -> bool:
    """True when Pinnacle's featured lines don't cover every target line —
    its alternate-line pools could rescue otherwise-skipped legs."""
    bms = {bm["key"]: bm for bm in game.get("bookmakers", [])}
    target_bm = bms.get(target_key)
    anchor_bm = bms.get(anchor_key)
    if not target_bm:
        return False
    if not anchor_bm:
        return True
    for category in ("spreads", "totals"):
        t_pts = _points(target_bm, category)
        if t_pts and not t_pts.issubset(_points(anchor_bm, category)):
            return True
    return False


def _useful_extra_markets(cfg_markets: list[str], target_bm: dict) -> list[str]:
    """Extras worth credits: alternates extend markets the target prices;
    team_totals/btts only matter when the target itself offers them."""
    target_cats = {market_category(m["key"]) for m in target_bm.get("markets", [])}
    useful = []
    for m in cfg_markets:
        cat = market_category(m)
        if m in ("alternate_spreads", "alternate_totals"):
            if cat in target_cats:
                useful.append(m)
        elif m in target_cats:
            useful.append(m)
    return useful


def _merge_event_markets(game: dict, event_data: dict, region: str) -> None:
    """Fold per-event extras markets into the game's bookmaker entries."""
    bms = {bm["key"]: bm for bm in game.get("bookmakers", [])}
    for ebm in event_data.get("bookmakers", []):
        if ebm["key"] in bms:
            have = {m["key"] for m in bms[ebm["key"]].get("markets", [])}
            bms[ebm["key"]].setdefault("markets", []).extend(
                m for m in ebm.get("markets", []) if m["key"] not in have)
        else:
            ebm = dict(ebm)
            ebm["_region"] = region
            game["bookmakers"].append(ebm)


def fetch_extras(client: OddsClient, cfg: dict, sport_key: str, games: list[dict],
                 resolution: dict, window_hours: float, notes: list[str]) -> None:
    """Per-event extras for imminent events that benefit, under a credit cap."""
    ex_cfg = cfg["extras"]
    sport_section = "soccer" if sport_key.startswith("soccer_") else sport_key
    markets = ex_cfg["markets"].get(sport_section, [])
    if not (ex_cfg.get("enabled") and markets):
        return

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=window_hours)
    target_key = resolution["target_book"]
    anchor_key = cfg["sharp_books"]["anchor"]

    candidates = []
    for g in games:
        if not now < _commence(g) <= horizon:
            continue
        target_bm = next((b for b in g["bookmakers"] if b["key"] == target_key), None)
        if not target_bm:
            continue
        useful = _useful_extra_markets(markets, target_bm)
        if useful and _needs_extras(g, target_key, anchor_key):
            candidates.append((g, useful))

    if not candidates:
        notes.append("extras: no event within window needs alternate lines — skipped")
        logger.info(notes[-1])
        return

    per_event = max(len(u) for _, u in candidates)
    cap = ex_cfg["max_credits"]
    n_affordable = max(0, cap // per_event)
    picked = sorted(candidates, key=lambda c: _commence(c[0]))[:n_affordable]
    est = sum(len(u) for _, u in picked)
    notes.append(
        f"extras: {len(candidates)} candidate events in next {window_hours:g}h; "
        f"fetching {len(picked)} × ≤{per_event} markets × 1 region ≈ {est} credits "
        f"(cap {cap})")
    logger.info(notes[-1])

    for g, useful in picked:
        data = client.event_extras(sport_key, g["id"], ex_cfg["region"], useful)
        if data:
            _merge_event_markets(g, data, ex_cfg["region"])


def run(sport_alias: str, sport_key: str, window_hours: float, extras: str,
        cfg: dict) -> dict:
    client = OddsClient(cfg)
    resolution = resolve_and_fetch(client, cfg, sport_key)
    notes: list[str] = []

    notes.append(
        f"target book: {resolution['target_label']} ({resolution['target_book']}) "
        f"from region(s) {','.join(resolution['target_regions'])}"
        + (" — PROXY: bet365 does not return on the free key"
           if resolution["target_is_proxy"] else ""))
    notes.append("sharp anchors: " + ", ".join(
        f"{b}({','.join(r)})" for b, r in resolution["anchors"].items()))
    notes.append(f"regions scanned: {','.join(resolution['regions_scanned'])}")
    for n in notes:
        logger.info(n)

    now = datetime.now(timezone.utc)
    games = [g for g in resolution["games"] if _commence(g) > now]
    skipped_live = len(resolution["games"]) - len(games)
    if skipped_live:
        notes.append(f"skipped {skipped_live} in-progress game(s)")

    if extras == "auto":
        fetch_extras(client, cfg, sport_key, games, resolution, window_hours, notes)
    else:
        notes.append("extras: disabled by --extras off")

    lib = merged_library(cfg["correlation"], sport_key)
    game_blocks = []
    total_sgps = 0
    for g in sorted(games, key=_commence):
        legs = extract_legs(g, resolution, cfg)
        if len(legs) < cfg["sgp"]["legs_per_sgp"]:
            continue
        sgps = build_game_sgps(legs, lib, cfg["sgp"])
        if not sgps:
            continue
        total_sgps += len(sgps)
        game_blocks.append({
            "id": g["id"],
            "game": f"{g['away_team']} @ {g['home_team']}"
            if not sport_key.startswith("soccer_")
            else f"{g['home_team']} vs {g['away_team']}",
            "commence_time": g["commence_time"],
            "n_candidate_legs": len(legs),
            "sgps": sgps,
        })

    # Global cap: keep the best break-even boosts across the slate
    max_total = cfg["sgp"].get("max_total")
    if max_total and total_sgps > max_total:
        flat = [(blk, s) for blk in game_blocks for s in blk["sgps"]]
        flat.sort(key=lambda t: (t[1]["break_even_boost"] is None,
                                 t[1]["break_even_boost"] or 0))
        keep = {id(s) for _, s in flat[:max_total]}
        for blk in game_blocks:
            blk["sgps"] = [s for s in blk["sgps"] if id(s) in keep]
        game_blocks = [blk for blk in game_blocks if blk["sgps"]]
        notes.append(f"capped output to best {max_total} of {total_sgps} SGPs")
        total_sgps = max_total

    notes.append(f"credits: ≈{client.credits_spent_est} spent this run; "
                 f"remaining={client.last_remaining or 'n/a (cache replay)'}")
    logger.info(notes[-1])

    return {
        "sport_key": sport_key,
        "sport_title": (resolution["games"][0]["sport_title"]
                        if resolution["games"] else sport_alias.upper()),
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "target_book": resolution["target_book"],
        "target_label": resolution["target_label"],
        "target_is_proxy": resolution["target_is_proxy"],
        "target_regions": resolution["target_regions"],
        "anchors": resolution["anchors"],
        "regions_scanned": resolution["regions_scanned"],
        "devig_method": cfg["devig"]["method"],
        "boost_defaults": cfg["boost"],
        "credits_est": client.credits_spent_est,
        "notes": notes,
        "games": game_blocks,
        "n_sgps": total_sgps,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Sharp SGP Finder (free-tier)")
    ap.add_argument("--sport", choices=["mlb", "nba", "soccer"],
                    help="one sport per run (credit discipline)")
    ap.add_argument("--sport-key", help="override the Odds API sport key "
                                        "(e.g. soccer_usa_mls)")
    ap.add_argument("--window-hours", type=float, default=None,
                    help="extras only for events starting within this window "
                         "(default from config: extras.window_hours)")
    ap.add_argument("--extras", choices=["auto", "off"], default="auto",
                    help="per-event alternate-line fetching (default auto, capped)")
    args = ap.parse_args()

    with open(_CFG_PATH) as f:
        cfg = yaml.safe_load(f)

    if not args.sport and not args.sport_key:
        ap.error("--sport (or --sport-key) is required")
    sport_alias = args.sport or "custom"
    sport_key = args.sport_key or cfg["sports"][args.sport]
    window = args.window_hours if args.window_hours is not None \
        else cfg["extras"]["window_hours"]

    block = run(sport_alias, sport_key, window, args.extras, cfg)
    render(sport_alias, block, cfg)


if __name__ == "__main__":
    main()
