"""DraftSharks ADP — the canonical Sleeper ADP feed.

DraftSharks publishes platform-specific ADP boards (Sleeper, ESPN, Underdog, …).
The on-page table is JS-rendered, but the raw HTML embeds a JSON array of player
objects, each with an ``adps`` map keyed by
``"<format_id>::<source_id>::<league_size>"``. We read the Sleeper board
(source 111), full-PPR (format 11), 12-team — Sleeper's standard ADP — and emit
it as a single ``Sleeper`` source that feeds the consensus mean.

The league here is 10-team, but Sleeper's published ADP is the 12-team board
(that's what real Sleeper drafts default to), so 12 is the right, most-populated
column to pull.
"""
from __future__ import annotations

import json
import re
from typing import List

from .base import AdpRow, http_get

SOURCE = "Sleeper"

# DraftSharks internal ids (stable on their site): format 11 = full PPR,
# source 111 = Sleeper. The page we scrape is the PPR/Sleeper/12 board.
_FORMAT_PPR = 11
_SLEEPER_SOURCE_ID = 111
_LEAGUE_SIZE = 12
_URL = "https://www.draftsharks.com/adp/ppr/sleeper/12"

_PLAYER_RE = re.compile(
    r'"first_name":"([^"]*)","last_name":"([^"]*)","position":"([^"]*)"'
)


def _decode(s: str) -> str:
    """The embedded JSON uses \\uXXXX escapes (e.g. Ja\\u0027Marr)."""
    try:
        return json.loads(f'"{s}"')
    except Exception:  # noqa: BLE001
        return s


def _balanced_object(html: str, brace_start: int, limit: int = 20000) -> str:
    """Return the brace-balanced substring starting at ``html[brace_start] == '{'``."""
    depth = 0
    end = min(len(html), brace_start + limit)
    for i in range(brace_start, end):
        c = html[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return html[brace_start:i + 1]
    return html[brace_start:end]


def fetch(season: int, scoring: str = "ppr") -> List[AdpRow]:
    key = f"{_FORMAT_PPR}::{_SLEEPER_SOURCE_ID}::{_LEAGUE_SIZE}"
    pick_re = re.compile(
        re.escape(f'"{key}":') + r'\{"player_id":\d+,"overall_pick_number":(\d+)'
    )
    html = http_get(_URL).text

    rows: List[AdpRow] = []
    seen: set = set()
    for pm in _PLAYER_RE.finditer(html):
        fn, ln, pos = _decode(pm.group(1)), _decode(pm.group(2)), pm.group(3)
        adps_i = html.find('"adps":{', pm.end())
        if adps_i < 0 or adps_i - pm.end() > 400:
            continue
        blob = _balanced_object(html, adps_i + len('"adps":'))
        m = pick_re.search(blob)
        if not m:
            continue
        name = re.sub(r"\s+", " ", f"{fn} {ln}").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        pos = (pos or "").upper().replace("DEF", "DST")
        rows.append(AdpRow(SOURCE, name, pos, "", float(m.group(1))))

    if not rows:
        raise ValueError("DraftSharks: no Sleeper ADP rows parsed (layout/key changed)")
    return rows
