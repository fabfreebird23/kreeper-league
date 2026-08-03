"""Unit tests for the draft-order lottery (kreeper/lottery.py)."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kreeper import lottery  # noqa: E402

WEIGHTS = {"A": 25, "B": 22, "C": 19, "D": 14, "E": 10, "F": 6, "G": 3, "H": 1}


def _rosters(owner_by_roster):
    return [{"roster_id": rid, "owner_id": o, "settings": {}} for rid, o in owner_by_roster.items()]


def _league_settings(playoff_week_start=13, playoff_round_type=0):
    return {"settings": {"playoff_week_start": playoff_week_start, "playoff_round_type": playoff_round_type}}


def _bracket_2round(r1, r2_p1, r2_p3):
    """A 2-round, 4-team bracket. Each arg is (t1, t2) roster_ids — no w/l
    fields, since placements are now resolved from real scores, not from
    the bracket API's own (potentially stale) winner/loser labels."""
    return [
        {"m": 1, "r": 1, "t1": r1[0][0], "t2": r1[0][1]},
        {"m": 2, "r": 1, "t1": r1[1][0], "t2": r1[1][1]},
        {"p": 1, "m": 3, "r": 2, "t1": r2_p1[0], "t2": r2_p1[1]},
        {"p": 3, "m": 4, "r": 2, "t1": r2_p3[0], "t2": r2_p3[1]},
    ]


def _matchups_fn(week_scores):
    """week_scores: {week: {roster_id: points}} -> a get_matchups(league_id, week) stand-in."""
    def fn(league_id, week):
        return [{"roster_id": rid, "points": pts} for rid, pts in week_scores.get(week, {}).items()]
    return fn


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
    complete_wb = _bracket_2round(r1=[(1, 2), (3, 4)], r2_p1=(1, 3), r2_p3=(2, 4))
    incomplete_lb = [{"p": 1, "m": 1, "r": 1, "t1": 5, "t2": 6}]  # round 2 unscheduled
    scores = {1: {1: 10, 2: 5, 3: 8, 4: 3}, 2: {1: 10, 2: 1, 3: 12, 4: 2}}

    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_winners_bracket", return_value=complete_wb), \
         patch("kreeper.sleeper.get_losers_bracket", return_value=incomplete_lb), \
         patch("kreeper.sleeper.get_league", return_value=_league_settings(playoff_week_start=1)), \
         patch("kreeper.sleeper.get_matchups", side_effect=_matchups_fn(scores)):
        assert lottery.season_is_complete("fake") is False

    complete_lb = _bracket_2round(r1=[(5, 6), (7, 8)], r2_p1=(5, 7), r2_p3=(6, 8))
    scores2 = dict(scores)
    scores2[1] = {**scores[1], 5: 9, 6: 4, 7: 11, 8: 2}
    scores2[2] = {**scores[2], 5: 6, 6: 1, 7: 7, 8: 2}
    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_winners_bracket", return_value=complete_wb), \
         patch("kreeper.sleeper.get_losers_bracket", return_value=complete_lb), \
         patch("kreeper.sleeper.get_league", return_value=_league_settings(playoff_week_start=1)), \
         patch("kreeper.sleeper.get_matchups", side_effect=_matchups_fn(scores2)):
        assert lottery.season_is_complete("fake") is True


def test_final_tiers_returns_none_when_incomplete():
    rosters = _rosters({1: "A", 2: "B", 3: "C", 4: "D"})
    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_winners_bracket", return_value=[]), \
         patch("kreeper.sleeper.get_losers_bracket", return_value=[]):
        assert lottery.final_tiers("fake") is None


def test_final_tiers_matches_2025_kreeper_league_result():
    """Reproduces the real, human-confirmed 2025 lottery order for this
    league — including the real bug: Sleeper's bracket API had the wrong
    winner recorded for both round-1 consolation games (confirmed against
    actual matchup scores), so placements must come from real per-round
    points, never from the bracket's own w/l fields. This fixture mirrors
    that exact scenario: round-1 "advancement" pairs the TRUE round-1
    winners together in round 2 (as Sleeper's real schedule did), but no
    w/l field is present anywhere — only real scores decide who won each
    game, at every round.
    """
    # roster_id -> owner, matching this league's real 2025 role mapping
    r2o = {1: "jared", 2: "chase", 3: "brandon", 4: "ned",
           5: "mike", 6: "heath", 7: "branigan", 8: "tanner"}
    rosters = _rosters(r2o)

    # Championship: round1 (chase vs mike, tanner vs jared); round2 final
    # pairs the two round1 winners (mike, tanner) for placement 1/2, and the
    # two round1 losers (chase, jared) for placement 3/4.
    wb = _bracket_2round(r1=[(2, 5), (8, 1)], r2_p1=(5, 8), r2_p3=(2, 1))
    # Consolation: round1 (heath vs brandon, ned vs branigan); round2 final
    # pairs the two round1 winners (brandon, branigan) for placement 1/2, and
    # the two round1 losers (heath, ned) for placement 3/4 — matching the
    # REAL 2025 schedule exactly.
    lb = _bracket_2round(r1=[(6, 3), (4, 7)], r2_p1=(7, 3), r2_p3=(6, 4))

    # Real (decisive-in-one-week-so-it's-easy-to-verify) scores reproducing
    # the actual result pattern: round1 winners = brandon, branigan, mike,
    # tanner; round2: brandon beats branigan, heath beats ned (narrowly),
    # tanner beats mike, jared beats chase. Week 14/16 are all-zero so each
    # round's total is decided entirely by week 13/15 (easier to verify by
    # inspection); playoff_round_type=2 still sums both weeks per round.
    week_scores = {
        13: {1: 10, 2: 10, 3: 20, 4: 10, 5: 15, 6: 8, 7: 14, 8: 18},
        14: {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0},
        15: {1: 20, 2: 10, 3: 30, 4: 14, 5: 12, 6: 15, 7: 20, 8: 16},
        16: {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0},
    }
    # round1: chase(2)=10<mike(5)=15 -> mike; tanner(8)=18>jared(1)=10 -> tanner
    #         heath(6)=8<brandon(3)=20 -> brandon; ned(4)=10<branigan(7)=14 -> branigan
    # round2: mike(5)=12<tanner(8)=16 -> tanner; chase(2)=10<jared(1)=20 -> jared
    #         branigan(7)=20<brandon(3)=30 -> brandon; ned(4)=14<heath(6)=15 -> heath (narrow)
    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_winners_bracket", return_value=wb), \
         patch("kreeper.sleeper.get_losers_bracket", return_value=lb), \
         patch("kreeper.sleeper.get_league", return_value=_league_settings(playoff_week_start=13, playoff_round_type=2)), \
         patch("kreeper.sleeper.get_matchups", side_effect=_matchups_fn(week_scores)), \
         patch("kreeper.config.lottery_weights", return_value=[25, 22, 19, 14, 10, 6, 3, 1]):
        tiers = lottery.final_tiers("fake")

    expected = {  # owner -> (rank, weight) — straight, no inversion
        "brandon": (1, 25), "branigan": (2, 22), "heath": (3, 19), "ned": (4, 14),
        "tanner": (5, 10), "mike": (6, 6), "jared": (7, 3), "chase": (8, 1),
    }
    for owner, (rank, weight) in expected.items():
        assert tiers[owner]["rank"] == rank, (owner, tiers[owner])
        assert tiers[owner]["weight"] == weight, (owner, tiers[owner])
    assert all(tiers[o]["tier"] == "consolation" for o in ("brandon", "branigan", "heath", "ned"))
    assert all(tiers[o]["tier"] == "championship" for o in ("tanner", "mike", "jared", "chase"))


def test_final_tiers_ignores_bracket_api_placement_and_uses_real_scores():
    """The exact regression this fix targets: even if a game's t1/t2 pairing
    looks like a normal bracket, the WINNER must come from real points, not
    any w/l-style field (this module never reads one — this test just
    confirms swapping which team scores higher flips the placement)."""
    rosters = _rosters({1: "A", 2: "B", 3: "C", 4: "D"})
    bracket = _bracket_2round(r1=[(1, 2), (3, 4)], r2_p1=(1, 3), r2_p3=(2, 4))
    scores = {
        1: {1: 10, 2: 5, 3: 10, 4: 5},
        2: {1: 100, 2: 1, 3: 1, 4: 100},  # A crushes C in round 2 -> A takes placement 1
    }
    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_winners_bracket", return_value=bracket), \
         patch("kreeper.sleeper.get_losers_bracket", return_value=[]), \
         patch("kreeper.sleeper.get_league", return_value=_league_settings(playoff_week_start=1)), \
         patch("kreeper.sleeper.get_matchups", side_effect=_matchups_fn(scores)):
        placements = lottery._resolve_bracket_placements(bracket, "fake")
    # Round1: A beats B, C beats D. Round2: A(100) beats C(1) -> A=1st, C=2nd;
    # D(100) beats B(1) in the losers' consolation game -> D=3rd, B=4th.
    assert placements == {1: 1, 2: 3, 3: 4, 4: 2}


def test_final_tiers_weight_count_mismatch_raises():
    """Both brackets fully decided (8 teams total) but config only has 3
    weights configured — that's a real misconfiguration, so it should raise
    loudly rather than silently mis-assign odds."""
    rosters = _rosters({1: "A", 2: "B", 3: "C", 4: "D", 5: "E", 6: "F", 7: "G", 8: "H"})
    wb = _bracket_2round(r1=[(1, 2), (3, 4)], r2_p1=(1, 3), r2_p3=(2, 4))
    lb = _bracket_2round(r1=[(5, 6), (7, 8)], r2_p1=(5, 7), r2_p3=(6, 8))
    scores = {
        1: {1: 10, 2: 5, 3: 8, 4: 3, 5: 9, 6: 4, 7: 11, 8: 2},
        2: {1: 10, 2: 1, 3: 8, 4: 2, 5: 9, 6: 1, 7: 11, 8: 2},
    }
    with patch("kreeper.sleeper.get_rosters", return_value=rosters), \
         patch("kreeper.sleeper.get_winners_bracket", return_value=wb), \
         patch("kreeper.sleeper.get_losers_bracket", return_value=lb), \
         patch("kreeper.sleeper.get_league", return_value=_league_settings(playoff_week_start=1)), \
         patch("kreeper.sleeper.get_matchups", side_effect=_matchups_fn(scores)), \
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


def test_projection_favors_strongest_of_the_projected_consolation_group():
    """The consolation bracket is a real mini-tournament, so the team
    closest to the playoff cutoff (strongest of the projected-bad four)
    should project a HIGHER expected weight than the team that's weakest of
    all — even though the weakest team has a HIGHER probability of actually
    landing in the consolation group in the first place. Regression test for
    the bug where a flat within-group average ignored this entirely."""
    power = {"weakest": 1.0, "b": 5.0, "c": 9.0, "closest_to_cutoff": 13.0,
             "e": 20.0, "f": 25.0, "g": 30.0, "h": 35.0}
    with patch("kreeper.config.lottery_weights", return_value=[25, 22, 19, 14, 10, 6, 3, 1]):
        rows = lottery.preseason_projection(power, playoff_teams=4)
    by_owner = {r["owner"]: r for r in rows}
    assert by_owner["closest_to_cutoff"]["proj_weight"] > by_owner["weakest"]["proj_weight"]
