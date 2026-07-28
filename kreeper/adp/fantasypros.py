"""FantasyPros ADP — public HTML table, no key required.

The page is itself an aggregator: it has an AVG (consensus) column plus
per-platform columns (ESPN, Yahoo, Sleeper, etc.). We emit the per-platform
columns as individual sources and the AVG as a 'FantasyPros' aggregate.

As of mid-2026 FantasyPros moved this page to a client-rendered table (data
embedded as JSON in a `window.FP.reportConfig` script block) and put a
"registrationFence" on it — anonymous requests only get the top 5 rows. We
still parse the embedded JSON (more robust than the old HTML-table scrape),
but if the fence is up there's no legitimate way to get the rest without an
account, so we raise clearly rather than pretend to have full data.
"""
from __future__ import annotations

import json
import re
from typing import List

from .base import POS_RE, AdpRow, clean_float, http_get

SOURCE = "FantasyPros"
_URLS = {
    "ppr": "https://www.fantasypros.com/nfl/adp/ppr-overall.php",
    "half": "https://www.fantasypros.com/nfl/adp/half-point-ppr-overall.php",
    "std": "https://www.fantasypros.com/nfl/adp/overall.php",
}

# A full ADP board is normally 300+ players; a suspiciously short response
# means the registration fence (or some other gate) kicked in.
_MIN_ROWS = 50


def _extract_report_config(html: str) -> dict:
    marker = "window.FP.reportConfig = "
    i = html.find(marker)
    if i < 0:
        raise ValueError("FantasyPros: page layout changed (no reportConfig found)")
    i += len(marker)
    depth, start, end = 0, i, None
    for j in range(i, len(html)):
        if html[j] == "{":
            depth += 1
        elif html[j] == "}":
            depth -= 1
            if depth == 0:
                end = j + 1
                break
    if end is None:
        raise ValueError("FantasyPros: reportConfig block wasn't well-formed")
    return json.loads(html[start:end])


def fetch(season: int, scoring: str = "ppr") -> List[AdpRow]:
    url = _URLS.get(scoring, _URLS["ppr"])
    html = http_get(url).text
    cfg = _extract_report_config(html)
    table = cfg.get("table") or {}
    rows_in = table.get("rows") or []

    if cfg.get("registrationFence") and len(rows_in) < _MIN_ROWS:
        raise ValueError(
            f"FantasyPros now gates full ADP behind free registration "
            f"(only {len(rows_in)} rows public) — skipping until that changes"
        )
    if len(rows_in) < _MIN_ROWS:
        raise ValueError(f"FantasyPros: only {len(rows_in)} rows returned (expected 300+)")

    # field key ('src_79', 'avg', ...) -> display label ('ESPN', 'FantasyPros', ...)
    field_label = {"avg": SOURCE}
    for f in table.get("fields", []):
        key = f.get("key", "")
        if key.startswith("src_"):
            field_label[key] = f.get("label") or key

    rows: List[AdpRow] = []
    for r in rows_in:
        player = r.get("player") or {}
        name = re.sub(r"\s+", " ", str(player.get("name") or "")).strip()
        if not name:
            continue
        pos_m = POS_RE.search(str(r.get("pos") or ""))
        pos = (pos_m.group(1).upper() if pos_m else "").replace("DEF", "DST")
        for key, label in field_label.items():
            if label == "ESPN":
                continue  # we pull ESPN directly from ESPN's own feed
            a = clean_float(r.get(key))
            if a:
                rows.append(AdpRow(label, name, pos, "", a))
    return rows
