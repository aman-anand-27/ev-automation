"""One-shot empirical probe of The Odds API free tier for the Sharp SGP Finder.

Answers, with real API responses (never from memory):
  (a) exact bookmaker keys for bet365 + sharp anchors (pinnacle, circa,
      bookmaker/betcris, betfair exchange, matchbook) and which REGION each
      returns in, per sport;
  (b) which markets actually come back on the FREE key per sport — featured
      (h2h/spreads/totals) and additional (team totals, BTTS, alternates) via
      one per-event call;
  (c) which soccer competition is in season right now;
  (d) credits used/remaining.

Designed to run in GitHub Actions where ODDS_API_KEY lives. Budget-guarded:
counts estimated credits before every call and refuses to exceed --max-credits.
Saves every raw response + a manifest to probe_results/ (uploaded as artifact)
so the responses can seed test fixtures and ODDS_CACHE_DIR replay later.

Usage: ODDS_API_KEY=... python scripts/probe_free_tier.py --max-credits 40
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

BASE = "https://api.the-odds-api.com/v4"
OUT = Path("probe_results")
RAW = OUT / "raw"

# Books we care about (presence checked per region; full lists also recorded)
TARGET_BOOK = "bet365"
SHARP_CANDIDATES = [
    "pinnacle",
    "circasports",
    "circa",
    "bookmaker",
    "bookmakereu",
    "betcris",
    "betfair_ex_uk",
    "betfair_ex_eu",
    "betfair_ex_au",
    "betfair",
    "matchbook",
]

SOCCER_PRIORITY = [
    "soccer_fifa_world_cup",
    "soccer_uefa_champs_league",
    "soccer_epl",
    "soccer_usa_mls",
    "soccer_spain_la_liga",
    "soccer_brazil_campeonato",
    "soccer_uefa_european_championship",
]

EXTRA_MARKETS = {
    "baseball_mlb": ["team_totals", "alternate_spreads", "alternate_totals"],
    "basketball_nba": ["team_totals", "alternate_spreads", "alternate_totals"],
    "soccer": ["btts", "team_totals", "alternate_totals"],
}


class Budget:
    """Tracks estimated + actual credit spend; refuses calls that would bust the cap."""

    def __init__(self, max_credits: int):
        self.max_credits = max_credits
        self.est_spent = 0
        self.last_remaining: str | None = None
        self.last_used: str | None = None

    def can_afford(self, est_cost: int) -> bool:
        return self.est_spent + est_cost <= self.max_credits

    def record(self, est_cost: int, headers: dict) -> None:
        self.est_spent += est_cost
        self.last_remaining = headers.get("x-requests-remaining", self.last_remaining)
        self.last_used = headers.get("x-requests-used", self.last_used)


def _sanitize(msg: str) -> str:
    key = os.environ.get("ODDS_API_KEY", "")
    return msg.replace(key, "***") if key else msg


def api_get(path: str, params: dict, budget: Budget, est_cost: int, save_as: str,
            manifest: list) -> tuple[object, int]:
    """GET with budget guard + raw-response capture. Returns (json_or_None, status)."""
    if not budget.can_afford(est_cost):
        print(f"  BUDGET-SKIP {path} (est {est_cost}cr would exceed cap "
              f"{budget.max_credits}, spent ~{budget.est_spent})")
        manifest.append({"file": None, "path": path, "params": params,
                         "status": "budget_skipped", "est_cost": est_cost})
        return None, 0

    full = dict(params)
    full["apiKey"] = os.environ["ODDS_API_KEY"]
    status = -1
    body: object = None
    for attempt in (1, 2):
        try:
            resp = requests.get(f"{BASE}{path}", params=full, timeout=30)
            status = resp.status_code
            try:
                body = resp.json()
            except ValueError:
                body = {"_non_json_body": resp.text[:500]}
            if status < 500:
                break
        except requests.RequestException as e:
            print(f"  network error (attempt {attempt}): {_sanitize(str(e))}")
            status = -1
        time.sleep(2)

    headers = dict(resp.headers) if status != -1 else {}
    # Only successful odds responses cost credits; errors cost 0
    cost = est_cost if status == 200 else 0
    budget.record(cost, headers)

    RAW.mkdir(parents=True, exist_ok=True)
    fp = RAW / f"{save_as}.json"
    fp.write_text(json.dumps(body, indent=1))
    manifest.append({
        "file": str(fp.relative_to(OUT)),
        "path": path,
        "params": params,  # apiKey never included
        "status": status,
        "est_cost": cost,
        "x_requests_remaining": headers.get("x-requests-remaining"),
        "x_requests_used": headers.get("x-requests-used"),
    })
    time.sleep(0.6)
    return body, status


def books_in(games: object) -> set:
    keys = set()
    if isinstance(games, list):
        for g in games:
            for bm in g.get("bookmakers", []):
                keys.add(bm["key"])
    return keys


def markets_by_book(games: object) -> dict:
    """{book_key: sorted list of market keys}, unioned across games."""
    out: dict[str, set] = {}
    if isinstance(games, list):
        for g in games:
            for bm in g.get("bookmakers", []):
                out.setdefault(bm["key"], set()).update(
                    m["key"] for m in bm.get("markets", []))
    return {k: sorted(v) for k, v in out.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-credits", type=int, default=40)
    args = ap.parse_args()

    budget = Budget(args.max_credits)
    manifest: list = []
    summary: dict = {"sports": {}, "notes": []}
    OUT.mkdir(exist_ok=True)

    # ── Step 0 (FREE): in-season sports + quota ──────────────────────────
    sports_list, status = api_get("/sports", {}, budget, est_cost=0,
                                  save_as="sports_list", manifest=manifest)
    if status != 200:
        print(f"FATAL: /sports returned {status}: {json.dumps(sports_list)[:300]}")
        sys.exit(1)
    active = {s["key"]: s for s in sports_list if s.get("active")}
    print(f"Active sports: {len(active)} | credits remaining={budget.last_remaining} "
          f"used={budget.last_used}")
    summary["quota_at_start"] = {"remaining": budget.last_remaining,
                                 "used": budget.last_used}

    soccer_active = [k for k in active if k.startswith("soccer_")]
    soccer_key = next((k for k in SOCCER_PRIORITY if k in active),
                      soccer_active[0] if soccer_active else None)
    summary["soccer_active"] = soccer_active
    summary["soccer_chosen"] = soccer_key
    print(f"Soccer in season: {soccer_active}\nChosen soccer key: {soccer_key}")

    probe_sports = []
    for k in ("baseball_mlb", "basketball_nba"):
        if k in active:
            probe_sports.append(k)
        else:
            summary["notes"].append(f"{k} not active per /sports — skipped")
    if soccer_key:
        probe_sports.append(soccer_key)

    # ── Per-sport probing ────────────────────────────────────────────────
    for sport in probe_sports:
        s: dict = {"regions": {}, "featured_markets_by_book": {},
                   "extras": {}, "notes": []}
        summary["sports"][sport] = s
        print(f"\n========== {sport} ==========")

        # Step 1: which books live in which region (h2h only, 1 credit/region)
        region_books: dict[str, set] = {}
        regions_to_try = ["uk", "eu"]
        if budget.can_afford(20):       # us2 = optional circa probe, skip when tight
            regions_to_try.append("us2")
        for region in regions_to_try:
            games, st = api_get(f"/sports/{sport}/odds",
                                {"regions": region, "markets": "h2h",
                                 "oddsFormat": "decimal"},
                                budget, est_cost=1,
                                save_as=f"{sport}__{region}__h2h",
                                manifest=manifest)
            bk = books_in(games)
            region_books[region] = bk
            n_games = len(games) if isinstance(games, list) else 0
            s["regions"][region] = {"status": st, "n_games": n_games,
                                    "books": sorted(bk)}
            print(f"  [{region}] status={st} games={n_games} books={sorted(bk)}")

        if TARGET_BOOK not in region_books.get("uk", set()) | region_books.get("eu", set()):
            games, st = api_get(f"/sports/{sport}/odds",
                                {"regions": "au", "markets": "h2h",
                                 "oddsFormat": "decimal"},
                                budget, est_cost=1,
                                save_as=f"{sport}__au__h2h", manifest=manifest)
            bk = books_in(games)
            region_books["au"] = bk
            s["regions"]["au"] = {"status": st,
                                  "n_games": len(games) if isinstance(games, list) else 0,
                                  "books": sorted(bk)}
            print(f"  [au fallback] status={st} books={sorted(bk)}")

        s["bet365_regions"] = [r for r, bk in region_books.items() if TARGET_BOOK in bk]
        s["sharp_anchor_regions"] = {
            b: [r for r, bk in region_books.items() if b in bk]
            for b in SHARP_CANDIDATES
            if any(b in bk for bk in region_books.values())
        }
        print(f"  bet365 in: {s['bet365_regions']}")
        print(f"  sharp anchors found: {s['sharp_anchor_regions']}")

        # Minimal region set: cheapest cover of bet365 + pinnacle (or any anchor)
        minimal: list[str] = []
        for pri in ("uk", "eu", "au"):
            if pri in s["bet365_regions"]:
                minimal.append(pri)
                break
        anchor_regions = s["sharp_anchor_regions"].get("pinnacle") or next(
            iter(s["sharp_anchor_regions"].values()), [])
        if anchor_regions and not (set(minimal) & set(anchor_regions)):
            for pri in ("eu", "uk"):
                if pri in anchor_regions:
                    minimal.append(pri)
                    break
        s["minimal_region_set"] = minimal
        print(f"  minimal region set: {minimal}")

        # Step 2: featured spreads/totals on the minimal set (h2h already probed)
        if minimal:
            games, st = api_get(f"/sports/{sport}/odds",
                                {"regions": ",".join(minimal),
                                 "markets": "spreads,totals",
                                 "oddsFormat": "decimal"},
                                budget, est_cost=2 * len(minimal),
                                save_as=f"{sport}__{'-'.join(minimal)}__spreads-totals",
                                manifest=manifest)
            if st == 200:
                s["featured_markets_by_book"] = markets_by_book(games)
                ev = games[0] if isinstance(games, list) and games else None
            else:
                s["notes"].append(f"spreads/totals probe failed: {st} "
                                  f"{json.dumps(games)[:200]}")
                ev = None
            print(f"  spreads/totals by book: {s['featured_markets_by_book']}")

            # Step 3: additional markets on ONE event (per-event endpoint)
            extras = EXTRA_MARKETS["soccer" if sport.startswith("soccer_") else sport]
            if ev:
                event_id = ev["id"]
                s["extras"]["event_probed"] = {
                    "id": event_id, "home": ev.get("home_team"),
                    "away": ev.get("away_team"),
                    "commence_time": ev.get("commence_time")}
                body, st = api_get(f"/sports/{sport}/events/{event_id}/odds",
                                   {"regions": ",".join(minimal),
                                    "markets": ",".join(extras),
                                    "oddsFormat": "decimal"},
                                   budget, est_cost=len(extras) * len(minimal),
                                   save_as=f"{sport}__event__extras",
                                   manifest=manifest)
                s["extras"]["requested"] = extras
                s["extras"]["status"] = st
                if st == 200:
                    s["extras"]["markets_by_book"] = markets_by_book(
                        [body] if isinstance(body, dict) else body)
                    print(f"  extras by book: {s['extras']['markets_by_book']}")
                else:
                    s["extras"]["error"] = json.dumps(body)[:300]
                    print(f"  extras probe: status={st} body={s['extras']['error']}")
                    # Batch failed (e.g. one invalid market) → try each alone
                    s["extras"]["per_market"] = {}
                    for m in extras:
                        b2, st2 = api_get(
                            f"/sports/{sport}/events/{event_id}/odds",
                            {"regions": minimal[0], "markets": m,
                             "oddsFormat": "decimal"},
                            budget, est_cost=1,
                            save_as=f"{sport}__event__{m}", manifest=manifest)
                        ok = st2 == 200 and isinstance(b2, dict) and any(
                            bm.get("markets") for bm in b2.get("bookmakers", []))
                        s["extras"]["per_market"][m] = {
                            "status": st2,
                            "returned": ok,
                            "books": sorted(books_in([b2])) if st2 == 200 and isinstance(b2, dict) else [],
                        }
                        print(f"    extras[{m}]: status={st2} returned={ok}")
            else:
                s["extras"]["note"] = "no event available to probe extras"

    summary["quota_at_end"] = {"remaining": budget.last_remaining,
                               "used": budget.last_used}
    summary["estimated_credits_spent"] = budget.est_spent

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))

    print("\n===== PROBE SUMMARY =====")
    print(json.dumps(summary, indent=1))
    print("===== END PROBE SUMMARY =====")


if __name__ == "__main__":
    main()
