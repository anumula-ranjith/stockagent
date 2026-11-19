"""A quote snapshot is not evidence of a broker tick."""
import asyncio
import json
import struct
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from stock_agents.api import market_feed
from stock_agents.sources import angel_market, angel_session


def test_every_tick_is_forwarded_after_the_snapshot(monkeypatch):
    import websockets.asyncio.client as ws_client

    monkeypatch.setattr(angel_session, "read_session", lambda: {
        "feed_token":"test", "client_code":"test", "token":"test", "api_key":"test"})
    monkeypatch.setattr(angel_market, "_instrument_master", lambda day: {
        "INFY": angel_market.Instrument("INFY","INFY-EQ","1594")})
    monkeypatch.setattr(market_feed, "quote_batch", lambda tickers: {"INFY":{"price":99}})
    frames = []
    for paise in (10000,10001):
        frame = bytearray(51)
        frame[:2] = bytes((1,1))
        frame[2:6] = b"1594"
        struct.pack_into("<qq",frame,35,1795084100000,paise)
        frames.append(bytes(frame))
    feed = AsyncMock()
    feed.recv.side_effect = [*frames,json.dumps({"error":"end fixture"})]

    @asynccontextmanager
    async def connect(*args, **kwargs):
        yield feed

    monkeypatch.setattr(ws_client,"connect",connect)
    browser = AsyncMock()
    asyncio.run(market_feed.broker_ticks(browser,["INFY"],time.monotonic()+5))
    packets = [call.args[0] for call in browser.send_json.call_args_list]
    assert [p["mode"] for p in packets] == ["awaiting_tick","ticks","ticks"]
    assert [p["quotes"]["INFY"]["price"] for p in packets[1:]] == [100,100.01]
    assert all(p["delta"] and p["quotes"]["INFY"]["source"]=="tick" for p in packets[1:])
