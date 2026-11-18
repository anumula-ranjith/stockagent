"""Probe the EODHD endpoints the ingest layer will depend on.

Endpoints probed (one ticker, one date, saved to tests/fixtures/):
  - /eod/AAPL.US                          daily OHLCV + adjusted close
  - /eod-bulk-last-day/US                 bulk-EOD slice
  - /splits/AAPL.US                       splits
  - /div/AAPL.US                          dividends
  - /fundamentals/AAPL.US                 EODHD fundamentals snapshot (fallback)
  - /news?s=AAPL.US                       news (includes polarity)
  - /sentiments?s=AAPL.US                 aggregated daily sentiment
  - /calendar/earnings                    upcoming earnings calendar

Run:
  python scripts/probe_eodhd.py
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import os  # noqa: E402

from _probe_util import (  # noqa: E402
    ProbeResult,
    preview,
    require_env,
    save_fixture,
    top_level_keys,
)

BASE = "https://eodhistoricaldata.com/api"
TICKER = "AAPL.US"
TIMEOUT = 20


def _get(path: str, params: dict | None = None) -> tuple[int, object]:
    p = {"api_token": os.environ["EODHD_API_KEY"], "fmt": "json"}
    if params:
        p.update(params)
    r = requests.get(f"{BASE}{path}", params=p, timeout=TIMEOUT)
    ctype = r.headers.get("content-type", "")
    body: object = r.json() if "json" in ctype else r.text
    return r.status_code, body


def _probe(endpoint: str, path: str, params: dict | None = None) -> ProbeResult:
    ok, msg = require_env("EODHD_API_KEY")
    if not ok:
        return ProbeResult("eodhd", endpoint, "skipped", note=msg)
    code, body = _get(path, params)
    if code in (401, 403):
        return ProbeResult("eodhd", endpoint, "not_entitled", http_status=code)
    if code >= 400:
        return ProbeResult("eodhd", endpoint, "error", http_status=code, note=preview(body, 300))
    fx = save_fixture("eodhd", endpoint, body)
    print(preview(body))
    return ProbeResult(
        "eodhd", endpoint, "ok", http_status=code, fixture=str(fx), fields=top_level_keys(body)
    )


def main() -> list[ProbeResult]:
    today = date.today()
    start = today - timedelta(days=30)
    results = [
        _probe("eod", f"/eod/{TICKER}", {"from": start.isoformat(), "to": today.isoformat()}),
        _probe("eod-bulk-last-day", "/eod-bulk-last-day/US", {"filter": "extended"}),
        _probe("splits", f"/splits/{TICKER}"),
        _probe("div", f"/div/{TICKER}"),
        _probe("fundamentals", f"/fundamentals/{TICKER}"),
        _probe("news", "/news", {"s": TICKER, "limit": 10}),
        _probe("sentiments", "/sentiments", {"s": TICKER}),
        _probe(
            "calendar-earnings",
            "/calendar/earnings",
            {"from": today.isoformat(), "to": (today + timedelta(days=14)).isoformat()},
        ),
    ]
    print("\n--- summary ---")
    for r in results:
        print(r.as_row())
    return results


if __name__ == "__main__":
    main()
