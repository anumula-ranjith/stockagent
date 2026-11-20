# PostgreSQL cutover

PostgreSQL is the warehouse for FastAPI, ingestion, scoring and backtests.
The snapshot import below is retained for older installations migrating an
existing DuckDB file. Install the development dependencies to use that legacy
importer. New installations use PostgreSQL directly.

## 1. Prepare PostgreSQL

Create a local PostgreSQL database owned by the role in `DATABASE_URL`.
From the repository root with the project virtual environment active, run:

```powershell
python -m stock_agents.cli init-db
python -m alembic current
python -m alembic check
```

The first migration applies `scripts/sql/init.sql` on a fresh database.
Alembic then applies each outstanding revision. The same command upgrades
existing Alembic-managed warehouses and preserves existing rows. For a
legacy warehouse created from ORM metadata with no Alembic history, back it
up and compare its schema with the recorded revisions before stamping its
matching revision.

## 2. Optional TimescaleDB and future migrations

The standard install uses ordinary PostgreSQL tables. On a TimescaleDB
installation supporting the columnstore API, apply `scripts/sql/timescale.sql`
with `psql -v ON_ERROR_STOP=1` against the configured database if you want
the `prices_daily` hypertable and compression policy. This can migrate
existing prices, so take a backup and schedule the change before running it.

For future schema changes, update SQLAlchemy metadata, generate a revision
with `python -m alembic revision --autogenerate -m "describe change"`, review
it, then run `python -m alembic upgrade head`. Check for drift with
`python -m alembic check`.

## 3. Import and reconcile

Pause writers to the DuckDB file before importing. Run the import before
starting the API and worker.

```powershell
python -m scripts.migrate_duckdb_to_postgres
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

## 4. Verify the database

Start the native services using the [local startup guide](../DEPLOY.md),
then request the warehouse counts.

```powershell
Invoke-RestMethod 'http://127.0.0.1:8701/health?include_stats=true'
```

To run the integration test from the host, install
`requirements-dev.txt` and set `TEST_DATABASE_URL` to a development
PostgreSQL server with permission to create a temporary database.

```powershell
python -m pytest tests/test_postgres_schema.py
```

The test exercises PostgreSQL even when TimescaleDB is unavailable. On a
server with the extension, it also checks the hypertable.
