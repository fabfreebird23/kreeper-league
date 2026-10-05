"""The week as it's played: NFL game state, weekly projections, lineups, and
head-to-head win probability.

Ported from the Draft Room (draftkit.gametime / projections / weekly), cut down
to what Kreeper's weekly pages need. Kreeper is a single Sleeper PPR league, so
none of Draft Room's multi-platform or custom-scoring plumbing comes along.

Network calls (ESPN scoreboard, Sleeper projections) degrade to empty results
rather than raising — a page that can't reach ESPN still renders, it just
can't say who is still to play. Everything else is pure logic.
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from . import config

# ESPN's site API answers a browser or custom User-Agent with a 403 HTML page;
# the bare requests default gets JSON. Measured in the Draft Room, not guessed.
_ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
_ABBR = {"WSH": "WAS", "JAC": "JAX", "LA": "LAR"}          # ESPN -> Sleeper

_PROJ = "https://api.sleeper.com/projections/nfl"
_PROJ_HEADERS = {"User-Agent": "kreeper-league/1.0 (league site)"}
SKILL = ("QB", "RB", "WR", "TE")
# Everything a lineup slot can hold. Leagues without K/DEF slots never ask for
# them, so projecting and pooling them is harmless there.
LINEUP_POS = SKILL + ("K", "DEF")
FLEX_OK = ("RB", "WR", "TE")
SUPERFLEX_OK = ("QB", "RB", "WR", "TE")


def _cache_dir():
    d = config.DATA_DIR / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------- NFL games
def load_week(season: int, week: int) -> Dict[str, dict]:
    """{team: {opp, home, kickoff (ISO UTC), state, score, opp_score, period,
    clock}} for every NFL team playing that week. `state` is ESPN's "pre",
    "in" or "post"; a team on bye is absent.

    Disk-cached for 2 minutes while any game is live and an hour otherwise,
    so every viewer's refresh shares one ESPN call.
    """
    p = _cache_dir() / f"games_{season}_w{week}.json"
    cached = None
    if p.exists():
        try:
            cached = json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            cached = None
    if cached is not None:
        ttl = 30 if any_live(cached) else 3600
        if time.time() - p.stat().st_mtime < ttl:
            return cached
    try:
        r = requests.get(_ESPN, params={"week": int(week), "seasontype": 2, "dates": int(season)},
                         timeout=12)
        r.raise_for_status()
        events = (r.json() or {}).get("events") or []
    except Exception:  # noqa: BLE001
        return cached or {}
    out: Dict[str, dict] = {}
    for e in events:
        comp = (e.get("competitions") or [{}])[0]
        stt = comp.get("status") or {}
        state = (stt.get("type") or {}).get("state") or "pre"
        sides = {}
        for t in comp.get("competitors") or []:
            ab = (t.get("team") or {}).get("abbreviation") or ""
            sides[t.get("homeAway")] = (_ABBR.get(ab.upper(), ab.upper()), t)
        if "home" not in sides or "away" not in sides:
            continue
        (hab, ht), (aab, at) = sides["home"], sides["away"]
        for ab, t, opp, home in ((hab, ht, aab, True), (aab, at, hab, False)):
            try:
                sc = float(t.get("score") or 0)
            except (TypeError, ValueError):
                sc = 0.0
            out[ab] = {"opp": opp, "home": home, "kickoff": e.get("date") or "",
                       "state": state, "score": sc, "period": stt.get("period"),
                       "clock": stt.get("displayClock") or ""}
    for g in out.values():
        g["opp_score"] = out.get(g["opp"], {}).get("score", 0.0)
    # Never cache nothing: one failed call written to disk would read as
    # "no games this week" for the next hour.
    if out:
        try:
            p.write_text(json.dumps(out))
        except Exception:  # noqa: BLE001
            pass
    return out or (cached or {})


def any_live(games: Dict[str, dict]) -> bool:
    return any(g.get("state") == "in" for g in (games or {}).values())


def week_complete(games: Dict[str, dict]) -> bool:
    """Every game that week is final. An empty dict (ESPN unreachable) is not
    complete — better to wait than to post a result that can still flip."""
    return bool(games) and all(g.get("state") == "post" for g in games.values())


def status(games: Dict[str, dict], team: str) -> str:
    """"pre" / "in" / "post" / "bye" for one NFL team."""
    g = (games or {}).get(team or "")
    return (g.get("state") or "pre") if g else "bye"


def _kick_dt(g: Optional[dict]):
    if not g or not g.get("kickoff"):
        return None
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromisoformat(g["kickoff"].replace("Z", "+00:00")).astimezone(
            ZoneInfo("America/New_York"))
    except Exception:  # noqa: BLE001
        return None


def kickoff_label(g: Optional[dict]) -> str:
    """"Thu 8:15", "Sun 1:00" — US Eastern, how everyone talks about kickoff."""
    dt = _kick_dt(g)
    if dt is None:
        return "BYE" if not g else "—"
    return f"{dt.strftime('%a')} {dt.strftime('%I:%M').lstrip('0')}"


def kickoff_ts(g: Optional[dict]) -> float:
    dt = _kick_dt(g)
    return dt.timestamp() if dt else float("inf")


def game_label(games: Dict[str, dict], team: str, short: bool = False) -> str:
    """One player's game, as a row sub-line: "FINAL · 30-27 @ LV",
    "Q3 4:12 · 14-10", "Mon 8:15 vs ATL", or "BYE"."""
    g = (games or {}).get(team or "")
    if not g:
        return "BYE"
    side = "vs" if g["home"] else "@"
    sc = f'{int(g["score"])}&ndash;{int(g["opp_score"])}'
    if g["state"] == "post":
        return "FINAL" if short else f"FINAL &middot; {sc} {side} {g['opp']}"
    if g["state"] == "in":
        q = g.get("period")
        when = (f"OT {g.get('clock','')}" if q and int(q) > 4
                else f"Q{int(q)} {g.get('clock','')}" if q else "LIVE").strip()
        return when if short else f"{when} &middot; {sc}"
    return kickoff_label(g) if short else f"{kickoff_label(g)} {side} {g['opp']}"


# ------------------------------------------------------------- projections
def week_projections(season: int, week: int) -> Dict[str, float]:
    """{sleeper_pid: projected PPR points} for one week. Cached for 30
    minutes — a week's numbers move with news right up to kickoff."""
    p = _cache_dir() / f"proj_{season}_w{week}.json"
    if p.exists() and time.time() - p.stat().st_mtime < 1800:
        try:
            return json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            pass
    out: Dict[str, float] = {}
    try:
        for pos in LINEUP_POS:
            r = requests.get(f"{_PROJ}/{season}/{int(week)}",
                             params={"season_type": "regular", "position[]": pos, "order_by": "pts_ppr"},
                             headers=_PROJ_HEADERS, timeout=15)
            r.raise_for_status()
            for row in r.json() or []:
                pid = str(row.get("player_id") or "")
                v = (row.get("stats") or {}).get("pts_ppr")
                if pid and v is not None:
                    out[pid] = round(float(v), 2)
    except Exception:  # noqa: BLE001
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:  # noqa: BLE001
                return {}
        return {}
    if out:
        try:
            p.write_text(json.dumps(out))
        except Exception:  # noqa: BLE001
            pass
    return out


# --------------------------------------------------------- win probability
# Rough within-season coefficient of variation of weekly PPR scoring by
# position (Draft Room's numbers). Gets the ORDER of risk right, which is all
# a win-probability bar needs.
_CV = {"QB": 0.34, "RB": 0.52, "WR": 0.58, "TE": 0.62, "K": 0.48, "DEF": 0.75}
_FLOOR_SD = 1.5


def player_sd(pos: str, mean: float) -> float:
    return max(_FLOOR_SD, float(mean or 0.0) * _CV.get((pos or "").upper(), 0.55))


def win_prob(a_mean: float, a_sd: float, b_mean: float, b_sd: float) -> float:
    """P(A beats B), each team total treated as an independent normal."""
    sd = math.sqrt(a_sd ** 2 + b_sd ** 2)
    if sd < 1e-9:
        return 1.0 if a_mean > b_mean else 0.0 if a_mean < b_mean else 0.5
    return 0.5 * (1.0 + math.erf((a_mean - b_mean) / sd / math.sqrt(2.0)))


# ------------------------------------------------------------------ lineups
def slot_accepts(slot: str, pos: str) -> bool:
    if slot == "FLEX":
        return pos in FLEX_OK
    if slot == "SUPER_FLEX":
        return pos in SUPERFLEX_OK
    return slot == pos


def optimal_lineup(pids: Iterable[str], slots: Sequence[str], proj: Dict[str, float],
                   pos_of: Dict[str, str], prefer: Iterable[str] = ()) -> List[Tuple[str, Optional[str]]]:
    """[(slot, pid|None)] — the best legal lineup by projection. Fixed slots
    fill first (best eligible player each), FLEX last from what's left, so a
    FLEX never steals the only TE. A slot nobody on the roster can fill with a
    non-zero projection still gets its best eligible body, and comes back with
    pid None only if there's no eligible player at all. Ties go to `prefer`
    (the current starters) so an equal projection never reads as a change."""
    prefer = {str(p) for p in prefer}
    pool = sorted({str(p) for p in pids if pos_of.get(str(p)) in LINEUP_POS},
                  key=lambda p: (-float(proj.get(p, 0.0)), p not in prefer, p))
    used: set = set()
    picks: Dict[int, Optional[str]] = {}
    order = sorted(range(len(slots)), key=lambda i: slots[i] in ("FLEX", "SUPER_FLEX"))
    for i in order:
        pick = next((p for p in pool if p not in used and slot_accepts(slots[i], pos_of[p])), None)
        if pick:
            used.add(pick)
        picks[i] = pick
    return [(slots[i], picks[i]) for i in range(len(slots))]


def advice_week(current_week: int, games: Dict[str, dict]) -> int:
    """Which week the lineup advice is about. The current week while anything
    in it can still be changed; next week once only Monday night (or nothing)
    is left, because by then the useful question is next week's lineup and
    the waiver claims it needs."""
    if any_live(games):
        return current_week
    pre = [g for g in (games or {}).values() if g.get("state") == "pre"]
    if not pre:
        return current_week + 1 if games else current_week
    days = {(_kick_dt(g) or datetime.max).weekday() for g in pre}
    return current_week + 1 if days <= {0, 1} else current_week


def lineup_advice(current: Sequence[str], roster: Iterable[str], slots: Sequence[str],
                  proj: Dict[str, float], pos_of: Dict[str, str],
                  locked: Iterable[str] = ()) -> Dict[str, Any]:
    """What to change before kickoff.

    {swaps: [(start_pid, bench_pid, gain)], holes: [slot], set_total,
     best_total, best: [(slot, pid)]}. A hole is a slot whose best possible
    starter projects 0 — a bye with no backup — which no swap can fix; it
    needs a waiver claim.

    `locked` is everyone whose game has started: a locked starter keeps his
    slot and a locked bench player can't come in, so mid-week advice only
    ever suggests moves Sleeper will still accept.
    """
    cur = [str(p) for p in current if p and str(p) != "0"]
    locked = {str(p) for p in locked}
    keep = {i: str(p) for i, p in enumerate(current) if str(p) in locked and i < len(slots)}
    open_slots = [s for i, s in enumerate(slots) if i not in keep]
    pool = [p for p in roster if str(p) not in locked]
    best_open = iter(optimal_lineup(pool, open_slots, proj, pos_of, prefer=cur))
    best = [(s, keep[i]) if i in keep else next(best_open) for i, s in enumerate(slots)]
    best_ids = {p for _, p in best if p}
    ins = sorted((p for p in best_ids if p not in cur), key=lambda p: -proj.get(p, 0.0))
    outs = sorted((p for p in cur if p not in best_ids), key=lambda p: proj.get(p, 0.0))
    # A swap that gains nothing (two QBs both on bye) isn't advice.
    swaps = [(i, o, round(proj.get(i, 0.0) - proj.get(o, 0.0), 1)) for i, o in zip(ins, outs)]
    swaps = [sw for sw in swaps if sw[2] > 0]
    holes = [s for s, p in best if not p or proj.get(p, 0.0) <= 0]
    return {"swaps": swaps, "holes": holes, "best": best,
            "set_total": round(sum(proj.get(p, 0.0) for p in cur), 1),
            "best_total": round(sum(proj.get(p, 0.0) for p in best_ids), 1)}


def side_outlook(starters: Sequence[str], actual: Dict[str, float], proj: Dict[str, float],
                 pos_of: Dict[str, str], team_of: Dict[str, str],
                 games: Dict[str, dict]) -> Dict[str, Any]:
    """Where one lineup stands mid-week: {points, final, sd, left}. Played men
    count their actual points; a man mid-game his actual plus half his
    projection (no clock, half is the honest guess); a man yet to play his
    projection. Only unfinished men contribute variance."""
    pts = final = var = 0.0
    left = 0
    for pid in starters:
        pid = str(pid)
        if not pid or pid == "0":
            continue
        a = float(actual.get(pid, 0.0) or 0.0)
        pj = float(proj.get(pid, 0.0) or 0.0)
        s = status(games, team_of.get(pid, ""))
        pts += a
        if s == "post" or s == "bye":
            final += a
        elif s == "in":
            final += a + 0.5 * pj
            var += player_sd(pos_of.get(pid, ""), 0.5 * pj) ** 2
            left += 1
        else:
            final += pj
            var += player_sd(pos_of.get(pid, ""), pj) ** 2
            left += 1
    return {"points": round(pts, 2), "final": round(final, 1), "sd": math.sqrt(var), "left": left}


# ------------------------------------------------------------- injury risk
# Chance a player does NOT play this week, from his Sleeper injury tag, moved
# by his latest practice report (a Questionable who sat out practice is a far
# bigger risk than one who practised in full). Rough league-wide rates, not a
# medical model: about three in four Doubtful players sit, about one in four
# Questionable players do.
_MISS = {"OUT": 1.0, "IR": 1.0, "PUP": 1.0, "SUS": 1.0, "NA": 1.0, "COV": 1.0,
         "DOUBTFUL": 0.75, "QUESTIONABLE": 0.25, "PROBABLE": 0.05, "DTD": 0.25}
_Q_PRACTICE = {"DNP": 0.50, "LIMITED": 0.25, "FULL": 0.10}
# Chance a player who suits up gets hurt badly enough to leave the game —
# approximate per-game rates by position. Backs take the most contact.
_IN_GAME = {"QB": 0.03, "RB": 0.06, "WR": 0.04, "TE": 0.04, "K": 0.005, "DEF": 0.0}


def injury_risk(status: Optional[str], practice: Optional[str], pos: str,
                game_state: str = "pre") -> Dict[str, Any]:
    """{pct, miss, label, level} — the chance he doesn't give you a full game.

    pct = P(misses the game) + P(plays) * P(hurt during it). `game_state` is
    the NFL game's state: once it's final the question is moot (pct None);
    mid-game only the in-game half remains, halved for the time already
    played. `level` is "ok" / "watch" / "high" / "out" for colouring.
    """
    if game_state in ("post", "bye"):
        return {"pct": None, "miss": 0.0, "label": "", "level": "ok"}
    key = (status or "").strip().upper().replace(" ", "")
    miss = _MISS.get(key, 0.0)
    if key == "QUESTIONABLE":
        pk = (practice or "").strip().upper().replace(" ", "").replace("PARTICIPATION", "")
        miss = _Q_PRACTICE.get(pk, miss)
    in_game = _IN_GAME.get((pos or "").upper(), 0.04)
    if key and miss < 1.0:
        in_game += 0.02           # already banged up: more likely to aggravate it
    if game_state == "in":
        miss, in_game = 0.0, in_game * 0.5
    pct = miss + (1 - miss) * in_game
    level = ("out" if miss >= 1.0 else "high" if pct >= 0.45 else
             "watch" if pct >= 0.15 else "ok")
    return {"pct": round(100 * pct), "miss": miss, "label": (status or "").strip(), "level": level}
