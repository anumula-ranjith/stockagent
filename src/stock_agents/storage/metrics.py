"""Durable worker telemetry, shared by the worker, scheduler, and API."""

from typing import cast

from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from stock_agents.storage.postgres import JobMetric

JOB_TYPES = {"backtest", "ingest", "news", "sentiment", "recompute"}


def record_job_result(conn: Connection, job_type: str, outcome: str, seconds: float) -> None:
    table = cast(Table, JobMetric.__table__)
    statement = insert(table).values(
        job_type=job_type if job_type in JOB_TYPES else "other",
        outcome=outcome,
        executions=1,
        duration_seconds=max(seconds, 0),
    )
    conn.execute(
        statement.on_conflict_do_update(
            index_elements=[table.c.job_type, table.c.outcome],
            set_={
                "executions": table.c.executions + 1,
                "duration_seconds": table.c.duration_seconds + statement.excluded.duration_seconds,
            },
        )
    )
