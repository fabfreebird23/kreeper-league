"""FAAB budget tracking for The Kreeper League.

House rule: the consolation-bracket champion wins the season's total
UNSPENT FAAB pot at year end (see kreeper/lottery.py for how that champion
is determined). Every dollar a team spends on a waiver claim is a dollar
that would otherwise be sitting in that pot — framed here as running up
"debt" against it, not as "budget remaining."

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
    """The league-wide unspent total — what the consolation-bracket champion
    wins at year end if nobody spends any more FAAB. Shrinks as the league
    spends; the final number isn't known until the season ends."""
    budgets = team_budgets(league_id)
    total_budget = sum(b["total"] for b in budgets.values())
    total_spent = sum(b["spent"] for b in budgets.values())
    return {"total_budget": total_budget, "total_spent": total_spent,
            "pot": total_budget - total_spent, "teams": len(budgets)}


def _all_transactions(league_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for wk in range(1, _MAX_WEEK + 1):
        out.extend(sleeper.get_transactions(league_id, wk))
    return out


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
