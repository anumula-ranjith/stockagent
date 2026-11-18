# Production deployment

The prepared deployment uses Render for FastAPI, RQ, and APScheduler, Tiger Cloud for PostgreSQL and TimescaleDB, Upstash for Redis, a private S3 bucket for artifacts, and Vercel for Next.js. Run the checklist against a staging environment with separate credentials and data before assigning a production domain.

## 1. Validate the release candidate

1. Confirm the Python, Next.js, and Docker Compose jobs passed for the release commit in [GitHub Actions](https://github.com/anumula-ranjith/stockagent/actions).
2. Create the cloud resources described below. Keep production credentials in the host dashboards or secrets managers. Keep local environment files and warehouse exports on approved storage.
3. Use the same tested commit for the API, worker, scheduler, and frontend. Record the active deployment IDs before changing traffic.

## 2. Provision PostgreSQL, Redis, and S3

1. Create a PostgreSQL database with TimescaleDB and backups enabled. Use the direct TLS connection string for migrations and session-scoped advisory locks. For a new database, load the baseline schema and TimescaleDB configuration once. For an existing database, take a backup and apply Alembic migrations to the existing schema.

   ```bash
   psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f scripts/sql/init.sql
   psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f scripts/sql/timescale.sql
   PYTHONPATH=src python -m alembic upgrade head
   ```

   Import licensed history only if the provider contract allows that host and dataset. Validate price coverage and run a known-period backtest before the cutover. The schema and migration commands assume PostgreSQL credentials with DDL access.

2. Create an Upstash Redis database for RQ. Copy the Redis protocol `rediss://` URL to `REDIS_URL`. Set `AUTH_RATE_LIMIT_STORAGE_URL` to the TLS Redis URL used for auth rate limits. A separate Redis database or instance isolates auth counters. Validate queue enqueue, worker dequeue, and dashboard operations against the chosen Upstash plan because RQ relies on blocking commands and Pub/Sub.
3. Create an S3 bucket with public access blocked and with encryption and versioning enabled. Set `S3_BUCKET`, `AWS_DEFAULT_REGION`, and AWS credentials for the API and RQ worker. Give the API bucket-check and backtest-read permissions, and the worker scoped backtest-write permissions. The same objects must be readable by the S3 presigned URL users receive. The application uses AWS S3 endpoints when the optional `S3_ENDPOINT` and `S3_PUBLIC_ENDPOINT` variables are unset.

## 3. Deploy to Render and Vercel

1. Connect the project repository to Render and import [render.yaml](render.yaml). The blueprint sets the API health check to `/health`, runs Alembic before the API starts, and gates automatic API deploys on passing CI. Use the same EODHD key on the worker and scheduler if their jobs share one vendor account. Set EODHD and FactSet credentials on the API if you intend to use its admin vendor probes. Configure OTLP/HTTP export on the services with `OTEL_EXPORTER_OTLP_ENDPOINT` and optional `OTEL_EXPORTER_OTLP_HEADERS`.
2. Deploy the API first and wait for `/health/live` and `/health` to return HTTP 200. Deploy RQ and the scheduler to the same commit. Keep one scheduler per environment. Its background process runs the three-second outbox reconciliation loop and the market schedule, including the 18:30 IST refresh and catch-up checks.
3. Create one Vercel Next.js project with the root directory `apps/web` and Node.js 24. Set `API_ORIGIN` to the Render HTTPS API origin, `NEXT_PUBLIC_API_BASE=/backend`, and `NEXT_PUBLIC_AUTH_PROVIDER=jwt`. Use the same settings in staging against the staging API. Disable automatic domain assignment while validating a staged production deployment. If using Clerk, configure the browser and API with the same tenant and authorized origins as described in [Authentication](docs/AUTHENTICATION.md).
4. Bootstrap the first JWT admin over HTTPS with the generated bootstrap token. Use an existing admin account to create other users. Set `AUTH_COOKIE_SECURE=true` and `REQUIRE_MARKET_DATA_AUTH=true` for production. When Vercel targets a custom API host, set `PUBLIC_API_ORIGIN` on the API to that exact HTTPS origin for dashboard request verification. Never put API secrets in `NEXT_PUBLIC_*` variables.

## 4. Verify before promoting

1. Open the staged frontend and verify sign-in, logout, and `Secure`, `HttpOnly`, and `SameSite` session cookie flags.
2. With a viewer session, verify market data and scoring reads succeed and admin job operations return 403. Verify an anonymous session receives 401 for market-data endpoints.
3. With an admin session, queue a backtest for a seeded date range and wait for its result. Check the job dashboard, confirm the signed artifact downloads, and verify the same object requires authorization without its signature.
4. Verify the scheduler reports its expected jobs, confirm the last valid EOD run date, and check that HTTP and job metrics and correlated traces appear. Promote the staged Vercel deployment only after these checks.

## 5. Roll back an unsuccessful release

1. If a candidate API fails its Render health check, keep traffic on the healthy deployment and investigate. For a regression after traffic switches, roll back the API deployment in Render and restore the last known-good Vercel deployment. Verify readiness and sign-in again.
2. RQ and scheduler updates are manual because some jobs outlast Render's 300-second shutdown window. Drain active work before replacing either process, then select the matching known-good commit for each. Check `/_admin/rq/` for any interrupted job before retrying it.
3. Leave backward-compatible schema changes in place for an application rollback. If the schema is incompatible, restore a tested backup to a separate database, verify it, and coordinate the connection switch and recovery of writes since the backup. Avoid running an automatic Alembic downgrade on the live database.

## Other hosting paths

| Path | Deployment shape |
| --- | --- |
| Fly.io | Build the same Dockerfile. Use separate API, RQ, and scheduler process groups and one scheduler Machine. Use a managed Timescale service and TLS Redis, and put Next.js on Vercel. Point health checks at `/health` and record the prior image for rollback. |
| AWS | Run FastAPI, RQ, and the continuous scheduler as separate ECS Fargate services. Put the API behind an HTTPS load balancer using `/health`, use ElastiCache and a private S3 bucket, and inject credentials from Secrets Manager. Choose Tiger Cloud or a TimescaleDB-capable PostgreSQL host if the extension is required. For standard RDS PostgreSQL, check the supported extension list and use the baseline PostgreSQL schema when TimescaleDB is unavailable. Vercel can host the existing Next.js proxy. An AWS-only frontend needs a Next.js server runtime because the proxy and authentication routes execute on the server. |

Provider references are available for [Render Blueprints](https://render.com/docs/blueprint-spec), [Render rollbacks](https://render.com/docs/rollbacks), [Vercel promotion and rollback](https://vercel.com/docs/deployments/promoting-a-deployment), [Upstash Redis compatibility](https://upstash.com/docs/redis/overall/compatibility), and [Amazon RDS extensions](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.FeatureSupport.Extensions.html).
