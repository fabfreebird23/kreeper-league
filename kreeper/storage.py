"""Persistence for each manager's keeper selections.

Default backend is a JSON file under data/. It's intentionally a thin, swappable
layer: to make selections durable across restarts on Streamlit Cloud, point
KREEPER_DATA at a persistent path or replace JsonStorage with a Google Sheets /
database adapter exposing the same get/set methods.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List

from . import config

_LOCK = threading.Lock()


def _path(season: int) -> Path:
    base = Path(os.environ.get("KREEPER_DATA", config.DATA_DIR))
    base.mkdir(parents=True, exist_ok=True)
    return base / f"keepers_{season}.json"


def load(season: int | None = None) -> Dict[str, List[Dict[str, Any]]]:
    season = season or config.current_season()
    p = _path(season)
    if not p.exists():
        return {}
    with _LOCK:
        return json.loads(p.read_text())


def save_manager_selections(
    owner_id: str,
    selections: List[Dict[str, Any]],
    season: int | None = None,
) -> None:
    """Replace one manager's keeper list. Each selection:
    {player_id, player_name, is_rookie_keeper, cost_choice, cost_round}.
    """
    season = season or config.current_season()
    p = _path(season)
    with _LOCK:
        data = json.loads(p.read_text()) if p.exists() else {}
        data[str(owner_id)] = selections
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(p)


def get_manager_selections(owner_id: str, season: int | None = None) -> List[Dict[str, Any]]:
    return load(season).get(str(owner_id), [])


def prior_rookie_seasons(
    owner_id: str, player_id: str, current_season: int, lookback: int = 6
) -> List[int]:
    """Seasons before `current_season` where this owner kept this player as a
    rookie keeper (from our own saved selections). Used to detect a rookie ->
    regular keeper conversion, which costs a last-round pick.
    """
    out: List[int] = []
    for yr in range(current_season - 1, current_season - 1 - lookback, -1):
        for s in load(yr).get(str(owner_id), []):
            if str(s.get("player_id")) == str(player_id) and s.get("is_rookie_keeper"):
                out.append(yr)
    return out
