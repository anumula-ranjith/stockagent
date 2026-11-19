"""Durable, idempotent market-pipeline orchestration. Celery carries IDs only."""
import logging
from datetime import UTC, datetime, time, timedelta
from functools import lru_cache
from threading import Event, Thread
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas_market_calendars as calendars
from sqlalchemy import case, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import OperationalError

from stock_agents.common.config import load_settings
from stock_agents.jobs.pipeline_models import PipelineRun, PipelineSchedule
from stock_agents.jobs.queue import sync_engine

TZ = ZoneInfo("Asia/Kolkata")
ACTIVE = ("queued", "running", "retrying")
TERMINAL = ("success", "partial", "failed", "cancelled")
PIPELINE_LOCK = 490122880
SUBMIT_LOCK = 490122881
PIPELINES = {
    "daily": ("preflight", "reference", "eod", "providers", "insider", "short_selling", "news", "sentiment", "validate", "scores", "publish"),
    "prices": ("preflight", "eod", "validate", "scores", "publish"),
    "reference": ("preflight", "reference", "publish"),
    "providers": ("preflight", "providers", "insider", "short_selling", "publish"),
    "news": ("preflight", "news", "sentiment", "publish"),
    "scores": ("preflight", "validate", "scores", "publish"),
    "validate": ("preflight", "validate"),
}
OPTIONAL = {"providers", "insider", "short_selling", "news", "sentiment"}


@lru_cache(maxsize=1)
def market_calendar():
    return calendars.get_calendar(load_settings().market_calendar)


def latest_session(now=None):
    now = (now or datetime.now(UTC)).astimezone(TZ)
    last = now.date() if now.time() >= time(18, 30) else now.date() - timedelta(days=1)
    days = market_calendar().valid_days(last - timedelta(days=31), last)
    if days.empty:
        raise ValueError("No completed trading session found")
    return days[-1].date()


def due_slots(now, schedules):
    local = now.astimezone(TZ)
    slots = []
    for schedule in schedules:
        if not schedule["enabled"]:
            continue
        at = datetime.combine(local.date(), time(schedule["hour"], schedule["minute"]), TZ)
        if at > local:
            at -= timedelta(days=1)
        if local - at < timedelta(days=1):
            slots.append((f"{schedule['id']}:{at.date()}", latest_session(at)))
    return slots


class PipelineBusy(Exception):
    pass


def submit(pipeline, day, key, *, user_id=None, trigger="manual", parent_id=None):
    if pipeline not in PIPELINES:
        raise ValueError("Unsupported pipeline")
    if day > latest_session() or day < latest_session() - timedelta(days=31):
        raise ValueError("Choose a completed trading session within the last 31 days")
    if market_calendar().valid_days(day, day).empty:
        raise ValueError("Choose an NSE trading session")
    table = PipelineRun.__table__
    with sync_engine().begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": SUBMIT_LOCK})
        previous = conn.execute(select(table).where(table.c.dedupe_key == key)).mappings().first()
        if previous:
            if previous["pipeline"] != pipeline or previous["trade_date"] != day:
                raise ValueError("Idempotency key was used with different inputs")
            return dict(previous)
        active = conn.scalar(select(table.c.id).where(table.c.status.in_(ACTIVE)).limit(1))
        if active:
            raise PipelineBusy(f"Pipeline {active} is already active")
        run_id = str(uuid4())
        conn.execute(insert(table).values(id=run_id, pipeline=pipeline, trade_date=day,
            status="queued", trigger=trigger, dedupe_key=key, user_id=user_id,
            parent_id=parent_id, stages=[], attempt=0, cancel_requested=False))
        return dict(conn.execute(select(table).where(table.c.id == run_id)).mappings().one())


def set_run(run_id, **values):
    if values.get("status") in ("success", "partial", "failed", "retrying"):
        # Evaluate at the UPDATE's row lock, so an accepted cancellation cannot
        # be overwritten by completion or failure from an in-flight stage.
        cancelled = PipelineRun.cancel_requested.is_(True)
        values["status"] = case((cancelled, "cancelled"), else_=values["status"])
        values["finished_at"] = case((cancelled, datetime.now(UTC)), else_=values.get("finished_at"))
        next_attempt = values.get("next_attempt_at")
        values["next_attempt_at"] = case((cancelled, None), else_=next_attempt) if next_attempt else None
    with sync_engine().begin() as conn:
        conn.execute(update(PipelineRun).where(PipelineRun.id == run_id).values(**values))


def dispatch_pending():
    from stock_agents.jobs.celery_app import execute_pipeline
    table = PipelineRun.__table__
    now = datetime.now(UTC)
    # A stale delivery is resent. The worker's PostgreSQL lock makes redelivery safe.
    with sync_engine().begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": SUBMIT_LOCK})
        rows = conn.execute(select(table).where(table.c.status.in_(ACTIVE))).mappings().all()
        for row in rows:
            if row["status"] == "running" and row["heartbeat_at"] and now - row["heartbeat_at"] < timedelta(minutes=3):
                continue
            if row["next_attempt_at"] and row["next_attempt_at"] > now:
                continue
            if row["dispatched_at"] and now - row["dispatched_at"] < timedelta(minutes=2):
                continue
            try:
                execute_pipeline.apply_async(args=[row["id"]], task_id=row["id"], queue="quantora-pipelines", retry=False)
            except Exception:
                # Durable row remains queued; safe text only, never broker credentials.
                conn.execute(update(table).where(table.c.id == row["id"]).values(error="Awaiting broker delivery; retrying automatically"))
            else:
                conn.execute(update(table).where(table.c.id == row["id"]).values(dispatched_at=now))


def tick():
    from stock_agents.jobs.queue import _redis, redis_url
    _redis(redis_url()).set("quantora:control-heartbeat", datetime.now(UTC).isoformat(), ex=180)
    dispatch_pending()
    with sync_engine().connect() as conn:
        schedules = conn.execute(select(PipelineSchedule.__table__)).mappings().all()
    for slot, day in due_slots(datetime.now(UTC), schedules):
        try:
            submit("daily", day, "schedule:" + slot, trigger="schedule")
        except PipelineBusy:
            continue
    dispatch_pending()


def _heartbeat(run_id, stopped):
    while not stopped.wait(15):
        try:
            set_run(run_id, heartbeat_at=datetime.now(UTC))
        except Exception:
            pass


def execute(run_id):
    from stock_agents.jobs.pipeline_stages import run_stage
    table = PipelineRun.__table__
    with sync_engine().connect() as lock:
        acquired = lock.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": PIPELINE_LOCK})
        lock.commit()
        if not acquired:
            return
        stopped = Event()
        try:
            row = lock.execute(select(table).where(table.c.id == run_id)).mappings().first()
            lock.commit()
            if not row or row["status"] in TERMINAL:
                return
            if row["cancel_requested"]:
                set_run(run_id, status="cancelled", finished_at=datetime.now(UTC))
                return
            if row["next_attempt_at"] and row["next_attempt_at"] > datetime.now(UTC):
                return
            attempt = row["attempt"] + 1
            if attempt > 3:
                set_run(run_id, status="failed", error="Worker recovery limit reached; retry manually", finished_at=datetime.now(UTC))
                return
            stages = list(row["stages"] or [])
            set_run(run_id, status="running", attempt=attempt, started_at=row["started_at"] or datetime.now(UTC),
                    heartbeat_at=datetime.now(UTC), error=None, next_attempt_at=None)
            heartbeat = Thread(target=_heartbeat, args=(run_id, stopped), daemon=True)
            heartbeat.start()
            for name in PIPELINES[row["pipeline"]]:
                if any(s["name"] == name and s["status"] in ("success", "partial", "skipped") for s in stages):
                    continue
                cancel = lock.scalar(select(table.c.cancel_requested).where(table.c.id == run_id))
                lock.commit()
                if cancel:
                    set_run(run_id, status="cancelled", finished_at=datetime.now(UTC), stages=stages)
                    return
                stages = [s for s in stages if s["name"] != name]
                stage = {"name": name, "status": "running", "started_at": datetime.now(UTC).isoformat(), "attempt": attempt}
                stages.append(stage)
                set_run(run_id, stages=stages)
                try:
                    result = run_stage(name, row["trade_date"])
                    state = result.get("status", "ok")
                    if state in ("busy", "awaiting_exchange", "awaiting_data"):
                        raise RuntimeError("Source data is not ready or another writer is active")
                    stage.update(status="partial" if state in ("partial", "warning") else "skipped" if state == "skipped" else "success", result=result)
                except Exception as exc:
                    logging.getLogger(__name__).error("Pipeline %s stage %s failed: %s sqlstate=%s",
                        run_id, name, type(exc).__name__, getattr(getattr(exc, "orig", None), "pgcode", None))
                    # Vendor payloads and exception messages can contain keys/SQL; expose type only.
                    stage.update(status="partial" if name in OPTIONAL else "failed",
                                 error=f"{type(exc).__name__}: stage did not complete; check service logs and source configuration")
                    if name not in OPTIONAL:
                        retry = attempt < 3 and isinstance(exc, (RuntimeError, TimeoutError, ConnectionError, OperationalError))
                        stage["finished_at"] = datetime.now(UTC).isoformat()
                        set_run(run_id, stages=stages, status="retrying" if retry else "failed",
                                error=stage["error"], next_attempt_at=datetime.now(UTC)+timedelta(minutes=5) if retry else None,
                                finished_at=None if retry else datetime.now(UTC))
                        return
                stage["finished_at"] = datetime.now(UTC).isoformat()
                set_run(run_id, stages=stages, heartbeat_at=datetime.now(UTC))
            status = "partial" if any(s["status"] in ("partial", "skipped") for s in stages) else "success"
            set_run(run_id, status=status, stages=stages, finished_at=datetime.now(UTC))
        finally:
            stopped.set()
            lock.rollback()
            lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": PIPELINE_LOCK})
            lock.commit()
