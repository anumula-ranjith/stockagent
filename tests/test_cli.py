from stock_agents import cli
from stock_agents.storage import schema


def test_init_db_cli_creates_warehouse(tmp_path, monkeypatch):
    # cli.init_db will write to settings.paths.duckdb; the conftest fixture
    # already redirected it to tmp_path, so this exercises the whole path.
    cli.main(["init-db"])
    from stock_agents.common.config import load_settings

    s = load_settings()
    assert s.paths.duckdb.exists()
    conn = schema.connect(str(s.paths.duckdb))
    try:
        tables = set(schema.list_tables(conn))
        assert {"prices_daily", "signals", "nav"} <= tables
    finally:
        conn.close()
