# Local verification — 20 November 2026

Applied migration `0014_market_signals` to verified local PostgreSQL `stock_agents_local` at `127.0.0.1:55433`. The official CSV supplied 500 real securities plus the explicitly labelled `DUMMYHEG` placeholder. The snapshot stores 500 unique symbols/ISINs; the placeholder is excluded and audited. Existing security IDs are reused.

## Live database results

Backfill window: **22 October–20 November 2026 inclusive**, using the current observed constituent snapshot.

| Dataset | Records | Distinct companies | Earliest–latest observation |
|---|---:|---:|---|
| NSE daily short-sale shares | 1,931 | 408 | 22 Oct–19 Nov 2026 |
| ORTEX outstanding estimates | 0 | 0 | Unavailable: server key not configured |
| Publisher social-buzz headlines | 1 | 1 | 13 Nov 2026 |
| HN public discussions | 5 | 3 | 3–10 Nov 2026 |

The market-wide NSE archive returned 2,408 rows before filtering to the current universe. The first HN scan read 30,378 public stories; the repeat read 30,387 as new stories appeared. Exact company matching retained five relevant posts. Manual review detected 17 false matches involving ordinary phrases and unrelated entities, including “black box,” “global health,” philosophy and the Haber–Bosch process. Those links/posts were removed and regression tests added. Publisher buzz contains a Moneycontrol article about a viral Reddit post mentioning Swiggy; it is retained as publisher coverage, not as a Reddit engagement observation.

## Repeat and scheduled-path checks

After correcting company matching, the identical 30-day backfill finished with **zero inserted and zero updated business rows** for all available datasets. Record counts, distinct-company counts and earliest/latest dates matched the corrected baseline exactly. No fixture post remains in PostgreSQL.

The live Celery worker successfully ran constituent sync and the seven-day incremental refresh (14–20 November). Incremental source statuses were NSE `success`, publishers `limited`, HN `success`, and ORTEX `unavailable`. HN scanned 7,034 stories in that recent window. No matching new business rows were added. These status distinctions are deliberate; this is not a claim that all 500 companies have all four inputs.

Beat is configured for constituent sync at **06:20 IST**, incremental refreshes at **07:10 and 18:40 IST**, on the existing pipeline queue. Existing 07:00 and 18:30 EOD jobs remain intact. Queue availability and a running host determine actual execution time.

## PAYTM historical check

Freshly downloaded NSE CSV for **19 November 2026** returned `PAYTM`, `short_sale_shares=56`. The PostgreSQL row also contains **56**. The value matches the user's historical reference; it was downloaded, not seeded. Raw response: `logs/market-signals-probe/paytm-live.csv`.

## Tests and evidence boundaries

- **11 targeted tests passed**, covering CSV validation, integer quantities, missing-versus-zero, date preservation, capped HN windows, exact matching, ambiguous names, multi-company links, ORTEX nulls/pagination/request budgets, credential-safe errors, API authentication/validation, and PostgreSQL upsert/rollback behavior.
- HN engagement refresh was tested with a fabricated post inside a rolled-back PostgreSQL transaction: points changed from 2 to 9 and comments from 3 to 6 on the existing ID; rerunning unchanged data added no duplicate. The live repeat had no engagement changes for the retained posts, so the change-path proof is a **fixture test**, not a claimed live change.
- ORTEX's successful pagination/estimate-storage path is **fixture-tested only**. Live runs confirmed missing-key handling and continued loading the other sources. No real ORTEX estimate is present.
- Alembic metadata comparison for the nine new tables reported **no schema differences**.
- The running HTTP service returns **401** without authentication. The saved [PAYTM response](market-signals-paytm-response.json) came through the FastAPI route with a test-only authentication override, reading actual PostgreSQL data. No production authentication bypass was installed.
- Publisher RSS/search coverage is explicitly limited. HN represents one public network, not comprehensive social sentiment. Missing observations remain absent/null.

The audit retains the initial rejected placeholder-bearing download and an interrupted preliminary repeat used while correcting matching. Subsequent valid sync, full repeat and Celery incremental runs completed with the statuses above.

## Exact execution commands

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m stock_agents.ingest.market_signals sync
.venv/Scripts/python.exe -m stock_agents.ingest.market_signals backfill --start 2026-10-22 --end 2026-11-20 > logs/market-signals-backfill-1.json
.venv/Scripts/python.exe -m stock_agents.ingest.market_signals diagnose --symbol PAYTM.NS --start 2026-11-19 --end 2026-11-19 --sources nse_short_sales > logs/market-signals-paytm.json
.venv/Scripts/python.exe -m stock_agents.ingest.market_signals backfill --start 2026-10-22 --end 2026-11-20 > logs/market-signals-backfill-2-corrected.json
.venv/Scripts/python.exe -m scripts.audit_market_signals > logs/market-signals-audit-2.json
.venv/Scripts/python.exe -m pytest tests/test_market_signals.py -q
```

Celery was dispatched through the project's configured application:

```python
from stock_agents.jobs.celery_app import app
app.send_task('quantora.market_signals', args=['sync'], queue='quantora-pipelines')
app.send_task('quantora.market_signals', queue='quantora-pipelines')
```

Audit artifacts: `logs/market-signals-audit-1-corrected.json`, `logs/market-signals-audit-2.json`, and `logs/market-signals-final-audit.json`. See the [operations guide](market-signals.md) for reusable PAYTM SQL, API usage, configuration and recovery behavior.
