"""The Trade Block: players up for trade, what each seller would take, offers.

A board for starting deals, not a trading engine. Sleeper is still where a
trade happens; the block only records who is selling (or buying), what they
asked for, and the offers made against it. A listing closes itself when its
player leaves the seller's roster (traded or dropped) or when it expires.

Self-contained on purpose (no Streamlit, no app imports), so the same file
drops into each league hub, like playoffs.py. The app owns storage: every
writer here takes the season blob and returns it, so it can run inside the
storage layer's read-modify-write retry.

Shapes
  blob     {"listings": [listing, ...]}
  listing  {id, kind: "sell"|"want", owner, player_id (sell), want_pos (want),
            asks: [ask], offering: [str] (want), note, until, expires (epoch|None),
            status: open|agreed|traded|dropped|expired|withdrawn, created, closed,
            offers: [offer]}
  ask      {"t": "pick", "year": 2027, "round": 5}   a pick in round 5 or better
           {"t": "pos", "pos": "WR"}                  a player at that position
           {"t": "faab", "min": 8}                    at least $8 of FAAB
           {"t": "slot"}                              a keeper slot (if the league allows)
           {"t": "offer"}                             make me an offer
  offer    {id, from, players: [pid], picks: [{year, round, label}], faab: int,
            note, status: pending|accepted|declined|withdrawn, created}
An ask list means "I'd take any of these", so an offer covers the listing when
it meets at least one ask.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

OPEN = ("open", "agreed")
POSITIONS = ("QB", "RB", "WR", "TE")


def blank() -> Dict[str, Any]:
    return {"listings": []}


def _id() -> str:
    return uuid.uuid4().hex[:10]


def next_sunday_kickoff(now: Optional[float] = None) -> float:
    """Epoch of the coming Sunday 1:00 pm Eastern (18:00 UTC, close enough
    across DST for a listing timer)."""
    t = datetime.fromtimestamp(now or time.time(), tz=timezone.utc)
    days = (6 - t.weekday()) % 7
    k = (t + timedelta(days=days)).replace(hour=18, minute=0, second=0, microsecond=0)
    if k <= t:
        k += timedelta(days=7)
    return k.timestamp()


def new_listing(owner: str, kind: str = "sell", player_id: Optional[str] = None,
                want_pos: Optional[str] = None, asks: Optional[List[dict]] = None,
                offering: Optional[List[str]] = None, note: str = "", until: str = "deadline",
                now: Optional[float] = None) -> Dict[str, Any]:
    now = now or time.time()
    return {"id": _id(), "kind": kind, "owner": str(owner),
            "player_id": str(player_id) if player_id else None,
            "want_pos": want_pos, "asks": list(asks or [{"t": "offer"}]),
            "offering": list(offering or []), "note": (note or "").strip()[:200],
            "until": until, "expires": next_sunday_kickoff(now) if until == "sunday" else None,
            "status": "open", "created": now, "closed": None, "offers": []}


def _find(blob: dict, listing_id: str) -> Optional[dict]:
    return next((x for x in blob.get("listings", []) if x.get("id") == listing_id), None)


def add_listing(blob: dict, listing: dict) -> dict:
    """Post a listing. Re-listing the same player (or the same position
    want) replaces the seller's open one instead of stacking duplicates."""
    blob = blob or blank()
    blob.setdefault("listings", [])
    for x in blob["listings"]:
        same = (x["owner"] == listing["owner"] and x["kind"] == listing["kind"] and x["status"] == "open"
                and (x.get("player_id") == listing.get("player_id") if listing["kind"] == "sell"
                     else x.get("want_pos") == listing.get("want_pos")))
        if same:
            x.update(status="withdrawn", closed=listing["created"])
    blob["listings"].append(listing)
    return blob


def withdraw(blob: dict, listing_id: str, by: str, now: Optional[float] = None) -> dict:
    x = _find(blob, listing_id)
    if x and x["owner"] == str(by) and x["status"] in OPEN:
        x.update(status="withdrawn", closed=now or time.time())
    return blob


def new_offer(by: str, players: Iterable[str] = (), picks: Iterable[dict] = (), faab: int = 0,
              note: str = "", now: Optional[float] = None) -> Dict[str, Any]:
    return {"id": _id(), "from": str(by), "players": [str(p) for p in players],
            "picks": [dict(p) for p in picks], "faab": max(0, int(faab or 0)),
            "note": (note or "").strip()[:200], "status": "pending", "created": now or time.time()}


def add_offer(blob: dict, listing_id: str, offer: dict) -> dict:
    """One live offer per manager per listing: a new one replaces theirs."""
    x = _find(blob, listing_id)
    if not x or x["status"] != "open" or offer["from"] == x["owner"]:
        return blob
    for o in x["offers"]:
        if o["from"] == offer["from"] and o["status"] == "pending":
            o["status"] = "withdrawn"
    x["offers"].append(offer)
    return blob


def respond(blob: dict, listing_id: str, offer_id: str, action: str, by: str,
            now: Optional[float] = None) -> dict:
    """The listing's owner accepts/declines an offer; the offer's maker can
    withdraw it. Accepting marks the listing "agreed" (it closes as traded
    once Sleeper shows the player moved) and declines the other offers."""
    x = _find(blob, listing_id)
    if not x:
        return blob
    o = next((y for y in x["offers"] if y["id"] == offer_id), None)
    if not o:
        return blob
    by = str(by)
    if action == "withdraw" and o["from"] == by and o["status"] in ("pending", "accepted"):
        o["status"] = "withdrawn"
        if x["status"] == "agreed" and not any(y["status"] == "accepted" for y in x["offers"]):
            x["status"] = "open"
    elif action in ("accept", "decline") and x["owner"] == by and o["status"] == "pending":
        o["status"] = "accepted" if action == "accept" else "declined"
        if action == "accept":
            x["status"] = "agreed"
            for y in x["offers"]:
                if y is not o and y["status"] == "pending":
                    y["status"] = "declined"
    return blob


def refresh(blob: dict, rosters: Dict[str, Iterable[str]], now: Optional[float] = None,
            closed_for_season: bool = False) -> bool:
    """Close what's finished; True when anything changed (so the caller saves).
    `rosters` is {owner: player ids}. A selling listing whose player left the
    seller closes as traded (he's on another roster) or dropped."""
    now = now or time.time()
    where = {str(p): o for o, ps in rosters.items() for p in ps}
    changed = False
    for x in blob.get("listings", []):
        if x["status"] not in OPEN:
            continue
        status = None
        pid = x.get("player_id")
        if x["kind"] == "sell" and pid and where.get(pid) != x["owner"]:
            status = "traded" if pid in where else "dropped"
        elif closed_for_season or (x.get("expires") and now >= x["expires"]):
            status = "expired"
        if status:
            x.update(status=status, closed=now)
            changed = True
    return changed


def active(blob: dict) -> List[dict]:
    """Open and agreed listings, newest first."""
    return sorted((x for x in (blob or {}).get("listings", []) if x["status"] in OPEN),
                  key=lambda x: -x["created"])


# ------------------------------------------------------------------ asks
def ask_text(a: dict) -> str:
    t = a.get("t")
    if t == "pick":
        r = int(a["round"])
        suf = {1: "st", 2: "nd", 3: "rd"}.get(r if r < 20 else r % 10, "th")
        return f'{a["year"]} {r}{suf} or better' if r > 1 else f'{a["year"]} 1st'
    if t == "pos":
        return f'A{"n" if a["pos"] == "RB" else ""} {a["pos"]}'
    if t == "faab":
        return f'${int(a["min"])} FAAB'
    if t == "slot":
        return "A keeper slot"
    return "Make me an offer"


def check_asks(listing: dict, assets: dict) -> List[dict]:
    """Which of the seller's asks the viewer could cover right now.
    `assets` = {"picks": [{year, round, label}], "spare": {pos: [names]},
    "faab": int, "slot": bool}. Returns [{ask, text, ok, have}]."""
    out = []
    for a in listing.get("asks") or []:
        t, have = a.get("t"), ""
        if t == "pick":
            ok_picks = [p for p in assets.get("picks", [])
                        if int(p["year"]) == int(a["year"]) and int(p["round"]) <= int(a["round"])]
            ok, have = bool(ok_picks), ", ".join(p["label"] for p in ok_picks[:2])
        elif t == "pos":
            names = (assets.get("spare") or {}).get(a["pos"]) or []
            ok, have = bool(names), ", ".join(names[:2])
        elif t == "faab":
            left = int(assets.get("faab") or 0)
            ok, have = left >= int(a["min"]), f"${left} left"
        elif t == "slot":
            ok = bool(assets.get("slot"))
        else:
            ok = False
        out.append({"ask": a, "text": ask_text(a), "ok": ok and t != "offer", "have": have})
    return out


def offer_covers(listing: dict, offer: dict, pos_of: Callable[[str], str]) -> bool:
    """Does an offer meet at least one of the listing's asks? "Make me an
    offer" listings are covered by anything."""
    asks = listing.get("asks") or []
    if not asks or any(a.get("t") == "offer" for a in asks):
        return bool(offer["players"] or offer["picks"] or offer["faab"])
    for a in asks:
        t = a.get("t")
        if t == "pick" and any(int(p["year"]) == int(a["year"]) and int(p["round"]) <= int(a["round"])
                               for p in offer["picks"]):
            return True
        if t == "pos" and any(pos_of(p) == a["pos"] for p in offer["players"]):
            return True
        if t == "faab" and offer["faab"] >= int(a["min"]):
            return True
    return False
