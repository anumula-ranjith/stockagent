# QUANTORA administration



Open `/admin` while signed in as an administrator. The portal has Overview,

Pipelines, Schedules, Data quality, Users and Audit sections. Only the explicitly

authorized existing account was granted access during setup. All endpoints check

the database role; hiding navigation is not the authorization boundary.



## Daily updates



Both schedules use Asia/Kolkata: **07:00 catch-up** and **18:30 after close**.

They resolve to the latest completed NSE session using the exchange calendar.

Weekends/holidays revisit that session. A missed slot catches up within 24 hours.

Schedule toggles affect future submissions, not work already queued.



With `MARKET_PRICE_PROVIDER=angel_one`, a separate Windows task,

`QUANTORA Angel One Market Data`, starts the price capture at **15:16 IST**.

The morning and evening pipelines consume that day's stored capture and continue

refreshing NSE reference data and other inputs. Configure the four server-side

SmartAPI fields in the project's private `.env`. The task reads them afresh on

every launch. Outcomes are recorded in `logs/angel_market.jsonl`. Completed and

partial captures are also recorded in PostgreSQL's `run_log`.



Install or update the task with `scripts/install_angel_market_task.ps1`. Windows

requests wake-up and retries failures every two minutes within the live window.

The runner checks the configured NSE session calendar and skips starts outside

15:16–15:30 IST. A machine offline throughout this window misses that capture.

On hosts where Windows restricts background logon registration, the installer

uses the current user's interactive token and the user must be signed in.



Daily stages: preflight, reference/membership/sectors, EOD prices and adjustments,

provider fundamentals/estimates, insider disclosures, short-selling disclosures,

news, sentiment, coverage validation, scores and cache publication. Reference

metadata uses today's observation date; historical runs do not manufacture past

knowledge. The validation panel explicitly checks current membership at the selected

completed price session. Source credentials remain in server configuration.



Use Pipelines → select a workflow/date → Run pipeline for manual execution.

Dates must be completed trading sessions in the last 31 days. Requests use

idempotency keys; PostgreSQL locks serialize submissions and warehouse writers.

An active run prevents a second submission. Run history persists in PostgreSQL,

independent of Redis. The data-quality page offers a shortcut to prepare an EOD repair.



Cancellation finishes the current stage, then stops. Committed stages remain.

Transient required-stage failures retry up to three attempts with five-minute delays.

Completed stages are skipped during automatic recovery. Manual retry creates a linked

new run and repeats the workflow. Optional-source failures yield **partial**, never

success. Required missing/invalid prices block score computation. Missing adjusted

closes/sectors remain visible as quality warnings. Source limitations cannot be

resolved by inventing values.



Beat checks pending work every minute. Undelivered requests are retried; running

work with a stale three-minute heartbeat is redelivered. A PostgreSQL advisory lock

prevents concurrent execution after duplicate delivery. Workers publish liveness;

the portal reports broker, scheduler and worker health. Server snapshots invalidate

on publication; the existing browser query cache can retain data up to five minutes.



## Local Windows operation



Installed task: `QUANTORA Pipeline Services`, at user logon with a five-minute

restart watchdog. It launches `scripts/run_pipeline_services.ps1`. The Python

supervisor owns the data worker, separate control worker and Beat, restarts exited

children, and holds a PostgreSQL lock so repeated starts do not create duplicates.

The native solo worker is a local compatibility mode: Celery does not officially

support Windows. The supervisor kills a stage exceeding two hours and lets durable

reconciliation recover it. Use Linux prefork workers for production.



Logs: `logs/pipeline-worker.log`, `pipeline-control.log`, `pipeline-beat.log` and

`pipeline-supervisor.err`. Stage errors shown in the portal exclude raw credentials,

SQL parameters and vendor payloads. Investigate the failing stage/source, then retry.

Do not expose logs publicly. Rotate logs as part of host operations.



The previous `Stock Agents NSE Daily EOD` task is disabled. The legacy RQ scheduler

runs with `SCHEDULER_RUN_MARKET_JOBS=false`, retaining backtest outbox recovery.

RQ workers still handle backtests. Do not reenable old market timers alongside Celery.

This local setup requires the computer awake, PostgreSQL/Redis running, and the user

logged on. It is not an always-on hosted deployment.



## Linux deployment



Install the locked application environment including `celery[redis]`, configure

DATABASE_URL, REDIS_URL and provider keys privately, then run `alembic upgrade head`.

Use separate supervised services with WorkingDirectory set to the repository:



```sh

.venv/bin/celery -A stock_agents.jobs.celery_app:app worker -Q quantora-pipelines -n pipeline@%h --pool=prefork -c 1 -l INFO

.venv/bin/celery -A stock_agents.jobs.celery_app:app worker -Q quantora-control -n control@%h --pool=prefork -c 1 -l INFO

.venv/bin/celery -A stock_agents.jobs.celery_app:app beat -s /var/lib/quantora/celerybeat-schedule -l INFO

```



Run one Beat, use systemd `Restart=always`, a dedicated unprivileged service account,

private environment file and persistent Beat directory. Workers have a 6,900-second

soft / 7,200-second hard limit. Redis visibility timeout is four hours. Keep Postgres

backups and Redis persistence enabled. Verify all three health indicators, trigger

a validation run, and check persisted stage completion before retiring old timers.

Linux deployment commands are provided; no Linux host was provisioned in this task.



## Verification



`tests/test_admin_pipelines.py` exercises authorization, last-admin protection,

date validation, schedules, audit, idempotency, cancellation, retry bounds and

broker failure using a disposable PostgreSQL database. `test_pipeline_schedule.py`

checks timezone/session behavior. Set TEST_DATABASE_URL to a test server whose role

can create databases; fixtures create and remove only uniquely named test databases.

Build the frontend with `npm run build` in apps/web. Review real stage history after

vendor runs: mocked tests do not establish source availability.



### Local acceptance results (19 November 2026)



47 selected tests passed, production build/type checks passed, and scoped Python

lint passed. All six admin sections were opened in the browser; morning pause/resume

was verified and restored. A full daily run was submitted through the browser and

completed with all required stages successful. Overall status was partial for two

unavailable optional short-selling reports. Current-session coverage: 501/501 prices,

adjusted closes and sectors. Final-build browser retry/cancel checks await renewed

sign-in; their API and lifecycle tests passed in PostgreSQL integration tests.





### Retry/cancel browser acceptance — 19 November 2026

After renewed sign-in, Retry on partial run 740fda98-a702-4d86-a673-92b356e12e23

created linked run 9a1a9508-2e4c-48d4-94d7-0c6c63cfda34. Cancel acknowledged the

request, disabled duplicate cancellation, finished the in-flight EOD stage and

persisted Cancelled. Retry on that cancelled run created

6c1fc458-180a-4338-9138-31644e83c99c, which completed Partial with source limitations

shown per stage. Both retry operations and cancellation appear in the audit log.

Both daily schedules remain enabled. No active test run remains.



Fixed cancellation racing with final-stage completion or failure: the status update

atomically gives an accepted cancellation precedence, clears the retry deadline,

and records completion time. Both regression cases failed before the fix and

passed afterward. Latest scoped suite: 13 admin/scheduling tests passed; Ruff passed.

A PostgreSQL null-CASE typing issue found during that fix was corrected. The test

retry's worker was refreshed after its stages finished and its durable run was

redelivered to finalize without repeating completed stages (attempt 2).

Browser retry/cancel validation is now complete. Evidence:

`docs/verification/admin-retry-cancel.jpg`.



### Angel One connection and missed-capture recovery

Admin Overview/Pipelines includes a six-digit authenticator-code form. Existing
server API key, client code and PIN authenticate the broker; the entered code is
not persisted. A Fernet-encrypted broker session is shared through Redis and expires
at midnight Asia/Kolkata. The UI displays expiry. The changing code is distinct
from ANGEL_ONE_TOTP_SECRET (the Base32 setup seed). With manual-code login, reconnect
each day before the 07:00 job, or reconnect later and retry it. This cannot provide
unattended authentication across midnight.

In Angel One price mode, the daily EOD stage retrieves official ONE_DAY historical
candles for the completed session. It does not pretend to reconstruct a missed
15:16 tick: recovered bars have no invented exchange trade timestamp. Existing
verified adjusted closes are retained only when the raw close agrees. A complete
recovery is checkpointed as angel-eod-YYYY-MM-DD and reused on subsequent runs.
The 15:16 IST capture reads the private project `.env` on each run. For automatic
login, save the Base32 setup key shown below the Angel One SmartAPI enrollment QR
code as `ANGEL_ONE_TOTP_SECRET` and use the default automatic authentication mode.
With manual-code login, the capture uses the active broker session from Redis.

Short-selling ingestion requests NSE trading dates only and checkpoints fully
validated reports, including valid empty reports. Missing trading-day reports
remain retryable errors. Verification for 11-18 November 2026 loaded six reports,
excluded two weekend dates, and found zero unmatched volumes. A second run reused
all six checkpoints. Provider outages and incomplete data remain visible as
failed/partial outcomes; they are never relabelled as successful.

If Angel One historical candles are unavailable (including broker AB1021 throttling),
the EOD recovery retries with bounded backoff, then requests the official NSE
bhavcopy for that exact session. Fallback bars retain source `nse_bhavcopy`; the
run records separate Angel One/NSE counts and the fallback reason. This restores
completed-session data, not a missing live capture. All members still undergo
OHLCV and final coverage validation; incomplete exchange files remain partial.

Regression verification: 44 targeted tests passed on 19 November 2026, including
admin access/code validation, encrypted session storage, recovery provenance,
missing reports, retry, cancellation and schedule behavior.

Live retry 591b8df7-4045-4e1b-8ba1-b0eea7c81619 completed successfully on 19 November 2026 for the 18 November session. All 11 stages succeeded: 501 priced and adjusted, zero missing sectors or invalid prices, 40 Angel One daily candles and 461 verified NSE fallback bars. Six short-selling reports were complete. See verification/market-recovery.json.

## Free news for personal research

Economic Times RSS stocks, companies, industry and technology feeds run in the
shared `news` stage of both enabled daily schedules (07:00 and 18:30 Asia/Kolkata).
The Admin news pipeline can also run this stage manually. No RSS API key is needed.
Current active NIFTY500/NSE_FO membership is unioned each run, including stocks
without EODHD symbols. RSS contains recent articles, not a guaranteed daily article
for every stock. Exact company names, conservative symbols and explicit published
aliases map headlines. Subsidiary-name guards protect SBI and L&T parent mappings.

RSS uses bounded requests, two attempts, four concurrent feeds, 2 MB size limits,
no DTD/entities, publisher-only HTTP(S) links, and publication-date validation.
Only title/link/date/publisher metadata is persisted; no full article scraping.
Sentiment stays null. Stable ticker/article IDs prevent repeat imports; the API
also collapses tracking-URL duplicates across sources. An EODHD savepoint prevents
paid-source failures from rolling back RSS. Failures remain partial in Admin,
while valid empty results are successful. Per-feed diagnostics live in run_log
(job free_news). News status and articles require the existing market-data login.

Stock pages show publisher links, last feed check, per-stock RSS count, honest
empty states, and a refresh button that reloads stored data (it does not fetch
publishers). Open pages poll news/status once per minute. The publisher RSS terms
allow personal non-commercial use: https://economictimes.indiatimes.com/rss.cms .
Do not enable this personal feed in a shared/commercial deployment without rights.

## EODHD quota recovery

Confirmed 19 November 2026: account usage 99,996/100,000 units; news and
sentiment returned HTTP 402 (daily quota exhausted). No code change can restore
provider access before quota reset or additional capacity. Official subscription
quota resets at midnight UTC (05:30 IST). QUANTORA defers quota-blocked pipelines
to 00:05 UTC (05:35 IST), visibly `retrying`, without marking missing data complete.
Completed stages remain committed. Waiting quota runs do not block a subsequent
scheduled pipeline, but all running warehouse writes still use the same lock.
Cancellation clears the deferred retry. The normal three-attempt ceiling applies.

EODHD news/sentiment now have separate durable checkpoints per morning/evening
refresh slot, limited to the current Nifty 500/F&O union. Each successful symbol
(or sentiment batch) is reused on later runs in the same slot, including valid
empty results. Failed requests are not checkpointed complete. The user endpoint
is checked before bounded batches; lazy reset dates and extra units are included.
HTTP 402 stops spending attempts, 401/403 stop account requests, and 429 respects
bounded Retry-After. Payloads are validated before persistence.

Fundamentals loading and its missing-values backfill reserve 12,000 API units
for news/sentiment by default (`EODHD_NEWS_RESERVED_UNITS`). Other consumers of
the same API key can still exhaust the shared account quota. An API key or paid
limit change is not performed automatically. Free RSS ingestion stays available.

Verification: 30 related tests passed; seven final recovery tests passed after adding malformed-payload and mid-batch quota tests. Both daily paths complete successfully with controlled provider responses. Live full daily run ad41c5b2-c2ef-4d22-aa55-1181bc971b8d retained six successful stages and four healthy RSS feeds, then entered quota waiting with an automatic retry at 20 November 2026 05:35 IST. Successful live EODHD completion remains unverified because the external account has only four API units available. See verification/eodhd-recovery.json.
