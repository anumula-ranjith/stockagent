import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from stock_agents.api import admin, auth
from stock_agents.jobs import pipeline_stages, pipelines
from stock_agents.jobs.pipeline_models import PipelineRun
from stock_agents.storage.postgres import Base, User, dispose_engine


@asynccontextmanager
async def admin_test_lifespan(app):
    try:
        yield
    finally:
        await dispose_engine()


def test_scheduled_price_history_reports_outcomes_and_paginates(auth_database):
    app = FastAPI(lifespan=admin_test_lifespan)
    app.include_router(admin.router)
    user = auth.UserOut(id=str(uuid4()), email="admin@test.example", is_admin=True, email_verified=True)
    app.dependency_overrides[auth.get_current_user] = lambda: user
    path = "/admin/angel-one/scheduled-runs"
    with TestClient(app) as client:
        assert client.get(path).json() == {"runs": [], "next_before": None}
        rows = []
        for i in range(11):
            ended = datetime(2026, 11, 2, 9, 47, 12) + timedelta(days=i)
            rows.append(dict(run_id=f"angel-market-{ended.date()}", job="angel_market",
                             started_at=ended - timedelta(minutes=1), ended_at=ended,
                             status=("ok", "partial", "failed")[i % 3], rows_written=None, warnings=None))
        # A retry writes one additional ticker; earlier captures already covered the others.
        rows[-1].update(rows_written=1, warnings=json.dumps({"members": 501, "priced": 499,
                                                           "missing": ["INFY", "SBIN"]}))
        rows[-2].update(rows_written=0, warnings=json.dumps({"members": 501, "priced": 501, "missing": []}))
        rows[-3].update(rows_written=0, warnings="legacy warning")
        rows.append({**rows[-1], "run_id": "angel-manual-2026-11-12"})
        rows.append({**rows[-1], "job": "angel_eod", "run_id": "angel-eod-2026-11-12"})
        with auth_database.begin() as conn:
            conn.execute(Base.metadata.tables["run_log"].insert(), rows)
        first = client.get(path).json()
        assert len(first["runs"]) == 10
        assert first["runs"][0] == {"trade_date": "2026-11-12", "finished_at": "2026-11-12T09:47:12Z",
                                    "status": "partial", "stocks_updated": 1, "priced": 499, "members": 501,
                                    "missing": ["INFY", "SBIN"]}
        assert first["runs"][1]["stocks_updated"] == 0 and first["runs"][1]["missing"] == []
        assert first["runs"][2]["stocks_updated"] == 0 and first["runs"][2]["missing"] is None
        assert {row["status"] for row in first["runs"]} == {"ok", "partial", "failed"}
        last = client.get(path, params={"before": first["next_before"]}).json()
        assert [row["trade_date"] for row in last["runs"]] == ["2026-11-02"]
        assert last["next_before"] is None
        user.is_admin = False
        assert client.get(path).status_code == 403


def test_durable_lifecycle(auth_database, monkeypatch):
    day = pipelines.latest_session()
    first = pipelines.submit("validate", day, "same")
    assert pipelines.submit("validate", day, "same")["id"] == first["id"]
    with pytest.raises(pipelines.PipelineBusy):
        pipelines.submit("validate", day, "other")
    with pytest.raises(ValueError):
        pipelines.submit("prices", day, "same")
    calls = []
    monkeypatch.setattr(pipeline_stages, "run_stage", lambda name, day: calls.append(name) or {"status": "ok"})
    pipelines.execute(first["id"])
    pipelines.execute(first["id"])
    assert calls == ["preflight", "validate"]
    with auth_database.connect() as conn:
        assert conn.scalar(select(PipelineRun.status)) == "success"
    second = pipelines.submit("validate", day, "cancel")
    pipelines.set_run(second["id"], cancel_requested=True)
    pipelines.execute(second["id"])
    with auth_database.connect() as conn:
        assert conn.scalar(select(PipelineRun.status).where(PipelineRun.id == second["id"])) == "cancelled"


def test_retries_resume_and_stop(auth_database, monkeypatch):
    run = pipelines.submit("validate", pipelines.latest_session(), "retry")
    calls = []
    def stage(name, day):
        calls.append(name)
        if name == "validate":
            raise RuntimeError("credential must not appear")
        return {"status": "ok"}
    monkeypatch.setattr(pipeline_stages, "run_stage", stage)
    for _ in range(3):
        pipelines.set_run(run["id"], next_attempt_at=None)
        pipelines.execute(run["id"])
    with auth_database.connect() as conn:
        row = conn.execute(select(PipelineRun.__table__)).mappings().one()
        assert row["status"] == "failed"
        assert row["attempt"] == 3
        assert "credential" not in str(row["stages"])
    assert calls.count("preflight") == 1


def test_duplicate_delivery_respects_backoff(auth_database, monkeypatch):
    run = pipelines.submit("validate", pipelines.latest_session(), "backoff")
    def unavailable(name, day):
        raise RuntimeError("not ready")
    monkeypatch.setattr(pipeline_stages, "run_stage", unavailable)
    pipelines.execute(run["id"])
    pipelines.execute(run["id"])
    with auth_database.connect() as conn:
        assert conn.scalar(select(PipelineRun.attempt)) == 1


def test_optional_failure_summary_is_partial():
    assert pipeline_stages.summary({"written": 4, "failures": [{"error":"upstream"}]})["status"] == "partial"


def test_partial_and_cooperative_cancel(auth_database, monkeypatch):
    run = pipelines.submit("news", pipelines.latest_session(), "partial")
    monkeypatch.setattr(pipeline_stages, "run_stage", lambda name, day: {"status": "partial" if name == "news" else "ok"})
    pipelines.execute(run["id"])
    with auth_database.connect() as conn:
        assert conn.scalar(select(PipelineRun.status).where(PipelineRun.id == run["id"])) == "partial"
    run = pipelines.submit("validate", pipelines.latest_session(), "cancel-during-stage")
    calls = []
    def cancel_during(name, day):
        calls.append(name)
        pipelines.set_run(run["id"], cancel_requested=True)
        return {"status": "ok"}
    monkeypatch.setattr(pipeline_stages, "run_stage", cancel_during)
    pipelines.execute(run["id"])
    assert calls == ["preflight"]
    with auth_database.connect() as conn:
        assert conn.scalar(select(PipelineRun.status).where(PipelineRun.id == run["id"])) == "cancelled"


def test_news_partial_response_is_reported(monkeypatch):
    from stock_agents.ingest import news
    class Warehouse:
        def execute(self, *args):
            return []
    class Source:
        def news(self, symbol, **kwargs):
            if symbol == "FAIL":
                raise TimeoutError()
            return []
    monkeypatch.setattr(news, "_tickers", lambda conn: [("A","OK"),("B","FAIL")])
    result = news.ingest_news(Warehouse(), Source(), report=True)
    assert result["status"] == "partial" and result["failures_count"] == 1


@pytest.mark.parametrize("fails", [False, True])
def test_cancel_during_final_stage_wins_over_completion_or_retry(auth_database, monkeypatch, fails):
    run = pipelines.submit("validate", pipelines.latest_session(), "cancel-final")
    def finish_stage(name, day):
        if name == "validate":
            pipelines.set_run(run["id"], cancel_requested=True)
            if fails:
                raise RuntimeError("source failed after cancellation")
        return {"status": "ok"}
    monkeypatch.setattr(pipeline_stages, "run_stage", finish_stage)
    pipelines.execute(run["id"])
    with auth_database.connect() as conn:
        row = conn.execute(select(PipelineRun.__table__)).mappings().one()
        assert row["status"] == "cancelled"
        assert row["finished_at"] is not None
        assert row["next_attempt_at"] is None
    pipelines.execute(run["id"])
    with auth_database.connect() as conn:
        assert conn.scalar(select(PipelineRun.attempt)) == 1


def test_broker_failure_keeps_request(auth_database, monkeypatch):
    from stock_agents.jobs.celery_app import execute_pipeline
    run = pipelines.submit("validate", pipelines.latest_session(), "broker")
    def fail(**kwargs):
        raise ConnectionError("secret")
    monkeypatch.setattr(execute_pipeline, "apply_async", fail)
    pipelines.dispatch_pending()
    with auth_database.connect() as conn:
        row = conn.execute(select(PipelineRun.__table__)).mappings().one()
        assert row["id"] == run["id"] and row["status"] == "queued"
        assert row["dispatched_at"] is None and "secret" not in row["error"]


def test_admin_api_permissions_validation_and_controls(auth_database, monkeypatch):
    app = FastAPI(lifespan=admin_test_lifespan)
    app.include_router(admin.router)
    with TestClient(app) as client:
        assert client.get("/admin/overview").status_code == 401
    uid = str(uuid4())
    with auth_database.begin() as conn:
        conn.execute(User.__table__.insert().values(id=uid, email="admin@test.example", is_admin=True))
    user = auth.UserOut(id=uid, email="admin@test.example", is_admin=True, email_verified=True)
    app.dependency_overrides[auth.get_current_user] = lambda: user
    monkeypatch.setattr(admin, "dispatch_pending", lambda: None)
    with TestClient(app) as client:
        for path in ("overview", "runs", "schedules", "users", "audit"):
            assert client.get("/admin/"+path).status_code == 200
        assert client.patch(f"/admin/users/{uid}/role", json={"is_admin": False}).status_code == 409
        bad = {"pipeline":"validate", "trade_date": str(pipelines.latest_session()+timedelta(days=2)), "idempotency_key":str(uuid4())}
        assert client.post("/admin/runs", json=bad).status_code == 422
        response = client.post("/admin/runs", json={"pipeline":"validate", "idempotency_key":str(uuid4())})
        assert response.status_code == 202, response.text
        rid = response.json()["id"]
        assert client.post(f"/admin/runs/{rid}/cancel").status_code == 200
        assert client.get(f"/admin/runs/{rid}").json()["status"] == "cancelled"
        retry_body = {"idempotency_key":str(uuid4())}
        retried = client.post(f"/admin/runs/{rid}/retry", json=retry_body)
        assert retried.status_code == 202
        pipelines.set_run(retried.json()["id"], status="success")
        assert client.post(f"/admin/runs/{rid}/retry", json=retry_body).json()["id"] == retried.json()["id"]
        assert client.patch("/admin/schedules/morning", json={"enabled":False}).status_code == 200
        assert client.get("/admin/schedules").json()[0]["enabled"] is False
        assert client.get("/admin/audit").json()["total"] >= 4
        user.is_admin = False
        assert client.get("/admin/users").status_code == 403
        assert client.post("/admin/runs", json=bad).status_code == 403
