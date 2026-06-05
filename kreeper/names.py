"""Player-name normalization so we can match players across ADP sources and Sleeper.

Different feeds spell names differently (A.J. vs AJ, Jr. suffixes, Marvin
Harrison Jr. vs Marvin Harrison). We collapse everything to a stable key:
lowercase, no punctuation, generational suffixes stripped, plus the position
and team when we have them to disambiguate same-name players.
"""
from __future__ import annotations

import re
import unicodedata

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
# Hand-fixes for spellings that normalization alone won't reconcile.
_ALIASES = {
    "kennethwalker": "kennethwalkeriii",
    "marvinharrison": "marvinharrisonjr",
    "brianthomas": "brianthomasjr",
    "michaelpittman": "michaelpittmanjr",
    "calvinaustin": "calvinaustiniii",
    "hollywoodbrown": "marquisebrown",
}


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def normalize_name(name: str) -> str:
    """Return a punctuation/suffix-free lowercase key for a player's name."""
    if not name:
        return ""
    s = _strip_accents(name).lower()
    s = re.sub(r"[^a-z0-9 ]", "", s)  # drop periods, apostrophes, hyphens
    parts = [p for p in s.split() if p]
    # Drop trailing generational suffix only if there's a real name before it.
    if len(parts) > 1 and parts[-1] in _SUFFIXES:
        parts = parts[:-1]
    key = "".join(parts)
    return _ALIASES.get(key, key)


def player_key(name: str, position: str | None = None) -> str:
    """A name key optionally namespaced by position to split same-name players."""
    base = normalize_name(name)
    if position:
        return f"{base}|{position.lower()}"
    return base
