"""Unit tests for FAAB budget tracking (kreeper/faab.py)."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kreeper import faab  # noqa: E402


def _rosters(entries):
    """entries: {roster_id: (owner_id, waiver_budget_used, [player_ids])}"""
    return [
        {"roster_id": rid, "owner_id": o, "players": players,
         "settings": {"waiver_budget_used": used}}
        for rid, (o, used, players) in entries.items()
    ]


def _league(waiver_budget=100):
    return {"settings": {"waiver_budget": waiver_budget}}


def _waiver_tx(week, adds, bid, status="complete"):
    return {"type": "waiver", "status": status, "leg": week,
            "settings": {"waiver_bid": bid}, "adds": adds}


def _transactions_fn(by_week):
    def fn(league_id, week):
        return by_week.get(week, [])
    return fn


def test_team_budgets_from_roster_settings():
    rosters = _rosters({1: ("A", 37, []), 2: ("B", 0, [])})
    with patch("kreeper.sleeper.get_league", return_value=_league(100)), \
         patch("kreeper.sleeper.get_rosters", return_value=rosters):
        budgets = faab.team_budgets("fake")
    assert budgets["A"] == {"total": 100, "spent": 37, "remaining": 63}
    assert budgets["B"] == {"total": 100, "spent": 0, "remaining": 100}


def test_team_budgets_remaining_never_negative():
    """A commissioner override or mid-season budget cut could push spent
    above total — remaining should floor at 0, not go negative."""
    rosters = _rosters({1: ("A", 150, [])})
    with patch("kreeper.sleeper.get_league", return_value=_league(100)), \
         patch("kreeper.sleeper.get_rosters", return_value=rosters):
        budgets = faab.team_budgets("fake")
    assert budgets["A"]["remaining"] == 0


def test_projected_pot_sums_across_league():
    rosters = _rosters({1: ("A", 40, []), 2: ("B", 10, []), 3: ("C", 0, [])})
    with patch("kreeper.sleeper.get_league", return_value=_league(100)), \
         patch("kreeper.sleeper.get_rosters", return_value=rosters):
        pot = faab.projected_pot("fake")
    assert pot == {"total_budget": 300, "total_spent": 50, "pot": 250, "teams": 3}


def test_dead_money_classifies_dropped_vs_still_rostered():
    # roster 1 (owner A) drafted/waivered player "100" (still owns it, live)
    # and player "200" (since dropped, dead).
    rosters = _rosters({1: ("A", 30, ["100"])})
    txs = {1: [_waiver_tx(1, {"100": 1}, 20), _waiver_tx(1, {"200": 1}, 10)]}
    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_transactions", side_effect=_transactions_fn(txs)):
        dm = faab.dead_money("fake")
    assert dm["A"]["live"] == 20   # player 100, still rostered
    assert dm["A"]["dead"] == 10   # player 200, dropped
    assert len(dm["A"]["moves"]) == 2


def test_dead_money_ignores_zero_bid():
    """A $0 waiver claim (priority-only, no FAAB spent) shouldn't count as
    either live or dead money."""
    rosters = _rosters({1: ("A", 0, [])})
    txs = {1: [_waiver_tx(1, {"100": 1}, 0)]}
    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_transactions", side_effect=_transactions_fn(txs)):
        dm = faab.dead_money("fake")
    assert dm["A"]["dead"] == 0
    assert dm["A"]["live"] == 0
    assert dm["A"]["moves"] == []


def test_dead_money_ignores_non_waiver_and_incomplete_transactions():
    rosters = _rosters({1: ("A", 0, [])})
    txs = {
        1: [
            {"type": "free_agent", "status": "complete", "leg": 1,
             "settings": None, "adds": {"100": 1}},
            _waiver_tx(1, {"200": 1}, 15, status="failed"),
        ]
    }
    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_transactions", side_effect=_transactions_fn(txs)):
        dm = faab.dead_money("fake")
    assert dm["A"]["dead"] == 0
    assert dm["A"]["live"] == 0
    assert dm["A"]["moves"] == []


def test_dead_money_moves_sorted_newest_first():
    rosters = _rosters({1: ("A", 0, [])})
    txs = {
        1: [_waiver_tx(1, {"100": 1}, 5)],
        3: [_waiver_tx(3, {"200": 1}, 8)],
    }
    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_transactions", side_effect=_transactions_fn(txs)):
        dm = faab.dead_money("fake")
    weeks = [m["week"] for m in dm["A"]["moves"]]
    assert weeks == sorted(weeks, reverse=True)
