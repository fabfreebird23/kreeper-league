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


def test_projected_pot_is_total_spent_not_unspent():
    """2026 rule: the pot is what the league SPENT, not what's left over."""
    rosters = _rosters({1: ("A", 40, []), 2: ("B", 10, []), 3: ("C", 0, [])})
    with patch("kreeper.sleeper.get_league", return_value=_league(100)), \
         patch("kreeper.sleeper.get_rosters", return_value=rosters):
        pot = faab.projected_pot("fake")
    assert pot == {"total_budget": 300, "total_spent": 50, "pot": 50,
                   "unspent": 250, "teams": 3}


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


# --------------------------------------------------------------- payout splits
def _bracket_2round(r1, r2_p1, r2_p3):
    """A 2-round, 4-team bracket (mirrors the helper in test_lottery.py)."""
    return [
        {"m": 1, "r": 1, "t1": r1[0][0], "t2": r1[0][1]},
        {"m": 2, "r": 1, "t1": r1[1][0], "t2": r1[1][1]},
        {"p": 1, "m": 3, "r": 2, "t1": r2_p1[0], "t2": r2_p1[1]},
        {"p": 3, "m": 4, "r": 2, "t1": r2_p3[0], "t2": r2_p3[1]},
    ]


def _matchups_fn(week_scores):
    def fn(league_id, week):
        return [{"roster_id": rid, "points": pts} for rid, pts in week_scores.get(week, {}).items()]
    return fn


def _payout_league(waiver_budget=100, playoff_week_start=13):
    return {"settings": {"waiver_budget": waiver_budget,
                         "playoff_week_start": playoff_week_start,
                         "playoff_round_type": 0}}


# Championship: r1 (1v2, 3v4); final pairs r1 winners (1,3) for p1/p2 and r1
# losers (2,4) for p3/p4. Consolation: r1 (5v6, 7v8); final pairs winners
# (5,7) for p1/p2, losers (6,8) for p3/p4.
_WB = _bracket_2round(r1=[(1, 2), (3, 4)], r2_p1=(1, 3), r2_p3=(2, 4))
_LB = _bracket_2round(r1=[(5, 6), (7, 8)], r2_p1=(5, 7), r2_p3=(6, 8))
# Scores: r1 -> 1,3,5,7 win. r2 -> 1 over 3 (champ=1, runner-up=3);
# 2 over 4 (3rd-place-game winner = roster 2); 5 over 7 (consolation champ
# = roster 5 = 5th overall).
_SCORES = {
    13: {1: 20, 2: 10, 3: 20, 4: 10, 5: 20, 6: 10, 7: 20, 8: 10},
    14: {1: 30, 2: 30, 3: 10, 4: 10, 5: 30, 6: 30, 7: 10, 8: 10},
}


def _patched(rosters, fee=250):
    return [
        patch("kreeper.sleeper.get_rosters", return_value=rosters),
        patch("kreeper.sleeper.get_winners_bracket", return_value=_WB),
        patch("kreeper.sleeper.get_losers_bracket", return_value=_LB),
        patch("kreeper.sleeper.get_league", return_value=_payout_league()),
        patch("kreeper.sleeper.get_matchups", side_effect=_matchups_fn(_SCORES)),
        patch("kreeper.config.entry_fee", return_value=fee),
    ]


def test_pot_split_refunds_third_place_and_gives_rest_to_fifth():
    """3rd-place-game winner (roster 2) gets back exactly their own spend;
    the consolation champion (roster 5, i.e. 5th overall) takes the rest."""
    rosters = _rosters({1: ("champ", 10, []), 2: ("third", 40, []), 3: ("second", 10, []),
                        4: ("fourth", 10, []), 5: ("fifth", 5, []), 6: ("f", 5, []),
                        7: ("g", 10, []), 8: ("h", 10, [])})
    ctxs = _patched(rosters)
    for c in ctxs:
        c.start()
    try:
        split = faab.pot_split("fake")
    finally:
        for c in ctxs:
            c.stop()
    assert split["pot"] == 100                      # total SPENT league-wide
    assert split["third_place"] == {"owner": "third", "refund": 40}
    assert split["fifth_place"] == {"owner": "fifth", "amount": 60}


def test_pot_split_refund_capped_at_pot_so_fifth_never_goes_negative():
    """Degenerate case: the 3rd-place-game winner is essentially the only
    spender. The refund can't exceed the pot, and 5th place floors at 0."""
    rosters = _rosters({1: ("champ", 0, []), 2: ("third", 90, []), 3: ("second", 0, []),
                        4: ("fourth", 0, []), 5: ("fifth", 0, []), 6: ("f", 0, []),
                        7: ("g", 0, []), 8: ("h", 0, [])})
    ctxs = _patched(rosters)
    for c in ctxs:
        c.start()
    try:
        split = faab.pot_split("fake")
    finally:
        for c in ctxs:
            c.stop()
    assert split["third_place"]["refund"] == 90
    assert split["fifth_place"]["amount"] == 0


def test_entry_pot_pays_runner_up_double_and_champion_the_balance():
    rosters = _rosters({i: (f"o{i}", 0, []) for i in range(1, 9)})
    ctxs = _patched(rosters, fee=250)
    for c in ctxs:
        c.start()
    try:
        pot = faab.entry_pot("fake")
    finally:
        for c in ctxs:
            c.stop()
    assert pot["total"] == 2000                       # 250 x 8
    assert pot["runner_up"] == {"owner": "o3", "amount": 500}   # doubles their buy-in
    assert pot["champion"] == {"owner": "o1", "amount": 1500}   # the balance


# ------------------------------------------------------------- burn-down
def test_weekly_spend_buckets_bids_by_week_and_owner():
    rosters = _rosters({1: ("A", 30, []), 2: ("B", 0, [])})
    txs = {
        1: [_waiver_tx(1, {"100": 1}, 20)],
        3: [_waiver_tx(3, {"200": 1}, 10), _waiver_tx(3, {"300": 2}, 5)],
    }
    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_transactions", side_effect=_transactions_fn(txs)):
        spend = faab.weekly_spend("fake")
    assert spend["A"] == {1: 20, 3: 10}
    assert spend["B"] == {3: 5}


def test_weekly_spend_ignores_failed_and_zero_bid_claims():
    rosters = _rosters({1: ("A", 0, [])})
    txs = {1: [_waiver_tx(1, {"100": 1}, 25, status="failed"),
               _waiver_tx(1, {"200": 1}, 0)]}
    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_transactions", side_effect=_transactions_fn(txs)):
        spend = faab.weekly_spend("fake")
    assert spend["A"] == {}


def test_burndown_is_cumulative_and_sorted_by_total():
    rosters = _rosters({1: ("A", 30, []), 2: ("B", 0, [])})
    txs = {1: [_waiver_tx(1, {"100": 1}, 20)],
           3: [_waiver_tx(3, {"200": 1}, 10), _waiver_tx(3, {"300": 2}, 5)]}
    league = {"settings": {"waiver_budget": 100, "playoff_week_start": 5}}
    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_league", return_value=league), \
         patch("kreeper.sleeper.get_transactions", side_effect=_transactions_fn(txs)):
        curve = faab.burndown("fake")
    assert curve["weeks"] == [1, 2, 3, 4]
    assert curve["budget"] == 100
    a = next(t for t in curve["teams"] if t["owner"] == "A")
    # cumulative: $20 in wk1, flat wk2, +$10 in wk3, flat wk4
    assert a["points"] == [20, 20, 30, 30]
    assert a["total"] == 30
    assert curve["teams"][0]["owner"] == "A"    # biggest spender first


def test_burndown_includes_playoff_week_spending():
    """Waivers stay open through the playoffs. Cutting the chart at
    playoff_week_start dropped that spend and made the chart disagree with
    the pot total shown on the same page — six of eight teams spent in weeks
    13-16 in the real 2025 season."""
    rosters = _rosters({1: ("A", 40, [])})
    txs = {1: [_waiver_tx(1, {"100": 1}, 10)],
           15: [_waiver_tx(15, {"200": 1}, 30)]}   # deep playoff-week claim
    league = {"settings": {"waiver_budget": 100, "playoff_week_start": 13}}
    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_league", return_value=league), \
         patch("kreeper.sleeper.get_transactions", side_effect=_transactions_fn(txs)):
        curve = faab.burndown("fake")
    assert curve["weeks"][-1] >= 15
    a = curve["teams"][0]
    assert a["total"] == 40           # not 10 — the week-15 claim counts
    assert a["points"][-1] == 40


def test_burndown_total_reconciles_with_team_budgets():
    """The chart's final value per team must equal the authoritative spend
    the pot is computed from, or the same page contradicts itself."""
    rosters = _rosters({1: ("A", 40, []), 2: ("B", 5, [])})
    txs = {2: [_waiver_tx(2, {"100": 1}, 40)],
           14: [_waiver_tx(14, {"200": 2}, 5)]}
    league = {"settings": {"waiver_budget": 100, "playoff_week_start": 13}}
    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_league", return_value=league), \
         patch("kreeper.sleeper.get_transactions", side_effect=_transactions_fn(txs)):
        curve = faab.burndown("fake")
        budgets = faab.team_budgets("fake")
    for t in curve["teams"]:
        assert t["total"] == budgets[t["owner"]]["spent"], t["owner"]
