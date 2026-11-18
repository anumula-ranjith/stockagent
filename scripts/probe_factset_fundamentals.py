"""Probe FactSet Fundamentals.

Resolves the list of available metrics and pulls one period for AAPL. The real
package is `fds.sdk.FactSetFundamentals`.

Install:
  pip install fds.sdk.utils fds.sdk.FactSetFundamentals

Run:
  python scripts/probe_factset_fundamentals.py
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
        return [ProbeResult("factset", "fundamentals", "skipped", note=msg)]
    try:
        from fds.sdk.FactSetFundamentals import ApiClient, Configuration
        from fds.sdk.FactSetFundamentals.api import fact_set_fundamentals_api, metrics_api
        from fds.sdk.FactSetFundamentals.model.fundamental_request import FundamentalRequest
        from fds.sdk.FactSetFundamentals.model.fundamentals_request import FundamentalsRequest
    except ImportError as e:
        return [
            ProbeResult(
                "factset",
                "fundamentals",
                "skipped",
                note=f"pip install fds.sdk.utils fds.sdk.FactSetFundamentals ({e})",
            )
        ]

    cfg = Configuration(
        username=os.environ["FACTSET_USERNAME_SERIAL"],
        password=os.environ["FACTSET_API_KEY"],
    )
    cfg.get_basic_auth_token()

    results: list[ProbeResult] = []
    with ApiClient(cfg) as api:
        # ---- metrics catalogue ---------------------------------------------
        try:
            mapi = metrics_api.MetricsApi(api)
            mresp = mapi.get_fds_fundamental_metrics()
            m_out = mresp.to_dict() if hasattr(mresp, "to_dict") else mresp
            fx = save_fixture("factset", "fundamentals_metrics", m_out)
            metrics = m_out.get("data", []) if isinstance(m_out, dict) else []
            fields = sorted({m.get("category", "") for m in metrics if isinstance(m, dict)})[:15]
            print(f"FactSet Fundamentals: {len(metrics)} metrics available")
            results.append(
                ProbeResult("factset", "fundamentals/metrics", "ok", fixture=str(fx), fields=fields)
            )
        except Exception as e:
            results.append(
                ProbeResult("factset", "fundamentals/metrics", "error", note=str(e)[:200])
            )

        # ---- sample fundamentals pull for AAPL ----------------------------
        try:
            fapi = fact_set_fundamentals_api.FactSetFundamentalsApi(api)
            req = FundamentalsRequest(
                data=FundamentalRequest(
                    ids=["AAPL-US"],
                    metrics=["FF_SALES", "FF_NET_INC", "FF_EPS"],
                    periodicity="QTR",
                    fiscal_period={"start": "-4", "end": "0"},
                )
            )
            fresp = fapi.get_fds_fundamentals_for_list(req)
            f_out = fresp.to_dict() if hasattr(fresp, "to_dict") else fresp
            fx = save_fixture("factset", "fundamentals_aapl_qtr", f_out)
            print(preview(f_out))
            rows = (f_out.get("data") or []) if isinstance(f_out, dict) else []
            row_fields = sorted(rows[0].keys()) if rows else []
            results.append(
                ProbeResult(
                    "factset", "fundamentals/aapl_qtr", "ok", fixture=str(fx), fields=row_fields
                )
            )
        except Exception as e:
            results.append(
                ProbeResult("factset", "fundamentals/aapl_qtr", "error", note=str(e)[:200])
            )

    return results


if __name__ == "__main__":
    for r in main():
        print(r.as_row())
