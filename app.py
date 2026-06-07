"""The Kreeper League — Keeper Hub (Streamlit app).

Pages (sidebar nav):
  Home            — top-30 keeper-value leaderboard + per-team submitted keepers
  Set my keepers  — pick your roster's keepers, with live cost + eligibility
  Consensus ADP   — daily multi-source consensus ADP (all sources averaged)
"""
from __future__ import annotations

import datetime as dt

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


def rookie_keeper_eligible(owner_id: str, pid: str) -> bool:
    """A player may be kept as a ROOKIE keeper only if THIS team drafted them in
    the player's rookie season and has held them continuously since. A trade (or
    picking them up as a veteran) breaks rookie-keeper eligibility.
    """
    pid = str(pid)
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


def render_home() -> None:
    st.markdown(theme.logo_html(60, "The Keeper Hub · 2026"), unsafe_allow_html=True)
    render_countdown()
    st.markdown(f'<h2>{theme.crt("top")}Top 50 Keeper Values</h2>', unsafe_allow_html=True)
    st.caption("Best keeper bargains across every roster — draft value gained by keeping a "
               "player (cost round vs. consensus ADP round). Green = declared keeper · "
               "purple RK = rookie keeper · cyan = free agent. Real NFL rookies are on the Rookies tab.")
    hide_rk = st.toggle("Hide rookie keepers", value=False,
                        help="Filter out players currently in rookie-keeper status.")
    lb = build_value_leaderboard(50, hide_rookie_keepers=hide_rk)
    if lb.empty:
        st.info("No ADP data yet — run `python scripts/refresh_adp.py` to populate the board.")
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
with st.sidebar:
    st.markdown(theme.logo_html(40, None), unsafe_allow_html=True)
    st.caption(f"**{LEAGUE['name']}** · season **{SEASON}** · {NT} teams · "
               f"{DRAFT_ROUNDS} rds · {LEAGUE.get('scoring','ppr').upper()}")
    page = st.radio("Navigate",
                    ["Home", "Rookies", "Draft Board", "Set My Keepers", "Consensus ADP"],
                    label_visibility="collapsed")
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

if page == "Home":
    render_home()
elif page == "Rookies":
    render_rookies()
elif page == "Draft Board":
    render_draft_board()
elif page == "Set My Keepers":
    render_my_keepers()
else:
    render_adp()
