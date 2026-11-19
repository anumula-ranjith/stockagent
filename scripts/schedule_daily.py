"""Schedule NSE market data and deliver PostgreSQL jobs to Redis."""

import logging
from datetime import date, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

import pandas_market_calendars as calendars
import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from opentelemetry.trace import SpanKind
from redis.exceptions import RedisError
from sqlalchemy.dialects.postgresql import insert

from stock_agents.common import config
from stock_agents.common.logging import configure
from stock_agents.common.telemetry import setup_tracing, trace_headers, tracer
from stock_agents.ingest.price_provider import price_provider
from stock_agents.ingest.screen_indices import refresh_screen_indices
from stock_agents.jobs.queue import dispatch, reconcile_jobs, sync_engine
from stock_agents.storage.postgres import JobRun

MARKET_TZ = ZoneInfo("Asia/Kolkata")
SCHEDULE = (
    ("ingest", 18, 30),
    ("news", 19, 0),
    ("sentiment", 19, 0),
    ("recompute", 19, 30),
)
log = structlog.get_logger(__name__)


def refresh_due_eod() -> None:
    from scripts.refresh_eod import due_date, run_refresh

    run_refresh(due_date(datetime.now(MARKET_TZ)), due=True)


def refresh_due_provider_inputs() -> None:
    from scripts.derive_peg import derive_peg
    from stock_agents.ingest.provider_inputs import refresh_provider_inputs

    result = refresh_provider_inputs(due=True)
    if result.get("date"):
        derive_peg(date.fromisoformat(result["date"]))
    if result["status"] == "partial":
        log.warning("provider.inputs.partial", date=result["date"])


def refresh_due_short_selling() -> None:
    from stock_agents.ingest.nse_short_selling import refresh_short_selling

    today = datetime.now(MARKET_TZ).date()
    result = refresh_short_selling(today - timedelta(days=3), today)
    if result["errors"] or result.get("unmatched_volume"):
        log.warning("nse.short_selling.partial", **result)


def enqueue_daily(kind: str, run_date: date | None = None) -> str | None:
    run_date = run_date or datetime.now(MARKET_TZ).date()
    calendar = calendars.get_calendar(config.load_settings().market_calendar)
    if kind != "ingest" and calendar.valid_days(run_date, run_date).empty:
        return None
    payload = {"trade_date": str(run_date)} if kind == "ingest" else {}
    if kind == "recompute":
        payload = {"asof": str(run_date)}
    job_id = str(uuid5(NAMESPACE_URL, f"stock-agents/nse-eod/{run_date}/{kind}"))
    with structlog.contextvars.bound_contextvars(request_id=job_id, job_id=job_id):
        with tracer().start_as_current_span(
            f"scheduler {kind}", kind=SpanKind.PRODUCER, record_exception=False,
            set_status_on_exception=False, attributes={"stock_agents.request_id": job_id},
        ):
            _submit_daily(job_id, kind, run_date, payload)
    return job_id


def _submit_daily(job_id: str, kind: str, run_date: date, payload: dict) -> None:
    context = trace_headers()
    table = JobRun.__table__
    with sync_engine().begin() as conn:
        submitted = conn.scalar(
            insert(table)
            .values(
                id=job_id, job_type=kind, status="queued", payload=payload,
                request_id=job_id, trace_context=context,
            )
            .on_conflict_do_nothing(index_elements=[table.c.id])
            .returning(table.c.id)
        )
    if submitted:
        log.info("job.scheduled", job_type=kind, trading_date=str(run_date))
        try:
            dispatch(job_id, kind, request_id=job_id, trace_context=context)
        except RedisError:
            log.warning("job.awaiting_delivery", job_type=kind)


def build_scheduler(*, market_jobs: bool = True) -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone=MARKET_TZ)
    scheduler.add_job(
        reconcile_jobs,
        "interval",
        seconds=3,
        id="job-outbox",
        next_run_time=datetime.now(MARKET_TZ),
        coalesce=True,
        max_instances=1,
    )
    if not market_jobs:
        return scheduler
    scheduler.add_job(refresh_screen_indices, "interval", hours=12, id="nifty-screen-indices",
                      next_run_time=datetime.now(MARKET_TZ), coalesce=True, max_instances=1)
    legacy_prices = price_provider() == "eodhd"
    if legacy_prices:
        scheduler.add_job(
            refresh_due_eod, "interval", minutes=15, id="eod-catchup",
            next_run_time=datetime.now(MARKET_TZ), coalesce=True, max_instances=1,
        )
    scheduler.add_job(
        refresh_due_provider_inputs, "interval", minutes=15, id="nifty-provider-inputs",
        next_run_time=datetime.now(MARKET_TZ), coalesce=True, max_instances=1,
    )
    scheduler.add_job(
        refresh_due_short_selling, "cron", hour=19, minute=10, id="nse-short-selling",
        coalesce=True, max_instances=1, misfire_grace_time=3600,
    )
    for kind, hour, minute in SCHEDULE:
        if kind == "ingest" and not legacy_prices:
            continue
        scheduler.add_job(
            refresh_due_eod if kind == "ingest" else enqueue_daily,
            "cron",
            hour=hour,
            minute=minute,
            day_of_week="*" if kind == "ingest" else "mon-fri",
            id=kind,
            args=() if kind == "ingest" else (kind,),
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
    return scheduler


if __name__ == "__main__":
    configure(service="stock-agents.scheduler")
    setup_tracing("stock-agents.scheduler")
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)
    market_jobs = config.load_settings().env("SCHEDULER_RUN_MARKET_JOBS", "true") != "false"
    build_scheduler(market_jobs=market_jobs).start()
