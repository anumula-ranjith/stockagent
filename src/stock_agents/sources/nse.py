"""Official NSE constituent, F&O eligibility, and final cash-market files."""

from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from datetime import date, datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

NSE_ARCHIVE = "https://nsearchives.nseindia.com"
NIFTY500_URL = NSE_ARCHIVE + "/content/indices/ind_nifty500list.csv"
NSE_LOT_SIZES = NSE_ARCHIVE + "/content/fo/fo_mktlots.csv"
EQUITY_SERIES = {"EQ", "BE", "BZ", "RR", "ST"}
NSE_ACTIONS = "https://www.nseindia.com/api/corporates-corporateActions"
MONEY = r"(?:Rs\.?|Re\.?|INR|₹)\s*([\d,]+(?:\.\d+)?)"


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


def parse_previous_closes(payload: str, trade_date: date) -> dict[str, dict]:
    """Read the ex-date file's published prior close, excluding unusable values."""
    reader = csv.DictReader(io.StringIO(payload.lstrip("\ufeff")))
    required = {"TradDt", "TckrSymb", "SctySrs", "ISIN", "PrvsClsgPric"}
    if not required.issubset(reader.fieldnames or ()):
        raise ValueError("NSE Bhavcopy previous-close schema is unexpected")
    result, seen = {}, set()
    for row in reader:
        if row["TradDt"] != trade_date.isoformat():
            raise ValueError("NSE Bhavcopy date differs from the requested date")
        if row["SctySrs"] not in EQUITY_SERIES:
            continue
        ticker, isin = row["TckrSymb"].strip(), row["ISIN"].strip()
        if not re.fullmatch(r"[A-Z0-9&._-]+", ticker) or not re.fullmatch(r"[A-Z0-9]{12}", isin):
            raise ValueError("Invalid NSE Bhavcopy security identity")
        if ticker in seen:
            raise ValueError(f"Multiple regular equity series for {ticker}")
        seen.add(ticker)
        try:
            close = float(row["PrvsClsgPric"])
        except (ValueError, TypeError):
            continue
        if math.isfinite(close) and close > 0:
            result[ticker] = {"close": close, "isin": isin}
    return result


def parse_corporate_actions(payload, symbol: str, start: date, end: date, isin: str) -> list[dict]:
    """Normalize supported exchange actions without inferring missing adjustments."""
    if start > end:
        raise ValueError("Invalid corporate-action date range")
    if not isinstance(payload, list):
        raise ValueError("NSE corporate actions must be a list")
    actions = {}
    for row in payload:
        if not isinstance(row, dict) or row.get("symbol") != symbol or row.get("isin") != isin:
            raise ValueError("NSE corporate-action identity does not match the requested symbol/ISIN")
        day = datetime.strptime(row["exDate"], "%d-%b-%Y").date()
        if not start <= day <= end:
            raise ValueError("NSE corporate-action date lies outside the requested range")
        subject = row.get("subject", "").strip()
        distribution = re.match(r"Distribution\s*-\s*" + MONEY + r"\s*Per\s+Unit\b", subject, re.I)
        dividend = re.fullmatch(
            r"(?:(?:Annual General Meeting|AGM)\s*/\s*)?"
            r"(?:(?:Interim|Final|Special)\s+)?Dividend\s*-\s*" + MONEY + r"\s*(?:/-)?\s*Per\s+Share\.?",
            subject, re.I,
        )
        split = re.fullmatch(
            r"Face Value Split\s*\(Sub-Division\)\s*-\s*From\s*" + MONEY +
            r"\s*(?:/-)?\s*Per Share\s*To\s*" + MONEY + r"\s*(?:/-)?\s*Per Share\.?",
            subject, re.I,
        )
        bonus = re.fullmatch(r"Bonus(?: Issue)?\s*[-:]?\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", subject, re.I)
        if distribution:
            if re.search(r"\b(?:bonus|demerger|split|rights)\b", subject, re.I):
                raise ValueError(f"Unsupported compound NSE corporate action for {symbol}: {subject}")
            kind = "distribution"
            value = float(distribution.group(1).replace(",", ""))
            amounts = [float(amount.replace(",", "")) for amount in re.findall(MONEY, subject, re.I)]
            if len(amounts) > 1 and not math.isclose(value, sum(amounts[1:]), rel_tol=1e-7, abs_tol=0.0001):
                raise ValueError("NSE distribution components differ from the declared total")
        elif dividend:
            kind, value = "dividend", float(dividend.group(1).replace(",", ""))
        elif split:
            old_face, new_face = (float(amount.replace(",", "")) for amount in split.groups())
            if new_face <= 0:
                raise ValueError("Invalid NSE split denominator")
            kind, value = "split", old_face / new_face
        elif bonus:
            added, held = map(float, bonus.groups())
            if held <= 0:
                raise ValueError("Invalid NSE bonus denominator")
            kind, value = "bonus", added / held
        else:
            raise ValueError(f"Unsupported NSE corporate action for {symbol}: {subject}")
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Invalid NSE corporate-action amount/ratio")
        key = (day, kind)
        if key in actions:
            raise ValueError("NSE corporate actions contain a duplicate date/type")
        actions[key] = dict(ex_date=day, action_type=kind, value=value, subject=subject)
    return sorted(actions.values(), key=lambda action: (action["ex_date"], action["action_type"]))


class NSEClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://www.nseindia.com/", "Accept": "application/json,text/plain,*/*",
        })
        self._action_session_initialized = False
        self._bhavcopy_cache: dict[date, str] = {}
        retries = Retry(total=3, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504))
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    def close(self) -> None:
        self.session.close()
        self._bhavcopy_cache.clear()

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

    def index_constituents(self, suffix: str, minimum: int) -> dict[str, dict]:
        url = f"https://www.niftyindices.com/IndexConstituent/ind_nifty{suffix}list.csv"
        members = parse_nifty500(self._get(url).content.decode("utf-8-sig"))
        if len(members) < minimum:
            raise ValueError(f"Incomplete constituent file for Nifty {suffix}")
        return members

    def fo_stocks(self) -> dict[str, str]:
        members = parse_fo_tickers(self._get(NSE_LOT_SIZES).content.decode("utf-8-sig"))
        if not 100 <= len(members) <= 500:
            raise ValueError("NSE F&O snapshot size is outside the expected range")
        return members

    def _bhavcopy_payload(self, trade_date: date) -> str:
        if trade_date in self._bhavcopy_cache:
            return self._bhavcopy_cache[trade_date]
        url = NSE_ARCHIVE + f"/content/cm/BhavCopy_NSE_CM_0_0_0_{trade_date:%Y%m%d}_F_0000.csv.zip"
        response = self._get(url)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if len(names) != 1:
                raise ValueError("Unexpected NSE Bhavcopy archive")
            payload = archive.read(names[0]).decode("utf-8-sig")
        if len(self._bhavcopy_cache) >= 8:
            self._bhavcopy_cache.pop(next(iter(self._bhavcopy_cache)))
        self._bhavcopy_cache[trade_date] = payload
        return payload

    def bhavcopy(self, trade_date: date) -> dict[str, dict]:
        return parse_bhavcopy(self._bhavcopy_payload(trade_date), trade_date)

    def previous_closes(self, trade_date: date) -> dict[str, dict]:
        """Return ticker -> {close, isin} from exact-date final PrvsClsgPric values."""
        return parse_previous_closes(self._bhavcopy_payload(trade_date), trade_date)

    def corporate_actions(self, symbol: str, start: date, end: date, isin: str) -> list[dict]:
        """Return identity-checked actions in an inclusive ex-date window.

        A split value is new shares per old share. A bonus value is additional
        shares per old share. Distributions include all declared cash components.
        """
        if start > end:
            return []
        if not re.fullmatch(r"[A-Z0-9&._-]+", symbol) or not re.fullmatch(r"[A-Z0-9]{12}", isin):
            raise ValueError("A valid NSE symbol and ISIN are required")
        if not self._action_session_initialized:
            self.session.get("https://www.nseindia.com/", timeout=(10, 30))
            self._action_session_initialized = True
        response = self.session.get(
            NSE_ACTIONS,
            params=dict(index="equities", symbol=symbol, from_date=start.strftime("%d-%m-%Y"),
                        to_date=end.strftime("%d-%m-%Y")),
            headers={"Referer": "https://www.nseindia.com/companies-listing/corporate-filings-actions"},
            timeout=(10, 30),
        )
        response.raise_for_status()
        actions = parse_corporate_actions(response.json(), symbol, start, end, isin)
        return [{**action, "source_url": response.url} for action in actions]
