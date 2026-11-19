"""Read-only Angel One SmartAPI access and broker response normalization."""

from __future__ import annotations

import os
from uuid import getnode

import httpx

BASE = "https://apiconnect.angelone.in"
LOGIN = "/rest/auth/angelbroking/user/v1/loginByPassword"
HOLDINGS = "/rest/secure/angelbroking/portfolio/v1/getHolding"
TRADES = "/rest/secure/angelbroking/order/v1/getTradeBook"


class AngelOneError(Exception):
    pass


def local_ticker(symbol: str, exchange: str) -> str | None:
    if exchange.upper() != "NSE" or not symbol.upper().endswith("-EQ"):
        return None
    return symbol[:-3].upper()


def number(value) -> float | None:
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else None
    except (TypeError, ValueError):
        return None


def normalize_holdings(data) -> list[dict]:
    if not isinstance(data, list):
        return []
    result = []
    for row in data:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("tradingsymbol") or "")[:80]
        exchange = str(row.get("exchange") or "")[:12]
        if not symbol:
            continue
        result.append({"symbol": symbol, "ticker": local_ticker(symbol, exchange), "exchange": exchange,
            "isin": str(row.get("isin") or "")[:32] or None,
            "quantity": number(row.get("quantity")), "average_price": number(row.get("averageprice")),
            "broker_ltp": number(row.get("ltp")), "broker_pnl": number(row.get("profitandloss"))})
    return result


def normalize_trades(data) -> list[dict]:
    if not isinstance(data, list):
        return []
    result = []
    for row in data:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("tradingsymbol") or "")[:80]
        exchange = str(row.get("exchange") or "")[:12]
        if not symbol:
            continue
        result.append({"symbol": symbol, "ticker": local_ticker(symbol, exchange), "exchange": exchange,
            "side": str(row.get("transactiontype") or "")[:8],
            "quantity": number(row.get("fillsize")), "fill_price": number(row.get("fillprice")),
            "fill_time": str(row.get("filltime") or "")[:24], "fill_id": str(row.get("fillid") or "")[:64],
            "order_id": str(row.get("orderid") or "")[:64]})
    return result


def _data(response: httpx.Response, label: str):
    if response.status_code != 200:
        raise AngelOneError(f"Angel One {label} request failed")
    try:
        payload = response.json()
    except ValueError as exc:
        raise AngelOneError(f"Angel One {label} returned invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("status") is not True:
        raise AngelOneError(f"Angel One {label} was rejected")
    return payload.get("data")


async def fetch_snapshot(api_key: str, client_code: str, password: str, totp: str,
                         *, transport: httpx.AsyncBaseTransport | None = None) -> tuple[list[dict], list[dict]]:
    mac = ":".join(f"{(getnode() >> shift) & 255:02x}" for shift in (40, 32, 24, 16, 8, 0))
    headers = {"Content-Type": "application/json", "Accept": "application/json", "X-PrivateKey": api_key,
        "X-UserType": "USER", "X-SourceID": "WEB", "X-ClientLocalIP": "127.0.0.1",
        "X-ClientPublicIP": os.getenv("ANGEL_ONE_PUBLIC_IP", "127.0.0.1"), "X-MACAddress": mac}
    try:
        async with httpx.AsyncClient(base_url=BASE, headers=headers, timeout=12.0,
                                     follow_redirects=False, transport=transport) as client:
            login = _data(await client.post(LOGIN, json={"clientcode": client_code, "password": password, "totp": totp}), "login")
            token = login.get("jwtToken") if isinstance(login, dict) else None
            if not isinstance(token, str) or not token:
                raise AngelOneError("Angel One login did not return a session")
            client.headers["Authorization"] = f"Bearer {token}"
            holdings = _data(await client.get(HOLDINGS), "holdings")
            trades = _data(await client.get(TRADES), "trade book")
            return normalize_holdings(holdings), normalize_trades(trades)
    except httpx.HTTPError as exc:
        raise AngelOneError("Angel One is unavailable. Try again later") from exc
