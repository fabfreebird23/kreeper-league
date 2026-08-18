"""Persistence for each manager's keeper selections.

Two backends, chosen automatically:
  * GitHub repo — used for the CURRENT season when Streamlit secrets provide a
    `github_token`. Submissions are stored as data/keepers_<season>.json on a
    dedicated data branch of this app's own repo, so they live WITH the dashboard
    (durable across Streamlit Cloud restarts) without any external service, and
    writing to a separate branch never triggers an app redeploy.
  * Local JSON under data/ — used for historical seasons (the committed keeper
    ledger) and as a fallback when no token is configured (local dev).

Same load / save_manager_selections / get_manager_selections API either way.
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from . import config

_LOCK = threading.Lock()


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


# ------------------------------------------------------------- GitHub backend
_API = "https://api.github.com"
_CACHE: Dict[int, Tuple[float, Dict]] = {}
_CACHE_TTL = 8  # seconds


def _gh_config() -> Optional[Tuple[str, str, str]]:
    try:
        import streamlit as st
        tok = st.secrets.get("github_token")
        if tok:
            repo = st.secrets.get("github_repo", "fabfreebird23/kreeper-league")
            branch = st.secrets.get("github_branch", "keeper-data")
            return str(tok), str(repo), str(branch)
    except Exception:
        pass
    return None


def _headers(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}


def _gh_path(season: int) -> str:
    return f"data/keepers_{season}.json"


def _ensure_branch(repo: str, branch: str, tok: str) -> None:
    h = _headers(tok)
    if requests.get(f"{_API}/repos/{repo}/branches/{branch}", headers=h, timeout=15).status_code == 200:
        return
    info = requests.get(f"{_API}/repos/{repo}", headers=h, timeout=15).json()
    default = info.get("default_branch", "main")
    ref = requests.get(f"{_API}/repos/{repo}/git/ref/heads/{default}", headers=h, timeout=15).json()
    requests.post(f"{_API}/repos/{repo}/git/refs", headers=h, timeout=15,
                  json={"ref": f"refs/heads/{branch}", "sha": ref["object"]["sha"]})


def _gh_get(season: int) -> Tuple[Dict[str, List[Dict[str, Any]]], Optional[str]]:
    tok, repo, branch = _gh_config()
    r = requests.get(f"{_API}/repos/{repo}/contents/{_gh_path(season)}",
                     headers=_headers(tok), params={"ref": branch}, timeout=15)
    if r.status_code == 404:
        return {}, None
    r.raise_for_status()
    j = r.json()
    content = base64.b64decode(j["content"]).decode()
    return (json.loads(content) if content.strip() else {}), j["sha"]


def _gh_load_cached(season: int) -> Dict[str, List[Dict[str, Any]]]:
    now = time.time()
    c = _CACHE.get(season)
    if c and now - c[0] < _CACHE_TTL:
        return c[1]
    data, _ = _gh_get(season)
    _CACHE[season] = (now, data)
    return data


def _gh_save(owner_id: str, selections: List[Dict[str, Any]], season: int) -> None:
    tok, repo, branch = _gh_config()
    _ensure_branch(repo, branch, tok)
    for _ in range(3):  # retry on a concurrent-write SHA conflict
        data, sha = _gh_get(season)
        data[str(owner_id)] = selections
        body = {
            "message": f"keepers: {config.manager_name(owner_id)} ({season})",
            "content": base64.b64encode(json.dumps(data, indent=2).encode()).decode(),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        r = requests.put(f"{_API}/repos/{repo}/contents/{_gh_path(season)}",
                         headers=_headers(tok), json=body, timeout=20)
        if r.status_code in (200, 201):
            _CACHE.pop(season, None)
            return
        if r.status_code != 409:  # not a SHA conflict -> give up
            r.raise_for_status()
    raise RuntimeError("GitHub save failed after retries")


# ------------------------------------------------------------------- public API
def _use_remote(season: int) -> bool:
    return season == config.current_season() and _gh_config() is not None


def load(season: int | None = None) -> Dict[str, List[Dict[str, Any]]]:
    season = season or config.current_season()
    if _use_remote(season):
        try:
            return _gh_load_cached(season)
        except Exception:
            pass  # fall back to local on any error
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
    if _use_remote(season):
        _gh_save(owner_id, selections, season)
        return
    _local_save(owner_id, selections, season)


def get_manager_selections(owner_id: str, season: int | None = None) -> List[Dict[str, Any]]:
    return load(season).get(str(owner_id), [])


# ------------------------------------------------------------------ change log
def _log_gh_path(season: int) -> str:
    return f"data/keeper_log_{season}.json"


def _log_local_path(season: int) -> Path:
    base = Path(os.environ.get("KREEPER_DATA", config.DATA_DIR))
    base.mkdir(parents=True, exist_ok=True)
    return base / f"keeper_log_{season}.json"


def _gh_read_list(path: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    tok, repo, branch = _gh_config()
    r = requests.get(f"{_API}/repos/{repo}/contents/{path}",
                     headers=_headers(tok), params={"ref": branch}, timeout=15)
    if r.status_code == 404:
        return [], None
    r.raise_for_status()
    j = r.json()
    content = base64.b64decode(j["content"]).decode()
    return (json.loads(content) if content.strip() else []), j["sha"]


def _gh_append_log(season: int, entry: Dict[str, Any]) -> None:
    tok, repo, branch = _gh_config()
    _ensure_branch(repo, branch, tok)
    path = _log_gh_path(season)
    for _ in range(3):  # re-read + append on a write conflict so no entry is lost
        data, sha = _gh_read_list(path)
        data = (data + [entry])[-300:]
        body = {
            "message": f"keeper log: {entry.get('name', '')} ({season})",
            "content": base64.b64encode(json.dumps(data, indent=2).encode()).decode(),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        r = requests.put(f"{_API}/repos/{repo}/contents/{path}",
                         headers=_headers(tok), json=body, timeout=20)
        if r.status_code in (200, 201):
            return
        if r.status_code != 409:
            r.raise_for_status()
    raise RuntimeError("GitHub log append failed after retries")


def append_log(owner_id: str, name: str, count: int, ts: str,
               season: int | None = None) -> None:
    """Record one keeper-set update. Best-effort — never raises, so a logging
    hiccup can't break a save."""
    season = season or config.current_season()
    entry = {"owner": str(owner_id), "name": name, "count": int(count), "ts": ts}
    try:
        if _use_remote(season):
            _gh_append_log(season, entry)
            return
    except Exception:  # noqa: BLE001
        return
    p = _log_local_path(season)
    try:
        with _LOCK:
            data = json.loads(p.read_text()) if p.exists() else []
            data = (data + [entry])[-300:]
            p.write_text(json.dumps(data, indent=2))
    except Exception:  # noqa: BLE001
        pass


def load_log(season: int | None = None) -> List[Dict[str, Any]]:
    """Update history, oldest first. Best-effort — returns [] on any error."""
    season = season or config.current_season()
    if _use_remote(season):
        try:
            data, _ = _gh_read_list(_log_gh_path(season))
            return data
        except Exception:  # noqa: BLE001
            return []
    p = _log_local_path(season)
    if not p.exists():
        return []
    try:
        with _LOCK:
            return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------- lottery
def _lottery_gh_path(season: int) -> str:
    return f"data/lottery_{season}.json"


def _lottery_local_path(season: int) -> Path:
    base = Path(os.environ.get("KREEPER_DATA", config.DATA_DIR))
    base.mkdir(parents=True, exist_ok=True)
    return base / f"lottery_{season}.json"


def _gh_get_lottery(season: int) -> Tuple[Dict[str, Any], Optional[str]]:
    tok, repo, branch = _gh_config()
    r = requests.get(f"{_API}/repos/{repo}/contents/{_lottery_gh_path(season)}",
                     headers=_headers(tok), params={"ref": branch}, timeout=15)
    if r.status_code == 404:
        return {}, None
    r.raise_for_status()
    j = r.json()
    content = base64.b64decode(j["content"]).decode()
    return (json.loads(content) if content.strip() else {}), j["sha"]


def _gh_save_lottery(data: Dict[str, Any], season: int) -> None:
    tok, repo, branch = _gh_config()
    _ensure_branch(repo, branch, tok)
    path = _lottery_gh_path(season)
    for _ in range(3):  # retry on a concurrent-write SHA conflict
        _, sha = _gh_get_lottery(season)
        body = {
            "message": f"lottery: {season}",
            "content": base64.b64encode(json.dumps(data, indent=2).encode()).decode(),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        r = requests.put(f"{_API}/repos/{repo}/contents/{path}",
                         headers=_headers(tok), json=body, timeout=20)
        if r.status_code in (200, 201):
            return
        if r.status_code != 409:
            r.raise_for_status()
    raise RuntimeError("GitHub lottery save failed after retries")


def load_lottery(season: int | None = None) -> Dict[str, Any]:
    """The persisted lottery record for a season:
    {weights, tiers, draw_order, slot_picks}. {} if nothing's saved yet."""
    season = season or config.current_season()
    if _use_remote(season):
        try:
            data, _ = _gh_get_lottery(season)
            return data
        except Exception:  # noqa: BLE001
            pass  # fall back to local on any error
    p = _lottery_local_path(season)
    if not p.exists():
        return {}
    try:
        with _LOCK:
            return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return {}


def save_lottery(data: Dict[str, Any], season: int | None = None) -> None:
    """Replace the whole persisted lottery record for a season."""
    season = season or config.current_season()
    if _use_remote(season):
        _gh_save_lottery(data, season)
        return
    p = _lottery_local_path(season)
    with _LOCK:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(p)


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


# ------------------------------------------------------------------- votes
# League motions and their ballots. Same durable-storage pattern as the
# lottery record: GitHub-backed for the live season, local JSON otherwise.
# Shape: {"motions": [{id, title, detail, options: [...], proposed_by,
#         status, ...}], "ballots": {motion_id: {owner_id: option}}}
def _votes_gh_path(season: int) -> str:
    return f"data/votes_{season}.json"


def _votes_local_path(season: int) -> Path:
    base = Path(os.environ.get("KREEPER_DATA", config.DATA_DIR))
    base.mkdir(parents=True, exist_ok=True)
    return base / f"votes_{season}.json"


def _gh_get_votes(season: int) -> Tuple[Dict[str, Any], Optional[str]]:
    tok, repo, branch = _gh_config()
    r = requests.get(f"{_API}/repos/{repo}/contents/{_votes_gh_path(season)}",
                     headers=_headers(tok), params={"ref": branch}, timeout=15)
    if r.status_code == 404:
        return {}, None
    r.raise_for_status()
    j = r.json()
    content = base64.b64decode(j["content"]).decode()
    return (json.loads(content) if content.strip() else {}), j["sha"]


def _gh_save_votes(data: Dict[str, Any], season: int) -> None:
    tok, repo, branch = _gh_config()
    _ensure_branch(repo, branch, tok)
    path = _votes_gh_path(season)
    for _ in range(3):  # retry on a concurrent-write SHA conflict
        _, sha = _gh_get_votes(season)
        body = {
            "message": f"votes: {season}",
            "content": base64.b64encode(json.dumps(data, indent=2).encode()).decode(),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        r = requests.put(f"{_API}/repos/{repo}/contents/{path}",
                         headers=_headers(tok), json=body, timeout=20)
        if r.status_code in (200, 201):
            return
        if r.status_code != 409:
            r.raise_for_status()
    raise RuntimeError("GitHub votes save failed after retries")


def load_votes(season: int | None = None) -> Dict[str, Any]:
    """{"motions": [...], "ballots": {motion_id: {owner: choice}}}. Always
    returns both keys so callers never have to guard for a fresh season."""
    season = season or config.current_season()
    data: Dict[str, Any] = {}
    if _use_remote(season):
        try:
            data, _ = _gh_get_votes(season)
        except Exception:  # noqa: BLE001
            data = {}
    if not data:
        p = _votes_local_path(season)
        if p.exists():
            try:
                with _LOCK:
                    data = json.loads(p.read_text())
            except Exception:  # noqa: BLE001
                data = {}
    data.setdefault("motions", [])
    data.setdefault("ballots", {})
    return data


def save_votes(data: Dict[str, Any], season: int | None = None) -> None:
    """Replace the whole votes record for a season."""
    season = season or config.current_season()
    if _use_remote(season):
        _gh_save_votes(data, season)
        return
    p = _votes_local_path(season)
    with _LOCK:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(p)


def record_vote(owner_id: str, motion_id: str, choice: str,
                season: int | None = None) -> None:
    """Cast (or change) one manager's ballot on one motion. Read-modify-write
    of the whole record, matching how the lottery record is persisted."""
    season = season or config.current_season()
    data = load_votes(season)
    data.setdefault("ballots", {}).setdefault(str(motion_id), {})[str(owner_id)] = choice
    save_votes(data, season)


def add_motion(motion: Dict[str, Any], season: int | None = None) -> None:
    """Append a proposed motion. Callers own the id/dedupe policy — the
    one-per-GM rule is a league bylaw enforced in the UI, not here."""
    season = season or config.current_season()
    data = load_votes(season)
    data.setdefault("motions", []).append(motion)
    save_votes(data, season)
