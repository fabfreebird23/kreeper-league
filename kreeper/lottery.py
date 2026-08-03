"""Draft-order lottery for The Kreeper League.

House rule (config.yaml has the full text + weights):
  One combined weighted draw across all `num_teams` teams sets next season's
  DRAFT ORDER directly (lottery rank 1 drafts 1st overall, rank N drafts
  last — this league's lottery sets a position, not a "choose your slot"
  selection order).

  * Consolation-bracket ("Chase for the Pick") teams occupy the best-odds
    ranks. Their rank is the bracket's own placement INVERTED — the team
    that finishes LAST in that bracket (loses every consolation game) gets
    the single best odds, since the bracket's whole purpose is confirming
    who's actually worst. The bracket's own winner gets the weakest odds of
    that group.
  * Championship-bracket (playoff) teams occupy the remaining, worse-odds
    ranks. NOT inverted — the champion gets the best odds of that group, the
    last-place playoff finisher the worst overall.

Validated against this league's real 2025 result (see tests/test_lottery.py
and the throwaway verification script referenced in that season's PR).

Pure logic module — no Streamlit here.
"""
from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Tuple

from . import config, sleeper


def _roster_to_owner(league_id: str) -> Dict[int, str]:
    return {int(r["roster_id"]): str(r.get("owner_id")) for r in sleeper.get_rosters(league_id)}


def _full_placements(bracket: List[Dict[str, Any]]) -> Dict[int, int]:
    """{placement_rank: roster_id} from a bracket's `p`-tagged games (winner
    takes placement `p`, loser takes `p+1`). Returns {} if the bracket has no
    placement games yet, OR any placement game exists but isn't decided yet
    (both cases correctly read as "not complete")."""
    out: Dict[int, int] = {}
    for g in bracket:
        p = g.get("p")
        if not p:
            continue
        w, l = g.get("w"), g.get("l")
        if w is None or l is None:
            return {}
        out[p] = w
        out[p + 1] = l
    return out


def _standings(league_id: str) -> List[Tuple[str, int, int, float]]:
    """[(owner_id, wins, losses, points_for)]."""
    out = []
    for r in sleeper.get_rosters(league_id):
        o = str(r.get("owner_id"))
        s = r.get("settings", {}) or {}
        w, l = int(s.get("wins", 0) or 0), int(s.get("losses", 0) or 0)
        pf = float(s.get("fpts", 0) or 0) + float(s.get("fpts_decimal", 0) or 0) / 100
        out.append((o, w, l, round(pf, 2)))
    return out


def season_is_complete(league_id: Optional[str] = None) -> bool:
    """True once BOTH the championship and consolation brackets have every
    placement game decided."""
    league_id = league_id or config.league()["sleeper_league_id"]
    wb = sleeper.get_winners_bracket(league_id)
    lb = sleeper.get_losers_bracket(league_id)
    return bool(_full_placements(wb)) and bool(_full_placements(lb))


def final_tiers(league_id: Optional[str] = None) -> Optional[Dict[str, Dict[str, Any]]]:
    """For a COMPLETED season: {owner_id: {"weight", "tier", "rank",
    "bracket_placement"}} for every team. Returns None if either bracket
    isn't fully decided yet — callers should treat that as "not ready"."""
    league_id = league_id or config.league()["sleeper_league_id"]
    wb = sleeper.get_winners_bracket(league_id)
    lb = sleeper.get_losers_bracket(league_id)
    wb_places = _full_placements(wb)
    lb_places = _full_placements(lb)
    if not wb_places or not lb_places:
        return None

    r2o = _roster_to_owner(league_id)
    weights = config.lottery_weights()
    n_consol, n_playoff = len(lb_places), len(wb_places)
    if len(weights) != n_consol + n_playoff:
        raise ValueError(
            f"lottery.weights has {len(weights)} entries but the brackets cover "
            f"{n_consol + n_playoff} teams ({n_consol} consolation + {n_playoff} championship)"
        )

    out: Dict[str, Dict[str, Any]] = {}
    # Consolation bracket, ranks 1..n_consol — INVERTED (worst literal
    # placement gets the best lottery odds).
    for lottery_rank in range(1, n_consol + 1):
        literal_placement = n_consol + 1 - lottery_rank
        owner = r2o.get(lb_places.get(literal_placement))
        out[owner] = {
            "weight": weights[lottery_rank - 1],
            "tier": "consolation",
            "rank": lottery_rank,
            "bracket_placement": literal_placement,
        }
    # Championship bracket, ranks (n_consol+1)..(n_consol+n_playoff) — NOT inverted.
    for literal_placement in range(1, n_playoff + 1):
        lottery_rank = n_consol + literal_placement
        owner = r2o.get(wb_places.get(literal_placement))
        out[owner] = {
            "weight": weights[lottery_rank - 1],
            "tier": "championship",
            "rank": lottery_rank,
            "bracket_placement": literal_placement,
        }
    return out


def position_probabilities(weights: Dict[str, float]) -> Dict[str, List[float]]:
    """Exact (not simulated) probability each owner lands in each 0-indexed
    draft position, via DP over "teams remaining" bitmask states — fast and
    exact for n up to the low dozens."""
    owners = list(weights)
    n = len(owners)
    full = (1 << n) - 1
    result = {o: [0.0] * n for o in owners}
    states_by_count: Dict[int, List[int]] = {}
    for mask in range(full + 1):
        states_by_count.setdefault(bin(mask).count("1"), []).append(mask)
    prob = {full: 1.0}
    for count in range(n, 0, -1):
        for mask in states_by_count.get(count, []):
            p_here = prob.get(mask, 0.0)
            if p_here <= 0:
                continue
            total_w = sum(weights[owners[i]] for i in range(n) if mask & (1 << i))
            if total_w <= 0:
                continue
            position = n - count
            for i in range(n):
                bit = 1 << i
                if not (mask & bit):
                    continue
                p_pick = p_here * weights[owners[i]] / total_w
                result[owners[i]][position] += p_pick
                prob[mask & ~bit] = prob.get(mask & ~bit, 0.0) + p_pick
    return result


def draw_order(weights: Dict[str, float], rng: Optional[random.Random] = None) -> List[str]:
    """One real weighted draw without replacement. Index 0 = drafts first."""
    rng = rng or random.Random()
    remaining = dict(weights)
    order: List[str] = []
    while remaining:
        total = sum(remaining.values())
        if total <= 0:
            order.extend(sorted(remaining))  # all-zero fallback: stable, arbitrary
            break
        pick = rng.uniform(0, total)
        upto = 0.0
        for owner, w in remaining.items():
            upto += w
            if upto >= pick:
                order.append(owner)
                del remaining[owner]
                break
    return order


def live_projection(
    league_id: Optional[str] = None, playoff_teams: Optional[int] = None
) -> Optional[List[Dict[str, Any]]]:
    """For an IN-PROGRESS or not-yet-started season: a self-contained
    heuristic projection of each team's likely lottery odds, from THIS
    season's current record + points-for alone (no cross-season history —
    deliberately separate from the Title Odds power-ranking model).

    Returns None if the season hasn't started yet (0 games played anywhere)
    — there's no signal to project from. This is an approximation for
    planning purposes, not the exact math `final_tiers` +
    `position_probabilities` give once the season is actually over.
    """
    league_id = league_id or config.league()["sleeper_league_id"]
    weights = config.lottery_weights()
    n = len(weights)
    playoff_teams = playoff_teams or n // 2
    n_consol = n - playoff_teams

    standings = _standings(league_id)
    if not standings or sum(w + l for _, w, l, _ in standings) == 0:
        return None

    def win_pct(w: int, l: int) -> float:
        gp = w + l
        return (w / gp) if gp else 0.0

    # Worst record first (win%, then points-for as the tiebreak).
    ranked = sorted(standings, key=lambda t: (win_pct(t[1], t[2]), t[3]))
    consol_avg = sum(weights[:n_consol]) / n_consol
    playoff_avg = sum(weights[n_consol:]) / playoff_teams

    rows = []
    for idx, (owner, w, l, pf) in enumerate(ranked):
        # Logistic confidence this team ends up on the playoff side of the
        # cutoff, centered on the consolation/playoff boundary and sharpened
        # as more games are played (more signal -> more confident). Purely a
        # planning heuristic, not a real simulation.
        boundary = n_consol - 0.5
        gp = w + l
        steepness = 0.35 + 0.12 * gp
        p_playoff = 1.0 / (1.0 + math.exp(-steepness * (idx - boundary)))
        p_consol = 1.0 - p_playoff
        rows.append({
            "owner": owner, "wins": w, "losses": l, "points_for": pf,
            "p_consolation": round(p_consol, 3),   # -> better lottery odds
            "p_playoff": round(p_playoff, 3),       # -> worse lottery odds
            "proj_weight": round(p_consol * consol_avg + p_playoff * playoff_avg, 2),
        })
    rows.sort(key=lambda r: -r["proj_weight"])
    return rows
