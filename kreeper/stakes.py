"""Game of the Week: what each of this week's games is worth.

For every game on the slate, the rest of the season is simulated twice, once
with each side taking it (the other games this week still play out), using
the Playoffs page's sim (`playoffs.simulate`) and team strengths. The gap
between the two runs, summed over every team, is the game's *stakes*: how
many points of playoff odds it moves across the whole league. The biggest
one is the Game of the Week, picked automatically every week.

Both runs share a random seed, so the small per-team differences (the
"root for" tips, often only 2-3 points) aren't just sim noise.

`h2h` is the two managers' all-time head-to-head, regular season only,
walking Sleeper's previous_league_id chain.
"""
from __future__ import annotations

import copy
from typing import Dict, List, Optional

from . import playoffs, sleeper


def week_stakes(league_id: str, season: int, week: int, n_sims: int = 20000) -> dict:
    """{"week", "playoff_teams", "base": {owner: pct}, "games": [...]}, games
    sorted biggest stakes first, each {a, b, stakes, if_a: {owner: pct},
    if_b: {owner: pct}}. Empty games once the regular season is over."""
    s = playoffs._settings(league_id)
    if week > s["last_regular"]:
        return {"week": week, "playoff_teams": s["playoff_teams"], "base": {}, "games": []}
    teams = playoffs.team_strength(league_id, season, week, s["slots"])
    fx = playoffs.fixtures(league_id, week, s["last_regular"])
    slate = fx.get(week) or []
    n_po = min(s["playoff_teams"], len(teams))
    rest = {w: g for w, g in fx.items() if w != week}

    def run(fixtures, t):
        sim = playoffs.simulate(t, fixtures, n_po, n_sims=n_sims, seed=11, median=s["median"])
        return {o: v["playoff_pct"] for o, v in (sim.get("teams") or {}).items()}

    base = run(fx, teams) if fx else {}
    games = []
    for a, b in slate:
        if a not in teams or b not in teams:
            continue
        others = [(x, y) for x, y in slate if {x, y} != {a, b}]
        outs = []
        for w, l in ((a, b), (b, a)):
            t2 = copy.deepcopy(teams)
            t2[w]["wins"] += 1
            t2[l]["losses"] += 1
            outs.append(run({**rest, week: others} if others else rest, t2))
        stakes = sum(abs(outs[0].get(o, 0) - outs[1].get(o, 0)) for o in teams)
        games.append({"a": a, "b": b, "stakes": stakes, "if_a": outs[0], "if_b": outs[1]})
    games.sort(key=lambda g: -g["stakes"])
    return {"week": week, "playoff_teams": n_po, "base": base, "games": games}


def h2h(league_id: str, a: str, b: str, season: int, week: int) -> dict:
    """All-time regular-season meetings of a and b before (season, week):
    {"a": wins, "b": wins, "games": [(season, week, pts_a, pts_b)], newest first}."""
    out = {"a": 0, "b": 0, "games": []}
    for lg in sleeper.league_chain(league_id):
        lid, yr = lg["league_id"], lg["season"]
        info = sleeper.get_league(lid) or {}
        last = int((info.get("settings") or {}).get("playoff_week_start") or 15) - 1
        if yr == season:
            last = min(last, week - 1)
        r2o = {r["roster_id"]: str(r.get("owner_id")) for r in sleeper.get_rosters(lid) or []}
        for wk in range(last, 0, -1):
            # past seasons never change, so cache them for a week
            rows = sleeper.get_matchups(lid, wk, ttl=1800 if yr == season else 86400 * 7) or []
            by: Dict[int, dict] = {}
            for r in rows:
                if r.get("matchup_id") is not None:
                    by.setdefault(r["matchup_id"], {})[r2o.get(r["roster_id"])] = float(r.get("points") or 0)
            for pts in by.values():
                if a in pts and b in pts and (pts[a] or pts[b]):
                    out["games"].append((yr, wk, pts[a], pts[b]))
                    if pts[a] != pts[b]:
                        out["a" if pts[a] > pts[b] else "b"] += 1
    return out


def rooting(games: List[dict], me: Optional[str]) -> Dict[tuple, Optional[tuple]]:
    """{(a, b): (side_to_root_for, points_it_adds)} for `me`; None for me's own
    game, and a side with 0 points when the result doesn't matter to me."""
    out: Dict[tuple, Optional[tuple]] = {}
    if not me:
        return out
    for g in games:
        if me in (g["a"], g["b"]):
            out[(g["a"], g["b"])] = None
            continue
        da = g["if_a"].get(me, 0) - g["if_b"].get(me, 0)
        out[(g["a"], g["b"])] = (g["a"] if da >= 0 else g["b"], abs(da))
    return out
