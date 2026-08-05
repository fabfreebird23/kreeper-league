"""Gradient-glass theme: near-black cards on a soft pink/blue glow, with a
page-scoped accent gradient (each of the six sections gets its own hue so
the app doesn't read as one card style copy-pasted six times), animated
liquid-wave surfaces, plus shared CSS for the custom HTML surfaces
(leaderboard, team cards, draft board) and Sleeper headshots.
"""
from __future__ import annotations

import math

SLEEPER_IMG = "https://sleepercdn.com/content/nfl/players/thumb/{pid}.jpg"
SLEEPER_DEFAULT = "https://sleepercdn.com/images/v2/icons/player_default.webp"
ESPN_IMG = "https://a.espncdn.com/i/headshots/nfl/players/full/{eid}.png"

# sleeper_pid -> espn player/headshot id, populated by app at startup
# (set_espn_ids). Lets newly-added rookies — who have no Sleeper photo — fall
# back to ESPN's headshot before the generic silhouette.
_ESPN_BY_PID: dict = {}


def set_espn_ids(mapping: dict) -> None:
    _ESPN_BY_PID.clear()
    _ESPN_BY_PID.update({str(k): str(v) for k, v in mapping.items() if v})

# Fixed semantic palette — status colors that mean the same thing on every
# page (kept/good, rookie, warn, bad) and never shift with the per-page accent.
ACCENT = "#4f9dff"
PURPLE = "#a06bff"
TEAL = "#3fd67c"
CYAN = "#5ecbf0"
AMBER = "#f0b840"
RED = "#ff5c6c"

# One fixed accent gradient (g1 -> g2 -> g3) used everywhere — same nav,
# same headings, same accent color regardless of which section you're on,
# so the theme doesn't shift underneath you as you click around. g2 also
# doubles as the flat "--accent" for solid fills (buttons, active nav, bar
# fills); it's bright/light enough to stay readable under the fixed dark ink.
GRADIENT = ("#ff5aa0", "#a06bff", "#4f9dff")

# Cycled across repeated card lists (team boxes, superlatives, draft-order
# picks) so a stack of identical cards doesn't read as one giant color block.
CARD_PALETTE = ["#ff5aa0", "#4f9dff", "#3fd67c", "#f0b840", "#a06bff", "#5ecbf0"]


def card_color(i: int) -> str:
    return CARD_PALETTE[i % len(CARD_PALETTE)]

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Anton&family=Oswald:wght@400;500;600;700&family=Rubik+Wet+Paint&display=swap');

:root{
  --bg:#08080b; --panel:#121216; --panel2:#17171d;
  --g1:#ff5aa0; --g2:#a06bff; --g3:#4f9dff; --accent:var(--g2); --accent-ink:#14101f;
  --purple:#a06bff; --teal:#3fd67c; --cyan:#5ecbf0;
  --amber:#f0b840; --red:#ff5c6c; --ink:#f2f2f0; --muted:#8a8a95; --dim:#5f5f6b;
  --line:rgba(255,255,255,.09);
  --grad:linear-gradient(90deg, var(--g1), var(--g2) 55%, var(--g3));
}

/* near-black field with a soft pink/blue glow + faint topo-line grid,
   like a dashboard product shot */
.stApp{
  background:
    radial-gradient(46% 34% at 14% 6%, rgba(255,90,160,.10), transparent 60%),
    radial-gradient(40% 34% at 86% 4%, rgba(79,157,255,.10), transparent 60%),
    repeating-radial-gradient(circle at 12% 4%, rgba(255,255,255,.032) 0,
      rgba(255,255,255,.032) 1px, transparent 1px, transparent 40px),
    repeating-radial-gradient(circle at 88% 100%, rgba(255,255,255,.022) 0,
      rgba(255,255,255,.022) 1px, transparent 1px, transparent 56px),
    var(--bg);
  background-attachment:fixed;
}
html, body, [class*="css"]{ font-family:'Oswald', sans-serif; color:var(--ink) !important; }
[data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li, [data-testid="stMarkdownContainer"] span,
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p,
[data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] li,
[data-testid="stSidebar"] label, [data-testid="stExpander"] summary,
[data-testid="stExpander"] p, [data-testid="stWidgetLabel"] p{ color:var(--ink) !important; }
[data-testid="stMarkdownContainer"] a{ color:var(--accent) !important; }

[data-testid="stHeader"]{ background:transparent; }
[data-testid="stSidebar"]{ background:#0d0d11; border-right:1px solid var(--line); }

/* expanders — themed card, not the bare default row (used for any plain
   st.expander elsewhere in the app, e.g. the sidebar's Source status) */
[data-testid="stExpander"]{ border:1px solid var(--line); border-left:4px solid var(--accent);
  border-radius:10px; background:var(--panel); margin-bottom:10px; overflow:hidden; }
[data-testid="stExpander"] summary{ padding:14px 18px !important; font-family:'Oswald', sans-serif !important;
  font-size:14.5px !important; font-weight:600 !important; transition:background .12s; }
[data-testid="stExpander"] summary:hover{ background:rgba(255,255,255,.03); }
[data-testid="stExpander"] summary [data-testid="stIconMaterial"]{ display:none; }
[data-testid="stExpander"] [data-testid="stExpanderDetails"]{ padding:0 18px 18px; }

/* team contract-card dropdowns — plain HTML <details>/<summary> instead of
   st.expander, so each one can carry its own two-tone color: "Contracts"
   stays white, the team name picks up that team's card-palette color.
   (Streamlit wraps every widget in identical generic divs, so nth-of-type
   can't target "the Nth expander" via CSS — raw HTML sidesteps that.) */
details.team-details{ border:1px solid var(--line); border-left:4px solid var(--accent);
  border-radius:10px; background:var(--panel); margin-bottom:10px; overflow:hidden; }
details.team-details summary{ list-style:none; cursor:pointer; padding:14px 18px;
  font-family:'Oswald', sans-serif; font-weight:600; font-size:14.5px; color:var(--ink);
  transition:background .12s; }
details.team-details summary::-webkit-details-marker{ display:none; }
details.team-details summary:hover{ background:rgba(255,255,255,.03); }
details.team-details .team-details-body{ padding:4px 18px 18px; }
details.team-details .empty-note{ color:var(--muted); font-size:13px; padding:0 0 4px; margin:0; }

/* headings — h2 carries the page's gradient as text color, not a filled bar */
h1{ font-family:'Anton', sans-serif !important; letter-spacing:1px; text-transform:uppercase;
  color:var(--ink) !important; }
h2{ font-family:'Anton', sans-serif !important; letter-spacing:.4px; margin:0 0 8px !important;
  font-size:1.5rem !important; color:var(--ink) !important; }
h3{ font-family:'Oswald', sans-serif !important; font-weight:600 !important; letter-spacing:.2px;
  color:var(--ink) !important; font-size:1.05rem !important; margin:0 0 10px !important; }
/* two-tone heading accent — wrap the one word that matters in <span class="g"> */
.g{ background:var(--grad) !important; -webkit-background-clip:text !important;
  background-clip:text !important; -webkit-text-fill-color:transparent !important; }

/* shared liquid-wave asset — the fill-level offset + drift animation apply
   anywhere a `.bob > .wv.front/.back` shows up (logo emblem, liquid rings) */
.bob{ transform:translateY(var(--sy,0px)); }
.wv.front{ animation:liq-front 7s linear infinite; }
.wv.back{ animation:liq-back 11s linear infinite; }
@keyframes liq-front{ from{transform:translateX(0)} to{transform:translateX(-200px)} }
@keyframes liq-back{ from{transform:translateX(0)} to{transform:translateX(200px)} }
@media (prefers-reduced-motion: reduce){
  .wv.front, .wv.back{ animation:none !important; }
}

/* ThunderCats wordmark — liquid-chrome steel letters + red-disc pig emblem */
.tc-wrap{ display:inline-flex; align-items:center; gap:8px; }
.tc-emblem{ flex:0 0 auto; filter:drop-shadow(0 4px 16px rgba(79,157,255,.35)); }
.neon-logo{ font-family:'Anton', sans-serif; line-height:1; display:inline-block;
  letter-spacing:0px; white-space:nowrap; transform:skewX(-7deg); }
.neon-logo .kl{ display:inline-block;
  background:linear-gradient(180deg,#f2f8ff 0%,#aecdf0 24%,#4a6ea4 47%,#14264a 51%,
            #3f6098 55%,#7ea4d4 76%,#e6f2ff 100%);
  -webkit-background-clip:text; background-clip:text;
  -webkit-text-fill-color:transparent; color:transparent;
  text-shadow:0 1px 0 #243b66, 1px 2px 0 #16264a, 3px 4px 6px rgba(8,14,30,.55); }
.neon-tag{ font-family:'Oswald'; letter-spacing:5px; font-weight:700; font-size:11px;
  color:var(--purple); text-transform:uppercase; }

/* section tabs (st.tabs) -> match the display-font header treatment */
[data-testid="stTabs"] button[data-baseweb="tab"]{
  font-family:'Anton', sans-serif !important; letter-spacing:.8px; text-transform:uppercase;
  font-size:14px; color:var(--muted);
}
[data-testid="stTabs"] button[data-baseweb="tab"] p{
  font-family:'Anton', sans-serif !important; letter-spacing:.8px; text-transform:uppercase;
  font-size:14px;
}
[data-testid="stTabs"] button[aria-selected="true"]{ color:var(--ink) !important; }
[data-testid="stTabs"] button[aria-selected="true"] p{ color:var(--ink) !important; }
[data-testid="stTabs"] [data-baseweb="tab-highlight"]{ background:var(--grad) !important; }

/* sidebar nav radio -> flat pills */
[data-testid="stSidebar"] [role="radiogroup"] label{ border:1px solid var(--line); border-radius:6px;
  padding:6px 10px; margin-bottom:6px; background:var(--panel); transition:.15s; }
[data-testid="stSidebar"] [role="radiogroup"] label:hover{ border-color:var(--accent); }
[data-testid="stSidebar"] [role="radiogroup"] label p{ font-weight:600; text-transform:uppercase; letter-spacing:.5px; font-size:13px;}

.stButton>button{ font-family:'Anton'; letter-spacing:1px; text-transform:uppercase;
  background:var(--accent); color:var(--accent-ink); border:none; border-radius:4px; }
.stButton>button:hover{ background:var(--purple); color:#fff; }

/* ---- shared custom tables — flat, no boxed wrapper, hairline row dividers only ---- */
.neonwrap{ overflow-x:auto; }
table.lb{ width:100%; border-collapse:collapse; font-family:'Oswald'; font-size:14px; }
table.lb th{ color:var(--muted); text-transform:uppercase; letter-spacing:1px;
  font-size:11px; text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); position:sticky; top:0; background:var(--bg); }
table.lb td{ padding:6px 10px; border-bottom:1px solid var(--line); }
table.lb tr:hover td{ background:rgba(255,255,255,.025); }
table.lb tr.kept td{ background:linear-gradient(90deg, rgba(47,224,196,.16), rgba(47,224,196,.03)); }
table.lb tr.kept td:first-child{ box-shadow:inset 3px 0 0 var(--teal); }
.lb .rk{ font-family:'Anton'; color:var(--accent); width:34px; text-align:center; }
.lb .pl{ font-weight:600; }
.lb .pos{ color:var(--muted); font-size:11px; font-weight:600; }
.lb .val{ font-family:'Anton'; color:var(--teal); text-align:right; }
.lb .num{ text-align:right; color:var(--ink); }
.lb .kept-badge{ color:#04231d; background:var(--teal); font-weight:700; font-size:10px;
  padding:1px 6px; border-radius:3px; text-transform:uppercase; letter-spacing:.5px; }
.lb .rk-badge{ color:#fff; background:var(--purple); font-weight:700; font-size:10px;
  padding:1px 6px; border-radius:3px; text-transform:uppercase; letter-spacing:.5px; margin-left:4px; }
.lb .fa-tag{ color:var(--cyan); font-weight:600; font-size:12px; font-style:italic; }
table.lb tr.fa td{ background:rgba(94,203,240,.06); }
.hs{ width:30px; height:30px; border-radius:50%; object-fit:cover; vertical-align:middle;
  background:var(--panel2); border:1px solid var(--line); margin-right:8px; }
.posdot{ display:inline-block; width:6px;height:6px;border-radius:50%;margin-right:5px;vertical-align:middle;}
.p-QB{background:var(--amber);} .p-RB{background:var(--teal);} .p-WR{background:var(--cyan);} .p-TE{background:var(--accent);}

/* team line-cards: colored strip header + spacious keeper rows */
.kcards{ display:grid; grid-template-columns:repeat(2,1fr); gap:16px; }
.kcard{ border:1px solid var(--line); border-radius:10px; background:var(--panel); overflow:hidden; }
.kcard h4{ font-family:'Anton', sans-serif; font-size:14px; margin:0; letter-spacing:.6px;
  text-transform:uppercase; color:var(--accent-ink); background:var(--accent); padding:9px 14px; }
.kcard .kp{ display:flex; align-items:center; gap:10px; font-size:13.5px; padding:8px 14px;
  border-bottom:1px solid var(--line); transition:background .12s; }
.kcard .kp:last-child{ border-bottom:none; }
.kcard .kp:hover{ background:var(--panel2); }
.kcard .kp img{ width:28px;height:28px;border-radius:50%;object-fit:cover;background:var(--panel2);
  border:1px solid var(--line); flex:0 0 auto; }
.kcard .kp span:not(.rd):not(.rk-tag){ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.kcard .kp .rd{ margin-left:auto; flex:0 0 auto; font-family:var(--mono, monospace); font-size:11.5px;
  font-weight:700; color:var(--teal); background:var(--panel2); border:1px solid var(--line);
  border-radius:5px; padding:2px 7px; }
.kcard .empty{ color:var(--muted); font-style:italic; font-size:12px; padding:12px 14px; }
.kcard .rk-tag{ color:var(--amber); font-size:9px; font-weight:700; margin-left:4px; }

/* stat tiles row */
.tiles{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:16px; }
.tile{ background:var(--panel2); border:1px solid var(--line); border-radius:10px; padding:12px 14px; }
.tile .num{ font-family:var(--mono, monospace); font-weight:700; font-size:24px; color:var(--ink); line-height:1; }
.tile .num.accent{ color:var(--accent); }
.tile .lbl{ font-size:10px; text-transform:uppercase; letter-spacing:.8px; color:var(--muted); margin-top:5px; }
.tile .sub{ font-size:11px; color:var(--ink); opacity:.75; margin-top:1px; }

/* FAAB debt ring — animated liquid-wave fill, same wave asset as the logo */
.faab-grid{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; }
.faab-card{ border:1px solid var(--line); border-radius:10px; background:var(--panel);
  padding:12px; text-align:center; }
.faab-card h4{ font-family:'Anton'; font-size:14px; margin:0 0 8px; color:var(--purple); }
.faab-card .rem{ font-size:11px; color:var(--muted); margin-top:2px; }

/* liquid-fill circle gauge — reusable for FAAB rings + home quick-glance tiles */
.liq-ring{ position:relative; display:inline-flex; align-items:center; justify-content:center; margin-bottom:8px; }
.liq-ring svg{ display:block; }
.liq-ring .liq-val{ position:absolute; inset:0; display:flex; flex-direction:column;
  align-items:center; justify-content:center; text-align:center; line-height:1.15; pointer-events:none; }
.liq-ring .liq-val b{ font-family:'Anton'; font-weight:400; }
.liq-ring .liq-val small{ font-size:8.5px; color:var(--muted); text-transform:uppercase; letter-spacing:.4px; }

.glance-panel{ border-radius:16px; padding:1px; margin:10px 0 26px;
  background:linear-gradient(135deg, rgba(255,90,160,.4), rgba(160,107,255,.28), rgba(79,157,255,.4)); }
.glance-panel-in{ background:var(--panel); border-radius:15px; padding:20px 24px; }
.liquid-stats{ display:flex; gap:36px; flex-wrap:wrap; }
.liquid-stat{ display:flex; align-items:center; gap:14px; }
.liquid-stat .txt .lbl{ font-size:10.5px; text-transform:uppercase; letter-spacing:1px; color:var(--muted); }
.liquid-stat .txt .sub{ font-size:13px; color:var(--ink); margin-top:3px; max-width:180px; }

.faab-pot{ text-align:center; padding:18px 12px; border-radius:12px; border:1px solid transparent;
  background:linear-gradient(var(--panel2),var(--panel2)) padding-box, var(--grad) border-box;
  margin-bottom:16px; }
.faab-pot b{ font-family:'Anton'; font-size:38px; background:var(--grad); -webkit-background-clip:text;
  background-clip:text; -webkit-text-fill-color:transparent; display:block; line-height:1; }
.faab-pot span{ font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:1px; }
.burnbar-track{ width:100%; height:8px; border-radius:5px; background:var(--bg); overflow:hidden; }
.burnbar-fill{ height:100%; border-radius:5px; }

/* generic gradient-bordered panel */
.gpanel{ border-radius:16px; padding:1px; margin-bottom:16px;
  background:linear-gradient(135deg, rgba(255,90,160,.4), rgba(160,107,255,.28), rgba(79,157,255,.4)); }
.gpanel-in{ background:var(--panel); border-radius:15px; padding:20px 22px; }

/* recent trades */
.gtrades{ display:flex; flex-direction:column; gap:16px; }
.gtrade-teams{ font-size:15px; font-weight:600; color:var(--ink); margin-bottom:12px; }
.gtrade-teams .vs{ color:var(--muted); font-weight:400; font-size:12px; margin:0 4px; }
.gtrade-assets{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:18px; }
.gtrade-assets div b{ display:block; font-size:10px; color:var(--muted); text-transform:uppercase;
  letter-spacing:.6px; margin-bottom:8px; font-weight:600; }
.gasset-chip{ display:inline-block; font-size:11.5px; background:rgba(255,90,160,.12);
  border:1px solid rgba(255,90,160,.32); color:#ffb3d4; padding:4px 10px; border-radius:999px;
  margin:0 6px 6px 0; }
.gtrade-date{ font-size:11px; color:var(--muted); margin-top:14px; }

/* contract cards — per-player keeper economics browse grid */
.kr-section{ margin-bottom:28px; }
.kr-section-head{ display:flex; align-items:baseline; justify-content:space-between; gap:14px; margin-bottom:14px; }
.kr-section-head h3{ font-family:'Anton', sans-serif !important; font-size:22px !important;
  font-weight:400 !important; letter-spacing:.3px; margin:0 !important; background:none !important;
  color:var(--ink) !important; padding:0 !important; display:inline !important; }
.kr-section-head .tag{ font-family:'Oswald'; font-weight:600; font-size:10.5px; letter-spacing:.6px;
  text-transform:uppercase; color:var(--purple); }
.contract-grid{ display:grid; grid-template-columns:repeat(2,1fr); gap:12px; }
.ccard{ border:1px solid var(--line); border-radius:10px; padding:14px 16px 15px; position:relative;
  background:var(--panel2); overflow:hidden; transition:border-color .15s; }
.ccard:hover{ border-color:rgba(255,255,255,.22); }
/* left accent = position, so a grid of cards reads by color at a glance */
.ccard::before{ content:""; position:absolute; left:0; top:0; bottom:0; width:4px; background:var(--muted); }
.ccard.pos-QB::before{ background:var(--amber); }
.ccard.pos-RB::before{ background:var(--teal); }
.ccard.pos-WR::before{ background:var(--cyan); }
.ccard.pos-TE::before{ background:var(--accent); }
/* tier still reads via a corner ring + dimming, independent of position color */
.ccard.wall{ box-shadow:inset 0 0 0 1px rgba(255,92,108,.5); }
.ccard.ineligible{ opacity:.55; }
.ccard-top{ display:flex; justify-content:space-between; align-items:flex-start; gap:10px; }
.ccard h4{ font-family:'Anton'; font-weight:400; font-size:18px; color:var(--ink); margin:0;
  letter-spacing:.2px; line-height:1.15; }
.ccard .pos{ font-size:11px; color:var(--muted); margin-top:1px; }
.ccard .cost{ text-align:right; }
.ccard .cost b{ font-family:'Anton'; font-size:18px; color:var(--accent); display:block; line-height:1; font-weight:400; }
.ccard .cost small{ font-size:9px; color:var(--muted); text-transform:uppercase; letter-spacing:.5px; }
.pips{ display:flex; gap:4px; margin:8px 0 7px; }
.pip{ width:15px; height:6px; border-radius:3px; background:rgba(255,255,255,.12); }
.pip.on{ background:var(--accent); }
.badges{ display:flex; gap:6px; flex-wrap:wrap; margin-bottom:6px; }
.badge{ font-family:'Oswald'; font-weight:600; font-size:9.5px; letter-spacing:.3px; text-transform:uppercase;
  padding:3px 7px; border-radius:999px; border:1px solid var(--line); color:var(--muted); background:var(--panel2); }
.badge.rookie{ background:rgba(143,123,255,.15); border-color:rgba(143,123,255,.35); color:var(--purple); }
.badge.surplus-pos{ background:rgba(47,224,196,.14); border-color:rgba(47,224,196,.35); color:var(--teal); }
.badge.surplus-neg{ background:rgba(255,107,125,.14); border-color:rgba(255,107,125,.35); color:var(--red); }
.ccard .note{ font-size:11.5px; color:var(--muted); margin-top:1px; }

/* lottery weighted-odds bar rows */
.lottery-rows{ display:flex; flex-direction:column; gap:10px; }
.lottery-row{ display:flex; align-items:center; gap:14px; }
.lottery-row-label{ flex:0 0 200px; min-width:0; }
.lottery-row-label b{ display:block; font-size:13.5px; color:var(--ink); }
.lottery-row-sub{ display:block; font-size:10.5px; color:var(--muted); text-transform:uppercase; letter-spacing:.3px; }
.lottery-row-bar{ flex:1; display:flex; align-items:center; gap:10px; min-width:0; }
.lottery-bar-track{ flex:1; height:22px; border-radius:6px; background:var(--panel2);
  border:1px solid var(--line); overflow:hidden; position:relative; }
.lottery-bar-fill{ height:100%; border-radius:5px; background:var(--grad);
  display:flex; align-items:center; justify-content:flex-end; padding-right:8px;
  font-family:var(--mono, monospace); font-size:11.5px; font-weight:700; color:var(--accent-ink); white-space:nowrap; }
.lottery-bar-fill.dim{ background:var(--muted); }
.lottery-row-val{ flex:0 0 34px; text-align:right; font-family:'Anton'; font-weight:400;
  font-size:14px; color:var(--ink); }

/* draft board — flat, hairline cell dividers; only cells that mean
   something (traded/kept/conflict) carry a background */
table.dboard{ width:100%; border-collapse:collapse; table-layout:fixed; font-family:'Oswald'; font-size:12px; }
table.dboard th{ color:var(--muted); text-align:center; font-size:11px; padding:5px;
  border-bottom:1px solid var(--line); text-transform:uppercase; letter-spacing:.5px; }
.dbcell{ border:1px solid var(--line); padding:3px 4px; vertical-align:top; height:48px; }
/* higher specificity so our padding beats Streamlit's default table td padding */
table.dboard td.dbcell{ padding:3px 4px; }
.dbpick{ color:var(--muted); font-size:9px; white-space:nowrap; }
.db-base{ background:none; color:var(--muted); }
.db-traded{ background:rgba(79,157,255,.16); color:#bcd7ff; }
.db-keep{ background:rgba(63,214,124,.16); color:#a4f0bf; box-shadow:inset 0 0 0 1px rgba(63,214,124,.45); }
.db-conflict{ background:rgba(255,92,108,.16); color:#ffb3ba; box-shadow:inset 0 0 0 1px rgba(255,92,108,.45); }
.db-rd{ background:none; color:var(--purple); font-family:'Anton'; text-align:center; white-space:nowrap; }

.lb .pos{ white-space:nowrap; }

/* top bar — logo + phase chip; section nav lives in the fixed bottom bar */
.kbar{ display:flex; align-items:center; justify-content:space-between; gap:28px; flex-wrap:wrap;
  padding-bottom:14px; margin-bottom:18px; border-bottom:1px solid var(--line); }
.khome{ text-decoration:none !important; line-height:1; }
.khome .neon-logo{ font-size:30px; margin:0; }

/* compact liquid-wave phase indicator, top-right, persistent on every page */
.topbar-chip{ background:var(--panel2); border:1px solid var(--line); border-radius:999px;
  padding:6px 16px 6px 6px; }
.topbar-chip .liquid-stat{ gap:10px; }
.topbar-chip .liq-ring{ margin-bottom:0; }
.topbar-chip .txt .lbl{ font-size:11.5px; font-weight:600; letter-spacing:.4px; color:var(--ink); }
.topbar-chip .txt .sub{ font-size:9.5px; color:var(--muted); margin-top:1px; max-width:none; }
@media (max-width: 640px){
  .topbar-chip .txt .sub{ display:none; }
}

/* fixed bottom bar — floating pill segmented control, the site's only nav.
   Leave room for it at the foot of the page so content never sits under it. */
[data-testid="stAppViewContainer"] .block-container{ padding-bottom:112px !important; }
.bottom-bar-wrap{ position:fixed; left:0; right:0; bottom:18px; display:flex;
  justify-content:center; z-index:1000; pointer-events:none; }
.bottom-bar{ pointer-events:auto; display:flex; gap:2px; background:rgba(18,18,22,.94);
  backdrop-filter:blur(16px); border:1px solid var(--line); border-radius:999px;
  padding:8px; box-shadow:0 12px 36px rgba(0,0,0,.5); }
.navlink, [data-testid="stMarkdownContainer"] a.navlink{
  font-family:'Oswald'; font-weight:600; letter-spacing:.5px; font-size:14px;
  text-transform:uppercase; color:var(--ink) !important; text-decoration:none !important;
  background:none; border:none !important; border-image:none !important; border-radius:999px !important;
  white-space:nowrap; opacity:.6; padding:13px 24px !important; transition:opacity .2s, background .25s ease; }
.navlink:hover{ opacity:.85; }
.navlink.active{ opacity:1; background:var(--grad) !important; color:#fff !important; }

/* bottom-bar popover — Pre-Season / League drill down into their sub-pages
   from a sheet anchored above the bar, instead of jumping straight to the
   page and landing at the top of a long nested-tabs stack. */
.bb-scrim{ position:fixed; inset:0; background:rgba(0,0,0,0); pointer-events:none;
  transition:background .25s; z-index:998; }
.bb-scrim.on{ background:rgba(0,0,0,.45); pointer-events:auto; }
.bb-pop{ position:fixed; left:50%; bottom:90px; transform:translate(-50%,10px) scale(.96);
  width:min(340px, calc(100% - 32px)); background:var(--panel2); border:1px solid var(--line);
  border-radius:16px; padding:8px; box-shadow:0 16px 44px rgba(0,0,0,.55); opacity:0;
  pointer-events:none; transition:opacity .2s ease, transform .2s ease; z-index:999; }
.bb-pop.on{ opacity:1; pointer-events:auto; transform:translate(-50%,0) scale(1); }
.bb-pop-panel{ display:none; }
.bb-pop-panel.on{ display:block; }
.bb-pop-head{ display:flex; align-items:center; gap:8px; padding:8px 10px 10px; }
.bb-pop-back{ font-size:11px; color:var(--muted); cursor:pointer; }
.bb-pop-back:hover{ color:var(--ink); }
.bb-pop-title{ font-family:'Anton', sans-serif; font-size:12px; text-transform:uppercase;
  letter-spacing:.5px; color:var(--muted); }
.bb-pop-item{ display:flex; align-items:center; justify-content:space-between; padding:12px 12px;
  border-radius:10px; font-size:13.5px; font-weight:600; color:var(--ink) !important;
  text-decoration:none !important; cursor:pointer; transition:background .15s; }
.bb-pop-item:hover{ background:rgba(255,255,255,.05); }
.bb-pop-item .chev{ color:var(--muted); font-size:11px; }
.bb-pop-item.leaf-active{ background:linear-gradient(90deg, rgba(255,90,160,.16), rgba(160,107,255,.12)); }
.bb-pop-item.leaf-active .lbl{ background:var(--grad); -webkit-background-clip:text;
  background-clip:text; -webkit-text-fill-color:transparent; }

/* ---------------- mobile ---------------- */
@media (max-width: 640px){
  /* hide Streamlit's own in-app chrome (toolbar/hamburger) on mobile —
     the bottom bar is the site's only nav there and this stuff just eats
     space over it. */
  [data-testid="stToolbar"], [data-testid="stDecoration"],
  [data-testid="stStatusWidget"], [data-testid="stAppDeployButton"],
  #MainMenu, footer{ display:none !important; }
  .neon-logo{ font-size:40px !important; }
  .neon-tag{ font-size:8px; letter-spacing:3px; }
  [data-testid="stAppViewContainer"] .block-container{ padding-bottom:108px !important; }
  .bottom-bar-wrap{ bottom:10px; }
  .bottom-bar{ gap:0; padding:6px; }
  .khome .neon-logo{ font-size:24px !important; }
  .navlink{ font-size:14px; padding:14px 16px !important; letter-spacing:.3px; }
  h1{ font-size:1.5rem !important; }
  h2{ font-size:1.25rem !important; }
  h3{ font-size:1.15rem !important; }
  .block-container{ padding-left:.6rem !important; padding-right:.6rem !important; padding-top:2.5rem !important; }
  /* flow the tall scroll panels with the page (no nested scrollbox) */
  .neonwrap{ max-height:none !important; }

  /* compact custom tables */
  table.lb{ font-size:11px; }
  table.lb th{ padding:5px 5px; font-size:8px; }
  table.lb td{ padding:4px 5px; }
  .hs{ width:22px; height:22px; margin-right:5px; }
  .lb .rk{ width:20px; }
  .lb .kept-badge, .lb .rk-badge{ font-size:8px; padding:1px 4px; margin-left:3px; }
  /* value board: drop Keep Yr (5) + ADP (7) so the essentials fit without scroll */
  .lb-value th:nth-child(5), .lb-value td:nth-child(5),
  .lb-value th:nth-child(7), .lb-value td:nth-child(7){ display:none; }
  /* rookies: drop the redundant Consensus ADP column (6) */
  .lb-rook th:nth-child(6), .lb-rook td:nth-child(6){ display:none; }
  /* title odds: drop Top Keepers (8) so the line fits without tall rows */
  .lb-odds th:nth-child(8), .lb-odds td:nth-child(8){ display:none; }

  /* team line-cards: single column */
  .kcards{ grid-template-columns:1fr; gap:10px; }
  .kcard h4{ font-size:13px; }
  .kcard .kp{ font-size:12px; padding:7px 12px; }

  /* contract cards: single column */
  .contract-grid{ grid-template-columns:1fr; }

  /* lottery bar rows: stack label above bar */
  .lottery-row{ flex-wrap:wrap; }
  .lottery-row-label{ flex:1 1 100%; }
  .lottery-row-bar{ flex:1 1 100%; }

  /* draft board: tiny + horizontal scroll */
  table.dboard{ font-size:9px; }
  table.dboard th{ padding:3px 2px; font-size:8px; }
  .dbcell{ height:auto; }
  table.dboard td.dbcell{ padding:2px 3px; }   /* win over Streamlit's td padding */
  .db-rd{ font-size:10px; }                      /* keep two-digit rounds legible */
}
</style>
"""


def headshot(pid: str) -> str:
    return SLEEPER_IMG.format(pid=pid)


def img_tag(pid: str, cls: str = "hs") -> str:
    """Headshot <img>. Source is picked server-side because Streamlit's HTML
    sanitizer strips `onerror`, so an in-browser fallback chain can't run.

    ESPN's headshots cover both veterans and incoming rookies (where Sleeper's
    CDN often has no photo), so we use ESPN whenever we have an id for the
    player and fall back to the Sleeper thumb otherwise.
    """
    eid = _ESPN_BY_PID.get(str(pid))
    src = ESPN_IMG.format(eid=eid) if eid else headshot(pid)
    return f'<img class="{cls}" src="{src}" loading="lazy">'


# Three hard-hat pigs (Brandon's photo) inside the red construction badge.
def _pig_svg(cx: float, cy: float, s: float, hat: str) -> str:
    r = 15 * s
    skin, edge, snout, dark = "#f7b8c6", "#c97b8c", "#f29bb0", "#7a3a4a"
    hy = cy - r * 0.72                       # hat seam height
    lx, rx, ly = cx - r * 0.9, cx + r * 0.9, hy + r * 0.12
    return (
        # ears (behind head)
        f'<path d="M{cx-r*0.72:.1f} {cy-r*0.55:.1f} l{-5*s:.1f} {-11*s:.1f} '
        f'l{11*s:.1f} {3*s:.1f} z" fill="{skin}" stroke="{edge}" stroke-width="{1.1*s:.2f}"/>'
        f'<path d="M{cx+r*0.72:.1f} {cy-r*0.55:.1f} l{5*s:.1f} {-11*s:.1f} '
        f'l{-11*s:.1f} {3*s:.1f} z" fill="{skin}" stroke="{edge}" stroke-width="{1.1*s:.2f}"/>'
        # head
        f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{r:.1f}" ry="{r*0.92:.1f}" '
        f'fill="{skin}" stroke="{edge}" stroke-width="{1.2*s:.2f}"/>'
        # snout + nostrils
        f'<ellipse cx="{cx:.1f}" cy="{cy+r*0.34:.1f}" rx="{r*0.52:.1f}" ry="{r*0.38:.1f}" '
        f'fill="{snout}" stroke="{edge}" stroke-width="{1*s:.2f}"/>'
        f'<ellipse cx="{cx-r*0.17:.1f}" cy="{cy+r*0.34:.1f}" rx="{r*0.08:.1f}" ry="{r*0.11:.1f}" fill="{dark}"/>'
        f'<ellipse cx="{cx+r*0.17:.1f}" cy="{cy+r*0.34:.1f}" rx="{r*0.08:.1f}" ry="{r*0.11:.1f}" fill="{dark}"/>'
        # eyes
        f'<circle cx="{cx-r*0.38:.1f}" cy="{cy-r*0.12:.1f}" r="{r*0.1:.2f}" fill="#3a2226"/>'
        f'<circle cx="{cx+r*0.38:.1f}" cy="{cy-r*0.12:.1f}" r="{r*0.1:.2f}" fill="#3a2226"/>'
        # hard hat: dome, brim, ridge
        f'<path d="M{lx:.1f} {ly:.1f} C {lx:.1f} {hy-r*0.78:.1f} {rx:.1f} {hy-r*0.78:.1f} '
        f'{rx:.1f} {ly:.1f} Z" fill="{hat}" stroke="#0d1830" stroke-width="{1.1*s:.2f}"/>'
        f'<ellipse cx="{cx:.1f}" cy="{ly:.1f}" rx="{r*1.12:.1f}" ry="{r*0.22:.1f}" '
        f'fill="{hat}" stroke="#0d1830" stroke-width="{1.1*s:.2f}"/>'
        f'<path d="M{cx:.1f} {hy-r*0.62:.1f} L{cx:.1f} {ly:.1f}" stroke="#0d1830" '
        f'stroke-width="{0.8*s:.2f}" opacity="0.45"/>'
    )


def _wave_d(amp: float, phase: float, second: float = 0.45) -> str:
    """One seamless wave surface as an SVG path, in local coords where y=0 is
    the still surface and +y is down. Two sine components at 200 and 100
    units — both divide the 200-unit loop distance exactly, so translating
    the path by -200 lands it back on itself with no visible seam."""
    pts = []
    x = -200.0
    while x <= 400.0:
        y = (amp * math.sin(2 * math.pi * x / 200.0 + phase)
             + amp * second * math.sin(2 * math.pi * x / 100.0 - phase * 1.7))
        pts.append("%.1f,%.2f" % (x, y))
        x += 8.0
    return "M " + " L ".join(pts) + " L 400,420 L -200,420 Z"


_WAVE_FRONT = _wave_d(6.5, 0.0)
_WAVE_BACK = _wave_d(4.8, 2.1, second=0.3)

_HAT_Y, _HAT_B = "#f4c20d", "#2f80d8"

# Fill level for the logo's liquid backdrop (0-1, fraction of the inner
# circle's diameter). Kept shallow so the pigs read as swimming, not
# submerged — the wave's whole point is to be visible above their heads.
_LOGO_FILL = 0.32


def _logo_liquid_layer() -> str:
    """The animated wave-fill sitting behind the three pigs, mapped from the
    same 200x200 wave-design space used everywhere else into the emblem's
    96x96 inner-circle box."""
    p = max(0.10, min(0.90, _LOGO_FILL))
    surface = 200.0 - 200.0 * p
    k = 96.0 / 200.0
    return (
        f'<g transform="translate(12,12) scale({k:.4f})">'
        f'<g class="bob" style="--sy:{surface:.1f}px">'
        f'<path class="wv back" d="{_WAVE_BACK}" fill="#4f9dff" opacity=".4"/>'
        f'<path class="wv front" d="{_WAVE_FRONT}" fill="url(#tcLiquid)"/>'
        f'</g></g>'
    )


_TC_EMBLEM = (
    '<svg class="tc-emblem" viewBox="0 0 120 120" style="width:{w}px;height:{w}px;" '
    'aria-hidden="true">'
    '<defs>'
    '<radialGradient id="tcDisc" cx="0.5" cy="0.4" r="0.75">'
    '<stop offset="0" stop-color="#ff4438"/><stop offset=".7" stop-color="#c1121f"/>'
    '<stop offset="1" stop-color="#5e0a10"/></radialGradient>'
    '<clipPath id="tcInner"><circle cx="60" cy="60" r="46"/></clipPath>'
    '<linearGradient id="tcLiquid" x1="0" y1="0" x2="0.3" y2="1">'
    '<stop offset="0" stop-color="#4f9dff" stop-opacity=".95"/>'
    '<stop offset="1" stop-color="#4f9dff" stop-opacity=".55"/>'
    '</linearGradient>'
    '</defs>'
    '<circle cx="60" cy="60" r="56" fill="url(#tcDisc)" stroke="#3a0608" stroke-width="3"/>'
    '<g clip-path="url(#tcInner)">'
    '<rect x="12" y="12" width="96" height="96" fill="#050b16"/>'   # night sky, not the old cel sky
    + _logo_liquid_layer()                # animated liquid the pigs swim in
    + _pig_svg(38, 70, 0.86, _HAT_Y)      # left pig — yellow hat
    + _pig_svg(82, 70, 0.86, _HAT_B)      # right pig — blue hat
    + _pig_svg(60, 76, 1.02, _HAT_Y)      # middle pig — yellow hat (front)
    + '</g></svg>'
)


def logo_html(size: int = 52, tag: str | None = "The Keeper Hub") -> str:
    t = f'<div class="neon-tag">{tag}</div>' if tag else ""
    letters = "".join(f'<span class="kl">{ch}</span>' for ch in "KREEPER")
    em = int(round(size * 1.5))
    emblem = _TC_EMBLEM.format(w=em)
    return (f'<div class="tc-wrap">{emblem}'
            f'<div class="neon-logo" style="font-size:{size}px;">{letters}</div></div>{t}')


_liq_uid_counter = 0


def liquid_ring_html(pct: float, value_html: str, label: str = "", size: int = 84,
                      accent: str = "#4f9dff") -> str:
    """A small animated liquid-wave-fill circle gauge (same wave asset as the
    logo), with an HTML value overlaid in the middle. `pct` in [0,1]."""
    global _liq_uid_counter
    _liq_uid_counter += 1
    uid = f"liq{_liq_uid_counter}"
    p = max(0.06, min(0.94, pct))
    surface = 200.0 - 200.0 * p
    inner = size - 8
    k = inner / 200.0
    off = (size - inner) / 2
    cx = cy = size / 2
    sub = f"<small>{label}</small>" if label else ""
    return (
        f'<span class="liq-ring" style="width:{size}px;height:{size}px;">'
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" aria-hidden="true">'
        f'<circle cx="{cx}" cy="{cy}" r="{(size-3)/2:.1f}" fill="none" '
        f'stroke="rgba(255,255,255,.12)" stroke-width="1.5"/>'
        f'<defs><clipPath id="{uid}"><circle cx="{cx}" cy="{cy}" r="{inner/2:.1f}"/></clipPath></defs>'
        f'<g clip-path="url(#{uid})">'
        f'<g transform="translate({off:.1f},{off:.1f}) scale({k:.4f})">'
        f'<g class="bob" style="--sy:{surface:.1f}px">'
        f'<path class="wv back" d="{_WAVE_BACK}" fill="{accent}" opacity=".45"/>'
        f'<path class="wv front" d="{_WAVE_FRONT}" fill="{accent}" opacity=".85"/>'
        f'</g></g></g></svg>'
        f'<span class="liq-val"><b>{value_html}</b>{sub}</span>'
        f'</span>'
    )


def liquid_stat_html(pct: float, value_html: str, ring_label: str, label: str, sub: str = "",
                      size: int = 84, accent: str = "#4f9dff") -> str:
    """A quick-glance stat: a liquid ring next to a label/sub text block."""
    ring = liquid_ring_html(pct, value_html, ring_label, size=size, accent=accent)
    return (f'<div class="liquid-stat">{ring}'
            f'<div class="txt"><div class="lbl">{label}</div>'
            + (f'<div class="sub">{sub}</div>' if sub else '') + '</div></div>')


def inject(st) -> None:
    st.markdown(CSS, unsafe_allow_html=True)
