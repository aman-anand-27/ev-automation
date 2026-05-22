# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Personal sportsbook low-hold scanner — a replacement for CrazyNinjaOdds (CNO). Fetches DraftKings + Novig odds from The Odds API, computes two-way hold for every DK×Novig pair, and publishes a static dashboard to GitHub Pages. Run on-demand via GitHub Actions `workflow_dispatch`.

The core insight: hold = `1/dk_price + 1/novig_price − 1`. Negative or near-zero hold on a DK+Novig round-trip is the signal.

## Commands

```bash
# Run tests
python3 -m pytest tests/

# Run a single test
python3 -m pytest tests/test_hold.py::test_find_opposing_spreads_mismatch_skipped

# Local end-to-end (burns ~24 API credits)
ODDS_API_KEY=your_key python3 -m src.cno_odds.main

# Local dev without burning credits — cache responses on first run, replay after
ODDS_API_KEY=your_key ODDS_CACHE_DIR=.odds_cache python3 -m src.cno_odds.main
open docs/index.html
```

## Pipeline

```
config/cno.yaml
      │
      ▼
fetch.py        → calls The Odds API (one request per sport)
      │
      ▼
hold.py         → pairs DK vs Novig outcomes, computes hold %, consensus implied prob, Novig rank
      │
      ▼
qualify.py      → stamps each row qualified=True/False + disqualify_reasons[]
      │
      ▼
render.py       → writes docs/data.json and docs/index.html (Jinja2 template)
      │
      ▼
GitHub Pages    (gh-pages branch, deployed by peaceiris/actions-gh-pages)
```

Each run is a full stateless snapshot — no deduplication, no persistent state.

## Key design decisions

**Pairing logic** (`hold.py`): DK TeamA pairs with Novig's opposing outcome. Spreads require exact handicap flip (DK -1.5 → Novig +1.5); mismatched lines are silently skipped — they're different bets. Totals require same point value, opposite Over/Under. 3-way h2h markets (soccer) are skipped.

**Consensus** (`hold.py:_consensus_implied`): Uses ALL bookmakers returned by the API except DK and Novig — not a fixed whitelist. The original config has a `consensus_books` list but it's unused; we exclude only `{primary, exchange}`. This was changed after discovering API bookmaker keys don't always match expected names (e.g. Pinnacle is in `eu` region, not `us`/`us_ex`).

**Novig rank** (`hold.py:_novig_rank`): Rank 1 = Novig has the best (highest decimal) price on the opposing side vs all other books. Rank 2 means one book has a better price.

**Qualification** (`qualify.py`): Three independent checks — hold threshold, DK within ±N pp of consensus, Novig top-N rank. All failures reported in `disqualify_reasons[]`.

## Tuning knobs

All in `config/cno.yaml`:
- `thresholds.hold_max_pct` — ceiling for the raw table (default 3%)
- `thresholds.dk_consensus_tolerance_pp` — how far DK can deviate from consensus (default 1.5pp)
- `thresholds.novig_best_rank` — how good Novig must be on opposing side (default top-2)
- `thresholds.min_books_for_consensus` — min books needed to compute consensus (default 2)
- `sports` — remove a sport to save API credits

## Credit budget

Free tier: 500 credits/month. Each run: 4 sports × 3 markets × 2 regions = **24 credits**. ≈ 20 runs/month.

## Deployment

GitHub Actions workflow (`.github/workflows/cno.yml`) is `workflow_dispatch` only — no cron. User triggers manually. Deploys `docs/` to orphan `gh-pages` branch. Dashboard URL: `https://<username>.github.io/<repo>/`.

`ODDS_API_KEY` must be set as a GitHub Actions secret.
