"""Read NSE cash quotes using the Angel One SmartAPI instrument master and FULL feed."""

from __future__ import annotations

import base64
import hmac
import time
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import httpx

from stock_agents.common.config import load_settings
from stock_agents.sources.angel_one import BASE, LOGIN, AngelOneError, _data, smartapi_headers
from stock_agents.sources.nse import EQUITY_SERIES

MASTER = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
QUOTE = "/rest/secure/angelbroking/market/v1/quote"
BATCH_SIZE = 50
RETRYABLE = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class Instrument:
    ticker: str
    symbol: str
    token: str


def _totp(secret: str) -> str:
    """SmartAPI uses RFC 6238 SHA-1, six digits and a 30-second period."""
    encoded = "".join(secret.split()).upper().rstrip("=")
    try:
        key = base64.b32decode(encoded + "=" * (-len(encoded) % 8))
        if not key:
            raise ValueError()
    except ValueError:
        raise AngelOneError("Angel One TOTP secret must be a Base32 key") from None
    counter = (int(time.time()) // 30).to_bytes(8, "big")
    digest = hmac.digest(key, counter, "sha1")
    offset = digest[-1] & 15
    truncated = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return f"{truncated % 1_000_000:06d}"


def _request(
    client: httpx.Client, method: str, url: str, label: str, *, attempts: int = 1, **kwargs
) -> httpx.Response:
    for attempt in range(attempts):
        try:
            response = client.request(method, url, **kwargs)
        except httpx.HTTPError:
            if attempt + 1 == attempts:
                raise AngelOneError(f"Angel One {label} is unavailable") from None
        else:
            try:
                payload = response.json()
                throttled = isinstance(payload, dict) and payload.get("errorcode") == "AB1021"
            except ValueError:
                throttled = False
            if (response.status_code not in RETRYABLE and not throttled) or attempt + 1 == attempts:
                return response
            if throttled:
                time.sleep(15 * (attempt + 1))
                continue
        time.sleep(2**attempt)


def _index_instruments(rows) -> dict[str, Instrument]:
    if not isinstance(rows, list):
        raise AngelOneError("Invalid Angel One instrument master")
    by_ticker = defaultdict(set)
    by_token = defaultdict(set)
    for row in rows:
        if not isinstance(row, dict) or str(row.get("exch_seg")).upper() not in {"NSE", "NSE_CM"}:
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        ticker, _, series = symbol.rpartition("-")
        token = str(row.get("token") or "").strip()
        if ticker and series in EQUITY_SERIES and token.isascii() and token.isdecimal():
            instrument = Instrument(ticker, symbol, token)
            by_ticker[ticker].add(instrument)
            by_token[token].add(instrument)
    if not by_ticker:
        raise AngelOneError("Angel One master contains no NSE cash equities")
    # Never guess on a series change or an inconsistent token assignment.
    unique = {}
    for ticker, instruments in by_ticker.items():
        if len(instruments) == 1:
            instrument = next(iter(instruments))
            if len(by_token[instrument.token]) == 1:
                unique[ticker] = instrument
    return unique


@lru_cache(maxsize=1)
def _instrument_master(download_day: date) -> dict[str, Instrument]:
    """Cache only public NSE identifiers, refreshed each Indian calendar day."""
    with httpx.Client(timeout=25.0, follow_redirects=False) as public:
        response = _request(public, "GET", MASTER, "instrument master", attempts=2)
    if response.status_code != 200:
        raise AngelOneError("Angel One instrument master is unavailable")
    try:
        rows = response.json()
    except ValueError:
        raise AngelOneError("Invalid Angel One instrument master") from None
    return _index_instruments(rows)


def fetch_full_quotes(members: list[str], download_day: date) -> Iterator[tuple[Instrument, dict]]:
    master = _instrument_master(download_day)
    mapped = [master[ticker] for ticker in members if ticker in master]
    if not mapped:
        return
    with authenticated_client() as client:
        for offset in range(0, len(mapped), BATCH_SIZE):
            if offset:
                time.sleep(1)  # SmartAPI market-data quota: 50 instruments per second.
            batch = {inst.token: inst for inst in mapped[offset : offset + BATCH_SIZE]}
            response = _request(
                client,
                "POST",
                QUOTE,
                "quotes",
                attempts=3,
                json={"mode": "FULL", "exchangeTokens": {"NSE": list(batch)}},
            )
            data = _data(response, "quotes")
            if not isinstance(data, dict) or not isinstance(data.get("fetched"), list):
                raise AngelOneError("Invalid Angel One FULL quote response")
            for row in data["fetched"]:
                if not isinstance(row, dict):
                    continue
                inst = batch.get(str(row.get("symbolToken")))
                if (
                    inst
                    and row.get("exchange") == "NSE"
                    and row.get("tradingSymbol") == inst.symbol
                ):
                    yield inst, row


@contextmanager
def authenticated_client():
    settings = load_settings()
    secret = settings.env("ANGEL_ONE_TOTP_SECRET")
    if secret and settings.env("ANGEL_ONE_AUTH_MODE", "automatic") != "interactive":
        credentials = {name:(settings.env("ANGEL_ONE_"+name) or "").strip() for name in ("API_KEY","CLIENT_CODE","PIN")}
        if not all(credentials.values()):
            raise AngelOneError("Angel One credentials are not configured")
        with httpx.Client(base_url=BASE, timeout=12.0, follow_redirects=False, headers=smartapi_headers(credentials["API_KEY"])) as client:
            login = _data(_request(client,"POST",LOGIN,"login",json={"clientcode":credentials["CLIENT_CODE"],"password":credentials["PIN"],"totp":_totp(secret)}),"login")
            token = login.get("jwtToken") if isinstance(login,dict) else None
            if not isinstance(token,str) or not token:
                raise AngelOneError("Angel One login did not return a session")
            client.headers["Authorization"] = f"Bearer {token}"
            yield client
    else:
        from stock_agents.sources.angel_session import read_session
        session = read_session()
        if not session:
            raise AngelOneError("Reconnect Angel One in Admin using the current six-digit code")
        with httpx.Client(base_url=BASE,timeout=12.0,follow_redirects=False,headers=smartapi_headers(session["api_key"])) as client:
            client.headers["Authorization"] = "Bearer " + session["token"]
            yield client


HISTORY = "/rest/secure/angelbroking/historical/v1/getCandleData"


def fetch_daily_candles(members, day):
    """Official daily candles recover missed captures; they are not live trade ticks."""
    master = _instrument_master(day)
    with authenticated_client() as client:
        for index, ticker in enumerate(members):
            inst = master.get(ticker)
            if inst is None:
                continue
            if index:
                time.sleep(1.05)  # Stay below per-second and per-minute history limits.
            result = _data(_request(client,"POST",HISTORY,"historical candles",attempts=3,json={
                "exchange":"NSE","symboltoken":inst.token,"interval":"ONE_DAY",
                "fromdate":f"{day} 00:00","todate":f"{day} 23:59"}),"historical candles")
            if not isinstance(result,list):
                raise AngelOneError("Invalid Angel One daily candle response")
            for candle in result:
                if isinstance(candle,list) and len(candle)>=6 and str(candle[0])[:10]==str(day):
                    yield ticker,candle
