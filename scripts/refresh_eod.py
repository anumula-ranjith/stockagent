"""Run the PostgreSQL EOD refresh, including durable retries from a local timer."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, time, timedelta
from time import perf_counter
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

import structlog
from opentelemetry.trace import StatusCode
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert

from stock_agents.common.config import load_settings
from stock_agents.common.logging import configure
from stock_agents.common.telemetry import flush_traces, setup_tracing, trace_headers, tracer
from stock_agents.jobs.queue import sync_engine
from stock_agents.storage.metrics import record_job_result
from stock_agents.storage.postgres import JobRun

MARKET_TZ = ZoneInfo("Asia/Kolkata")
WAREHOUSE_LOCK = 490122862
log = structlog.get_logger(__name__)


def due_date(now: datetime) -> date:
    """Before the publication window, retry the previous evening's refresh."""
    local = now.astimezone(MARKET_TZ)
    return local.date() if local.time() >= time(18, 30) else local.date() - timedelta(days=1)


def run_refresh(trade_date: date, *, due: bool = False) -> dict:
    now = datetime.now(UTC)
    # A retry gets its own audit row. Timers sharing a quarter-hour share an ID.
    slot = int(now.timestamp()) // 900 if due else now.isoformat()
    job_id = str(uuid5(NAMESPACE_URL, f"stock-agents/eod/{trade_date}/{slot}"))
    with structlog.contextvars.bound_contextvars(request_id=job_id, job_id=job_id):
        with tracer().start_as_current_span(
            "eod refresh", record_exception=False, set_status_on_exception=False,
            attributes={"stock_agents.request_id": job_id, "stock_agents.job_type": "ingest"},
        ) as span:
            try:
                return _run_refresh(job_id, trade_date, now, due)
            except Exception:
                span.set_status(StatusCode.ERROR)
                raise


def _run_refresh(job_id: str, trade_date: date, now: datetime, due: bool) -> dict:
    from stock_agents.ingest.daily import EODNotReady, refresh_eod

    table = JobRun.__table__
    with sync_engine().connect() as conn:
        locked = conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": WAREHOUSE_LOCK})
        conn.commit()
        if not locked:
            return {"status": "busy", "trade_date": str(trade_date)}
        try:
            if due:
                prior = conn.execute(
                    select(table.c.result_data).where(
                        table.c.job_type == "ingest",
                        table.c.status == "finished",
                        table.c.result_data["trade_date"].astext == str(trade_date),
                        table.c.result_data["status"].astext == "ok",
                    ).limit(1)
                ).first()
                if prior:
                    return {"status": "already_current", "trade_date": str(trade_date)}
            added = conn.scalar(
                insert(table).values(
                    id=job_id, job_type="ingest", status="started", started_at=now,
                    payload={"trade_date": str(trade_date), "scheduled": due},
                    request_id=job_id, trace_context=trace_headers(),
                ).on_conflict_do_nothing(index_elements=[table.c.id]).returning(table.c.id)
            )
            conn.commit()
            if not added:
                return {"status": "already_attempted", "trade_date": str(trade_date)}
            start = perf_counter()
            log.info("job.started", job_type="ingest", trade_date=str(trade_date))
            try:
                result = refresh_eod(conn, trade_date=trade_date)
                conn.execute(update(table).where(table.c.id == job_id).values(
                    status="finished", result_data=result, finished_at=datetime.now(UTC),
                ))
                record_job_result(conn, "ingest", "success", perf_counter() - start)
                conn.commit()
                log.info("job.finished", job_type="ingest")
                return result
            except EODNotReady:
                conn.rollback()
                result = {"status": "awaiting_exchange", "trade_date": str(trade_date)}
                conn.execute(update(table).where(table.c.id == job_id).values(
                    status="finished", result_data=result, finished_at=datetime.now(UTC),
                ))
                record_job_result(conn, "ingest", "deferred", perf_counter() - start)
                conn.commit()
                log.info("job.deferred", job_type="ingest", reason="awaiting_exchange")
                return result
            except Exception as exc:
                conn.rollback()
                conn.execute(update(table).where(table.c.id == job_id).values(
                    status="failed", error=type(exc).__name__, finished_at=datetime.now(UTC),
                ))
                record_job_result(conn, "ingest", "failure", perf_counter() - start)
                conn.commit()
                log.error("job.failed", job_type="ingest", error_type=type(exc).__name__)
                raise RuntimeError(f"EOD refresh failed ({type(exc).__name__})") from None
        finally:
            conn.rollback()
            conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": WAREHOUSE_LOCK})
            conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--due", action="store_true", help="Skip a completed refresh for the due date")
    args = parser.parse_args()
    settings = load_settings()
    configure(service="stock-agents.eod")
    setup_tracing("stock-agents.eod")
    day = args.date or due_date(datetime.now(UTC))
    try:
        result = run_refresh(day, due=args.due)
        code = 0
    except RuntimeError as error:
        result = {"status": "failed", "trade_date": str(day), "error": str(error)}
        code = 1
    finally:
        flush_traces()
    with (settings.paths.log_dir / "daily_eod.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": datetime.now(UTC).isoformat(), **result}, default=str) + "\n")
    print(json.dumps(result, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
