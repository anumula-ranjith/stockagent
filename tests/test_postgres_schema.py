from datetime import UTC, date, datetime, timedelta

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text

from stock_agents.api import diagnostics
from stock_agents.api.auth import make_token
from stock_agents.api.main import app
from stock_agents.common.config import project_root
from stock_agents.storage.postgres import Base, database_url
from stock_agents.storage.schema import ALL_TABLES, connect, init_schema


def test_postgres_metadata_covers_warehouse():
    assert set(Base.metadata.tables) == {table.name for table in ALL_TABLES} | {
        "users",
        "job_runs",
        "audit_log",
        "job_metrics",
        "account_tokens",
        "company_reference",
        "portfolio_accounts",
        "portfolio_entries",
        "watchlists",
        "watchlist_items",
        "broker_snapshots",
        "pipeline_runs",
        "pipeline_schedules",
    }


def test_managed_postgres_tls_url_works_for_both_drivers():
    value = "postgresql://user:password@database.example.com/warehouse?sslmode=require"
    assert dict(database_url("asyncpg", value).query) == {"ssl": "require"}
    assert dict(database_url("psycopg2", value).query) == {"sslmode": "require"}


def test_migration_and_api_parity(postgres_url, _isolated_paths, monkeypatch):
    from scripts.migrate_duckdb_to_postgres import migrate

    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("JWT_SECRET", "integration-test-key-for-postgres-parity")
    async def healthy():
        return None

    monkeypatch.setattr(diagnostics, "redis_check", healthy)
    monkeypatch.setattr(diagnostics, "s3_check", healthy)
    engine = create_engine(database_url("psycopg2"))
    sql_dir = project_root() / "scripts" / "sql"
    with engine.begin() as target:
        target.exec_driver_sql((sql_dir / "init.sql").read_text(encoding="utf-8"))
        timescale_available = target.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb')")
        )
        if timescale_available:
            target.exec_driver_sql((sql_dir / "timescale.sql").read_text(encoding="utf-8"))
            assert (
                target.scalar(
                    text(
                        "SELECT count(*) FROM timescaledb_information.hypertables "
                        "WHERE hypertable_name = 'prices_daily'"
                    )
                )
                == 1
            )
    command.upgrade(Config(str(project_root() / "alembic.ini")), "head")

    duck_path = _isolated_paths.paths.duckdb
    today = date.today()
    sample = {
        "VARCHAR": "sample",
        "BIGINT": 123,
        "INTEGER": 4,
        "DOUBLE": 10.5,
        "BOOLEAN": True,
        "DATE": today,
        "TIMESTAMP": "2025-01-02 12:00:00",
    }
    expected_rows = {}
    with connect(str(duck_path)) as source:
        init_schema(source)
        for table in ALL_TABLES:
            fields = source.execute(f"DESCRIBE {table.name}").fetchall()
            row = [
                "AAA" if name == "ticker" else "technical" if name == "agent" else sample[dtype]
                for name, dtype, *_ in fields
            ]
            values = ", ".join("?" for _ in row)
            source.execute(f"INSERT INTO {table.name} VALUES ({values})", row)
            if table.name == "quality_log":
                source.execute(f"INSERT INTO {table.name} VALUES ({values})", row)
            elif table.name == "prices_daily":
                source.execute(
                    """INSERT INTO prices_daily (ticker, date, close, source, known_date)
                       VALUES ('AAA', ?, 999, ' FactSet', ?)""",
                    [today, today],
                )
            elif table.name == "classification":
                source.execute(
                    """INSERT INTO classification VALUES (?, ?, ?, 'FUTURE', NULL, 'other')""",
                    ["AAA", today, today + timedelta(days=1)],
                )
            columns = ", ".join(Base.metadata.tables[table.name].columns.keys())
            expected_rows[table.name] = source.execute(
                f"SELECT {columns} FROM {table.name}"
            ).fetchall()

    for _ in range(2):
        counts = migrate(duck_path, engine)
        assert all(source == target for _, source, target in counts)
    with engine.begin() as target:
        for table in ALL_TABLES:
            rows = target.execute(select(Base.metadata.tables[table.name])).all()
            actual_rows = [
                tuple(
                    value.astimezone(UTC).replace(tzinfo=None)
                    if isinstance(value, datetime) and value.tzinfo is not None
                    else value
                    for value in row
                )
                for row in rows
            ]
            assert sorted(actual_rows, key=repr) == sorted(expected_rows[table.name], key=repr)
        for name in ("users", "job_runs"):
            table = Base.metadata.tables[name]
            values = (
                {"email": "sample@example.com", "hashed_pwd": "fixture"}
                if name == "users"
                else {"job_type": "sample", "status": "queued"}
            )
            target.execute(table.insert().values(**values))
            row = target.execute(select(table)).one()
            assert row.id
            if name == "users":
                user_id = str(row.id)

    routes = [
        "/health?include_stats=true",
        "/universe",
        "/prices/AAA",
        "/news/AAA",
        "/sentiment/AAA",
        "/agents/technical",
        "/combine",
        "/scores/AAA",
        "/backtest/latest",
    ]
    headers = {"Authorization": f"Bearer {make_token(user_id).access_token}"}
    with TestClient(app, headers=headers) as client:
        monkeypatch.setenv("STORAGE_BACKEND", "duckdb")
        expected = {route: client.get(route) for route in routes}
        assert all(response.status_code == 200 for response in expected.values())
        assert expected["/universe"].json()[0]["sector"] == "sample"
        assert len(expected["/prices/AAA"].json()) == 1
        assert expected["/agents/technical"].json()[0]["sector"] == "sample"
        assert expected["/combine"].json()["longs"][0]["sector"] == "sample"
        assert expected["/scores/AAA"].json()[0]["score"] == 10.5
        assert client.get("/combine?technical=0&sentiment=0&momentum=0&fundamental=0").status_code == 422
        monkeypatch.setenv("STORAGE_BACKEND", "postgres")
        for route in routes:
            response = client.get(route)
            assert (response.status_code, response.content) == (200, expected[route].content), route
        with engine.begin() as target:
            target.execute(Base.metadata.tables["symbology"].insert().values(ticker="PG_ONLY"))
        assert {row["ticker"] for row in client.get("/universe").json()} == {"AAA", "PG_ONLY"}
    engine.dispose()
