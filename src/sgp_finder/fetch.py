"""Fetch with region fallback for the SGP finder.

Strategy (credit discipline): scan regions in cfg's scan_order, one featured
call per region (markets × 1 region credits each), stopping as soon as a
qualifying target book AND a sharp anchor have both turned up. Events from all
scanned regions are merged by event id, each bookmaker tagged with the region
it resolved from. Per-event "extras" (alternate lines, team totals, BTTS) are
fetched only for imminent events that benefit, under a hard credit cap, with
the estimate printed first.

ODDS_CACHE_DIR replay: every GET is cached on disk by (path, params) so local
development burns zero credits after the first run.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

_BASE = "https://api.the-odds-api.com/v4"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(requests.RequestException),
    reraise=True,
)
def _get(url: str, params: dict) -> requests.Response:
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp


def cache_key(path: str, params: dict) -> str:
    """Stable cache key over endpoint path + params (apiKey excluded)."""
    raw = path + str(sorted((k, v) for k, v in params.items() if k != "apiKey"))
    return hashlib.md5(raw.encode()).hexdigest()


class OddsClient:
    """Thin Odds API client with disk-cache replay and credit accounting."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.odds_format = cfg["odds_api"].get("oddsFormat", "decimal")
        cache_env = os.getenv("ODDS_CACHE_DIR")
        self.cache_dir = Path(cache_env) if cache_env else None
        self.credits_spent_est = 0
        self.last_remaining: str | None = None

    def _request(self, path: str, params: dict, est_cost: int) -> object:
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            fp = self.cache_dir / f"{cache_key(path, params)}.json"
            if fp.exists():
                logger.info("[cache] %s %s", path, params.get("regions", ""))
                return json.loads(fp.read_text())

        api_key = os.environ.get("ODDS_API_KEY")
        if not api_key:
            raise RuntimeError(
                f"ODDS_API_KEY not set and {path} not in ODDS_CACHE_DIR — "
                "cannot fetch")
        full = dict(params)
        full["apiKey"] = api_key
        resp = _get(f"{_BASE}{path}", full)
        data = resp.json()
        self.credits_spent_est += est_cost
        self.last_remaining = resp.headers.get("x-requests-remaining", self.last_remaining)

        if self.cache_dir:
            fp.write_text(json.dumps(data))
        return data

    def featured_odds(self, sport_key: str, region: str, markets: list[str]) -> list[dict]:
        """One region's featured odds — costs len(markets) × 1 credits."""
        params = {
            "regions": region,
            "markets": ",".join(markets),
            "oddsFormat": self.odds_format,
        }
        data = self._request(f"/sports/{sport_key}/odds", params, est_cost=len(markets))
        return data if isinstance(data, list) else []

    def event_extras(self, sport_key: str, event_id: str, region: str,
                     markets: list[str]) -> dict | None:
        """Per-event additional markets — costs ≤ len(markets) × 1 credits."""
        params = {
            "regions": region,
            "markets": ",".join(markets),
            "oddsFormat": self.odds_format,
        }
        try:
            data = self._request(f"/sports/{sport_key}/events/{event_id}/odds",
                                 params, est_cost=len(markets))
        except requests.HTTPError as e:
            logger.warning("extras fetch failed for %s: HTTP %s", event_id,
                           e.response.status_code if e.response is not None else "?")
            return None
        except RuntimeError as e:
            # extras are an enhancement — replay without a key degrades gracefully
            logger.warning("extras skipped for %s: %s", event_id, e)
            return None
        return data if isinstance(data, dict) else None


# ── Region fallback / target resolution (pure logic, unit-testable) ─────────

def book_market_coverage(games_by_region: dict[str, list[dict]]) -> dict[str, dict]:
    """{book_key: {"regions": [..], "markets": set()}} across scanned regions."""
    cov: dict[str, dict] = {}
    for region, games in games_by_region.items():
        for g in games:
            for bm in g.get("bookmakers", []):
                entry = cov.setdefault(bm["key"], {"regions": [], "markets": set()})
                if region not in entry["regions"]:
                    entry["regions"].append(region)
                entry["markets"].update(m["key"] for m in bm.get("markets", []))
    return cov


def select_target_book(coverage: dict[str, dict], priority: list[str],
                       featured: list[str], min_distinct: int) -> str | None:
    """First priority book whose returned featured markets allow a 3-distinct-market SGP."""
    for book in priority:
        entry = coverage.get(book)
        if entry and len(entry["markets"] & set(featured)) >= min_distinct:
            return book
    return None


def anchors_present(coverage: dict[str, dict], sharp_cfg: dict) -> dict[str, list[str]]:
    """{sharp_book: regions} for every configured anchor/exchange that returned."""
    out: dict[str, list[str]] = {}
    for book in [sharp_cfg["anchor"], *sharp_cfg["exchanges"]]:
        if book in coverage:
            out[book] = coverage[book]["regions"]
    return out


def merge_regions(games_by_region: dict[str, list[dict]], scan_order: list[str]) -> list[dict]:
    """Merge per-region event lists by event id; tag bookmakers with _region.

    A book serving multiple regions keeps its first-scanned region's prices
    (scan_order is the precedence).
    """
    merged: dict[str, dict] = {}
    for region in scan_order:
        for g in games_by_region.get(region, []):
            tagged = []
            for bm in g.get("bookmakers", []):
                bm = dict(bm)
                bm["_region"] = region
                tagged.append(bm)
            if g["id"] not in merged:
                g = dict(g)
                g["bookmakers"] = tagged
                merged[g["id"]] = g
            else:
                have = {bm["key"] for bm in merged[g["id"]]["bookmakers"]}
                merged[g["id"]]["bookmakers"].extend(
                    bm for bm in tagged if bm["key"] not in have)
    return list(merged.values())


def resolve_and_fetch(client: OddsClient | object, cfg: dict, sport_key: str) -> dict:
    """Scan regions per cfg until target book + sharp anchor are both covered.

    `client` only needs .featured_odds(sport_key, region, markets) — tests
    inject a fake. Returns a resolution dict; raises RuntimeError when no
    target or no anchor can be found in any region.
    """
    featured = cfg["featured_markets"]
    tb_cfg = cfg["target_books"]
    sharp_cfg = cfg["sharp_books"]
    scan_order = cfg["regions"]["scan_order"]
    require = cfg["regions"].get("require_target")

    games_by_region: dict[str, list[dict]] = {}
    scanned: list[str] = []
    target = None
    anchors: dict[str, list[str]] = {}

    for region in scan_order:
        games_by_region[region] = client.featured_odds(sport_key, region, featured)
        scanned.append(region)
        coverage = book_market_coverage(games_by_region)
        target = select_target_book(coverage, tb_cfg["priority"], featured,
                                    tb_cfg["min_distinct_markets"])
        anchors = anchors_present(coverage, sharp_cfg)
        target_ok = target is not None and (require is None or target == require)
        if target_ok and anchors:
            break

    if target is None:
        raise RuntimeError(
            f"no target book with ≥{tb_cfg['min_distinct_markets']} featured markets "
            f"found in regions {scanned} (priority {tb_cfg['priority']})")
    if not anchors:
        raise RuntimeError(f"no sharp anchor found in regions {scanned} — cannot "
                           f"compute fair value (anchors: {sharp_cfg['anchor']}, "
                           f"{sharp_cfg['exchanges']})")
    if require and target != require:
        logger.warning("require_target=%s never qualified in %s; using %s",
                       require, scanned, target)

    coverage = book_market_coverage(games_by_region)
    return {
        "games": merge_regions(games_by_region, scan_order),
        "target_book": target,
        "target_label": tb_cfg["labels"].get(target, target),
        "target_regions": coverage[target]["regions"],
        "target_is_proxy": target != tb_cfg["priority"][0],
        "anchors": anchors,
        "regions_scanned": scanned,
        "book_regions": {b: e["regions"] for b, e in coverage.items()},
    }
