"""Redis delivery for durable PostgreSQL job rows."""

from datetime import UTC, datetime, timedelta
from functools import lru_cache

from redis import Redis
from rq import Queue
from rq.exceptions import DuplicateJobError, NoSuchJobError
from rq.job import Job, JobStatus
from rq.serializers import JSONSerializer
from sqlalchemy import create_engine, select, update

from stock_agents.common import config
from stock_agents.storage.metrics import record_job_result
from stock_agents.storage.postgres import JobRun, database_url
from stock_agents.storage.tracing import instrument_engine

QUEUE_NAME = "stock-agents"
TIMEOUTS = {
    "backtest": 1800,
    "ingest": 7200,
    "news": 7200,
    "sentiment": 7200,
    "recompute": 1800,
}


def redis_url() -> str:
    return config.load_settings().env("REDIS_URL", "redis://127.0.0.1:6379/0")


@lru_cache(maxsize=4)
def _redis(url: str) -> Redis:
    return Redis.from_url(url, socket_connect_timeout=3)


def rq_queue() -> Queue:
    return Queue(QUEUE_NAME, connection=_redis(redis_url()), serializer=JSONSerializer)


@lru_cache(maxsize=4)
def _sync_engine(url):
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
    instrument_engine(engine)
    return engine


def sync_engine():
    return _sync_engine(database_url("psycopg2"))


def dispatch(
    job_id: str, kind: str, *, request_id: str | None = None, trace_context: dict[str, str] | None = None
) -> None:
    """The unique Redis job ID makes API and scheduler delivery safe to repeat."""
    try:
        rq_queue().enqueue_call(
            "stock_agents.jobs.worker.run_job",
            args=(job_id,),
            job_id=job_id,
            description=kind,
            timeout=TIMEOUTS[kind],
            result_ttl=86400,
            failure_ttl=604800,
            unique=True,
            meta={"request_id": request_id or job_id, "trace_context": trace_context or {}},
        )
    except DuplicateJobError:
        pass


def rq_status(job_id: str) -> JobStatus | None:
    queue = rq_queue()
    try:
        job = Job.fetch(job_id, connection=queue.connection, serializer=JSONSerializer)
        return job.get_status()
    except NoSuchJobError:
        return None


def reconcile_jobs() -> None:
    """Deliver committed jobs and expose failures if an RQ work horse died."""
    table = JobRun.__table__
    with sync_engine().connect() as conn:
        active = conn.execute(
            select(
                table.c.id, table.c.job_type, table.c.status, table.c.started_at,
                table.c.request_id, table.c.trace_context,
            )
            .where(table.c.status.in_(("queued", "started")), table.c.payload.is_not(None))
            .order_by(table.c.enqueued_at, table.c.id)
        ).all()
    now = datetime.now(UTC)
    for row in active:
        state = rq_status(row.id)
        if state is None and row.status == "queued":
            dispatch(row.id, row.job_type, request_id=row.request_id, trace_context=row.trace_context)
            continue
        stale = (
            state is None
            and row.started_at is not None
            and now - row.started_at > timedelta(seconds=TIMEOUTS[row.job_type] + 300)
        )
        terminal = state in {JobStatus.FAILED, JobStatus.STOPPED, JobStatus.CANCELED}
        if stale or terminal:
            with sync_engine().begin() as conn:
                changed = conn.execute(
                    update(table)
                    .where(
                        table.c.id == row.id, table.c.status == row.status,
                        table.c.started_at.is_not_distinct_from(row.started_at),
                    )
                    .values(
                        status="failed",
                        error="Worker stopped before completing the job",
                        finished_at=now,
                    )
                )
                if changed.rowcount:
                    duration = (now - row.started_at).total_seconds() if row.started_at else 0
                    record_job_result(conn, row.job_type, "failure", duration)
