from sqlalchemy import inspect

from stock_agents import cli


def test_init_db_cli_creates_postgres_warehouse(auth_database, _isolated_paths):
    cli.main(["init-db"])
    assert {"prices_daily", "signals", "nav"} <= set(inspect(auth_database).get_table_names())
    assert not _isolated_paths.paths.duckdb.exists()
