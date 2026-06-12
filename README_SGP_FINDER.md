# Sharp SGP Finder

Finds the best **boosted 3-leg Same Game Parlays** from game-level markets by
comparing a retail book's lines to **sharp anchors** (Pinnacle + exchanges),
modeling intra-game correlation with a **Gaussian copula**, and ranking by
**break-even boost** — the boost % at which each SGP turns +EV ("needs +18%,
you have +50% → take it").

Sibling automation to the low-hold scanner ([README.md](README.md)); same
scaffolding: The Odds API, on-demand GitHub Actions runs, static dashboard on
GitHub Pages under `/sgp/`.

```bash
# tests
python3 -m pytest tests/test_sgp_*.py

# one sport per run (≈3–15 credits)
ODDS_API_KEY=your_key python3 -m src.sgp_finder.main --sport mlb   # nba | soccer

# develop without burning credits (replay cached responses)
ODDS_API_KEY=your_key ODDS_CACHE_DIR=.odds_cache_sgp python3 -m src.sgp_finder.main --sport mlb
open docs/sgp/index.html
```

## Scope: FREE tier, game-level only — read this first

- **The Odds API free tier (500 credits/month), on-demand `workflow_dispatch`
  runs only.** One sport per run. Featured markets cost
  `3 markets × regions scanned` (today: one `eu` region call = **3 credits**);
  optional per-event alternate lines add up to `extras.max_credits`
  (default 12) more, with the estimate printed before fetching.
- **No player props anywhere.** Props are paid-gated on the free tier
  (verified empirically). This tool operates on game-level markets only:
  moneyline (`h2h`, 3-way for soccer), spreads/run lines (`spreads`), game
  totals (`totals`) — plus team totals / BTTS / alternate lines **only where
  the free key actually returns them** (see below).
- Everything market/book-related was **probed against the live API on
  2026-06-12** (`scripts/probe_free_tier.py`, run via the "SGP Free-Tier
  Probe" workflow). Anything that didn't return is treated as unavailable.

### Empirical reality of the free key (probe 2026-06-12)

| Fact | Consequence |
|---|---|
| **bet365 returns in NO region** (uk/eu/au probed, all sports) | The target book is a **priority list with bet365 first**; the run resolves the first book that actually returns ≥3 featured markets — today **888sport** (MLB/NBA) and **BetOnline** (soccer, 888sport has h2h only there). Dashboard, log and cards flag the resolved book as a **PROXY for bet365**. If bet365 ever appears on the key, it's picked automatically (or force it with `regions.require_target`). |
| Pinnacle: `eu` only, full featured coverage | Primary fair-value anchor. One `eu` call covers target proxy + Pinnacle + Matchbook → 3-credit runs. |
| Exchanges: Matchbook (uk+eu, full), Betfair Ex (h2h mostly), Smarkets (uk) | De-vigged **exchange-consensus median** is the fallback fair when Pinnacle doesn't price a line. Never retail. |
| Circa / BookMaker / BetCRIS: **no such keys** on the free tier | Out of the anchor set until they exist. |
| Extras (`team_totals`, `btts`, `alternate_*`): **Pinnacle only** | No target book prices them → they can't be SGP legs. They're still fetched (capped) to **widen Pinnacle's line pool** so target main lines that drifted from Pinnacle's main line still get an exact match. Leg support for team totals/BTTS is already built and activates the day a target book returns them. |

## How fair value works (per leg)

Sharp anchor's full market at the leg's **exact line** → strip vig → fair
probability. De-vig method is pluggable (`devig.method`): `multiplicative`
(default) or `shin` (pushes more overround onto longshots). Leg edge:
`EV = p_fair·(o_target − 1) − (1 − p_fair)`. Handicaps must match **exactly**
(target −1.5 needs sharp −1.5/+1.5; cross-line pairs are different bets and
are skipped — same rule as the hold scanner). Mildly −EV legs are kept
(`legs.min_leg_ev`, default −8%) because the boost can rescue them.

## Correlation model (the core)

Within-game legs are **not independent**. Joint probability uses a **Gaussian
copula**: each leg's fair prob maps to a latent threshold `z = Φ⁻¹(p)`; legs
share a correlation matrix `R`; `P(all hit)` is the multivariate-normal
orthant probability (scipy's Genz CDF; Monte-Carlo cross-checked in tests).

`R` comes from the **correlation library** in [config/sgp.yaml](config/sgp.yaml)
— heuristic priors keyed by leg-relation per sport, one-line rationale each,
built to be tuned. Sign conventions are exact, not heuristic: "Under hits" is
the complement of "Over hits", so its latent is negated and ρ flips sign.
Inconsistent heuristic triples are repaired to the nearest PSD matrix and
flagged (`ρ matrix repaired`).

**⚠️ The ML+spread redundancy caveat:** the free-tier flagship triple — same
team ML + spread + total — is **highly correlated / low-diversification**.
A "Marlins ML + Marlins +1.5 + Over" SGP is mostly ONE bet on the Marlins
with a side of total. That's just what game-level SGPs are. Every card shows
**effective legs** (3 = independent, →1 = one real bet) and flags anything
below `sgp.low_diversification_below` (default 2.0) so a near-deterministic
combo can't masquerade as a diversified parlay. Contradictory pairs
(opponent ML vs cover, draw vs handicap) are excluded outright
(`sgp.exclude_pair_rho_below`).

## SGP construction

Always **exactly 3 legs, 3 distinct markets** (bet365's boosted-SGP format).
Candidate legs per game are capped (`legs.top_k_per_game`), triples
enumerated, contradictory combos dropped, scored by correlated joint prob →
fair SGP odds, and the slate is capped at the best `sgp.max_total` by
break-even boost.

**⚠️ The offered price is an estimate.** The book's real SGP price is not on
any API: we run the **same copula over the book's own (vig-retained) leg
prices** to approximate its pricing engine. Every card says `model est` until
you paste the real price into the card's override box — then all numbers
(EV, break-even, gate) recompute from **YOUR PRICE**.

## Boost math (client-side — no re-fetch, no credits)

Two inputs on the dashboard, exactly like a bet365 boost token:

- **boost_pct** (presets 30/50/100): `o' = 1 + (o − 1)·(1 + boost/100)`
- **min_odds** (American, presets +100/+300): SGPs whose offered price is
  below the floor are greyed (or hidden). The gate keys on the **pre-boost**
  price by default; the "gate on boosted price" toggle covers promos worded
  the other way.

Headline per card: **break-even boost** `= 100·[(1/P_fair − 1)/(o − 1) − 1]`
and your margin ("need +12%, you have +50% (+38pp)"). Qualifying SGPs sort by
EV at your boost. Changing either input recomputes everything in the browser
from `docs/sgp/data.json` — runs are only for fresh odds.

## Dashboard & deployment

`docs/sgp/index.html` + `data.json`, GitHub Pages
(`https://<user>.github.io/<repo>/sgp/`). Each run covers ONE sport and
merges into `data.json`; the workflow commits `docs/sgp` back to `main` so
other sports' latest runs survive. Trigger: Actions → **Sharp SGP Finder** →
choose sport. The per-sport toggle, like the boost inputs, is client-side.

Run log on the page records which **region each book resolved from**, the
anchors used, de-vig method, and credit spend.

## Tuning knobs

All in [config/sgp.yaml](config/sgp.yaml): target-book priority &
`require_target`, region scan order, correlation library (per-sport ρ),
de-vig method, leg EV floor & top-K, exclusion threshold, redundancy
threshold, extras window/cap, boost defaults.

## Future (requires paid plan — NOT built)

Player props (NBA pts/reb/ast, MLB Ks/HR/TB, soccer scorer/shots) unlock the
real SGP value and a much richer correlation library. Seams already exist:
leg extraction is market-generic (`legs.LEG_MARKETS`), the correlation
library is keyed by relation classes, and the target-book priority list will
prefer bet365 the moment the key returns it.
