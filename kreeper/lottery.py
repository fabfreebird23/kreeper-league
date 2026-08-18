"""Draft-order lottery for The Kreeper League.

House rule (config.yaml has the full text + weights). Reseeded by league vote
2026-08 — see the Rules page for the actual passed motion:
  One combined weighted draw across all `num_teams` teams sets next season's
  DRAFT ORDER directly (lottery rank 1 drafts 1st overall, rank N drafts
  last — this league's lottery sets a position, not a "choose your slot"
  selection order).

  * Consolation-bracket ("Chase for the Pick") teams occupy the best-odds
    ranks. The bracket's LAST-PLACE finisher gets the single best odds
    (they're the team on the hook for the draft-night meal); the bracket
    CHAMPION gets the weakest odds of that group.
  * Championship-bracket (playoff) teams occupy the remaining, worse-odds
    ranks, same inverted direction: the 4th-place playoff finisher (lost in
    round 1) gets the best odds of that group; the league CHAMPION gets the
    single worst odds overall.

  Both brackets invert the SAME way — worst placement in a bracket gets that
  bracket's best odds. (2025 and earlier ran the opposite direction —
  bracket placement mapped straight onto lottery rank, champion-of-each-
  bracket getting the best odds of their group. That direction is NOT a
  historical bug to guard against; it was simply the rule before this vote.
  A distinct, unrelated bug did bite an even-earlier inverted attempt in
  2025: Sleeper's bracket API had the wrong winner recorded in both round-1
  games of the real consolation bracket, confirmed by cross-checking actual
  matchup scores. See `_resolve_bracket_placements` below: placements are
  computed directly from real per-round scores, never from the bracket
  API's own w/l fields, so that specific failure mode can't recur — this
  has nothing to do with which direction the current rule inverts.)

Validated against this league's real 2025 result under the PRE-2026-vote
(non-inverted) direction (see tests/test_lottery.py and the derivation this
was built from — kreeper-league conversation, the 2025 season). The 2026+
inverted direction is new and not yet validated against a real completed
season.

Pure logic module — no Streamlit here.
"""
from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Tuple

from . import config, sleeper


def _roster_to_owner(league_id: str) -> Dict[int, str]:
    return {int(r["roster_id"]): str(r.get("owner_id")) for r in sleeper.get_rosters(league_id)}


def _weeks_per_round(league_id: str) -> int:
    """Sleeper's `playoff_round_type`: 0 = one scored week per round; any other
    value = a combined two-week round (this league uses type 2)."""
    settings = sleeper.get_league(league_id).get("settings", {}) or {}
    return 1 if int(settings.get("playoff_round_type", 0) or 0) == 0 else 2


def _round_scores(league_id: str, round_num: int, playoff_week_start: int, wpr: int) -> Dict[int, float]:
    """roster_id -> total real points across the week(s) that make up this
    playoff round."""
    start = playoff_week_start + (round_num - 1) * wpr
    totals: Dict[int, float] = {}
    for wk in range(start, start + wpr):
        for m in sleeper.get_matchups(league_id, wk):
            rid = m.get("roster_id")
            if rid is None:
                continue
            totals[rid] = totals.get(rid, 0.0) + float(m.get("points") or 0)
    return totals


def _resolve_bracket_placements(bracket: List[Dict[str, Any]], league_id: str) -> Dict[int, int]:
    """{placement: roster_id} for a bracket (winners_ or losers_bracket),
    determined from REAL per-round scores — never from the bracket API's own
    `w`/`l` fields, which have been observed stale/wrong for this league's
    multi-week playoff rounds (see the module docstring). `t1`/`t2` (who's
    scheduled to play whom) are trusted — that's been reliable in every case
    checked — only the WINNER of each game is independently recomputed.

    Each team's true win/lose result in every prior round is tracked so a
    round's games can be grouped by "both participants won their previous
    round" (-> the true higher-placement decider) vs "both lost" (-> the
    true lower-placement decider), rather than trusting which `p` tag
    Sleeper's own (possibly-buggy) bracket-building attached to each game.

    Returns {} if any game needed to fully resolve is unscheduled or its
    round's scores aren't in yet — read as "not complete."
    """
    if not bracket:
        return {}
    settings = sleeper.get_league(league_id).get("settings", {}) or {}
    playoff_start = int(settings.get("playoff_week_start") or 1)
    wpr = _weeks_per_round(league_id)

    by_round: Dict[int, List[Dict[str, Any]]] = {}
    for g in bracket:
        by_round.setdefault(int(g.get("r") or 0), []).append(g)

    result: Dict[int, str] = {}       # (round, roster_id) key below, flattened as f"{r}:{rid}"
    winner_of: Dict[int, int] = {}    # matchup id -> winning roster_id (real, score-based)
    loser_of: Dict[int, int] = {}

    def key(r, rid):
        return f"{r}:{rid}"

    for r in sorted(by_round):
        scores = _round_scores(league_id, r, playoff_start, wpr)
        for g in by_round[r]:
            t1, t2 = g.get("t1"), g.get("t2")
            if t1 is None or t2 is None:
                return {}  # this round isn't scheduled yet
            s1, s2 = scores.get(t1), scores.get(t2)
            if s1 is None or s2 is None or s1 == s2:
                return {}  # scores not in yet, or an unresolved tie
            w, l = (t1, t2) if s1 > s2 else (t2, t1)
            winner_of[g["m"]], loser_of[g["m"]] = w, l
            result[key(r, w)] = "win"
            result[key(r, l)] = "lose"

    # Final round's `p`-tagged games decide placements. Group by each game's
    # participants' shared result in the PRIOR round (both won -> the true
    # top-half decider; both lost -> the true bottom-half decider) instead of
    # trusting Sleeper's own p-tag-to-game assignment, since that assignment
    # is itself built from the same (possibly-wrong) round-by-round advancement.
    last_round = max(by_round)
    placements: Dict[int, int] = {}
    for g in by_round[last_round]:
        p = g.get("p")
        if not p:
            continue
        t1, t2 = g["t1"], g["t2"]
        w, l = winner_of[g["m"]], loser_of[g["m"]]
        if last_round > 1:
            prior = {result.get(key(last_round - 1, t1)), result.get(key(last_round - 1, t2))}
        else:
            prior = set()  # single-round bracket -> nothing to disambiguate against
        if prior == {"win"}:
            placements[1], placements[2] = w, l
        elif prior == {"lose"}:
            placements[3], placements[4] = w, l
        else:
            # Can't disambiguate (bracket deeper than 2 rounds, or a bye) —
            # fall back to trusting this game's own p tag.
            placements[p], placements[p + 1] = w, l
    return placements


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
    placement game decided (per real scores, not the bracket API's own
    w/l fields)."""
    league_id = league_id or config.league()["sleeper_league_id"]
    wb = sleeper.get_winners_bracket(league_id)
    lb = sleeper.get_losers_bracket(league_id)
    return bool(_resolve_bracket_placements(wb, league_id)) and \
        bool(_resolve_bracket_placements(lb, league_id))


def final_tiers(league_id: Optional[str] = None) -> Optional[Dict[str, Dict[str, Any]]]:
    """For a COMPLETED season: {owner_id: {"weight", "tier", "rank",
    "bracket_placement"}} for every team. Returns None if either bracket
    isn't fully decided yet — callers should treat that as "not ready".

    Placement is INVERTED onto lottery rank within each bracket (2026 vote):
    the consolation bracket's LAST-place finisher gets the single best odds;
    the championship bracket's last-place (4th) finisher gets the best odds
    of the (worse) playoff group, and the league champion the worst odds
    overall. See the module docstring.
    """
    league_id = league_id or config.league()["sleeper_league_id"]
    wb = sleeper.get_winners_bracket(league_id)
    lb = sleeper.get_losers_bracket(league_id)
    wb_places = _resolve_bracket_placements(wb, league_id)
    lb_places = _resolve_bracket_placements(lb, league_id)
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
    # Consolation bracket, ranks 1..n_consol — INVERTED: the bracket's
    # last-place finisher (placement n_consol) takes rank 1 / the best odds;
    # the bracket champion (placement 1) falls to rank n_consol.
    for literal_placement in range(1, n_consol + 1):
        lottery_rank = n_consol - literal_placement + 1
        owner = r2o.get(lb_places.get(literal_placement))
        out[owner] = {
            "weight": weights[lottery_rank - 1],
            "tier": "consolation",
            "rank": lottery_rank,
            "bracket_placement": literal_placement,
        }
    # Championship bracket, ranks (n_consol+1)..(n_consol+n_playoff) — same
    # inversion: the 4th-place playoff finisher takes the best odds of this
    # group, the league champion (placement 1) the worst odds overall.
    for literal_placement in range(1, n_playoff + 1):
        lottery_rank = n_consol + (n_playoff - literal_placement + 1)
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


def _expected_weight_given_group(
    members: List[Tuple[str, float]], group_weights: List[float]
) -> Dict[str, float]:
    """members: [(owner, positive_strength), ...] for exactly len(group_weights)
    teams. group_weights are that bracket's lottery weights, BEST first (e.g.
    the consolation group's [25, 22, 19, 14]). Returns owner -> expected
    lottery weight.

    `position_probabilities` still models the STRONGEST member of the group as
    most likely to WIN that bracket — that part is just how a mini-tournament
    plays out and hasn't changed. What changed with the 2026 vote is the
    payoff: winning your bracket now claims that group's WORST weight, so
    finish position i (i=0 = bracket champion) maps to group_weights
    reversed. Net effect on projections: within the consolation group the
    very worst team now projects the BEST odds, where it used to be the team
    closest to the playoff cutoff."""
    if not members:
        return {}
    power = {o: max(1e-6, s) for o, s in members}
    probs = position_probabilities(power)
    payoff = list(reversed(group_weights))  # bracket champion -> worst weight
    return {o: sum(probs[o][i] * payoff[i] for i in range(len(payoff))) for o, _ in members}


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
    # Assumed group membership: the n_consol weakest teams / n_playoff
    # strongest, using a positive win%+points-for strength proxy so the
    # STRONGEST of each assumed group is favored to win that bracket.
    strength = {o: 1.0 + win_pct(w, l) * 10 + pf / 1000 for o, w, l, pf in ranked}
    consol_members = [(o, strength[o]) for o, *_ in ranked[:n_consol]]
    playoff_members = [(o, strength[o]) for o, *_ in ranked[n_consol:]]
    consol_exp = _expected_weight_given_group(consol_members, weights[:n_consol])
    playoff_exp = _expected_weight_given_group(playoff_members, weights[n_consol:])
    # Flat-average fallback for the cross-group term (e.g. a team assumed
    # playoff-bound still has SOME chance of ending up in consolation) —
    # only matters for teams near the boundary, where that probability is
    # small, so a flat average there is a fine approximation.
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
        e_consol = consol_exp.get(owner, consol_avg)
        e_playoff = playoff_exp.get(owner, playoff_avg)
        rows.append({
            "owner": owner, "wins": w, "losses": l, "points_for": pf,
            "p_consolation": round(p_consol, 3),   # -> better lottery odds
            "p_playoff": round(p_playoff, 3),       # -> worse lottery odds
            "proj_weight": round(p_consol * e_consol + p_playoff * e_playoff, 2),
        })
    rows.sort(key=lambda r: -r["proj_weight"])
    return rows


def preseason_projection(
    power: Dict[str, float], playoff_teams: Optional[int] = None, weights: Optional[List[float]] = None,
) -> List[Dict[str, Any]]:
    """Before the season starts (or before enough games exist for
    `live_projection` to have real signal): project each team's likely
    lottery tier from a PRE-SEASON strength signal instead of in-season
    record. `power`: owner_id -> relative strength (higher = stronger team,
    more likely to make the playoffs) — e.g. the same blended history +
    keeper-strength signal the Title Odds page uses. Deliberately uses a
    fixed, modest confidence (no games played yet to sharpen with), so this
    reads softer/less certain than `live_projection` once real games start.
    Returns [] if `power` is empty (nothing to project from).
    """
    weights = weights if weights is not None else config.lottery_weights()
    n = len(weights)
    playoff_teams = playoff_teams or n // 2
    n_consol = n - playoff_teams
    if not power:
        return []

    # Weakest (lowest power) first -> most likely consolation-bound.
    ranked = sorted(power.items(), key=lambda kv: kv[1])
    # Within each assumed group, the STRONGEST member is favored to win that
    # bracket (same reasoning as live_projection — see _expected_weight_given_group).
    consol_members = ranked[:n_consol]
    playoff_members = ranked[n_consol:]
    consol_exp = _expected_weight_given_group(consol_members, weights[:n_consol])
    playoff_exp = _expected_weight_given_group(playoff_members, weights[n_consol:])
    consol_avg = sum(weights[:n_consol]) / n_consol
    playoff_avg = sum(weights[n_consol:]) / playoff_teams
    boundary = n_consol - 0.5
    steepness = 0.5  # fixed and modest — there's no in-season signal to sharpen with yet

    rows = []
    for idx, (owner, p) in enumerate(ranked):
        p_playoff = 1.0 / (1.0 + math.exp(-steepness * (idx - boundary)))
        p_consol = 1.0 - p_playoff
        e_consol = consol_exp.get(owner, consol_avg)
        e_playoff = playoff_exp.get(owner, playoff_avg)
        rows.append({
            "owner": owner,
            "power_rank": idx + 1,
            "p_consolation": round(p_consol, 3),
            "p_playoff": round(p_playoff, 3),
            "proj_weight": round(p_consol * e_consol + p_playoff * e_playoff, 2),
        })
    rows.sort(key=lambda r: -r["proj_weight"])
    return rows
