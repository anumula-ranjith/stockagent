"""Health and Prometheus endpoints for the API and its dependencies."""

import asyncio
from collections.abc import Awaitable
from datetime import date, timedelta
from hmac import compare_digest
from typing import Any

import requests
import structlog
from fastapi import APIRouter, Header, HTTPException, Response
from opentelemetry.trace import SpanKind, StatusCode
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, CollectorRegistry, generate_latest
from prometheus_client.core import CounterMetricFamily, SummaryMetricFamily
from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from sqlalchemy import select, text
from starlette.concurrency import run_in_threadpool

from stock_agents.api.auth import AdminUser
from stock_agents.api.schemas import HealthOut
from stock_agents.common import config
from stock_agents.common.telemetry import dependency_ready, tracer
from stock_agents.jobs.queue import redis_url
from stock_agents.sources.eodhd import EODHDClient
from stock_agents.storage import s3
from stock_agents.storage.postgres import JobMetric, session_factory

router = APIRouter()
log = structlog.get_logger(__name__)
FACTSET_FORMULA = "https://api.factset.com/formula-api/v1/time-series"


async def postgres_check() -> None:
    async with session_factory()() as session:
        await session.execute(text("SELECT 1"))


async def warehouse_counts() -> dict[str, int]:
    async with session_factory()() as session:
        result = await session.execute(text(
            """SELECT (SELECT COUNT(*) FROM symbology WHERE active = TRUE),
                      COUNT(*), COUNT(DISTINCT ticker) FROM prices_daily"""
        ))
        tickers, rows, priced = result.one()
    return {"tickers": tickers, "price_rows": rows, "tickers_with_prices": priced}


async def redis_check() -> None:
    def ping() -> None:
        with Redis.from_url(
            redis_url(), socket_connect_timeout=2, socket_timeout=2, retry=Retry(NoBackoff(), 0)
        ) as client:
            if not client.ping():
                raise RuntimeError("Ping was not acknowledged")
    await run_in_threadpool(ping)


async def s3_check() -> None:
    await run_in_threadpool(s3.head_bucket)


async def eodhd_check() -> str:
    key = config.load_settings().env("EODHD_API_KEY")
    if not key:
        return "unconfigured"
    end = date.today()
    client = EODHDClient(key, timeout=3, max_retries=1, backoff_s=0)
    rows = await run_in_threadpool(client.eod, "RELIANCE.NSE", end - timedelta(days=7), end)
    return "ok" if isinstance(rows, list) and rows else "unavailable"


async def factset_check() -> str:
    settings = config.load_settings()
    username = settings.env("FACTSET_USERNAME_SERIAL")
    key = settings.env("FACTSET_API_KEY")
    if not username or not key:
        return "unconfigured"
    end = date.today()
    probe = {
        "ids": "RELIANCE-IN", "formulas": "P_PRICE", "frequency": "D", "batch": "Y",
        "currency": "INR", "startDate": (end - timedelta(days=7)).isoformat(),
        "endDate": end.isoformat(),
    }
    # Use the existing Formula API probe contract. The health response never includes vendor data.
    def check() -> str:
        with requests.get(FACTSET_FORMULA, params=probe, auth=(username, key), timeout=3,
                          allow_redirects=False, stream=True) as response:
            return "ok" if response.status_code in {200, 202} else "unavailable"
    return await run_in_threadpool(check)


async def _check(name: str, operation: Awaitable[str | None]) -> str:
    with tracer().start_as_current_span(f"check {name}", kind=SpanKind.CLIENT,
                                        record_exception=False, set_status_on_exception=False) as span:
        try:
            status = await asyncio.wait_for(operation, timeout=4) or "ok"
        except Exception as exc:
            status = "unavailable"
            log.warning("dependency.check_failed", dependency=name, error_type=type(exc).__name__)
        span.set_attribute("stock_agents.check_result", status)
        if status != "ok":
            span.set_status(StatusCode.ERROR)
        return status


async def readiness() -> dict[str, Any]:
    results = await asyncio.gather(
        _check("postgres", postgres_check()), _check("redis", redis_check()), _check("s3", s3_check()),
    )
    checks = dict(zip(("postgres", "redis", "s3"), results, strict=True))
    for name, status in checks.items():
        dependency_ready.labels(name).set(status == "ok")
    ok = all(status == "ok" for status in checks.values())
    return {"status": "ok" if ok else "degraded", "checks": checks}


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health", response_model=HealthOut, response_model_exclude_unset=True)
async def health(response: Response, include_stats: bool = False) -> dict[str, Any]:
    payload = await readiness()
    if payload["status"] != "ok":
        response.status_code = 503
    if include_stats and payload["checks"]["postgres"] == "ok":
        try:
            payload.update(await asyncio.wait_for(warehouse_counts(), timeout=12))
        except Exception as exc:
            log.warning("warehouse.counts_unavailable", error_type=type(exc).__name__)
    return payload


@router.get("/health/deep", response_model=HealthOut, response_model_exclude_unset=True)
async def deep_health(_admin: AdminUser, response: Response) -> dict[str, Any]:
    baseline, eodhd, factset = await asyncio.gather(
        readiness(), _check("eodhd", eodhd_check()), _check("factset", factset_check()),
    )
    baseline["checks"].update(eodhd=eodhd, factset=factset)
    if any(status != "ok" for status in baseline["checks"].values()):
        baseline["status"] = "degraded"
        response.status_code = 503
    return baseline


class JobMetricsCollector:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def collect(self):
        labels = ["job_type", "outcome"]
        count = CounterMetricFamily("stock_agents_jobs_completed_total", "Completed job attempts", labels=labels)
        duration = SummaryMetricFamily("stock_agents_job_duration_seconds", "Wall time of job attempts", labels=labels)
        for job_type, outcome, executions, seconds in self.rows:
            count.add_metric([job_type, outcome], executions)
            duration.add_metric([job_type, outcome], executions, seconds)
        yield count
        yield duration


async def job_metric_rows() -> list[Any]:
    table = JobMetric.__table__
    async with session_factory()() as session:
        return list((await session.execute(select(table))).all())


@router.get("/metrics", include_in_schema=False)
async def metrics(authorization: str | None = Header(default=None)) -> Response:
    expected = config.load_settings().env("METRICS_BEARER_TOKEN")
    if expected and not compare_digest((authorization or "").encode(), f"Bearer {expected}".encode()):
        raise HTTPException(401, "Metrics token required", headers={"WWW-Authenticate": "Bearer"})
    # Publish process metrics even when the database is unavailable.
    registry = CollectorRegistry()
    try:
        rows = await asyncio.wait_for(job_metric_rows(), timeout=3)
    except Exception as exc:
        rows = []
        log.warning("job.metrics_unavailable", error_type=type(exc).__name__)
    registry.register(JobMetricsCollector(rows))
    return Response(generate_latest(REGISTRY) + generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
