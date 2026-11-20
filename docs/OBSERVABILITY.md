# Observability and CI

## 1. Start the stack

Follow [Local startup](../DEPLOY.md). Run `python -m scripts.local prepare`
before starting a new version to apply Alembic migrations and ensure the
configured local artifact bucket exists.

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

Read the API, worker and scheduler terminals. The services emit JSON logs with `request_id`, `trace_id`, and `span_id` where available. The API returns `X-Request-ID` on responses, and the Next.js proxy forwards it. For a queued operation, search for the request ID or the job ID returned by the API. Scheduled jobs generate their own request IDs.

To collect local traces, start Tempo with `config/tempo.yaml` and set
`OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318` in the root `.env`.
The local receiver exposes trace lookup at `http://127.0.0.1:3200/api/traces/<trace-id>`.
Set `OTEL_EXPORTER_OTLP_HEADERS` if your receiver requires credentials.

The `stock_agents_http_request_duration_seconds` histogram has bounded labels for route template, HTTP method, and status. Job execution counters and duration sums are stored in PostgreSQL so worker restarts preserve them. They cover RQ jobs and direct end-of-day refreshes recorded after Phase 5. A refresh waiting for the exchange to publish its data is counted as `deferred`.

## 4. Run CI

CI runs Ruff, mypy and pytest against native PostgreSQL. An isolated API,
Redis, RQ worker, scheduler and SeaweedFS instance exercise readiness,
authentication, a queued backtest and a private signed artifact download.
A separate job lints, builds and type-checks the Next.js app. Run the local
verification commands in [Local startup](../DEPLOY.md) to check your install.
