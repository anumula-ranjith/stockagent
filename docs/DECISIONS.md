# Production build decisions

## Phase 1 · PostgreSQL foundation

1. Restore the test baseline for the configured NSE universe.
2. Match PostgreSQL and SQLAlchemy metadata to all 27 DuckDB tables. Keep
   PostgreSQL as the operational store and DuckDB as the research store.
3. Import a consistent DuckDB snapshot in a PostgreSQL transaction. Batch
   prices by calendar month, preserve duplicate log entries, and reconcile
   counts before switching the API.
4. Route operational API reads through the configured backend and compare
   the existing HTTP responses across both stores. Keep ingestion and
   backtest computation on the existing DuckDB path for this phase.
5. Verify the schema with Alembic and document the cutover. Keep development
   endpoints local while the authentication phase is pending.

The attached production brief provides the phase order. Hosting and
identity-provider decisions belong to later phases.

The PostgreSQL import is insert-only and compares source and destination
counts. The same DuckDB file remains the source for research backtests.
Authentication, continuous data synchronization, and the Next.js replacement
for the HTML prototype belong to their later phases.

Local verification used PostgreSQL 16 and TimescaleDB 2.22.1. Both imports
matched all 27 warehouse table counts, and the integration suite exercised
API parity and the hypertable. Full Compose startup remains pending on a
machine with Docker.

## Phase 2 · Authentication

1. Add a reversible schema migration for account identity, audit events and
   durable job payloads.
2. Implement local JWT authentication, first-admin bootstrap, the optional
   Clerk verifier and shared rate limits.
3. Protect administrative actions and reports, and wire the existing
   sign-in and backtest flows to the authenticated API.
4. Exercise role boundaries, audit entries, rate limits and a real DuckDB
   backtest in a disposable database before switching the local app.

## Phase 3 · Workers and operations

1. Replace the API's in-process job runner with Redis-backed RQ. Use existing
   PostgreSQL job rows as a durable outbox, keeping job IDs, audit events and
   older reports readable across the cutover.
2. Upload completed backtest artifacts to private object storage and expose
   signed downloads through the authorized job endpoint.
3. Schedule NSE trading-day jobs in Asia/Kolkata. Publish their warehouse
   changes to PostgreSQL for the dashboard.
4. Protect the mounted RQ dashboard with the existing administrator role.
   Verify through the current HTML UI. The Next.js replacement belongs to Phase 4.

## Phase 4 · Next.js frontend

1. Add the Next.js App Router in `apps/web`, generate API types and extend
   the existing ranking API with weighted queries and recorded score history.
2. Port the home, ranking dashboard, stocks, ticker, backtest and methodology
   routes. Use the existing account and RQ boundaries through a same-origin
   proxy with private response caching disabled.
3. Check a production build, the browsing experience and a real backtest.
   Keep the FastAPI pages available during the side-by-side rollout.

## Phase 5 · Observability and CI

1. Add structured process logs, request IDs, and trace propagation through
   durable job records. Trace SQL operations using bounded attributes.
2. Expose request latency and durable job execution metrics. Split public
   readiness, process liveness, and the administrator-only vendor check.
3. Add a local Tempo receiver and CI for Python, the Next.js build, and the
   Compose startup check.
4. Verify the new signals against an isolated backtest, then roll out locally
   while keeping the API's existing routes and role boundaries.
