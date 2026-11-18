from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from stock_agents.engine.backtest import run_backtest
from stock_agents.engine.scores import compute_and_store
from stock_agents.ingest.news import ingest_news, ingest_sentiment_daily
from stock_agents.ingest.prices import (
    backfill_prices,
    ingest_bulk_last_day,
    ingest_corporate_actions,
)
from stock_agents.storage.warehouse import connect


def test_ingestion_scores_and_backtest_use_postgres(auth_database, _isolated_paths):
    today = date.today()
    client = SimpleNamespace(
        eod=lambda *args, **kwargs: [{
            "date": str(today - timedelta(days=offset)), "open": 100, "high": 105, "low": 99,
            "close": 103, "adjusted_close": 103, "volume": 500,
        } for offset in range(280)],
        splits=lambda symbol: [{"date": str(today), "split": "2/1"}],
        dividends=lambda symbol: [],
        news=lambda *args, **kwargs: [{"date": f"{today}T15:00:00Z", "title": "Earnings"}],
        sentiments=lambda symbol: {
            symbol: [{"date": str(today), "count": 4, "normalized": 0.2}]
        },
    )
    with connect() as conn:
        conn.execute("INSERT INTO symbology(ticker,eodhd_symbol) VALUES (?,?)", ["TEST", "TEST.NSE"])
        assert backfill_prices(conn, client, tickers=["TEST"]) == 280
        assert ingest_corporate_actions(conn, client, tickers=["TEST"]) == 1
        assert ingest_news(conn, client, tickers=["TEST"]) == 1
        assert ingest_sentiment_daily(conn, client, tickers=["TEST"]) == 1
        assert set(compute_and_store(conn, today)) == {
            "technical", "momentum", "sentiment", "fundamental"
        }
        assert run_backtest(conn, today, today, persist=False)["n_days"] == 1
    with auth_database.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM prices_daily")) == 280
        assert conn.scalar(text("SELECT count(*) FROM agent_scores")) == 4
    assert not _isolated_paths.paths.duckdb.exists()


def test_warehouse_rolls_back_failed_transaction(auth_database):
    with pytest.raises(ValueError, match="deliberate"):
        with connect() as conn:
            conn.execute("INSERT INTO symbology(ticker) VALUES (?)", ["ROLLBACK"])
            raise ValueError("deliberate")
    with auth_database.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM symbology WHERE ticker='ROLLBACK'")) == 0


@pytest.mark.parametrize("loader", ["backfill", "bulk"])
def test_vendor_ingestion_replaces_fallback_without_duplicate_bars(auth_database, loader):
    today = date.today()
    earlier = today - timedelta(days=2)
    bar = dict(date=str(today), code="TEST", open=100, high=105, low=99,
               close=103, adjusted_close=103, volume=500)
    client = SimpleNamespace(eod=lambda *args, **kwargs: [bar],
                             bulk_eod=lambda *args, **kwargs: [bar])
    with connect() as conn:
        conn.execute("INSERT INTO symbology(ticker,eodhd_symbol) VALUES (?,?)", ["TEST", "TEST.NSE"])
        conn.execute("""INSERT INTO prices_daily
            (ticker,date,open,high,low,close,volume,source,known_date)
            VALUES ('TEST',?,100,105,99,103,500,'nse_bhavcopy',?)""", [today, earlier])
        if loader == "backfill":
            assert backfill_prices(conn, client, tickers=["TEST"]) == 1
        else:
            assert ingest_bulk_last_day(conn, client, "NSE", today) == 1
        assert conn.execute("SELECT source,adj_close FROM prices_daily").fetchall() == [("eodhd", 103)]
        conn.execute("UPDATE prices_daily SET known_date=?", [earlier])
        assert ingest_bulk_last_day(conn, client, "NSE", today) == 1
        assert conn.execute("SELECT known_date FROM prices_daily").fetchall() == [(earlier,)]
        assert run_backtest(conn, today, today, persist=False)["n_days"] == 1
