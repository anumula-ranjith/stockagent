"""Probe FactSet Symbology.

Resolves a few tickers to FactSet IDs (FSYM / ticker-region). The real SDK
package is `fds.sdk.Symbology`; this probe imports it lazily and reports
"skipped" if the SDK isn't installed.

Install:
  pip install fds.sdk.utils fds.sdk.Symbology

Run:
  python scripts/probe_factset_symbology.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe_util import ProbeResult, preview, require_env, save_fixture  # noqa: E402

TICKERS = ["AAPL-US", "MSFT-US", "BRK.B-US"]


def _result(status: str, note: str = "", fixture: str | None = None, fields=None) -> ProbeResult:
    return ProbeResult(
        source="factset",
        endpoint="symbology/resolve",
        status=status,
        note=note,
        fixture=fixture,
        fields=fields or [],
    )


def main() -> list[ProbeResult]:
    ok, msg = require_env("FACTSET_USERNAME_SERIAL", "FACTSET_API_KEY")
    if not ok:
        return [_result("skipped", msg)]
    try:
        from fds.sdk.Symbology import ApiClient, Configuration
        from fds.sdk.Symbology.api import symbology_api
    except ImportError as e:
        return [_result("skipped", f"pip install fds.sdk.utils fds.sdk.Symbology ({e})")]

    import os

    cfg = Configuration(
        username=os.environ["FACTSET_USERNAME_SERIAL"],
        password=os.environ["FACTSET_API_KEY"],
    )
    cfg.get_basic_auth_token()
    with ApiClient(cfg) as api:
        api_instance = symbology_api.SymbologyApi(api)
        # The Symbology SDK offers `translate_by_symbols` / similar helpers.
        # We call it defensively: anything that works reports fields.
        for method in ("translate_by_symbols", "translate", "list_symbols"):
            if hasattr(api_instance, method):
                try:
                    resp = getattr(api_instance, method)(TICKERS)
                    out = resp.to_dict() if hasattr(resp, "to_dict") else resp
                    print(preview(out))
                    fx = save_fixture("factset", f"symbology_{method}", out)
                    return [
                        _result(
                            "ok",
                            fixture=str(fx),
                            fields=sorted(out.keys())[:20] if isinstance(out, dict) else [],
                        )
                    ]
                except Exception as e:  # pragma: no cover
                    return [_result("error", f"{method}: {e}")]
        return [_result("error", "no recognizable method on SymbologyApi")]


if __name__ == "__main__":
    results = main()
    print("\n--- summary ---")
    for r in results:
        print(r.as_row())
