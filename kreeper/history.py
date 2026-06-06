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
    # Subset of kept_set where the keep was a ROOKIE keeper. Rookie-keeper years
    # are career-exempt, so they must NOT advance the 3-year regular-keeper clock.
    rookie_kept_set: set = field(default_factory=set)

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

        def _kept_regular(season: int) -> bool:
            # A REGULAR (non-rookie) keep. Rookie-keeper years are career-exempt
            # and don't advance the 3-year clock — the clock starts at conversion.
            return _kept(season) and (pid, season) not in self.rookie_kept_set

        # Consecutive REGULAR keeper seasons (under ANY owner) ending last season.
        consecutive_keeper = 0
        s = prev
        while _kept_regular(s):
            consecutive_keeper += 1
            s -= 1

        # Anchor round = the cost basis the regular-keeper streak started from.
        original_round: Optional[int] = None
        if consecutive_keeper == 0:
            # Next year would be Year 1 — anchor on last year's (draft) round.
            if prev in pseasons:
                original_round = pseasons[prev]["round"]
        else:
            first_regular = prev - consecutive_keeper + 1  # first regular keep season
            anchor = first_regular - 1                     # season that set the basis
            if _kept(anchor):
                # The basis season was itself a keep — a rookie->regular conversion
                # (kept at a last round) or a streak predating our data. Anchor on
                # the first regular keep round, not the rookie-era draft round.
                original_round = (pseasons.get(first_regular) or {}).get("round")
            elif anchor in pseasons:
                original_round = pseasons[anchor]["round"]  # the draft that started it
            if original_round is None and prev in pseasons:
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

    # Fetch every season's draft picks concurrently (each is an independent,
    # disk-cached Sleeper call) — the chain walk above is the only sequential part.
    from concurrent.futures import ThreadPoolExecutor

    drafts = [(n["season"], n["draft_id"]) for n in chain if n.get("draft_id")]
    picks_by_season: Dict[int, List[Dict[str, Any]]] = {}
    if drafts:
        with ThreadPoolExecutor(max_workers=min(8, len(drafts))) as ex:
            for (season, _), picks in zip(
                drafts, ex.map(lambda d: sleeper.get_draft_picks(d[1]), drafts)
            ):
                picks_by_season[season] = picks or []

    for season, _draft_id in drafts:
        picks = picks_by_season.get(season) or []
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
    rookie_kept_set: set = set()
    cur = config.current_season()
    for yr in range(cur - 6, cur):
        for picks in storage.load(yr).values():
            for sel in picks:
                pidx = sel.get("player_id")
                if pidx:
                    kept_set.add((str(pidx), yr))
                    if sel.get("is_rookie_keeper"):
                        rookie_kept_set.add((str(pidx), yr))

    return DraftHistory(
        by_owner_player=by_owner_player,
        any_owner_rounds=any_owner_rounds,
        player_seasons=player_seasons,
        players=players,
        seasons=sorted(set(seasons), reverse=True),
        kept_set=kept_set,
        rookie_kept_set=rookie_kept_set,
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
