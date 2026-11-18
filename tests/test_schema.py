from stock_agents.storage import schema


def _expected() -> set[str]:
    return {t.name for t in schema.ALL_TABLES}


def test_init_schema_creates_every_table():
    conn = schema.connect(":memory:")
    try:
        schema.init_schema(conn)
        got = set(schema.list_tables(conn))
        missing = _expected() - got
        assert not missing, f"not created: {missing}"
    finally:
        conn.close()


def test_init_schema_is_idempotent():
    conn = schema.connect(":memory:")
    try:
        schema.init_schema(conn)
        schema.init_schema(conn)
        # If it re-ran DDL cleanly, table count matches.
        assert set(schema.list_tables(conn)) >= _expected()
    finally:
        conn.close()


def test_pit_columns_present():
    """Every fact table has known_date so PIT reads can enforce <= t."""
    conn = schema.connect(":memory:")
    try:
        schema.init_schema(conn)
        pit_tables = [
            "prices_daily",
            "fundamentals_pit",
            "estimates_pit",
            "analyst_pit",
            "earnings_surprise",
            "events_calendar",
            "news",
            "sentiment_daily",
            "insider_tx",
            "short_interest",
            "social_daily",
            "macro",
            "classification",
            "corporate_actions",
        ]
        for t in pit_tables:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info('{t}')").fetchall()]
            assert "known_date" in cols, f"{t} missing known_date"
    finally:
        conn.close()
