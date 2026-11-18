"""Probe FactSet Events & Transcripts (earnings calendar, conferences).

Install:
  pip install fds.sdk.utils fds.sdk.EventsandTranscripts

Run:
  python scripts/probe_factset_events.py
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
        return [ProbeResult("factset", "events", "skipped", note=msg)]
    try:
        from fds.sdk.EventsandTranscripts import ApiClient, Configuration
        from fds.sdk.EventsandTranscripts.api import events_api
    except ImportError as e:
        return [
            ProbeResult(
                "factset",
                "events",
                "skipped",
                note=f"pip install fds.sdk.utils fds.sdk.EventsandTranscripts ({e})",
            )
        ]

    cfg = Configuration(
        username=os.environ["FACTSET_USERNAME_SERIAL"],
        password=os.environ["FACTSET_API_KEY"],
    )
    cfg.get_basic_auth_token()

    end = date.today() + timedelta(days=30)
    start = date.today()
    with ApiClient(cfg) as api:
        ev = events_api.EventsApi(api)
        for method in ("get_company_event", "get_events"):
            if hasattr(ev, method):
                try:
                    resp = getattr(ev, method)(
                        ids=["AAPL-US"],
                        event_types=["earnings"],
                        start_date=start.isoformat(),
                        end_date=end.isoformat(),
                    )
                    out = resp.to_dict() if hasattr(resp, "to_dict") else resp
                    fx = save_fixture("factset", f"events_{method}", out)
                    print(preview(out))
                    return [
                        ProbeResult(
                            "factset",
                            f"events/{method}",
                            "ok",
                            fixture=str(fx),
                            fields=sorted(out.keys())[:20] if isinstance(out, dict) else [],
                        )
                    ]
                except Exception as e:
                    return [ProbeResult("factset", f"events/{method}", "error", note=str(e)[:200])]
    return [ProbeResult("factset", "events", "error", note="no method found")]


if __name__ == "__main__":
    for r in main():
        print(r.as_row())
