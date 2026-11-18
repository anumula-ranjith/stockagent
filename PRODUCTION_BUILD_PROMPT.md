# Production build prompt — stock-agents

Paste this whole file into a fresh Claude Code session inside the
`stock-agents/` repo. It takes the current working DuckDB + FastAPI + HTML
prototype to the production stack in the screenshot. Nothing in here is
speculation — everything maps to an existing file to replace or extend.

---

## What exists today (don't rebuild)

- **Backend**: FastAPI at `src/stock_agents/api/main.py` with these endpoints,
  all tested and working:
    - `GET /health /universe /prices/{ticker} /news/{ticker} /sentiment/{ticker}`
    - `GET /agents/{name} /combine /backtest/latest`
    - `POST /backtest/run?start=&end=&n=`
- **Data layer**: DuckDB at `data/market.duckdb`, 27 tables defined in
  `src/stock_agents/storage/schema.py`. Point-in-time columns on every fact
  table (`effective_date`, `known_date`).
- **Ingest**: EODHD NSE client at `src/stock_agents/sources/eodhd.py`,
  ingest wrappers at `src/stock_agents/ingest/{prices,news,universe}.py`.
- **Engine**: factor + agent + combiner + backtest in
  `src/stock_agents/{factors,engine}/*`.
- **UI**: Vanilla HTML + CSS at `src/stock_agents/ui/` — home, dashboard,
  stocks explorer, per-ticker, backtest, methodology, shared header/footer
  via a template shell in `main.py`.
- **Universe**: 213 Nifty 200 tickers at `config/universe_seed.csv`.
- **Credentials**: `.env` has EODHD, FactSet (Formula API), FRED, Alpaca
  paper keys. Never commit `.env`.
- **Partial production scaffolds already placed**:
    - `docker-compose.yml` with Postgres+TimescaleDB, Redis, MinIO, api, worker
    - `Dockerfile` (multi-stage)
    - `requirements-prod.txt`
    - `scripts/sql/init.sql` — Postgres schema with the Timescale hypertable
    - `src/stock_agents/api/schemas.py` — Pydantic request/response models
    - `src/stock_agents/storage/postgres.py` — async SQLAlchemy ORM
    - `src/stock_agents/storage/s3.py` — MinIO/S3 helper
    - `src/stock_agents/jobs/worker.py` — RQ worker with 3 jobs
    - `src/stock_agents/api/auth.py` — JWT auth (passlib + pyjwt)
    - `PRODUCTION_BUILD_PROMPT.md` — this file

**Do not rebuild anything above. Read it, extend it, and only replace what
the phase explicitly tells you to.**

---

## Target stack (from the screenshot)

| Layer | Target |
|---|---|
| Frontend | Next.js 15 + React 19 + TypeScript + Tailwind + shadcn/ui |
| Charts | TradingView Lightweight Charts (prices), Recharts (equity + metrics), TanStack Table (rankings) |
| Backend API | FastAPI + Pydantic v2 + SQLAlchemy 2.x (async) |
| Workers | RQ + Redis (keep as-is; Celery is overkill) |
| Scheduler | APScheduler for daily EOD; Prefect in a later phase |
| Primary DB | PostgreSQL + TimescaleDB (prices_daily hypertable) |
| Research store | DuckDB + Parquet (kept, for backtest scans) |
| Cache + queue | Redis |
| Object storage | S3 (prod) / MinIO (dev) |
| Auth | FastAPI JWT for self-hosted, Clerk/Auth0 adapter as option |
| Hosting | Frontend on Vercel; API + workers on Render / Railway / Fly.io / AWS ECS; database on Timescale Cloud / RDS / Supabase |

---

## Non-negotiables

1. **Never invent an endpoint, field name or metric code.** If a data source
   needs a call, run a probe script first (`scripts/probe_*.py`), save the
   response under `tests/fixtures/`, then write the ingest against the real
   shape.
2. **Point-in-time or it doesn't ship.** Every ingest writes `known_date`.
   Every factor/agent query filters on `known_date <= t`.
3. **Secrets only from `.env`** (local dev) or the host's secret manager
   (AWS Secrets Manager / Fly secrets / Railway variables / Vercel env).
   Never log a secret. Never commit one.
4. **FactSet is licensed data.** It never leaves the authenticated API. No
   public cache, no Vercel edge cache, no shared dashboard export.
5. **No feature flag plumbing, no hypothetical abstractions, no commented-out
   code.** Delete what you replace.
6. **Every phase ends in a green test suite and a working `docker compose up`.**

---

## Phases

Each phase is self-contained. At the end of a phase, stop and summarize
what works + what doesn't. Don't start the next phase until the user signs
off.

### Phase 1 — Postgres cutover (foundation)

Replace DuckDB as the operational store. Keep DuckDB for the backtest
research path.

Tasks:
1. `docker compose up postgres redis minio` — confirm all three are healthy.
   Run `scripts/sql/init.sql` against the Postgres container (it's wired as
   a mount so it runs on first boot). Verify all tables + the hypertable
   exist: `SELECT * FROM timescaledb_information.hypertables;`
2. Add `scripts/migrate_duckdb_to_postgres.py`:
   - Read every DuckDB table.
   - Write to the matching SQLAlchemy ORM model in
     `src/stock_agents/storage/postgres.py`.
   - Use `INSERT ... ON CONFLICT DO NOTHING` so re-runs are idempotent.
   - Chunk `prices_daily` into month batches so Timescale compression kicks in.
   - Print a row-count diff table at the end.
3. Add Alembic:
   - `alembic init src/stock_agents/storage/alembic`
   - Point `env.py` at `postgres.Base.metadata` and `DATABASE_URL`.
   - `alembic revision --autogenerate -m "initial"` — verify it only
     generates the delta vs. `init.sql` (should be empty if `init.sql` is
     already applied).
   - Document the migration workflow in `docs/MIGRATIONS.md`.
4. Add a feature-switched DB layer:
   - `src/stock_agents/storage/__init__.py` exports `get_conn()` that
     returns a DuckDB connection or a SQLAlchemy session based on
     `STORAGE_BACKEND=duckdb|postgres` env var.
   - Rewrite `api/main.py` endpoints to use the SQLAlchemy sessions
     (async, via `Depends(get_session)`).
   - Keep the engine modules (`engine/scores.py`, `engine/backtest.py`)
     on DuckDB — they're research code, not operational code.
5. Smoke test:
   - `pytest tests/test_postgres_schema.py` — new file, verifies every
     ORM model round-trips a sample row.
   - Hit every existing JSON endpoint against Postgres and compare the
     response shape byte-for-byte with the DuckDB version.
6. Done when: `STORAGE_BACKEND=postgres docker compose up api` serves
   the same JSON as `python -m uvicorn stock_agents.api.main:app`.

### Phase 2 — Auth + user model

Lock down the API before the Next.js frontend starts calling it.

Tasks:
1. Wire `src/stock_agents/api/auth.py` into `main.py`:
   - `POST /login` — body `{email, password}`, returns JWT.
   - `POST /signup` — admin-only unless a `BOOTSTRAP_SIGNUP_TOKEN` env var
     matches (one-time bootstrap for the first admin).
   - `GET /me` — returns the current user.
   - Mark these as "require_admin" via `Depends(require_admin)`:
     `POST /backtest/run`, `POST /admin/ingest`, `POST /admin/recompute`.
   - Mark these as "require_user": `GET /universe /combine` etc. only
     when the request includes any FactSet-derived field.
2. Add a Clerk adapter at `src/stock_agents/api/auth_clerk.py`:
   - Fetch JWKS from `CLERK_JWKS_URL`, cache 10 min.
   - `verify_clerk_jwt(token) -> UserOut`.
   - `AUTH_PROVIDER=jwt|clerk` env var switches between the two.
3. Rate limit: add `slowapi` on `/login` (5/min per IP) and
   `/backtest/run` (3/hour per user).
4. Audit: every admin-only action writes a row to a new `audit_log` table
   with user_id, action, ip, timestamp, request hash.
5. Done when: unauthenticated curl against `/backtest/run` returns 401,
   authenticated non-admin returns 403, admin returns 202 with a job_id.

### Phase 3 — Workers, scheduler, job dashboard

Move heavy work off the API process.

Tasks:
1. Replace `POST /backtest/run` body:
   - Use `jobs.worker.enqueue_backtest(start, end, n)`.
   - Return `202 {job_id, status: "queued"}`.
2. Add `GET /jobs/{job_id}` — returns status + result key + presigned S3 URL
   when the result lands.
3. Add `scripts/schedule_daily.py` using APScheduler:
   - 18:30 IST — `ingest_prices_job(years=1)` (incremental).
   - 19:00 IST — `ingest_news_job()` + `ingest_sentiment_daily_job()`.
   - 19:30 IST — `compute_scores_job()`.
   - Wire it into docker-compose as a `scheduler` service.
4. Mount `rq-dashboard` at `/_admin/rq` (admin-only) so the operator can see
   queue depth, failed jobs, retry a failure.
5. Done when: enqueue a backtest from the Next.js UI → it lands as JSON in
   MinIO → the UI polls `/jobs/{job_id}` → renders the chart.

### Phase 4 — Next.js frontend

Stand up the production UI.

Tasks:
1. `apps/web/` — create a new Next.js 15 app (`pnpm create next-app@latest
   apps/web --ts --tailwind --app --eslint --src-dir`).
2. Install shadcn/ui, Recharts, TradingView Lightweight Charts, TanStack
   Table, TanStack Query (for API calls), zod, nuqs (URL state).
3. Generate TypeScript types from the FastAPI OpenAPI:
   - Add a script: `pnpm gen:api` → `openapi-typescript
     http://localhost:8701/openapi.json -o src/lib/api-types.ts`.
   - Add a fetcher `src/lib/api.ts` that reads
     `NEXT_PUBLIC_API_BASE` and attaches the Clerk JWT (when
     `AUTH_PROVIDER=clerk`) or a cookie token.
4. Port the pages from `src/stock_agents/ui/templates/`:
   - `/` — home (hero + feature grid + live snapshot from `/combine?n=5`).
   - `/dashboard` — 4-agent tuner. Weights are controlled React state;
     `/combine` is re-fetched via TanStack Query on slider change,
     debounced 300 ms.
   - `/stocks` — TanStack Table over `/universe` joined with all 4 agent
     score maps. Column sort, text search, sector filter (nuqs URL state).
   - `/stocks/[ticker]` — TradingView Lightweight Charts for the price
     series, Recharts for the score history, news table.
   - `/backtest` — POST to `/backtest/run`, poll `/jobs/{id}`, render the
     equity curve with Recharts and the final book with TanStack Table.
   - `/methodology` — port as-is.
5. Dark mode via `next-themes`, driven by the same CSS variables as the
   current `src/stock_agents/ui/static/styles.css`.
6. Delete the old HTML `templates/` + FastAPI page routes when the Next.js
   app covers all six pages.
7. Done when: `pnpm dev` on 3000 + `uvicorn` on 8701, the UI works
   end-to-end against the production stack, Lighthouse Performance >= 90.

### Phase 5 — Observability + ops

Tasks:
1. Structured JSON logs via `structlog`. Every request gets a request_id,
   every job inherits it.
2. OpenTelemetry tracing — spans on every DB query and every API endpoint.
   Point at Grafana Tempo in dev, Honeycomb or Datadog in prod.
3. Prometheus `/metrics` endpoint on the API. One useful metric per endpoint
   (latency histogram), one per job type (duration + success counter).
4. Healthchecks:
   - `/health` returns 200 only if the Postgres query + Redis ping + S3
     head-bucket all pass.
   - `/health/deep` adds an EODHD and FactSet reachability probe (admin-only).
5. CI: GitHub Actions workflow at `.github/workflows/ci.yml` running
   ruff + mypy + pytest + `docker build` + a smoke `docker compose up -d`
   with a one-shot curl at `/health`.
6. Done when: pushing to main deploys to Render/Fly with zero manual
   steps, and a failed healthcheck rolls back.

### Phase 6 — Hosting

Pick one path and wire it. All three are documented in `DEPLOY.md`
(write it as part of this phase).

**Path A — Render + Timescale Cloud + Upstash Redis + S3** (easiest)
- Render Web Service for the API (Dockerfile build).
- Render Background Worker for RQ.
- Render Cron Job for the scheduler.
- Timescale Cloud for the DB (managed Postgres with the extension).
- Upstash Redis.
- AWS S3 bucket (not Render's disks).
- Vercel for the Next.js frontend (`apps/web`).

**Path B — Fly.io** (cheaper, requires more ops)
- Fly app for the API (3 regions).
- Fly machine for the worker.
- Fly scheduled machine for cron.
- Fly Postgres (apply TimescaleDB extension manually).
- Upstash Redis.
- AWS S3.
- Vercel for frontend.

**Path C — AWS** (if the firm already uses AWS)
- ECS Fargate for API + worker + scheduler.
- RDS Postgres with TimescaleDB extension (or Aurora PostgreSQL + Timescale).
- Elasticache Redis.
- S3.
- CloudFront + S3 for the Next.js frontend (or Vercel still).
- Secrets Manager.

Tasks in this phase:
1. Write `DEPLOY.md` covering all three.
2. Pick one with the user. Ship it. Shake out env-var problems.
3. Document the rollback procedure.

### Phase 7 — Pro data features

These unlock the full product once the stack is solid.

1. **Live-ish prices**: EODHD WebSocket (intraday prices during NSE hours)
   → Redis Streams → API server-sent-events on `/stream/prices/{ticker}`
   → chart updates every 5s on the frontend.
2. **FactSet fundamentals ingest** — write real parsers for the Formula API
   batch responses. Store into `fundamentals_pit` with correct
   `known_date` = filing date.
3. **News embeddings**: pgvector on the Postgres, compute embeddings for
   every headline, serve similar-news on the per-ticker page.
4. **Alerts**: a rule engine that watches `/combine` output and posts to
   `SLACK_WEBHOOK_URL` / email when a name enters or leaves the book.
5. **Portfolio tracker**: `positions` table + a page that shows the live
   book (longs/shorts open, PnL from the last rebalance, next rebalance
   date).

---

## Working style

- **Ask before anything irreversible** — dropping a prod table, deleting a
  cloud resource, pushing to main, changing a user's permissions.
- **Run the probe first** — any new EODHD/FactSet/FRED endpoint. Save the
  fixture before writing ingest.
- **Keep tests passing** — `pytest` must stay green at every commit.
- **Short commits**, conventional style:
  `feat(api): ...`, `fix(engine): ...`, `chore(deps): ...`.
- **One PR per phase** unless the user asks otherwise. Open as draft, the
  user reviews, then marked ready.
- **Stop at phase boundaries** — summarize, don't roll into the next phase.

---

## What to do right now when a user hands you this file

1. Read this whole file.
2. Read the "What exists today" files (don't just glance, read them).
3. Ask the user:
   - Which phase do they want first? Default is Phase 1.
   - Which hosting path do they lean toward? (affects Phase 6 choices and
     some Phase 1 env-var decisions).
   - Do they want Clerk/Auth0 or self-hosted JWT? (affects Phase 2).
4. Open a plan with `update_plan`, list the phase's tasks, start work.
5. Save intermediate decisions to `docs/DECISIONS.md` so the next session
   can pick up where you stopped.
