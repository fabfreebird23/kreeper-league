"""FootballGuys ADP — public HTML table aggregating many platforms.

Like FantasyPros, the page carries a consensus column plus per-platform columns
(ESPN, Yahoo, Sleeper, Underdog, CBS, NFL, ...). We emit per-platform columns as
individual sources and the consensus as a 'FootballGuys' aggregate. If the table
is JS-rendered and not present in the raw HTML, this raises and the consensus
builder skips it.
"""
from __future__ import annotations

import io
import re
from typing import List

import pandas as pd

from .base import AdpRow, clean_float, http_get
from .fantasypros import _PLATFORMS, _POS_RE

SOURCE = "FootballGuys"
_URL = "https://www.footballguys.com/adp"


def fetch(season: int, scoring: str = "ppr") -> List[AdpRow]:
    html = http_get(_URL).text
    tables = pd.read_html(io.StringIO(html))
    if not tables:
        raise ValueError("FootballGuys: no tables found (likely JS-rendered)")
    df = max(tables, key=lambda t: t.shape[0] * t.shape[1])
    df.columns = [str(c).strip() for c in df.columns]

    player_col = next((c for c in df.columns if "player" in c.lower() or "name" in c.lower()), None)
    pos_col = next((c for c in df.columns if c.lower() in ("pos", "position")), None)
    # consensus column is often 'ADP', 'Consensus', or 'AVG'
    cons_col = next(
        (c for c in df.columns if c.lower() in ("adp", "consensus", "avg", "average", "overall")),
        None,
    )
    if player_col is None:
        raise ValueError("FootballGuys: could not locate player column")

    # Skip ESPN here — we pull it directly from ESPN's own feed.
    platform_cols = {
        c: _PLATFORMS[c.lower()]
        for c in df.columns
        if c.lower() in _PLATFORMS and c.lower() != "espn"
    }

    rows: List[AdpRow] = []
    for _, r in df.iterrows():
        name = re.sub(r"\s+", " ", str(r[player_col])).strip()
        name = re.sub(r"\s+[A-Z]{2,3}\s*(\(\d+\))?$", "", name).strip()
        if not name or name.lower() in ("player", "name", "nan"):
            continue
        pos = ""
        if pos_col is not None:
            m = _POS_RE.search(str(r[pos_col]))
            pos = (m.group(1).upper() if m else "").replace("DEF", "DST")
        if cons_col is not None:
            a = clean_float(r[cons_col])
            if a:
                rows.append(AdpRow(SOURCE, name, pos, "", a))
        for col, label in platform_cols.items():
            a = clean_float(r[col])
            if a:
                rows.append(AdpRow(label, name, pos, "", a))
    return rows
