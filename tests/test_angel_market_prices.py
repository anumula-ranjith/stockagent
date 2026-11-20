import json
from datetime import date

import duckdb
import httpx
import pytest
from sqlalchemy import create_engine, select

from scripts.migrate_duckdb_to_postgres import _source_rows
from stock_agents.ingest import angel_prices
from stock_agents.sources import angel_market
from stock_agents.sources.angel_one import AngelOneError
from stock_agents.storage.postgres import Base

DAY = date(2025, 1, 2)


def instrument(ticker, token, segment="NSE", series="EQ"):
    return {"exch_seg": segment, "symbol": f"{ticker}-{series}", "token": str(token)}


def quote(ticker="M&M", token="1", **fields):
    return {
        "exchange": "NSE",
        "tradingSymbol": f"{ticker}-EQ",
        "symbolToken": token,
        "open": 101,
        "high": 108,
        "low": 99,
        "close": 100,
        "ltp": 107,
        "tradeVolume": 450,
        "exchTradeTime": "02-Jan-2025 15:20:02",
        **fields,
    }


def test_instrument_map_preserves_symbols_and_requires_unambiguous_nse_cash_tokens():
    rows = [
        instrument("M&M", 1),
        instrument("M&M", 1, "NFO"),
        instrument("M&M", 80, "BSE"),
        instrument("FUT", 2, "NFO"),
        instrument("BE-ONLY", 3, "nse_cm", "BE"),
        instrument("CONFLICT", 4),
        instrument("CONFLICT", 5),
        instrument("CLASH", 7),
        instrument("SECOND", 7),
        instrument("FUT", 8, series="FUT"),
    ]
    result = angel_market._index_instruments(rows)
    assert set(result) == {"M&M", "BE-ONLY"}
    assert result["BE-ONLY"].symbol == "BE-ONLY-BE"
    assert result["M&M"].token == "1"


def test_authenticated_batches_retry_only_reads_and_keep_master_public(monkeypatch):
    monkeypatch.setattr(angel_market.time, "time", lambda: 59)
    sleeps = []
    monkeypatch.setattr(angel_market.time, "sleep", sleeps.append)
    for name, val in {
        "API_KEY": "test-key",
        "CLIENT_CODE": "test-client",
        "PIN": "0123",
        "TOTP_SECRET": "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ",
    }.items():
        monkeypatch.setenv("ANGEL_ONE_" + name, val)
    members = ["T" + str(i) for i in range(51)]
    batches = []
    paths = []

    def handler(request):
        paths.append((request.method, request.url.path))
        if str(request.url) == angel_market.MASTER:
            assert "X-PrivateKey" not in request.headers and "Authorization" not in request.headers
            return httpx.Response(200, json=[instrument(t, i) for i, t in enumerate(members, 1)])
        assert request.headers["X-PrivateKey"] == "test-key"
        body = json.loads(request.content)
        if request.url.path == angel_market.LOGIN:
            assert body == {"clientcode": "test-client", "password": "0123", "totp": "287082"}
            return httpx.Response(200, json={"status": True, "data": {"jwtToken": "private-jwt"}})
        assert request.url.path == angel_market.QUOTE and body["mode"] == "FULL"
        assert request.headers["Authorization"] == "Bearer private-jwt"
        tokens = body["exchangeTokens"]["NSE"]
        batches.append(tokens)
        if len(batches) == 1:
            return httpx.Response(429)
        rows = [quote(members[int(t) - 1], t) for t in tokens]
        rows.extend([quote("WRONG", tokens[0]), quote("T0", "999")])
        return httpx.Response(
            200, json={"status": True, "data": {"fetched": rows, "unfetched": []}}
        )

    client = httpx.Client
    monkeypatch.setattr(
        angel_market.httpx,
        "Client",
        lambda **kw: client(transport=httpx.MockTransport(handler), **kw),
    )
    angel_market._instrument_master.cache_clear()
    try:
        result = list(angel_market.fetch_full_quotes(members, DAY))
    finally:
        angel_market._instrument_master.cache_clear()
    assert [len(b) for b in batches] == [50, 50, 1] and batches[0] == batches[1]
    assert [inst.ticker for inst, _ in result] == members
    assert [method for method, _ in paths] == ["GET", "POST", "POST", "POST", "POST"]
    assert sleeps == [1, 1]


def test_rejected_credentials_are_sanitized_and_never_retried(monkeypatch):
    for suffix in ("API_KEY", "CLIENT_CODE", "PIN", "TOTP_SECRET"):
        monkeypatch.setenv("ANGEL_ONE_" + suffix, "JBSWY3DPEHPK3PXP")
    monkeypatch.setattr(
        angel_market,
        "_instrument_master",
        lambda _: {"ABC": angel_market.Instrument("ABC", "ABC-EQ", "1")},
    )
    calls = []

    def reject(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"status": False, "message": "sensitive provider payload"})

    client = httpx.Client
    monkeypatch.setattr(
        angel_market.httpx,
        "Client",
        lambda **kw: client(transport=httpx.MockTransport(reject), **kw),
    )
    with pytest.raises(AngelOneError, match="login was rejected") as failure:
        list(angel_market.fetch_full_quotes(["ABC"], DAY))
    assert "sensitive" not in str(failure.value)
    assert calls == [angel_market.LOGIN]


@pytest.mark.parametrize(
    "fields",
    [
        {"exchTradeTime": "01-Jan-2025 15:20:00", "exchFeedTime": "02-Jan-2025 15:20:10"},
        {"exchTradeTime": None},
        {"tradeVolume": "12.5"},
        {"tradeVolume": 0},
        {"ltp": 150},
        {"ltp": True},
        {"high": float("inf")},
        {"open": float("nan")},
    ],
)
def test_stale_malformed_or_untraded_quotes_never_create_bars(fields):
    assert angel_prices._bar("M&M", quote(**fields), DAY, DAY) is None


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_partial_refresh_preserves_eod_and_retries_fill_only_valid_newer_bars(
    monkeypatch, request, backend
):
    engine = (
        create_engine("sqlite://")
        if backend == "sqlite"
        else request.getfixturevalue("auth_database")
    )
    prices = Base.metadata.tables["prices_daily"]
    sym = Base.metadata.tables["symbology"]
    membership = Base.metadata.tables["index_membership"]
    inst = angel_market.Instrument("M&M", "M&M-EQ", "1")
    second = angel_market.Instrument("FO", "FO-EQ", "2")
    rounds = [
        [(inst, quote()), (second, quote(exchTradeTime="01-Jan-2025 15:29:30"))],
        [(inst, quote(exchTradeTime="02-Jan-2025 15:19:30", ltp=100)), (second, quote())],
        [(inst, quote()), (second, quote())],
        [(inst, quote(exchTradeTime="02-Jan-2025 15:21:01", ltp=106))],
    ]

    def fetch(members, _):
        assert members == ["FO", "M&M"]
        return rounds.pop(0)

    monkeypatch.setattr(angel_prices, "fetch_full_quotes", fetch)
    with engine.begin() as conn:
        for table in (sym, membership, prices):
            table.create(conn, checkfirst=True)
        for ticker, group, active in (
            ("M&M", "NIFTY500", True),
            ("FO", "NSE_FO", True),
            ("OTHER", "NIFTY50", True),
            ("INACTIVE", "NSE_FO", False),
            ("DUMMYHEG", "NIFTY500", True),
        ):
            conn.execute(sym.insert().values(ticker=ticker, active=active))
            conn.execute(
                membership.insert().values(
                    ticker=ticker, index_code=group, known_on=DAY, joined_on=DAY
                )
            )
        conn.execute(
            prices.insert().values(
                ticker="M&M", date=DAY, known_date=DAY, close=103, adj_close=102.5, source="eodhd"
            )
        )
        first = angel_prices.refresh_angel_prices(conn, DAY)
        assert (first["status"], first["missing"], first["written"]) == ("partial", ["FO"], 1)
        second_run = angel_prices.refresh_angel_prices(conn, DAY)
        assert (second_run["status"], second_run["priced"], second_run["written"]) == ("ok", 2, 1)
        assert angel_prices.refresh_angel_prices(conn, DAY)["written"] == 0
        row = (
            conn.execute(
                select(prices).where(prices.c.ticker == "M&M", prices.c.source == "angel_one")
            )
            .mappings()
            .one()
        )
        assert row["close"] == 107 and row["adj_close"] is None
        assert row["date"] == DAY and row["exchange_trade_at"].minute == 20
        assert angel_prices.refresh_angel_prices(conn, DAY)["written"] == 1
        prices_by_source = dict(
            conn.execute(
                select(prices.c.source, prices.c.close).where(prices.c.ticker == "M&M")
            ).all()
        )
        assert prices_by_source == {"eodhd": 103, "angel_one": 106}
        conn.execute(sym.update().where(~sym.c.ticker.startswith("DUMMY")).values(active=False))
        with pytest.raises(ValueError, match="No active Nifty 500"):
            angel_prices.refresh_angel_prices(conn, DAY)


def test_legacy_duckdb_import_supplies_null_exchange_time():
    table = Base.metadata.tables["prices_daily"]
    with duckdb.connect(":memory:") as source:
        source.execute("CREATE TABLE prices_daily AS SELECT 'X' ticker, DATE '2025-01-02' date")
        assert list(_source_rows(source, table, ["ticker", "exchange_trade_at"])) == [("X", None)]
