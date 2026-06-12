"""Seed ODDS_CACHE_DIR from probe_results/ so the SGP pipeline replays locally
with ZERO credits.

The probe fetched h2h and spreads/totals as separate calls; the pipeline makes
one combined featured call per region. This script merges the probe responses
into the exact cache entries the pipeline will look for (featured per region,
plus the one probed per-event extras response filtered to the market subsets
the pipeline requests).

Usage: python3 scripts/seed_cache_from_probe.py [probe_dir] [cache_dir]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from src.sgp_finder.fetch import cache_key  # noqa: E402

FEATURED = "h2h,spreads,totals"
SPORTS = ["baseball_mlb", "basketball_nba", "soccer_fifa_world_cup"]
# market subsets the pipeline's _useful_extra_markets can request, per sport
EXTRA_SUBSETS = {
    "baseball_mlb": ["alternate_spreads,alternate_totals"],
    "basketball_nba": ["alternate_spreads,alternate_totals"],
    "soccer_fifa_world_cup": ["alternate_totals,alternate_spreads"],
}


def merge_games(*game_lists: list) -> list:
    by_id: dict[str, dict] = {}
    for games in game_lists:
        for g in games:
            if g["id"] not in by_id:
                by_id[g["id"]] = json.loads(json.dumps(g))
                continue
            tgt = by_id[g["id"]]
            books = {bm["key"]: bm for bm in tgt["bookmakers"]}
            for bm in g.get("bookmakers", []):
                if bm["key"] in books:
                    have = {m["key"] for m in books[bm["key"]]["markets"]}
                    books[bm["key"]]["markets"].extend(
                        m for m in bm.get("markets", []) if m["key"] not in have)
                else:
                    tgt["bookmakers"].append(bm)
    return list(by_id.values())


def main() -> None:
    probe = Path(sys.argv[1] if len(sys.argv) > 1 else "probe_results")
    cache = Path(sys.argv[2] if len(sys.argv) > 2 else ".odds_cache")
    cache.mkdir(parents=True, exist_ok=True)
    raw = probe / "raw"
    n = 0

    for sport in SPORTS:
        h2h_fp = raw / f"{sport}__eu__h2h.json"
        st_fp = raw / f"{sport}__eu__spreads-totals.json"
        if not (h2h_fp.exists() and st_fp.exists()):
            print(f"skip {sport}: probe files missing")
            continue
        merged = merge_games(json.loads(h2h_fp.read_text()),
                             json.loads(st_fp.read_text()))
        params = {"regions": "eu", "markets": FEATURED, "oddsFormat": "decimal"}
        key = cache_key(f"/sports/{sport}/odds", params)
        (cache / f"{key}.json").write_text(json.dumps(merged))
        print(f"seeded featured eu for {sport}: {len(merged)} games → {key}")
        n += 1

        extras_fp = raw / f"{sport}__event__extras.json"
        if extras_fp.exists():
            ev = json.loads(extras_fp.read_text())
            for subset in EXTRA_SUBSETS.get(sport, []):
                wanted = set(subset.split(","))
                filt = json.loads(json.dumps(ev))
                for bm in filt.get("bookmakers", []):
                    bm["markets"] = [m for m in bm["markets"] if m["key"] in wanted]
                filt["bookmakers"] = [bm for bm in filt["bookmakers"] if bm["markets"]]
                params = {"regions": "eu", "markets": subset, "oddsFormat": "decimal"}
                key = cache_key(f"/sports/{sport}/events/{ev['id']}/odds", params)
                (cache / f"{key}.json").write_text(json.dumps(filt))
                print(f"seeded extras [{subset}] for {ev['id'][:8]}… → {key}")
                n += 1

    print(f"done: {n} cache entries in {cache}/")


if __name__ == "__main__":
    main()
