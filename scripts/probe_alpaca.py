"""Probe the Alpaca paper-trading account.

Endpoints:
  - GET /v2/account
  - GET /v2/clock
  - GET /v2/positions
  - GET /v2/orders?status=all&limit=5

Run:
  python scripts/probe_alpaca.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe_util import (  # noqa: E402
    ProbeResult,
    preview,
    require_env,
    save_fixture,
    top_level_keys,
)

BASE = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
TIMEOUT = 15


def _headers() -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": os.environ["ALPACA_KEY_ID"],
        "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"],
    }


def _probe(endpoint: str, path: str, params: dict | None = None) -> ProbeResult:
    ok, msg = require_env("ALPACA_KEY_ID", "ALPACA_SECRET_KEY")
    if not ok:
        return ProbeResult("alpaca", endpoint, "skipped", note=msg)
    r = requests.get(f"{BASE}{path}", headers=_headers(), params=params, timeout=TIMEOUT)
    if r.status_code in (401, 403):
        return ProbeResult(
            "alpaca",
            endpoint,
            "not_entitled",
            http_status=r.status_code,
            note="check ALPACA_KEY_ID / SECRET and that the account is paper",
        )
    if r.status_code >= 400:
        return ProbeResult(
            "alpaca", endpoint, "error", http_status=r.status_code, note=r.text[:200]
        )
    body = r.json() if "json" in r.headers.get("content-type", "") else r.text
    fx = save_fixture("alpaca", endpoint, body)
    print(preview(body))
    return ProbeResult(
        "alpaca", endpoint, "ok", http_status=200, fixture=str(fx), fields=top_level_keys(body)
    )


def main() -> list[ProbeResult]:
    results = [
        _probe("account", "/v2/account"),
        _probe("clock", "/v2/clock"),
        _probe("positions", "/v2/positions"),
        _probe("orders", "/v2/orders", {"status": "all", "limit": 5}),
    ]
    print("\n--- summary ---")
    for r in results:
        print(r.as_row())
    return results


if __name__ == "__main__":
    main()
