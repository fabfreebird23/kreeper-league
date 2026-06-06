"""Unit tests for the keeper cost engine."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kreeper import engine  # noqa: E402

RULES = {"max_keep_years": 3, "year2_bump_rounds": 3, "rookie_keeper_cost": "original_round",
         "rookie_fixed_round": 14}
NT = 8


def prof(next_year, original_round, acquired="draft"):
    return {"next_keep_year": next_year, "original_round": original_round,
            "consecutive_keeper_years": next_year - 1, "acquired_via": acquired}


def test_year1_keeps_at_draft_round():
    c = engine.compute(prof(1, 8), adp_rank=40, rules=RULES, num_teams=NT)
    assert c.eligible and c.keep_year == 1 and c.recommended_round == 8


def test_year2_uses_bump_adp_never_discounts():
    # Drafted R12, bump = R9. ADP rank 24 -> R3 (more expensive than the bump):
    # allowed as an option, but the cost stays the cheaper bump (R9).
    c = engine.compute(prof(2, 12), adp_rank=24, rules=RULES, num_teams=NT)
    assert c.keep_year == 2 and c.recommended_round == 9
    # Faded player: drafted R12, ADP rank 80 -> R10 (cheaper than the R9 bump).
    # ADP can't lower the cost, so he's still kept at the bump round R9 (not R10).
    c2 = engine.compute(prof(2, 12), adp_rank=80, rules=RULES, num_teams=NT)
    assert c2.recommended_round == 9
    # The cheaper ADP option is not even offered.
    assert all("ADP" not in o.label for o in c2.options)


def test_year3_adp_or_3round_jump_from_year2():
    # Year 3 = ADP unless a 3-round jump from last year's round is cheaper.
    # Last year R10 -> jump = R7.
    p = prof(3, 12)
    p["last_season_record"] = {"round": 10}
    # ADP rank 16 -> R2 (more expensive than the R7 jump) -> ADP applies.
    c = engine.compute(p, adp_rank=16, rules=RULES, num_teams=NT)
    assert c.recommended_round == 2
    # ADP rank 80 -> R10 (cheaper than the R7 jump) -> use the 3-round jump R7.
    c2 = engine.compute(p, adp_rank=80, rules=RULES, num_teams=NT)
    assert c2.recommended_round == 7
    # No ADP yet -> fall back to the 3-round jump.
    c3 = engine.compute(p, adp_rank=None, rules=RULES, num_teams=NT)
    assert c3.recommended_round == 7


def test_year2_bump_floor_round_1():
    c = engine.compute(prof(2, 2), adp_rank=None, rules=RULES, num_teams=NT)
    assert c.recommended_round == 1  # max(1, 2-3)


def test_year3_forces_adp():
    c = engine.compute(prof(3, 5), adp_rank=16, rules=RULES, num_teams=NT)
    assert c.keep_year == 3 and c.recommended_round == 2  # ceil(16/8)


def test_fourth_year_ineligible():
    c = engine.compute(prof(4, 5), adp_rank=16, rules=RULES, num_teams=NT)
    assert not c.eligible


def test_rookie_keeper_exempt_and_locked():
    c = engine.compute(prof(5, 14), adp_rank=10, is_rookie_keeper=True, rules=RULES, num_teams=NT)
    assert c.eligible and c.keep_year == "Rookie" and c.recommended_round == 14


def waiver_prof(next_year=1):
    return {"next_keep_year": next_year, "original_round": None,
            "consecutive_keeper_years": next_year - 1, "acquired_via": "undrafted"}


def trade_prof(next_year, original_round):
    # Traded keeper: another owner drafted/kept them; round + clock carry over.
    return {"next_keep_year": next_year, "original_round": original_round,
            "consecutive_keeper_years": next_year - 1, "acquired_via": "trade"}


def test_traded_keeper_inherits_round_and_clock():
    # JSN: Ned kept at R10 in year 1, traded to me -> year 2 -> bump to R7.
    items = [
        {"player_id": "jsn", "is_rookie": False, "profile": trade_prof(2, 10),
         "adp_rank": 5, "year2_choice": None},
    ]
    out = engine.allocate_keeper_costs(items, draft_rounds=14, num_teams=NT, rules=RULES)
    # Year 2: bump = R7, ADP rank 5 -> R1; cheaper (later) = R7.
    assert out["jsn"].keep_year == 2 and out["jsn"].recommended_round == 7
    # A traded keeper is NOT dumped into the last rounds.
    assert out["jsn"].recommended_round != 14


def test_rookies_take_last_rounds_first():
    items = [
        {"player_id": "a", "is_rookie": True, "profile": prof(1, 5), "adp_rank": 10, "year2_choice": None},
        {"player_id": "b", "is_rookie": True, "profile": prof(1, 3), "adp_rank": 20, "year2_choice": None},
    ]
    out = engine.allocate_keeper_costs(items, draft_rounds=14, num_teams=NT, rules=RULES)
    assert out["a"].keep_year == "Rookie" and out["a"].recommended_round == 14
    assert out["b"].recommended_round == 13


def test_waiver_pickup_takes_latest_available_after_rookies():
    items = [
        {"player_id": "rook", "is_rookie": True, "profile": prof(1, 9), "adp_rank": 5, "year2_choice": None},
        {"player_id": "wv", "is_rookie": False, "profile": waiver_prof(1), "adp_rank": 30, "year2_choice": None},
    ]
    out = engine.allocate_keeper_costs(items, draft_rounds=14, num_teams=NT, rules=RULES)
    assert out["rook"].recommended_round == 14          # rookie takes the last round
    assert out["wv"].recommended_round == 13            # waiver takes next latest available


def test_drafted_keeper_keeps_normal_cost_in_allocation():
    items = [
        {"player_id": "d", "is_rookie": False, "profile": prof(1, 8), "adp_rank": 40, "year2_choice": None},
    ]
    out = engine.allocate_keeper_costs(items, draft_rounds=14, num_teams=NT, rules=RULES)
    assert out["d"].recommended_round == 8              # Year 1 -> drafted round


def test_two_waivers_take_descending_rounds():
    items = [
        {"player_id": "w1", "is_rookie": False, "profile": waiver_prof(1), "adp_rank": None, "year2_choice": None},
        {"player_id": "w2", "is_rookie": False, "profile": waiver_prof(1), "adp_rank": None, "year2_choice": None},
    ]
    out = engine.allocate_keeper_costs(items, draft_rounds=14, num_teams=NT, rules=RULES)
    assert {out["w1"].recommended_round, out["w2"].recommended_round} == {14, 13}


def test_rookie_to_regular_is_last_round_and_resets_clock():
    # Long keeper streak (as a rookie keeper) — converting to a regular keeper
    # should ignore the old clock and slot a last-round pick at Year 1.
    items = [
        {"player_id": "c", "is_rookie": False, "from_rookie": True,
         "profile": prof(4, 2), "adp_rank": 5, "year2_choice": None},
    ]
    out = engine.allocate_keeper_costs(items, draft_rounds=14, num_teams=NT, rules=RULES)
    assert out["c"].eligible
    assert out["c"].keep_year == 1
    assert out["c"].recommended_round == 14   # last round


def test_rookie_to_regular_yields_to_rookie_for_last_round():
    # A current rookie keeper takes R14; a same-round conversion takes the next one.
    items = [
        {"player_id": "rook", "is_rookie": True, "profile": prof(1, 5), "adp_rank": 9, "year2_choice": None},
        {"player_id": "conv", "is_rookie": False, "from_rookie": True,
         "profile": prof(3, 4), "adp_rank": 20, "year2_choice": None},
    ]
    out = engine.allocate_keeper_costs(items, draft_rounds=14, num_teams=NT, rules=RULES)
    assert out["rook"].recommended_round == 14
    assert out["conv"].recommended_round == 13 and out["conv"].keep_year == 1


def test_adjust_to_owned_bumps_to_next_highest():
    from collections import Counter
    owned = Counter({r: 1 for r in range(1, 15)})
    owned[7] = 0  # traded away R7
    assert engine.adjust_to_owned(7, owned, 14) == 6   # next-highest owned
    assert engine.adjust_to_owned(5, owned, 14) == 5   # owns R5, no change


def test_allocation_snaps_to_owned_pick():
    from collections import Counter
    owned = Counter({r: 1 for r in range(1, 15)})
    owned[7] = 0  # team traded away its R7 pick
    # JSN: drafted R10, kept once -> Year 2 -> bump to R7; but R7 not owned -> R6.
    items = [{"player_id": "jsn", "is_rookie": False, "profile": prof(2, 10),
              "adp_rank": 5, "year2_choice": "Round 7"}]
    out = engine.allocate_keeper_costs(items, draft_rounds=14, num_teams=NT, rules=RULES, owned=owned)
    assert out["jsn"].recommended_round == 6


def test_multiple_keepers_same_round_when_multiple_picks():
    # Own TWO R14 picks -> two keepers can both sit at R14 before anyone drops to R13.
    from collections import Counter
    owned = Counter({r: 1 for r in range(1, 15)})
    owned[14] = 2
    items = [
        {"player_id": "a", "is_rookie": True, "profile": prof(1, 5), "adp_rank": 10, "year2_choice": None},
        {"player_id": "b", "is_rookie": True, "profile": prof(1, 5), "adp_rank": 20, "year2_choice": None},
        {"player_id": "c", "is_rookie": True, "profile": prof(1, 5), "adp_rank": 30, "year2_choice": None},
    ]
    out = engine.allocate_keeper_costs(items, draft_rounds=14, num_teams=NT, rules=RULES, owned=owned)
    assert out["a"].recommended_round == 14
    assert out["b"].recommended_round == 14   # second R14 pick used
    assert out["c"].recommended_round == 13   # only the third drops to R13


def test_adp_rank_to_round():
    assert engine.adp_rank_to_round(1, 8) == 1
    assert engine.adp_rank_to_round(8, 8) == 1
    assert engine.adp_rank_to_round(9, 8) == 2
    assert engine.adp_rank_to_round(None, 8) is None


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failed else 0)
