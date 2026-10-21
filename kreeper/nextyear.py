"""A projected NEXT-SEASON ADP — what a keeper actually costs against.

Ported from the Draft Room (draftkit/nextyear.py) so the hub and the Draft
Room price next year's keepers off the same number. A keeper's ADP option is
priced against next summer's draft, and nobody publishes that until next
summer; this season's preseason ADP is frozen in August.

The projection comes from FantasyCalc, whose values are built from real
trades between managers, keyed by Sleeper id:

  * dynasty value — what a player is worth across seasons; it keeps a player
    on IR or out for the year at his real value.
  * redraft value — what he is worth for the rest of THIS season.

Next summer's ADP sits between the two, so the projection averages them. A
player whose redraft value has collapsed while his dynasty value holds (out
for the season, on IR) is priced on dynasty alone.

Ranks are over the QB/RB/WR/TE pool, so a projected rank reads like an ADP and
divides into rounds the same way.
"""
from __future__ import annotations

import json
import time
from typing import Dict, Optional

import requests

from . import config, sleeper

_URL = "https://api.fantasycalc.com/values/current"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/130 Safari/537.36"}
_TTL = 12 * 3600
# season-long designations; a plain "Out" is often one week
_LONG = {"IR", "PUP", "NFI", "DNR"}
_OUT = {"Out", "OUT", "Sus", "SUS"}
_MEMO: Dict[tuple, tuple] = {}


def _fetch(n_teams: int, ppr: float) -> list:
    p = config.DATA_DIR / f"nextyear_fc_{n_teams}_{ppr}.json"
    config.DATA_DIR.mkdir(exist_ok=True)
    if p.exists() and time.time() - p.stat().st_mtime < _TTL:
        try:
            return json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            pass
    try:
        r = requests.get(_URL, params={"isDynasty": "true", "numQbs": 1, "numTeams": int(n_teams),
                                       "ppr": ppr}, headers=_UA, timeout=20)
        r.raise_for_status()
        rows = r.json() or []
        if rows:
            p.write_text(json.dumps(rows))
            return rows
    except Exception:  # noqa: BLE001
        pass
    try:
        return json.loads(p.read_text()) if p.exists() else []
    except Exception:  # noqa: BLE001
        return []


def projected(n_teams: int = 10, ppr: float = 1.0) -> Dict[str, dict]:
    """{sleeper_pid: {rank, value, dynasty, redraft, injured, basis}}."""
    key = (int(n_teams), float(ppr))
    hit = _MEMO.get(key)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    rows = _fetch(n_teams, ppr)
    if not rows:
        return {}
    try:
        players = sleeper.get_players() or {}
    except Exception:  # noqa: BLE001
        players = {}
    out = {}
    for x in rows:
        p = x.get("player") or {}
        pid = str(p.get("sleeperId") or "")
        if not pid or (p.get("position") or "").upper() not in ("QB", "RB", "WR", "TE"):
            continue
        dyn = float(x.get("value") or 0)
        red = float(x.get("redraftValue") or 0)
        inj = (players.get(pid) or {}).get("injury_status") or ""
        collapsed = dyn > 0 and red < 0.45 * dyn
        injured = inj in _LONG or (inj in _OUT and collapsed)
        val = dyn if injured or not red else 0.5 * dyn + 0.5 * red
        out[pid] = {"value": val, "dynasty": dyn, "redraft": red, "injured": injured,
                    "basis": "dynasty (out / IR)" if injured else "dynasty + redraft"}
    for i, (pid, r) in enumerate(sorted(out.items(), key=lambda kv: -kv[1]["value"]), 1):
        r["rank"] = i
    _MEMO[key] = (time.time(), out)
    return out


def ppr_for(scoring: str) -> float:
    s = (scoring or "ppr").lower()
    return 1.0 if s == "ppr" else 0.5 if s in ("half", "half_ppr", "0.5") else 0.0


def rank(pid, n_teams: int = 10, ppr: float = 1.0) -> Optional[int]:
    """Projected next-season rank for one Sleeper id, or None if unpriced."""
    r = projected(n_teams, ppr).get(str(pid))
    return r["rank"] if r else None
