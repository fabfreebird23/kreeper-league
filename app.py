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


def build_value_leaderboard(top_n: int = 50, hide_rookie_keepers: bool = False) -> pd.DataFrame:
    """Best keeper bargains across every roster.

    Value = keeper-cost round minus ADP round, i.e. how many rounds of draft
    capital you'd gain by keeping the player versus drafting them at market.
    The "Kept" column flags players a manager has already declared as a keeper.
    Real NFL rookies (years_exp == 0) are excluded — they live on the Rookies tab.
    """
    # Players already declared as keepers (match by Sleeper id and by name).
    submitted = storage.load(SEASON)
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
    for oid, picks in storage.load(SEASON).items():
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


def build_mock_draft(rookie_factor: float | None = None) -> pd.DataFrame:
    """Projected draft order of the players who'd actually be available — everyone
    minus likely keepers — ranked by ADP with our league's rookie premium applied."""
    if rookie_factor is None:
        rookie_factor = config.mock_draft_rookie_factor()
    kept = _projected_kept_ids()
    name_idx = get_name_index()
    rows = []
    seen = set()
    for _, ar in ADP_DF.iterrows():
        pos, rank = ar.get("position"), ar.get("consensus_rank")
        if pos not in ("QB", "RB", "WR", "TE") or pd.isna(rank):
            continue
        pid = name_idx.get(normalize_name(ar["name"]), "")
        if not pid or str(pid) in kept or str(pid) in seen:
            continue
        seen.add(str(pid))
        rookie = _years_exp(pid) == 0
        adj = float(rank) * (rookie_factor if rookie else 1.0)
        rows.append({"_pid": str(pid), "Player": ar["name"], "Pos": pos,
                     "ADP": int(rank), "Rookie": rookie, "_adj": adj})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("_adj").reset_index(drop=True)
    df.insert(0, "Pick", range(1, len(df) + 1))
    df["Round"] = ((df["Pick"] - 1) // NT) + 1
    # snake slot within the round -> which team is on the clock
    order = config.load().get("draft_order") or list(MANAGERS.keys())
    def team_for(pick):
        rd = (pick - 1) // NT
        idx = (pick - 1) % NT
        slot = idx if rd % 2 == 0 else (NT - 1 - idx)  # snake
        return config.manager_name(order[slot]) if slot < len(order) else "—"
    df["Team"] = df["Pick"].map(team_for)
    return df


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
    data = storage.load(SEASON)
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


# ===================== My Draft Kit (private, password-gated) =================
# One-click UDK grabber: paste this as a browser bookmark's URL, then click it on
# the UDK Position Rankings page. It cycles QB/RB/WR/TE, sorts by ADP, and
# downloads udk_rankings.csv (Player,Tier) to upload here.
_DK_BOOKMARKLET = (
    "javascript:(async()=>{const w=m=>new Promise(r=>setTimeout(r,m));"
    "const P=['QB','RB','WR','TE'],A=[];for(const p of P){const b=[...document."
    "querySelectorAll('button')].find(x=>x.textContent.trim()===p);if(b)b.click();"
    "await w(2600);for(const tr of document.querySelectorAll('table tr')){const c="
    "[...tr.querySelectorAll('td')].map(x=>x.innerText.replace(/\\s+/g,' ').trim());"
    "if(c.length<7||!/^\\d+$/.test(c[1]))continue;A.push({n:c[0].replace("
    "/\\s+[A-Z]{2,4}\\s*\\(\\d+\\)\\s*$/,'').trim(),a:parseFloat(c[5]),t:c[6]});}}"
    "A.sort((x,y)=>x.a-y.a);const csv='Player,Tier\\n'+A.map(r=>'\"'+r.n+'\",'+r.t)"
    ".join('\\n');const u=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));"
    "const e=document.createElement('a');e.href=u;e.download='udk_rankings.csv';"
    "document.body.appendChild(e);e.click();e.remove();alert('UDK exported: '+"
    "A.length+' players. Now upload udk_rankings.csv in your Draft Kit.');})();"
)


def _dk_parse_rankings(text: str) -> list:
    """Parse pasted rankings: one player per line (any leading rank number / pos /
    team is stripped); a line like 'Tier 3' sets the tier for players below it."""
    idx = get_name_index()
    rows, tier, rank = [], 1, 0
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^[\-\*\s>]*tier\s*[:#]?\s*(\d+)", s, re.I)
        if m:
            tier = int(m.group(1))
            continue
        nm = re.sub(r"^\s*\d+[\.\):]?\s*", "", s)        # leading "12." / "12)"
        nm = re.sub(r"[,\t|].*$", "", nm)                # CSV/extra columns
        nm = re.sub(r"\([^)]*\)", "", nm)                # "(WR - PHI)"
        nm = re.sub(r"\b(QB|RB|WR|TE|K|DST|DEF)\d*\b", "", nm, flags=re.I).strip(" -–")
        if not nm:
            continue
        rank += 1
        rows.append({"rank": rank, "name": nm, "tier": tier,
                     "pid": idx.get(normalize_name(nm))})
    return rows


def _dk_parse_csv(text: str) -> list:
    """Parse a CSV export (e.g. a UDK / Google-Sheets rankings export): auto-detect
    the player-name column (the one matching the most players) and a tier column."""
    import csv
    import io
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if len(rows) < 2:
        return []
    idx = get_name_index()
    body = rows[1:]
    ncols = max(len(r) for r in rows)
    name_col, best = 0, -1
    for c in range(ncols):
        hits = sum(1 for r in body if len(r) > c and idx.get(normalize_name(r[c])))
        if hits > best:
            best, name_col = hits, c
    if best <= 0:
        return []
    header = [h.lower() for h in rows[0]]
    tier_col = next((i for i, h in enumerate(header) if "tier" in h), None)
    out, rank = [], 0
    for r in body:
        if len(r) <= name_col:
            continue
        nm = re.sub(r"\([^)]*\)", "", r[name_col]).strip()
        if not nm:
            continue
        tier = 1
        if tier_col is not None and len(r) > tier_col:
            tm = re.search(r"\d+", r[tier_col])
            tier = int(tm.group()) if tm else 1
        rank += 1
        out.append({"rank": rank, "name": nm, "tier": tier, "pid": idx.get(normalize_name(nm))})
    return out


def _dk_smart_parse(text: str) -> list:
    """Parse from a CSV export or a plain ranked list — whichever matches more."""
    line = _dk_parse_rankings(text)
    if "," in text or "\t" in text:
        csvp = _dk_parse_csv(text)
        if sum(1 for r in csvp if r.get("pid")) > sum(1 for r in line if r.get("pid")):
            return csvp
    return line


def _dk_fetch_url(url: str) -> str:
    """Fetch ranking text from a CSV / published-Google-Sheet URL."""
    import requests
    u = url.strip()
    m = re.search(r"docs\.google\.com/spreadsheets/d/([\w-]+)", u)
    if m and "output=csv" not in u and "format=csv" not in u:
        gid = re.search(r"[#&?]gid=(\d+)", u)
        u = f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv"
        if gid:
            u += f"&gid={gid.group(1)}"
    r = requests.get(u, timeout=15, headers={"User-Agent": "kreeper-draftkit/1.0"})
    r.raise_for_status()
    return r.text


@st.cache_data(ttl=86400, show_spinner=False)
def _dk_adp_pool():
    """ADP-ordered draftable players (pid, name, pos, adp) for AI mock picks."""
    idx = get_name_index()
    out = []
    for _, ar in ADP_DF.iterrows():
        pos, rank = ar.get("position"), ar.get("consensus_rank")
        if pos not in ("QB", "RB", "WR", "TE") or pd.isna(rank):
            continue
        pid = idx.get(normalize_name(ar["name"]))
        if pid:
            out.append({"pid": str(pid), "name": ar["name"], "pos": pos, "adp": int(rank)})
    out.sort(key=lambda x: x["adp"])
    return out


_TIER_COLORS = ["#0c7a6e", "#7b5cff", "#2bb5e8", "#ff4f9d", "#d98a00", "#8b86a0"]


def _dk_board_html(rows, drafted, limit=60):
    """Best-available table: each row = a ranked player not yet drafted."""
    body = []
    shown = 0
    for r in rows:
        if shown >= limit:
            break
        if not r.get("pid") or str(r["pid"]) in drafted:
            continue
        shown += 1
        col = _TIER_COLORS[(r["tier"] - 1) % len(_TIER_COLORS)]
        pos = (H.player_meta(r["pid"]).position if r.get("pid") else "")
        body.append(
            f'<tr><td class="rk">{r["rank"]}</td>'
            f'<td class="pl">{theme.img_tag(r["pid"])}{r["name"]}</td>'
            f'<td class="pos">{pos}</td>'
            f'<td class="num"><span style="background:{col};color:#fff;padding:1px 7px;'
            f'border-radius:6px;font-size:11px;">T{r["tier"]}</span></td></tr>'
        )
    head = '<tr><th>Rk</th><th>Player</th><th>Pos</th><th>Tier</th></tr>'
    return ('<div class="neonwrap" style="max-height:560px;overflow:auto;">'
            '<table class="lb"><thead>' + head + '</thead><tbody>'
            + "".join(body) + '</tbody></table></div>')


def _dk_set_rankings(rankings):
    st.session_state.dk_rankings = rankings
    storage.save_rankings(rankings, SEASON)   # persist (repo-backed) for next time


def _dk_rankings_ui():
    # Load the saved set once per session so rankings persist across visits/devices.
    if "dk_rankings" not in st.session_state:
        st.session_state.dk_rankings = storage.load_rankings(SEASON)

    st.caption("Import your UDK rankings: use the one-click UDK grabber below, or "
               "paste / upload / link a CSV. Tiers, rank numbers, positions and "
               "teams are all handled, and it's saved automatically for next time.")

    with st.expander("🔄 One-click refresh from the UDK (bookmarklet)"):
        st.markdown(
            "This app can't log into the UDK for you, so the grab runs **in your "
            "browser** (where you're already logged in). One-time setup, then it's a "
            "single click whenever the UDK updates:\n\n"
            "1. **Make a bookmark** — bookmark this page, edit it, name it "
            "*Grab UDK*, and replace its **URL** with the code below.\n"
            "2. Open your **UDK → Position Rankings** page (any position).\n"
            "3. Click the **Grab UDK** bookmark. It cycles QB/RB/WR/TE and downloads "
            "`udk_rankings.csv` (~10 sec).\n"
            "4. Back here, pick **Upload file** and choose that CSV. Done — it "
            "re-matches everyone and saves.")
        st.code(_DK_BOOKMARKLET, language="text")
        st.caption("Or just tell me \"refresh my UDK rankings\" and I'll pull them for you.")

    src = st.radio("Source", ["Paste", "CSV / Sheet URL", "Upload file"],
                   horizontal=True, key="dk_src")
    if src == "Paste":
        text = st.text_area("Paste rankings (or CSV)", height=220, key="dk_text",
                            placeholder="Tier 1\nJa'Marr Chase\nBijan Robinson\nTier 2\n...")
        if st.button("Parse & save", type="primary"):
            _dk_set_rankings(_dk_smart_parse(text))
    elif src == "CSV / Sheet URL":
        url = st.text_input("CSV or published Google-Sheet URL", key="dk_url")
        if st.button("Fetch & save", type="primary") and url:
            try:
                _dk_set_rankings(_dk_smart_parse(_dk_fetch_url(url)))
                st.success("Fetched from URL.")
            except Exception as e:  # noqa: BLE001
                st.error(f"Couldn't fetch that URL ({type(e).__name__}). Make sure it's "
                         "public / published to the web as CSV.")
    else:
        up = st.file_uploader("Upload rankings (.csv or .json)", type=["csv", "json"], key="dk_up")
        if up is not None:
            try:
                raw = up.getvalue().decode("utf-8", "ignore")
                parsed = json.loads(raw) if up.name.endswith(".json") else _dk_smart_parse(raw)
                _dk_set_rankings(parsed)
                st.success(f"Loaded {len(parsed)} players.")
            except Exception:  # noqa: BLE001
                st.error("Couldn't read that file.")

    ranks = st.session_state.get("dk_rankings")
    if not ranks:
        return
    unmatched = [r["name"] for r in ranks if not r.get("pid")]
    st.success(f"**{len(ranks)}** ranked · **{len(ranks) - len(unmatched)}** matched"
               f" · **{len(unmatched)}** unmatched.")
    if unmatched:
        with st.expander(f"⚠️ {len(unmatched)} names didn't match — fix spelling & re-parse"):
            st.write(", ".join(unmatched))
    st.download_button("⬇ Save my rankings (.json)", json.dumps(ranks),
                       file_name=f"my_rankings_{SEASON}.json", mime="application/json")
    st.dataframe(pd.DataFrame([{"Rk": r["rank"], "Tier": r["tier"], "Player": r["name"],
                                "Matched": "✓" if r.get("pid") else "—"} for r in ranks]),
                 hide_index=True, use_container_width=True, height=320)


def _dk_assistant_ui():
    ranks = st.session_state.get("dk_rankings")
    if not ranks:
        st.info("Add your rankings on the **My Rankings** tab first.")
        return
    from kreeper import sleeper
    names = list(NAME_TO_ID.keys())
    default_me = names.index("Brandon Cliffton") if "Brandon Cliffton" in names else 0
    c1, c2, c3 = st.columns([1, 1, 1])
    me = c1.selectbox("Your team", names, index=default_me, key="dk_live_me")
    pos_f = c2.selectbox("Position", ["All", "QB", "RB", "WR", "TE"], key="dk_live_pos")
    with c3:
        st.write("")
        auto = st.checkbox("Auto-refresh (12s)", key="dk_live_auto")
        st.button("🔄 Refresh now")
    if auto:
        try:
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval=12000, key="dk_live_tick")
        except Exception:  # noqa: BLE001
            st.caption("(auto-refresh unavailable — use the button)")

    lg = sleeper.get_league(LEAGUE["sleeper_league_id"])
    draft_id = lg.get("draft_id")
    picks = sleeper.get_draft_picks_fresh(draft_id) if draft_id else []
    drafted = {str(p.get("player_id")) for p in picks if p.get("player_id")}
    me_id = NAME_TO_ID[me]
    my_pids = [str(p.get("player_id")) for p in picks if str(p.get("picked_by")) == str(me_id)]

    m1, m2, m3 = st.columns(3)
    m1.metric("Picks made", len(picks))
    m2.metric("On the clock", f"#{len(picks) + 1}" if draft_id else "—")
    m3.metric("Your players", len(my_pids))

    rows = ranks if pos_f == "All" else [
        r for r in ranks if r.get("pid") and H.player_meta(r["pid"]).position == pos_f]
    st.markdown("##### 🎯 Best available (your board)")
    st.markdown(_dk_board_html(rows, drafted), unsafe_allow_html=True)

    if my_pids:
        from collections import Counter
        pc = Counter(H.player_meta(p).position for p in my_pids)
        st.markdown("##### Your roster · " + " · ".join(f"{k}:{v}" for k, v in sorted(pc.items())))
        st.write(", ".join(H.player_meta(p).name for p in my_pids))
    st.caption("Reads your league's live Sleeper draft — best available is ranked "
               "by YOUR list, colored by tier, with drafted players removed. Hit "
               "Refresh (or auto) as picks come in.")


def _dk_mock_ui():
    ranks = st.session_state.get("dk_rankings")
    if not ranks:
        st.info("Add your rankings on the **My Rankings** tab first.")
        return
    order = config.load().get("draft_order") or list(MANAGERS.keys())
    slot_names = [config.manager_name(o) for o in order]
    default_me = slot_names.index("Brandon Cliffton") if "Brandon Cliffton" in slot_names else 0
    me_slot = st.selectbox("Your draft slot", slot_names, index=default_me, key="dk_mock_slot")
    my_slot = slot_names.index(me_slot)
    n = len(order)

    if st.button("🔁 Start / reset mock"):
        st.session_state.dk_mock = {"taken": list(_projected_kept_ids()), "log": []}
    state = st.session_state.get("dk_mock")
    if not state:
        st.info("Click **Start** to mock from the current board (likely keepers removed).")
        return

    taken = set(state["taken"])
    adp_pool = _dk_adp_pool()

    def snake_slot(pick_idx):  # 0-based overall pick -> 0-based slot
        rd = pick_idx // n
        i = pick_idx % n
        return i if rd % 2 == 0 else (n - 1 - i)

    # Auto-run AI picks until it's the user's turn (or the draft is full).
    progressed = False
    while len(state["log"]) < n * DRAFT_ROUNDS and snake_slot(len(state["log"])) != my_slot:
        nxt = next((p for p in adp_pool if p["pid"] not in taken), None)
        if not nxt:
            break
        taken.add(nxt["pid"])
        state["log"].append({"slot": snake_slot(len(state["log"])), "pid": nxt["pid"], "by": "ADP"})
        progressed = True
    if progressed:
        state["taken"] = list(taken)

    pick_no = len(state["log"]) + 1
    rd = (pick_no - 1) // n + 1
    st.caption(f"Pick **{pick_no}** · Round **{rd}** · you're on the clock at slot {my_slot + 1}.")

    cols = st.columns(4)
    avail = [r for r in ranks if r.get("pid") and str(r["pid"]) not in taken][:8]
    st.markdown("##### Your pick — top of your board")
    for i, r in enumerate(avail):
        if cols[i % 4].button(f'{r["name"]}', key=f"dk_pick_{len(state['log'])}_{r['pid']}"):
            taken.add(str(r["pid"]))
            state["taken"] = list(taken)
            state["log"].append({"slot": my_slot, "pid": str(r["pid"]), "by": "you"})
            st.rerun()

    mine = [p["pid"] for p in state["log"] if p["slot"] == my_slot]
    if mine:
        st.markdown("##### Your team")
        st.write(", ".join(H.player_meta(p).name for p in mine))
    st.caption("Practice mock: other teams auto-pick by consensus ADP; you pick off "
               "your own board. Keepers are pre-removed.")


def render_draft_kit():
    st.markdown(f'<h2>{theme.crt("draft")}My Draft Kit 🔒</h2>', unsafe_allow_html=True)
    try:
        pw = st.secrets.get("draft_kit_password")
    except Exception:  # noqa: BLE001
        pw = None
    if not pw:
        st.warning('Private tab. To enable it, add `draft_kit_password = "your-password"` '
                   "to your Streamlit secrets (same place as `github_token`).")
        return
    if not st.session_state.get("dk_auth"):
        with st.form("dk_login"):
            entered = st.text_input("Password", type="password")
            if st.form_submit_button("Unlock") and entered:
                if entered == pw:
                    st.session_state.dk_auth = True
                    st.rerun()
                else:
                    st.error("Wrong password.")
        return
    st.caption("Your private draft command center. Rankings are saved automatically "
               "and reload here every time — on any device.")
    t1, t2, t3 = st.tabs(["📥 My Rankings", "🎯 Live Draft Assistant", "🧪 Mock Draft"])
    with t1:
        _dk_rankings_ui()
    with t2:
        _dk_assistant_ui()
    with t3:
        _dk_mock_ui()


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
    data = storage.load(SEASON)
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
    st.caption("Who'd actually be drafted once keepers come off the board. Likely "
               "keepers (declared + each team's best by value) are removed, then the "
               "rest are ranked by consensus ADP with our league's rookie premium "
               "applied — so the studs everyone keeps clear the way for the rookies.")
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
        rk = ' <span class="rk-badge">RK</span>' if r["Rookie"] else ""
        rows.append(
            f'<tr><td class="rk">{r["Round"]}.{((r["Pick"]-1)%NT)+1:02d}</td>'
            f'<td class="pl">{theme.img_tag(r["_pid"])}{r["Player"]}{rk}</td>'
            f'<td class="pos"><span class="posdot p-{r["Pos"]}"></span>{r["Pos"]}</td>'
            f'<td>{r["Team"]}</td>'
            f'<td class="num">{r["ADP"]}</td></tr>'
        )
    head = '<tr><th>Pick</th><th>Player</th><th>Pos</th><th>On the clock</th><th>ADP</th></tr>'
    st.markdown('<div class="neonwrap"><table class="lb lb-mock"><thead>' + head
                + '</thead><tbody>' + "".join(rows) + '</tbody></table></div>',
                unsafe_allow_html=True)
    st.caption("Projection only — assumes snake order and that managers draft by "
               "ADP. **RK** = rookie. Tune the rookie premium above to match how "
               "your league really values rookies.")


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
    data = storage.load(SEASON)
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
               + ", ".join(ADP_META.get("sources", [])) + ".")
    if ADP_DF.empty:
        st.info("No ADP data yet. Run `python scripts/refresh_adp.py`.")
        return
    c1, c2 = st.columns([2, 1])
    with c1:
        q = st.text_input("Search player", "")
    with c2:
        pos = st.multiselect("Position", ["QB", "RB", "WR", "TE"], default=[])
    view = ADP_DF.copy()
    if q:
        view = view[view["name"].str.contains(q, case=False, na=False)]
    if pos:
        view = view[view["position"].isin(pos)]
    view = view[["consensus_rank", "name", "position", "consensus_adp"]].rename(
        columns={"consensus_rank": "Rank", "name": "Player",
                 "position": "Pos", "consensus_adp": "Consensus ADP"})
    st.dataframe(view, hide_index=True, use_container_width=True, height=600)


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
    ("kit", "🔒 Draft Kit"),
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

if page == "home":
    render_home()
elif page == "keepers":
    t1, t2 = st.tabs(["📋 Set My Keepers", "🗺️ Keeper Landscape"])
    with t1:
        render_my_keepers()
    with t2:
        render_keeper_landscape()
elif page == "draft":
    t1, t2 = st.tabs(["🃏 Draft Board", "🔮 Projected Draft"])
    with t1:
        render_draft_board()
    with t2:
        render_mock_draft()
elif page == "trades":
    t1, t2 = st.tabs(["🔁 Trade Market", "⚖️ Trade Analyzer"])
    with t1:
        render_trade_targets()
    with t2:
        render_trade_analyzer()
elif page == "league":
    t1, t2 = st.tabs(["🎲 Title Odds", "🏆 Record Book"])
    with t1:
        render_odds()
    with t2:
        render_record_book()
elif page == "players":
    t1, t2 = st.tabs(["🆕 Rookies", "📊 Consensus ADP"])
    with t1:
        render_rookies()
    with t2:
        render_adp()
elif page == "kit":
    render_draft_kit()
