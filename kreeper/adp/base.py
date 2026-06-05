"""Shared bits for ADP providers.

Each provider exposes `fetch(season, scoring) -> list[AdpRow]`. A provider that
fails (site down, layout changed) should raise; the consensus builder catches it
and carries on with whatever other sources succeeded — a daily cron must never
die because one site hiccuped.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import requests

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class AdpRow:
    source: str
    name: str
    position: str
    team: str
    adp: float          # overall average draft position / pick number


def http_get(url: str, headers: Optional[dict] = None, timeout: int = 25) -> requests.Response:
    h = dict(BROWSER_HEADERS)
    if headers:
        h.update(headers)
    r = requests.get(url, headers=h, timeout=timeout)
    r.raise_for_status()
    return r


def clean_float(x) -> Optional[float]:
    try:
        v = float(str(x).strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None
