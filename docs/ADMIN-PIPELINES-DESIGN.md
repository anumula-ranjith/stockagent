# QUANTORA administration and daily pipelines

Status: proposed implementation design, 19 November 2026. Not yet implemented.

## Confirmed requirements

Admin portal; daily data-update explanation; manual pipeline controls; Celery
daily scheduling at 07:00 Asia/Kolkata; retain the after-close update at 18:30
Asia/Kolkata. Nifty 500 plus NSE F&O-eligible stocks, not derivative contracts.
PostgreSQL remains authoritative. Existing user-facing workflows remain available.

## Recommended architecture

Use Celery for market-maintenance pipelines and Celery Beat as their single
schedule owner. Retain RQ for existing backtests. Extend the durable PostgreSQL
job registry with explicit executor ownership, parent run, pipeline stage,
attempt, heartbeat, cancellation request and delivery metadata. RQ reconciliation
must exclude Celery-owned jobs. Do not silently route jobs between executors.

Replace existing EOD timer execution with the coordinated Celery pipeline when
cutover is verified. Keep the same after-close schedule; remove duplicate EOD
ownership from APScheduler and Windows Task Scheduler. A bounded reconciliation
task recovers undelivered PostgreSQL jobs and missed schedules after downtime.
Use a durable unique schedule/date key and the existing warehouse advisory lock
to prevent overlapping market writes across old and new workers during cutover.

Celery worker and Beat should run under Linux, separately supervised, with Redis
as broker and PostgreSQL as the authoritative audit/result store. JSON-only task
messages contain job IDs, not credentials or arbitrary Python callables. One Beat
instance owns the schedule. A Windows solo-worker development mode can be supplied
and tested, but must not be described as an officially supported production setup.
No configured WSL distribution or Docker executable was found during inspection.

## Scheduling and market dates

- 07:00 every day: catch up through the latest completed NSE trading session.
- 18:30 every day: refresh the latest session eligible for published EOD data.
- Resolve trading sessions with the configured NSE calendar. Holidays/weekends
  must not be treated as missing daily prices. Exchange publication delays become
  explicit awaiting-data states with bounded retry, not false successful runs.
- Resume a missed scheduled run after service recovery using its durable key.
- Allow pause/resume of automatic runs, with actor/time audit; manual runs remain
  separately authorized. Display timezone and next due execution in the portal.

## Pipeline stages

1. Preflight: PostgreSQL, Redis, configured vendor availability and worker health.
2. Refresh Nifty/index and F&O membership, symbols, company names and sectors.
3. Incrementally ingest EOD OHLCV, corporate actions and adjusted closes.
4. Refresh configured provider inputs, estimates, exchange insider/short-selling
   observations, news and sentiment, respecting each source's publication window.
5. Validate coverage, duplicate keys, invalid prices, adjustment availability,
   missing sectors and latest completed session. Retain per-ticker exceptions.
6. Recompute agent scores only after required market inputs commit successfully.
7. Invalidate shared market snapshots, publish completion and display coverage.

Required-stage failure stops dependent stages. Optional unavailable sources are
reported as skipped or partial with a reason; they do not become fabricated data.
Each stage commits independently and records timings/counts. Retries are idempotent
and resume safe stages; permission/configuration errors do not retry indefinitely.

## Admin portal

Route `/admin`, visible only to authenticated administrators, with backend checks
on every admin endpoint. Non-admin API requests return 403. Hiding navigation is
not the access-control mechanism. Never promote an account implicitly.

- Overview: latest completed market session, freshness, coverage, unresolved
  tickers, worker/scheduler heartbeat and source configuration availability.
- Pipelines: run complete daily update or selected supported maintenance stages;
  choose validated trading date; show scope and confirmation of expensive backfills.
- Runs: paginated history, stage progression, counts, duration, initiating actor,
  safe error details, retry failed run and cooperative cancel at stage boundaries.
- Schedules: both daily times, timezone, next run and pause/resume audit.
- Data quality: searchable missing/invalid observations and targeted repair queue.
- Users: existing identity/role status; role management only through an authorized
  administrator, audit all changes, and prevent removing the final active admin.
- Settings: non-secret operational controls and source connectivity indicators;
  secrets remain in deployment configuration, never returned to the browser.
- Help: explain source → validation → PostgreSQL → scores → UI freshness flow.

All forms have labels, validation messages, pending states and duplicate-submit
protection. Poll only active runs; cache completed history. Keep prior content
visible during refresh and provide clear empty, forbidden, offline and error states.

## Failure and validation contract

Validate pipeline allowlist, date bounds, scope limits and user permissions before
enqueueing. A successful enqueue means accepted, not completed. Store the durable
job before delivery. Broker failure leaves an explicit awaiting-delivery job that
reconciliation can dispatch later. Use an idempotency key for repeated submissions.

Bound network timeouts and retries with backoff. Detect worker loss using heartbeat
and execution lease; expose abandoned runs and recover safely. Manual retries
create linked attempts so history is retained. Cancellation is cooperative and
must not claim to roll back stages already committed. Error output is redacted;
audit logs retain correlation IDs without credentials or complete vendor payloads.

## Acceptance checks

- Unauthenticated/non-admin/admin endpoint and navigation behavior.
- Manual run → durable row → Celery delivery → stage results → coverage → UI.
- Both 07:00 and 18:30 schedules in India time; holiday/weekend and restart catch-up.
- Repeated clicks, duplicate Beat delivery and concurrent legacy EOD execution.
- Broker unavailable, worker offline/killed, vendor timeout/rate limit, database
  rollback, partial source coverage and retry exhaustion.
- Invalid/future date, unsupported task, unbounded backfill and malformed input.
- Idempotent upserts, no point-in-time leakage and no destructive price replacement.
- Final-admin protection, safe errors, audited schedule/role changes, CSRF checks.
- Browser verification of overview, run details, filters, manual run, retry,
  cancellation, schedule controls and non-admin denial.
- Migrations, targeted unit/integration tests, production frontend build and live
  queue smoke test. Use an isolated database for destructive integration fixtures.

## Implementation order

1. Durable orchestration schema, executor separation and regression tests.
2. Celery app/tasks, trading-date scheduling, idempotency and recovery tests.
3. Stage adapters around existing ingestion/validation/scoring functions.
4. Admin API, role safeguards, configuration endpoints and audit tests.
5. Admin UI and typed API integration.
6. Linux deployment/service configuration and controlled scheduler cutover.
7. Live manual run, simulated schedule execution, browser tests and operations guide.

Approval requested for this concrete design before feature implementation.
