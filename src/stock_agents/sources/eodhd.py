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
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

import requests

from stock_agents.common.logging import get_logger

log = get_logger(__name__)

BASE = "https://eodhistoricaldata.com/api"


@dataclass(frozen=True)
class EODHDClient:
    api_key: str
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
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                r = requests.get(f"{BASE}{path}", params=p, timeout=self.timeout)
                if r.status_code == 429:
                    time.sleep(self.backoff_s * attempt)
                    continue
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                ctype = r.headers.get("content-type", "")
                return r.json() if "json" in ctype else r.text
            except requests.RequestException as e:
                last_exc = e
                log.warning("eodhd %s attempt %d failed: %s", path, attempt, e)
                time.sleep(self.backoff_s * attempt)
        raise RuntimeError(f"eodhd {path} failed after {self.max_retries} retries: {last_exc}")

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

    def news(self, symbol: str, limit: int = 50) -> list[dict[str, Any]]:
        return self._get("/news", {"s": symbol, "limit": limit}) or []

    def sentiments(self, symbol: str) -> dict[str, Any]:
        return self._get("/sentiments", {"s": symbol}) or {}

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
