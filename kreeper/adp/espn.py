"""ESPN ADP — public, unauthenticated JSON read endpoint.

The default response caps players, so we send an X-Fantasy-Filter header to pull
the full board sorted by PPR draft rank. averageDraftPosition is 0 in the early
offseason before drafts populate it; we drop zeros.
"""
from __future__ import annotations

import json
from typing import List

from .base import AdpRow, http_get

SOURCE = "ESPN"
_HOST = "https://lm-api-reads.fantasy.espn.com"
# leaguedefaults/3 == standard PPR scoring slot
_URL = _HOST + "/apis/v3/games/ffl/seasons/{season}/segments/0/leaguedefaults/3?view=kona_player_info"

_POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}
_SCORE_FILTER = {"ppr": "PPR", "half": "PPR", "std": "STANDARD"}


def headshot_ids(season: int) -> dict:
    """{normalized_name: espn_player_id} for the full ESPN player board.

    The ESPN player id doubles as the headshot id
    (a.espncdn.com/i/headshots/nfl/players/full/<id>.png). Unlike `fetch`, this
    keeps players with no ADP yet (incoming rookies) — exactly where Sleeper has
    no photo.
    """
    from ..names import normalize_name

    flt = {"players": {"limit": 1000, "sortDraftRanks": {"sortPriority": 1, "value": "PPR"}}}
    resp = http_get(_URL.format(season=season), headers={"X-Fantasy-Filter": json.dumps(flt)})
    out: dict = {}
    for item in resp.json().get("players", []):
        p = item.get("player", {})
        eid = item.get("id") or p.get("id")
        name = p.get("fullName", "")
        if eid and name:
            out.setdefault(normalize_name(name), str(eid))
    return out


def fetch(season: int, scoring: str = "ppr") -> List[AdpRow]:
    rank_type = _SCORE_FILTER.get(scoring, "PPR")
    flt = {
        "players": {
            "limit": 400,
            "sortDraftRanks": {"sortPriority": 1, "value": rank_type},
        }
    }
    resp = http_get(
        _URL.format(season=season),
        headers={"X-Fantasy-Filter": json.dumps(flt)},
    )
    data = resp.json()
    rows: List[AdpRow] = []
    for item in data.get("players", []):
        p = item.get("player", {})
        adp = (p.get("ownership") or {}).get("averageDraftPosition")
        if not adp or adp <= 0:
            continue
        rows.append(
            AdpRow(
                source=SOURCE,
                name=p.get("fullName", ""),
                position=_POS.get(p.get("defaultPositionId"), ""),
                team="",
                adp=float(adp),
            )
        )
    return rows
