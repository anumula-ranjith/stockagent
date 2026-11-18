from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from stock_agents.api import diagnostics
from stock_agents.api.main import app
from stock_agents.common import telemetry
from stock_agents.common.logging import _safe_record
from stock_agents.storage.tracing import connect_duckdb


def test_request_id_is_returned_and_metrics_use_route_templates():
    with TestClient(app) as client:
        response = client.get("/stocks/PRIVATE-SYMBOL", headers={"X-Request-ID": "test-request"})
        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == "test-request"
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "stock_agents_http_request_duration_seconds_bucket" in metrics.text
        assert 'route="/stocks/{ticker}"' in metrics.text
        assert "PRIVATE-SYMBOL" not in metrics.text


def test_readiness_reports_dependency_failure_while_liveness_responds(monkeypatch):
    async def postgres():
        return None

    async def counts():
        return {"tickers": 2, "price_rows": 4, "tickers_with_prices": 2}

    async def redis():
        raise RuntimeError("Sensitive upstream configuration")

    async def s3():
        return None

    monkeypatch.setattr(diagnostics, "postgres_check", postgres)
    monkeypatch.setattr(diagnostics, "warehouse_counts", counts)
    monkeypatch.setattr(diagnostics, "redis_check", redis)
    monkeypatch.setattr(diagnostics, "s3_check", s3)
    with TestClient(app) as client:
        ready = client.get("/health?include_stats=true")
        assert ready.status_code == 503
        assert ready.json()["checks"] == {"postgres": "ok", "redis": "unavailable", "s3": "ok"}
        assert ready.json()["price_rows"] == 4
        assert "Sensitive" not in ready.text
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/deep").status_code == 401


def test_trace_preserves_remote_parent_and_excludes_sql_and_path_input(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "_provider", provider)
    remote = "00-1234567890abcdef1234567890abcdef-abcdef1234567890-01"
    with TestClient(app) as client:
        assert client.get("/stocks/PRIVATE-SYMBOL", headers={"traceparent": remote}).status_code == 200
    with connect_duckdb(":memory:") as connection:
        connection.execute("SELECT 'SQL-PRIVATE-VALUE'").fetchone()
    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert spans["GET /stocks/{ticker}"].parent.span_id == int("abcdef1234567890", 16)
    assert spans["duckdb SELECT"].attributes["db.system.name"] == "duckdb"
    assert all("PRIVATE" not in str(span.attributes) for span in spans.values())


def test_log_redacts_url_tokens_and_presigned_signatures():
    result = _safe_record(None, "info", {
        "event": "postgresql://user:password@db/data /?api_token=vendor&X-Amz-Signature=signed",
    })
    assert result["event"] == "postgresql://[redacted]@db/data /?api_token=[redacted]&X-Amz-Signature=[redacted]"


def test_metrics_token_when_configured(monkeypatch):
    async def no_job_metrics():
        return []

    monkeypatch.setenv("METRICS_BEARER_TOKEN", "scraper-test-token")
    monkeypatch.setattr(diagnostics, "job_metric_rows", no_job_metrics)
    with TestClient(app) as client:
        assert client.get("/metrics").status_code == 401
        response = client.get("/metrics", headers={"Authorization": "Bearer scraper-test-token"})
        assert response.status_code == 200
        assert "stock_agents_http_request_duration_seconds" in response.text
