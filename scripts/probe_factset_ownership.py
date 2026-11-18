"""Probe FactSet Ownership (insider transactions + institutional holdings).

Install:
  pip install fds.sdk.utils fds.sdk.FactSetOwnership

Run:
  python scripts/probe_factset_ownership.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe_util import ProbeResult, preview, require_env, save_fixture  # noqa: E402


def main() -> list[ProbeResult]:
    ok, msg = require_env("FACTSET_USERNAME_SERIAL", "FACTSET_API_KEY")
    if not ok:
        return [ProbeResult("factset", "ownership", "skipped", note=msg)]
    try:
        from fds.sdk.FactSetOwnership import ApiClient, Configuration
        from fds.sdk.FactSetOwnership.api import ownership_api
    except ImportError as e:
        return [
            ProbeResult(
                "factset",
                "ownership",
                "skipped",
                note=f"pip install fds.sdk.utils fds.sdk.FactSetOwnership ({e})",
            )
        ]

    cfg = Configuration(
        username=os.environ["FACTSET_USERNAME_SERIAL"],
        password=os.environ["FACTSET_API_KEY"],
    )
    cfg.get_basic_auth_token()

    results: list[ProbeResult] = []
    with ApiClient(cfg) as api:
        own = ownership_api.OwnershipApi(api)
        for method, endpoint in (
            ("get_ownership_insider_transactions", "ownership/insider_tx"),
            ("get_ownership_holdings", "ownership/holdings"),
        ):
            if not hasattr(own, method):
                results.append(ProbeResult("factset", endpoint, "error", note=f"no {method}"))
                continue
            try:
                resp = getattr(own, method)(ids=["AAPL-US"])
                out = resp.to_dict() if hasattr(resp, "to_dict") else resp
                fx = save_fixture("factset", endpoint.replace("/", "_"), out)
                print(preview(out))
                results.append(
                    ProbeResult(
                        "factset",
                        endpoint,
                        "ok",
                        fixture=str(fx),
                        fields=sorted(out.keys())[:20] if isinstance(out, dict) else [],
                    )
                )
            except Exception as e:
                results.append(ProbeResult("factset", endpoint, "error", note=str(e)[:200]))
    return results


if __name__ == "__main__":
    for r in main():
        print(r.as_row())
