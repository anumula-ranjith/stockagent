from datetime import date

import httpx
from fakeredis import FakeRedis
from sqlalchemy import text

from stock_agents.ingest import angel_eod, nse_short_selling
from stock_agents.sources import angel_session


def test_connection_api_requires_admin_and_rejects_bad_code(auth_database,monkeypatch):
    from contextlib import asynccontextmanager
    from uuid import uuid4

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from stock_agents.api import admin, auth
    from stock_agents.storage.postgres import User, dispose_engine
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            await dispose_engine()
    app=FastAPI(lifespan=lifespan)
    app.include_router(admin.router)
    calls=[]
    monkeypatch.setattr(angel_session,"connect_code",lambda code:calls.append(code) or {"connected":True})
    with TestClient(app) as client:
        assert client.post('/admin/angel-one/connect',json={"code":"123456"}).status_code==401
        user=auth.UserOut(id=str(uuid4()),email="admin@test.example",is_admin=False,email_verified=True)
        app.dependency_overrides[auth.get_current_user]=lambda:user
        assert client.post('/admin/angel-one/connect',json={"code":"123456"}).status_code==403
        with auth_database.begin() as conn:
            conn.execute(User.__table__.insert().values(id=user.id,email=user.email,is_admin=True))
        user.is_admin=True
        assert client.post('/admin/angel-one/connect',json={"code":"abcdef"}).status_code==422
        assert not calls
        assert client.post('/admin/angel-one/connect',json={"code":"123456"}).json()["connected"]
        assert calls==["123456"]


def test_session_encrypts_token_and_discards_code(monkeypatch):
    redis=FakeRedis()
    monkeypatch.setattr(angel_session,"_redis",lambda _:redis)
    monkeypatch.setenv("JWT_SECRET","test-secret-"*6)
    for suffix in ("API_KEY","CLIENT_CODE","PIN"):
        monkeypatch.setenv("ANGEL_ONE_"+suffix,"test-value")
    client=httpx.Client
    monkeypatch.setattr(angel_session.httpx,"Client",lambda **kw:client(transport=httpx.MockTransport(
        lambda req:httpx.Response(200,json={"status":True,"data":{"jwtToken":"private-token"}})),**kw))
    result=angel_session.connect_code("123456")
    assert result["connected"] and result["expires_at"]
    stored=redis.get(angel_session.KEY)
    assert b"123456" not in stored and b"private-token" not in stored
    assert angel_session.read_session()["token"]=="private-token"
    assert "123456" not in str(angel_session.read_session())
    assert 0<redis.ttl(angel_session.KEY)<=86400


def test_short_selling_only_checks_sessions_and_checkpoints_empty_reports(auth_database,monkeypatch):
    calls=[]
    monkeypatch.setattr(nse_short_selling,"_fetch_report",lambda day,symbols:(calls.append(day) or ("ok",[],0)))
    result=nse_short_selling.refresh_short_selling(date(2026,11,13),date(2026,11,16))
    assert calls==[date(2026,11,13),date(2026,11,16)]
    assert result["status"]=="ok" and result["non_trading_days"]==2
    calls.clear()
    assert nse_short_selling.refresh_short_selling(date(2026,11,13),date(2026,11,16))["already_loaded"]==2
    assert not calls


def test_missing_trading_day_report_remains_partial_and_retryable(auth_database,monkeypatch):
    monkeypatch.setattr(nse_short_selling,"_fetch_report",lambda *args:("unavailable",[],0))
    result=nse_short_selling.refresh_short_selling(date(2026,11,16),date(2026,11,16))
    assert result["status"]=="partial" and result["errors"]
    monkeypatch.setattr(nse_short_selling,"_fetch_report",lambda *args:("ok",[],0))
    assert nse_short_selling.refresh_short_selling(date(2026,11,16),date(2026,11,16))["status"]=="ok"


def test_history_recovery_does_not_invent_trade_timestamp_or_adjustment(auth_database,monkeypatch):
    day=date(2026,11,18)
    with auth_database.begin() as conn:
        conn.execute(text("INSERT INTO symbology(ticker,active) VALUES ('ABC',true)"))
        conn.execute(text("INSERT INTO index_membership(index_code,ticker,joined_on,known_on) VALUES ('NIFTY500','ABC','2026-01-01','2026-01-01')"))
        monkeypatch.setattr(angel_eod,"fetch_daily_candles",lambda *args:iter([("ABC",[str(day)+"T00:00:00+05:30",100,110,95,105,1500])]))
        result=angel_eod.refresh_angel_eod(conn,day)
        assert result["status"]=="ok" and not result["live_capture_reconstructed"]
        row=conn.execute(text("select exchange_trade_at,adj_close,close from prices_daily where ticker='ABC'")).one()
        assert row.exchange_trade_at is None and row.adj_close is None and row.close==105
        assert angel_eod.refresh_angel_eod(conn,day)["reused"]


def test_broker_outage_uses_validated_exchange_source(auth_database,monkeypatch):
    from unittest.mock import Mock

    from stock_agents.sources.angel_one import AngelOneError
    def unavailable(*args):
        raise AngelOneError("Historical requests throttled")
    monkeypatch.setattr(angel_eod,"fetch_daily_candles",unavailable)
    client=Mock()
    client.bhavcopy.return_value={"ABC":{"open":100,"high":110,"low":95,"close":105,"volume":1500}}
    monkeypatch.setattr(angel_eod,"NSEClient",lambda:client)
    with auth_database.begin() as conn:
        conn.execute(text("INSERT INTO symbology(ticker,active) VALUES ('ABC',true)"))
        conn.execute(text("INSERT INTO index_membership(index_code,ticker,joined_on,known_on) VALUES ('NIFTY500','ABC','2026-01-01','2026-01-01')"))
        result=angel_eod.refresh_angel_eod(conn,date(2026,11,18))
        assert result["status"]=="ok" and result["nse_fallback_bars"]==1 and result["angel_one_bars"]==0
        assert conn.scalar(text("SELECT source FROM prices_daily WHERE ticker='ABC'"))=="nse_bhavcopy"
