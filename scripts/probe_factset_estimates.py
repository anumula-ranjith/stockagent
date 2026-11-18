"""Probe FactSet Estimates (consensus EPS NTM, rating, target).

Install:
  pip install fds.sdk.utils fds.sdk.FactSetEstimates

Run:
  python scripts/probe_factset_estimates.py
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
        return [ProbeResult("factset", "estimates", "skipped", note=msg)]
    try:
        from fds.sdk.FactSetEstimates import ApiClient, Configuration
        from fds.sdk.FactSetEstimates.api import consensus_api, rating_api
    except ImportError as e:
        return [
            ProbeResult(
                "factset",
                "estimates",
                "skipped",
                note=f"pip install fds.sdk.utils fds.sdk.FactSetEstimates ({e})",
            )
        ]

    cfg = Configuration(
        username=os.environ["FACTSET_USERNAME_SERIAL"],
        password=os.environ["FACTSET_API_KEY"],
    )
    cfg.get_basic_auth_token()

    results: list[ProbeResult] = []
    with ApiClient(cfg) as api:
        # Rolling consensus for NTM EPS on AAPL. The exact method names vary
        # by SDK version; we try the common ones.
        try:
            cons = consensus_api.ConsensusApi(api)
            for method in ("get_consensus", "get_rolling_consensus"):
                if hasattr(cons, method):
                    resp = getattr(cons, method)(
                        ids=["AAPL-US"], metrics=["EPS"], periodicity="ANN", fiscal_period_start="0"
                    )
                    out = resp.to_dict() if hasattr(resp, "to_dict") else resp
                    fx = save_fixture("factset", f"estimates_consensus_{method}", out)
                    print(preview(out))
                    results.append(
                        ProbeResult(
                            "factset",
                            f"estimates/{method}",
                            "ok",
                            fixture=str(fx),
                            fields=sorted(out.keys())[:20] if isinstance(out, dict) else [],
                        )
                    )
                    break
            else:
                results.append(
                    ProbeResult("factset", "estimates/consensus", "error", note="no method found")
                )
        except Exception as e:
            results.append(
                ProbeResult("factset", "estimates/consensus", "error", note=str(e)[:200])
            )

        try:
            rat = rating_api.RatingApi(api)
            for method in ("get_rating_summary", "get_rating"):
                if hasattr(rat, method):
                    resp = getattr(rat, method)(ids=["AAPL-US"])
                    out = resp.to_dict() if hasattr(resp, "to_dict") else resp
                    fx = save_fixture("factset", f"estimates_rating_{method}", out)
                    results.append(
                        ProbeResult(
                            "factset",
                            f"estimates/{method}",
                            "ok",
                            fixture=str(fx),
                            fields=sorted(out.keys())[:20] if isinstance(out, dict) else [],
                        )
                    )
                    break
            else:
                results.append(
                    ProbeResult("factset", "estimates/rating", "error", note="no method found")
                )
        except Exception as e:
            results.append(ProbeResult("factset", "estimates/rating", "error", note=str(e)[:200]))

    return results


if __name__ == "__main__":
    for r in main():
        print(r.as_row())
