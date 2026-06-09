"""Load and expose the league configuration from config.yaml."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("KREEPER_CONFIG", ROOT / "config.yaml"))
DATA_DIR = ROOT / "data"


@lru_cache(maxsize=1)
def load() -> Dict[str, Any]:
    with open(CONFIG_PATH, "r") as fh:
        cfg = yaml.safe_load(fh)
    # Normalize manager keys to strings (YAML may parse big ints).
    cfg["managers"] = {str(k): v for k, v in cfg.get("managers", {}).items()}
    return cfg


def league() -> Dict[str, Any]:
    return load()["league"]


def rules() -> Dict[str, Any]:
    return load()["rules"]


def managers() -> Dict[str, Dict[str, str]]:
    return load()["managers"]


def manager_name(user_id: str) -> str:
    m = managers().get(str(user_id))
    return m["name"] if m else f"Unknown ({user_id})"


def adp_sources() -> Dict[str, Any]:
    return load()["adp_sources"]


def num_teams() -> int:
    return int(league()["num_teams"])


def current_season() -> int:
    return int(league()["current_season"])


def mock_draft_rookie_factor() -> float:
    try:
        return float(load().get("mock_draft_rookie_factor", 0.4))
    except (ValueError, TypeError):
        return 0.4


def keeper_timezone_name() -> str:
    return str(league().get("keeper_timezone") or "America/Indiana/Indianapolis")


def keeper_deadline():
    """The keeper-submission deadline as a tz-aware datetime, or None if unset.

    A naive value is interpreted as wall-clock time in `keeper_timezone`
    (DST handled automatically via the IANA zone); a value with an explicit
    offset is used as-is. Returns None on a missing/unparseable value so a bad
    config can never block submissions.
    """
    import datetime as _dt

    raw = league().get("keeper_deadline")
    if not raw:
        return None
    try:
        d = _dt.datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return None
    if d.tzinfo is None:
        try:
            from zoneinfo import ZoneInfo
            d = d.replace(tzinfo=ZoneInfo(keeper_timezone_name()))
        except Exception:  # noqa: BLE001 - missing tzdata: leave naive rather than crash
            pass
    return d
