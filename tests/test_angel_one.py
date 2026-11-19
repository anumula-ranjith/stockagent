import asyncio

import httpx
import pytest

from stock_agents.sources.angel_one import (
    AngelOneError,
    fetch_snapshot,
    normalize_holdings,
    normalize_trades,
)


def test_normalize_broker_equities_without_inventing_local_tickers():
    holdings = normalize_holdings([{"tradingsymbol": "RELIANCE-EQ", "exchange": "NSE", "quantity": 2,
        "averageprice": 1200, "ltp": 1363, "profitandloss": 326},
        {"tradingsymbol": "NIFTY26NOVFUT", "exchange": "NFO", "quantity": 1}])
    assert holdings[0]["ticker"] == "RELIANCE"
    assert holdings[1]["ticker"] is None
    assert normalize_trades([{"tradingsymbol": "RELIANCE-EQ", "exchange": "NSE", "fillsize": "2",
        "fillprice": "1200.5", "transactiontype": "BUY", "fillid": "42"}])[0]["quantity"] == 2


def test_read_only_paths_and_no_secret_persistence():
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("loginByPassword"):
            return httpx.Response(200, json={"status": True, "data": {"jwtToken": "session-token"}})
        assert request.headers["authorization"] == "Bearer session-token"
        if request.url.path.endswith("getHolding"):
            return httpx.Response(200, json={"status": True, "data": [{"tradingsymbol": "ITC-EQ", "exchange": "NSE", "quantity": 3}]})
        return httpx.Response(200, json={"status": True, "data": []})

    holdings, trades = asyncio.run(fetch_snapshot("api-key", "A123", "pin", "123456",
        transport=httpx.MockTransport(handler)))
    assert [path.rsplit("/", 1)[-1] for _, path in calls] == ["loginByPassword", "getHolding", "getTradeBook"]
    assert all(method == "GET" for method, _ in calls[1:])
    assert holdings[0]["ticker"] == "ITC" and trades == []
    assert "session-token" not in str(holdings)


def test_failed_login_does_not_fetch_holdings():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"status": False, "message": "Rejected"})

    with pytest.raises(AngelOneError, match="login was rejected"):
        asyncio.run(fetch_snapshot("api-key", "A123", "pin", "123456", transport=httpx.MockTransport(handler)))
    assert len(calls) == 1
