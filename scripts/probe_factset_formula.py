"""Probe FactSet Formula API (time-series REST endpoint).

This is the lightweight REST endpoint the user provided:
  FACTSET_BASE_URL = https://api.factset.com/formula-api/v1/time-series

Auth is HTTP Basic with FACTSET_USERNAME_SERIAL:FACTSET_API_KEY. We ask for a
single metric (price) on one Indian ticker to confirm the account is live
without burning entitlement budget.

Run:
  python scripts/probe_factset_formula.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe_util import ProbeResult, preview, require_env, save_fixture  # noqa: E402

DEFAULT_BASE = "https://api.factset.com/formula-api/v1/time-series"
TIMEOUT = 25


def main() -> list[ProbeResult]:
    ok, msg = require_env("FACTSET_USERNAME_SERIAL", "FACTSET_API_KEY")
    if not ok:
        return [ProbeResult("factset", "formula/time-series", "skipped", note=msg)]

    base = os.environ.get("FACTSET_BASE_URL", DEFAULT_BASE)
    auth = HTTPBasicAuth(os.environ["FACTSET_USERNAME_SERIAL"], os.environ["FACTSET_API_KEY"])
    currency = os.environ.get("FACTSET_DEFAULT_CURRENCY", "INR")

    # Ask for one month of close price on Reliance (Nifty 200 bellwether).
    # FactSet Formula API accepts NSE tickers as "RELIANCE-IN" (ticker-exchange).
    # batch=Y is required for iterated cross-sectional time-series requests.
    from datetime import date, timedelta

    today = date.today()
    start = today - timedelta(days=30)
    params = {
        "ids": "RELIANCE-IN",
        "formulas": "P_PRICE",
        "startDate": start.isoformat(),
        "endDate": today.isoformat(),
        "frequency": "D",
        "batch": "Y",
        "currency": currency,
    }
    try:
        r = requests.get(base, params=params, auth=auth, timeout=TIMEOUT)
    except Exception as e:
        return [ProbeResult("factset", "formula/time-series", "error", note=str(e)[:200])]

    status = r.status_code
    try:
        body = r.json()
    except Exception:
        body = r.text[:400]

    if status == 202:
        # Batch accepted and queued — auth works, request is valid.
        fx = save_fixture("factset", "formula_reliance_price_batch_ack", body)
        print(preview(body))
        return [
            ProbeResult(
                "factset",
                "formula/time-series",
                "ok",
                http_status=status,
                fixture=str(fx),
                note="batch queued (async)",
            )
        ]
    if status in (401, 403):
        return [
            ProbeResult(
                "factset",
                "formula/time-series",
                "not_entitled",
                http_status=status,
                note=preview(body, 200),
            )
        ]
    if status >= 400:
        return [
            ProbeResult(
                "factset",
                "formula/time-series",
                "error",
                http_status=status,
                note=preview(body, 200),
            )
        ]

    fx = save_fixture("factset", "formula_reliance_price", body)
    print(preview(body))
    fields = sorted(body.keys()) if isinstance(body, dict) else []
    return [
        ProbeResult(
            "factset",
            "formula/time-series",
            "ok",
            http_status=status,
            fixture=str(fx),
            fields=fields,
        )
    ]


if __name__ == "__main__":
    for r in main():
        print(r.as_row())
