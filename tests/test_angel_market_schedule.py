from datetime import UTC, date, datetime
from unittest.mock import Mock

import pytest
from sqlalchemy import text

from scripts import refresh_angel_market as runner
from scripts.schedule_daily import build_scheduler
from stock_agents.ingest import daily
from stock_agents.jobs import pipeline_stages


@pytest.mark.parametrize(("at", "due"), [
    ("2026-11-20T09:45:59", False),
    ("2026-11-20T09:46:00", True),
    ("2026-11-20T09:59:59", True),
    ("2026-11-20T10:00:00", False),
    ("2026-11-21T09:46:00", False),  # Saturday
    ("2026-11-24T09:46:00", False),  # NSE holiday
])
def test_market_window_uses_exchange_session_and_india_time(at, due):
    assert runner.in_capture_window(datetime.fromisoformat(at).replace(tzinfo=UTC)) == due


def test_screen_distinguishes_manual_updates_from_scheduled_attempts(auth_database, monkeypatch):
    from stock_agents.api import screener
    from stock_agents.jobs import queue

    monkeypatch.setattr(queue, "sync_engine", lambda: auth_database)
    monkeypatch.setattr(screener, "connection_status", lambda: {"connected": False, "expires_at": None})
    day = datetime.now(screener.TZ).date()
    ended = datetime.combine(day, datetime.min.time())
    insert_run = text("""INSERT INTO run_log(run_id, job, status, started_at, ended_at, rows_written)
                         VALUES (:id, 'angel_market', :status, :ended, :ended, :rows)""")
    with auth_database.begin() as conn:
        conn.execute(insert_run, dict(id=f"angel-manual-{day}", status="ok", ended=ended, rows=501))
    report = screener.screen_market_status(None)
    assert report.connected is False
    assert report.scheduled_status not in {"complete", "failed", "partial"}
    assert report.last_update.method == "Manual capture"
    assert report.last_update.completed_at == ended.replace(tzinfo=UTC)
    with auth_database.begin() as conn:
        conn.execute(insert_run, dict(id=f"angel-market-{day}", status="failed", ended=ended, rows=0))
    report = screener.screen_market_status(None)
    assert report.scheduled_status == "failed"
    assert report.last_update.method == "Manual capture"


def test_angel_mode_preserves_other_schedules(monkeypatch):
    monkeypatch.setenv("MARKET_PRICE_PROVIDER", "angel_one")
    jobs = {job.id for job in build_scheduler().get_jobs()}
    assert jobs.isdisjoint({"ingest", "eod-catchup"})
    assert {"news", "sentiment", "nifty-provider-inputs", "job-outbox"} <= jobs


def test_eod_never_fetches_another_price_in_angel_mode(monkeypatch):
    monkeypatch.setenv("MARKET_PRICE_PROVIDER", "angel_one")
    def unexpected(*args, **kwargs):
        pytest.fail("After-close workflow attempted a vendor request")
    monkeypatch.setattr(daily, "NSEClient", unexpected)
    monkeypatch.setattr(daily.EODHDClient, "from_env", unexpected)
    conn = Mock()
    conn.scalar.return_value = None
    day = date(2026, 11, 18)
    assert daily.refresh_eod(conn, day)["status"] == "skipped"
    conn.scalar.return_value = '{"status":"ok","trade_date":"2026-11-18","priced":1}'
    assert daily.refresh_eod(conn, day)["priced"] == 1


def test_capture_retries_partial_then_reuses_complete_snapshot(auth_database, monkeypatch):
    from stock_agents.ingest import angel_prices

    monkeypatch.setenv("MARKET_PRICE_PROVIDER", "angel_one")
    monkeypatch.setattr(pipeline_stages, "sync_engine", lambda: auth_database)
    redis = Mock()
    monkeypatch.setattr(runner, "_redis", lambda _: redis)
    at = datetime(2026, 11, 20, 9, 46, tzinfo=UTC)
    capture = Mock(side_effect=[{"status": state, "written": 1, "trade_date": str(at.date())}
                                for state in ("partial", "ok")])
    monkeypatch.setattr(angel_prices, "refresh_angel_prices", capture)
    assert runner.run_capture(at)["status"] == "partial"
    assert runner.run_capture(at)["status"] == "ok"
    assert runner.run_capture(at)["status"] == "ok"
    assert capture.call_count == 2
    assert redis.incr.call_count == 3
    with auth_database.connect() as conn:
        assert conn.scalar(text("SELECT COUNT(*) FROM run_log WHERE job='angel_market' AND status='ok'")) == 1


def test_primary_membership_refresh_preserves_known_fo_identity(auth_database, monkeypatch):
    nse = Mock(spec=["nifty500", "fo_stocks", "close"])
    nse.nifty500.return_value = {"NEW": {"isin": "INE000000001", "name": "New", "industry": "Metals & Mining"}}
    nse.fo_stocks.return_value = {"FOSTOCK": "Futures member"}
    monkeypatch.setattr(daily, "NSEClient", lambda: nse)
    with auth_database.begin() as conn:
        conn.execute(text("INSERT INTO symbology(ticker, isin) VALUES ('FOSTOCK', 'INE000000002')"))
        daily.refresh_primary_reference(conn)
        assert conn.scalar(text("SELECT isin FROM symbology WHERE ticker='FOSTOCK'")) == "INE000000002"
        assert set(conn.execute(text("SELECT ticker, index_code FROM index_membership"))) == {
            ("NEW", "NIFTY500"), ("FOSTOCK", "NSE_FO")}
        assert conn.scalar(text("SELECT COUNT(*) FROM prices_daily")) == 0

