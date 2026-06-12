# EV Automation

Two on-demand tools share this repo (and one Odds API free-tier budget):

- **Low-Hold Dashboard** (below) — DK×Novig two-way hold scanner.
- **[Sharp SGP Finder](README_SGP_FINDER.md)** — boosted 3-leg SGPs vs sharp
  fair value (Pinnacle + exchanges), Gaussian-copula correlation, break-even
  boost ranking. Dashboard at `…/sgp/`; trigger via Actions → Sharp SGP Finder.

## Low-Hold Dashboard

A personal CNO replacement. Fetches DraftKings + Novig odds via [The Odds API](https://the-odds-api.com), computes two-way hold for every DK×Novig pair, and publishes a dashboard to GitHub Pages.

**Dashboard URL:** `https://<your-username>.github.io/<repo-name>/`

### Running a refresh

Go to **Actions → Update Low-Hold Dashboard → Run workflow**. The workflow fetches odds, builds `docs/`, and deploys to the `gh-pages` branch. One click, ~30 seconds.

### One-time setup

1. Add `ODDS_API_KEY` as a GitHub Actions secret (Settings → Secrets → Actions).
2. Enable GitHub Pages: Settings → Pages → Source → **Deploy from a branch** → branch `gh-pages`, folder `/` (root).

### Local smoke test

```bash
pip install -r requirements.txt
ODDS_API_KEY=your_key python -m src.cno_odds.main
open docs/index.html
```

Set `ODDS_CACHE_DIR=.odds_cache` to cache API responses on disk and avoid burning credits on repeated local runs.

### Configuration (`config/cno.yaml`)

| Key | Default | Effect |
|-----|---------|--------|
| `thresholds.hold_max_pct` | `3.0` | Max hold % shown in the raw table |
| `thresholds.dk_consensus_tolerance_pp` | `1.5` | Max DK vs consensus deviation (pp) |
| `thresholds.novig_best_rank` | `2` | Novig must be top-N on opposing side |
| `sports` | 4 sports | Remove a sport to save credits |

Credit budget: 4 sports × 3 markets × 2 regions = **24 credits/run**. Free tier (500/mo) ≈ 20 runs/month.

### Running tests

```bash
pytest tests/
```
