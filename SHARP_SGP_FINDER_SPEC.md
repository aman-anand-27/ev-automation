# Sharp SGP Finder — Build Spec (FREE-TIER constrained)

**Build this end-to-end now — this spec is the design, no proposal step.** A sibling automation to the existing low-hold scanner. Reuse the proven scaffolding
(The Odds API client with `ODDS_CACHE_DIR` replay caching, no-vig math, Jinja2 → static
`docs/` dashboard, GitHub Actions `workflow_dispatch` only, per-sport client-side toggle).
Build it as a **NEW project/module** so it doesn't tangle with the hold scanner.

## Hard constraint: FREE Odds API tier only
- I am on the **free tier** (500 credits/month) and this runs **on-demand only** (no cron —
  `workflow_dispatch`).
- **Player props are NOT available on the free tier** — confirmed empirically; they require a
  paid plan. So props are OUT of scope. Do NOT build a per-event prop path. The tool operates on
  **game-level markets only**.
- Only use markets/lines that the free key actually returns. At build time, PROBE which markets
  come back for each sport+book on the free key and design around the confirmed set. Treat any
  market that doesn't return as unavailable — never assume.

## Markets (free-tier, game-level only)
- **Guaranteed baseline (the three "featured" markets, one cheap call to `/sports/{sport}/odds`):**
  moneyline (`h2h`, 3-way for soccer), spreads/run-lines/puck-lines (`spreads`), game totals
  (`totals`). Design the whole tool to work on these alone.
- **Probe-and-include-if-they-return (additional markets, often paid-gated → may be empty on
  free):** team totals, BTTS (soccer), alternate lines. If the free key returns them, use them
  (they unlock better correlated combos); if not, skip silently and note it in the run log.
- No player props anywhere in the active design. (A paid-tier prop extension is noted at the
  bottom as future work, but is NOT built now.)

## Objective
For ONE sport at a time (MLB, NBA, or soccer), find the best Same Game Parlays buildable on
bet365 from game-level legs, and apply a boost to. Compare bet365's lines to SHARP/line-setting
books, compute sharp-fair probabilities, model intra-game correlation the sharp way, and output
ranked boosted-SGP recommendations — like BetterOdds' SGP creator, but inferring SGP fair value
from legs + correlation rather than reading the book's actual SGP price.

## Books
- Target (the book I actually bet on): **bet365**.
- Sharp / line-setter reference set (NO retail books): **Pinnacle** (primary fair anchor),
  plus Circa, BookMaker/BetCRIS if available, and sharp **exchanges** (Betfair Exchange,
  Matchbook). Use sharp/exchange consensus only — never DraftKings/FanDuel/MGM/Caesars-type
  retail for fair value.
- IMPORTANT: verify exact bookmaker keys and which region each lives in against The Odds API's
  live `/sports` and bookmaker list at build time — do not hardcode from memory (e.g. Pinnacle
  is typically eu-region, bet365 in uk/eu/au). Also confirm each book actually returns on the
  FREE key in the resolved region.

## Region fallback (must actually return lines)
For each (sport, book), try regions in priority order until the book+markets actually come
back, then stop: bet365 → `[uk, eu, au]`; Pinnacle/exchanges → `[eu, uk]`. US is fine but
optional — if US doesn't return the book, fall through to international regions. Request the
MINIMAL region set per sport that covers bet365 + at least one sharp anchor; only widen if a
needed book is missing. Log which region each book resolved from.

## Credit discipline
Pull ONE sport per run (CLI flag, e.g. `--sport mlb`). Never fetch all sports at once. Game-level
featured markets come from a single `/sports/{sport}/odds` call per region, so cost ≈
`markets × regions` per sport (e.g. 3 markets × 2 regions ≈ 6 credits/run) — cheap, fits the free
budget easily. If you probe additional markets (team totals/BTTS) via the per-event endpoint,
scope to the imminent slate with `--window-hours` (default 12) and print an estimated credit cost
before fetching. Keep the `ODDS_CACHE_DIR` replay path working so I can develop without burning
credits.

## Fair value (per leg) — sharp no-vig
For each candidate leg, take the sharp anchor's price (Pinnacle first; fall back to sharp
consensus if Pinnacle absent), strip vig to get fair probability. Default method:
multiplicative/proportional no-vig over the full market (2-way Over/Under or spread sides; n-way
for soccer 1X2). Make the de-vig method pluggable (multiplicative default; Shin's method
optional). Then compute bet365's edge per leg: `EV_leg = p_fair·(o_b365 − 1) − (1 − p_fair)`;
also report `bet365_implied` vs `p_fair`. Reuse the existing no-vig helpers where possible.
Note: bet365 spread/total handicaps must EXACTLY match the sharp anchor's line to be comparable
(reuse the hold scanner's handicap-flip / point-match logic); skip mismatched lines.

## Correlation model (the core — standard sharp way)
Within-game legs are NOT independent. Model joint probability with a GAUSSIAN COPULA:
- Map each leg's fair prob `p_i` to a latent threshold `z_i = Φ⁻¹(p_i)`.
- Build a correlation matrix `R` over latent variables, with `ρ_ij` from a documented,
  configurable CORRELATION LIBRARY keyed by leg-type pairs per sport. Heuristic industry-standard
  priors (no play-by-play data) — named constants, one-line rationale each, easy to tune.
- Free-tier (game-level) correlated structures — this is the actual usable set:
  - **Same-team ML ↔ spread**: very high positive (near-redundant for big favorites). Allow as a
    classic correlated 2-leg, but CAP ρ below 1 and flag it as low-diversification.
  - **Favorite ML/spread ↔ game total**: weak, sign depends on sport/line — keep small.
  - **Soccer**: home/away win (`h2h`) ↔ Over 2.5 (`totals`): mild positive; if BTTS returns,
    BTTS ↔ Over: strong positive, BTTS ↔ a one-sided win: structure carefully.
  - **Team total Over ↔ that team's ML/spread** (only if team totals return): solid positive —
    the best free-tier combo when available.
  - Opposing/contradictory legs (e.g. both teams' ML, ML vs opposing spread): negative — flag and
    exclude as SGP legs.
- Joint `P(all legs hit)` = orthant probability of the multivariate normal with correlation `R`
  (bivariate-normal CDF for 2 legs; scipy `multivariate_normal` CDF or Monte-Carlo for ≥3). Show
  the "correlation premium" = correlated joint ÷ naive product.

## SGP construction & search
bet365's boosted SGPs are **always EXACTLY 3 legs** — build only 3-leg SGPs. On the free tier
with featured markets only, the natural 3-leg is **one side each of moneyline + spread + total**
(e.g. Team A ML + Team A −1.5 + Over) — essentially one structural template per game, with
favorite/dog and over/under variants. Team totals/BTTS (if they return) expand the leg pool so you
can form more varied triples. Enforce 3 DISTINCT markets per SGP. Gather candidate legs (prefer
fair-or-better at bet365, but keep mildly -EV legs since the boost can rescue them), drop strongly
anti-correlated triples, enumerate valid 3-leg combos, cap with top-K legs per game. Score each by
correlated joint prob → fair SGP decimal odds (`= 1/P_fair`). REALITY CHECK for the README: an
ML+spread+total triple on the same favorite is highly correlated / low-diversification — that's
just how game-level SGPs work, but surface an "effective legs" / redundancy flag so I'm not fooled
by a near-deterministic combo.

## Boost EV (always a boosted 3-leg SGP — two inputs)
Every recommendation assumes a boosted 3-leg SGP. I enter TWO params per boost token:
- `boost_pct` — the profit boost, always applied. Typical: **30, 50, occasionally 100**.
- `min_odds` — the boost's minimum-odds requirement in AMERICAN odds (e.g. `+100` or `+300`).
  Only SGPs whose offered price meets/exceeds this qualify for the boost.

Math:
- Estimate bet365's offered SGP price by running the SAME copula on bet365's own per-leg implied
  probs (vig retained) — approximates the book's correlation engine. Flag as an estimate; allow me
  to paste a real SGP price to override. Express it in American + decimal.
- **Min-odds gate:** drop any SGP whose offered price is below `min_odds`. The gate keys on the
  PRE-boost (natural) SGP price by default — make pre-boost-vs-boosted configurable in case a
  promo differs.
- Apply boost: `o' = 1 + (o_offer − 1)·(1 + boost_pct/100)`.
- `EV_SGP = P_fair·(o' − 1) − (1 − P_fair)`.
- HEADLINE METRIC — **break-even boost**: the boost % at which the SGP turns +EV. Compare directly
  to my `boost_pct` → "needs +18%, you have +50% → take it." Rank qualifying SGPs by EV at my boost
  and by margin (`boost_pct − break_even_boost`).
- `boost_pct` and `min_odds` are **client-side UI controls** (like the per-sport toggle): store
  each SGP's `P_fair` + offered odds in `data.json` so the browser recomputes qualification, EV,
  and break-even live when I change them — no re-run, no credits.

## Output / dashboard
Mirror the existing static dashboard: render `docs/data.json` + `docs/index.html` via Jinja2,
GitHub Pages, `workflow_dispatch` only. UI controls (all client-side, no re-fetch): per-sport
toggle, `boost_pct` input, `min_odds` input (American). Each card = one recommended boosted 3-leg
SGP for a game showing: the 3 legs, per-leg bet365 odds + sharp fair + edge, naive vs correlated
joint prob, fair SGP odds, estimated offered odds (American + decimal), boosted odds at my
`boost_pct`, EV, break-even boost, correlation/redundancy notes, and which region each book
resolved from. Grey out / hide SGPs below the current `min_odds`. Sort qualifying SGPs by EV /
lowest break-even boost. Caveat banner: I must still verify the SGP is actually buildable on
bet365 (book SGP-eligibility rules are unknown to this tool).

## Constraints
- The Odds API **free tier only**; on-demand runs only; game-level markets only (NO props).
  Keep `ODDS_CACHE_DIR` replay working. Document credit cost per run; one-sport-per-run discipline.
- Tests for: no-vig math, copula joint-prob (sanity vs naive product, ρ=0 → independence, ρ=1 →
  min leg), boost/EV + break-even-boost solver, min-odds gate (American↔decimal conversion +
  threshold), 3-leg enumeration, region-fallback selection, handicap line-match.
- README must be explicit about: the free-tier game-level-only scope, the heuristic correlation
  priors, the estimated-offered-price assumption, and the ML+spread redundancy caveat.

## First steps
This spec is the design — just build it, no proposal/approval step. The ONLY thing to confirm
empirically first (because the build depends on it and can't be known from memory): hit the live
API with my free key and verify (a) the exact bookmaker keys for bet365 + the sharp anchors and
which region each returns in, and (b) which markets actually come back free per sport. Then build
the full pipeline + tests + dashboard end-to-end.

## Future (NOT now — requires paid plan)
If I later upgrade, a per-event player-prop path unlocks the real SGP value (NBA points/reb/ast,
MLB Ks/HR/total-bases, soccer scorer/shots) and a much richer correlation library. Leave clean
seams for it but do not build it on the free tier.
