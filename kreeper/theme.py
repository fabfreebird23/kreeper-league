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
.neon-logo{ font-family:'Rubik Wet Paint', cursive; color:var(--pink); line-height:1;
  text-shadow:0 0 6px rgba(255,79,157,.35), 3px 4px 0 rgba(43,181,232,.55);
  transform:rotate(-3deg); display:inline-block; }
.neon-tag{ font-family:'Oswald'; letter-spacing:5px; font-weight:700; font-size:11px;
  color:var(--purple); text-transform:uppercase; }

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

/* draft board */
table.dboard{ width:100%; border-collapse:collapse; table-layout:fixed; font-family:'Oswald'; font-size:12px; }
table.dboard th{ background:#f1ebfb; color:var(--ink); text-align:center; font-size:11px; padding:5px;
  border:1px solid var(--line); text-transform:uppercase; letter-spacing:.5px; }
.dbcell{ border:1px solid #efeaf8; padding:3px 4px; vertical-align:top; height:48px; }
.dbpick{ color:#b6aecd; font-size:9px; }
.db-base{ background:#faf7ff; color:#9089ab; }
.db-traded{ background:rgba(255,79,157,.16); color:#b21e6b; }
.db-keep{ background:rgba(22,184,166,.20); color:#0c7a6e; box-shadow:inset 0 0 0 1px rgba(22,184,166,.45); }
.db-conflict{ background:rgba(229,72,77,.18); color:#b3232a; box-shadow:inset 0 0 0 1px rgba(229,72,77,.45); }
.db-rd{ background:#f1ebfb; color:var(--purple); font-family:'Anton'; text-align:center; }

/* classic basketball sneaker icon for section headers */
.sneak{ display:inline-block; vertical-align:middle; height:52px; margin:0 14px 6px 0;
  filter:drop-shadow(2px 4px 4px rgba(80,40,70,.32)); }
.lb .pos{ white-space:nowrap; }

/* ---------------- mobile ---------------- */
@media (max-width: 640px){
  .neon-logo{ font-size:40px !important; }
  .neon-tag{ font-size:8px; letter-spacing:3px; }
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

  /* team cards stack two-up */
  .kcards{ grid-template-columns:1fr 1fr; gap:8px; }
  .kcard{ min-height:auto; padding:8px 9px; }
  .kcard h4{ font-size:13px; }
  .kcard .kp{ font-size:12px; }

  /* draft board: tiny + horizontal scroll */
  table.dboard{ font-size:9px; }
  table.dboard th{ padding:3px 2px; font-size:8px; }
  .dbcell{ height:auto; padding:2px 3px; }
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


def logo_html(size: int = 52, tag: str | None = "The Keeper Hub") -> str:
    t = f'<div class="neon-tag">{tag}</div>' if tag else ""
    return (f'<div class="neon-logo" style="font-size:{size}px;">KREEPER</div>{t}')


def inject(st) -> None:
    st.markdown(CSS, unsafe_allow_html=True)
