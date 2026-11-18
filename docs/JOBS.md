# Phase 3 jobs and scheduler

## 1. Start the services

Start PostgreSQL, Redis, the private local artifact store and the API using
the [local startup guide](../DEPLOY.md). With the project virtual
environment active, run each command in its own terminal:

```powershell
python -m scripts.local worker
python -m scripts.local scheduler
```

The scheduler reconciles PostgreSQL jobs with Redis. To run queued backtests
while leaving scheduled vendor ingestion disabled, set
`SCHEDULER_RUN_MARKET_JOBS=false` in the root `.env` and restart the scheduler.

## 2. Submit and inspect a backtest

Sign in as an administrator and open [Backtest](http://localhost:3001/backtest).
The API records the job and audit event together in PostgreSQL and returns
HTTP 202 with the job ID. The scheduler reconciles undelivered jobs with
Redis. The worker computes the report against PostgreSQL and uploads it to the
private bucket. The page displays the chart and a five-minute signed JSON
download. The job endpoint checks ownership or administrator access before
signing a new URL.

Open [Job queues](http://localhost:3001/_admin/rq/) from the signed-in admin
navigation. The dashboard shows queue depth, workers, failures and retries.
A retry retains the original job ID and adds an audit entry. PostgreSQL
keeps the job history and backs the latest-report endpoint.

## 3. Review the exchange schedule

All times use Asia/Kolkata. EOD checks also run on weekends to pick up special
trading sessions. A refresh requires the exact date's final NSE Bhavcopy.

| Time | Jobs |
|---|---|
| 18:30 | Nifty 500 and stock F&O membership refresh, followed by EOD ingestion directly into PostgreSQL. |
| 19:00 | News and daily sentiment ingestion. |
| 19:30 | Score recomputation. |

Scheduled jobs use a stable ID per task and trading date. Warehouse jobs write directly to PostgreSQL. A database advisory lock serializes
writers, and each worker transaction commits its results and job status together.
Configure EODHD access before enabling daily vendor jobs.

The scheduler checks EOD completion every 15 minutes and on startup. Before
18:30 it checks the previous evening's date, so an overnight interruption can
catch up. It records each attempt in PostgreSQL `job_runs` and the completed
coverage in `run_log`. A missing final file remains `awaiting_exchange` and is
retried. Identical completed runs are skipped. The union is recorded under
`NIFTY500` and `NSE_FO` in `index_membership`, with overlapping stocks loaded once.

For Windows, install the persistent task from the repository root after creating
`.venv` and installing `requirements-prod.txt` there.

```powershell
./scripts/install_daily_eod_task.ps1
Start-ScheduledTask -TaskName 'Stock Agents NSE Daily EOD'
Get-ScheduledTaskInfo -TaskName 'Stock Agents NSE Daily EOD'
```

The task uses the project `.env`, runs while the Windows user is signed in, and
attempts catch-up when the machine resumes. PostgreSQL and network access must
be available. This EOD task runs directly against PostgreSQL and can operate
independently of Redis. Its results are also written to `logs/daily_eod.jsonl`.
The database advisory lock coordinates it with the application scheduler and workers.

Run a date explicitly or check the currently due refresh with the same entrypoint.

```powershell
$env:PYTHONPATH = 'src'
./.venv/Scripts/python.exe -m scripts.refresh_eod --date 2026-11-18
./.venv/Scripts/python.exe -m scripts.refresh_eod --due
```

NSE fallback adjusted closes are calculated from official NSE corporate actions,
validated against the stock's ISIN. Cash dividends and total REIT distributions
use the factor `1 - cash_amount / previous_session_close`; splits and bonuses use
their share ratios. Each action adjusts only earlier sessions, with the latest
close as the anchor. All retained fallback history is recalculated daily, including
already populated values, so new distributions update earlier prices. EODHD-supplied
adjustments remain vendor-sourced. `quality_log` records the NSE action evidence
and calculation method; `corporate_actions` stores the normalized events as source
`nse`. Consumers must select a single corporate-action source per ticker/event
when computing their own returns, since EODHD and NSE may report the same event.

If exchange actions are unavailable or unsupported (such as a demerger), the run
records a warning and retries; it does not invent an adjusted value. An unchanged
price retains its previously verified adjustment during a source outage.
Newly encountered stocks receive the configured EODHD history lookback. For stocks absent from
EODHD, the NSE fallback initially checks 31 calendar days. Subsequent refreshes
fill gaps since the latest stored date. Coverage limitations are included in the
run result. Corporate-action changes trigger an adjusted-history refresh.
