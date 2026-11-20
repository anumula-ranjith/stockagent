from datetime import date, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from scripts.schedule_daily import MARKET_TZ, build_scheduler, enqueue_daily
from stock_agents.api.auth import COOKIE, make_token
from stock_agents.api.main import app
from stock_agents.ingest.news import ingest_news, ingest_sentiment_daily
from stock_agents.jobs.queue import reconcile_jobs
from stock_agents.jobs.worker import WindowsWorker
from stock_agents.storage.postgres import AuditLog, JobRun, User
from stock_agents.storage.schema import connect, init_schema


def test_rq_dashboard_rejects_anonymous_requests():
    with TestClient(app) as client:
        response = client.get("/_admin/rq/")
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


def test_market_schedule_has_the_expected_ist_times(monkeypatch):
    monkeypatch.setenv("MARKET_PRICE_PROVIDER", "eodhd")
    morning = datetime(2025, 2, 3, 8, tzinfo=MARKET_TZ)
    jobs = {job.id: job for job in build_scheduler().get_jobs()}
    expected = {"ingest": (18, 30), "news": (19, 0), "sentiment": (19, 0), "recompute": (19, 30)}
    for name, (hour, minute) in expected.items():
        assert jobs[name].trigger.get_next_fire_time(None, morning) == morning.replace(
            hour=hour, minute=minute
        )


def test_daily_refresh_preserves_when_unchanged_data_became_known():
    initial = date(2025, 2, 3)
    client = SimpleNamespace(
        news=lambda *args, **kwargs: [{"date": "2025-02-03T15:30:00Z", "title": "Headline"}],
        sentiments=lambda symbol: {
            symbol: [{"date": "2025-02-03", "count": 1, "normalized": 0.4}]
        },
    )
    with connect(":memory:") as conn:
        init_schema(conn)
        conn.execute("INSERT INTO symbology (ticker, eodhd_symbol) VALUES ('SAMPLE', 'SAMPLE.NSE')")
        for table, load in (("news", ingest_news), ("sentiment_daily", ingest_sentiment_daily)):
            load(conn, client)
            conn.execute(f"UPDATE {table} SET known_date = ?", [initial])
            load(conn, client)
            assert conn.execute(f"SELECT known_date FROM {table}").fetchall() == [(initial,)]


def test_daily_enqueue_is_idempotent_and_skips_non_trading_days(auth_database, rq_test_queue):
    assert enqueue_daily("news", date(2025, 2, 2)) is None
    first = enqueue_daily("ingest", date(2025, 2, 3))
    assert enqueue_daily("ingest", date(2025, 2, 3)) == first
    reconcile_jobs()
    assert rq_test_queue.job_ids == [first]
    with auth_database.connect() as conn:
        job = conn.execute(select(JobRun.__table__)).one()
        assert job.job_type == "ingest"
        assert job.payload == {"trade_date": "2025-02-03"}
        assert job.user_id is None


def test_outbox_recovers_and_admin_can_retry_a_failed_job(
    auth_database, rq_test_queue, _isolated_paths, monkeypatch
):
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-retrying-phase-three-jobs")
    job_id = str(uuid4())
    admin_id = str(uuid4())
    today = date.today()
    with auth_database.begin() as conn:
        conn.execute(
            User.__table__.insert().values(id=admin_id, email="admin@example.com", is_admin=True)
        )
        conn.execute(
            JobRun.__table__.insert().values(
                id=job_id,
                job_type="backtest",
                user_id=admin_id,
                status="queued",
                payload={"start": str(today), "end": str(today), "n": 3},
            )
        )
    reconcile_jobs()
    reconcile_jobs()
    assert rq_test_queue.job_ids == [job_id]
    worker = WindowsWorker(
        [rq_test_queue], connection=rq_test_queue.connection, serializer=rq_test_queue.serializer
    )
    worker.work(burst=True)
    assert rq_test_queue.failed_job_registry.get_job_ids() == [job_id]

    headers = {"Authorization": "Bearer " + make_token(admin_id).access_token}
    retry = f"/_admin/rq/job/{job_id}/requeue"
    with TestClient(app) as client:
        assert client.get(f"/jobs/{job_id}", headers=headers).json()["status"] == "failed"
        assert client.get("/_admin/rq/requeue/stock-agents", headers=headers).status_code == 405
        assert client.post(retry).status_code == 401
        client.cookies.set(COOKIE, make_token(admin_id).access_token)
        assert client.post(retry).status_code == 403
        assert client.post(
            retry, headers={"X-Requested-With": "XMLHttpRequest", "Origin": "https://other.test"}
        ).status_code == 403
        assert client.post(
            retry, headers={"X-Requested-With": "XMLHttpRequest", "Origin": "http://testserver"}
        ).json()["status"] == "OK"
        assert client.get(f"/jobs/{job_id}", headers=headers).json()["status"] == "queued"
        from stock_agents.storage.warehouse import connect as postgres_connect

        with postgres_connect() as conn:
            conn.execute(
                """INSERT INTO prices_daily (ticker, date, adj_close, source, known_date)
                   VALUES ('SAMPLE', ?, 11.0, 'eodhd', ?)""",
                [today, today],
            )
        worker.work(burst=True)
        assert client.get(f"/jobs/{job_id}", headers=headers).json()["status"] == "finished"
    with auth_database.connect() as conn:
        audit = conn.execute(select(AuditLog.__table__)).one()
        assert audit.action == "/_admin/rq/requeue"
