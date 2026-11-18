"""Probe FactSet Prices (used only as the EODHD cross-check).

Install:
  pip install fds.sdk.utils fds.sdk.FactSetPrices

Run:
  python scripts/probe_factset_prices.py
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe_util import ProbeResult, preview, require_env, save_fixture  # noqa: E402


def main() -> list[ProbeResult]:
    ok, msg = require_env("FACTSET_USERNAME_SERIAL", "FACTSET_API_KEY")
    if not ok:
        return [ProbeResult("factset", "prices", "skipped", note=msg)]
    try:
        from fds.sdk.FactSetPrices import ApiClient, Configuration
        from fds.sdk.FactSetPrices.api import prices_api
    except ImportError as e:
        return [
            ProbeResult(
                "factset",
                "prices",
                "skipped",
                note=f"pip install fds.sdk.utils fds.sdk.FactSetPrices ({e})",
            )
        ]

    cfg = Configuration(
        username=os.environ["FACTSET_USERNAME_SERIAL"],
        password=os.environ["FACTSET_API_KEY"],
    )
    cfg.get_basic_auth_token()

    end = date.today()
    start = end - timedelta(days=10)
    with ApiClient(cfg) as api:
        papi = prices_api.PricesApi(api)
        for method in ("get_prices", "get_security_prices"):
            if hasattr(papi, method):
                try:
                    resp = getattr(papi, method)(
                        ids=["AAPL-US"],
                        start_date=start.isoformat(),
                        end_date=end.isoformat(),
                        frequency="D",
                    )
                    out = resp.to_dict() if hasattr(resp, "to_dict") else resp
                    fx = save_fixture("factset", f"prices_{method}", out)
                    print(preview(out))
                    return [
                        ProbeResult(
                            "factset",
                            f"prices/{method}",
                            "ok",
                            fixture=str(fx),
                            fields=sorted(out.keys())[:20] if isinstance(out, dict) else [],
                        )
                    ]
                except Exception as e:
                    return [ProbeResult("factset", f"prices/{method}", "error", note=str(e)[:200])]
    return [ProbeResult("factset", "prices", "error", note="no method found")]


if __name__ == "__main__":
    for r in main():
        print(r.as_row())
