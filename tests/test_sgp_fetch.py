"""Region-fallback selection tests (fake client, no network)."""

import pytest

from src.sgp_finder.fetch import (
    anchors_present,
    book_market_coverage,
    merge_regions,
    resolve_and_fetch,
    select_target_book,
)

FEATURED = ["h2h", "spreads", "totals"]


def _game(gid, books_markets, home="H", away="A"):
    return {
        "id": gid, "sport_title": "MLB", "commence_time": "2099-01-01T00:00:00Z",
        "home_team": home, "away_team": away,
        "bookmakers": [
            {"key": k, "markets": [
                {"key": m, "outcomes": [{"name": "x", "price": 2.0}]}
                for m in mkts]}
            for k, mkts in books_markets.items()
        ],
    }


class FakeClient:
    """Region → games map; records which regions were fetched."""

    def __init__(self, by_region):
        self.by_region = by_region
        self.fetched = []

    def featured_odds(self, sport_key, region, markets):
        self.fetched.append(region)
        return self.by_region.get(region, [])


def _cfg(scan_order=("eu", "uk", "au"), require=None,
         priority=("bet365", "sport888")):
    return {
        "featured_markets": FEATURED,
        "target_books": {
            "priority": list(priority),
            "labels": {k: k for k in priority},
            "min_distinct_markets": 3,
            "region_priority": {"default": ["eu", "uk"]},
        },
        "sharp_books": {"anchor": "pinnacle",
                        "exchanges": ["matchbook", "betfair_ex_uk"]},
        "regions": {"scan_order": list(scan_order), "require_target": require},
    }


FULL = {"h2h", "spreads", "totals"}


def test_early_stop_when_eu_covers_everything():
    client = FakeClient({
        "eu": [_game("g1", {"sport888": FULL, "pinnacle": FULL})],
        "uk": [_game("g1", {"bet365": FULL})],  # never reached
    })
    res = resolve_and_fetch(client, _cfg(), "baseball_mlb")
    assert client.fetched == ["eu"]              # stopped after one region
    assert res["target_book"] == "sport888"
    assert res["target_is_proxy"] is True        # bet365 was priority #1
    assert res["anchors"] == {"pinnacle": ["eu"]}
    assert res["regions_scanned"] == ["eu"]


def test_priority_book_wins_when_present():
    client = FakeClient({
        "eu": [_game("g1", {"bet365": FULL, "sport888": FULL, "pinnacle": FULL})],
    })
    res = resolve_and_fetch(client, _cfg(), "baseball_mlb")
    assert res["target_book"] == "bet365"
    assert res["target_is_proxy"] is False


def test_widens_until_anchor_found():
    client = FakeClient({
        "eu": [_game("g1", {"sport888": FULL})],          # no anchor yet
        "uk": [_game("g1", {"matchbook": FULL})],         # exchange anchor
    })
    res = resolve_and_fetch(client, _cfg(), "baseball_mlb")
    assert client.fetched == ["eu", "uk"]
    assert res["anchors"] == {"matchbook": ["uk"]}


def test_book_with_too_few_markets_not_target():
    # sport888 returns h2h only (soccer case) → falls through to next priority
    client = FakeClient({
        "eu": [_game("g1", {"sport888": {"h2h"}, "betonlineag": FULL,
                            "pinnacle": FULL})],
    })
    cfg = _cfg(priority=("bet365", "sport888", "betonlineag"))
    res = resolve_and_fetch(client, cfg, "soccer_fifa_world_cup")
    assert res["target_book"] == "betonlineag"


def test_require_target_keeps_scanning():
    client = FakeClient({
        "eu": [_game("g1", {"sport888": FULL, "pinnacle": FULL})],
        "uk": [_game("g1", {"bet365": FULL})],
        "au": [],
    })
    res = resolve_and_fetch(client, _cfg(require="bet365"), "baseball_mlb")
    assert client.fetched == ["eu", "uk"]        # kept going past sport888
    assert res["target_book"] == "bet365"
    assert res["book_regions"]["bet365"] == ["uk"]


def test_require_target_falls_back_when_never_found():
    client = FakeClient({
        "eu": [_game("g1", {"sport888": FULL, "pinnacle": FULL})],
        "uk": [], "au": [],
    })
    res = resolve_and_fetch(client, _cfg(require="bet365"), "baseball_mlb")
    assert res["regions_scanned"] == ["eu", "uk", "au"]  # exhausted the scan
    assert res["target_book"] == "sport888"              # best available fallback


def test_no_target_anywhere_raises():
    client = FakeClient({"eu": [], "uk": [], "au": []})
    with pytest.raises(RuntimeError, match="no target book"):
        resolve_and_fetch(client, _cfg(), "baseball_mlb")


def test_no_anchor_anywhere_raises():
    client = FakeClient({
        "eu": [_game("g1", {"sport888": FULL})],
        "uk": [], "au": [],
    })
    with pytest.raises(RuntimeError, match="no sharp anchor"):
        resolve_and_fetch(client, _cfg(), "baseball_mlb")


def test_merge_regions_tags_and_dedups():
    games_by_region = {
        "eu": [_game("g1", {"pinnacle": FULL, "matchbook": {"h2h"}})],
        "uk": [_game("g1", {"matchbook": FULL, "bet365": FULL}),
               _game("g2", {"bet365": FULL})],
    }
    merged = merge_regions(games_by_region, ["eu", "uk", "au"])
    by_id = {g["id"]: g for g in merged}
    assert set(by_id) == {"g1", "g2"}
    g1_books = {bm["key"]: bm for bm in by_id["g1"]["bookmakers"]}
    # matchbook present in both regions → first scanned region (eu) wins
    assert g1_books["matchbook"]["_region"] == "eu"
    assert g1_books["bet365"]["_region"] == "uk"


def test_coverage_and_selection_helpers():
    games_by_region = {
        "eu": [_game("g1", {"pinnacle": FULL, "sport888": {"h2h", "spreads"}})]}
    cov = book_market_coverage(games_by_region)
    assert cov["pinnacle"]["markets"] == FULL
    assert select_target_book(cov, ["sport888"], FEATURED, 3) is None
    assert select_target_book(cov, ["sport888"], FEATURED, 2) == "sport888"
    anchors = anchors_present(cov, {"anchor": "pinnacle", "exchanges": ["matchbook"]})
    assert anchors == {"pinnacle": ["eu"]}
