"""Run every probe and print a one-line summary per endpoint.

  python scripts/run_all_probes.py

Any probe missing a key is reported as 'skipped' and does not abort the run.
Fixtures land in tests/fixtures/. After this runs, review the output and
update docs/DATA_NOTES.md with confirmed endpoints, field names and any
entitlement surprises.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probe_alpaca  # noqa: E402
import probe_eodhd  # noqa: E402
import probe_factset_estimates as fs_est  # noqa: E402
import probe_factset_events as fs_events  # noqa: E402
import probe_factset_fundamentals as fs_fund  # noqa: E402
import probe_factset_ownership as fs_own  # noqa: E402
import probe_factset_prices as fs_prc  # noqa: E402
import probe_factset_symbology as fs_sym  # noqa: E402
import probe_finra  # noqa: E402
import probe_fred  # noqa: E402
from _probe_util import ProbeResult, banner  # noqa: E402

PROBES = [
    ("EODHD", probe_eodhd.main),
    ("FRED", probe_fred.main),
    ("FINRA", probe_finra.main),
    ("Alpaca paper", probe_alpaca.main),
    ("FactSet Symbology", fs_sym.main),
    ("FactSet Fundamentals", fs_fund.main),
    ("FactSet Estimates", fs_est.main),
    ("FactSet Prices", fs_prc.main),
    ("FactSet Ownership", fs_own.main),
    ("FactSet Events", fs_events.main),
]


def main() -> int:
    all_results: list[ProbeResult] = []
    for name, fn in PROBES:
        banner(name)
        try:
            results = fn()
        except Exception as e:  # pragma: no cover
            print(f"!! {name} raised: {e}")
            all_results.append(ProbeResult(name, "?", "error", note=str(e)))
            continue
        if isinstance(results, list):
            all_results.extend(results)
        else:
            all_results.append(results)

    print("\n" + "=" * 80)
    print("PROBE SUMMARY")
    print("=" * 80)
    print(f"{'source':<18} {'endpoint':<34} {'status':<14} fixture")
    print("-" * 80)
    counts = {"ok": 0, "skipped": 0, "not_entitled": 0, "error": 0}
    for r in all_results:
        counts[r.status] = counts.get(r.status, 0) + 1
        print(r.as_row())
    print("-" * 80)
    print(
        f"ok={counts.get('ok', 0)}  skipped={counts.get('skipped', 0)}  "
        f"not_entitled={counts.get('not_entitled', 0)}  error={counts.get('error', 0)}"
    )
    print(
        "\nNext: review the output, open the fixtures under tests/fixtures/,\n"
        "then update docs/DATA_NOTES.md and config/factset_metrics.yaml with\n"
        "the confirmed endpoints and field names before Phase 2 begins."
    )
    return 0 if counts["error"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
