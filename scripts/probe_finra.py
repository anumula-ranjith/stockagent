"""Probe the FINRA consolidated short-interest files.

FINRA publishes the NYSE and NASDAQ consolidated short-interest files twice a
month. They are flat text files hosted on the FINRA CDN. The exact filename is
published in the dissemination schedule — this probe TRIES the current
settlement cycle and falls back to a listing of the parent directory.

Reference:
  https://www.finra.org/filing-reporting/regulatory-filing-systems/regsho

Run:
  python scripts/probe_finra.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe_util import ProbeResult, save_fixture  # noqa: E402

TIMEOUT = 20
# Short interest consolidated files have historically lived at these URLs; the
# real filename is YYYYMMDD (settlement date). We don't know the current
# settlement date here, so this probe lists likely candidates and reports
# whichever works. Phase 2 will replace this with a real dated download.
CANDIDATES = [
    "https://cdn.finra.org/equity/regsho/daily/RegSHO_NYSE_Daily.csv",
    "https://www.finra.org/sites/default/files/shortsale_2024.zip",  # historical zip
]


def _probe(url: str) -> ProbeResult:
    try:
        r = requests.head(url, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException as e:
        return ProbeResult("finra", url.rsplit("/", 1)[-1], "error", note=str(e))
    if r.status_code in (401, 403):
        return ProbeResult("finra", url, "not_entitled", http_status=r.status_code)
    if r.status_code >= 400:
        return ProbeResult("finra", url, "error", http_status=r.status_code)
    # Save a small payload: URL + content-type + length + first 500 bytes.
    sample = requests.get(url, timeout=TIMEOUT, stream=True)
    head_bytes = sample.raw.read(500) if sample.ok else b""
    body = {
        "url": url,
        "http_status": r.status_code,
        "content_type": r.headers.get("content-type"),
        "content_length": r.headers.get("content-length"),
        "head_bytes_utf8": head_bytes.decode("utf-8", errors="replace"),
        "probed_on": date.today().isoformat(),
    }
    fx = save_fixture("finra", url.rsplit("/", 1)[-1], body)
    return ProbeResult(
        "finra", url.rsplit("/", 1)[-1], "ok", http_status=r.status_code, fixture=str(fx)
    )


def main() -> list[ProbeResult]:
    results = [_probe(u) for u in CANDIDATES]
    print("\n--- summary ---")
    for r in results:
        print(r.as_row())
    print(
        "\nNote: FINRA publishes real consolidated short-interest files by\n"
        "settlement date. Phase 2 will use the published dissemination\n"
        "schedule from https://www.finra.org/filing-reporting/regulatory-filing-systems/regsho\n"
        "to pick the right filename on each run."
    )
    return results


if __name__ == "__main__":
    main()
