"""Build the draft-board model: who owns each pick, accounting for trades.

The board is rounds (rows) x draft slots (columns). Each cell is one pick. Base
ownership comes from the draft's slot_to_roster_id (snake order); Sleeper's
traded_picks then reassign individual picks to their new owners. Submitted
keepers are overlaid onto the pick they cost in app.py.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Optional

from . import config, sleeper


def owned_picks_by_owner(league_id: Optional[str] = None, season: Optional[int] = None) -> Dict[str, Counter]:
    """owner_id -> Counter({round: num_picks_owned}) after trades.

    Each team starts with one pick per round; traded picks move a round's pick
    from the original owner to the new owner (a team can end up with two of a
    round or none of a round).
    """
    league_id = league_id or config.league()["sleeper_league_id"]
    season = season or config.current_season()
    rounds = int(config.league()["draft_rounds"])
    roster_to_owner = {
        int(r["roster_id"]): str(r.get("owner_id"))
        for r in sleeper.get_rosters(league_id)
    }
    owned: Dict[str, Counter] = {o: Counter() for o in roster_to_owner.values()}
    for owner in roster_to_owner.values():
        for r in range(1, rounds + 1):
            owned[owner][r] += 1
    for tp in sleeper.get_traded_picks(league_id):
        if str(tp.get("season")) != str(season):
            continue
        r = int(tp["round"])
        orig = roster_to_owner.get(int(tp["roster_id"]))
        new = roster_to_owner.get(int(tp["owner_id"]))
        if orig:
            owned[orig][r] -= 1
        if new:
            owned[new][r] += 1
    return owned


def _short(name: str) -> str:
    return name.split()[0] if name else "?"


def build_board(league_id: Optional[str] = None, season: Optional[int] = None) -> Dict[str, Any]:
    league_id = league_id or config.league()["sleeper_league_id"]
    season = season or config.current_season()

    lg = sleeper.get_league(league_id)
    draft = sleeper.get_draft(lg["draft_id"])
    rounds = int(draft.get("settings", {}).get("rounds") or config.league()["draft_rounds"])
    teams = int(draft.get("settings", {}).get("teams") or config.num_teams())

    roster_to_owner = {
        int(r["roster_id"]): str(r.get("owner_id"))
        for r in sleeper.get_rosters(league_id)
    }

    # Draft order (slot -> roster_id). Prefer the manual order from config; fall
    # back to Sleeper's slot_to_roster_id, then to default roster order.
    manual_order = config.load().get("draft_order")
    if manual_order:
        owner_to_roster = {o: rid for rid, o in roster_to_owner.items()}
        slot_to_roster = {i + 1: owner_to_roster.get(str(oid))
                          for i, oid in enumerate(manual_order)}
        order_is_set = True
    else:
        slot_to_roster = {int(k): int(v) for k, v in (draft.get("slot_to_roster_id") or {}).items()}
        if not slot_to_roster:
            slot_to_roster = {s: s for s in range(1, teams + 1)}
        order_is_set = bool(draft.get("draft_order"))

    # (round, original_roster_id) -> new owner roster_id
    traded: Dict[tuple, int] = {}
    for tp in sleeper.get_traded_picks(league_id):
        if str(tp.get("season")) != str(season):
            continue
        traded[(int(tp["round"]), int(tp["roster_id"]))] = int(tp["owner_id"])

    def owner_name(roster_id: int) -> str:
        return config.manager_name(roster_to_owner.get(roster_id, ""))

    cells: Dict[tuple, Dict[str, Any]] = {}
    for r in range(1, rounds + 1):
        for slot in range(1, teams + 1):
            base_roster = slot_to_roster.get(slot, slot)
            owner_roster = traded.get((r, base_roster), base_roster)
            pick_in_round = slot if r % 2 == 1 else (teams - slot + 1)  # snake
            cells[(r, slot)] = {
                "base_roster": base_roster,
                "owner_roster": owner_roster,
                "owner_name": owner_name(owner_roster),
                "owner_short": _short(owner_name(owner_roster)),
                "base_short": _short(owner_name(base_roster)),
                "traded": owner_roster != base_roster,
                "pick_no": (r - 1) * teams + pick_in_round,
            }

    owner_to_slot = {
        roster_to_owner.get(slot_to_roster.get(slot, slot)): slot
        for slot in range(1, teams + 1)
    }
    slot_team = {slot: owner_name(slot_to_roster.get(slot, slot)) for slot in range(1, teams + 1)}

    return {
        "rounds": rounds,
        "teams": teams,
        "cells": cells,
        "slot_team": slot_team,
        "owner_to_slot": owner_to_slot,
        "owner_to_roster": {o: rid for rid, o in roster_to_owner.items()},
        "order_set": order_is_set,
    }
