from kreeper import stakes


def test_rooting_picks_the_side_that_helps_you():
    games = [
        {"a": "chase", "b": "mike", "stakes": 69,
         "if_a": {"chase": 66, "mike": 70, "me": 91}, "if_b": {"chase": 32, "mike": 94, "me": 94}},
        {"a": "me", "b": "heath", "stakes": 31,
         "if_a": {"me": 90, "heath": 1}, "if_b": {"me": 75, "heath": 5}},
        {"a": "ned", "b": "jared", "stakes": 4,
         "if_a": {"me": 80}, "if_b": {"me": 80}},
    ]
    r = stakes.rooting(games, "me")
    assert r[("chase", "mike")] == ("mike", 3)
    assert r[("me", "heath")] is None          # your own game
    assert r[("ned", "jared")][1] == 0          # doesn't move you
    assert stakes.rooting(games, None) == {}
