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

# Per-page accent gradient (g1 -> g2 -> g3). g2 is also used as the flat
# "--accent" for solid fills (buttons, active nav, bar fills) — every g2
# below is bright/light enough to stay readable under the fixed dark ink.
# This is the one thing that changes page to page; everything else (type,
# panel radius, semantic colors) stays constant so the app still reads as
# one product, just with each section given its own identity.
_PAGE_ACCENT = {
    "home":    ("#ff5aa0", "#a06bff", "#4f9dff"),
    "keepers": ("#a06bff", "#c9a6ff", "#a06bff"),
    "draft":   ("#4f9dff", "#3fd67c", "#4f9dff"),
    "trades":  ("#ff5aa0", "#ff8fc0", "#ff5aa0"),
    "league":  ("#3fd67c", "#4f9dff", "#3fd67c"),
    "players": ("#cfcfd6", "#e9e9ee", "#cfcfd6"),
}

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

/* near-black field with a soft pink/blue glow, like a dashboard product shot */
.stApp{
  background:
    radial-gradient(46% 34% at 14% 6%, rgba(255,90,160,.09), transparent 60%),
    radial-gradient(40% 34% at 86% 4%, rgba(79,157,255,.09), transparent 60%),
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

/* headings — h2 carries the page's gradient as text color, not a filled bar */
h1{ font-family:'Anton', sans-serif !important; letter-spacing:1px; text-transform:uppercase;
  color:var(--ink) !important; }
h2{ font-family:'Anton', sans-serif !important; letter-spacing:.4px; margin:0 0 8px !important;
  font-size:1.5rem !important; background:var(--grad) !important; -webkit-background-clip:text !important;
  background-clip:text !important; -webkit-text-fill-color:transparent !important; }
h3{ font-family:'Oswald', sans-serif !important; font-weight:600 !important; letter-spacing:.2px;
  color:var(--ink) !important; font-size:1.05rem !important; margin:0 0 10px !important; }

/* ThunderCats wordmark — liquid-chrome steel letters + red-disc pig emblem */
.tc-wrap{ display:inline-flex; align-items:center; gap:8px; }
.tc-emblem{ flex:0 0 auto; filter:drop-shadow(0 4px 16px rgba(79,157,255,.35)); }
.tc-emblem .bob{ transform:translateY(var(--sy,0px)); }
.tc-emblem .wv.front{ animation:liq-front 7s linear infinite; }
.tc-emblem .wv.back{ animation:liq-back 11s linear infinite; }
@keyframes liq-front{ from{transform:translateX(0)} to{transform:translateX(-200px)} }
@keyframes liq-back{ from{transform:translateX(0)} to{transform:translateX(200px)} }
@media (prefers-reduced-motion: reduce){
  .tc-emblem .wv.front, .tc-emblem .wv.back{ animation:none !important; }
}
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
[data-testid="stTabs"] button[aria-selected="true"]{ color:var(--accent) !important; }
[data-testid="stTabs"] button[aria-selected="true"] p{ color:var(--accent) !important; }
[data-testid="stTabs"] [data-baseweb="tab-highlight"]{ background-color:var(--accent) !important; }

/* sidebar nav radio -> flat pills */
[data-testid="stSidebar"] [role="radiogroup"] label{ border:1px solid var(--line); border-radius:6px;
  padding:6px 10px; margin-bottom:6px; background:var(--panel); transition:.15s; }
[data-testid="stSidebar"] [role="radiogroup"] label:hover{ border-color:var(--accent); }
[data-testid="stSidebar"] [role="radiogroup"] label p{ font-weight:600; text-transform:uppercase; letter-spacing:.5px; font-size:13px;}

.stButton>button{ font-family:'Anton'; letter-spacing:1px; text-transform:uppercase;
  background:var(--accent); color:var(--accent-ink); border:none; border-radius:4px; }
.stButton>button:hover{ background:var(--purple); color:#fff; }

/* ---- shared custom tables ---- */
.neonwrap{ overflow-x:auto; border:1px solid var(--line); border-radius:10px; background:var(--panel); }
table.lb{ width:100%; border-collapse:collapse; font-family:'Oswald'; font-size:14px; }
table.lb th{ background:var(--panel2); color:var(--muted); text-transform:uppercase; letter-spacing:1px;
  font-size:11px; text-align:left; padding:8px 10px; border-bottom:2px solid var(--line); position:sticky; top:0; }
table.lb td{ padding:6px 10px; border-bottom:1px solid var(--line); }
table.lb tr:hover td{ background:var(--panel2); }
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

/* FAAB debt ring — a CSS conic-gradient donut, no chart library needed */
.faab-grid{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; }
.faab-card{ border:1px solid var(--line); border-radius:10px; background:var(--panel);
  padding:12px; text-align:center; }
.faab-card h4{ font-family:'Anton'; font-size:14px; margin:0 0 8px; color:var(--purple); }
.faab-ring{ width:84px; height:84px; border-radius:50%; margin:0 auto 8px;
  display:flex; align-items:center; justify-content:center; }
.faab-ring-hole{ width:64px; height:64px; border-radius:50%; background:var(--bg);
  display:flex; flex-direction:column; align-items:center; justify-content:center; }
.faab-ring-hole b{ font-family:'Anton'; font-size:16px; color:var(--accent); line-height:1; }
.faab-ring-hole small{ font-size:9px; color:var(--muted); text-transform:uppercase; letter-spacing:.5px; }
.faab-card .rem{ font-size:11px; color:var(--muted); margin-top:2px; }
.faab-pot{ text-align:center; padding:18px 12px; border-radius:12px; border:1px solid transparent;
  background:linear-gradient(var(--panel2),var(--panel2)) padding-box, var(--grad) border-box;
  margin-bottom:16px; }
.faab-pot b{ font-family:'Anton'; font-size:38px; background:var(--grad); -webkit-background-clip:text;
  background-clip:text; -webkit-text-fill-color:transparent; display:block; line-height:1; }
.faab-pot span{ font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:1px; }
.burnbar-track{ width:100%; height:8px; border-radius:5px; background:var(--bg); overflow:hidden; }
.burnbar-fill{ height:100%; border-radius:5px; }

/* contract cards — per-player keeper economics browse grid */
.kr-section{ border:1px solid var(--line); border-radius:14px; background:var(--panel);
  padding:16px 18px 18px; margin-bottom:16px; }
.kr-section-head{ display:flex; align-items:baseline; justify-content:space-between; gap:14px; margin-bottom:10px; }
.kr-section-head h3{ font-size:16px; margin:0 !important; background:none !important; color:var(--ink) !important;
  padding:0 !important; display:inline !important; }
.kr-section-head .tag{ font-family:'Oswald'; font-weight:600; font-size:10.5px; letter-spacing:.6px;
  text-transform:uppercase; color:var(--purple); }
.contract-grid{ display:grid; grid-template-columns:repeat(2,1fr); gap:12px; }
.ccard{ border:1px solid var(--line); border-radius:10px; padding:12px 14px 13px; position:relative;
  background:var(--panel2); overflow:hidden; }
.ccard::before{ content:""; position:absolute; left:0; top:0; bottom:0; width:4px; background:var(--accent); }
.ccard.rookie::before{ background:var(--purple); }
.ccard.wall::before{ background:var(--red); }
.ccard.ineligible::before{ background:var(--muted); }
.ccard-top{ display:flex; justify-content:space-between; align-items:flex-start; gap:10px; }
.ccard h4{ font-family:'Anton'; font-weight:400; font-size:14px; color:var(--ink); margin:0; letter-spacing:.3px; }
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
.lottery-bar-fill{ height:100%; border-radius:5px; background:var(--accent);
  display:flex; align-items:center; justify-content:flex-end; padding-right:8px;
  font-family:var(--mono, monospace); font-size:11.5px; font-weight:700; color:var(--accent-ink); white-space:nowrap; }
.lottery-bar-fill.dim{ background:var(--muted); }
.lottery-row-val{ flex:0 0 34px; text-align:right; font-family:'Anton'; font-weight:400;
  font-size:14px; color:var(--ink); }

/* draft board */
table.dboard{ width:100%; border-collapse:collapse; table-layout:fixed; font-family:'Oswald'; font-size:12px; }
table.dboard th{ background:var(--panel2); color:var(--ink); text-align:center; font-size:11px; padding:5px;
  border:1px solid var(--line); text-transform:uppercase; letter-spacing:.5px; }
.dbcell{ border:1px solid var(--line); padding:3px 4px; vertical-align:top; height:48px; }
/* higher specificity so our padding beats Streamlit's default table td padding */
table.dboard td.dbcell{ padding:3px 4px; }
.dbpick{ color:var(--muted); font-size:9px; white-space:nowrap; }
.db-base{ background:var(--panel); color:var(--muted); }
.db-traded{ background:rgba(79,157,255,.16); color:#bcd7ff; }
.db-keep{ background:rgba(63,214,124,.16); color:#a4f0bf; box-shadow:inset 0 0 0 1px rgba(63,214,124,.45); }
.db-conflict{ background:rgba(255,92,108,.16); color:#ffb3ba; box-shadow:inset 0 0 0 1px rgba(255,92,108,.45); }
.db-rd{ background:var(--panel2); color:var(--purple); font-family:'Anton'; text-align:center; white-space:nowrap; }

.lb .pos{ white-space:nowrap; }

/* top navigation bar — plain uppercase links, gradient underline on the
   active section (matches the sub-nav treatment from the gradient-glass mock) */
.kbar{ display:flex; align-items:center; gap:28px; flex-wrap:wrap;
  padding-bottom:0; margin-bottom:18px; border-bottom:1px solid var(--line); }
.khome{ text-decoration:none !important; line-height:1; }
.khome .neon-logo{ font-size:30px; margin:0; }
.topnav{ display:flex; gap:26px; flex-wrap:wrap; align-self:stretch; align-items:center; }
.navlink{ font-family:'Oswald'; font-weight:600; letter-spacing:.8px; font-size:12.5px;
  text-transform:uppercase; color:var(--muted) !important; text-decoration:none !important;
  background:none; border:none; border-radius:0; white-space:nowrap;
  padding:8px 0 13px; border-bottom:2px solid transparent; transition:color .15s; }
.navlink:hover{ color:var(--ink) !important; }
.navlink.active{ color:var(--ink) !important; border-bottom:2px solid; border-image:var(--grad) 1; }

/* ---------------- mobile ---------------- */
@media (max-width: 640px){
  .neon-logo{ font-size:40px !important; }
  .neon-tag{ font-size:8px; letter-spacing:3px; }
  .kbar{ gap:14px; }
  .topnav{ gap:14px; }
  .khome .neon-logo{ font-size:24px !important; }
  .navlink{ font-size:11px; padding:6px 0 10px; letter-spacing:.4px; }
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


def inject(st, page: str = "home") -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    g1, g2, g3 = _PAGE_ACCENT.get(page, _PAGE_ACCENT["home"])
    st.markdown(f"<style>:root{{ --g1:{g1}; --g2:{g2}; --g3:{g3}; }}</style>", unsafe_allow_html=True)
