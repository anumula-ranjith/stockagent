# Nifty 500 research data ingestion

This independent pipeline uses the repository's PostgreSQL configuration, security master, publisher integrations, authentication and Celery services. It does not call the reference project's server. Data remains in four distinct datasets; daily short-sale volume is never converted into estimated outstanding short interest.

## Run locally

Run from `D:\Projects\AIQuantPlatform\stock-agents` in PowerShell:

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m stock_agents.ingest.market_signals sync
.venv/Scripts/python.exe -m stock_agents.ingest.market_signals backfill --start 2026-10-22 --end 2026-11-20
# Repeat the same command to refresh observations without duplicate primary keys.
.venv/Scripts/python.exe -m stock_agents.ingest.market_signals diagnose --symbol PAYTM.NS --start 2026-11-19 --end 2026-11-19 --sources nse_short_sales
.venv/Scripts/python.exe -m stock_agents.ingest.market_signals incremental
.venv/Scripts/python.exe -m scripts.audit_market_signals
.venv/Scripts/python.exe -m pytest tests/test_market_signals.py -q
```

`--sources` accepts a comma-separated subset of `nse_short_sales,ortex,publisher_buzz,hacker_news`. CLI writes require a loopback PostgreSQL host and a database name identifying local/dev/test. Do not redirect it to a production database. Tests exercising PostgreSQL use the configured local database and roll back fixture rows.

## Automation and operations

The existing Celery Beat schedules `quantora.market_signals` on `quantora-pipelines`:

| IST time | Operation |
|---|---|
| 06:20 daily | Refresh and validate official current constituents |
| 07:10 daily | Refresh all four datasets, today and previous six calendar days |
| 18:40 daily | Repeat recent-date refresh for delayed publications |

Existing 07:00 and 18:30 EOD pipelines remain in place. These independent jobs follow them and share the pipeline worker queue; actual start depends on queued work. Weekends still recheck delayed records. `scripts.run_pipeline_services` supervises the existing worker and Beat. The host, PostgreSQL and Redis must be running; do not start a second Beat against the same schedule file.

Manual Celery dispatch:

```powershell
.venv/Scripts/python.exe -m celery -A stock_agents.jobs.celery_app:app call quantora.market_signals --queue quantora-pipelines
```

Configure `ORTEX_API_KEY` only on the server. Optional request budgets are `ORTEX_REQUEST_BUDGET` (default 50 per run) and `HN_REQUEST_BUDGET` (default 300). Each HTTP attempt counts; retries are bounded. ORTEX listings rotate toward least recently attempted companies. Authorization, entitlement and rate-limit errors stop further wasteful requests. A missing key is recorded as `unavailable`, never as zero. ORTEX grants and billing remain provider controlled.

Each source has an independent PostgreSQL advisory lock. Concurrent attempts are recorded as `already_running`. Data and successful source-run counters commit together; completed providers survive another provider's failure. ORTEX commits each completed ticker, reporting outstanding tickers when the budget is exhausted. A new owner of a source lock marks abandoned `running` attempts `interrupted`. CLI output reports individual statuses; process success alone is not a declaration of full data coverage.

## Interpretation

- Official snapshots require 500 distinct securities and ISINs. Explicit `DUMMY` company/symbol/ISIN placeholders are excluded and recorded. Failed validation preserves prior membership. Backfills record the current snapshot, not historical index membership.
- `short_sale_observations.short_sale_shares` is NSE's disclosed integer daily volume. An absent row differs from a published zero.
- `short_interest_estimates` contains ORTEX observation-date estimates only. Either estimate can be null. No response/coverage never creates zeroes.
- `publisher_buzz` joins existing `news_items` for title, publisher, URL and UTC publication time. Separate company links support multi-company stories. Rules identify online reactions/viral/social-campaign titles; this is publisher coverage, not observed social engagement. RSS/search archives are inherently limited.
- `public_social_posts` contains HN story IDs, public discussion links and observed engagement counts. Exact whole-name/brand matching avoids `payment` → `Paytm`. HN's capped windows are recursively split and all remaining pages checked. Engagement reruns update the same row and observation timestamp.
- UTC timestamps are stored; inclusive input dates use IST midnight boundaries. Source-run ranges and snapshot IDs retain provenance. Retrieval-only refreshes do not count as business-field updates.

## Read-only API

Authenticated `GET /market-signals/PAYTM.NS?start=2026-11-19&end=2026-11-19` returns `short_sales`, `short_interest`, `publisher_buzz`, `public_social_posts` and `coverage` separately. The web proxy allows `/backend/market-signals/{ticker}` after its next build. Unknown symbols return 404; invalid dates return 422; unauthenticated requests return 401.

Coverage describes the latest overlapping run per source and explicitly says whether that run covers the entire requested window. Inspect source status, ticker reason, `ticker_not_requested` and row dates; a successful market-wide query does not imply every company has an observation. No credentials are returned.

## Reusable SQL

```sql
SELECT s.ticker, s.trade_date, s.short_sale_shares, s.source, s.retrieved_at,
       r.status, r.snapshot_id, r.membership_basis
FROM short_sale_observations s JOIN market_signal_runs r ON r.id=s.run_id
WHERE s.ticker='PAYTM' AND s.trade_date BETWEEN DATE '2026-10-22' AND DATE '2026-11-20'
ORDER BY s.trade_date DESC;

SELECT source, start_date, end_date, status, rows_fetched, rows_inserted,
       rows_updated, reason, details, started_at, finished_at
FROM market_signal_runs ORDER BY started_at DESC;
```

`scripts.audit_market_signals` reports table counts, distinct tickers, date bounds, latest source attempts and a PAYTM response read from PostgreSQL. The checked-in implementation does not seed historical PAYTM values or fixture social posts.
