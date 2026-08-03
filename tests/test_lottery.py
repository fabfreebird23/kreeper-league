"""Unit tests for the draft-order lottery (kreeper/lottery.py)."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kreeper import lottery  # noqa: E402

WEIGHTS = {"A": 25, "B": 22, "C": 19, "D": 14, "E": 10, "F": 6, "G": 3, "H": 1}


def _rosters(owner_by_roster):
    return [{"roster_id": rid, "owner_id": o, "settings": {}} for rid, o in owner_by_roster.items()]


def _bracket_2games(p1_w, p1_l, p3_w, p3_l):
    """A 2-placement-game bracket (4 teams): p=1 decides 1st/2nd, p=3 decides 3rd/4th."""
    return [
        {"m": 1, "r": 1, "w": None, "l": None},  # semifinal noise, no `p` — ignored
        {"p": 1, "m": 3, "r": 2, "w": p1_w, "l": p1_l},
        {"p": 3, "m": 4, "r": 2, "w": p3_w, "l": p3_l},
    ]


# ---------------------------------------------------------- position_probabilities
def test_position_probabilities_sums_to_one_per_team():
    probs = lottery.position_probabilities(WEIGHTS)
    for o, dist in probs.items():
        assert abs(sum(dist) - 1.0) < 1e-9, (o, dist)


def test_position_probabilities_sums_to_one_per_position():
    probs = lottery.position_probabilities(WEIGHTS)
    n = len(WEIGHTS)
    for pos in range(n):
        total = sum(probs[o][pos] for o in WEIGHTS)
        assert abs(total - 1.0) < 1e-9, (pos, total)


def test_first_choice_probability_equals_weight_share():
    probs = lottery.position_probabilities(WEIGHTS)
    total_w = sum(WEIGHTS.values())
    for o, w in WEIGHTS.items():
        assert abs(probs[o][0] - w / total_w) < 1e-9, o


def test_heavier_weight_more_likely_to_pick_early():
    probs = lottery.position_probabilities(WEIGHTS)
    exp_pos = {o: sum(i * p for i, p in enumerate(dist)) for o, dist in probs.items()}
    ordered = sorted(WEIGHTS, key=lambda o: -WEIGHTS[o])  # heaviest first
    exp_ordered = [exp_pos[o] for o in ordered]
    assert all(exp_ordered[i] <= exp_ordered[i + 1] for i in range(len(exp_ordered) - 1)), exp_ordered


# ------------------------------------------------------------------------ draw_order
def test_draw_order_is_permutation():
    import random
    order = lottery.draw_order(WEIGHTS, rng=random.Random(1))
    assert sorted(order) == sorted(WEIGHTS)
    assert len(order) == len(WEIGHTS)


def test_draw_order_reproducible_with_seed():
    import random
    o1 = lottery.draw_order(WEIGHTS, rng=random.Random(99))
    o2 = lottery.draw_order(WEIGHTS, rng=random.Random(99))
    assert o1 == o2


# ------------------------------------------------------------------------ final_tiers
def test_season_is_complete_requires_both_brackets():
    rosters = _rosters({1: "A", 2: "B", 3: "C", 4: "D", 5: "E", 6: "F", 7: "G", 8: "H"})
    complete_wb = _bracket_2games(1, 2, 3, 4)
    incomplete_lb = [{"p": 1, "m": 1, "r": 1, "w": None, "l": None}]
    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_winners_bracket", return_value=complete_wb), \
         patch("kreeper.sleeper.get_losers_bracket", return_value=incomplete_lb):
        assert lottery.season_is_complete("fake") is False

    complete_lb = _bracket_2games(5, 6, 7, 8)
    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_winners_bracket", return_value=complete_wb), \
         patch("kreeper.sleeper.get_losers_bracket", return_value=complete_lb):
        assert lottery.season_is_complete("fake") is True


def test_final_tiers_returns_none_when_incomplete():
    rosters = _rosters({1: "A", 2: "B", 3: "C", 4: "D"})
    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_winners_bracket", return_value=[]), \
         patch("kreeper.sleeper.get_losers_bracket", return_value=[]):
        assert lottery.final_tiers("fake") is None


def test_final_tiers_matches_2025_kreeper_league_result():
    """Reproduces the real, human-confirmed 2025 lottery order for this league."""
    # roster_id -> owner (handle), matching real Sleeper ids' role, not real ids
    r2o = {1: "brandon", 2: "mike", 3: "tanner", 4: "ned",
           5: "branigan", 6: "heath", 7: "jared", 8: "chase"}
    rosters = _rosters(r2o)
    # championship (winners_bracket): 1.tanner 2.mike 3.jared 4.chase
    wb = _bracket_2games(p1_w=3, p1_l=2, p3_w=7, p3_l=8)
    # consolation (losers_bracket), LITERAL Sleeper placement: 1.ned 2.heath 3.branigan 4.brandon
    lb = _bracket_2games(p1_w=4, p1_l=6, p3_w=5, p3_l=1)

    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_winners_bracket", return_value=wb), \
         patch("kreeper.sleeper.get_losers_bracket", return_value=lb), \
         patch("kreeper.config.lottery_weights", return_value=[25, 22, 19, 14, 10, 6, 3, 1]):
        tiers = lottery.final_tiers("fake")

    expected = {  # owner -> (rank, weight) — INVERTED consolation, normal championship
        "brandon": (1, 25), "branigan": (2, 22), "heath": (3, 19), "ned": (4, 14),
        "tanner": (5, 10), "mike": (6, 6), "jared": (7, 3), "chase": (8, 1),
    }
    for owner, (rank, weight) in expected.items():
        assert tiers[owner]["rank"] == rank, owner
        assert tiers[owner]["weight"] == weight, owner
    assert all(tiers[o]["tier"] == "consolation" for o in ("brandon", "branigan", "heath", "ned"))
    assert all(tiers[o]["tier"] == "championship" for o in ("tanner", "mike", "jared", "chase"))


def test_final_tiers_weight_count_mismatch_raises():
    """Both brackets fully decided (8 teams total) but config only has 3
    weights configured — that's a real misconfiguration, so it should raise
    loudly rather than silently mis-assign odds."""
    rosters = _rosters({1: "A", 2: "B", 3: "C", 4: "D", 5: "E", 6: "F", 7: "G", 8: "H"})
    wb = _bracket_2games(1, 2, 3, 4)
    lb = _bracket_2games(5, 6, 7, 8)
    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_winners_bracket", return_value=wb), \
         patch("kreeper.sleeper.get_losers_bracket", return_value=lb), \
         patch("kreeper.config.lottery_weights", return_value=[3, 2, 1]):
        try:
            lottery.final_tiers("fake")
            assert False, "expected a ValueError for a weights/team-count mismatch"
        except ValueError:
            pass


# --------------------------------------------------------------------- live_projection
def test_live_projection_returns_none_when_season_not_started():
    rosters = _rosters({1: "A", 2: "B"})
    for r in rosters:
        r["settings"] = {"wins": 0, "losses": 0, "fpts": 0, "fpts_decimal": 0}
    with patch("kreeper.sleeper.get_rosters", return_value=rosters):
        assert lottery.live_projection("fake", playoff_teams=1) is None


def test_live_projection_worst_record_gets_highest_projected_weight():
    rosters = [
        {"roster_id": 1, "owner_id": "worst", "settings": {"wins": 0, "losses": 6, "fpts": 500, "fpts_decimal": 0}},
        {"roster_id": 2, "owner_id": "best", "settings": {"wins": 6, "losses": 0, "fpts": 900, "fpts_decimal": 0}},
    ]
    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.config.lottery_weights", return_value=[10, 1]):
        rows = lottery.live_projection("fake", playoff_teams=1)
    by_owner = {r["owner"]: r for r in rows}
    assert by_owner["worst"]["proj_weight"] > by_owner["best"]["proj_weight"]
