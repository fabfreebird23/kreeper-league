"""Keeper eligibility + cost rules for The Kreeper League.

Rules (house rules, configurable in config.yaml):
  * A regular keeper can be kept at most `max_keep_years` (3) consecutive years.
  * Rookie keepers can be kept for their whole career. Moving a rookie keeper
    into a regular keeper slot starts the 3-year clock.
  * Year 1 keeping:  kept at the round they were drafted.
  * Year 2 keeping:  bumped up `year2_bump_rounds` (3) rounds, OR kept at ADP
                     (manager's choice — whichever they prefer).
  * Year 3 keeping:  must be kept at ADP.

ADP arrives as an overall consensus rank; we convert it to a draft round for
this league with ceil(rank / num_teams).
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import config


def adjust_to_owned(target: Optional[int], owned, draft_rounds: int) -> Optional[int]:
    """If the team doesn't own a pick in `target` round, return their next-highest
    owned round (earlier round first, e.g. R7 traded -> R6). No reservation."""
    if not target or owned is None:
        return target
    if owned.get(target, 0) > 0:
        return target
    for r in range(target - 1, 0, -1):
        if owned.get(r, 0) > 0:
            return r
    for r in range(target + 1, draft_rounds + 1):
        if owned.get(r, 0) > 0:
            return r
    return target


def adp_rank_to_round(adp_rank: Optional[float], num_teams: int) -> Optional[int]:
    if adp_rank is None or adp_rank <= 0:
        return None
    return max(1, math.ceil(adp_rank / num_teams))


@dataclass
class CostOption:
    label: str
    round: Optional[int]


@dataclass
class KeeperCost:
    eligible: bool
    keep_year: Any              # 1, 2, 3, or "Rookie"
    recommended_round: Optional[int]
    options: List[CostOption] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    reason: str = ""            # why ineligible, when eligible is False

    @property
    def recommended_label(self) -> str:
        if not self.eligible:
            return "—"
        if self.recommended_round is None:
            return "No pick" if self.keep_year == "Rookie" else "ADP (TBD)"
        return f"Round {self.recommended_round}"


def compute(
    profile: Dict[str, Any],
    adp_rank: Optional[float],
    is_rookie_keeper: bool = False,
    rules: Optional[Dict[str, Any]] = None,
    num_teams: Optional[int] = None,
) -> KeeperCost:
    rules = rules or config.rules()
    num_teams = num_teams or config.num_teams()
    adp_round = adp_rank_to_round(adp_rank, num_teams)
    original_round = profile.get("original_round")
    notes: List[str] = []

    # --- Rookie keepers: career-long, exempt from the 3-year clock ----------
    if is_rookie_keeper:
        mode = rules.get("rookie_keeper_cost", "last_rounds")
        if mode == "last_rounds":
            # Actual round is assigned by allocate_keeper_costs (last rounds first);
            # this per-player path is only a placeholder when called standalone.
            rnd, label = None, "Your last rounds (allocated)"
        elif mode == "free":
            rnd, label = None, "No pick cost"
        elif mode == "fixed_round":
            rnd = int(rules.get("rookie_fixed_round", num_teams))
            label = f"Round {rnd} (fixed rookie cost)"
        else:  # original_round
            rnd = original_round
            label = (
                f"Round {rnd} (rookie draft round)"
                if rnd
                else "Rookie draft round (unknown — set manually)"
            )
        return KeeperCost(
            eligible=True,
            keep_year="Rookie",
            recommended_round=rnd,
            options=[CostOption(label, rnd)],
            notes=notes
            + ["Rookie keeper — eligible for their whole career while in the rookie slot."],
        )

    # --- Regular keepers -----------------------------------------------------
    next_year = int(profile.get("next_keep_year", 1))
    max_years = int(rules.get("max_keep_years", 3))

    if next_year > max_years:
        return KeeperCost(
            eligible=False,
            keep_year=next_year,
            recommended_round=None,
            reason=f"Already kept {max_years} years — no longer eligible "
            "(unless they're a rookie keeper).",
            notes=notes,
        )

    if next_year == 1:
        if original_round is None:
            notes.append("No draft round on record — defaulting to last round.")
            original_round = int(config.league()["draft_rounds"])
        opt = CostOption(f"Round {original_round} (where drafted)", original_round)
        return KeeperCost(
            eligible=True,
            keep_year=1,
            recommended_round=original_round,
            options=[opt],
            notes=notes,
        )

    if next_year == 2:
        bump = int(rules.get("year2_bump_rounds", 3))
        bumped = max(1, (original_round or config.league()["draft_rounds"]) - bump)
        options = [CostOption(f"Round {bumped} (bumped up {bump})", bumped)]
        # ADP can only RAISE a keeper's cost, never lower it: it's offered as an
        # option only when it's at least as expensive as the bump (an earlier /
        # lower-or-equal round). A cheaper ADP is disallowed.
        if adp_round is not None and adp_round <= bumped:
            options.append(CostOption(f"Round {adp_round} (ADP)", adp_round))
        elif adp_round is not None:
            notes.append(
                f"ADP would be round {adp_round} — cheaper than the bump (round "
                f"{bumped}), so it's not allowed; ADP can't lower a keeper's cost."
            )
        else:
            notes.append("ADP not available yet — only the bump option is shown.")
        # Recommended = cheapest allowed option (the bump; ADP, when offered, is
        # never cheaper than it).
        recommended = bumped
        return KeeperCost(
            eligible=True,
            keep_year=2,
            recommended_round=recommended,
            options=options,
            notes=notes,
        )

    # next_year == 3 (== max_years): kept at ADP, but never cheaper than the
    # round they cost last year (ADP can raise the cost, not discount it).
    prev_round = (profile.get("last_season_record") or {}).get("round")
    cost_round = adp_round
    if adp_round is not None and prev_round and adp_round > prev_round:
        cost_round = int(prev_round)
        notes.append(
            f"ADP would be round {adp_round} — cheaper than last year's round "
            f"{prev_round}; floored at round {prev_round} (ADP can't lower the cost)."
        )
        label = f"Round {cost_round} (ADP floored at last year's round)"
    else:
        label = f"Round {adp_round} (ADP — required)" if adp_round else "ADP (required)"
    if adp_round is None:
        notes.append("ADP not available yet — cost will be set from ADP closer to the draft.")
    return KeeperCost(
        eligible=True,
        keep_year=3,
        recommended_round=cost_round,
        options=[CostOption(label, cost_round)],
        notes=notes,
    )


def _resolve_choice(cost: KeeperCost, year2_choice: Optional[str]) -> Optional[int]:
    """For a Year-2 keeper, pick the round matching the manager's chosen option."""
    if cost.keep_year == 2 and year2_choice:
        for o in cost.options:
            if o.label.startswith(year2_choice):
                return o.round
    return cost.recommended_round


def allocate_keeper_costs(
    items: List[Dict[str, Any]],
    draft_rounds: Optional[int] = None,
    num_teams: Optional[int] = None,
    rules: Optional[Dict[str, Any]] = None,
    owned=None,
) -> Dict[str, KeeperCost]:
    """Compute every keeper's cost for one manager, handling round allocation.

    Each keeper must land on a pick the team actually OWNS. If they don't own the
    target round (traded it away), the keeper slots at their next-highest owned
    pick (e.g. a kept-at-R7 player when R7 was traded -> R6). `owned` is a Counter
    of {round: picks owned}; default = one pick per round.

    Order: rookie keepers claim the last owned rounds, then drafted keepers take
    (or bump to) their owned round, then undrafted/waiver pickups take the latest
    owned round. Each item: {player_id, is_rookie, profile, adp_rank, year2_choice}.
    """
    rules = rules or config.rules()
    num_teams = num_teams or config.num_teams()
    draft_rounds = draft_rounds or int(config.league()["draft_rounds"])
    if owned is None:
        owned = Counter({r: 1 for r in range(1, draft_rounds + 1)})
    consumed: Counter = Counter()

    def _avail(r: int) -> bool:
        return owned.get(r, 0) - consumed.get(r, 0) > 0

    def take_bottom() -> Optional[int]:
        for r in range(draft_rounds, 0, -1):
            if _avail(r):
                consumed[r] += 1
                return r
        return None

    def take_near(target: Optional[int]) -> Optional[int]:
        """Owned pick at target, else next-highest (earlier) owned, else later."""
        if target and _avail(target):
            consumed[target] += 1
            return target
        for r in range((target or draft_rounds) - 1, 0, -1):
            if _avail(r):
                consumed[r] += 1
                return r
        for r in range((target or 0) + 1, draft_rounds + 1):
            if _avail(r):
                consumed[r] += 1
                return r
        return target

    results: Dict[str, KeeperCost] = {}

    def _bumped_note(want, got):
        if want and got and want != got:
            return [f"You don't own a round {want} pick (traded away) — "
                    f"slotted at your next pick, round {got}."]
        return []

    # 1) Rookie keepers -> last owned rounds first.
    for it in [i for i in items if i.get("is_rookie")]:
        rnd = take_bottom()
        results[it["player_id"]] = KeeperCost(
            eligible=True,
            keep_year="Rookie",
            recommended_round=rnd,
            options=[CostOption(f"Round {rnd} (rookie — last rounds)" if rnd else "No round left", rnd)],
            notes=["Rookie keeper — kept for their whole career; costs your last rounds."],
        )

    # 2) Drafted / traded regular keepers -> normal rules, snapped to an owned pick.
    waivers: List[Dict[str, Any]] = []
    for it in [i for i in items if not i.get("is_rookie")]:
        prof = it["profile"]
        inherits = (
            not it.get("from_rookie")
            and prof.get("acquired_via") in ("draft", "trade")
            and prof.get("original_round")
        )
        if not inherits:
            waivers.append(it)
            continue
        cost = compute(prof, it.get("adp_rank"), False, rules, num_teams)
        if cost.eligible:
            want = _resolve_choice(cost, it.get("year2_choice"))
            got = take_near(want)
            cost.recommended_round = got
            cost.notes = (cost.notes or []) + _bumped_note(want, got)
        if prof.get("acquired_via") == "trade":
            cost.notes = (cost.notes or []) + [
                "Traded in — keeper round and year clock carried over from the previous owner."
            ]
        results[it["player_id"]] = cost

    # 3) Last-round slots: undrafted/waiver pickups AND rookie->regular conversions.
    for it in waivers:
        base = take_bottom()
        prof = dict(it["profile"])
        prof["original_round"] = base
        prof["acquired_via"] = "draft"  # base round is now their cost anchor
        if it.get("from_rookie"):
            prof["next_keep_year"] = 1
            prof["consecutive_keeper_years"] = 0
        cost = compute(prof, it.get("adp_rank"), False, rules, num_teams)
        if cost.eligible:
            cost.recommended_round = _resolve_choice(cost, it.get("year2_choice"))
        if it.get("from_rookie"):
            cost.notes = (cost.notes or []) + [
                "Converted from rookie keeper — kept at a last-round pick; "
                "the 3-year clock starts now."
            ]
        else:
            cost.notes = (cost.notes or []) + [
                "Undrafted/waiver pickup — kept at your latest available round "
                "(rookie keepers take the last rounds first)."
            ]
        results[it["player_id"]] = cost

    return results
