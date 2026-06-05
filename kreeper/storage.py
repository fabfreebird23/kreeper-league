"""Persistence for each manager's keeper selections.

Two backends, chosen automatically:
  * Google Sheets — used for the CURRENT season when Streamlit secrets provide a
    service account (`gcp_service_account`) + `sheet_id`. This is what makes
    public submissions on Streamlit Cloud durable (the container filesystem
    resets on restart). Reads are cached briefly to stay under Sheets API limits.
  * Local JSON under data/ — used for historical seasons (the committed keeper
    ledger) and as a fallback when no Sheets credentials are configured (local
    dev, or before you've set up the sheet).

Both expose the same load / save_manager_selections / get_manager_selections API.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config

_LOCK = threading.Lock()

HEADER = ["owner_id", "player_id", "player_name", "position",
          "is_rookie_keeper", "keep_year", "cost_choice", "cost_round"]

# ---------------------------------------------------------------- local JSON
def _path(season: int) -> Path:
    base = Path(os.environ.get("KREEPER_DATA", config.DATA_DIR))
    base.mkdir(parents=True, exist_ok=True)
    return base / f"keepers_{season}.json"


def _local_load(season: int) -> Dict[str, List[Dict[str, Any]]]:
    p = _path(season)
    if not p.exists():
        return {}
    with _LOCK:
        return json.loads(p.read_text())


def _local_save(owner_id: str, selections: List[Dict[str, Any]], season: int) -> None:
    p = _path(season)
    with _LOCK:
        data = json.loads(p.read_text()) if p.exists() else {}
        data[str(owner_id)] = selections
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(p)


# ---------------------------------------------------------------- Google Sheets
_GS: Dict[str, Any] = {}
_CACHE: Dict[int, Tuple[float, Dict]] = {}
_CACHE_TTL = 8  # seconds


def _gs_config() -> Optional[Tuple[dict, str]]:
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets and "sheet_id" in st.secrets:
            return dict(st.secrets["gcp_service_account"]), str(st.secrets["sheet_id"])
    except Exception:
        pass
    return None


def _worksheet(season: int):
    cfg = _gs_config()
    if not cfg:
        return None
    info, sheet_id = cfg
    import gspread
    from google.oauth2.service_account import Credentials
    if _GS.get("client") is None:
        creds = Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        _GS["client"] = gspread.authorize(creds)
    if _GS.get("sheet") is None or _GS.get("sheet_id") != sheet_id:
        _GS["sheet"] = _GS["client"].open_by_key(sheet_id)
        _GS["sheet_id"] = sheet_id
    title = f"keepers_{season}"
    try:
        return _GS["sheet"].worksheet(title)
    except gspread.WorksheetNotFound:
        ws = _GS["sheet"].add_worksheet(title=title, rows=300, cols=len(HEADER))
        ws.append_row(HEADER)
        return ws


def _as_bool(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def _as_int(v):
    s = str(v).strip()
    return int(s) if s.lstrip("-").isdigit() else None


def _sheet_load(season: int) -> Dict[str, List[Dict[str, Any]]]:
    ws = _worksheet(season)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in ws.get_all_records():
        oid = str(r.get("owner_id") or "").strip()
        if not oid:
            continue
        out.setdefault(oid, []).append({
            "player_id": str(r.get("player_id") or ""),
            "player_name": r.get("player_name"),
            "position": r.get("position"),
            "is_rookie_keeper": _as_bool(r.get("is_rookie_keeper")),
            "keep_year": r.get("keep_year"),
            "cost_choice": (r.get("cost_choice") or None),
            "cost_round": _as_int(r.get("cost_round")),
        })
    return out


def _sheet_load_cached(season: int) -> Dict[str, List[Dict[str, Any]]]:
    now = time.time()
    c = _CACHE.get(season)
    if c and now - c[0] < _CACHE_TTL:
        return c[1]
    data = _sheet_load(season)
    _CACHE[season] = (now, data)
    return data


def _sheet_save(owner_id: str, selections: List[Dict[str, Any]], season: int) -> None:
    ws = _worksheet(season)
    keep = [r for r in ws.get_all_records() if str(r.get("owner_id")) != str(owner_id)]
    rows = [HEADER]
    for r in keep:
        rows.append([r.get(h, "") for h in HEADER])
    for s in selections:
        rows.append([str(owner_id), str(s.get("player_id") or ""), s.get("player_name"),
                     s.get("position"), bool(s.get("is_rookie_keeper")), s.get("keep_year"),
                     s.get("cost_choice"), s.get("cost_round")])
    ws.clear()
    ws.update(rows, value_input_option="USER_ENTERED")
    _CACHE.pop(season, None)


# ------------------------------------------------------------------- public API
def _use_sheets(season: int) -> bool:
    return season == config.current_season() and _gs_config() is not None


def load(season: int | None = None) -> Dict[str, List[Dict[str, Any]]]:
    season = season or config.current_season()
    if _use_sheets(season):
        try:
            return _sheet_load_cached(season)
        except Exception:
            pass  # fall back to local on any Sheets error
    return _local_load(season)


def save_manager_selections(
    owner_id: str,
    selections: List[Dict[str, Any]],
    season: int | None = None,
) -> None:
    """Replace one manager's keeper list. Each selection:
    {player_id, player_name, is_rookie_keeper, cost_choice, cost_round}.
    """
    season = season or config.current_season()
    if _use_sheets(season):
        try:
            _sheet_save(owner_id, selections, season)
            return
        except Exception:
            pass  # fall back to local on any Sheets error
    _local_save(owner_id, selections, season)


def get_manager_selections(owner_id: str, season: int | None = None) -> List[Dict[str, Any]]:
    return load(season).get(str(owner_id), [])


def prior_rookie_seasons(
    owner_id: str, player_id: str, current_season: int, lookback: int = 6
) -> List[int]:
    """Seasons before `current_season` where this owner kept this player as a
    rookie keeper (from our own saved selections) — historical (local) ledger.
    """
    out: List[int] = []
    for yr in range(current_season - 1, current_season - 1 - lookback, -1):
        for s in _local_load(yr).get(str(owner_id), []):
            if str(s.get("player_id")) == str(player_id) and s.get("is_rookie_keeper"):
                out.append(yr)
    return out
