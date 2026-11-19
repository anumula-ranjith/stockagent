"""Read-only SmartAPI market panels and short-lived local watchlist subscriptions."""
import asyncio
import json
import struct
import re
import secrets
import time
from datetime import datetime, timedelta
from functools import lru_cache
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from stock_agents.api.auth import CurrentUser, Session
from stock_agents.api.personal import known_ticker, watchlist_for
from stock_agents.sources.angel_market import HISTORY, QUOTE, authenticated_client
from stock_agents.sources.angel_one import AngelOneError, _data, number
from stock_agents.storage.postgres import WatchlistItem

router = APIRouter(prefix="/market-feed")
ROOT = "/rest/secure/angelbroking/"
TZ = ZoneInfo("Asia/Kolkata")


def request(client, path, label, body=None):
    response = client.get(path) if body is None else client.post(path, json=body)
    return _data(response, label)


@lru_cache(maxsize=2048)
def contracts(exchange, ticker, day):
    with authenticated_client() as client:
        rows = request(client, ROOT+"order/v1/searchScrip", "instrument lookup",
                       {"exchange":exchange, "searchscrip":ticker})
    return [row for row in rows or [] if row.get("exchange")==exchange and str(row.get("symboltoken","")).isdigit()]


def equity(ticker, day):
    return next((r for r in contracts("NSE", ticker, day) if r["tradingsymbol"]==ticker+"-EQ"), None)


def quote_batch(tickers):
    # The public instrument master maps an entire list in a single download.
    from stock_agents.sources.angel_market import fetch_full_quotes
    rows = fetch_full_quotes(tickers, datetime.now(TZ).date())
    return {inst.ticker: {"price": number(row.get("ltp")), "time":row.get("exchTradeTime")}
            for inst,row in rows if number(row.get("ltp")) is not None}


@lru_cache(maxsize=512)
def candles(ticker, day, bucket):
    inst = equity(ticker, day)
    if not inst:
        return []
    with authenticated_client() as client:
        data = request(client, HISTORY, "daily candles", {"exchange":"NSE","symboltoken":inst["symboltoken"],
            "interval":"ONE_DAY","fromdate":f"{day-timedelta(days=730)} 00:00","todate":f"{day} 23:59"})
    bars = {}
    for row in data or []:
        if not isinstance(row,list) or len(row)<6:
            continue
        values = [number(v) for v in row[1:6]]
        if any(v is None for v in values) or min(values[:4])<=0:
            continue
        date = str(row[0])[:10]
        bars[date] = dict(zip(("open","high","low","close","volume"),values),date=date,source="angel_one")
    return [bars[key] for key in sorted(bars)]


@lru_cache(maxsize=512)
def derivatives(ticker, day, bucket):
    futures = []
    for row in contracts("NFO", ticker, day):
        match = re.fullmatch(re.escape(ticker)+r"(\d{2}[A-Z]{3}\d{2})FUT",row["tradingsymbol"])
        if match:
            expiry = datetime.strptime(match[1],"%d%b%y").date()
            if expiry >= day:
                futures.append((expiry,row["tradingsymbol"],row["symboltoken"]))
    if not futures:
        return {"contract":None}
    expiry,symbol,token = min(futures)
    result = {"contract":symbol,"expiry":str(expiry),"oi":None,"pcr":None,"greeks":[],"buildup":None,"unavailable":[]}
    with authenticated_client() as client:
        def optional(path, label, body=None):
            try:
                return request(client,path,label,body)
            except (AngelOneError,httpx.HTTPError):
                result["unavailable"].append(label)
                return None
        quotes = optional(QUOTE,"Futures quote",{"mode":"FULL","exchangeTokens":{"NFO":[token]}})
        for row in (quotes or {}).get("fetched",[]):
            if str(row.get("symbolToken"))==token:
                result["oi"]=number(row.get("opnInterest"))
        for row in optional(ROOT+"marketData/v1/putCallRatio","Put/call ratio") or []:
            if row.get("tradingSymbol")==symbol:
                result["pcr"]=number(row.get("pcr"))
        greeks = optional(ROOT+"marketData/v1/optionGreek","Option Greeks",
                          {"name":ticker,"expirydate":expiry.strftime("%d%b%Y").upper()})
        result["greeks"] = [row for row in greeks or [] if row.get("name")==ticker and
                            row.get("expiry")==expiry.strftime("%d%b%Y").upper()]
        for kind in ("Long Built Up","Short Built Up","Short Covering","Long Unwinding"):
            rows = optional(ROOT+"marketData/v1/OIBuildup","OI buildup "+kind,{"expirytype":"NEAR","datatype":kind})
            if any(r.get("tradingSymbol")==symbol for r in rows or []):
                result["buildup"]=kind
                break
            time.sleep(1)
    return result


@router.get("/stock/{ticker}/{section}")
async def stock_market(ticker:str, section:str, user:CurrentUser, session:Session):
    ticker = await known_ticker(session,ticker)
    day = datetime.now(TZ).date()
    try:
        if section=="quote":
            rows = await run_in_threadpool(quote_batch,[ticker])
            return rows.get(ticker)
        if section=="candles":
            return await run_in_threadpool(candles,ticker,day,int(time.time()//300))
        if section=="derivatives":
            return await run_in_threadpool(derivatives,ticker,day,int(time.time()//300))
    except (AngelOneError,httpx.HTTPError) as exc:
        raise HTTPException(503,str(exc) if isinstance(exc,AngelOneError) else "Angel One unavailable") from None
    raise HTTPException(404,"Unknown market panel")


async def broker_ticks(socket, tickers, until):
    from websockets.asyncio.client import connect
    from websockets.exceptions import WebSocketException
    from stock_agents.sources.angel_market import _instrument_master
    from stock_agents.sources.angel_session import read_session

    session = await run_in_threadpool(read_session)
    if not session or not session.get("feed_token") or not session.get("client_code"):
        return False
    master = await run_in_threadpool(_instrument_master, datetime.now(TZ).date())
    symbols = {master[t].token:t for t in tickers if t in master}
    if not symbols:
        return False
    headers = {"Authorization":session["token"],"x-api-key":session["api_key"],
               "x-client-code":session["client_code"],"x-feed-token":session["feed_token"]}
    try:
        async with connect("wss://smartapisocket.angelone.in/smart-stream", additional_headers=headers,
                           open_timeout=8, ping_interval=10) as feed:
            await feed.send(json.dumps({"action":1,"params":{"mode":1,"tokenList":[
                {"exchangeType":1,"tokens":list(symbols)}]}}))
            latest = await run_in_threadpool(quote_batch,tickers)
            await socket.send_json({"quotes":latest,"mode":"awaiting_tick"})
            last_flush = time.monotonic()
            received_tick = False
            while time.monotonic()<until:
                try:
                    packet = await asyncio.wait_for(feed.recv(),1)
                except TimeoutError:
                    packet = None
                if isinstance(packet,bytes) and len(packet)>=51 and packet[:2]==bytes((1,1)):
                    ticker = symbols.get(packet[2:27].split(b"\0",1)[0].decode("ascii"))
                    stamp,paise = struct.unpack_from("<qq",packet,35)
                    if ticker and paise>0 and stamp>0:
                        latest[ticker]={"source":"tick","price":paise/100,"time":datetime.fromtimestamp(stamp/1000,TZ).strftime("%d-%b-%Y %H:%M:%S")}
                        received_tick = True
                        await socket.send_json({"quotes":{ticker:latest[ticker]},"mode":"ticks","delta":True})
                        last_flush=time.monotonic()
                elif isinstance(packet,str) and packet.startswith("{") and "error" in packet.lower():
                    return False
                if time.monotonic()-last_flush>=10:
                    await socket.send_json({"quotes":latest,"mode":"ticks" if received_tick else "awaiting_tick"})
                    last_flush=time.monotonic()
            return True
    except (WebSocketException,OSError,TimeoutError):
        return False


tickets = {}


@router.post("/watchlist/{list_id}")
async def subscribe(list_id:UUID,user:CurrentUser,session:Session):
    watchlist = await watchlist_for(session,user.id,list_id)
    tickers = list(await session.scalars(select(WatchlistItem.ticker).where(WatchlistItem.watchlist_id==watchlist.id)))
    return issue_ticket(tickers)


@router.post("/subscribe/{ticker}")
async def subscribe_stock(ticker:str,user:CurrentUser,session:Session):
    return issue_ticket([await known_ticker(session,ticker)])


def issue_ticket(tickers):
    now = time.monotonic()
    for key in list(tickets):
        if tickets[key][0]<now:
            tickets.pop(key,None)
    ticket = secrets.token_urlsafe(32)
    tickets[ticket]=(now+20,tickers)
    return {"ticket":ticket}


@router.websocket("/stream")
async def stream(socket:WebSocket):
    await socket.accept()
    try:
        hello = await asyncio.wait_for(socket.receive_text(),5)
        grant = tickets.pop(hello,None)
        if not grant or grant[0]<time.monotonic():
            await socket.close(1008)
            return
        until = time.monotonic()+300
        if await broker_ticks(socket,grant[1],until):
            await socket.close()
            return
        while time.monotonic()<until:
            try:
                quotes = await run_in_threadpool(quote_batch,grant[1])
                await socket.send_json({"quotes":quotes})
            except (AngelOneError,httpx.HTTPError):
                await socket.send_json({"error":"Angel One quotes unavailable"})
            try:
                await asyncio.wait_for(socket.receive_text(),10)
                break
            except TimeoutError:
                pass
        await socket.close()
    except (WebSocketDisconnect,TimeoutError):
        pass
