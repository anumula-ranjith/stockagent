# Admin pipelines implementation plan

**Goal:** Ship the approved admin portal and durable Celery market pipelines.
**Spec:** ../../ADMIN-PIPELINES-DESIGN.md
**Architecture:** Separate PostgreSQL pipeline tables isolate Celery work from existing RQ backtests. Beat dispatches both daily slots and reconciles durable pending work. Existing ingestion adapters retain their transaction and source validation behavior.
**Stack:** FastAPI, PostgreSQL, Redis, Celery, Next.js, React Query.

## Constraints and rulings
- Both 07:00 and 18:30 Asia/Kolkata; no invented weekend sessions.
- User authorized admin access for ranjith.a@goldenhillsindia.com only.
- Execute inline under the executing-plans skill; approval to implement is already supplied.
- Ruling: separate pipeline tables instead of extending JobRun prevents legacy RQ reconciliation claiming Celery jobs.
- Ruling: retain shared working directory to preserve extensive concurrent uncommitted work; no broad commits or resets.
- Linux deployment supported; native Windows solo workers are a documented local compatibility mode, tested before activation.

## Tasks
- [x] Add durable runs/schedules schema and model, schedule resolution tests and migration.
- [x] Implement queue submission, dispatch recovery, stage progress, heartbeat, retry, cancellation and validation adapters; test duplicate delivery and failed stages.
- [x] Add admin-only APIs for overview, paginated runs, details, retry/cancel, schedules, coverage, users and audit; test permissions, future dates and last-admin guard.
- [x] Build admin portal and proxy routes; production build and browser checks.
- [x] Install Celery, start supervised local worker/Beat, configure both schedules, cut over duplicate timers, grant authorized account role, execute live smoke pipeline.
- [x] Run isolated DB integration tests and final review; document deployment, limitations and verification evidence.

## Review focus
- Broker unavailable after durable commit must not lose requests.
- Worker death must not leave permanent running jobs or duplicate active writers.
- A partial vendor response must not appear as fully successful.
- Repeated submissions and multiple Beat processes must deduplicate by durable keys.
- Last-admin demotion and non-admin execution must be denied server-side.

## Verification ledger — 19 November 2026
- Schema migrated to 0010_admin_pipelines on local PostgreSQL.
- Final focused integration/regression suite: 47 passed, exit 0 (admin pipelines, schedules, snapshots, daily EOD, adjustments, providers, sectors, insider, short selling, RQ jobs and auth).
- Production build `.next-admin-verified`: exit 0; deployed on port 3001. API restarted on 8701.
- Ruff scoped checks: all passed. TypeScript and ESLint passed during production build.
- Fresh reviewer /root/admin_review found three important issues. Fixed partial-source accounting (news/sentiment/insider), replay-safe retry keys, and duplicate-delivery backoff. Reproducing tests failed before fixes and passed in final 47-test suite.
- Live manual daily run 740fda98-a702-4d86-a673-92b356e12e23 completed in approximately 4m26s: all required stages succeeded; partial overall for two unavailable short-selling files. Prices/adjusted closes/sectors cover all 501 current members for 18 November.
- Investigated live timeout: fallback DELETE planned 391 Timescale chunks. Explicit incoming date bounds reduce it to one; live EOD stage then completed successfully.
- Browser verified Overview, Pipelines, Schedules, Data quality, Users, Audit, pause/resume morning schedule, manual daily submission, progress, and blocking another run while active. Both schedules restored enabled.
- Session expired after the final build restart. Browser checks for manual retry/cancel on the final build remain pending sign-in; those API/lifecycle controls passed integration tests. User asked asynchronously to sign in.
- Local supervisor/worker/control/Beat healthy; Windows task installed. Old EOD task disabled; legacy scheduler keeps only RQ reconciliation.
- Ruling: native Windows solo compatibility is enabled locally with an owned-process watchdog; Linux prefork deployment is documented but no Linux host was provisioned. Local operation requires an awake machine and logged-in user.
- No unrelated changes committed or reset. Working plan retained for pending browser validation.


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
