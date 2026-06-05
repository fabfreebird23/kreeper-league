"""Reconstruct keeper streaks and original draft rounds from Sleeper draft history.

Everything here is derived from real draft picks across the league's season
chain (2023 -> current), so a player's "where they were drafted" and how many
consecutive years a manager has kept them are computed, not transcribed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import config, sleeper


@dataclass
class PlayerMeta:
    player_id: str
    name: str
    position: str
    team: str


@dataclass
class DraftHistory:
    # (owner_id, player_id) -> [{season, round, pick_no, is_keeper}], newest first
    by_owner_player: Dict[Tuple[str, str], List[Dict[str, Any]]]
    # player_id -> any-owner draft rounds by season {season: round}
    any_owner_rounds: Dict[str, Dict[int, int]]
    # player_id -> {season: {"round", "is_keeper", "owner"}} across ALL owners.
    # This is what lets a traded player carry their keeper round/clock to the new owner.
    player_seasons: Dict[str, Dict[int, Dict[str, Any]]]
    players: Dict[str, Any]
    seasons: List[int]
    meta: Dict[str, PlayerMeta] = field(default_factory=dict)
    # (player_id, season) the player was a keeper per our seeded ledger (the
    # league spreadsheet). Sleeper's is_keeper flag is unreliable for older
    # seasons (2024 had only 2 of ~24 keepers flagged), so this is authoritative.
    kept_set: set = field(default_factory=set)

    def player_meta(self, player_id: str) -> PlayerMeta:
        if player_id in self.meta:
            return self.meta[player_id]
        p = self.players.get(str(player_id), {}) or {}
        name = p.get("full_name") or " ".join(
            x for x in [p.get("first_name"), p.get("last_name")] if x
        ) or f"Player {player_id}"
        pm = PlayerMeta(
            player_id=str(player_id),
            name=name,
            position=p.get("position") or "",
            team=p.get("team") or "FA",
        )
        self.meta[player_id] = pm
        return pm

    def keeper_profile(
        self, owner_id: str, player_id: str, target_season: int
    ) -> Dict[str, Any]:
        """The player's keeper chain and base round — followed across owners.

        Keeper provenance follows the PLAYER, not the manager: a trade carries
        the keeper round and the consecutive-year clock to the new owner. Only a
        player who went undrafted last season (true waiver/undrafted pickup)
        starts fresh.

        next_keep_year: 1 if keeping next season would be the first year.
        original_round: the round that started the keeper streak (where drafted).
        acquired_via: 'draft' (this owner had them last year),
                      'trade'  (another owner drafted/kept them last year),
                      'undrafted' (not in last year's draft at all).
        """
        owner = str(owner_id)
        pid = str(player_id)
        pseasons = self.player_seasons.get(pid, {})
        own_by_season = {
            r["season"]: r for r in self.by_owner_player.get((owner, pid), [])
        }
        prev = target_season - 1

        # A season counts as a keep if Sleeper flagged it OR our seeded ledger
        # (the spreadsheet) records the player as a keeper that year.
        def _kept(season: int) -> bool:
            rec = pseasons.get(season)
            return bool(rec and rec.get("is_keeper")) or (pid, season) in self.kept_set

        # Consecutive keeper seasons (under ANY owner) ending last season.
        consecutive_keeper = 0
        s = prev
        while _kept(s):
            consecutive_keeper += 1
            s -= 1

        # Acquisition season = the draft pick that started the streak.
        acq_season = prev - consecutive_keeper
        original_round: Optional[int] = None
        if acq_season in pseasons:
            original_round = pseasons[acq_season]["round"]
        elif prev in pseasons:
            # Streak predates our data window — anchor on the oldest round we have.
            original_round = pseasons[min(pseasons)]["round"]

        present_last_year = prev in pseasons
        if prev in own_by_season:
            acquired_via = "draft"
        elif present_last_year:
            acquired_via = "trade"
        else:
            acquired_via = "undrafted"

        prev_owner = None
        if present_last_year and str(pseasons[prev]["owner"]) != owner:
            prev_owner = str(pseasons[prev]["owner"])

        return {
            "consecutive_keeper_years": consecutive_keeper,
            "next_keep_year": consecutive_keeper + 1,
            "original_round": original_round,
            "acquired_via": acquired_via,
            "prev_owner": prev_owner,
            "last_season_record": pseasons.get(prev),
        }


def build_history(league_id: Optional[str] = None) -> DraftHistory:
    league_id = league_id or config.league()["sleeper_league_id"]
    chain = sleeper.league_chain(league_id)
    players = sleeper.get_players()

    by_owner_player: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    any_owner_rounds: Dict[str, Dict[int, int]] = {}
    player_seasons: Dict[str, Dict[int, Dict[str, Any]]] = {}
    seasons: List[int] = []

    for node in chain:
        draft_id = node.get("draft_id")
        season = node["season"]
        if not draft_id:
            continue
        picks = sleeper.get_draft_picks(draft_id)
        if not picks:
            continue
        seasons.append(season)
        for pk in picks:
            pid = str(pk.get("player_id") or "")
            owner = str(pk.get("picked_by") or "")
            if not pid or not owner:
                continue
            rnd = int(pk.get("round") or 0)
            rec = {
                "season": season,
                "round": rnd,
                "pick_no": pk.get("pick_no"),
                "is_keeper": bool(pk.get("is_keeper")),
            }
            by_owner_player.setdefault((owner, pid), []).append(rec)
            any_owner_rounds.setdefault(pid, {})[season] = rnd
            player_seasons.setdefault(pid, {})[season] = {
                "round": rnd,
                "is_keeper": bool(pk.get("is_keeper")),
                "owner": owner,
            }

    # Sort each owner/player record list newest-first for convenience.
    for recs in by_owner_player.values():
        recs.sort(key=lambda r: r["season"], reverse=True)

    # Authoritative keeper ledger from the seeded spreadsheet (every saved
    # selection in a prior season's file is a keeper that year).
    from . import storage
    kept_set: set = set()
    cur = config.current_season()
    for yr in range(cur - 6, cur):
        for picks in storage.load(yr).values():
            for sel in picks:
                pidx = sel.get("player_id")
                if pidx:
                    kept_set.add((str(pidx), yr))

    return DraftHistory(
        by_owner_player=by_owner_player,
        any_owner_rounds=any_owner_rounds,
        player_seasons=player_seasons,
        players=players,
        seasons=sorted(set(seasons), reverse=True),
        kept_set=kept_set,
    )


def roster_candidates(league_id: Optional[str] = None) -> Dict[str, List[str]]:
    """owner_id -> list of player_ids currently on their roster (keeper pool)."""
    league_id = league_id or config.league()["sleeper_league_id"]
    out: Dict[str, List[str]] = {}
    for r in sleeper.get_rosters(league_id):
        owner = str(r.get("owner_id") or "")
        if owner:
            out[owner] = [str(p) for p in (r.get("players") or [])]
    return out
