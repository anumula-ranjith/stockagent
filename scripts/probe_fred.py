"""Probe FRED series endpoints for the macro factors we need.

Endpoints:
  - /fred/series/observations?series_id=DGS3MO
  - /fred/series/observations?series_id=VIXCLS

Run:
  python scripts/probe_fred.py
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
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

BASE = "https://api.stlouisfed.org/fred"
TIMEOUT = 15


def _probe(series_id: str) -> ProbeResult:
    ok, msg = require_env("FRED_API_KEY")
    if not ok:
        return ProbeResult("fred", f"series/{series_id}", "skipped", note=msg)
    end = date.today()
    start = end - timedelta(days=30)
    r = requests.get(
        f"{BASE}/series/observations",
        params={
            "series_id": series_id,
            "api_key": os.environ["FRED_API_KEY"],
            "file_type": "json",
            "observation_start": start.isoformat(),
            "observation_end": end.isoformat(),
        },
        timeout=TIMEOUT,
    )
    if r.status_code in (401, 403):
        return ProbeResult("fred", f"series/{series_id}", "not_entitled", http_status=r.status_code)
    if r.status_code >= 400:
        return ProbeResult(
            "fred", f"series/{series_id}", "error", http_status=r.status_code, note=r.text[:200]
        )
    body = r.json()
    fx = save_fixture("fred", f"series_{series_id}", body)
    print(preview(body))
    obs = body.get("observations", [])
    fields = sorted(obs[0].keys()) if obs else top_level_keys(body)
    return ProbeResult(
        "fred", f"series/{series_id}", "ok", http_status=200, fixture=str(fx), fields=fields
    )


def main() -> list[ProbeResult]:
    results = [_probe("DGS3MO"), _probe("VIXCLS")]
    print("\n--- summary ---")
    for r in results:
        print(r.as_row())
    return results


if __name__ == "__main__":
    main()
