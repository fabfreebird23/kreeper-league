"""The Playoffs page: the rest of the regular season, played 10,000 times.

Ported from the Draft Room's Playoffs tab (draftkit.weekly.season_sim) so the
league hubs answer the same questions the Draft Room does:

  * how likely each team is to make it, and where they're likely to seed;
  * for YOU: where you finish, your win % each remaining week, and the one
    game that moves your playoff odds the most;
  * how your starters' playoff-week matchups look, judged on THIS season's
    defenses (points allowed per game, so a bye doesn't flatter anyone).

Self-contained on purpose — it only needs this package's `sleeper` and
`gameday` modules, which every hub (Kreeper, B&B, 7½ Men) has with the same
API — so the same file drops into each one.

Team strength is the best legal lineup by this week's Sleeper projections,
blended 60/40 with the team's actual scoring average once two weeks are in
the books: projections see this week's roster (trades, injuries), the actual
average sees how the team has really played.
"""
from __future__ import annotations

import json
import math
import random
import time
from typing import Dict, List, Optional, Tuple

import requests

from . import config, gameday, sleeper

_STATS = "https://api.sleeper.com/stats/nfl/{season}/{week}?season_type=regular"
_SKILL = ("QB", "RB", "WR", "TE")
_BENCH = {"BN", "TAXI", "IR"}


# ---------------------------------------------------------------- inputs
def _settings(league_id: str) -> dict:
    lg = sleeper.get_league(league_id) or {}
    st = lg.get("settings") or {}
    start = int(st.get("playoff_week_start") or 15)
    teams = int(st.get("playoff_teams") or 0) or None
    slots = [s for s in (lg.get("roster_positions") or []) if s not in _BENCH]
    # Sleeper's bracket: 4 teams = 2 rounds, 6-8 = 3 rounds; a round can be two
    # weeks long ("playoff_round_type" 1 = two-week final, 2 = all two-week)
    n = teams or max(2, int(st.get("num_teams") or 8) // 2)
    rounds = 2 if n <= 4 else 3
    rtype = int(st.get("playoff_round_type") or 0)
    weeks = rounds + (1 if rtype == 1 else rounds if rtype == 2 else 0)
    return {"playoff_teams": n, "start": start, "last_regular": start - 1,
            # B&B and 7½ Men also play the league median every week: a second
            # result, a win for every team in the top half. 6-4 after five weeks.
            "median": bool(int(st.get("league_average_match") or 0)),
            "playoff_weeks": list(range(start, min(18, start + weeks - 1) + 1)), "slots": slots}


def fixtures(league_id: str, first: int, last: int) -> Dict[int, List[Tuple[str, str]]]:
    """{week: [(owner_a, owner_b), ...]} for the weeks still to play."""
    r2o = {r["roster_id"]: str(r.get("owner_id")) for r in sleeper.get_rosters(league_id) or []}
    out: Dict[int, List[Tuple[str, str]]] = {}
    for wk in range(int(first), int(last) + 1):
        try:
            rows = sleeper.get_matchups(league_id, wk) or []
        except Exception:  # noqa: BLE001
            continue
        by: Dict[int, list] = {}
        for r in rows:
            if r.get("matchup_id") is not None:
                by.setdefault(r["matchup_id"], []).append(r2o.get(r["roster_id"]))
        pairs = [tuple(v) for v in by.values() if len(v) == 2 and all(v)]
        if pairs:
            out[wk] = pairs
    return out


def team_strength(league_id: str, season: int, week: int, slots: List[str]) -> dict:
    """{owner: {mean, sd, wins, losses, pf, games}} — see the module note."""
    players = sleeper.get_players() or {}
    pos_of = {str(k): (v.get("position") or "") for k, v in players.items()}
    proj = gameday.week_projections(season, week) or {}
    out = {}
    for r in sleeper.get_rosters(league_id) or []:
        owner = str(r.get("owner_id") or "")
        if not owner:
            continue
        se = r.get("settings") or {}
        wins, losses, ties = int(se.get("wins") or 0), int(se.get("losses") or 0), int(se.get("ties") or 0)
        pf = float(se.get("fpts") or 0) + float(se.get("fpts_decimal") or 0) / 100
        games = wins + losses + ties
        lineup = gameday.optimal_lineup(r.get("players") or [], slots, proj, pos_of) if proj else []
        pm = sum(float(proj.get(p, 0) or 0) for _s, p in lineup if p)
        var = sum(gameday.player_sd(pos_of.get(p, ""), float(proj.get(p, 0) or 0)) ** 2
                  for _s, p in lineup if p)
        actual = pf / games if games else None
        if pm and actual and games >= 2:
            mean = 0.6 * pm + 0.4 * actual
        else:
            mean = pm or actual or 100.0
        out[owner] = {"mean": mean, "sd": math.sqrt(var) if var else 22.0, "wins": wins,
                      "losses": losses, "ties": ties, "pf": pf, "games": games,
                      "proj": pm, "actual": actual}
    return out


# ------------------------------------------------------------------ sim
def simulate(teams: dict, schedule: Dict[int, List[Tuple[str, str]]], playoff_teams: int,
             me: Optional[str] = None, n_sims: int = 10000, seed: int = 7,
             median: bool = False) -> dict:
    """The rest of the season on the real fixture list.

    {"teams": {owner: {playoff_pct, avg_seed}}, "seeds": [% per seed] for `me`,
     "weeks": [{week, opp, p_win, if_win, if_lose, swing}] for `me`}.
    Ties on wins go to points for (season so far + simulated), which is how
    Sleeper seeds by default. `swing` is how far one game moves `me`'s odds.
    """
    rng = random.Random(seed)
    owners = sorted(teams)
    n = len(owners)
    if n < 2:
        return {}
    made = {o: 0 for o in owners}
    seed_sum = {o: 0.0 for o in owners}
    seeds = [0] * n
    weeks = sorted(schedule)
    # per week of mine: [wins, made|win, made|loss, losses]
    mine = {wk: [0, 0, 0, 0] for wk in weeks}
    my_opp = {}
    for _ in range(n_sims):
        wins = {o: teams[o]["wins"] + 0.5 * teams[o].get("ties", 0) for o in owners}
        pf = {o: teams[o]["pf"] for o in owners}
        my_res = {}
        for wk in weeks:
            week_pts = {}
            for a, b in schedule[wk]:
                if a not in teams or b not in teams:
                    continue
                sa = rng.gauss(teams[a]["mean"], teams[a]["sd"])
                sb = rng.gauss(teams[b]["mean"], teams[b]["sd"])
                week_pts[a], week_pts[b] = sa, sb
                pf[a] += sa
                pf[b] += sb
                win_a = sa >= sb
                wins[a if win_a else b] += 1
                if me in (a, b):
                    my_res[wk] = win_a if me == a else not win_a
                    my_opp[wk] = b if me == a else a
            if median and week_pts:
                for o in sorted(week_pts, key=week_pts.get, reverse=True)[:len(week_pts) // 2]:
                    wins[o] += 1
        order = sorted(owners, key=lambda o: (-wins[o], -pf[o]))
        for i, o in enumerate(order):
            seed_sum[o] += i + 1
            if i < playoff_teams:
                made[o] += 1
        if me in teams:
            rank = order.index(me)
            seeds[rank] += 1
            ok = rank < playoff_teams
            for wk, won in my_res.items():
                m = mine[wk]
                if won:
                    m[0] += 1
                    m[1] += ok
                else:
                    m[3] += 1
                    m[2] += ok
    out = {"teams": {o: {"playoff_pct": round(100 * made[o] / n_sims),
                         "avg_seed": round(seed_sum[o] / n_sims, 1)} for o in owners},
           "seeds": [round(100 * s / n_sims) for s in seeds] if me in teams else [],
           "weeks": []}
    for wk in weeks:
        w, mw, ml, l = mine[wk]
        if not (w or l) or wk not in my_opp:
            continue
        iw = 100 * mw / w if w else 0.0
        il = 100 * ml / l if l else 0.0
        out["weeks"].append({"week": wk, "opp": my_opp[wk], "p_win": round(100 * w / (w + l)),
                             "if_win": round(iw), "if_lose": round(il), "swing": round(iw - il)})
    return out


# ------------------------------------------------- playoff-week matchups
def _week_stats(season: int, week: int) -> list:
    """[{o: opponent, p: pid, s: {pts_*}}] for one played week, disk-cached."""
    p = gameday._cache_dir() / f"stats_{season}_{week}.json"
    if p.exists() and time.time() - p.stat().st_mtime < 3 * 86400:
        try:
            return json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            pass
    try:
        raw = requests.get(_STATS.format(season=season, week=week), timeout=20).json() or []
    except Exception:  # noqa: BLE001
        return json.loads(p.read_text()) if p.exists() else []
    rows = [{"o": r.get("opponent"), "p": str(r.get("player_id")),
             "s": {k: v for k, v in (r.get("stats") or {}).items() if k.startswith("pts_")}}
            for r in raw if r.get("opponent") and r.get("player_id") is not None]
    if rows:
        p.write_text(json.dumps(rows))
    return rows


def dvp(season: int, through_week: int, pos_of: Dict[str, str], key: str = "pts_ppr"):
    """({pos: {defense: rank}}, label) from THIS season's weeks played — rank 1
    = stingiest by fantasy points allowed per game. With under three weeks in,
    last season counts as two games of prior that fades out."""
    def allowed(s, weeks):
        pts = {p: {} for p in _SKILL}
        gms = {p: {} for p in _SKILL}
        for wk in weeks:
            seen = set()
            for r in _week_stats(s, wk):
                v = (r.get("s") or {}).get(key)
                pos = pos_of.get(r["p"])
                if v is None or pos not in pts:
                    continue
                pts[pos][r["o"]] = pts[pos].get(r["o"], 0.0) + float(v)
                if (pos, r["o"]) not in seen:
                    seen.add((pos, r["o"]))
                    gms[pos][r["o"]] = gms[pos].get(r["o"], 0) + 1
        return pts, gms

    done = max(0, int(through_week))
    pts, gms = allowed(season, range(1, done + 1))
    prior_w = 2.0 if done < 3 else 0.0
    if prior_w:
        ppts, pgms = allowed(season - 1, range(1, 19))
    out = {}
    for pos in _SKILL:
        per = {}
        for t in set(pts[pos]) | (set(ppts[pos]) if prior_w else set()):
            g, tot = gms[pos].get(t, 0), pts[pos].get(t, 0.0)
            if prior_w and pgms[pos].get(t):
                per[t] = (tot + ppts[pos][t] / pgms[pos][t] * prior_w) / (g + prior_w)
            elif g:
                per[t] = tot / g
        out[pos] = {t: i + 1 for i, (t, _v) in enumerate(sorted(per.items(), key=lambda x: x[1]))}
    label = f"{season} through week {done}" + (", blended with last season" if prior_w else "")
    return out, label


def playoff_slate(league_id: str, season: int, week: int, owner: str, slots: List[str],
                  playoff_weeks: List[int]) -> dict:
    """Your starters' opponents in the playoff weeks, each graded on this
    season's defense-vs-position. {"rows": [...], "label": str}"""
    players = sleeper.get_players() or {}
    pos_of = {str(k): (v.get("position") or "") for k, v in players.items()}
    roster = next((r for r in sleeper.get_rosters(league_id) or []
                   if str(r.get("owner_id")) == str(owner)), None)
    if not roster:
        return {"rows": [], "label": ""}
    proj = gameday.week_projections(season, week) or {}
    lineup = gameday.optimal_lineup(roster.get("players") or [], slots, proj, pos_of)
    ranks, label = dvp(season, max(0, week - 1), pos_of)
    n_def = max([len(v) for v in ranks.values()] or [32])
    games = {wk: gameday.load_week(season, wk) for wk in playoff_weeks}
    rows = []
    for slot, pid in lineup:
        pos = pos_of.get(str(pid or ""))
        if not pid or pos not in _SKILL:
            continue
        p = players.get(str(pid)) or {}
        team = (p.get("team") or "").upper()
        wks, rs = [], []
        for wk in playoff_weeks:
            g = (games.get(wk) or {}).get(team)
            if not g:
                wks.append((wk, "bye", None))
                continue
            r = (ranks.get(pos) or {}).get(g["opp"])
            wks.append((wk, ("vs " if g.get("home") else "@ ") + g["opp"], r))
            if r:
                rs.append(r)
        avg = sum(rs) / len(rs) if rs else None
        grade = (None if avg is None else "easy" if avg > n_def * 0.62 else
                 "hard" if avg < n_def * 0.38 else "avg")
        rows.append({"pid": str(pid), "name": p.get("full_name") or pid, "pos": pos, "team": team,
                     "slot": slot, "weeks": wks, "avg": avg, "grade": grade})
    return {"rows": rows, "label": label, "n_def": n_def}


# ---------------------------------------------------------------- page
def outlook(league_id: Optional[str] = None, season: Optional[int] = None,
            week: Optional[int] = None, me: Optional[str] = None, n_sims: int = 10000) -> dict:
    """Everything the Playoffs page shows, in one call."""
    if not league_id:
        lg = config.league()
        league_id = lg.get("sleeper_league_id") or lg.get("id")
    state = sleeper.get_nfl_state() if hasattr(sleeper, "get_nfl_state") else {}
    season = int(season or (state or {}).get("season") or time.gmtime().tm_year)
    week = int(week or (state or {}).get("week") or 1)
    s = _settings(league_id)
    teams = team_strength(league_id, season, week, s["slots"])
    weeks_left = max(0, s["last_regular"] - week + 1)
    fx = fixtures(league_id, week, s["last_regular"]) if weeks_left else {}
    sim = simulate(teams, fx, min(s["playoff_teams"], len(teams)), me=me, n_sims=n_sims,
                   median=s["median"]) if fx else {}
    return {"season": season, "week": week, "settings": s, "teams": teams, "sim": sim,
            "weeks_left": weeks_left, "fixtures": fx}
