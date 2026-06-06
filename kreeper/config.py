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


def keeper_deadline():
    """The keeper-submission deadline as a datetime, or None if unset.

    Naive values are treated as the host's local time. Returns None on a missing
    or unparseable value so a bad config never blocks submissions.
    """
    import datetime as _dt

    raw = league().get("keeper_deadline")
    if not raw:
        return None
    try:
        return _dt.datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return None
