from sqlalchemy import create_engine, inspect, text

from stock_agents import cli
from stock_agents.storage.postgres import database_url


def test_init_db_cli_creates_postgres_warehouse(postgres_url, _isolated_paths):
    engine = create_engine(database_url("psycopg2", postgres_url))
    try:
        cli.main(["init-db"])
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO symbology (ticker) VALUES ('LOCAL')"))
        cli.main(["init-db"])
        assert {"prices_daily", "signals", "nav", "alembic_version"} <= set(inspect(engine).get_table_names())
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT ticker FROM symbology")) == "LOCAL"
    finally:
        engine.dispose()
    assert not _isolated_paths.paths.duckdb.exists()
