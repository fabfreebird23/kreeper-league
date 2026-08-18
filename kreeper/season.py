"""Live in-season state for The Kreeper League — standings, weekly results,
schedule, and the derived views built on top of them (power ranking, luck,
playoff odds).

Everything here is driven by what actually happened on the field this season:
real per-week scores from Sleeper's matchups endpoint, not the pre-season
history+keeper power model that drives Title Odds (see app.team_power). The
two are deliberately separate — this one knows nothing about keepers and
only starts saying anything once games have been played.

Sleeper pairs opponents by a shared `matchup_id` within a week; a week with
no matchup_id (or no scores yet) is treated as not played.

Pure logic module — no Streamlit here.
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

from . import config, sleeper


def _roster_to_owner(league_id: str) -> Dict[int, str]:
    return {int(r["roster_id"]): str(r.get("owner_id")) for r in sleeper.get_rosters(league_id)}


def regular_season_weeks(league_id: Optional[str] = None) -> int:
    """Weeks 1..N-1 where N is Sleeper's `playoff_week_start` — i.e. every week
    that counts toward the regular-season standings."""
    league_id = league_id or config.league()["sleeper_league_id"]
    settings = sleeper.get_league(league_id).get("settings", {}) or {}
    return max(0, int(settings.get("playoff_week_start") or 15) - 1)


def current_week(league_id: Optional[str] = None) -> int:
    """The league's current week per Sleeper's global NFL clock, clamped to
    this league's regular season. 0 means the season hasn't started."""
    state = sleeper.get_nfl_state() or {}
    if str(state.get("season_type") or "") in ("pre", "off"):
        return 0
    try:
        wk = int(state.get("week") or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(wk, regular_season_weeks(league_id)))


def week_results(league_id: Optional[str] = None, week: int = 1) -> List[Dict[str, Any]]:
    """One week's head-to-head results:
    [{matchup_id, home: {owner, roster_id, points}, away: {...},
      winner: owner|None, tie: bool, margin: float}].

    Returns [] if the week hasn't been played (no scores posted yet). A
    matchup with only one side present (bye, or a mid-season roster removal)
    is skipped rather than guessed at.
    """
    league_id = league_id or config.league()["sleeper_league_id"]
    rows = sleeper.get_matchups(league_id, week) or []
    r2o = _roster_to_owner(league_id)

    by_matchup: Dict[Any, List[Dict[str, Any]]] = {}
    for m in rows:
        mid = m.get("matchup_id")
        rid = m.get("roster_id")
        if mid is None or rid is None:
            continue
        by_matchup.setdefault(mid, []).append(m)

    out: List[Dict[str, Any]] = []
    for mid, sides in sorted(by_matchup.items(), key=lambda kv: (kv[0] is None, kv[0])):
        if len(sides) != 2:
            continue
        a, b = sides
        pa, pb = float(a.get("points") or 0), float(b.get("points") or 0)
        # Both sides at exactly 0 means the week hasn't been scored yet —
        # a real 0.0 fantasy score is possible in theory but not for two
        # full lineups simultaneously.
        if pa == 0 and pb == 0:
            continue
        home = {"owner": r2o.get(int(a["roster_id"])), "roster_id": int(a["roster_id"]), "points": round(pa, 2)}
        away = {"owner": r2o.get(int(b["roster_id"])), "roster_id": int(b["roster_id"]), "points": round(pb, 2)}
        tie = pa == pb
        out.append({
            "matchup_id": mid,
            "home": home, "away": away,
            "winner": None if tie else (home["owner"] if pa > pb else away["owner"]),
            "tie": tie,
            "margin": round(abs(pa - pb), 2),
        })
    return out


def season_results(league_id: Optional[str] = None,
                   through_week: Optional[int] = None) -> Dict[int, List[Dict[str, Any]]]:
    """{week: [result, ...]} for every played regular-season week."""
    league_id = league_id or config.league()["sleeper_league_id"]
    last = through_week if through_week is not None else regular_season_weeks(league_id)
    out: Dict[int, List[Dict[str, Any]]] = {}
    for wk in range(1, last + 1):
        res = week_results(league_id, wk)
        if res:
            out[wk] = res
    return out


def standings(league_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Live standings, best first: [{owner, wins, losses, ties, points_for,
    points_against, streak, rank, weeks_played}].

    Sorted on (wins desc, points_for desc) — deliberately the same tiebreak
    Sleeper itself shows, so this page can never disagree with the app the
    league actually plays on.

    Record comes from the real week-by-week results rather than Sleeper's
    roster `settings.wins`, so it stays consistent with the matchup views
    here and can be recomputed for any prefix of the season.
    """
    league_id = league_id or config.league()["sleeper_league_id"]
    r2o = _roster_to_owner(league_id)
    tally: Dict[str, Dict[str, Any]] = {
        o: {"owner": o, "wins": 0, "losses": 0, "ties": 0,
            "points_for": 0.0, "points_against": 0.0, "results": []}
        for o in r2o.values() if o
    }

    results = season_results(league_id)
    for wk in sorted(results):
        for g in results[wk]:
            for side, opp in ((g["home"], g["away"]), (g["away"], g["home"])):
                rec = tally.get(side["owner"])
                if rec is None:
                    continue
                rec["points_for"] += side["points"]
                rec["points_against"] += opp["points"]
                if g["tie"]:
                    rec["ties"] += 1
                    rec["results"].append("T")
                elif g["winner"] == side["owner"]:
                    rec["wins"] += 1
                    rec["results"].append("W")
                else:
                    rec["losses"] += 1
                    rec["results"].append("L")

    rows = sorted(tally.values(), key=lambda r: (-r["wins"], -r["points_for"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["weeks_played"] = len(r["results"])
        r["points_for"] = round(r["points_for"], 2)
        r["points_against"] = round(r["points_against"], 2)
        r["streak"] = _streak(r["results"])
    return rows


def _streak(results: List[str]) -> str:
    """Trailing run as e.g. "W3" / "L2". Empty string with no games played."""
    if not results:
        return ""
    last = results[-1]
    n = 0
    for r in reversed(results):
        if r != last:
            break
        n += 1
    return f"{last}{n}"


def luck(league_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """How much of each team's record is schedule luck.

    `expected_wins` is what they'd have if every week they'd played the whole
    league instead of one opponent: each week, the fraction of teams they
    outscored. `luck` is actual wins minus that — positive means the schedule
    has been kind. Best-record-first, same order as standings().
    """
    league_id = league_id or config.league()["sleeper_league_id"]
    results = season_results(league_id)

    expected: Dict[str, float] = {}
    for wk in sorted(results):
        scores = []
        for g in results[wk]:
            scores.append((g["home"]["owner"], g["home"]["points"]))
            scores.append((g["away"]["owner"], g["away"]["points"]))
        n = len(scores)
        if n < 2:
            continue
        for owner, pts in scores:
            beat = sum(1 for o, p in scores if o != owner and pts > p)
            drew = sum(1 for o, p in scores if o != owner and pts == p)
            expected[owner] = expected.get(owner, 0.0) + (beat + 0.5 * drew) / (n - 1)

    out = []
    for row in standings(league_id):
        exp = round(expected.get(row["owner"], 0.0), 2)
        out.append({
            "owner": row["owner"],
            "wins": row["wins"],
            "expected_wins": exp,
            "luck": round(row["wins"] - exp, 2),
            "points_for": row["points_for"],
        })
    return out


def power_rankings(league_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Results-driven power ranking, strongest first: [{owner, score, rank,
    win_pct, points_for, recent_avg, rank_delta}].

    Blends three signals a plain standings table hides: win rate (did you
    win), scoring rate (are you actually good), and recent form (are you
    good NOW — last 3 weeks weighted separately so a hot team climbs past a
    team that front-loaded a soft schedule). `rank_delta` is power rank vs.
    standings rank: positive means underrated by the standings.

    Returns [] before any games are played — there's no signal to rank on,
    and a fabricated ranking would read as real.
    """
    league_id = league_id or config.league()["sleeper_league_id"]
    table = standings(league_id)
    if not table or not any(r["weeks_played"] for r in table):
        return []

    results = season_results(league_id)
    weeks = sorted(results)
    recent_weeks = weeks[-3:]

    per_week: Dict[str, List[float]] = {}
    for wk in weeks:
        for g in results[wk]:
            for side in (g["home"], g["away"]):
                per_week.setdefault(side["owner"], []).append(side["points"])
    recent: Dict[str, List[float]] = {}
    for wk in recent_weeks:
        for g in results[wk]:
            for side in (g["home"], g["away"]):
                recent.setdefault(side["owner"], []).append(side["points"])

    def avg(xs):
        return sum(xs) / len(xs) if xs else 0.0

    all_avgs = [avg(v) for v in per_week.values()] or [0.0]
    lo, hi = min(all_avgs), max(all_avgs)
    span = (hi - lo) or 1.0
    recent_avgs = [avg(v) for v in recent.values()] or [0.0]
    rlo, rhi = min(recent_avgs), max(recent_avgs)
    rspan = (rhi - rlo) or 1.0

    scored = []
    for row in table:
        o = row["owner"]
        gp = row["weeks_played"] or 1
        win_pct = (row["wins"] + 0.5 * row["ties"]) / gp
        scoring = (avg(per_week.get(o, [])) - lo) / span
        form = (avg(recent.get(o, [])) - rlo) / rspan
        score = 0.45 * win_pct + 0.35 * scoring + 0.20 * form
        scored.append({
            "owner": o,
            "score": round(score * 100, 1),
            "win_pct": round(win_pct, 3),
            "points_for": row["points_for"],
            "recent_avg": round(avg(recent.get(o, [])), 1),
            "_standings_rank": row["rank"],
        })

    scored.sort(key=lambda r: -r["score"])
    for i, r in enumerate(scored, 1):
        r["rank"] = i
        r["rank_delta"] = r.pop("_standings_rank") - i
    return scored


def remaining_schedule(league_id: Optional[str] = None) -> Dict[int, List[Tuple[str, str]]]:
    """{week: [(owner_a, owner_b), ...]} for regular-season weeks not yet
    played. Sleeper only exposes the schedule via the matchups endpoint, so
    an unplayed week still returns its pairings (with zero points) — that's
    what makes forecasting the rest of the season possible.
    """
    league_id = league_id or config.league()["sleeper_league_id"]
    r2o = _roster_to_owner(league_id)
    played = set(season_results(league_id))
    out: Dict[int, List[Tuple[str, str]]] = {}
    for wk in range(1, regular_season_weeks(league_id) + 1):
        if wk in played:
            continue
        by_matchup: Dict[Any, List[int]] = {}
        for m in sleeper.get_matchups(league_id, wk) or []:
            mid, rid = m.get("matchup_id"), m.get("roster_id")
            if mid is None or rid is None:
                continue
            by_matchup.setdefault(mid, []).append(int(rid))
        pairs = [
            (r2o.get(sides[0]), r2o.get(sides[1]))
            for sides in by_matchup.values()
            if len(sides) == 2 and r2o.get(sides[0]) and r2o.get(sides[1])
        ]
        if pairs:
            out[wk] = pairs
    return out


def playoff_odds(league_id: Optional[str] = None, playoff_teams: Optional[int] = None,
                 trials: int = 10000, seed: Optional[int] = 12345) -> List[Dict[str, Any]]:
    """Monte-Carlo playoff odds from where the season actually stands:
    [{owner, odds, proj_wins, current_wins, rank}] best-first.

    Each remaining game is simulated from the two teams' scoring
    distributions so far (normal around their mean, spread by their own
    week-to-week standard deviation), then the final table is sorted by the
    league's real tiebreak (wins, then points-for) and the top
    `playoff_teams` make it.

    Seeded by default so the number doesn't twitch on every rerun — this is
    a projection, and a page that shows 61% then 59% for no reason reads as
    broken. Returns [] before any games are played.
    """
    league_id = league_id or config.league()["sleeper_league_id"]
    table = standings(league_id)
    if not table or not any(r["weeks_played"] for r in table):
        return []
    playoff_teams = playoff_teams or max(1, len(table) // 2)

    results = season_results(league_id)
    scores: Dict[str, List[float]] = {}
    for wk in sorted(results):
        for g in results[wk]:
            for side in (g["home"], g["away"]):
                scores.setdefault(side["owner"], []).append(side["points"])

    def mean(xs):
        return sum(xs) / len(xs) if xs else 100.0

    def stdev(xs):
        if len(xs) < 2:
            return 20.0
        m = mean(xs)
        return max(1.0, (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5)

    mu = {o: mean(v) for o, v in scores.items()}
    sd = {o: stdev(v) for o, v in scores.items()}
    base = {r["owner"]: (r["wins"], r["points_for"]) for r in table}
    rest = remaining_schedule(league_id)

    rng = random.Random(seed)
    made = {r["owner"]: 0 for r in table}
    win_total = {r["owner"]: 0.0 for r in table}

    for _ in range(trials):
        wins = {o: w for o, (w, _pf) in base.items()}
        pf = {o: p for o, (_w, p) in base.items()}
        for _wk, pairs in rest.items():
            for a, b in pairs:
                sa = rng.gauss(mu.get(a, 100.0), sd.get(a, 20.0))
                sb = rng.gauss(mu.get(b, 100.0), sd.get(b, 20.0))
                pf[a] = pf.get(a, 0.0) + sa
                pf[b] = pf.get(b, 0.0) + sb
                if sa >= sb:
                    wins[a] = wins.get(a, 0) + 1
                else:
                    wins[b] = wins.get(b, 0) + 1
        order = sorted(wins, key=lambda o: (-wins[o], -pf.get(o, 0.0)))
        for o in order[:playoff_teams]:
            made[o] += 1
        for o, w in wins.items():
            win_total[o] += w

    out = [{
        "owner": o,
        "odds": round(100 * made[o] / trials, 1),
        "proj_wins": round(win_total[o] / trials, 1),
        "current_wins": base[o][0],
    } for o in made]
    out.sort(key=lambda r: -r["odds"])
    for i, r in enumerate(out, 1):
        r["rank"] = i
    return out
