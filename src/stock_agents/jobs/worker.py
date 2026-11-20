"""RQ entrypoint and isolated execution of durable application jobs."""

import os
from datetime import UTC, date, datetime
from time import perf_counter
from zoneinfo import ZoneInfo

import structlog
from opentelemetry import propagate
from opentelemetry.trace import Span, SpanKind, StatusCode
from rq import SimpleWorker, Worker, get_current_job
from rq.timeouts import TimerDeathPenalty
from sqlalchemy import select, text, update

from stock_agents.common import config
from stock_agents.common.logging import configure
from stock_agents.common.telemetry import flush_traces, setup_tracing, tracer
from stock_agents.jobs.queue import rq_queue, sync_engine
from stock_agents.storage.metrics import JOB_TYPES, record_job_result
from stock_agents.storage.postgres import JobRun
from stock_agents.storage.warehouse import Warehouse, connect

log = structlog.get_logger(__name__)
MARKET_TZ = ZoneInfo("Asia/Kolkata")
WAREHOUSE_LOCK = 490122862


class WindowsWorker(SimpleWorker):
    death_penalty_class = TimerDeathPenalty


def _backtest(job_id: str, payload: dict, submitted: datetime) -> tuple[dict, str]:
    from stock_agents.engine.backtest import run_backtest
    from stock_agents.storage.s3 import put_backtest

    with connect(read_only=True) as conn:
        if "ranker" in payload:
            from stock_agents.engine.ranker_replay import Replay, replay

            summary = replay(conn, Replay.model_validate(payload["ranker"]))
        else:
            summary = run_backtest(
                conn,
                date.fromisoformat(payload["start"]),
                date.fromisoformat(payload["end"]),
                n_per_side=payload["n"],
                persist=False,
            )
    if "error" in summary:
        raise BacktestInputError(summary["error"])
    return summary, put_backtest(job_id, summary, when=submitted.astimezone(MARKET_TZ).date())


class BacktestInputError(Exception):
    """A client-safe error from the backtest engine."""


def _warehouse_job(kind: str, payload: dict, submitted: datetime, target) -> dict:
    from stock_agents.engine.scores import compute_and_store
    from stock_agents.ingest.news import ingest_news, ingest_sentiment_daily
    from stock_agents.sources.eodhd import EODHDClient

    since = submitted.astimezone(MARKET_TZ).date()
    source = Warehouse(target)
    if kind == "recompute":
        asof = date.fromisoformat(payload["asof"]) if payload.get("asof") else since
        return compute_and_store(source, asof=asof)
    if kind == "ingest":
        from stock_agents.ingest.daily import refresh_eod

        trade_date = date.fromisoformat(payload["trade_date"]) if payload.get("trade_date") else None
        return refresh_eod(target, trade_date=trade_date)
    client = EODHDClient.from_env()
    if kind == "news":
        count = ingest_news(source, client)
    elif kind == "sentiment":
        count = ingest_sentiment_daily(source, client)
    else:
        raise ValueError("Unsupported job type")
    return {"rows": count}


def run_job(job_id: str) -> None:
    """Run one RQ delivery and commit its authoritative PostgreSQL state."""
    setup_tracing("stock-agents.worker")
    current = get_current_job()
    metadata = current.meta if current else {}
    correlation = metadata.get("request_id") or job_id
    parent = propagate.extract(metadata.get("trace_context") or {})
    try:
        with structlog.contextvars.bound_contextvars(request_id=correlation, job_id=job_id):
            with tracer().start_as_current_span(
                "rq job", context=parent, kind=SpanKind.CONSUMER,
                record_exception=False, set_status_on_exception=False,
                attributes={"messaging.system": "rq", "messaging.message.id": job_id,
                            "stock_agents.request_id": correlation},
            ) as span:
                try:
                    _run_job(job_id, span)
                except Exception:
                    span.set_status(StatusCode.ERROR)
                    raise
    finally:
        flush_traces()


def _run_job(job_id: str, span: Span) -> None:
    table = JobRun.__table__
    config.load_settings()
    with sync_engine().connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(:lock)"), {"lock": WAREHOUSE_LOCK})
        conn.commit()
        try:
            job = conn.execute(select(table).where(table.c.id == job_id)).one_or_none()
            if job is None or job.status == "finished":
                return
            kind = job.job_type if job.job_type in JOB_TYPES else "other"
            span.update_name(f"rq {kind}")
            span.set_attribute("stock_agents.job_type", kind)
            start = perf_counter()
            conn.execute(
                update(table)
                .where(table.c.id == job_id)
                .values(
                    status="started",
                    started_at=datetime.now(UTC),
                    finished_at=None,
                    error=None,
                )
            )
            conn.commit()
            log.info("job.started", job_type=kind)

            try:
                result_key = None
                if job.job_type == "backtest":
                    result, result_key = _backtest(job_id, job.payload, job.enqueued_at)
                else:
                    result = _warehouse_job(job.job_type, job.payload, job.enqueued_at, conn)
                conn.execute(
                    update(table)
                    .where(table.c.id == job_id)
                    .values(
                        status="finished",
                        result_data=result,
                        result_key=result_key,
                        finished_at=datetime.now(UTC),
                    )
                )
                duration = perf_counter() - start
                record_job_result(conn, kind, "success", duration)
                conn.commit()
                log.info("job.finished", job_type=kind, duration_ms=round(duration * 1000, 2))
            except Exception as exc:
                conn.rollback()
                message = str(exc) if isinstance(exc, BacktestInputError) else "Job failed"
                conn.execute(
                    update(table)
                    .where(table.c.id == job_id)
                    .values(
                        status="failed",
                        error=message,
                        finished_at=datetime.now(UTC),
                    )
                )
                duration = perf_counter() - start
                record_job_result(conn, kind, "failure", duration)
                conn.commit()
                log.error("job.failed", job_type=kind, error_type=type(exc).__name__,
                          duration_ms=round(duration * 1000, 2))
                raise RuntimeError(message) from None
        finally:
            conn.rollback()
            conn.execute(text("SELECT pg_advisory_unlock(:lock)"), {"lock": WAREHOUSE_LOCK})
            conn.commit()


def main() -> None:
    configure(service="stock-agents.worker")
    queue = rq_queue()
    worker_class = WindowsWorker if os.name == "nt" else Worker
    worker_class([queue], connection=queue.connection, serializer=queue.serializer).work()


if __name__ == "__main__":
    main()
