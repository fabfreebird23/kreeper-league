"""FantasyPros ADP — public HTML table, no key required.

The page is itself an aggregator: it has an AVG (consensus) column plus
per-platform columns (ESPN, Yahoo, Sleeper, etc.). We emit the per-platform
columns as individual sources and the AVG as a 'FantasyPros' aggregate.
"""
from __future__ import annotations

import io
import re
from typing import List

import pandas as pd

from .base import AdpRow, clean_float, http_get

SOURCE = "FantasyPros"
_URLS = {
    "ppr": "https://www.fantasypros.com/nfl/adp/ppr-overall.php",
    "half": "https://www.fantasypros.com/nfl/adp/half-point-ppr-overall.php",
    "std": "https://www.fantasypros.com/nfl/adp/overall.php",
}

# header text (lowercased) -> canonical platform label
_PLATFORMS = {
    "espn": "ESPN", "yahoo": "Yahoo", "sleeper": "Sleeper", "cbs": "CBS",
    "nfl": "NFL", "rtsports": "RTSports", "ffc": "FFC", "nffc": "NFFC",
    "mfl": "MFL", "underdog": "Underdog", "ud": "Underdog", "bb10s": "BestBall10s",
    "drafters": "Drafters", "dk": "DraftKings", "draftkings": "DraftKings",
}
_POS_RE = re.compile(r"\b(QB|RB|WR|TE|K|DST|DEF)\d*\b", re.I)
_NAME_RE = re.compile(r"^(.*?)\s+[A-Z]{2,3}\s*(\(\d+\))?\s*$")


def _split_player_cell(cell: str):
    """'Ja'Marr Chase CIN (10)' -> ('Ja'Marr Chase', '')."""
    s = re.sub(r"\s+", " ", str(cell)).strip()
    m = _NAME_RE.match(s)
    name = m.group(1).strip() if m else s
    return name


def fetch(season: int, scoring: str = "ppr") -> List[AdpRow]:
    url = _URLS.get(scoring, _URLS["ppr"])
    html = http_get(url).text
    tables = pd.read_html(io.StringIO(html))
    # The data table is the widest one with a 'Player' column.
    df = max(tables, key=lambda t: t.shape[0] * t.shape[1])
    df.columns = [str(c).strip() for c in df.columns]

    player_col = next((c for c in df.columns if "player" in c.lower()), None)
    pos_col = next((c for c in df.columns if c.lower() in ("pos", "position")), None)
    avg_col = next((c for c in df.columns if c.lower() in ("avg", "average")), None)
    if player_col is None:
        raise ValueError("FantasyPros: could not locate player column")

    # Skip ESPN here — we pull it directly from ESPN's own feed.
    platform_cols = {
        c: _PLATFORMS[c.lower()]
        for c in df.columns
        if c.lower() in _PLATFORMS and c.lower() != "espn"
    }

    rows: List[AdpRow] = []
    for _, r in df.iterrows():
        name = _split_player_cell(r[player_col])
        if not name or name.lower().startswith("player"):
            continue
        pos = ""
        if pos_col is not None:
            m = _POS_RE.search(str(r[pos_col]))
            pos = (m.group(1).upper() if m else "").replace("DEF", "DST")
        # consensus AVG -> aggregate source
        if avg_col is not None:
            a = clean_float(r[avg_col])
            if a:
                rows.append(AdpRow(SOURCE, name, pos, "", a))
        # per-platform sub-columns -> individual sources
        for col, label in platform_cols.items():
            a = clean_float(r[col])
            if a:
                rows.append(AdpRow(label, name, pos, "", a))
    return rows
