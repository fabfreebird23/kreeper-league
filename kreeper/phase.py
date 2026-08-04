"""Home-page phase detection.

The home page leads with whatever's actually useful right now rather than
always showing the same static layout. Phase is inferred from data we
already have — no new config to maintain, nothing to remember to flip:

  keepers_open  — keeper_deadline is set and hasn't passed yet
  pre_draft     — keepers are locked but the Sleeper draft isn't complete
  pre_season    — draft is complete, NFL games haven't started
  in_season     — NFL is in its regular season or postseason
  offseason     — the Sleeper league itself is marked complete

Pure logic module — no Streamlit here.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from . import config, sleeper

PHASES = ["keepers_open", "pre_draft", "pre_season", "in_season", "offseason"]


def current_phase(league_id: Optional[str] = None) -> str:
    league_id = league_id or config.league()["sleeper_league_id"]

    deadline = config.keeper_deadline()
    if deadline is not None and dt.datetime.now(deadline.tzinfo) < deadline:
        return "keepers_open"

    lg = sleeper.get_league(league_id)
    if lg.get("status") == "complete":
        return "offseason"

    draft_id = lg.get("draft_id")
    if draft_id:
        try:
            if sleeper.get_draft(draft_id).get("status") != "complete":
                return "pre_draft"
        except Exception:  # noqa: BLE001 — a flaky Sleeper call shouldn't crash the home page
            return "pre_draft"

    try:
        season_type = sleeper.get_nfl_state().get("season_type")
    except Exception:  # noqa: BLE001
        season_type = None
    if season_type in ("regular", "post"):
        return "in_season"
    return "pre_season"
