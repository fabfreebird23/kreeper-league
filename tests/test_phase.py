"""Unit tests for home-page phase detection (kreeper/phase.py)."""
import datetime as dt
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kreeper import phase  # noqa: E402


def _future():
    return dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)


def _past():
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)


def test_keepers_open_when_deadline_in_future():
    with patch("kreeper.config.keeper_deadline", return_value=_future()):
        assert phase.current_phase("fake") == "keepers_open"


def test_pre_draft_when_deadline_passed_and_draft_incomplete():
    with patch("kreeper.config.keeper_deadline", return_value=_past()), \
         patch("kreeper.sleeper.get_league",
               return_value={"status": "pre_draft", "draft_id": "d1"}), \
         patch("kreeper.sleeper.get_draft", return_value={"status": "drafting"}):
        assert phase.current_phase("fake") == "pre_draft"


def test_pre_season_when_draft_complete_and_nfl_off():
    with patch("kreeper.config.keeper_deadline", return_value=_past()), \
         patch("kreeper.sleeper.get_league",
               return_value={"status": "in_season", "draft_id": "d1"}), \
         patch("kreeper.sleeper.get_draft", return_value={"status": "complete"}), \
         patch("kreeper.sleeper.get_nfl_state", return_value={"season_type": "pre"}):
        assert phase.current_phase("fake") == "pre_season"


def test_in_season_when_nfl_regular_season():
    with patch("kreeper.config.keeper_deadline", return_value=_past()), \
         patch("kreeper.sleeper.get_league",
               return_value={"status": "in_season", "draft_id": "d1"}), \
         patch("kreeper.sleeper.get_draft", return_value={"status": "complete"}), \
         patch("kreeper.sleeper.get_nfl_state", return_value={"season_type": "regular"}):
        assert phase.current_phase("fake") == "in_season"


def test_offseason_when_league_marked_complete():
    with patch("kreeper.config.keeper_deadline", return_value=_past()), \
         patch("kreeper.sleeper.get_league", return_value={"status": "complete"}):
        assert phase.current_phase("fake") == "offseason"


def test_no_deadline_falls_through_to_draft_status():
    with patch("kreeper.config.keeper_deadline", return_value=None), \
         patch("kreeper.sleeper.get_league",
               return_value={"status": "pre_draft", "draft_id": "d1"}), \
         patch("kreeper.sleeper.get_draft", return_value={"status": "pre_draft"}):
        assert phase.current_phase("fake") == "pre_draft"
