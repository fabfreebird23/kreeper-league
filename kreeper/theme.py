"""Retro pastel-synthwave theme: graffiti wordmark, soft neon grid + glows on a
light lavender/sunset field, light panels with dark text, plus shared CSS for the
custom HTML surfaces (leaderboard, team cards, draft board) and Sleeper headshots.
"""
from __future__ import annotations

import base64
import pathlib

_ASSETS = pathlib.Path(__file__).resolve().parent.parent / "assets"


def _b64(path: pathlib.Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


# Classic basketball sneaker (one colorway per section), embedded as base64
_SNEAKERS = {
    k: _b64(_ASSETS / f"sneaker_{k}.png")
    for k in ("top", "board", "draft", "adp", "keepers", "rookies")
}

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

# Pastel palette
PINK = "#ff4f9d"
PURPLE = "#7b5cff"
TEAL = "#16b8a6"
CYAN = "#2bb5e8"
AMBER = "#f5a524"
RED = "#e5484d"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Anton&family=Oswald:wght@400;500;600;700&family=Rubik+Wet+Paint&display=swap');

:root{
  --bg:#f4f0fb; --panel:#ffffff; --panel2:#f7f3fe;
  --pink:#ff4f9d; --purple:#7b5cff; --teal:#16b8a6; --cyan:#2bb5e8; --amber:#f5a524; --red:#e5484d;
  --ink:#2b2540; --muted:#8a83a6; --line:#e4ddf2;
}

/* warm pastel sunset-synthwave field */
.stApp{
  background-color:#fbf3ec;
  background-image:
    radial-gradient(74% 56% at 3% -8%, rgba(255,116,134,.30), transparent 58%),
    radial-gradient(70% 52% at 105% -6%, rgba(54,196,206,.26), transparent 58%),
    radial-gradient(72% 40% at 50% 86%, rgba(255,176,92,.24), transparent 66%),
    radial-gradient(130% 130% at 50% 42%, transparent 56%, rgba(150,90,120,.09)),
    linear-gradient(rgba(196,128,120,.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(196,128,120,.06) 1px, transparent 1px),
    linear-gradient(180deg,#fef8f1,#f6eae1);
  background-size:auto,auto,auto,auto,48px 48px,48px 48px,auto;
  background-attachment:fixed;
}
html, body, [class*="css"]{ font-family:'Oswald', sans-serif; color:var(--ink); }

/* faint CRT scanlines */
.stApp::before{ content:""; position:fixed; inset:0; pointer-events:none; z-index:9998;
  background:repeating-linear-gradient(to bottom, transparent 0 2px, rgba(80,60,120,.045) 2px 3px); }
/* soft glowing perspective floor grid, behind content */
.stApp::after{ content:""; position:fixed; left:-25%; right:-25%; bottom:-2vh; height:48vh;
  z-index:-1; pointer-events:none; opacity:.55;
  background-image:
    repeating-linear-gradient(90deg, rgba(255,116,134,.55) 0 1px, transparent 1px 7%),
    repeating-linear-gradient(0deg, rgba(54,196,206,.45) 0 1px, transparent 1px 20%);
  transform:perspective(32vh) rotateX(65deg); transform-origin:bottom center;
  -webkit-mask-image:linear-gradient(to top,#000 4%, transparent 72%);
  mask-image:linear-gradient(to top,#000 4%, transparent 72%);
  filter:drop-shadow(0 0 5px rgba(255,140,120,.35)); }

[data-testid="stHeader"]{ background:transparent; }
[data-testid="stSidebar"]{ background:rgba(255,255,255,.72); backdrop-filter:blur(4px);
  border-right:1px solid var(--line); }

/* headings */
h1,h2,h3{ font-family:'Anton', sans-serif !important; letter-spacing:1px; text-transform:uppercase; }
h1{ color:var(--pink); }
h2{ color:var(--purple); }
h3{ color:var(--ink); }

/* graffiti wordmark — pink with teal retro offset */
/* ThunderCats wordmark — liquid-chrome steel letters + red-disc cat emblem */
.tc-wrap{ display:inline-flex; align-items:center; gap:8px; }
.tc-emblem{ flex:0 0 auto; filter:drop-shadow(1px 2px 3px rgba(8,14,30,.5)); }
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
[data-testid="stTabs"] button[aria-selected="true"]{ color:var(--pink) !important; }
[data-testid="stTabs"] button[aria-selected="true"] p{ color:var(--pink) !important; }
[data-testid="stTabs"] [data-baseweb="tab-highlight"]{ background-color:var(--pink) !important; }

/* sidebar nav radio -> pastel pills */
[data-testid="stSidebar"] [role="radiogroup"] label{ border:1px solid var(--line); border-radius:6px;
  padding:6px 10px; margin-bottom:6px; background:#fff; transition:.15s; }
[data-testid="stSidebar"] [role="radiogroup"] label:hover{ border-color:var(--pink); }
[data-testid="stSidebar"] [role="radiogroup"] label p{ font-weight:600; text-transform:uppercase; letter-spacing:.5px; font-size:13px;}

.stButton>button{ font-family:'Anton'; letter-spacing:1px; text-transform:uppercase;
  background:var(--pink); color:#fff; border:none; border-radius:4px; }
.stButton>button:hover{ background:var(--purple); color:#fff; }

/* ---- shared custom tables ---- */
.neonwrap{ overflow-x:auto; border:1px solid var(--line); border-radius:10px;
  background:rgba(255,255,255,.78); backdrop-filter:blur(2px);
  box-shadow:0 10px 30px rgba(123,92,255,.12), 0 0 0 1px rgba(255,79,157,.06); }
table.lb{ width:100%; border-collapse:collapse; font-family:'Oswald'; font-size:14px; }
table.lb th{ background:#f1ebfb; color:var(--muted); text-transform:uppercase; letter-spacing:1px;
  font-size:11px; text-align:left; padding:8px 10px; border-bottom:2px solid var(--line); position:sticky; top:0; }
table.lb td{ padding:6px 10px; border-bottom:1px solid #efeaf8; }
table.lb tr:hover td{ background:#faf7ff; }
table.lb tr.kept td{ background:linear-gradient(90deg, rgba(22,184,166,.18), rgba(22,184,166,.04)); }
table.lb tr.kept td:first-child{ box-shadow:inset 3px 0 0 var(--teal); }
.lb .rk{ font-family:'Anton'; color:var(--pink); width:34px; text-align:center; }
.lb .pl{ font-weight:600; }
.lb .pos{ color:var(--muted); font-size:11px; font-weight:600; }
.lb .val{ font-family:'Anton'; color:var(--teal); text-align:right; }
.lb .num{ text-align:right; color:var(--ink); }
.lb .kept-badge{ color:#fff; background:var(--teal); font-weight:700; font-size:10px;
  padding:1px 6px; border-radius:3px; text-transform:uppercase; letter-spacing:.5px; }
.lb .rk-badge{ color:#fff; background:var(--purple); font-weight:700; font-size:10px;
  padding:1px 6px; border-radius:3px; text-transform:uppercase; letter-spacing:.5px; margin-left:4px; }
.lb .fa-tag{ color:var(--cyan); font-weight:600; font-size:12px; font-style:italic; }
table.lb tr.fa td{ background:rgba(43,181,232,.05); }
.hs{ width:30px; height:30px; border-radius:50%; object-fit:cover; vertical-align:middle;
  background:#efeaf8; border:1px solid var(--line); margin-right:8px; }
.posdot{ display:inline-block; width:6px;height:6px;border-radius:50%;margin-right:5px;vertical-align:middle;}
.p-QB{background:var(--amber);} .p-RB{background:var(--teal);} .p-WR{background:var(--cyan);} .p-TE{background:var(--pink);}

/* team cards */
.kcards{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }
.kcard{ border:1px solid var(--line); border-top:3px solid var(--pink); border-radius:10px;
  background:#fff; padding:10px 12px; min-height:96px; box-shadow:0 6px 18px rgba(123,92,255,.10); }
.kcard h4{ font-family:'Anton'; font-size:15px; margin:0 0 6px; color:var(--purple); letter-spacing:.5px; }
.kcard .kp{ display:flex; align-items:center; font-size:13px; padding:2px 0; }
.kcard .kp img{ width:22px;height:22px;border-radius:50%;margin-right:6px;object-fit:cover;background:#efeaf8; }
.kcard .kp .rd{ margin-left:auto; color:var(--teal); font-weight:700; }
.kcard .empty{ color:var(--muted); font-style:italic; font-size:12px; }
.kcard .rk-tag{ color:var(--amber); font-size:9px; font-weight:700; margin-left:4px; }

/* stat tiles row */
.tiles{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:16px; }
.tile{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:12px 14px;
  box-shadow:0 6px 18px rgba(123,92,255,.08); }
.tile .num{ font-family:'Anton'; font-weight:400; font-size:24px; color:var(--ink); line-height:1; }
.tile .num.pink{ color:var(--pink); }
.tile .lbl{ font-size:10px; text-transform:uppercase; letter-spacing:.8px; color:var(--muted); margin-top:5px; }
.tile .sub{ font-size:11px; color:var(--ink); opacity:.75; margin-top:1px; }

/* FAAB debt ring — a CSS conic-gradient donut, no chart library needed */
.faab-grid{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; }
.faab-card{ border:1px solid var(--line); border-radius:10px; background:#fff;
  padding:12px; text-align:center; box-shadow:0 6px 18px rgba(123,92,255,.10); }
.faab-card h4{ font-family:'Anton'; font-size:14px; margin:0 0 8px; color:var(--purple); }
.faab-ring{ width:84px; height:84px; border-radius:50%; margin:0 auto 8px;
  display:flex; align-items:center; justify-content:center; }
.faab-ring-hole{ width:64px; height:64px; border-radius:50%; background:#fff;
  display:flex; flex-direction:column; align-items:center; justify-content:center; }
.faab-ring-hole b{ font-family:'Anton'; font-size:16px; color:var(--pink); line-height:1; }
.faab-ring-hole small{ font-size:9px; color:var(--muted); text-transform:uppercase; letter-spacing:.5px; }
.faab-card .rem{ font-size:11px; color:var(--muted); margin-top:2px; }
.faab-pot{ text-align:center; padding:18px 12px; border-radius:12px;
  background:linear-gradient(135deg, rgba(255,79,157,.10), rgba(43,181,232,.10));
  border:1px solid var(--line); margin-bottom:16px; }
.faab-pot b{ font-family:'Anton'; font-size:38px; color:var(--pink); display:block; line-height:1; }
.faab-pot span{ font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:1px; }
.burnbar-track{ width:100%; height:8px; border-radius:5px; background:#efe9fb; overflow:hidden; }
.burnbar-fill{ height:100%; border-radius:5px; }

/* contract cards — per-player keeper economics browse grid */
.kr-section{ border:1px solid var(--line); border-radius:10px; background:#fff;
  padding:16px 18px 18px; margin-bottom:16px; box-shadow:0 6px 18px rgba(123,92,255,.10); }
.kr-section-head{ display:flex; align-items:baseline; justify-content:space-between; gap:14px; margin-bottom:10px; }
.kr-section-head h3{ font-size:16px; margin:0; }
.kr-section-head .tag{ font-family:'Oswald'; font-weight:600; font-size:10.5px; letter-spacing:.6px;
  text-transform:uppercase; color:var(--purple); }
.contract-grid{ display:grid; grid-template-columns:repeat(2,1fr); gap:12px; }
.ccard{ border:1px solid var(--line); border-radius:10px; padding:12px 14px 13px; position:relative;
  background:var(--panel2); overflow:hidden; }
.ccard::before{ content:""; position:absolute; left:0; top:0; bottom:0; width:4px; background:var(--pink); }
.ccard.rookie::before{ background:var(--purple); }
.ccard.ineligible::before{ background:var(--muted); }
.ccard-top{ display:flex; justify-content:space-between; align-items:flex-start; gap:10px; }
.ccard h4{ font-family:'Anton'; font-weight:400; font-size:14px; color:var(--ink); margin:0; letter-spacing:.3px; }
.ccard .pos{ font-size:11px; color:var(--muted); margin-top:1px; }
.ccard .cost{ text-align:right; }
.ccard .cost b{ font-family:'Anton'; font-size:18px; color:var(--pink); display:block; line-height:1; font-weight:400; }
.ccard .cost small{ font-size:9px; color:var(--muted); text-transform:uppercase; letter-spacing:.5px; }
.pips{ display:flex; gap:4px; margin:8px 0 7px; }
.pip{ width:15px; height:6px; border-radius:3px; background:#e3dcf4; }
.pip.on{ background:var(--pink); }
.badges{ display:flex; gap:6px; flex-wrap:wrap; margin-bottom:6px; }
.badge{ font-family:'Oswald'; font-weight:600; font-size:9.5px; letter-spacing:.3px; text-transform:uppercase;
  padding:3px 7px; border-radius:999px; border:1px solid var(--line); color:var(--muted); background:#fff; }
.badge.rookie{ background:#efeaff; border-color:#dcd2ff; color:var(--purple); }
.badge.surplus-pos{ background:#e3f8f4; border-color:#bfe9e2; color:var(--teal); }
.badge.surplus-neg{ background:#fdeaec; border-color:#f4c7cb; color:var(--red); }
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
.lottery-bar-fill{ height:100%; border-radius:5px; background:var(--pink);
  display:flex; align-items:center; justify-content:flex-end; padding-right:8px;
  font-family:var(--mono, monospace); font-size:11.5px; font-weight:700; color:#fff; white-space:nowrap; }
.lottery-bar-fill.dim{ background:var(--muted); }
.lottery-row-val{ flex:0 0 34px; text-align:right; font-family:'Anton'; font-weight:400;
  font-size:14px; color:var(--ink); }

/* lottery selection-odds stacked bars: pick 1 / pick 2 / 3rd+ */
.lottery-stack{ flex:1; height:22px; border-radius:6px; background:var(--panel2);
  border:1px solid var(--line); overflow:hidden; display:flex; }
.lottery-seg{ height:100%; display:flex; align-items:center; justify-content:center;
  font-size:10.5px; font-weight:700; color:#fff; white-space:nowrap; overflow:hidden; }
.lottery-seg-1{ background:var(--pink); }
.lottery-seg-2{ background:var(--purple); }
.lottery-seg-rest{ flex:1; display:flex; align-items:center; justify-content:center;
  font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.3px; }

/* draft board */
table.dboard{ width:100%; border-collapse:collapse; table-layout:fixed; font-family:'Oswald'; font-size:12px; }
table.dboard th{ background:#f1ebfb; color:var(--ink); text-align:center; font-size:11px; padding:5px;
  border:1px solid var(--line); text-transform:uppercase; letter-spacing:.5px; }
.dbcell{ border:1px solid #efeaf8; padding:3px 4px; vertical-align:top; height:48px; }
/* higher specificity so our padding beats Streamlit's default table td padding */
table.dboard td.dbcell{ padding:3px 4px; }
.dbpick{ color:#b6aecd; font-size:9px; white-space:nowrap; }
.db-base{ background:#faf7ff; color:#9089ab; }
.db-traded{ background:rgba(255,79,157,.16); color:#b21e6b; }
.db-keep{ background:rgba(22,184,166,.20); color:#0c7a6e; box-shadow:inset 0 0 0 1px rgba(22,184,166,.45); }
.db-conflict{ background:rgba(229,72,77,.18); color:#b3232a; box-shadow:inset 0 0 0 1px rgba(229,72,77,.45); }
.db-rd{ background:#f1ebfb; color:var(--purple); font-family:'Anton'; text-align:center; white-space:nowrap; }

/* classic basketball sneaker icon for section headers */
.sneak{ display:inline-block; vertical-align:middle; height:52px; margin:0 14px 6px 0;
  filter:drop-shadow(2px 4px 4px rgba(80,40,70,.32)); }
.lb .pos{ white-space:nowrap; }

/* top navigation bar */
.kbar{ display:flex; align-items:center; gap:16px; flex-wrap:wrap;
  padding-bottom:8px; margin-bottom:10px; border-bottom:1.5px solid var(--line); }
.khome{ text-decoration:none !important; line-height:1; }
.khome .neon-logo{ font-size:30px; margin:0; }
.topnav{ display:flex; gap:6px; flex-wrap:wrap; }
.navlink{ font-family:'Anton'; text-transform:uppercase; letter-spacing:1px; font-size:13px;
  color:var(--ink) !important; text-decoration:none !important; padding:6px 13px; border-radius:9px;
  border:1.5px solid var(--line); background:#fff; transition:.15s; white-space:nowrap; }
.navlink:hover{ border-color:var(--pink); color:var(--pink) !important; }
.navlink.active{ background:var(--pink); color:#fff !important; border-color:var(--pink); }

/* ---------------- mobile ---------------- */
@media (max-width: 640px){
  .neon-logo{ font-size:40px !important; }
  .neon-tag{ font-size:8px; letter-spacing:3px; }
  .kbar{ gap:8px; }
  .khome .neon-logo{ font-size:24px !important; }
  .navlink{ font-size:11px; padding:5px 9px; letter-spacing:.5px; }
  h1{ font-size:1.5rem !important; }
  h2{ font-size:1.25rem !important; }
  h3{ font-size:1.15rem !important; }
  .sneak{ height:30px; margin:0 8px 2px 0; }
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

  /* team cards stack two-up */
  .kcards{ grid-template-columns:1fr 1fr; gap:8px; }
  .kcard{ min-height:auto; padding:8px 9px; }
  .kcard h4{ font-size:13px; }
  .kcard .kp{ font-size:12px; }

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


def crt(key: str = "top") -> str:
    """Render the classic basketball sneaker header icon (a colorway per section)."""
    img = _SNEAKERS.get(key, _SNEAKERS["top"])
    return f'<img class="sneak" src="{img}" alt="">'


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


_HAT_Y, _HAT_B = "#f4c20d", "#2f80d8"
_TC_EMBLEM = (
    '<svg class="tc-emblem" viewBox="0 0 120 120" style="width:{w}px;height:{w}px;" '
    'aria-hidden="true">'
    '<defs>'
    '<radialGradient id="tcDisc" cx="0.5" cy="0.4" r="0.75">'
    '<stop offset="0" stop-color="#ff4438"/><stop offset=".7" stop-color="#c1121f"/>'
    '<stop offset="1" stop-color="#5e0a10"/></radialGradient>'
    '<clipPath id="tcInner"><circle cx="60" cy="60" r="46"/></clipPath>'
    '</defs>'
    '<circle cx="60" cy="60" r="56" fill="url(#tcDisc)" stroke="#3a0608" stroke-width="3"/>'
    '<g clip-path="url(#tcInner)">'
    '<rect x="12" y="12" width="96" height="96" fill="#cfe8f5"/>'   # sky
    '<rect x="12" y="82" width="96" height="30" fill="#c69a5e"/>'   # dirt ground
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


def inject(st) -> None:
    st.markdown(CSS, unsafe_allow_html=True)
