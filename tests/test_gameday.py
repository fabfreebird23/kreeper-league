"""Unit tests for the weekly game/lineup/win-probability logic (kreeper/gameday.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kreeper import gameday as gd  # noqa: E402

SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]
POS = {"q1": "QB", "q2": "QB", "r1": "RB", "r2": "RB", "r3": "RB",
       "w1": "WR", "w2": "WR", "w3": "WR", "t1": "TE", "t2": "TE"}


def test_optimal_lineup_fills_fixed_slots_before_flex():
    """The FLEX must not take the only good TE: TE fills first, FLEX gets the
    best remaining RB/WR/TE."""
    proj = {"q1": 20, "r1": 15, "r2": 12, "r3": 11, "w1": 14, "w2": 13, "w3": 9, "t1": 16, "t2": 4}
    lu = dict(enumerate(gd.optimal_lineup(POS, SLOTS, proj, POS)))
    assert lu[5] == ("TE", "t1")
    assert lu[6] == ("FLEX", "r3")
    assert lu[0] == ("QB", "q1")


def test_lineup_advice_pairs_best_bench_with_worst_starter():
    proj = {"q1": 20, "r1": 15, "r2": 12, "r3": 18, "w1": 14, "w2": 13, "w3": 2, "t1": 10}
    current = ["q1", "r1", "r2", "w1", "w2", "t1", "w3"]
    adv = gd.lineup_advice(current, POS, SLOTS, proj, POS)
    assert adv["swaps"] == [("r3", "w3", 16.0)]
    assert adv["best_total"] - adv["set_total"] == 16.0
    assert adv["holes"] == []


def test_lineup_advice_flags_a_bye_with_no_backup_as_a_hole():
    """Both QBs project 0 (bye): no swap fixes that — it's a waiver claim."""
    proj = {"q1": 0, "q2": 0, "r1": 15, "r2": 12, "w1": 14, "w2": 13, "t1": 10, "r3": 9}
    adv = gd.lineup_advice(["q1", "r1", "r2", "w1", "w2", "t1", "r3"], POS, SLOTS, proj, POS)
    assert adv["holes"] == ["QB"]
    assert adv["swaps"] == []


def test_win_prob_is_symmetric_and_bounded():
    a = gd.win_prob(120, 15, 100, 15)
    b = gd.win_prob(100, 15, 120, 15)
    assert 0.5 < a < 1 and abs(a + b - 1) < 1e-9
    assert gd.win_prob(110, 0, 100, 0) == 1.0
    assert gd.win_prob(100, 0, 100, 0) == 0.5


def test_side_outlook_counts_actual_for_played_and_projection_for_the_rest():
    games = {"KC": {"state": "post"}, "NO": {"state": "pre"}, "BUF": {"state": "in"}}
    team = {"a": "KC", "b": "NO", "c": "BUF"}
    out = gd.side_outlook(["a", "b", "c"], {"a": 20.0, "c": 6.0}, {"a": 18, "b": 15, "c": 10},
                          {"a": "QB", "b": "WR", "c": "RB"}, team, games)
    assert out["points"] == 26.0
    assert out["final"] == 20.0 + 15 + (6.0 + 5.0)
    assert out["left"] == 2
    assert out["sd"] > 0


def test_side_outlook_finished_lineup_has_no_variance():
    out = gd.side_outlook(["a"], {"a": 12.0}, {"a": 10}, {"a": "WR"}, {"a": "KC"},
                          {"KC": {"state": "post"}})
    assert out["sd"] == 0 and out["left"] == 0 and out["final"] == 12.0


def test_week_complete_needs_every_game_final_and_some_games():
    assert gd.week_complete({"A": {"state": "post"}, "B": {"state": "post"}})
    assert not gd.week_complete({"A": {"state": "post"}, "B": {"state": "pre"}})
    assert not gd.week_complete({})


def test_game_label_bye_and_final():
    games = {"KC": {"opp": "LV", "home": False, "state": "post", "score": 30, "opp_score": 27,
                    "kickoff": "2026-10-04T20:25Z"}}
    assert gd.game_label(games, "KC").startswith("FINAL")
    assert "@ LV" in gd.game_label(games, "KC")
    assert gd.game_label(games, "KC", short=True) == "FINAL"
    assert gd.game_label(games, "SEA") == "BYE"


def test_lineup_advice_never_moves_a_locked_player():
    """w3 (FLEX) has kicked off, so he keeps the FLEX — r3 can still come in,
    but only at RB, for r2. And once r3 himself is locked on the bench he
    can't come in at all."""
    proj = {"q1": 20, "r1": 15, "r2": 12, "r3": 18, "w1": 14, "w2": 13, "w3": 2, "t1": 10}
    current = ["q1", "r1", "r2", "w1", "w2", "t1", "w3"]
    assert gd.lineup_advice(current, POS, SLOTS, proj, POS, locked={"w3"})["swaps"] == [("r3", "r2", 6.0)]
    assert gd.lineup_advice(current, POS, SLOTS, proj, POS, locked={"r3"})["swaps"] == []


def _g(state, iso):
    return {"state": state, "kickoff": iso}


def test_advice_week_moves_on_when_only_monday_night_is_left():
    games = {"KC": _g("post", "2026-10-04T17:00:00Z"),            # Sun 1:00 ET
             "NO": _g("pre", "2026-10-06T00:15:00Z")}             # Mon 8:15 ET
    assert gd.advice_week(4, games) == 5


def test_advice_week_stays_while_sunday_games_are_to_come():
    games = {"DAL": _g("post", "2026-10-02T00:15:00Z"),           # Thu night
             "KC": _g("pre", "2026-10-04T17:00:00Z")}             # Sun 1:00
    assert gd.advice_week(4, games) == 4


def test_advice_week_stays_while_a_game_is_live():
    games = {"KC": _g("in", "2026-10-04T17:00:00Z"), "NO": _g("pre", "2026-10-06T00:15:00Z")}
    assert gd.advice_week(4, games) == 4


def test_advice_week_after_every_game_is_final_is_next_week():
    assert gd.advice_week(4, {"KC": _g("post", "2026-10-04T17:00:00Z")}) == 5
    assert gd.advice_week(4, {}) == 4
