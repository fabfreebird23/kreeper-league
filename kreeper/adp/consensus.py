"""Run every enabled ADP provider, reconcile players, and build a consensus.

Output: data/adp_<season>.csv with one row per player — each source's ADP, a
consensus (mean of the individual platform sources), and a consensus overall
rank used by the keeper engine to derive a draft round.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Callable, Dict, List

import pandas as pd

from .. import config
from ..names import normalize_name
from .base import AdpRow
from . import espn, fantasypros, footballguys

# Providers keyed by their config toggle name.
PROVIDERS: Dict[str, Callable[[int, str], List[AdpRow]]] = {
    "espn": espn.fetch,
    "fantasypros": fantasypros.fetch,
    "footballguys": footballguys.fetch,
}

# Aggregator columns: displayed, but excluded from the consensus mean so we don't
# double-count platforms that already feed their per-source sub-columns.
AGGREGATE_SOURCES = {"FantasyPros", "FootballGuys"}


def collect_rows(season: int, scoring: str) -> (List[AdpRow], Dict[str, str]):
    rows: List[AdpRow] = []
    status: Dict[str, str] = {}
    enabled = config.adp_sources()
    active = {k: fn for k, fn in PROVIDERS.items() if enabled.get(k, False)}
    for key in PROVIDERS:
        if key not in active:
            status[key] = "disabled"

    # Sources are independent network calls — fetch them concurrently. A flaky
    # site only fails its own future; the others still land.
    from concurrent.futures import ThreadPoolExecutor

    def _one(key: str):
        try:
            got = active[key](season, scoring)
            return key, got, f"ok ({len(got)} rows)"
        except Exception as e:  # noqa: BLE001
            return key, [], f"FAILED: {type(e).__name__}: {e}"

    if active:
        with ThreadPoolExecutor(max_workers=len(active)) as ex:
            for key, got, st in ex.map(_one, active):
                rows.extend(got)
                status[key] = st
    return rows, status


def build(season: int | None = None, scoring: str | None = None) -> pd.DataFrame:
    season = season or config.current_season()
    scoring = scoring or config.league().get("scoring", "ppr")
    rows, status = collect_rows(season, scoring)

    # Group rows by player name only (positions are reported inconsistently
    # across sources, which would otherwise split one player into two rows).
    players: Dict[str, Dict] = {}
    for r in rows:
        nkey = normalize_name(r.name)
        rec = players.setdefault(
            nkey,
            {
                "key": nkey,
                "name_key": nkey,
                "name": r.name,
                "position": r.position,
                "sources": {},
            },
        )
        # keep the longest/cleanest display name and first known position
        if len(r.name) > len(rec["name"]):
            rec["name"] = r.name
        if not rec["position"] and r.position:
            rec["position"] = r.position
        rec["sources"].setdefault(r.source, []).append(r.adp)

    records = []
    all_sources = set()
    for rec in players.values():
        src_avg = {s: round(sum(v) / len(v), 2) for s, v in rec["sources"].items()}
        all_sources.update(src_avg)
        primary = [v for s, v in src_avg.items() if s not in AGGREGATE_SOURCES]
        pool = primary if primary else list(src_avg.values())
        consensus = round(sum(pool) / len(pool), 2) if pool else None
        row = {
            "key": rec["key"],
            "name_key": rec["name_key"],
            "name": rec["name"],
            "position": rec["position"],
            "consensus_adp": consensus,
            "n_sources": len([s for s in src_avg if s not in AGGREGATE_SOURCES]) or len(src_avg),
        }
        row.update(src_avg)
        records.append(row)

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values("consensus_adp", na_position="last").reset_index(drop=True)
        df["consensus_rank"] = range(1, len(df) + 1)
        df.loc[df["consensus_adp"].isna(), "consensus_rank"] = pd.NA

    config.DATA_DIR.mkdir(exist_ok=True)
    out = config.DATA_DIR / f"adp_{season}.csv"
    df.to_csv(out, index=False)
    meta = {
        "season": season,
        "scoring": scoring,
        "updated_utc": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "sources": sorted(all_sources),
        "status": status,
        "players": len(df),
    }
    (config.DATA_DIR / f"adp_{season}_meta.json").write_text(json.dumps(meta, indent=2))
    return df


def load(season: int | None = None) -> pd.DataFrame:
    season = season or config.current_season()
    path = config.DATA_DIR / f"adp_{season}.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def load_meta(season: int | None = None) -> dict:
    season = season or config.current_season()
    path = config.DATA_DIR / f"adp_{season}_meta.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _history_path(season: int):
    return config.DATA_DIR / f"adp_history_{season}.json"


def snapshot(season: int | None = None, day: str | None = None, keep_days: int = 90) -> int:
    """Append today's consensus ranks to the ADP history (one entry per day).
    Returns the number of days now stored."""
    season = season or config.current_season()
    df = load(season)
    if df.empty:
        return 0
    if day is None:
        day = dt.date.today().isoformat()
    rows = {}
    for _, r in df.iterrows():
        rank = r.get("consensus_rank")
        if pd.isna(rank):
            continue
        rows[normalize_name(str(r["name"]))] = [int(rank), str(r["name"]), str(r.get("position", ""))]
    path = _history_path(season)
    hist = {}
    if path.exists():
        try:
            hist = json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            hist = {}
    hist[day] = rows
    for old in sorted(hist)[:-keep_days]:
        hist.pop(old, None)
    path.write_text(json.dumps(hist))
    return len(hist)


def adp_movement(season: int | None = None, window_days: int = 7) -> dict:
    """Risers/fallers vs the snapshot ~window_days ago. delta>0 = moved up."""
    season = season or config.current_season()
    path = _history_path(season)
    if not path.exists():
        return {"days": [], "moves": []}
    hist = json.loads(path.read_text())
    days = sorted(hist)
    if len(days) < 2:
        return {"days": days, "moves": []}
    latest = days[-1]
    cutoff = (dt.date.fromisoformat(latest) - dt.timedelta(days=window_days)).isoformat()
    prior = next((d for d in days if d >= cutoff and d != latest), days[0])
    cur, old = hist[latest], hist[prior]
    moves = []
    for nm, val in cur.items():
        if nm in old:
            now_r, was_r = val[0], old[nm][0]
            moves.append({"name": val[1], "pos": val[2], "now": now_r, "was": was_r,
                          "delta": was_r - now_r})
    return {"latest": latest, "prior": prior, "moves": moves}


def adp_lookup(season: int | None = None) -> Dict[str, float]:
    """normalized-name(+pos and name-only) -> consensus_adp rank for quick joins."""
    df = load(season)
    lk: Dict[str, float] = {}
    if df.empty:
        return lk
    for _, r in df.iterrows():
        rank = r.get("consensus_rank")
        if pd.isna(rank):
            continue
        lk[str(r["key"])] = float(rank)
        lk.setdefault(str(r["name_key"]), float(rank))
    return lk
