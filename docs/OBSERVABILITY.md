# Observability and CI

## 1. Start the stack

Run `docker compose up -d --build --wait` from the project root. The API container applies Alembic migrations and ensures the private S3 bucket exists before starting. For native or managed services, run `python -m alembic upgrade head` once before starting the updated API, RQ worker, and scheduler. Revision `0003_observability` adds request correlation fields and a table for cumulative job metrics.

## 2. Check readiness

| Endpoint | Use |
| --- | --- |
| `GET /health/live` | Confirms the API process can respond. |
| `GET /health` | Checks PostgreSQL, Redis, and the private S3 bucket. Returns HTTP 503 if a dependency fails. |
| `GET /health/deep` | Checks EODHD and FactSet with test data requests. Requires an admin session and may use vendor quota. |
| `GET /metrics` | Serves Prometheus process, HTTP, dependency, and job metrics. |

Use `/health/live` for liveness and `/health` for traffic readiness. On managed hosts, keep `/metrics` on a private network or set `METRICS_BEARER_TOKEN` and configure the scraper to send it as a bearer token. The dependency gauges report the result of the most recent readiness check.

Use `/health?include_stats=true` to request exact warehouse row counts. The default readiness probe skips the warehouse scan so it remains responsive as market history grows.

## 3. Find a request or job

Run `docker compose logs -f api worker scheduler`. The services emit JSON logs with `request_id`, `trace_id`, and `span_id` where available. The API returns `X-Request-ID` on responses, and the Next.js proxy forwards it. For a queued operation, search for the request ID or the job ID returned by the API. Scheduled jobs generate their own request IDs.

Compose sends traces to Tempo at `http://tempo:4318`. Its query API is available on loopback port 3200. For example, query `/api/traces/<trace-id>` to see API, database, and RQ spans for a queued request. To export to a Collector or hosted backend, set `OTEL_EXPORTER_OTLP_ENDPOINT` to the OTLP/HTTP base URL or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` to the full trace endpoint. Use `OTEL_EXPORTER_OTLP_HEADERS` for collector credentials.

The `stock_agents_http_request_duration_seconds` histogram has bounded labels for route template, HTTP method, and status. Job execution counters and duration sums are stored in PostgreSQL so worker restarts preserve them. They cover RQ jobs and direct end-of-day refreshes recorded after Phase 5. A refresh waiting for the exchange to publish its data is counted as `deferred`.

## 4. Run CI

The GitHub Actions workflow runs for pull requests, pushes to `main`, and manual dispatch. It checks Python with Ruff, mypy, and pytest against TimescaleDB, builds and checks Next.js with pnpm, and starts a fresh Compose stack to smoke-test readiness, metrics, and the deep-health authentication guard.
