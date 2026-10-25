import random

from kreeper import playoffs


def _teams(means):
    return {o: {"mean": m, "sd": 1.0, "wins": 0, "losses": 0, "ties": 0, "pf": 0.0} for o, m in means.items()}


def test_bracket_favours_the_strongest_seed():
    t = _teams({"a": 200, "b": 100, "c": 90, "d": 80})
    rng = random.Random(1)
    assert all(playoffs._bracket(rng, t, ["a", "b", "c", "d"], [2, 2]) == "a" for _ in range(50))


def test_simulate_title_odds_sum_to_100():
    t = _teams({"a": 150, "b": 140, "c": 130, "d": 120, "e": 110, "f": 100})
    sched = {1: [("a", "b"), ("c", "d"), ("e", "f")]}
    out = playoffs.simulate(t, sched, 4, n_sims=2000, round_weeks=[2, 2])
    total = sum(v["title_pct"] for v in out["teams"].values())
    assert 99 <= total <= 101
    assert out["teams"]["a"]["title_pct"] > out["teams"]["d"]["title_pct"]
    # without round_weeks the output is unchanged (stakes.py relies on that)
    assert "title_pct" not in playoffs.simulate(t, sched, 4, n_sims=200)["teams"]["a"]
