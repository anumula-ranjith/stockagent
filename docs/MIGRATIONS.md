# PostgreSQL cutover

PostgreSQL is the warehouse for FastAPI, ingestion, scoring and backtests.
The snapshot import below is retained for older installations migrating an
existing DuckDB file. Install the development dependencies to use that legacy
importer. New installations use PostgreSQL directly.

## 1. Start the infrastructure

Copy `.env.example` to `.env` if needed. Run the following from the repository
root with Docker Compose and a local `data/market.duckdb` file.

```powershell
docker compose up -d --wait postgres redis object-store
docker compose exec postgres psql -U stockagents -d stockagents -c "SELECT hypertable_name FROM timescaledb_information.hypertables;"
```

Compose uses SeaweedFS for its local S3 endpoint. To retain artifacts from an older MinIO volume, copy the objects through the S3 API before retiring that volume.

Use the configured database user and name if they differ from the development
defaults. Expect `prices_daily` in the result. A new volume applies
`scripts/sql/init.sql` followed by `scripts/sql/timescale.sql`. For an
existing development volume created from the earlier scaffold, back it up and
apply both updated SQL files in the same order with `psql -v ON_ERROR_STOP=1`.

## 2. Verify and register the baseline

```powershell
docker compose build api
docker compose run --rm --no-deps api python -m alembic stamp 0001_postgres_baseline
docker compose run --rm --no-deps api python -m alembic upgrade head
docker compose run --rm --no-deps api python -m alembic check
```

Stamp the baseline once after SQL bootstrap, then apply the current
revisions. `alembic check` should report zero new operations. Resolve any
differences before the API cutover. For
subsequent schema changes, update SQLAlchemy metadata, generate a revision
with `python -m alembic revision --autogenerate -m "describe change"`, review
it, then run `python -m alembic upgrade head`. Timescale-specific DDL belongs
in reviewed SQL within the migration.

## 3. Import and reconcile

Pause writers to the DuckDB file before importing. Run the import before
starting the API and worker.

```powershell
docker compose run --rm --no-deps api python -m scripts.migrate_duckdb_to_postgres
```

The command opens the source in read-only mode. It imports all 27
warehouse tables in one PostgreSQL transaction and batches prices in calendar
months. Timescale uses 30-day chunks and converts older chunks to the
columnstore according to its 90-day policy. Reimports use
`ON CONFLICT DO NOTHING` for existing primary keys. The quality log preserves
the number of occurrences of each source row. The command prints counts for
both stores and exits with a nonzero status if any target count differs.
DuckDB timestamps without time zones are interpreted as UTC when the
destination column has a time zone.

## 4. Start and test the API

```powershell
docker compose up -d --wait
Invoke-RestMethod 'http://127.0.0.1:8701/health?include_stats=true'
```

Open [the local dashboard](http://127.0.0.1:8701/dashboard) or
[the API docs](http://127.0.0.1:8701/docs). All runtime services use PostgreSQL. Keep the stack on loopback until the authentication phase.

To run the integration test from the host, install
`requirements-dev.txt` and set `TEST_DATABASE_URL` to a development
PostgreSQL server with permission to create a temporary database.

```powershell
python -m pytest tests/test_postgres_schema.py
```

The test exercises PostgreSQL even when TimescaleDB is unavailable. On a
server with the extension, it also checks the hypertable.
