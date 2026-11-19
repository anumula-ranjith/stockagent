from datetime import UTC, date, datetime

from sqlalchemy import select

from scripts.refresh_eod import due_date
from scripts.schedule_daily import MARKET_TZ, build_scheduler
from stock_agents.storage.postgres import JobMetric, JobRun


def test_due_date_uses_ist_and_catches_up_before_evening():
    assert due_date(datetime(2026, 11, 18, 12, 59, tzinfo=UTC)) == date(2026, 11, 17)
    assert due_date(datetime(2026, 11, 18, 13, 0, tzinfo=UTC)) == date(2026, 11, 18)
    assert due_date(datetime(2026, 11, 19, 0, 0, tzinfo=UTC)) == date(2026, 11, 18)


def test_ingest_checks_for_special_weekend_trading(monkeypatch):
    monkeypatch.setenv("MARKET_PRICE_PROVIDER", "eodhd")
    sunday = datetime(2026, 11, 8, 8, tzinfo=MARKET_TZ)
    job = next(job for job in build_scheduler().get_jobs() if job.id == "ingest")
    assert job.trigger.get_next_fire_time(None, sunday) == sunday.replace(hour=18, minute=30)


def test_completed_refresh_is_skipped_on_timer_retry(auth_database, monkeypatch):
    from scripts import refresh_eod as runner
    from stock_agents.ingest import daily

    calls = []

    def refresh(connection, trade_date):
        calls.append(trade_date)
        return {"status": "ok", "trade_date": str(trade_date), "covered": 500}

    monkeypatch.setattr(runner, "sync_engine", lambda: auth_database)
    monkeypatch.setattr(daily, "refresh_eod", refresh)
    day = date(2026, 11, 18)
    assert runner.run_refresh(day, due=True)["status"] == "ok"
    assert runner.run_refresh(day, due=True)["status"] == "already_current"
    assert calls == [day]
    with auth_database.connect() as connection:
        job = connection.execute(select(JobRun.__table__)).one()
        assert job.status == "finished"
        assert job.result_data["covered"] == 500
        metric = connection.execute(select(JobMetric.__table__)).one()
        assert (metric.job_type, metric.outcome, metric.executions) == ("ingest", "success", 1)


def test_failed_refresh_rolls_back_data_and_records_failure(auth_database, monkeypatch):
    import pytest
    from sqlalchemy import text

    from scripts import refresh_eod as runner
    from stock_agents.ingest import daily

    def refresh(connection, trade_date):
        connection.execute(text("INSERT INTO symbology (ticker) VALUES ('ROLLBACK')"))
        raise ValueError("Invalid source data")

    monkeypatch.setattr(runner, "sync_engine", lambda: auth_database)
    monkeypatch.setattr(daily, "refresh_eod", refresh)
    with pytest.raises(RuntimeError, match="ValueError"):
        runner.run_refresh(date(2026, 11, 18), due=True)
    with auth_database.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM symbology")) == 0
        job = connection.execute(select(JobRun.__table__)).one()
        assert job.status == "failed"
        metric = connection.execute(select(JobMetric.__table__)).one()
        assert (metric.outcome, metric.executions) == ("failure", 1)


def test_missing_exchange_file_is_recorded_for_retry(auth_database, monkeypatch):
    from scripts import refresh_eod as runner
    from stock_agents.ingest import daily

    def refresh(connection, trade_date):
        raise daily.EODNotReady()

    monkeypatch.setattr(runner, "sync_engine", lambda: auth_database)
    monkeypatch.setattr(daily, "refresh_eod", refresh)
    day = date(2026, 11, 18)
    assert runner.run_refresh(day, due=True)["status"] == "awaiting_exchange"
    with auth_database.connect() as connection:
        job = connection.execute(select(JobRun.__table__)).one()
        assert job.result_data["status"] == "awaiting_exchange"
        metric = connection.execute(select(JobMetric.__table__)).one()
        assert (metric.outcome, metric.executions) == ("deferred", 1)
