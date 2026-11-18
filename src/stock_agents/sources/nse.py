"""Official NSE constituent, F&O eligibility, and final cash-market files."""

from __future__ import annotations

import csv
import io
import math
import zipfile
from datetime import date

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

NSE_ARCHIVE = "https://nsearchives.nseindia.com"
NIFTY500_URL = NSE_ARCHIVE + "/content/indices/ind_nifty500list.csv"
NSE_LOT_SIZES = NSE_ARCHIVE + "/content/fo/fo_mktlots.csv"
EQUITY_SERIES = {"EQ", "BE", "BZ", "RR", "ST"}


class EODNotReady(RuntimeError):
    """The exact trading day's final exchange file is unavailable."""


def parse_fo_tickers(payload: str) -> dict[str, str]:
    rows = csv.reader(payload.lstrip("\ufeff").splitlines())
    for row in rows:
        if len(row) >= 2 and row[0].strip().casefold() == "derivatives on individual securities":
            if row[1].strip().casefold() == "symbol":
                break
    else:
        raise ValueError("NSE lot-size CSV is missing its Derivatives on Individual Securities header.")
    tickers = {}
    for row in rows:
        if len(row) < 2 or not row[0].strip() or not row[1].strip():
            continue
        ticker = row[1].strip().upper()
        if ticker in tickers:
            raise ValueError("NSE F&O list contains duplicate symbols")
        tickers[ticker] = row[0].strip()
    if not tickers:
        raise ValueError("NSE lot-size CSV has no individual securities.")
    return tickers


def parse_nifty500(payload: str) -> dict[str, dict]:
    reader = csv.DictReader(io.StringIO(payload.lstrip("\ufeff")))
    required = {"Company Name", "Industry", "Symbol", "Series", "ISIN Code"}
    if not required.issubset(reader.fieldnames or ()):
        raise ValueError("Nifty 500 CSV has an unexpected schema")
    members = {}
    for row in reader:
        ticker = row["Symbol"].strip().upper()
        if not ticker or ticker in members:
            raise ValueError("Nifty 500 CSV contains empty or duplicate symbols")
        members[ticker] = {
            "name": row["Company Name"].strip(),
            "industry": row["Industry"].strip(),
            "isin": row["ISIN Code"].strip(),
            "series": row["Series"].strip(),
        }
    return members


def parse_bhavcopy(payload: str, trade_date: date) -> dict[str, dict]:
    reader = csv.DictReader(io.StringIO(payload.lstrip("\ufeff")))
    required = {"TradDt", "TckrSymb", "SctySrs", "ISIN", "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol"}
    if not required.issubset(reader.fieldnames or ()):
        raise ValueError("NSE Bhavcopy has an unexpected schema")
    result = {}
    for row in reader:
        if row["TradDt"] != trade_date.isoformat():
            raise ValueError("NSE Bhavcopy date differs from the requested date")
        if row["SctySrs"] not in EQUITY_SERIES:
            continue
        ticker = row["TckrSymb"].strip()
        values = [float(row[key]) for key in ("OpnPric", "HghPric", "LwPric", "ClsPric")]
        volume = int(row["TtlTradgVol"])
        if not all(math.isfinite(v) and v >= 0 for v in values) or volume < 0:
            raise ValueError(f"Invalid NSE price for {ticker}")
        opening, high, low, close = values
        # Suspended/no-trade securities can have zero OHLC and a carried close.
        if volume and not low <= min(opening, close) <= max(opening, close) <= high:
            raise ValueError(f"Inconsistent NSE OHLC for {ticker}")
        if ticker in result:
            raise ValueError(f"Multiple regular equity series for {ticker}")
        result[ticker] = {
            "ticker": ticker, "date": trade_date, "open": opening, "high": high,
            "low": low, "close": close, "adj_close": None, "volume": volume,
            "source": "nse_bhavcopy", "isin": row["ISIN"], "series": row["SctySrs"],
        }
    if not result:
        raise ValueError("NSE Bhavcopy contains no equity records")
    return result


class NSEClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com/"})
        retries = Retry(total=3, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504))
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    def close(self) -> None:
        self.session.close()

    def _get(self, url: str) -> requests.Response:
        response = self.session.get(url, timeout=(10, 30))
        if response.status_code == 404:
            raise EODNotReady("NSE final file is not published for the requested date")
        response.raise_for_status()
        return response

    def nifty500(self) -> dict[str, dict]:
        members = parse_nifty500(self._get(NIFTY500_URL).content.decode("utf-8-sig"))
        if not 480 <= len(members) <= 550:
            raise ValueError("Nifty 500 snapshot size is outside the expected range")
        return members

    def fo_stocks(self) -> dict[str, str]:
        members = parse_fo_tickers(self._get(NSE_LOT_SIZES).content.decode("utf-8-sig"))
        if not 100 <= len(members) <= 500:
            raise ValueError("NSE F&O snapshot size is outside the expected range")
        return members

    def bhavcopy(self, trade_date: date) -> dict[str, dict]:
        url = NSE_ARCHIVE + f"/content/cm/BhavCopy_NSE_CM_0_0_0_{trade_date:%Y%m%d}_F_0000.csv.zip"
        response = self._get(url)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if len(names) != 1:
                raise ValueError("Unexpected NSE Bhavcopy archive")
            return parse_bhavcopy(archive.read(names[0]).decode("utf-8-sig"), trade_date)
