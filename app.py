"""The Kreeper League — Keeper Hub (Streamlit app).

Pages (sidebar nav):
  Home            — top-30 keeper-value leaderboard + per-team submitted keepers
  Set my keepers  — pick your roster's keepers, with live cost + eligibility
  Consensus ADP   — daily multi-source consensus ADP (all sources averaged)
"""
from __future__ import annotations

import datetime as dt
import json
import math
import random
import re

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from kreeper import config, draftboard, engine, history, storage, theme
from kreeper.adp import consensus as adp_consensus
from kreeper.names import normalize_name

st.set_page_config(page_title="The Kreeper League — Keeper Hub", page_icon="🏈", layout="wide")
theme.inject(st)

LEAGUE = config.league()
SEASON = config.current_season()
MANAGERS = config.managers()  # owner_id -> {handle, name, team}
NAME_TO_ID = {m["name"]: oid for oid, m in MANAGERS.items()}
NT = int(LEAGUE["num_teams"])
DRAFT_ROUNDS = int(LEAGUE["draft_rounds"])
MAX_REG = int(LEAGUE.get("max_regular_keepers", 3))
MAX_ROOKIE = int(LEAGUE.get("max_rookie_keepers", 2))
# Realistic draft pool: every pick in the draft (teams x rounds). ADP risers /
# fallers are scoped to this so we only see players we'd actually draft.
DRAFT_SCOPE_RANK = NT * DRAFT_ROUNDS

# Light league trash-talk, sprinkled around the dashboard. Strictly fantasy ribbing.
_NED_QUIPS = [
    "Ned traded away his draft picks again. Bold strategy.",
    "Somewhere out there, Ned is making another terrible trade.",
    "Ned's war chest: a participation trophy and a 14th-round pick.",
    "Whatever you're worried about, at least you're not Ned.",
    "Ned could not be reached for comment (he's busy losing).",
    "Reminder: Ned can't even keep his own good players.",
    "Power move of the offseason: not being Ned.",
    "Ned's keeper strategy is just vibes and regret.",
    "This dashboard runs on data, ADP, and dunking on Ned.",
    "Ned out here rostering Kyle Monangai like it's a flex.",
    "Ned's title odds are a rounding error, and that's generous.",
    "If draft capital were a personality, Ned would be bankrupt.",
]


def ned() -> str:
    return random.choice(_NED_QUIPS)


def keeper_lock() -> tuple:
    """(deadline_or_None, locked_bool). Locked once now >= the deadline."""
    deadline = config.keeper_deadline()
    if deadline is None:
        return None, False
    now = dt.datetime.now(deadline.tzinfo) if deadline.tzinfo else dt.datetime.now()
    return deadline, now >= deadline


def _fmt_ts(iso: str) -> str:
    try:
        d = dt.datetime.fromisoformat(iso)
        return d.strftime("%b %d, %-I:%M %p")
    except (ValueError, TypeError):
        return iso or ""


_COUNTDOWN_TEMPLATE = """
<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Oswald:wght@500;700&display=swap" rel="stylesheet">
<style>
 *{margin:0;box-sizing:border-box;}
 html,body{background:transparent;overflow:hidden;font-family:'Oswald',sans-serif;}
 .cd{display:flex;flex-direction:column;align-items:center;gap:6px;
   background:#fff;border:2px solid #ff4f9d;border-radius:16px;padding:14px 18px;
   box-shadow:0 6px 22px rgba(123,92,255,.18);}
 .ttl{font-family:'Anton',sans-serif;text-transform:uppercase;letter-spacing:3px;
   font-size:15px;color:#7b5cff;}
 .units{display:flex;gap:16px;}
 .u{display:flex;flex-direction:column;align-items:center;min-width:60px;}
 .u .n{font-family:'Anton',sans-serif;font-size:42px;line-height:1;color:#ff4f9d;
   text-shadow:0 0 12px rgba(255,79,157,.45);}
 .u .l{font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#8b86a0;margin-top:5px;}
 .sub{font-size:12px;letter-spacing:1px;color:#6a6580;}
 .locked{font-family:'Anton',sans-serif;font-size:30px;color:#7b5cff;letter-spacing:2px;}
</style></head><body>
<div class="cd">
  <div class="ttl">&#9203; Keepers Due In</div>
  <div id="units" class="units"></div>
  <div class="sub" id="when"></div>
</div>
<script>
 var target=new Date("__ISO__").getTime();
 var box=document.getElementById('units'), when=document.getElementById('when');
 when.textContent="Announce by "+new Date(target).toLocaleString('en-US',
   {timeZone:'__TZ__',weekday:'long',month:'long',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'});
 function pad(n){return String(n).padStart(2,'0');}
 function tick(){
   var d=target-Date.now();
   if(d<=0){box.innerHTML='<div class="locked">&#128274; KEEPERS LOCKED</div>';
            when.textContent="The deadline has passed.";return;}
   var days=Math.floor(d/86400000),h=Math.floor(d/3600000)%24,
       m=Math.floor(d/60000)%60,s=Math.floor(d/1000)%60;
   var cells=[[days,'Days'],[h,'Hrs'],[m,'Min'],[s,'Sec']];
   box.innerHTML=cells.map(function(c){
     var n=(c[1]==='Days')?c[0]:pad(c[0]);
     return '<div class="u"><div class="n">'+n+'</div><div class="l">'+c[1]+'</div></div>';
   }).join('');
 }
 tick(); setInterval(tick,1000);
</script></body></html>
"""


def render_countdown() -> None:
    deadline = config.keeper_deadline()
    if deadline is None:
        return
    html = (_COUNTDOWN_TEMPLATE
            .replace("__ISO__", deadline.isoformat())
            .replace("__TZ__", config.keeper_timezone_name()))
    components.html(html, height=150)


# ---------------------------------------------------------------- data loaders
@st.cache_resource(show_spinner="Loading league history from Sleeper…")
def get_history() -> history.DraftHistory:
    return history.build_history()


@st.cache_data(ttl=3600, show_spinner=False)
def get_candidates():
    return history.roster_candidates()


@st.cache_data(ttl=300, show_spinner=False)
def get_adp():
    return adp_consensus.load(SEASON), adp_consensus.adp_lookup(SEASON), adp_consensus.load_meta(SEASON)


@st.cache_data(ttl=600, show_spinner=False)
def get_board():
    return draftboard.build_board()


@st.cache_data(ttl=600, show_spinner=False)
def get_owned():
    """owner_id -> Counter of draft rounds the team owns (after trades)."""
    return draftboard.owned_picks_by_owner()


@st.cache_data(ttl=600, show_spinner=False)
def get_owned_for(season: int):
    """owner_id -> Counter of rounds owned for a given (incl. future) season."""
    return draftboard.owned_picks_by_owner(season=season)


@st.cache_data(ttl=86400, show_spinner=False)
def get_name_index():
    """normalized name -> Sleeper player_id (skill positions; prefer active/with team)."""
    from kreeper import sleeper
    idx = {}
    for pid, p in sleeper.get_players().items():
        if p.get("position") not in ("QB", "RB", "WR", "TE"):
            continue
        nm = normalize_name(p.get("full_name") or "")
        if not nm:
            continue
        score = (1 if p.get("active") else 0, 1 if p.get("team") else 0)
        if nm not in idx or score > idx[nm][1]:
            idx[nm] = (pid, score)
    return {k: v[0] for k, v in idx.items()}


@st.cache_data(ttl=86400, show_spinner=False)
def get_espn_headshots():
    """sleeper_pid -> ESPN headshot id, so rookies with no Sleeper photo still
    get a real headshot. Sleeper's own espn_id wins; otherwise match by name to
    ESPN's board. Best-effort — returns {} if ESPN is unreachable."""
    from kreeper import sleeper
    from kreeper.adp import espn
    try:
        by_name = espn.headshot_ids(SEASON)
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for pid, p in sleeper.get_players().items():
        if p.get("position") not in ("QB", "RB", "WR", "TE"):
            continue
        eid = p.get("espn_id") or by_name.get(normalize_name(p.get("full_name") or ""))
        if eid:
            out[str(pid)] = str(eid)
    return out


H = get_history()
CANDS = get_candidates()
ADP_DF, ADP_LK, ADP_META = get_adp()
theme.set_espn_ids(get_espn_headshots())


def adp_rank_for(name: str, position: str = "") -> float | None:
    key = f"{normalize_name(name)}|{position.lower()}" if position else None
    if key and key in ADP_LK:
        return ADP_LK[key]
    return ADP_LK.get(normalize_name(name))


def build_candidate_rows(owner_id: str) -> pd.DataFrame:
    rows = []
    owned = get_owned().get(owner_id)
    for pid in CANDS.get(owner_id, []):
        pm = H.player_meta(pid)
        if pm.position not in ("QB", "RB", "WR", "TE"):
            continue  # keepers are skill-position players in this league
        prof = H.keeper_profile(owner_id, pid, SEASON)
        rank = adp_rank_for(pm.name, pm.position)
        cost = engine.compute(prof, adp_rank=rank, is_rookie_keeper=False)
        from_rookie = bool(storage.prior_rookie_seasons(owner_id, pid, SEASON))
        inherits = (not from_rookie) and prof.get("acquired_via") in ("draft", "trade") and prof.get("original_round")
        no_pick = False
        if inherits:
            # The pick used is the cost round, or the nearest earlier (higher)
            # pick you own. If you own nothing at the cost round or earlier, you
            # can't keep this player.
            placed = engine.adjust_to_owned(cost.recommended_round, owned, DRAFT_ROUNDS)
            if placed is None:
                no_pick = True
                reg_cost = "No pick to keep"
            else:
                reg_cost = f"Round {placed}"
        else:
            reg_cost = "Last rounds"
        if from_rookie:
            keep_year, acq, eligible = 1, "rookie→reg", True
        elif not cost.eligible:
            keep_year, acq, eligible = "DONE", prof.get("acquired_via"), False
        elif no_pick:
            keep_year, acq, eligible = "NO PICK", prof.get("acquired_via"), False
        else:
            keep_year, acq, eligible = cost.keep_year, prof.get("acquired_via"), True
        rows.append(
            {
                "player_id": pid,
                "Photo": theme.headshot(pid),
                "Player": pm.name,
                "Pos": pm.position,
                "NFL": pm.team,
                "Keep Year": keep_year,
                "Eligible": eligible,
                "Reg. Cost": reg_cost,
                "ADP Rank": int(rank) if rank else None,
                "Orig. Rd": prof.get("original_round") if inherits else None,
                "Acq.": acq,
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["Eligible", "ADP Rank"], ascending=[False, True], na_position="last")
    return df.reset_index(drop=True)


def _years_exp(pid: str):
    return (H.players.get(str(pid)) or {}).get("years_exp")


def _was_regular_keeper(pid: str) -> bool:
    """True if the player has ever been kept as a REGULAR (non-rookie) keeper in
    our ledger — i.e. the rookie->regular conversion already happened."""
    pid = str(pid)
    return any(p == pid and (p, s) not in H.rookie_kept_set for (p, s) in H.kept_set)


def rookie_keeper_eligible(owner_id: str, pid: str) -> bool:
    """A player may be kept as a ROOKIE keeper only if THIS team drafted them in
    the player's rookie season and has held them continuously since. A trade (or
    picking them up as a veteran) breaks rookie-keeper eligibility, and the
    rookie->regular move is one-way: once kept as a regular keeper they can never
    return to a rookie keeper.
    """
    pid = str(pid)
    # One-way: a player who has been a regular keeper can't go back to rookie.
    if _was_regular_keeper(pid):
        return False
    # An established rookie keeper for THIS owner stays eligible (seeded ledger
    # may predate our Sleeper draft window).
    if storage.prior_rookie_seasons(owner_id, pid, SEASON):
        return True
    ye = _years_exp(pid)
    if ye is None:
        return False
    rookie_season = SEASON - int(ye)
    ps = H.player_seasons.get(pid, {})
    rec = ps.get(rookie_season)
    # Must be their rookie-season DRAFT pick (not a keeper slot) by THIS owner.
    if not rec or str(rec.get("owner")) != str(owner_id) or rec.get("is_keeper"):
        return False
    # Held continuously since — any season under a different owner = traded.
    for s in range(rookie_season, SEASON):
        r = ps.get(s)
        if r and str(r.get("owner")) != str(owner_id):
            return False
    return True


def current_keepers(season: int | None = None) -> dict:
    """Declared keeper selections, filtered to players the declaring owner still
    rosters per the live Sleeper rosters. A keeper that's been traded away no
    longer counts for the team that gave it up. Selections without a player_id
    can't be validated against a roster, so they're left as-is. Historical
    seasons have no live roster to check against and are returned unfiltered."""
    season = season or SEASON
    raw = storage.load(season)
    if season != SEASON:
        return raw
    out = {}
    for oid, picks in raw.items():
        owned = {str(p) for p in CANDS.get(str(oid), [])}
        kept = [s for s in picks
                if not s.get("player_id") or str(s["player_id"]) in owned]
        if kept:
            out[oid] = kept
    return out


def build_value_leaderboard(top_n: int = 50, hide_rookie_keepers: bool = False) -> pd.DataFrame:
    """Best keeper bargains across every roster.

    Value = keeper-cost round minus ADP round, i.e. how many rounds of draft
    capital you'd gain by keeping the player versus drafting them at market.
    The "Kept" column flags players a manager has already declared as a keeper.
    Real NFL rookies (years_exp == 0) are excluded — they live on the Rookies tab.
    """
    # Players already declared as keepers (match by Sleeper id and by name).
    # Filtered so a keeper traded away no longer counts for the old team.
    submitted = current_keepers()
    kept_ids, kept_names = set(), set()
    for picks in submitted.values():
        for s in picks:
            if s.get("player_id"):
                kept_ids.add(str(s["player_id"]))
            if s.get("player_name"):
                kept_names.add(normalize_name(s["player_name"]))

    # (owner, player) pairs previously kept as a rookie keeper -> last-round cost.
    rookie_hist = set()
    for yr in range(SEASON - 1, SEASON - 7, -1):
        for oid, picks in storage.load(yr).items():
            for s in picks:
                if s.get("is_rookie_keeper") and s.get("player_id"):
                    rookie_hist.add((str(oid), str(s["player_id"])))

    rows = []
    for owner_id, pids in CANDS.items():
        mgr = config.manager_name(owner_id)
        for pid in pids:
            pm = H.player_meta(pid)
            if pm.position not in ("QB", "RB", "WR", "TE"):
                continue
            if _years_exp(pid) == 0:
                continue  # real NFL rookie -> Rookies tab
            rank = adp_rank_for(pm.name, pm.position)
            if not rank:
                continue
            prof = H.keeper_profile(owner_id, pid, SEASON)
            cost = engine.compute(prof, adp_rank=rank, is_rookie_keeper=False)
            from_rookie = (owner_id, str(pid)) in rookie_hist
            if from_rookie and hide_rookie_keepers:
                continue
            if from_rookie:
                # rookie keeper / rookie->regular conversion = a last-round pick
                cost_round, keep_yr = DRAFT_ROUNDS, 1
            else:
                if not cost.eligible:
                    continue  # already kept 3 years
                inherits = prof.get("acquired_via") in ("draft", "trade") and prof.get("original_round")
                if inherits:
                    # Must own a pick at the cost round or earlier (a higher pick);
                    # otherwise the team can't keep this player at all -> not a
                    # keeper option, so drop them from the value board.
                    cost_round = engine.adjust_to_owned(
                        cost.recommended_round, get_owned().get(owner_id), DRAFT_ROUNDS)
                else:
                    cost_round = DRAFT_ROUNDS
                keep_yr = cost.keep_year
            if not cost_round:
                continue  # ineligible (no high-enough pick) or no round resolved
            adp_round = engine.adp_rank_to_round(rank, NT)
            is_kept = str(pid) in kept_ids or normalize_name(pm.name) in kept_names
            rows.append(
                {
                    "_pid": str(pid),
                    "Player": pm.name, "Pos": pm.position, "Team": mgr,
                    "Kept": is_kept, "Rookie": from_rookie, "FA": False,
                    "Keep Yr": keep_yr, "Cost Rd": cost_round,
                    "ADP": int(rank), "ADP Rd": adp_round,
                    "Value": cost_round - adp_round,
                }
            )

    # Free agents: ADP-ranked skill players not on any 2026 roster. If kept they'd
    # cost a last-round pick (the undrafted rule), so value = last round - ADP round.
    rostered_pids = {str(p) for ps in CANDS.values() for p in ps}
    rostered_names = {normalize_name(H.player_meta(p).name) for ps in CANDS.values() for p in ps}
    name_idx = get_name_index()
    for _, ar in ADP_DF.iterrows():
        pos = ar.get("position")
        rank = ar.get("consensus_rank")
        if pos not in ("QB", "RB", "WR", "TE") or pd.isna(rank):
            continue
        nm = normalize_name(ar["name"])
        fa_pid = name_idx.get(nm, "")
        if not fa_pid or fa_pid in rostered_pids or nm in rostered_names:
            continue  # unresolved (likely incoming rookie) or already on a roster
        if _years_exp(fa_pid) == 0:
            continue  # real NFL rookie -> Rookies tab
        # Drafted-then-dropped players keep at their drafted round; only the truly
        # undrafted keep at a last-round pick.
        ps = H.player_seasons.get(str(fa_pid), {})
        fa_cost = ps[max(ps)]["round"] if ps else DRAFT_ROUNDS
        adp_round = engine.adp_rank_to_round(rank, NT)
        rows.append(
            {
                "_pid": fa_pid or "0",
                "Player": ar["name"], "Pos": pos, "Team": "Free Agent",
                "Kept": False, "Rookie": False, "FA": True,
                "Keep Yr": 1, "Cost Rd": fa_cost,
                "ADP": int(rank), "ADP Rd": adp_round,
                "Value": fa_cost - adp_round,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("Value", ascending=False).head(top_n).reset_index(drop=True)
    df.insert(0, "#", range(1, len(df) + 1))
    return df


@st.cache_data(ttl=300, show_spinner=False)
def build_trade_targets() -> pd.DataFrame:
    """Every rostered keeper's cost round — the round that carries over to a new
    team on a trade. Lets you scout, for a pick you own, which players you could
    trade for and keep at that round.
    """
    # Rookie keepers cost a last-round pick. (On a trade they convert to a regular
    # keeper — rookie status doesn't transfer — but still slot at a last round.)
    rookie_hist = set()
    for yr in range(SEASON - 1, SEASON - 7, -1):
        for oid, picks in storage.load(yr).items():
            for s in picks:
                if s.get("is_rookie_keeper") and s.get("player_id"):
                    rookie_hist.add((str(oid), str(s["player_id"])))

    rows = []
    for owner_id, pids in CANDS.items():
        mgr = config.manager_name(owner_id)
        for pid in pids:
            pm = H.player_meta(pid)
            if pm.position not in ("QB", "RB", "WR", "TE"):
                continue
            if _years_exp(pid) == 0:
                continue  # real NFL rookie -> Rookies tab
            rank = adp_rank_for(pm.name, pm.position)
            if not rank:
                continue
            from_rookie = (str(owner_id), str(pid)) in rookie_hist
            if from_rookie:
                cost_round, keep_yr = DRAFT_ROUNDS, "RK"
            else:
                prof = H.keeper_profile(owner_id, pid, SEASON)
                cost = engine.compute(prof, adp_rank=rank, is_rookie_keeper=False)
                if not cost.eligible:
                    continue  # already kept 3 years
                inherits = prof.get("acquired_via") in ("draft", "trade") and prof.get("original_round")
                # Natural round (carries on trade); undrafted/waiver = last-round pick.
                cost_round = cost.recommended_round if inherits else DRAFT_ROUNDS
                keep_yr = cost.keep_year if inherits else 1
            if not cost_round:
                continue
            adp_round = engine.adp_rank_to_round(rank, NT)
            rows.append({
                "_pid": str(pid), "Player": pm.name, "Pos": pm.position,
                "Owner": mgr, "Keep Yr": keep_yr, "Rookie": from_rookie,
                "Cost Rd": int(cost_round), "ADP": int(rank), "ADP Rd": adp_round,
                "Value": int(cost_round) - adp_round,
            })
    return pd.DataFrame(rows)


@st.cache_data(ttl=300, show_spinner=False)
@st.cache_data(ttl=86400, show_spinner=False)
def position_keeper_caps() -> dict:
    """Max keepers a team would realistically hold at a position, from the league's
    starting lineup (you don't keep two QBs/TEs when you only start one). Positions
    not listed are uncapped (RB/WR fill flex)."""
    from collections import Counter
    from kreeper import sleeper
    rp = sleeper.get_league(LEAGUE["sleeper_league_id"]).get("roster_positions", [])
    c = Counter(rp)
    return {"QB": c.get("QB", 0) + c.get("SUPER_FLEX", 0) or 1,
            "TE": c.get("TE", 0) or 1}


def _select_keepers(team_lb, cap, pos_cap, seed_positions=None):
    """Pick a team's realistic keeper set: top by value, but no more than the
    positional cap at QB/TE. Returns a list of leaderboard rows."""
    from collections import Counter
    pcount = Counter(seed_positions or [])
    chosen = []
    for _, r in team_lb.sort_values("Value", ascending=False).iterrows():
        if len(chosen) >= cap:
            break
        limit = pos_cap.get(r["Pos"])
        if limit is not None and pcount[r["Pos"]] >= limit:
            continue  # already keeping the max QBs/TEs
        chosen.append(r)
        pcount[r["Pos"]] += 1
    return chosen


def _projected_kept_ids() -> set:
    """player_ids likely off the draft board: everyone declared as a keeper, plus
    each team's most valuable eligible keepers (respecting roster + positional
    limits — no team keeps two QBs or two TEs)."""
    declared_pos = {}   # owner -> [positions already declared]
    kept = set()
    for oid, picks in current_keepers().items():
        for s in picks:
            if s.get("player_id"):
                kept.add(str(s["player_id"]))
                declared_pos.setdefault(str(oid), []).append(s.get("position"))
    lb = build_value_leaderboard(400)
    cap = MAX_REG + MAX_ROOKIE
    pos_cap = position_keeper_caps()
    for o in MANAGERS:
        seeded = declared_pos.get(str(o), [])
        team = lb[(lb["Team"] == config.manager_name(o)) & (~lb["_pid"].astype(str).isin(kept))]
        for r in _select_keepers(team, cap - len(seeded), pos_cap, seeded):
            kept.add(str(r["_pid"]))
    return kept


@st.cache_data(ttl=86400, show_spinner=False)
def starter_slots() -> list:
    """Ordered starting-lineup slots from the league settings (no bench/IR)."""
    from kreeper import sleeper
    rp = sleeper.get_league(LEAGUE["sleeper_league_id"]).get("roster_positions", [])
    starters = [p for p in rp if p not in ("BN", "IR", "TAXI")]
    return starters or ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "FLEX"]


def team_keeper_rows(owner_id) -> list:
    """The keeper set a team would likely carry (declared + best by value, with
    positional caps). Returns leaderboard rows."""
    lb = build_value_leaderboard(400)
    declared = [s for s in current_keepers().get(str(owner_id), []) if s.get("player_id")]
    seeded = [s.get("position") for s in declared]
    declared_ids = {str(s["player_id"]) for s in declared}
    team = lb[lb["Team"] == config.manager_name(owner_id)]
    out = list(team[team["_pid"].astype(str).isin(declared_ids)].to_dict("records"))
    cap = MAX_REG + MAX_ROOKIE
    rest = team[~team["_pid"].astype(str).isin(declared_ids)]
    out += [dict(r) for r in _select_keepers(rest, cap - len(declared), position_keeper_caps(), seeded)]
    return out


def build_mock_draft(rookie_factor: float | None = None) -> pd.DataFrame:
    """A full projected draft board: each team's likely KEEPERS occupy their pick
    slots, and every other pick is filled by the best available player (ADP with
    our league's rookie premium). Accounts for traded picks via the real board."""
    if rookie_factor is None:
        rookie_factor = config.mock_draft_rookie_factor()
    board = get_board()
    cells, rounds = board["cells"], board["rounds"]
    owner_to_roster = board["owner_to_roster"]

    # 1) Place each team's projected keepers onto a pick they OWN (their keeper
    #    cost round, or the nearest owned pick), marking those pick numbers.
    keeper_at = {}     # pick_no -> {player, pos, adp, owner}
    kept_ids, used = set(), set()
    for o in MANAGERS:
        rid = owner_to_roster.get(str(o))
        owned = {}     # round -> [(pick_no)]
        for (r, _slot), c in cells.items():
            if c["owner_roster"] == rid:
                owned.setdefault(r, []).append(c["pick_no"])
        for k in sorted(team_keeper_rows(o), key=lambda x: (x.get("Cost Rd") or 99)):
            kept_ids.add(str(k["_pid"]))
            rd = int(k.get("Cost Rd") or rounds)
            cand = [rd] + [rd - i for i in range(1, rd)] + [rd + i for i in range(1, rounds)]
            spot = next((pn for cr in cand for pn in owned.get(cr, []) if pn not in used), None)
            if spot is not None:
                used.add(spot)
                keeper_at[spot] = {"player": k["Player"], "pos": k["Pos"], "pid": str(k["_pid"]),
                                   "adp": k.get("ADP"), "owner": config.manager_name(o)}

    # 2) Available pool: ADP-ranked, keepers removed, league rookie premium applied.
    name_idx, pool, seen = get_name_index(), [], set()
    for _, ar in ADP_DF.iterrows():
        pos, rank = ar.get("position"), ar.get("consensus_rank")
        if pos not in ("QB", "RB", "WR", "TE") or pd.isna(rank):
            continue
        pid = name_idx.get(normalize_name(ar["name"]), "")
        if not pid or str(pid) in kept_ids or str(pid) in seen:
            continue
        seen.add(str(pid))
        rookie = _years_exp(pid) == 0
        pool.append((float(rank) * (rookie_factor if rookie else 1.0), str(pid),
                     ar["name"], pos, int(rank), rookie))
    pool.sort(key=lambda x: x[0])

    # 3) Walk the board in pick order; keeper cells = keepers, else next available.
    rows, pi = [], 0
    for (r, slot), c in sorted(cells.items(), key=lambda kv: kv[1]["pick_no"]):
        pn = c["pick_no"]
        base = {"Pick": pn, "Round": r, "Slot": slot, "Team": c["owner_name"]}
        if pn in keeper_at:
            k = keeper_at[pn]
            rows.append({**base, "_pid": k["pid"], "Player": k["player"], "Pos": k["pos"],
                         "ADP": k["adp"], "Rookie": False, "Keeper": True})
        elif pi < len(pool):
            _adj, pid, nm, pos, adp, rk = pool[pi]
            pi += 1
            rows.append({**base, "_pid": pid, "Player": nm, "Pos": pos,
                         "ADP": adp, "Rookie": rk, "Keeper": False})
    return pd.DataFrame(rows)


def build_rookies_table(top_n: int = 40) -> pd.DataFrame:
    """This year's NFL rookies (years_exp == 0) ranked by consensus ADP."""
    name_idx = get_name_index()
    rows = []
    for _, ar in ADP_DF.iterrows():
        pos, rank = ar.get("position"), ar.get("consensus_rank")
        if pos not in ("QB", "RB", "WR", "TE") or pd.isna(rank):
            continue
        pid = name_idx.get(normalize_name(ar["name"]), "")
        if not pid or _years_exp(pid) != 0:
            continue
        p = H.players.get(pid, {}) or {}
        cadp = ar.get("consensus_adp")
        rows.append(
            {
                "_pid": pid, "Player": ar["name"], "Pos": pos,
                "NFL": p.get("team") or "FA", "ADP": int(rank),
                "Consensus ADP": None if pd.isna(cadp) else round(float(cadp), 1),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("ADP").head(top_n).reset_index(drop=True)
    df.insert(0, "#", range(1, len(df) + 1))
    return df


# --------------------------------------------------------------------- pages
def _leaderboard_html(df) -> str:
    rows = []
    for _, r in df.iterrows():
        kept = bool(r["Kept"])
        is_fa = bool(r.get("FA"))
        cls = ' class="kept"' if kept else (' class="fa"' if is_fa else "")
        badge = '<span class="kept-badge">kept</span>' if kept else ""
        rk_badge = '<span class="rk-badge" title="rookie keeper">RK</span>' if r.get("Rookie") else ""
        v = int(r["Value"])
        vtxt = f"+{v}" if v >= 0 else str(v)
        team = '<span class="fa-tag">Free Agent</span>' if is_fa else r["Team"]
        rows.append(
            f'<tr{cls}><td class="rk">{r["#"]}</td>'
            f'<td class="pl">{theme.img_tag(r["_pid"])}{r["Player"]} {badge}{rk_badge}</td>'
            f'<td class="pos"><span class="posdot p-{r["Pos"]}"></span>{r["Pos"]}</td>'
            f'<td>{team}</td>'
            f'<td class="num">{r["Keep Yr"]}</td>'
            f'<td class="num">R{r["Cost Rd"]}</td>'
            f'<td class="num">{r["ADP"]}</td>'
            f'<td class="val">{vtxt}</td></tr>'
        )
    head = ('<tr><th>#</th><th>Player</th><th>Pos</th><th>Team</th>'
            '<th>Keep&nbsp;Yr</th><th>Cost</th><th>ADP</th><th>Value</th></tr>')
    return ('<div class="neonwrap" style="max-height:660px;overflow:auto;">'
            '<table class="lb lb-value"><thead>' + head + '</thead><tbody>'
            + "".join(rows) + '</tbody></table></div>')


def render_team_boxes() -> None:
    data = current_keepers()
    cards = []
    for oid, m in MANAGERS.items():
        picks = data.get(oid, [])
        if picks:
            # Order by keeper cost round (earliest pick first); rookies, kept at the
            # last rounds, naturally fall to the bottom.
            picks = sorted(picks, key=lambda x: (x.get("cost_round") or 99,
                                                 bool(x.get("is_rookie_keeper"))))
            inner = ""
            for s in picks:
                rk = '<span class="rk-tag">RK</span>' if s.get("is_rookie_keeper") else ""
                rd = f"R{s['cost_round']}" if s.get("cost_round") else "ADP"
                hs = theme.img_tag(s.get("player_id", ""), cls="")
                inner += (f'<div class="kp">{hs}<span>{s["player_name"]}{rk}</span>'
                          f'<span class="rd">{rd}</span></div>')
        else:
            inner = '<div class="empty">— no keepers yet —</div>'
        cards.append(f'<div class="kcard"><h4>{m["name"]}</h4>{inner}</div>')
    st.markdown('<div class="kcards">' + "".join(cards) + "</div>", unsafe_allow_html=True)


def render_home() -> None:
    render_countdown()
    st.markdown(f'<h2>{theme.crt("top")}Top 50 Keeper Values</h2>', unsafe_allow_html=True)
    st.caption("Best keeper bargains across every roster — draft value gained by keeping a "
               "player (cost round vs. consensus ADP round). Green = declared keeper · "
               "purple RK = rookie keeper · cyan = free agent. Real NFL rookies are on the Rookies tab.")
    fc1, fc2, fc3 = st.columns([1, 1, 1])
    with fc1:
        pos_f = st.selectbox("Position", ["All", "QB", "RB", "WR", "TE"], key="lb_pos")
    with fc2:
        team_f = st.selectbox("Team", ["All teams"] + [m["name"] for m in MANAGERS.values()] + ["Free Agent"], key="lb_team")
    with fc3:
        hide_rk = st.toggle("Hide rookie keepers", value=False,
                            help="Filter out players currently in rookie-keeper status.")
    lb = build_value_leaderboard(400, hide_rookie_keepers=hide_rk)
    if not lb.empty:
        if pos_f != "All":
            lb = lb[lb["Pos"] == pos_f]
        if team_f != "All teams":
            lb = lb[lb["Team"] == team_f]
        lb = lb.head(50).reset_index(drop=True)
        lb["#"] = range(1, len(lb) + 1)
    if lb.empty:
        st.info("No players match those filters (or no ADP data yet).")
    else:
        st.markdown(_leaderboard_html(lb), unsafe_allow_html=True)
    st.markdown(f'<h2>{theme.crt("board")}Submitted Keepers by Team</h2>', unsafe_allow_html=True)
    render_team_boxes()

    # Export — grab every submitted keeper to paste into the year-to-year sheet.
    data = current_keepers()
    if any(data.values()):
        export = []
        for oid, m in MANAGERS.items():
            for s in sorted(data.get(oid, []), key=lambda x: (x.get("cost_round") or 99)):
                export.append({
                    "Team": m["name"], "Player": s.get("player_name"), "Pos": s.get("position"),
                    "Type": "Rookie" if s.get("is_rookie_keeper") else "Regular",
                    "Keep Year": s.get("keep_year"), "Round": s.get("cost_round"),
                })
        st.download_button(
            "⬇ Download all keepers (CSV)",
            pd.DataFrame(export).to_csv(index=False),
            file_name=f"kreeper_keepers_{SEASON}.csv", mime="text/csv",
        )

    # Recent updates — who changed their keepers and when (shared-URL audit trail).
    st.markdown(f'<h3>{theme.crt("keepers")}Recent Updates</h3>', unsafe_allow_html=True)
    deadline, locked = keeper_lock()
    if deadline:
        st.caption((f"🔒 Submissions closed {deadline:%b %d, %Y · %-I:%M %p}."
                    if locked else
                    f"⏳ Submissions close {deadline:%b %d, %Y · %-I:%M %p}."))
    log = storage.load_log(SEASON)
    if not log:
        st.caption("No keeper updates yet.")
    else:
        lines = []
        for e in reversed(log[-12:]):
            n = int(e.get("count", 0) or 0)
            who = e.get("name") or config.manager_name(e.get("owner", ""))
            lines.append(f"- **{who}** → {n} keeper{'' if n == 1 else 's'} · {_fmt_ts(e.get('ts', ''))}")
        st.markdown("\n".join(lines))
    st.caption(f"💀 {ned()}")


@st.cache_data(ttl=3600, show_spinner="Opening the record book…")
def build_record_book():
    from kreeper import sleeper
    chain = sleeper.league_chain(LEAGUE["sleeper_league_id"])
    seasons = []  # newest first: {season, standings:[...], champ, runner}
    agg = {o: {"w": 0, "l": 0, "pf": 0.0, "titles": 0, "runner": 0, "seasons": 0, "best": ""}
           for o in MANAGERS}
    for c in chain:
        if c["season"] == SEASON:
            continue
        rosters = sleeper.get_rosters(c["league_id"])
        r2o = {int(r["roster_id"]): str(r.get("owner_id")) for r in rosters}
        champ = runner = None
        try:
            for m in sleeper.get_winners_bracket(c["league_id"]):
                if m.get("p") == 1:
                    champ, runner = r2o.get(m.get("w")), r2o.get(m.get("l"))
        except Exception:  # noqa: BLE001
            pass
        standings = []
        for r in rosters:
            o = str(r.get("owner_id"))
            s = r.get("settings", {}) or {}
            w, l = s.get("wins", 0) or 0, s.get("losses", 0) or 0
            pf = s.get("fpts", 0) + s.get("fpts_decimal", 0) / 100
            standings.append({"owner": o, "name": config.manager_name(o), "w": w, "l": l, "pf": round(pf, 1)})
            if o in agg:
                agg[o]["w"] += w; agg[o]["l"] += l; agg[o]["pf"] += pf; agg[o]["seasons"] += 1
                if o == champ:
                    agg[o]["titles"] += 1
                if o == runner:
                    agg[o]["runner"] += 1
        standings.sort(key=lambda x: (-x["w"], -x["pf"]))
        seasons.append({"season": c["season"], "standings": standings,
                        "champ": config.manager_name(champ) if champ else None,
                        "runner": config.manager_name(runner) if runner else None})
    return seasons, agg


def render_record_book() -> None:
    st.markdown(f'<h2>{theme.crt("top")}League Record Book</h2>', unsafe_allow_html=True)
    seasons, agg = build_record_book()
    if not seasons:
        st.info("No completed seasons on record yet.")
        return

    st.markdown("##### 🏆 Champions")
    champ_rows = "".join(
        f'<tr><td class="rk">{s["season"]}</td>'
        f'<td class="pl">🏆 {s["champ"] or "—"}</td>'
        f'<td>runner-up: {s["runner"] or "—"}</td></tr>'
        for s in seasons)
    st.markdown('<div class="neonwrap"><table class="lb"><thead>'
                '<tr><th>Season</th><th>Champion</th><th></th></tr></thead><tbody>'
                + champ_rows + '</tbody></table></div>', unsafe_allow_html=True)

    st.markdown("##### All-Time Standings")
    rows = []
    order = sorted(agg.items(),
                   key=lambda kv: (kv[1]["titles"], kv[1]["w"] / max(1, kv[1]["w"] + kv[1]["l"])),
                   reverse=True)
    for i, (o, a) in enumerate(order, 1):
        if a["seasons"] == 0:
            continue
        wp = a["w"] / max(1, a["w"] + a["l"])
        rings = "🏆" * a["titles"]
        rows.append(
            f'<tr><td class="rk">{i}</td>'
            f'<td class="pl">{config.manager_name(o)} {rings}</td>'
            f'<td class="num">{a["w"]}-{a["l"]}</td>'
            f'<td class="num">{wp:.3f}</td>'
            f'<td class="num">{int(a["pf"])}</td>'
            f'<td class="num">{a["titles"]}</td>'
            f'<td class="num">{a["runner"]}</td></tr>'
        )
    head = ('<tr><th>#</th><th>Manager</th><th>All-Time</th><th>Win%</th>'
            '<th>Points</th><th>Titles</th><th>Finals</th></tr>')
    st.markdown('<div class="neonwrap"><table class="lb lb-record"><thead>' + head
                + '</thead><tbody>' + "".join(rows) + '</tbody></table></div>',
                unsafe_allow_html=True)

    st.markdown("##### Season by Season")
    for s in seasons:
        title = f"{s['season']} — 🏆 {s['champ'] or '—'}"
        with st.expander(title):
            body = "".join(
                f'<tr><td class="rk">{i}</td><td class="pl">{r["name"]}</td>'
                f'<td class="num">{r["w"]}-{r["l"]}</td><td class="num">{r["pf"]}</td></tr>'
                for i, r in enumerate(s["standings"], 1))
            st.markdown('<table class="lb"><thead><tr><th>#</th><th>Team</th>'
                        '<th>Record</th><th>Points</th></tr></thead><tbody>'
                        + body + '</tbody></table>', unsafe_allow_html=True)


def _draft_value(pos: int) -> int:
    """Trade-value points for an asset at overall draft position `pos` (a standard
    decaying draft-value curve; pick #1 ≈ 100)."""
    return max(1, round(100 * (0.965 ** (max(1, pos) - 1))))


def _pick_value(rnd: int) -> int:
    """Points for a draft pick in a given round (valued at a mid-round slot)."""
    return _draft_value((rnd - 1) * NT + NT // 2)


def render_trade_analyzer() -> None:
    st.markdown(f'<h2>{theme.crt("draft")}Trade Analyzer</h2>', unsafe_allow_html=True)
    st.caption("Build a deal and grade it. Each player is valued by their talent "
               "(ADP draft position) plus any keeper bargain on top; picks by a "
               "draft-value curve. Higher total wins.")

    tt = build_trade_targets()
    kv = {str(r["_pid"]): int(r["Value"]) for _, r in tt.iterrows()}     # keeper bargain (rounds)
    adp = {str(r["_pid"]): int(r["ADP"]) for _, r in tt.iterrows()}      # ADP rank

    names = list(NAME_TO_ID.keys())
    c1, c2 = st.columns(2)
    with c1:
        a = st.selectbox("Team A", names, index=0, key="ta_a")
    with c2:
        b = st.selectbox("Team B", [n for n in names if n != a], index=0, key="ta_b")
    oa, ob = NAME_TO_ID[a], NAME_TO_ID[b]

    def roster_opts(oid):
        out = {}
        for pid in CANDS.get(oid, []):
            pm = H.player_meta(pid)
            if pm.position in ("QB", "RB", "WR", "TE"):
                out[f"{pm.name} ({pm.position})"] = str(pid)
        return out

    pick_seasons = [SEASON, SEASON + 1, SEASON + 2]

    def pick_opts(oid):
        opts = []
        for yr in pick_seasons:
            owned = get_owned_for(yr).get(oid) or {}
            for r in range(1, DRAFT_ROUNDS + 1):
                for i in range(owned.get(r, 0)):
                    opts.append(f"{yr} R{r}" + (f" (#{i+1})" if owned.get(r, 0) > 1 else ""))
        return opts

    ra, rb = roster_opts(oa), roster_opts(ob)
    with c1:
        a_pl = st.multiselect(f"{a} sends — players", list(ra.keys()), key="ta_apl")
        a_pk = st.multiselect(f"{a} sends — picks", pick_opts(oa), key="ta_apk")
    with c2:
        b_pl = st.multiselect(f"{b} sends — players", list(rb.keys()), key="ta_bpl")
        b_pk = st.multiselect(f"{b} sends — picks", pick_opts(ob), key="ta_bpk")

    def player_value(pid):
        """Talent (by ADP draft position) + a bonus for any keeper bargain."""
        pid = str(pid)
        a = adp.get(pid) or adp_rank_for(H.player_meta(pid).name, H.player_meta(pid).position)
        talent = _draft_value(int(a)) if a else 4
        bonus = max(0, kv.get(pid, 0)) * 6   # cheap-keeper edge, on top of talent
        return talent + bonus

    def pick_pts(label):
        # "2027 R1 (#2)" -> discounted value (future picks worth less, slot unknown)
        yr = int(label.split()[0])
        rnd = int(label.split()[1][1:])
        discount = 0.8 ** (yr - SEASON)
        return _pick_value(rnd) * discount

    def side_value(players, ropts, picks):
        pv = sum(player_value(ropts[p]) for p in players)
        pc = sum(pick_pts(p) for p in picks)
        return pv, pc

    # What each team RECEIVES (the other side's outgoing assets).
    a_pv, a_pc = side_value(b_pl, rb, b_pk)   # A receives B's stuff
    b_pv, b_pc = side_value(a_pl, ra, a_pk)   # B receives A's stuff

    if not (a_pl or a_pk or b_pl or b_pk):
        st.info("Pick players and/or picks for each side to grade the deal.")
        return

    a_score, b_score = a_pv + a_pc, b_pv + b_pc
    col1, col2 = st.columns(2)
    for col, who, pv, pc, score in ((col1, a, a_pv, a_pc, a_score), (col2, b, b_pv, b_pc, b_score)):
        col.markdown(f"#### {who} receives")
        col.metric("Players", f"{round(pv)} pts", help="Talent (ADP position) + keeper bargain")
        col.metric("Picks", f"{round(pc)} pts")
        col.caption(f"Total value: **{round(score)}**")

    diff = a_score - b_score
    if abs(diff) <= max(10, 0.08 * max(a_score, b_score, 1)):
        st.success("⚖️ Even deal — both sides come out roughly equal.")
    else:
        winner = a if diff > 0 else b
        st.success(f"📈 Edge to **{winner}** by ~{abs(round(diff))} pts.")
    st.caption("Heuristic only — player value = a draft-value curve at their ADP "
               "plus a bonus for any keeper discount; picks use the same curve at a "
               "mid-round slot. Future picks (next two years) are discounted ~20% "
               "per year out. Doesn't model roster need or positional scarcity.")


def render_keeper_landscape() -> None:
    st.markdown(f'<h2>{theme.crt("board")}Keeper Landscape</h2>', unsafe_allow_html=True)
    st.caption("Positional scarcity: of the top players at each position, who's "
               "likely kept (and by whom) vs. left in the draft pool. Thin pools "
               "= positions to target early; deep pools = wait.")
    kept = _projected_kept_ids()
    pid_owner = {}
    for o, pids in CANDS.items():
        for pid in pids:
            pid_owner[str(pid)] = config.manager_name(o)
    name_idx = get_name_index()
    by_pos = {p: [] for p in ("RB", "WR", "QB", "TE")}
    seen = set()
    for _, ar in ADP_DF.iterrows():
        pos, rank = ar.get("position"), ar.get("consensus_rank")
        if pos not in by_pos or pd.isna(rank):
            continue
        pid = name_idx.get(normalize_name(ar["name"]), "")
        if not pid or str(pid) in seen:
            continue
        seen.add(str(pid))
        owner = pid_owner.get(str(pid)) if str(pid) in kept else None
        by_pos[pos].append((int(rank), ar["name"], str(pid), owner))

    tabs = st.tabs(["RB", "WR", "QB", "TE"])
    for tab, pos in zip(tabs, ["RB", "WR", "QB", "TE"]):
        with tab:
            players = sorted(by_pos[pos], key=lambda x: x[0])[:18]
            kept_n = sum(1 for *_, o in players if o)
            avail_n = len(players) - kept_n
            tone = "🔴 thin" if avail_n <= len(players) * 0.35 else ("🟡 moderate" if avail_n <= len(players) * 0.6 else "🟢 deep")
            st.caption(f"Top {len(players)} {pos}s — **{kept_n} likely kept**, "
                       f"**{avail_n} available**. Draft pool: {tone}.")
            rows = []
            for rank, nm, pid, owner in players:
                if owner:
                    status = f'<span style="color:#b3232a;">kept · {owner}</span>'
                else:
                    status = '<span class="kept-badge">AVAILABLE</span>'
                rows.append(
                    f'<tr><td class="rk">{rank}</td>'
                    f'<td class="pl">{theme.img_tag(pid)}{nm}</td>'
                    f'<td>{status}</td></tr>'
                )
            head = '<tr><th>ADP</th><th>Player</th><th>Status</th></tr>'
            st.markdown('<div class="neonwrap"><table class="lb"><thead>' + head
                        + '</thead><tbody>' + "".join(rows) + '</tbody></table></div>',
                        unsafe_allow_html=True)


def render_mock_draft() -> None:
    st.markdown(f'<h2>{theme.crt("draft")}Projected Draft</h2>', unsafe_allow_html=True)
    st.caption("A full projected board: each team's likely keepers (🔒, declared + "
               "best by value) sit in their pick slots, and every other pick is the "
               "best available by consensus ADP with our league's rookie premium.")
    rf = config.mock_draft_rookie_factor()
    c1, c2 = st.columns([2, 1])
    with c1:
        rf = st.slider("Rookie premium (lower = rookies go higher)", 0.15, 1.0,
                       value=float(rf), step=0.05,
                       help="A rookie's draft rank = ADP rank × this. 1.0 = no premium.")
    df = build_mock_draft(rf)
    if df.empty:
        st.info("No ADP data yet — run `python scripts/refresh_adp.py`.")
        return
    only_rd = c2.selectbox("Show round", ["First 3 rounds"] + [f"Round {r}" for r in range(1, DRAFT_ROUNDS + 1)])
    if only_rd == "First 3 rounds":
        view = df[df["Round"] <= 3]
    else:
        view = df[df["Round"] == int(only_rd.split()[1])]
    rows = []
    for _, r in view.iterrows():
        keep = bool(r.get("Keeper"))
        tag = (' <span class="kept-badge">🔒 KEEP</span>' if keep
               else (' <span class="rk-badge">RK</span>' if r["Rookie"] else ""))
        adp = "" if (keep or not r["ADP"]) else r["ADP"]
        tr = ' style="background:rgba(22,184,166,.10);"' if keep else ""
        rows.append(
            f'<tr{tr}><td class="rk">{int(r["Round"])}.{int(r["Slot"]):02d}</td>'
            f'<td class="pl">{theme.img_tag(r["_pid"])}{r["Player"]}{tag}</td>'
            f'<td class="pos"><span class="posdot p-{r["Pos"]}"></span>{r["Pos"]}</td>'
            f'<td>{r["Team"]}</td>'
            f'<td class="num">{adp}</td></tr>'
        )
    head = '<tr><th>Pick</th><th>Player</th><th>Pos</th><th>On the clock</th><th>ADP</th></tr>'
    st.markdown('<div class="neonwrap"><table class="lb lb-mock"><thead>' + head
                + '</thead><tbody>' + "".join(rows) + '</tbody></table></div>',
                unsafe_allow_html=True)
    st.caption("🔒 = a kept player (occupies that pick) · everyone else = projected "
               "pick by ADP. **RK** = rookie. Tune the rookie premium above to match "
               "how your league really values rookies.")


def render_trade_targets() -> None:
    st.markdown(f'<h2>{theme.crt("draft")}Keeper Trade Market</h2>', unsafe_allow_html=True)
    st.caption("Pick the round you want to keep someone at — these are the players "
               "across the league whose keeper cost is that round. The keeper round "
               "carries over on a trade, so you could deal for one and keep them "
               "there. Best value (cheapest relative to ADP) up top.")
    df = build_trade_targets()
    if df.empty:
        st.info("No keeper data yet — run `python scripts/refresh_adp.py` to populate ADP.")
        return

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        rnd = st.selectbox("Keeper cost round", list(range(1, DRAFT_ROUNDS + 1)),
                           index=1, help="The round a keeper would cost on your roster.")
    with c2:
        pos_f = st.selectbox("Position", ["All", "QB", "RB", "WR", "TE"], key="tm_pos")
    with c3:
        me = st.selectbox("Hide my own players (optional)",
                          ["— show everyone —"] + list(NAME_TO_ID.keys()), index=0)

    view = df[df["Cost Rd"] == rnd].copy()
    if pos_f != "All":
        view = view[view["Pos"] == pos_f]
    owned_note = ""
    if me in NAME_TO_ID:
        view = view[view["Owner"] != me]
        owned = get_owned().get(NAME_TO_ID[me]) or {}
        can = any(owned.get(r, 0) > 0 for r in range(1, rnd + 1))
        owned_note = (f" You own a Round&nbsp;{rnd}-or-earlier pick, so you could keep one. "
                      if can else
                      f" ⚠️ You don't own a Round&nbsp;{rnd}-or-earlier pick — you couldn't keep "
                      "a player at this round without acquiring one first. ")

    view = view.sort_values(["Value", "ADP"], ascending=[False, True])
    if view.empty:
        st.info(f"No keeper-eligible players cost Round {rnd} right now.")
        return

    rows = []
    for i, (_, r) in enumerate(view.iterrows(), 1):
        val = int(r["Value"])
        color = "#0c7a6e" if val > 0 else ("#b3232a" if val < 0 else "#8b86a0")
        rk = ' <span class="rk-badge">RK</span>' if r.get("Rookie") else ""
        rows.append(
            f'<tr><td class="rk">{i}</td>'
            f'<td class="pl">{theme.img_tag(r["_pid"])}{r["Player"]}{rk}</td>'
            f'<td class="pos"><span class="posdot p-{r["Pos"]}"></span>{r["Pos"]}</td>'
            f'<td>{r["Owner"]}</td>'
            f'<td class="num">{r["Keep Yr"]}</td>'
            f'<td class="num">{r["ADP"]}</td>'
            f'<td class="num" style="color:{color};font-weight:600;">{val:+d}</td></tr>'
        )
    head = (f'<tr><th>#</th><th>Player</th><th>Pos</th><th>Owner</th>'
            f'<th>Keep&nbsp;Yr</th><th>ADP</th><th>Value</th></tr>')
    st.markdown(f'<p style="margin:.2rem 0 .6rem;">Keepable at <b>Round {rnd}</b>:{owned_note}</p>',
                unsafe_allow_html=True)
    st.markdown('<div class="neonwrap"><table class="lb lb-trade"><thead>' + head
                + '</thead><tbody>' + "".join(rows) + '</tbody></table></div>',
                unsafe_allow_html=True)
    st.caption(f"Value = Round {rnd} − the player's ADP round (draft capital you'd "
               "gain by keeping them there). Remember: to keep a player you must own "
               "a pick at their cost round or earlier. **RK** = rookie keeper — kept "
               "at a last round, and on a trade they convert to a regular keeper "
               "(rookie status doesn't transfer, and the 3-year clock starts).")
    if me in NAME_TO_ID and "Ned" in me:
        st.caption("💀 You're Ned. The whole league is your trade partner.")


def render_rookies() -> None:
    st.markdown(f'<h3>{theme.crt("rookies")}{SEASON} Top Rookies</h3>', unsafe_allow_html=True)
    st.caption("This year's NFL rookie class ranked by our consensus ADP — your rookie-keeper targets.")
    df = build_rookies_table(40)
    if df.empty:
        st.info("No rookies found in the current ADP data yet — run `python scripts/refresh_adp.py`.")
        return
    rows = []
    for _, r in df.iterrows():
        cadp = "" if r["Consensus ADP"] is None else f'{r["Consensus ADP"]:.1f}'
        rows.append(
            f'<tr><td class="rk">{r["#"]}</td>'
            f'<td class="pl">{theme.img_tag(r["_pid"])}{r["Player"]}</td>'
            f'<td class="pos"><span class="posdot p-{r["Pos"]}"></span>{r["Pos"]}</td>'
            f'<td>{r["NFL"]}</td>'
            f'<td class="num">{r["ADP"]}</td>'
            f'<td class="num">{cadp}</td></tr>'
        )
    head = ('<tr><th>#</th><th>Player</th><th>Pos</th><th>NFL</th>'
            '<th>ADP&nbsp;Rank</th><th>Consensus&nbsp;ADP</th></tr>')
    st.markdown('<div class="neonwrap" style="max-height:660px;overflow:auto;">'
                '<table class="lb lb-rook"><thead>' + head + '</thead><tbody>'
                + "".join(rows) + '</tbody></table></div>', unsafe_allow_html=True)


def _saved_slip(owner_id: str):
    """Read-only table of a manager's already-submitted keepers (or None)."""
    saved = storage.get_manager_selections(owner_id, SEASON)
    if not saved:
        return None
    rows = [{
        "Player": s.get("player_name"), "Pos": s.get("position"),
        "Type": "Rookie" if s.get("is_rookie_keeper") else "Regular",
        "Keep Year": s.get("keep_year"),
        "Cost": f"Round {s['cost_round']}" if s.get("cost_round") else "—",
    } for s in sorted(saved, key=lambda x: (x.get("cost_round") or 99))]
    return pd.DataFrame(rows)


def render_my_keepers() -> None:
    st.markdown(f'<h3>{theme.crt("keepers")}Set Your Keepers</h3>', unsafe_allow_html=True)
    deadline, locked = keeper_lock()
    if locked:
        st.warning(f"🔒 Keeper submissions closed on **{deadline:%b %d, %Y · %-I:%M %p}**. "
                   "The board is final — selections are read-only.")
    elif deadline:
        st.caption(f"⏳ Submissions close **{deadline:%b %d, %Y · %-I:%M %p}**.")

    name = st.selectbox("Who are you?", list(NAME_TO_ID.keys()), index=None,
                        placeholder="Pick your name…")
    if not name:
        st.info("Select your name to load your roster.")
        return

    owner_id = NAME_TO_ID[name]

    if locked:
        slip = _saved_slip(owner_id)
        if slip is None:
            st.info(f"{name} didn't submit any keepers before the deadline.")
        else:
            st.markdown("##### Your final keepers")
            st.dataframe(slip, hide_index=True, use_container_width=True)
        return

    df = build_candidate_rows(owner_id)
    if df.empty:
        st.warning("No skill-position players found on your roster.")
        return

    saved = {s["player_id"]: s for s in storage.get_manager_selections(owner_id, SEASON)}
    df["Keep"] = df["player_id"].map(lambda p: p in saved)
    df["Rookie Keeper"] = df["player_id"].map(
        lambda p: bool(saved.get(p, {}).get("is_rookie_keeper", False)))

    st.caption("Tick **Keep** for players you want to keep. Tick **Rookie Keeper** "
               "for career-long rookie keepers (kept at your last rounds, exempt from the 3-year clock).")
    edited = st.data_editor(
        df,
        key=f"editor_{owner_id}",
        hide_index=True,
        use_container_width=True,
        column_order=["Keep", "Rookie Keeper", "Photo", "Player", "Pos", "NFL",
                      "Keep Year", "Reg. Cost", "ADP Rank", "Orig. Rd", "Acq."],
        column_config={
            "player_id": None,
            "Eligible": None,
            "Photo": st.column_config.ImageColumn("", width="small"),
            "Keep": st.column_config.CheckboxColumn("Keep", width="small"),
            "Rookie Keeper": st.column_config.CheckboxColumn("Rookie Keeper", width="small"),
            "ADP Rank": st.column_config.NumberColumn("ADP Rank", help="Consensus overall ADP rank"),
            "Orig. Rd": st.column_config.NumberColumn("Orig. Rd", help="Round originally drafted"),
        },
        disabled=["Photo", "Player", "Pos", "NFL", "Keep Year", "Reg. Cost", "ADP Rank", "Orig. Rd", "Acq."],
    )

    # Ticking Rookie Keeper auto-keeps the player — no need to tick both.
    picked = edited[edited["Keep"] | edited["Rookie Keeper"]]

    st.markdown("##### Your keeper slip")
    st.caption("Tip: ticking **Rookie Keeper** keeps the player automatically — "
               "you don't need to also tick Keep.")

    items = []
    ineligible = []
    year2_choices = {}
    for _, r in picked.iterrows():
        pid = r["player_id"]
        is_rookie = bool(r["Rookie Keeper"])
        # A rookie keeper must have been drafted by THIS team in the player's
        # rookie season; a trade-acquired player can't be a rookie keeper.
        if is_rookie and not rookie_keeper_eligible(owner_id, pid):
            ineligible.append(
                f"**{r['Player']}** can't be a *rookie keeper* — you must have drafted "
                "them in their rookie season and held them since (this player was "
                "acquired by trade or not drafted by you as a rookie). Untick Rookie "
                "Keeper; keep them as a regular keeper if eligible."
            )
            continue
        prof = H.keeper_profile(owner_id, pid, SEASON)
        rank = adp_rank_for(r["Player"], r["Pos"])
        # Was a rookie keeper, now kept as a regular keeper -> last-round pick, clock resets.
        from_rookie = (not is_rookie) and bool(storage.prior_rookie_seasons(owner_id, pid, SEASON))
        if not is_rookie and not from_rookie:
            base = engine.compute(prof, adp_rank=rank, is_rookie_keeper=False)
            if not base.eligible:
                ineligible.append(f"**{r['Player']}** — {base.reason}")
                continue
            opt_rounds = [o.round for o in base.options]
            if base.keep_year == 2 and len([x for x in opt_rounds if x is not None]) > 1:
                labels = [o.label for o in base.options]
                ridx = opt_rounds.index(base.recommended_round) if base.recommended_round in opt_rounds else 0
                choice = st.radio(f"{r['Player']} — Year 2 cost", labels, horizontal=True,
                                  index=ridx, key=f"y2_{owner_id}_{pid}")
                year2_choices[pid] = choice.split(" (")[0]
        items.append({
            "player_id": pid, "name": r["Player"], "position": r["Pos"],
            "is_rookie": is_rookie, "from_rookie": from_rookie, "profile": prof, "adp_rank": rank,
            "year2_choice": year2_choices.get(pid),
        })

    costs = engine.allocate_keeper_costs(items, draft_rounds=DRAFT_ROUNDS,
                                         owned=get_owned().get(owner_id))
    reg_items = [i for i in items if not i["is_rookie"]]
    rook_items = [i for i in items if i["is_rookie"]]

    summary = []
    for it in items:
        c = costs[it["player_id"]]
        summary.append({
            "Player": it["name"], "Pos": it["position"],
            "Type": "Rookie" if it["is_rookie"] else "Regular",
            "Keep Year": c.keep_year,
            "Cost": f"Round {c.recommended_round}" if c.recommended_round else c.recommended_label,
        })

    # Ownership eligibility: a keeper must cost a pick at its round or earlier (a
    # higher pick). allocate_keeper_costs flags anyone you can't actually keep.
    for it in items:
        c = costs[it["player_id"]]
        if not c.eligible or c.recommended_round is None:
            reason = c.reason or "no pick available to keep this player."
            ineligible.append(f"**{it['name']}** — {reason}")

    for msg in ineligible:
        st.error("Can't keep: " + msg)
    problems = []
    if len(reg_items) > MAX_REG:
        problems.append(f"Too many **regular** keepers: {len(reg_items)} (max {MAX_REG}).")
    if len(rook_items) > MAX_ROOKIE:
        problems.append(f"Too many **rookie** keepers: {len(rook_items)} (max {MAX_ROOKIE}).")

    if summary:
        st.dataframe(pd.DataFrame(summary), hide_index=True, use_container_width=True)
    st.caption(f"Regular: {len(reg_items)}/{MAX_REG} · Rookie: {len(rook_items)}/{MAX_ROOKIE}")
    for p in problems:
        st.warning(p)

    disabled = bool(problems or ineligible)
    if st.button("💾 Save my keepers", type="primary", disabled=disabled):
        # Re-check server-side: the set must still be valid and the deadline open
        # (it could have passed, or another tab changed things, since page load).
        _, locked_now = keeper_lock()
        if locked_now:
            st.error("Submissions just closed — your changes weren't saved.")
        elif problems or ineligible:
            st.error("Fix the issues above before saving.")
        else:
            payload = []
            for it in items:
                c = costs[it["player_id"]]
                payload.append({
                    "player_id": it["player_id"], "player_name": it["name"], "position": it["position"],
                    "is_rookie_keeper": it["is_rookie"], "keep_year": c.keep_year,
                    "cost_choice": it.get("year2_choice"), "cost_round": c.recommended_round,
                })
            try:
                storage.save_manager_selections(owner_id, payload, SEASON)
                storage.append_log(owner_id, name, len(payload),
                                   dt.datetime.now().isoformat(timespec="seconds"), SEASON)
                st.success(f"Saved {len(payload)} keepers for {name}.")
            except Exception as e:  # noqa: BLE001
                st.error(f"Couldn't save — try again in a moment. ({type(e).__name__})")


def _board_cell_html(c: dict, keepers: list) -> str:
    pick = f'<span class="dbpick">#{c["pick_no"]}</span>'
    if keepers:
        conflict = False
        parts = []
        for k in keepers:
            rk = " 🆕" if k.get("is_rookie_keeper") else ""
            # Keeper on an acquired pick (not their own column) -> tag the owner.
            tag = "" if k.get("_home") else f' <span style="font-size:9px;">({k.get("_owner_short","")})</span>'
            parts.append(f'<b>{k["player_name"]}</b> '
                         f'<span style="font-size:9px;opacity:.8;">{k.get("position","")}{rk}</span>{tag}')
            conflict = conflict or k.get("_conflict")
        names = "<br>".join(parts)
        if conflict:
            return (f'<td class="dbcell db-conflict">{pick}<br>{names}'
                    f'<br><span style="font-size:9px;">⚠️ no pick this round</span></td>')
        return f'<td class="dbcell db-keep">{pick}<br>{names}</td>'
    if c["traded"]:
        return (f'<td class="dbcell db-traded">{pick}<br><b>{c["owner_short"]}</b><br>'
                f'<span style="font-size:9px;">◄ {c["base_short"]}</span></td>')
    return f'<td class="dbcell db-base">{pick}<br>{c["owner_short"]}</td>'


@st.cache_data(ttl=1800, show_spinner="Setting the line…")
def build_championship_odds():
    """A for-fun Vegas-style title line. Rosters reset at the draft, so the only
    thing that carries over is each team's KEEPERS — the model blends three
    seasons of results with keeper strength (talent retained) and keeper value
    (draft capital saved), then converts to win probabilities and American odds
    with a bookmaker's vig."""
    from kreeper import sleeper

    chain = sleeper.league_chain(LEAGUE["sleeper_league_id"])
    completed = [c["season"] for c in chain if c["season"] != SEASON]
    recency = dict(zip(sorted(completed, reverse=True), [0.5, 0.3, 0.2, 0.1, 0.05]))

    hist = {o: 0.0 for o in MANAGERS}       # recency-weighted win %
    record = {o: [0, 0] for o in MANAGERS}  # aggregate W, L over completed seasons
    for c in chain:
        if c["season"] not in recency:
            continue
        wt = recency[c["season"]]
        for r in sleeper.get_rosters(c["league_id"]):
            o = str(r.get("owner_id"))
            if o not in hist:
                continue
            stt = r.get("settings", {}) or {}
            w, l = stt.get("wins", 0) or 0, stt.get("losses", 0) or 0
            hist[o] += wt * (w / max(1, w + l))
            record[o][0] += w
            record[o][1] += l

    # Keeper-based strength: only the players a team can carry over matter. Take
    # each team's most valuable eligible keepers (their likely keep set) and
    # measure the talent retained (ADP) and the draft capital saved (value).
    lb = build_value_leaderboard(400)
    keep_n = MAX_REG + MAX_ROOKIE
    pos_cap = position_keeper_caps()
    talent, kcap, best = {}, {}, {}
    for o in MANAGERS:
        team = lb[lb["Team"] == config.manager_name(o)]
        sel = _select_keepers(team, keep_n, pos_cap)  # realistic keep set (no 2 QB/TE)
        talent[o] = float(sum(max(0, 260 - int(r["ADP"])) for r in sel))
        kcap[o] = float(sum(r["Value"] for r in sel))
        best[o] = [r["Player"] for r in sel[:3]]

    def _z(d):
        v = list(d.values())
        m = sum(v) / len(v)
        sd = (sum((x - m) ** 2 for x in v) / len(v)) ** 0.5 or 1.0
        return {k: (x - m) / sd for k, x in d.items()}

    hz, tz, vz = _z(hist), _z(talent), _z(kcap)
    power = {o: 0.35 * hz[o] + 0.40 * tz[o] + 0.25 * vz[o] for o in MANAGERS}

    T = 1.05  # temperature: lower = bigger favorites, higher = more parity
    exps = {o: math.exp(power[o] / T) for o in power}
    tot = sum(exps.values())
    fair = {o: exps[o] / tot for o in power}
    keeprank = {o: i + 1 for i, o in enumerate(sorted(talent, key=talent.get, reverse=True))}

    def american(p):
        p = min(0.95, max(0.01, p * 1.16))  # ~16% overround (the house edge)
        return f"-{round(p / (1 - p) * 100)}" if p >= 0.5 else f"+{round((1 - p) / p * 100)}"

    rows = []
    for o in sorted(fair, key=fair.get, reverse=True):
        rows.append({
            "Team": config.manager_name(o),
            "Odds": american(fair[o]),
            "Win %": round(fair[o] * 100, 1),
            "Record": f"{record[o][0]}-{record[o][1]}",
            "KeeperRk": keeprank[o],
            "KeepVal": round(kcap[o]),
            "Best": best[o],
        })
    return rows


def render_odds() -> None:
    st.markdown(f'<h2>{theme.crt("top")}{SEASON} Title Odds</h2>', unsafe_allow_html=True)
    st.caption("For fun — rosters reset at the draft, so this prices each team on "
               "what carries over: three seasons of results plus keeper strength "
               "and value. A Vegas-style line, juice included. Not a real "
               "sportsbook; no Ned were harmed.")
    rows = build_championship_odds()
    body = []
    n = len(rows)
    for i, r in enumerate(rows):
        tag = ('<span class="kept-badge">FAVORITE</span>' if i == 0 else
               ('<span class="rk-badge">LONGSHOT</span>' if i >= n - 2 else ""))
        keepers = ", ".join(r["Best"][:3]) or "—"
        body.append(
            f'<tr><td class="rk">{i+1}</td>'
            f'<td class="pl">{r["Team"]} {tag}</td>'
            f'<td class="num" style="font-family:\'Anton\';font-size:17px;color:var(--pink);">{r["Odds"]}</td>'
            f'<td class="num">{r["Win %"]}%</td>'
            f'<td class="num">{r["Record"]}</td>'
            f'<td class="num">{r["KeeperRk"]}/{n}</td>'
            f'<td class="num">{r["KeepVal"]:+d}</td>'
            f'<td style="font-size:12px;opacity:.85;">{keepers}</td></tr>'
        )
    head = ('<tr><th>#</th><th>Team</th><th>Odds</th><th>Win&nbsp;%</th>'
            '<th>3-Yr&nbsp;W-L</th><th>Keeper&nbsp;Rk</th><th>Keeper&nbsp;Value</th>'
            '<th>Top Keepers</th></tr>')
    st.markdown('<div class="neonwrap"><table class="lb lb-odds"><thead>' + head
                + '</thead><tbody>' + "".join(body) + '</tbody></table></div>',
                unsafe_allow_html=True)
    st.caption("Odds = how the model prices each team to win it all (American "
               "format: −150 = favorite, +600 = longshot). Keeper Rk = strength of "
               "your kept players by ADP (1 = best core) · Keeper Value = draft "
               "rounds gained by your best keepers.")


def render_draft_board() -> None:
    st.markdown(f'<h3>{theme.crt("draft")}{SEASON} Draft Board</h3>', unsafe_allow_html=True)
    try:
        board = get_board()
    except Exception as e:  # noqa: BLE001
        st.error(f"Couldn't load the draft board from Sleeper: {e}")
        return

    if not board["order_set"]:
        st.caption("⚠️ Draft order isn't set in Sleeper yet — slots show in default roster "
                   "order and will update automatically once the commissioner sets it. "
                   "Traded picks are already reflected.")

    teams, rounds, cells = board["teams"], board["rounds"], board["cells"]

    # Overlay submitted keepers onto a pick the team OWNS that round — preferring
    # their own column, then an acquired pick's slot. So two keepers at the same
    # round (when the team owns two of that pick) split across both cells instead
    # of stacking. Each cell is used at most once.
    from collections import defaultdict
    data = current_keepers()
    owner_to_slot = board["owner_to_slot"]
    owner_to_roster = board["owner_to_roster"]
    owned_slots = defaultdict(list)  # (round, roster_id) -> [slots that roster owns]
    for (r, slot), c in cells.items():
        owned_slots[(r, c["owner_roster"])].append(slot)

    keeper_cell: dict = {}
    used_cells: set = set()
    for owner_id, picks in data.items():
        roster = owner_to_roster.get(str(owner_id))
        own_slot = owner_to_slot.get(str(owner_id))
        if roster is None:
            continue
        short = config.manager_name(owner_id).split()[0]
        for s in sorted(picks, key=lambda x: (x.get("cost_round") or 99)):
            rd = s.get("cost_round")
            if not rd:
                continue
            rd = int(rd)
            cands = sorted(owned_slots.get((rd, roster), []),
                           key=lambda sl: (sl != own_slot, sl))
            placed = next((sl for sl in cands if (rd, sl) not in used_cells), None)
            conflict = placed is None
            if placed is None:
                placed = own_slot  # team owns no pick this round — flag it
            used_cells.add((rd, placed))
            entry = dict(s)
            entry["_owner_short"] = short
            entry["_home"] = placed == own_slot
            entry["_conflict"] = conflict
            keeper_cell.setdefault((rd, placed), []).append(entry)
    html = ['<div class="neonwrap"><table class="dboard">']
    html.append('<tr><th style="width:32px;">Rd</th>')
    for slot in range(1, teams + 1):
        html.append(f'<th>{slot}. {board["slot_team"][slot].split()[0]}</th>')
    html.append("</tr>")
    for r in range(1, rounds + 1):
        html.append("<tr>")
        html.append(f'<td class="dbcell db-rd">{r}</td>')
        for slot in range(1, teams + 1):
            html.append(_board_cell_html(cells[(r, slot)], keeper_cell.get((r, slot))))
        html.append("</tr>")
    html.append("</table></div>")
    st.markdown("".join(html), unsafe_allow_html=True)
    st.caption("🟩 keeper locked in (a name in parentheses = kept on a pick acquired via trade) · "
               "🟧 traded pick (new owner, ◄ original owner) · plain cell = pick owner. "
               "Keepers appear here for everyone as soon as they're saved.")


def render_adp() -> None:
    st.markdown(f'<h3>{theme.crt("adp")}{SEASON} Consensus ADP</h3>', unsafe_allow_html=True)
    st.caption("One consensus number per player, averaged across all sources: "
               + ", ".join(ADP_META.get("sources", [])) + ". The **Move** column shows each "
               "player's consensus-rank change over the selected window (▲ = drafted earlier).")
    if ADP_DF.empty:
        st.info("No ADP data yet. Run `python scripts/refresh_adp.py`.")
        return
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        q = st.text_input("Search player", "")
    with c2:
        pos = st.multiselect("Position", ["QB", "RB", "WR", "TE"], default=[])
    with c3:
        win = st.selectbox("Move window", [7, 14, 30], index=2,
                           format_func=lambda d: f"Last {d} days", key="cadp_win")

    mv = adp_consensus.adp_movement(SEASON, window_days=win)
    move_map = {normalize_name(m["name"]): m["delta"] for m in mv.get("moves", [])}

    def _fmt_move(d):
        if d is None or (isinstance(d, float) and pd.isna(d)):
            return ""
        d = int(d)
        return f"▲ {d}" if d > 0 else (f"▼ {abs(d)}" if d < 0 else "—")

    view = ADP_DF.copy()
    if q:
        view = view[view["name"].str.contains(q, case=False, na=False)]
    if pos:
        view = view[view["position"].isin(pos)]
    movecol = f"Move ({win}d)"
    view[movecol] = view["name_key"].map(move_map).map(_fmt_move)
    view = view[["consensus_rank", "name", "position", "consensus_adp", movecol]].rename(
        columns={"consensus_rank": "Rank", "name": "Player",
                 "position": "Pos", "consensus_adp": "Consensus ADP"})
    st.dataframe(view, hide_index=True, use_container_width=True, height=600)
    if not mv.get("moves"):
        st.caption("📈 ADP movement appears once two daily snapshots exist — check back after "
                   "the next daily refresh.")


def render_adp_trends() -> None:
    st.markdown(f'<h2>{theme.crt("adp")}ADP Risers & Fallers</h2>', unsafe_allow_html=True)
    win = st.selectbox("Window", [7, 14, 30], format_func=lambda d: f"Last {d} days", key="adp_win")
    mv = adp_consensus.adp_movement(SEASON, window_days=win)
    if not mv.get("moves"):
        st.info("📈 Collecting ADP history — risers & fallers show up once there are "
                "two daily snapshots. A snapshot is saved with each daily ADP refresh, "
                "so check back tomorrow.")
        return
    st.caption(f"Consensus-ADP movement **{mv['prior']} → {mv['latest']}**, limited to the "
               f"top {DRAFT_SCOPE_RANK} by current consensus ADP (the realistic draft pool). "
               "▲ = climbing draft boards (being drafted earlier).")
    # Only players currently inside the draft pool — deep-waiver churn isn't useful.
    moves = [m for m in mv["moves"] if abs(m["delta"]) >= 1 and m["now"] <= DRAFT_SCOPE_RANK]
    risers = sorted(moves, key=lambda x: -x["delta"])[:15]
    fallers = sorted(moves, key=lambda x: x["delta"])[:15]
    if not moves:
        st.info(f"No top-{DRAFT_SCOPE_RANK} players moved over this window yet.")
        return

    def _tbl(data):
        body = []
        for m in data:
            d = m["delta"]
            color = "#0c7a6e" if d > 0 else "#b3232a"
            arrow = "▲" if d > 0 else "▼"
            body.append(
                f'<tr><td class="pl">{m["name"]} <span style="font-size:10px;color:#8b86a0;">{m["pos"]}</span></td>'
                f'<td class="num">{m["was"]}→{m["now"]}</td>'
                f'<td class="num" style="color:{color};font-weight:700;">{arrow}{abs(d)}</td></tr>')
        return ('<table class="lb"><thead><tr><th>Player</th><th>ADP</th><th>Move</th>'
                '</tr></thead><tbody>' + "".join(body) + "</tbody></table>")

    c1, c2 = st.columns(2)
    c1.markdown("##### 📈 Risers")
    c1.markdown(_tbl(risers), unsafe_allow_html=True)
    c2.markdown("##### 📉 Fallers")
    c2.markdown(_tbl(fallers), unsafe_allow_html=True)


def render_draft_capital() -> None:
    st.markdown(f'<h2>{theme.crt("draft")}Draft Capital & Keeper Cost</h2>', unsafe_allow_html=True)
    st.caption("What each team brings to the draft after keepers: picks they'll "
               "actually make, future-pick stash, and a win-now vs. rebuild lean.")
    rows = []
    for o in MANAGERS:
        kr = team_keeper_rows(o)
        nk = len(kr)
        p26 = sum(get_owned_for(SEASON).get(o, {}).values())
        p27 = sum(get_owned_for(SEASON + 1).get(o, {}).values())
        p28 = sum(get_owned_for(SEASON + 2).get(o, {}).values())
        draftable = max(0, p26 - nk)
        kval = sum(int(r.get("Value", 0)) for r in kr)
        net_future = (p27 - DRAFT_ROUNDS) + (p28 - DRAFT_ROUNDS)
        if net_future >= 2:
            lean = '<span class="rk-badge">🔄 REBUILD</span>'
        elif net_future <= -2 or draftable <= 8:
            lean = '<span class="kept-badge">🔥 WIN-NOW</span>'
        else:
            lean = '<span style="color:#8b86a0;">⚖️ Balanced</span>'
        rows.append((config.manager_name(o), nk, kval, p26, draftable, p27, p28, lean, net_future))
    rows.sort(key=lambda x: (-x[2]))  # by keeper value
    body = "".join(
        f'<tr><td class="rk">{i}</td><td class="pl">{nm}</td><td class="num">{nk}</td>'
        f'<td class="num">{kval:+d}</td><td class="num">{p26}</td><td class="num">{dr}</td>'
        f'<td class="num">{p27}</td><td class="num">{p28}</td><td>{lean}</td></tr>'
        for i, (nm, nk, kval, p26, dr, p27, p28, lean, _nf) in enumerate(rows, 1))
    head = ('<tr><th>#</th><th>Team</th><th>Keepers</th><th>Keeper&nbsp;Val</th>'
            '<th>2026&nbsp;Picks</th><th>After&nbsp;Keepers</th><th>2027</th><th>2028</th>'
            '<th>Lean</th></tr>')
    st.markdown('<div class="neonwrap"><table class="lb"><thead>' + head
                + '</thead><tbody>' + body + '</tbody></table></div>', unsafe_allow_html=True)
    st.caption("After Keepers = 2026 picks you'll actually draft. 2027/2028 = total "
               "picks owned that year (14 = untouched). Lean: hoarding future picks → "
               "rebuild; sold future/early picks or thin on 2026 picks → win-now.")
    st.caption("💀 Ned's lean: whichever one loses harder.")


def render_roster_needs() -> None:
    st.markdown(f'<h2>{theme.crt("board")}Roster Needs</h2>', unsafe_allow_html=True)
    st.caption("After likely keepers, the starting spots each team still has to draft. "
               "🟢 set · 🟡 one short · 🔴 multiple holes.")
    from collections import Counter
    slots = starter_slots()
    need = Counter(s for s in slots if s in ("QB", "RB", "WR", "TE"))
    n_start = len([s for s in slots])
    cols_pos = ["QB", "RB", "WR", "TE"]

    def cell(have, req):
        gap = req - have
        bg = "#0c7a6e" if gap <= 0 else ("#d98a00" if gap == 1 else "#b3232a")
        return (f'<td class="num"><span style="background:{bg};color:#fff;padding:2px 9px;'
                f'border-radius:6px;">{have}/{req}</span></td>')

    body = []
    for o in MANAGERS:
        kr = team_keeper_rows(o)
        pc = Counter(r["Pos"] for r in kr)
        # count filled starter slots (base + flex from RB/WR/TE overflow)
        filled, flex_left = 0, sum(1 for s in slots if s == "FLEX")
        for p in ("QB", "RB", "WR", "TE"):
            use = min(pc.get(p, 0), need.get(p, 0))
            filled += use
            overflow = pc.get(p, 0) - use
            if p in ("RB", "WR", "TE"):
                take = min(overflow, flex_left)
                filled += take
                flex_left -= take
        cells = "".join(cell(pc.get(p, 0), need.get(p, 0)) for p in cols_pos)
        body.append(f'<tr><td class="pl">{config.manager_name(o)}</td>{cells}'
                    f'<td class="num">{filled}/{n_start}</td></tr>')
    head = ('<tr><th>Team</th>' + "".join(f"<th>{p}</th>" for p in cols_pos)
            + '<th>Starters&nbsp;Set</th></tr>')
    st.markdown('<div class="neonwrap"><table class="lb"><thead>' + head
                + '</thead><tbody>' + "".join(body) + '</tbody></table></div>',
                unsafe_allow_html=True)
    st.caption(f"Each cell = keepers / starters needed at that position ({dict(need)}). "
               "Starters Set counts FLEX filled by extra RB/WR/TE.")


@st.cache_data(ttl=86400 * 7, show_spinner=False)
def _season_stats(yr: int) -> dict:
    """player_id -> season stat line (pts_ppr, pos_rank_ppr...). Self-contained so
    it doesn't depend on a freshly-added sleeper attribute (cloud import caching)."""
    import requests
    try:
        r = requests.get(f"https://api.sleeper.app/v1/stats/nfl/regular/{yr}",
                         headers={"User-Agent": "kreeper-league/1.0"}, timeout=15)
        r.raise_for_status()
        return r.json() or {}
    except Exception:  # noqa: BLE001
        return {}


@st.cache_data(ttl=3600, show_spinner="Grading old keeper calls…")
def build_keeper_hitrate():
    thresh = {"QB": 12, "RB": 24, "WR": 30, "TE": 12}
    stats = {}
    per_owner, decisions = {}, []
    for yr in range(SEASON - 3, SEASON):
        ss = stats.get(yr) or _season_stats(yr)
        stats[yr] = ss
        for oid, picks in storage.load(yr).items():
            for s in picks:
                pid = s.get("player_id")
                if not pid:
                    continue
                pos = H.player_meta(pid).position  # seed has no position field
                if pos not in thresh:
                    continue
                pr = (ss.get(str(pid)) or {}).get("pos_rank_ppr")
                if pr is None:
                    continue
                hit = pr <= thresh[pos]
                d = per_owner.setdefault(oid, {"hit": 0, "tot": 0})
                d["hit"] += 1 if hit else 0
                d["tot"] += 1
                decisions.append({"owner": oid, "season": yr,
                                  "name": s.get("player_name") or H.player_meta(pid).name,
                                  "pos": pos, "fin": int(pr), "hit": hit})
    return per_owner, decisions


def render_keeper_hitrate() -> None:
    st.markdown(f'<h2>{theme.crt("top")}Keeper Hit-Rate</h2>', unsafe_allow_html=True)
    st.caption("Did past keepers pay off? A keep \"hits\" if the player finished a "
               "startable positional rank that season (QB/TE top-12, RB top-24, WR top-30).")
    per_owner, decisions = build_keeper_hitrate()
    if not decisions:
        st.info("No prior keeper seasons on record yet.")
        return
    rows = []
    for oid, d in sorted(per_owner.items(), key=lambda kv: -(kv[1]["hit"] / max(1, kv[1]["tot"]))):
        rate = d["hit"] / max(1, d["tot"])
        rows.append(f'<tr><td class="pl">{config.manager_name(oid)}</td>'
                    f'<td class="num">{d["hit"]}/{d["tot"]}</td>'
                    f'<td class="num" style="font-weight:700;color:{"#0c7a6e" if rate>=.5 else "#b3232a"};">'
                    f'{rate*100:.0f}%</td></tr>')
    st.markdown('##### Manager hit-rate (last 3 seasons)')
    st.markdown('<table class="lb"><thead><tr><th>Manager</th><th>Hits</th><th>Rate</th>'
                '</tr></thead><tbody>' + "".join(rows) + '</tbody></table>', unsafe_allow_html=True)
    best = sorted(decisions, key=lambda x: x["fin"])[:6]
    worst = sorted([d for d in decisions if not d["hit"]], key=lambda x: -x["fin"])[:6]
    c1, c2 = st.columns(2)
    c1.markdown("##### 💎 Best keeper calls")
    c1.markdown("\n".join(
        f'- **{d["name"]}** ({d["pos"]}{d["fin"]}, {d["season"]}) · {config.manager_name(d["owner"]).split()[0]}'
        for d in best))
    c2.markdown("##### 🧊 Coldest keeps")
    c2.markdown("\n".join(
        f'- **{d["name"]}** ({d["pos"]}{d["fin"]}, {d["season"]}) · {config.manager_name(d["owner"]).split()[0]}'
        for d in worst))


def render_superlatives() -> None:
    st.markdown(f'<h2>{theme.crt("rookies")}Superlatives</h2>', unsafe_allow_html=True)
    cards = []

    def card(emoji, title, who, sub):
        cards.append(f'<div class="kcard"><h4>{emoji} {title}</h4>'
                     f'<div style="font-family:\'Anton\';font-size:18px;color:var(--pink);">{who}</div>'
                     f'<div style="font-size:12px;opacity:.8;">{sub}</div></div>')

    lb = build_value_leaderboard(400)
    if not lb.empty:
        top = lb.sort_values("Value", ascending=False).iloc[0]
        card("💎", "Biggest Keeper Steal", top["Player"],
             f'{top["Team"]} · keep R{top["Cost Rd"]} vs ADP {top["ADP"]} (+{int(top["Value"])})')

    odds = build_championship_odds()
    if odds:
        card("🎲", "Title Favorite", odds[0]["Team"], f'{odds[0]["Odds"]} · {odds[0]["Win %"]}%')

    # most all-in (fewest 2026 picks after keepers) & deepest war chest
    cap = []
    for o in MANAGERS:
        nk = len(team_keeper_rows(o))
        p26 = sum(get_owned_for(SEASON).get(o, {}).values())
        cap.append((config.manager_name(o), max(0, p26 - nk), p26))
    allin = min(cap, key=lambda x: x[1])
    deep = max(cap, key=lambda x: x[2])
    card("🔥", "Most All-In", allin[0], f'only {allin[1]} picks left to draft')
    card("🏦", "Deepest War Chest", deep[0], f'{deep[2]} draft picks in 2026')

    seasons, agg = build_record_book()
    champ = max(agg.items(), key=lambda kv: (kv[1]["titles"], kv[1]["w"]))
    if champ[1]["titles"]:
        card("👑", "Most Titles", config.manager_name(champ[0]), f'{champ[1]["titles"]} championship(s)')
    runner = max(agg.items(), key=lambda kv: (kv[1]["runner"], -kv[1]["titles"]))
    if runner[1]["runner"] and not runner[1]["titles"]:
        card("🥈", "Always a Bridesmaid", config.manager_name(runner[0]),
             f'{runner[1]["runner"]} finals, 0 titles')
    best_rec = max(agg.items(), key=lambda kv: kv[1]["w"] / max(1, kv[1]["w"] + kv[1]["l"]))
    card("📊", "Best All-Time Record", config.manager_name(best_rec[0]),
         f'{best_rec[1]["w"]}-{best_rec[1]["l"]}')

    mv = adp_consensus.adp_movement(SEASON, window_days=14)
    pool_moves = [m for m in mv.get("moves", []) if m["now"] <= DRAFT_SCOPE_RANK]
    if pool_moves:
        riser = max(pool_moves, key=lambda m: m["delta"])
        if riser["delta"] > 0:
            card("🚀", "Hottest ADP Riser", riser["name"], f'up {riser["delta"]} spots ({riser["pos"]})')

    card("💀", "Most Likely To Be Ned", "Ned", "Runaway winner. Every year.")

    st.markdown('<div class="kcards">' + "".join(cards) + "</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------- sidebar + nav
# ----------------------------------------------------------------- navigation
# Consolidated sections; each groups related pages under sub-tabs. Routing via a
# `?p=` query param so the nav links are real, shareable, static links.
SECTIONS = [
    ("home", "Home"),
    ("keepers", "Keepers"),
    ("draft", "Draft"),
    ("trades", "Trades"),
    ("league", "League"),
    ("players", "Players"),
]
_VALID = {k for k, _ in SECTIONS}
page = st.query_params.get("p", "home")
if page not in _VALID:
    page = "home"

# Top bar on every page: clickable KREEPER logo (-> Home) + section links.
navlinks = "".join(
    f'<a class="navlink{" active" if k == page else ""}" href="?p={k}" target="_self">{label}</a>'
    for k, label in SECTIONS
)
st.markdown(
    f'<div class="kbar">'
    f'<a class="khome" href="?p=home" target="_self">{theme.logo_html(40, None)}</a>'
    f'<div class="topnav">{navlinks}</div></div>',
    unsafe_allow_html=True,
)

# Sidebar keeps the league info + ADP freshness (secondary).
with st.sidebar:
    st.caption(f"**{LEAGUE['name']}** · season **{SEASON}** · {NT} teams · "
               f"{DRAFT_ROUNDS} rds · {LEAGUE.get('scoring','ppr').upper()}")
    st.divider()
    st.subheader("ADP freshness")
    if ADP_META:
        st.caption(f"Updated: {ADP_META.get('updated_utc','—')}")
        st.caption("Sources: " + ", ".join(ADP_META.get("sources", [])))
        with st.expander("Source status"):
            for k, v in ADP_META.get("status", {}).items():
                st.write(f"{'✅' if v.startswith('ok') else '⚠️'} **{k}** — {v}")
    else:
        st.warning("No ADP pulled yet. Run `python scripts/refresh_adp.py`.")
    st.divider()
    st.caption("Rules: 3-yr max per keeper · Yr1 draft round · Yr2 up 3 rounds or ADP · "
               "Yr3 ADP · rookies kept for their career at your last rounds · "
               "trades carry the keeper round over.")
    st.divider()
    st.caption(f"💀 {ned()}")

if page == "home":
    render_home()
elif page == "keepers":
    t1, t2, t3 = st.tabs(["📋 Set My Keepers", "🗺️ Keeper Landscape", "🧩 Roster Needs"])
    with t1:
        render_my_keepers()
    with t2:
        render_keeper_landscape()
    with t3:
        render_roster_needs()
elif page == "draft":
    t1, t2, t3 = st.tabs(["🃏 Draft Board", "🔮 Projected Draft", "💰 Draft Capital"])
    with t1:
        render_draft_board()
    with t2:
        render_mock_draft()
    with t3:
        render_draft_capital()
elif page == "trades":
    t1, t2 = st.tabs(["🔁 Trade Market", "⚖️ Trade Analyzer"])
    with t1:
        render_trade_targets()
    with t2:
        render_trade_analyzer()
elif page == "league":
    t1, t2, t3, t4 = st.tabs(["🎲 Title Odds", "🏆 Record Book", "🎯 Keeper Hit-Rate", "🏅 Superlatives"])
    with t1:
        render_odds()
    with t2:
        render_record_book()
    with t3:
        render_keeper_hitrate()
    with t4:
        render_superlatives()
elif page == "players":
    t1, t2, t3 = st.tabs(["🆕 Rookies", "📊 Consensus ADP", "📈 ADP Trends"])
    with t1:
        render_rookies()
    with t2:
        render_adp()
    with t3:
        render_adp_trends()
