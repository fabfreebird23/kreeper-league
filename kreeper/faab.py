"""FAAB budget tracking for The Kreeper League.

House rule (2026 vote — see the Rules page; replaced the old "consolation
champion wins the UNSPENT pot" rule entirely): the pot is every dollar
SPENT league-wide this season, and it's split two ways at year end —
  * The winner of the winners-bracket 3rd-place game (the two round-1
    losers play each other; that's bracket placement 3) gets back exactly
    what THEY personally spent.
  * 5th place — the consolation-bracket CHAMPION, i.e. the best of the
    non-playoff teams — gets whatever remains.
So spending is no longer purely "debt against the pot": it both grows the
pot and sets what the 3rd-place-game winner could win back.

Pure logic module — no Streamlit here.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import config, sleeper

# Sleeper caps a season at 18 legs (regular season + playoffs); scanning the
# full range is cheap (disk-cached per week) and avoids guessing where the
# season actually ends.
_MAX_WEEK = 18


def _roster_to_owner(league_id: str) -> Dict[int, str]:
    return {int(r["roster_id"]): str(r.get("owner_id")) for r in sleeper.get_rosters(league_id)}


def team_budgets(league_id: Optional[str] = None) -> Dict[str, Dict[str, int]]:
    """owner_id -> {total, spent, remaining} for this season's FAAB, straight
    from Sleeper's own per-roster running total (no need to sum transactions
    for this — Sleeper already tracks `waiver_budget_used`)."""
    league_id = league_id or config.league()["sleeper_league_id"]
    total = int(sleeper.get_league(league_id).get("settings", {}).get("waiver_budget", 100) or 100)
    out: Dict[str, Dict[str, int]] = {}
    for r in sleeper.get_rosters(league_id):
        owner = str(r.get("owner_id"))
        spent = int((r.get("settings") or {}).get("waiver_budget_used", 0) or 0)
        out[owner] = {"total": total, "spent": spent, "remaining": max(0, total - spent)}
    return out


def projected_pot(league_id: Optional[str] = None) -> Dict[str, int]:
    """The year-end FAAB pot: everything SPENT league-wide so far (2026 rule).
    GROWS as the league spends; the final number isn't known until the season
    ends. `unspent` is kept alongside purely as context for the UI — it is no
    longer what anybody wins."""
    budgets = team_budgets(league_id)
    total_budget = sum(b["total"] for b in budgets.values())
    total_spent = sum(b["spent"] for b in budgets.values())
    return {"total_budget": total_budget, "total_spent": total_spent,
            "pot": total_spent, "unspent": total_budget - total_spent,
            "teams": len(budgets)}


def pot_split(league_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """How the FAAB pot actually pays out, once the season is complete:
    {"pot", "third_place": {owner, refund}, "fifth_place": {owner, amount}}.

    The winners-bracket 3rd-place game's winner (bracket placement 3) takes
    back exactly their own spend; the consolation-bracket champion (placement
    1 of that bracket = 5th overall) takes the remainder. Returns None if
    either bracket isn't fully decided yet.

    The refund is capped at the pot — it can't exceed what's actually in it
    (only reachable in a degenerate season where one team is nearly the sole
    spender), which also keeps 5th place's share from going negative.
    """
    from . import lottery

    league_id = league_id or config.league()["sleeper_league_id"]
    wb = lottery._resolve_bracket_placements(sleeper.get_winners_bracket(league_id), league_id)
    lb = lottery._resolve_bracket_placements(sleeper.get_losers_bracket(league_id), league_id)
    if not wb or not lb:
        return None

    r2o = _roster_to_owner(league_id)
    budgets = team_budgets(league_id)
    pot = sum(b["spent"] for b in budgets.values())

    third = r2o.get(wb.get(3))
    fifth = r2o.get(lb.get(1))
    refund = min(pot, budgets.get(third, {}).get("spent", 0))
    return {
        "pot": pot,
        "third_place": {"owner": third, "refund": refund},
        "fifth_place": {"owner": fifth, "amount": pot - refund},
    }


def entry_pot(league_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The cash entry pot and who it pays, once the season is complete:
    {"total", "entry_fee", "champion": {owner, amount}, "runner_up": {...}}.

    2nd place doubles their buy-in; the champion takes the balance. Returns
    None if the championship bracket isn't decided yet.
    """
    from . import lottery

    league_id = league_id or config.league()["sleeper_league_id"]
    wb = lottery._resolve_bracket_placements(sleeper.get_winners_bracket(league_id), league_id)
    if not wb:
        return None

    r2o = _roster_to_owner(league_id)
    fee = config.entry_fee()
    total = fee * len(r2o)
    runner_up_take = fee * 2
    return {
        "total": total,
        "entry_fee": fee,
        "champion": {"owner": r2o.get(wb.get(1)), "amount": total - runner_up_take},
        "runner_up": {"owner": r2o.get(wb.get(2)), "amount": runner_up_take},
    }


def _all_transactions(league_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for wk in range(1, _MAX_WEEK + 1):
        out.extend(sleeper.get_transactions(league_id, wk))
    return out


def weekly_spend(league_id: Optional[str] = None) -> Dict[str, Dict[int, int]]:
    """owner_id -> {week: dollars spent that week}. Only COMPLETED waiver
    claims with a real bid count — failed claims and $0 free-agent adds
    never move money, so counting them would overstate the pot.
    """
    league_id = league_id or config.league()["sleeper_league_id"]
    r2o = _roster_to_owner(league_id)
    out: Dict[str, Dict[int, int]] = {o: {} for o in r2o.values() if o}

    for tx in _all_transactions(league_id):
        if tx.get("type") != "waiver" or tx.get("status") != "complete":
            continue
        bid = int((tx.get("settings") or {}).get("waiver_bid", 0) or 0)
        if bid <= 0:
            continue
        week = int(tx.get("leg") or 0)
        for rid in (tx.get("adds") or {}).values():
            owner = r2o.get(int(rid))
            if owner is None:
                continue
            out[owner][week] = out[owner].get(week, 0) + bid
    return out


def burndown(league_id: Optional[str] = None,
             weeks: Optional[int] = None) -> Dict[str, Any]:
    """Cumulative FAAB spend per team, week by week — the pot filling up.

    {"weeks": [1..N], "budget": int,
     "teams": [{owner, points: [cumulative $ after each week], total}, ...]}
    sorted biggest spender first. A flat line is a team sitting on their
    budget; the gap between a line and the ceiling is what they still have
    to spend.
    """
    league_id = league_id or config.league()["sleeper_league_id"]
    budgets = team_budgets(league_id)
    budget = max((b["total"] for b in budgets.values()), default=100)
    per_week = weekly_spend(league_id)
    if weeks is None:
        # Span the whole season, NOT just the regular season — waivers stay
        # open through the playoffs and real money moves there (in 2025 six
        # of eight teams spent in weeks 13-16). Cutting at
        # playoff_week_start silently dropped that spend and left the chart
        # disagreeing with the pot total on the same page.
        last_spend = max((wk for by in per_week.values() for wk in by), default=0)
        settings = sleeper.get_league(league_id).get("settings", {}) or {}
        reg = max(1, int(settings.get("playoff_week_start") or 15) - 1)
        weeks = max(reg, last_spend)
    teams = []
    for owner, by_week in per_week.items():
        running, pts = 0, []
        for wk in range(1, weeks + 1):
            running += by_week.get(wk, 0)
            pts.append(running)
        teams.append({"owner": owner, "points": pts, "total": running})
    teams.sort(key=lambda t: -t["total"])
    return {"weeks": list(range(1, weeks + 1)), "budget": budget, "teams": teams}


def dead_money(league_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """owner_id -> {dead, live, moves}. "Dead" money is FAAB spent on a
    completed waiver claim for a player who is NOT on that team's CURRENT
    roster anymore (dropped — a bust). "Live" is FAAB spent on a player
    still rostered right now. `moves` lists every priced waiver add for
    that team, newest first, each tagged with whether it's still rostered.
    """
    league_id = league_id or config.league()["sleeper_league_id"]
    r2o = _roster_to_owner(league_id)
    current_players = {
        int(r["roster_id"]): {str(p) for p in (r.get("players") or [])}
        for r in sleeper.get_rosters(league_id)
    }
    out: Dict[str, Dict[str, Any]] = {o: {"dead": 0, "live": 0, "moves": []} for o in r2o.values()}

    for tx in _all_transactions(league_id):
        if tx.get("type") != "waiver" or tx.get("status") != "complete":
            continue
        bid = int((tx.get("settings") or {}).get("waiver_bid", 0) or 0)
        if bid <= 0:
            continue
        for pid, rid in (tx.get("adds") or {}).items():
            rid = int(rid)
            owner = r2o.get(rid)
            if owner is None:
                continue
            still_rostered = str(pid) in current_players.get(rid, set())
            out[owner]["dead" if not still_rostered else "live"] += bid
            out[owner]["moves"].append({
                "player_id": str(pid), "bid": bid, "week": tx.get("leg"),
                "still_rostered": still_rostered,
            })

    for rec in out.values():
        rec["moves"].sort(key=lambda m: -(m.get("week") or 0))
    return out
