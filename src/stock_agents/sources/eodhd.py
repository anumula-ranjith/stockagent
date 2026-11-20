"""EODHD REST client for the NSE India ingest pipeline.

Endpoints (confirmed by scripts/probe_eodhd.py against RELIANCE.NSE):
  GET /eod/{TICKER}.{EXCH}           daily OHLCV + adjusted close
  GET /eod-bulk-last-day/{EXCH}      bulk EOD slice (one trading day, all names)
  GET /splits/{TICKER}.{EXCH}        splits
  GET /div/{TICKER}.{EXCH}           dividends
  GET /fundamentals/{TICKER}.{EXCH}  fundamentals snapshot
  GET /news?s={TICKER}.{EXCH}        news with polarity
  GET /sentiments?s={TICKER}.{EXCH}  aggregated daily sentiment
  GET /calendar/earnings             upcoming earnings calendar

Exchange suffix comes from config/settings.yaml (`exchange_suffix`, e.g. ``.NSE``).
"""

from __future__ import annotations

import os
import math
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import requests

from stock_agents.common.logging import get_logger

log = get_logger(__name__)

BASE = "https://eodhistoricaldata.com/api"


class EODHDAccountError(RuntimeError):
    """Authentication, entitlement, or quota failure for this account."""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class EODHDClient:
    api_key: str = field(repr=False)
    timeout: int = 30
    max_retries: int = 3
    backoff_s: float = 1.5

    @classmethod
    def from_env(cls) -> EODHDClient:
        key = os.environ.get("EODHD_API_KEY")
        if not key:
            raise RuntimeError("EODHD_API_KEY not set in env / .env")
        return cls(api_key=key)

    # -- internal -----------------------------------------------------------
    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        p = {"api_token": self.api_key, "fmt": "json"}
        if params:
            p.update(params)
        failure = "request failed"
        for attempt in range(1, self.max_retries + 1):
            try:
                r = requests.get(f"{BASE}{path}", params=p, timeout=self.timeout)
                if r.status_code == 429:
                    failure = "HTTP 429"
                    try:
                        delay = float(r.headers.get("Retry-After", self.backoff_s * attempt))
                    except ValueError:
                        delay = self.backoff_s * attempt
                    if delay > 60:
                        raise RuntimeError("EODHD rate limit requires a later retry")
                    if attempt < self.max_retries:
                        time.sleep(max(0, delay))
                    continue
                if r.status_code == 404:
                    return None
                if r.status_code in (401, 402, 403):
                    raise EODHDAccountError(f"EODHD HTTP {r.status_code}", r.status_code)
                if r.status_code in (400, 422):
                    raise ValueError(f"EODHD HTTP {r.status_code}: invalid request")
                r.raise_for_status()
                ctype = r.headers.get("content-type", "")
                return r.json() if "json" in ctype else r.text
            except requests.RequestException as e:
                failure = f"HTTP {e.response.status_code}" if e.response is not None else type(e).__name__
                log.warning("eodhd %s attempt %d failed (%s)", path, attempt, failure)
                time.sleep(self.backoff_s * attempt)
        raise RuntimeError(f"eodhd {path} failed after {self.max_retries} attempts ({failure})")

    # -- endpoints ----------------------------------------------------------
    def eod(
        self, symbol: str, start: date | None = None, end: date | None = None
    ) -> list[dict[str, Any]]:
        """Daily OHLCV. `symbol` is the fully qualified EODHD symbol, e.g. 'RELIANCE.NSE'."""
        params: dict[str, Any] = {}
        if start:
            params["from"] = start.isoformat()
        if end:
            params["to"] = end.isoformat()
        out = self._get(f"/eod/{symbol}", params)
        return out or []

    def bulk_eod(self, exchange: str, trade_date: date | None = None) -> list[dict[str, Any]]:
        """Bulk end-of-day for an exchange, optionally for a historical date."""
        params = {"filter": "extended"}
        if trade_date:
            params["date"] = trade_date.isoformat()
        out = self._get(f"/eod-bulk-last-day/{exchange}", params)
        return out or []

    def splits(self, symbol: str) -> list[dict[str, Any]]:
        return self._get(f"/splits/{symbol}") or []

    def dividends(self, symbol: str) -> list[dict[str, Any]]:
        return self._get(f"/div/{symbol}") or []

    def fundamentals(self, symbol: str) -> dict[str, Any] | None:
        return self._get(f"/fundamentals/{symbol}")

    def ranking_fundamentals(self, symbol: str) -> dict[str, Any] | None:
        return self._get(f"/fundamentals/{symbol}", {
            "filter": "General,Highlights,Valuation,Earnings::Trend,Earnings::History",
        })

    def remaining_calls(self) -> int:
        account = self._get("/user")
        used = int(account["apiRequests"])
        # The provider resets its counter lazily on the first post-midnight call.
        reported = account.get("apiRequestsDate")
        if reported and date.fromisoformat(str(reported)[:10]) < datetime.now(UTC).date():
            used = 0
        return max(0, int(account["dailyRateLimit"]) + int(account.get("extraLimit") or 0) - used)

    def news(self, symbol: str, limit: int = 50) -> list[dict[str, Any]]:
        result = self._get("/news", {"s": symbol, "limit": limit})
        if result is None:
            return []
        if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
            raise ValueError("Invalid EODHD news response")
        for item in result:
            if not isinstance(item.get("title"), str) or not item["title"].strip() or not isinstance(item.get("date"), str):
                raise ValueError("Invalid EODHD news article")
            datetime.fromisoformat(item["date"].replace("Z", "+00:00"))
        return result

    def sentiments(self, symbol: str) -> dict[str, Any]:
        result = self._get("/sentiments", {"s": symbol})
        if result is None:
            return {}
        if not isinstance(result, dict) or any(not isinstance(items,list) or any(not isinstance(item,dict) for item in items) for items in result.values()):
            raise ValueError("Invalid EODHD sentiment response")
        for items in result.values():
            for item in items:
                date.fromisoformat(str(item.get("date", "")))
                count = item.get("count")
                polarity = item.get("normalized")
                if not isinstance(count,(int,float)) or not math.isfinite(count) or count < 0 or int(count) != count:
                    raise ValueError("Invalid EODHD sentiment count")
                if count and (not isinstance(polarity,(int,float)) or not math.isfinite(polarity) or not -1 <= polarity <= 1):
                    raise ValueError("Invalid EODHD sentiment polarity")
        return result

    def calendar_earnings(
        self, start: date | None = None, end: date | None = None, symbol: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if start:
            params["from"] = start.isoformat()
        if end:
            params["to"] = end.isoformat()
        if symbol:
            params["symbols"] = symbol
        return self._get("/calendar/earnings", params) or {}
