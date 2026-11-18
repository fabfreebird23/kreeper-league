"""Unit tests for the Trade Block logic (kreeper/tradeblock.py)."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kreeper import tradeblock as tb  # noqa: E402

POS = {"p1": "RB", "p2": "WR", "p3": "WR"}.get


def _sell(owner="heath", pid="p1", asks=None, **kw):
    return tb.new_listing(owner, "sell", player_id=pid,
                          asks=asks or [{"t": "pick", "year": 2027, "round": 3}], now=1000, **kw)


def test_relisting_the_same_player_replaces_the_open_listing():
    b = tb.add_listing(tb.blank(), _sell())
    b = tb.add_listing(b, _sell(note="lower price"))
    assert [x["status"] for x in b["listings"]] == ["withdrawn", "open"]
    assert len(tb.active(b)) == 1


def test_offer_flow_accept_declines_the_rest_and_marks_agreed():
    b = tb.add_listing(tb.blank(), _sell())
    lid = b["listings"][0]["id"]
    o1 = tb.new_offer("brandon", picks=[{"year": 2027, "round": 2, "label": "2027 R2"}])
    o2 = tb.new_offer("tanner", picks=[{"year": 2027, "round": 4, "label": "2027 R4"}], faab=6)
    b = tb.add_offer(b, lid, o1)
    b = tb.add_offer(b, lid, o2)
    b = tb.respond(b, lid, o1["id"], "accept", by="tanner")      # not his listing: ignored
    assert b["listings"][0]["status"] == "open"
    b = tb.respond(b, lid, o1["id"], "accept", by="heath")
    x = b["listings"][0]
    assert x["status"] == "agreed"
    assert [o["status"] for o in x["offers"]] == ["accepted", "declined"]


def test_a_seller_cannot_offer_on_their_own_listing_and_new_offers_replace_old():
    b = tb.add_listing(tb.blank(), _sell())
    lid = b["listings"][0]["id"]
    b = tb.add_offer(b, lid, tb.new_offer("heath", faab=5))
    assert b["listings"][0]["offers"] == []
    b = tb.add_offer(b, lid, tb.new_offer("brandon", faab=5))
    b = tb.add_offer(b, lid, tb.new_offer("brandon", faab=9))
    assert [o["status"] for o in b["listings"][0]["offers"]] == ["withdrawn", "pending"]


def test_refresh_closes_traded_dropped_and_expired():
    b = tb.blank()
    for x in (_sell(pid="p1"), _sell(pid="p2"), _sell(pid="p3", until="sunday")):
        tb.add_listing(b, x)
    rosters = {"heath": ["p3"], "mike": ["p1"]}          # p1 traded to Mike, p2 dropped
    assert tb.refresh(b, rosters, now=1001)
    assert [x["status"] for x in b["listings"]] == ["traded", "dropped", "open"]
    assert tb.refresh(b, rosters, now=b["listings"][2]["expires"] + 1)
    assert b["listings"][2]["status"] == "expired"
    assert not tb.refresh(b, rosters, now=10 ** 10)


def test_trade_deadline_closes_everything_open():
    b = tb.add_listing(tb.blank(), tb.new_listing("jared", "want", want_pos="RB", now=1000))
    assert tb.refresh(b, {}, closed_for_season=True)
    assert b["listings"][0]["status"] == "expired"


def test_sunday_kickoff_is_the_next_sunday_18_utc():
    wed = datetime(2026, 11, 18, 15, tzinfo=timezone.utc).timestamp()
    k = datetime.fromtimestamp(tb.next_sunday_kickoff(wed), tz=timezone.utc)
    assert (k.year, k.month, k.day, k.hour) == (2026, 11, 22, 18)
    late_sun = datetime(2026, 11, 22, 20, tzinfo=timezone.utc).timestamp()
    assert datetime.fromtimestamp(tb.next_sunday_kickoff(late_sun), tz=timezone.utc).day == 29


def test_check_asks_against_a_viewers_assets():
    x = _sell(asks=[{"t": "pick", "year": 2027, "round": 3}, {"t": "pos", "pos": "WR"},
                    {"t": "faab", "min": 10}, {"t": "offer"}])
    assets = {"picks": [{"year": 2027, "round": 2, "label": "2027 R2"},
                        {"year": 2028, "round": 1, "label": "2028 R1"}],
              "spare": {"WR": ["George Pickens"]}, "faab": 8}
    got = tb.check_asks(x, assets)
    assert [g["ok"] for g in got] == [True, True, False, False]
    assert got[0]["have"] == "2027 R2" and got[1]["have"] == "George Pickens"
    assert [g["text"] for g in got] == ["2027 3rd or better", "A WR", "$10 FAAB", "Make me an offer"]


def test_offer_covers_any_one_ask():
    x = _sell(asks=[{"t": "pick", "year": 2027, "round": 3}, {"t": "faab", "min": 10}])
    assert tb.offer_covers(x, tb.new_offer("b", picks=[{"year": 2027, "round": 3, "label": ""}]), POS)
    assert not tb.offer_covers(x, tb.new_offer("b", picks=[{"year": 2027, "round": 4, "label": ""}]), POS)
    assert tb.offer_covers(x, tb.new_offer("b", faab=10), POS)
    y = _sell(asks=[{"t": "pos", "pos": "WR"}])
    assert tb.offer_covers(y, tb.new_offer("b", players=["p2"]), POS)
    assert not tb.offer_covers(y, tb.new_offer("b", players=["p1"]), POS)
    z = _sell(asks=[{"t": "offer"}])
    assert tb.offer_covers(z, tb.new_offer("b", faab=1), POS)
    assert not tb.offer_covers(z, tb.new_offer("b"), POS)
