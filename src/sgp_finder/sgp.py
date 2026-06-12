"""3-leg SGP enumeration, copula scoring, and offered-price estimation.

Every SGP is EXACTLY 3 legs across 3 DISTINCT markets (bet365's boosted-SGP
format). Triples containing a contradictory pair (ρ below the exclusion
threshold, e.g. a side's ML with the opponent's cover) are dropped. Each
surviving triple gets:

  P_fair    — copula joint over sharp fair probs (the truth estimate)
  P_offer   — copula joint over the target book's IMPLIED probs (vig retained):
              an approximation of the book's own SGP pricing engine. Flagged as
              an estimate; the dashboard accepts a pasted real price override.
  premium   — P_fair ÷ naive product (what correlation is worth)
  effective_legs — redundancy metric (3 = independent, →1 = one real leg)
  break_even_boost — headline: the boost % that turns the SGP +EV
"""

from __future__ import annotations

from itertools import combinations

from .boost import break_even_boost, ev
from .copula import (
    build_corr_matrix,
    correlation_premium,
    effective_legs,
    joint_prob,
    naive_product,
)
from .correlation import pair_rho
from .devig import decimal_to_american


def score_triple(triple: list[dict], lib: dict, sgp_cfg: dict) -> dict | None:
    """Score one 3-leg combo; None when the combo is structurally excluded."""
    if len({leg["market"] for leg in triple}) != len(triple):
        return None  # distinct markets required

    pairs: list[dict] = []
    pairwise: dict[tuple[int, int], float] = {}
    for i, j in combinations(range(len(triple)), 2):
        rho, relation = pair_rho(triple[i], triple[j], lib)
        if rho is None:
            return None  # same-market pair sneaked in
        if rho <= sgp_cfg["exclude_pair_rho_below"]:
            return None  # contradictory legs — not an SGP
        pairwise[(i, j)] = rho
        pairs.append({
            "legs": f"{triple[i]['label']} × {triple[j]['label']}",
            "relation": relation,
            "rho": round(rho, 3),
        })

    r, psd_repaired = build_corr_matrix(pairwise, len(triple))

    fair_probs = [leg["fair_p"] for leg in triple]
    p_fair = joint_prob(fair_probs, r)
    if p_fair < sgp_cfg["min_fair_prob"]:
        return None

    p_naive = naive_product(fair_probs)
    # Same copula on the book's own implied (vig-retained) probs approximates
    # how the book itself would price the SGP.
    p_offer = joint_prob([leg["target_implied"] for leg in triple], r)
    if p_offer <= 0.0 or p_offer >= 1.0:
        return None
    offered_decimal = 1.0 / p_offer

    eff = effective_legs(p_fair, fair_probs)
    be = break_even_boost(p_fair, offered_decimal)

    return {
        "legs": triple,
        "pairs": pairs,
        "p_fair": round(p_fair, 5),
        "p_naive": round(p_naive, 5),
        "premium": round(correlation_premium(p_fair, fair_probs), 3),
        "fair_decimal": round(1.0 / p_fair, 3),
        "fair_american": decimal_to_american(1.0 / p_fair),
        "offered_decimal_est": round(offered_decimal, 3),
        "offered_american_est": decimal_to_american(offered_decimal),
        "ev_at_offered": round(ev(p_fair, offered_decimal), 5),
        "break_even_boost": round(be, 1) if be is not None else None,
        "effective_legs": round(eff, 2),
        "low_diversification": eff < sgp_cfg["low_diversification_below"],
        "psd_repaired": psd_repaired,
    }


def build_game_sgps(legs: list[dict], lib: dict, sgp_cfg: dict) -> list[dict]:
    """All qualifying 3-leg SGPs for one game, best break-even boost first."""
    n = sgp_cfg["legs_per_sgp"]
    out: list[dict] = []
    for triple in combinations(legs, n):
        scored = score_triple(list(triple), lib, sgp_cfg)
        if scored:
            out.append(scored)
    out.sort(key=lambda s: (s["break_even_boost"] is None,
                            s["break_even_boost"] if s["break_even_boost"] is not None else 0))
    return out[:sgp_cfg["max_per_game"]]
