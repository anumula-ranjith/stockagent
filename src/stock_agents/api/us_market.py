"""US research data. Exchange codes, currency and provider feeds are explicit."""

import asyncio
import json
import math
import os
import re
import secrets
import time
from datetime import datetime, timedelta
from functools import lru_cache
from threading import Lock
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from stock_agents.api.auth import CurrentUser
from stock_agents.sources.eodhd import EODHDClient

router = APIRouter(prefix="/us", tags=["US equities"])
ET = ZoneInfo("America/New_York")
EXCHANGES = {"NYSE", "NASDAQ", "NYSE ARCA", "NYSE MKT", "NYSE AMERICAN", "AMEX", "BATS"}
SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.-]{0,14}")
lock = Lock()


def clean(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def vendor(fn, *args):
    try:
        return fn(*args)
    except (ValueError, RuntimeError, httpx.HTTPError):
        raise HTTPException(
            503, "US data provider is unavailable or this feed is outside the account entitlement"
        ) from None


def headers():
    key, secret = os.getenv("ALPACA_KEY_ID"), os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("Missing Alpaca credentials")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def alpaca(path, params, host="https://data.alpaca.markets"):
    r = httpx.get(host + path, params=params, headers=headers(), timeout=12)
    r.raise_for_status()
    return r.json()


@lru_cache(maxsize=1)
def directory(day):
    rows = EODHDClient.from_env()._get("/exchange-symbol-list/US")
    return {
        row["Code"]: row
        for row in rows
        if SYMBOL.fullmatch(row.get("Code") or "")
        and row.get("Exchange") in EXCHANGES
        and row.get("Currency") == "USD"
        and row.get("Type") in {"Common Stock", "ETF"}
    }


@lru_cache(maxsize=1)
def market(bucket):
    client = EODHDClient.from_env()
    names = directory(datetime.now(ET).date())
    rows = []
    for bar in client.bulk_eod("US"):
        ticker = bar.get("code")
        if ticker not in names or not clean(bar.get("close")):
            continue
        meta = names[ticker]
        close = clean(bar["close"])
        opening, high, low = [clean(bar.get(k)) for k in ("open", "hi_250d", "lo_250d")]
        rows.append(
            dict(
                ticker=ticker,
                name=meta["Name"],
                exchange=meta["Exchange"],
                kind=meta["Type"],
                date=bar["date"],
                close=close,
                volume=clean(bar.get("volume")),
                cap=clean(bar.get("MarketCapitalization")),
                intraday=(close / opening - 1) * 100 if opening else None,
                below=(1 - close / high) * 100 if high else None,
                above=(close / low - 1) * 100 if low else None,
            )
        )
    return sorted(rows, key=lambda row: (row["cap"] or 0), reverse=True)


@router.get("/market")
def us_market(user: CurrentUser):
    with lock:
        return vendor(market, int(time.time() // 1800))


def validate(ticker):
    if not SYMBOL.fullmatch(ticker) or ticker not in vendor(directory, datetime.now(ET).date()):
        raise HTTPException(404, "US listing not found")


@lru_cache(maxsize=128)
def bars(ticker, day):
    data = EODHDClient.from_env().eod(ticker + ".US", day - timedelta(days=1096), day)
    return [
        dict(
            date=x["date"],
            source="eodhd",
            open=clean(x.get("open")),
            high=clean(x.get("high")),
            low=clean(x.get("low")),
            close=clean(x.get("close")),
            adj_close=clean(x.get("adjusted_close")),
            volume=clean(x.get("volume")),
        )
        for x in data
        if clean(x.get("close"))
    ]


@lru_cache(maxsize=128)
def news(ticker, bucket):
    params = {"limit": 25}
    if ticker:
        params["s"] = ticker + ".US"
    else:
        params["s"] = "SPY.US"
    rows = EODHDClient.from_env()._get("/news", params)
    return [
        dict(title=r["title"], date=r["date"], url=r["link"])
        for r in rows or []
        if str(r.get("link", "")).startswith(("https://", "http://"))
    ]


@lru_cache(maxsize=128)
def options(ticker, bucket):
    day = datetime.now(ET).date()
    query = {
        "underlying_symbols": ticker.replace("-", "."),
        "expiration_date_gte": str(day),
        "expiration_date_lte": str(day + timedelta(days=60)),
        "limit": 1,
    }
    host = (
        "https://paper-api.alpaca.markets"
        if os.getenv("ALPACA_PAPER", "true").lower() != "false"
        else "https://api.alpaca.markets"
    )
    path = "/v2/options/contracts"
    first = alpaca(path, query, host).get("option_contracts") or []
    if not first:
        return {"expiry": None, "rows": []}
    expiry = first[0]["expiration_date"]
    contracts = {}
    q = {
        "underlying_symbols": query["underlying_symbols"],
        "expiration_date": expiry,
        "limit": 10000,
    }
    while True:
        data = alpaca(path, q, host)
        contracts.update({r["symbol"]: r for r in data.get("option_contracts", [])})
        if not data.get("next_page_token"):
            break
        q["page_token"] = data["next_page_token"]
    q = {"feed": "indicative", "expiration_date": expiry, "limit": 1000}
    snaps = {}
    while True:
        data = alpaca("/v1beta1/options/snapshots/" + query["underlying_symbols"], q)
        snaps.update(data.get("snapshots", {}))
        if not data.get("next_page_token"):
            break
        q["page_token"] = data["next_page_token"]
    rows = []
    for symbol, c in contracts.items():
        snap = snaps.get(symbol, {})
        rows.append(
            dict(
                symbol=symbol,
                strike=clean(c["strike_price"]),
                side=c["type"],
                oi=clean(c.get("open_interest")),
                oi_date=c.get("open_interest_date"),
                iv=clean(snap.get("impliedVolatility")),
                greeks=snap.get("greeks") or {},
            )
        )
    return {"expiry": expiry, "rows": sorted(rows, key=lambda x: (x["strike"], x["side"]))}


@router.get("/news")
def us_news(user: CurrentUser):
    return vendor(news, "", int(time.time() // 900))


@router.get("/stock/{ticker}/{panel}")
def stock(ticker: str, panel: str, user: CurrentUser):
    validate(ticker)
    if panel == "candles":
        return vendor(bars, ticker, datetime.now(ET).date())
    if panel == "news":
        return vendor(news, ticker, int(time.time() // 900))
    if panel == "options":
        return vendor(options, ticker, int(time.time() // 900))
    raise HTTPException(404, "Unknown panel")


def snapshots(symbols):
    raw = alpaca(
        "/v2/stocks/snapshots",
        {"feed": "iex", "symbols": ",".join(t.replace("-", ".") for t in symbols)},
    )
    return {
        t: {"price": trade["p"], "time": trade["t"], "source": "snapshot"}
        for t in symbols
        if (trade := raw.get(t.replace("-", "."), {}).get("latestTrade"))
    }


class Subscription(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=30)


tickets = {}


@router.post("/subscribe")
async def subscribe(body: Subscription, user: CurrentUser):
    for t in set(body.symbols):
        await run_in_threadpool(validate, t)
    now = time.monotonic()
    for key in list(tickets):
        if tickets[key][0] < now:
            tickets.pop(key, None)
    key = secrets.token_urlsafe(32)
    tickets[key] = (now + 20, list(dict.fromkeys(body.symbols)))
    return {"ticket": key}


@router.websocket("/stream")
async def stream(ws: WebSocket):
    await ws.accept()
    try:
        ticket = await asyncio.wait_for(ws.receive_text(), 5)
        grant = tickets.pop(ticket, None)
        if not grant or grant[0] < time.monotonic():
            await ws.close(1008)
            return
        symbols = grant[1]
        mapping = {t.replace("-", "."): t for t in symbols}
        until = time.monotonic() + 300
        initial = await run_in_threadpool(snapshots, symbols)
        await ws.send_json({"prices": initial, "mode": "IEX latest trade"})
        try:
            async with connect(
                "wss://stream.data.alpaca.markets/v2/iex", open_timeout=8
            ) as upstream:
                await upstream.recv()
                h = headers()
                await upstream.send(
                    json.dumps(
                        {
                            "action": "auth",
                            "key": h["APCA-API-KEY-ID"],
                            "secret": h["APCA-API-SECRET-KEY"],
                        }
                    )
                )
                reply = json.loads(await asyncio.wait_for(upstream.recv(), 8))
                if not any(x.get("msg") == "authenticated" for x in reply):
                    raise ValueError()
                await upstream.send(json.dumps({"action": "subscribe", "trades": list(mapping)}))
                while time.monotonic() < until:
                    try:
                        incoming = json.loads(await asyncio.wait_for(upstream.recv(), 10))
                    except TimeoutError:
                        await ws.send_json({"prices": {}, "mode": "IEX subscribed"})
                        continue
                    for x in incoming:
                        if x.get("T") == "error":
                            raise ValueError()
                        if x.get("T") == "t" and x.get("S") in mapping:
                            await ws.send_json(
                                {
                                    "prices": {
                                        mapping[x["S"]]: {
                                            "price": x["p"],
                                            "time": x["t"],
                                            "source": "tick",
                                        }
                                    },
                                    "mode": "IEX trades",
                                }
                            )
        except (WebSocketException, OSError, ValueError, TimeoutError):
            while time.monotonic() < until:
                await ws.send_json(
                    {
                        "prices": await run_in_threadpool(snapshots, symbols),
                        "mode": "IEX snapshots · 15 seconds",
                    }
                )
                await asyncio.sleep(15)
        await ws.close()
    except (WebSocketDisconnect, TimeoutError):
        pass
    except (httpx.HTTPError, RuntimeError):
        if ws.client_state.name == "CONNECTED":
            await ws.close(1011)


@router.get("/watchlist")
def watchlist(user: CurrentUser):
    from stock_agents.jobs.queue import _redis, redis_url

    saved = _redis(redis_url()).smembers("us:watchlist:" + str(user.id))
    return sorted(v.decode() if isinstance(v, bytes) else v for v in saved)


@router.put("/watchlist/{ticker}")
def follow(ticker: str, user: CurrentUser):
    from stock_agents.jobs.queue import _redis, redis_url

    validate(ticker)
    _redis(redis_url()).sadd("us:watchlist:" + str(user.id), ticker)
    return {"saved": True}


@router.delete("/watchlist/{ticker}")
def unfollow(ticker: str, user: CurrentUser):
    from stock_agents.jobs.queue import _redis, redis_url

    _redis(redis_url()).srem("us:watchlist:" + str(user.id), ticker)
    return {"saved": False}
