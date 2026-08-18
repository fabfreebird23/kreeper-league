"""Unit tests for live in-season state (kreeper/season.py)."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kreeper import season  # noqa: E402


def _rosters(r2o):
    return [{"roster_id": rid, "owner_id": o} for rid, o in r2o.items()]


R2O = {1: "alice", 2: "bob", 3: "carol", 4: "dave"}
ROSTERS = _rosters(R2O)


def _league(playoff_week_start=4):
    return {"settings": {"playoff_week_start": playoff_week_start}}


def _matchups_fn(by_week):
    """by_week: {week: [(roster_id, matchup_id, points), ...]}"""
    def fn(league_id, week):
        return [{"roster_id": rid, "matchup_id": mid, "points": pts}
                for rid, mid, pts in by_week.get(week, [])]
    return fn


# Weeks 1-3 are the regular season (playoff_week_start=4).
# wk1: alice 100 > bob 90 ; carol 120 > dave 80
# wk2: alice 80 < carol 110 ; bob 95 > dave 70
# wk3: alice 105 > dave 100 ; bob 60 < carol 130
PLAYED = {
    1: [(1, 1, 100), (2, 1, 90), (3, 2, 120), (4, 2, 80)],
    2: [(1, 1, 80), (3, 1, 110), (2, 2, 95), (4, 2, 70)],
    3: [(1, 1, 105), (4, 1, 100), (2, 2, 60), (3, 2, 130)],
}


def _patched(by_week=None):
    by_week = PLAYED if by_week is None else by_week
    return [
        patch("kreeper.sleeper.get_rosters", return_value=ROSTERS),
        patch("kreeper.sleeper.get_league", return_value=_league()),
        patch("kreeper.sleeper.get_matchups", side_effect=_matchups_fn(by_week)),
    ]


def _run(fn, by_week=None):
    ctxs = _patched(by_week)
    for c in ctxs:
        c.start()
    try:
        return fn()
    finally:
        for c in ctxs:
            c.stop()


# ------------------------------------------------------------- week_results
def test_week_results_pairs_by_matchup_id_and_picks_winner():
    res = _run(lambda: season.week_results("fake", 1))
    assert len(res) == 2
    first = next(r for r in res if r["matchup_id"] == 1)
    assert {first["home"]["owner"], first["away"]["owner"]} == {"alice", "bob"}
    assert first["winner"] == "alice"
    assert first["margin"] == 10
    assert first["tie"] is False


def test_week_results_skips_unplayed_week():
    """Both sides at 0 means the week hasn't been scored — not a real 0-0 game."""
    unplayed = {1: [(1, 1, 0), (2, 1, 0)]}
    assert _run(lambda: season.week_results("fake", 1), unplayed) == []


def test_week_results_skips_unpaired_matchup():
    """A matchup with only one side (bye / removed roster) is skipped, not guessed."""
    lonely = {1: [(1, 1, 100)]}
    assert _run(lambda: season.week_results("fake", 1), lonely) == []


def test_week_results_marks_tie_with_no_winner():
    tied = {1: [(1, 1, 100), (2, 1, 100)]}
    res = _run(lambda: season.week_results("fake", 1), tied)
    assert res[0]["tie"] is True
    assert res[0]["winner"] is None
    assert res[0]["margin"] == 0


# --------------------------------------------------------------- standings
def test_standings_tallies_record_and_points():
    table = _run(lambda: season.standings("fake"))
    by_owner = {r["owner"]: r for r in table}
    # carol: beat dave, beat alice, beat bob -> 3-0, PF 120+110+130
    assert (by_owner["carol"]["wins"], by_owner["carol"]["losses"]) == (3, 0)
    assert by_owner["carol"]["points_for"] == 360
    # alice: beat bob, lost to carol, beat dave -> 2-1
    assert (by_owner["alice"]["wins"], by_owner["alice"]["losses"]) == (2, 1)
    # dave: lost all three -> 0-3
    assert (by_owner["dave"]["wins"], by_owner["dave"]["losses"]) == (0, 3)
    # dave faced carol (120), bob (95), alice (105)
    assert by_owner["dave"]["points_against"] == 120 + 95 + 105


def test_standings_sorted_by_wins_then_points_for():
    table = _run(lambda: season.standings("fake"))
    assert [r["owner"] for r in table] == ["carol", "alice", "bob", "dave"]
    assert [r["rank"] for r in table] == [1, 2, 3, 4]


def test_standings_streak_counts_trailing_run():
    table = _run(lambda: season.standings("fake"))
    by_owner = {r["owner"]: r for r in table}
    assert by_owner["carol"]["streak"] == "W3"
    assert by_owner["dave"]["streak"] == "L3"
    assert by_owner["alice"]["streak"] == "W1"   # W, L, W


def test_standings_empty_season_is_all_zeros_not_an_error():
    table = _run(lambda: season.standings("fake"), {})
    assert len(table) == 4
    assert all(r["wins"] == 0 and r["weeks_played"] == 0 for r in table)
    assert all(r["streak"] == "" for r in table)


# --------------------------------------------------------------------- luck
def test_luck_expected_wins_uses_whole_league_each_week():
    """Week 1 carol scored 120, the highest of four -> beat 3 of 3 others = 1.0
    expected win. Dave scored 80, lowest -> 0.0."""
    rows = _run(lambda: season.luck("fake"))
    by_owner = {r["owner"]: r for r in rows}
    # carol was top scorer all 3 weeks -> 3.0 expected wins, actual 3 -> luck 0
    assert by_owner["carol"]["expected_wins"] == 3.0
    assert by_owner["carol"]["luck"] == 0.0
    # bob went 1-2 but scored poorly; expected should be below his actual or close
    assert by_owner["bob"]["expected_wins"] < 2.0


def test_luck_flags_a_lucky_team_as_positive():
    """alice went 2-1 while being out-scored on aggregate by bob's week-2 95
    and others — her luck should exceed the least-lucky team's."""
    rows = _run(lambda: season.luck("fake"))
    by_owner = {r["owner"]: r for r in rows}
    assert by_owner["alice"]["luck"] > by_owner["dave"]["luck"]


# ----------------------------------------------------------- power_rankings
def test_power_rankings_empty_before_any_games():
    assert _run(lambda: season.power_rankings("fake"), {}) == []


def test_power_rankings_puts_undefeated_top_scorer_first():
    ranks = _run(lambda: season.power_rankings("fake"))
    assert ranks[0]["owner"] == "carol"
    assert ranks[0]["rank"] == 1
    assert all("rank_delta" in r for r in ranks)


def test_power_rankings_rank_delta_is_vs_standings():
    ranks = _run(lambda: season.power_rankings("fake"))
    table = _run(lambda: season.standings("fake"))
    s_rank = {r["owner"]: r["rank"] for r in table}
    for r in ranks:
        assert r["rank_delta"] == s_rank[r["owner"]] - r["rank"]


# -------------------------------------------------------- remaining_schedule
def test_remaining_schedule_lists_only_unplayed_weeks():
    """Week 3 unplayed (0-0) but scheduled -> it should show up as remaining."""
    partial = {
        1: PLAYED[1],
        2: PLAYED[2],
        3: [(1, 1, 0), (4, 1, 0), (2, 2, 0), (3, 2, 0)],
    }
    rest = _run(lambda: season.remaining_schedule("fake"), partial)
    assert list(rest) == [3]
    pairs = {frozenset(p) for p in rest[3]}
    assert pairs == {frozenset(("alice", "dave")), frozenset(("bob", "carol"))}


def test_remaining_schedule_empty_when_season_complete():
    assert _run(lambda: season.remaining_schedule("fake")) == {}


# ------------------------------------------------------------- playoff_odds
def test_playoff_odds_empty_before_any_games():
    assert _run(lambda: season.playoff_odds("fake"), {}) == []


def test_playoff_odds_complete_season_is_deterministic_top_half():
    """With no games left, the odds collapse to the actual standings — the top
    2 of 4 are in at 100%, everyone else 0%."""
    odds = _run(lambda: season.playoff_odds("fake", playoff_teams=2, trials=50))
    by_owner = {r["owner"]: r for r in odds}
    assert by_owner["carol"]["odds"] == 100.0
    assert by_owner["alice"]["odds"] == 100.0
    assert by_owner["bob"]["odds"] == 0.0
    assert by_owner["dave"]["odds"] == 0.0


def test_playoff_odds_are_probabilities_that_cover_every_team():
    partial = {1: PLAYED[1], 2: PLAYED[2],
               3: [(1, 1, 0), (4, 1, 0), (2, 2, 0), (3, 2, 0)]}
    odds = _run(lambda: season.playoff_odds("fake", playoff_teams=2, trials=200), partial)
    assert len(odds) == 4
    assert all(0.0 <= r["odds"] <= 100.0 for r in odds)
    # exactly playoff_teams spots are filled every trial, so the odds sum to
    # 2 teams' worth of probability mass
    assert abs(sum(r["odds"] for r in odds) - 200.0) < 1e-6


def test_playoff_odds_seeded_run_is_reproducible():
    partial = {1: PLAYED[1], 2: PLAYED[2],
               3: [(1, 1, 0), (4, 1, 0), (2, 2, 0), (3, 2, 0)]}
    a = _run(lambda: season.playoff_odds("fake", playoff_teams=2, trials=200), partial)
    b = _run(lambda: season.playoff_odds("fake", playoff_teams=2, trials=200), partial)
    assert [r["odds"] for r in a] == [r["odds"] for r in b]
