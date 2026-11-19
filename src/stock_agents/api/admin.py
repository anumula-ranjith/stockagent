"""Authenticated operations portal API. Every endpoint requires an administrator."""
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from sqlalchemy import func, select, text, update
from starlette.concurrency import run_in_threadpool

from stock_agents.api.auth import AdminUser, Session, audit
from stock_agents.common.config import load_settings
from stock_agents.common.snapshot_cache import SnapshotCache
from stock_agents.jobs.pipeline_models import PipelineRun, PipelineSchedule
from stock_agents.jobs.pipeline_stages import coverage
from stock_agents.jobs.pipelines import (
    ACTIVE,
    PIPELINES,
    TZ,
    PipelineBusy,
    dispatch_pending,
    blocking_runs,
    latest_session,
    submit,
)
from stock_agents.jobs.queue import _redis, redis_url
from stock_agents.storage.postgres import AuditLog, Base, User

router = APIRouter(prefix="/admin", tags=["admin"])
quality_cache = SnapshotCache(ttl=30, max_age=60, capacity=4)


class AngelCodeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: SecretStr = Field(min_length=6, max_length=6)


@router.get("/angel-one")
async def angel_status(user: AdminUser):
    from stock_agents.sources.angel_session import connection_status
    return await run_in_threadpool(connection_status)


class CaptureCoverage(BaseModel):
    members: int | None = None
    priced: int | None = None
    missing: list[str] | None = None


class ScheduledPriceRun(CaptureCoverage):
    trade_date: date
    finished_at: datetime
    status: Literal["ok", "partial", "failed"]
    stocks_updated: int | None


class ScheduledPriceHistory(BaseModel):
    runs: list[ScheduledPriceRun]
    next_before: date | None


@router.get("/angel-one/scheduled-runs", response_model=ScheduledPriceHistory)
async def scheduled_price_history(user: AdminUser, session: Session, before: date | None = None):
    log = Base.metadata.tables["run_log"].c
    query = select(log.run_id, log.ended_at, log.status, log.rows_written, log.warnings).where(
        log.job == "angel_market", log.run_id.like("angel-market-%"),
        log.ended_at.is_not(None), log.status.in_(("ok", "partial", "failed")),
    )
    # The scheduler keys one final outcome per trading day by its ISO date.
    if before:
        query = query.where(log.run_id < f"angel-market-{before.isoformat()}")
    rows = (await session.execute(query.order_by(log.run_id.desc()).limit(11))).all()
    runs = []
    for row in rows[:10]:
        try:
            coverage = CaptureCoverage.model_validate_json(row.warnings or "{}")
        except ValidationError:
            coverage = CaptureCoverage()  # Older log entries may contain plain-text warnings.
        runs.append(ScheduledPriceRun(
            trade_date=date.fromisoformat(row.run_id.removeprefix("angel-market-")),
            finished_at=row.ended_at.replace(tzinfo=UTC), status=row.status,
            stocks_updated=row.rows_written,
            **coverage.model_dump(),
        ))
    return ScheduledPriceHistory(runs=runs, next_before=runs[-1].trade_date if len(rows) > 10 else None)


@router.post("/angel-one/connect")
async def angel_connect(body: AngelCodeInput, request: Request, user: AdminUser, session: Session):
    from stock_agents.sources.angel_one import AngelOneError
    from stock_agents.sources.angel_session import connect_code
    code = body.code.get_secret_value()
    if not code.isascii() or not code.isdigit():
        raise HTTPException(422,"Enter the current six-digit authenticator code")
    try:
        result = await run_in_threadpool(connect_code, code)
    except AngelOneError as exc:
        raise HTTPException(502,str(exc)) from None
    audit(session,request,user.id,"angel.connect",{})
    await session.commit()
    return result


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pipeline: Literal["daily", "prices", "reference", "providers", "news", "scores", "validate"]
    trade_date: date | None = None
    idempotency_key: UUID


class ScheduleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class RoleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_admin: bool


class RetryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: UUID


def service_status():
    configured = load_settings()
    try:
        redis = _redis(redis_url())
        redis.ping()
        control = redis.get("quantora:control-heartbeat")
        worker = redis.get("quantora:pipeline-worker-heartbeat")
        return {"broker": True, "scheduler": bool(control), "worker": bool(worker),
                "scheduler_seen": control.decode() if control else None,
                "worker_seen": worker.decode() if worker else None,
                "eodhd_configured": bool(configured.env("EODHD_API_KEY")),
                "timezone": "Asia/Kolkata"}
    except Exception:
        return {"broker": False, "scheduler": False, "worker": False, "timezone": "Asia/Kolkata",
                "eodhd_configured": bool(configured.env("EODHD_API_KEY"))}


@router.get("/overview")
async def overview(user: AdminUser, session: Session):
    last = await session.scalar(select(PipelineRun).order_by(PipelineRun.created_at.desc()).limit(1))
    active = await session.scalar(select(func.count()).select_from(PipelineRun).where(blocking_runs()))
    return {"latest_session": latest_session(), "active_runs": active,
            "services": await run_in_threadpool(service_status),
            "latest_run": row_out(last) if last else None,
            "pipelines": {k: list(v) for k, v in PIPELINES.items()},
            "cache_note": "Market snapshots refresh in the background; open browser data may remain cached for up to five minutes."}


def row_out(row):
    return {column.name: getattr(row, column.name) for column in PipelineRun.__table__.columns}


@router.get("/runs")
async def runs(user: AdminUser, session: Session, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100),
               status: Literal["queued", "running", "retrying", "success", "partial", "failed", "cancelled"] | None = None):
    query = select(PipelineRun)
    count = select(func.count()).select_from(PipelineRun)
    if status:
        query = query.where(PipelineRun.status == status)
        count = count.where(PipelineRun.status == status)
    values = (await session.scalars(query.order_by(PipelineRun.created_at.desc(), PipelineRun.id).offset(offset).limit(limit))).all()
    return {"total": await session.scalar(count), "items": [row_out(row) for row in values]}


@router.get("/runs/{run_id}")
async def run_detail(run_id: UUID, user: AdminUser, session: Session):
    row = await session.get(PipelineRun, str(run_id))
    if not row:
        raise HTTPException(404, "Pipeline run not found")
    return row_out(row)


@router.post("/runs", status_code=202)
async def run_pipeline(body: RunInput, request: Request, user: AdminUser, session: Session):
    try:
        result = await run_in_threadpool(submit, body.pipeline, body.trade_date or latest_session(),
                                        f"manual:{user.id}:{body.idempotency_key}", user_id=user.id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except PipelineBusy as exc:
        raise HTTPException(409, str(exc)) from None
    audit(session, request, user.id, "pipeline.submit", {"run_id": result["id"], "pipeline": body.pipeline})
    await session.commit()
    await run_in_threadpool(dispatch_pending)
    return jsonable_encoder(result)


@router.post("/runs/{run_id}/cancel")
async def cancel(run_id: UUID, request: Request, user: AdminUser, session: Session):
    row = await session.scalar(select(PipelineRun).where(PipelineRun.id == str(run_id)).with_for_update())
    if not row:
        raise HTTPException(404, "Pipeline run not found")
    if row.status not in ACTIVE:
        raise HTTPException(409, "Only active runs can be cancelled")
    row.cancel_requested = True
    if row.status in ("queued", "retrying"):
        row.status, row.finished_at = "cancelled", datetime.now(UTC)
    audit(session, request, user.id, "pipeline.cancel", {"run_id": str(run_id)})
    await session.commit()
    return {"status": "cancellation_requested", "note": "Running stages finish safely; committed data is retained."}


@router.post("/runs/{run_id}/retry", status_code=202)
async def retry(run_id: UUID, body: RetryInput, request: Request, user: AdminUser, session: Session):
    row = await session.get(PipelineRun, str(run_id))
    if not row:
        raise HTTPException(404, "Pipeline run not found")
    if row.status not in ("failed", "partial", "cancelled"):
        raise HTTPException(409, "Only failed, partial or cancelled runs can be retried")
    try:
        result = await run_in_threadpool(submit, row.pipeline, row.trade_date, f"retry:{run_id}:{body.idempotency_key}",
                                        user_id=user.id, parent_id=str(run_id), trigger="retry")
    except (ValueError, PipelineBusy) as exc:
        raise HTTPException(409, str(exc)) from None
    audit(session, request, user.id, "pipeline.retry", {"parent_id": str(run_id), "run_id": result["id"]})
    await session.commit()
    await run_in_threadpool(dispatch_pending)
    return jsonable_encoder(result)


@router.get("/schedules")
async def schedules(user: AdminUser, session: Session):
    now = datetime.now(TZ)
    result = []
    for row in (await session.scalars(select(PipelineSchedule).order_by(PipelineSchedule.hour))).all():
        due = now.replace(hour=row.hour, minute=row.minute, second=0, microsecond=0)
        if due <= now:
            due += timedelta(days=1)
        result.append({"id": row.id, "label": row.label, "hour": row.hour, "minute": row.minute,
                       "enabled": row.enabled, "timezone": "Asia/Kolkata", "next_run": due if row.enabled else None})
    return result


@router.patch("/schedules/{schedule_id}")
async def set_schedule(schedule_id: Literal["morning", "evening"], body: ScheduleInput,
                       request: Request, user: AdminUser, session: Session):
    await session.execute(update(PipelineSchedule).where(PipelineSchedule.id == schedule_id).values(enabled=body.enabled))
    audit(session, request, user.id, "schedule." + schedule_id, body.model_dump())
    await session.commit()
    return {"enabled": body.enabled}


@router.get("/quality")
async def quality(user: AdminUser):
    day = latest_session()
    return await run_in_threadpool(quality_cache.get, day, lambda: coverage(day))


@router.get("/users")
async def users(user: AdminUser, session: Session, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    rows = (await session.execute(select(User.id, User.email, User.is_admin, User.email_verified, User.created_at)
                                  .order_by(User.created_at, User.id).offset(offset).limit(limit))).mappings().all()
    return {"total": await session.scalar(select(func.count()).select_from(User)), "items": [dict(row) for row in rows]}


@router.patch("/users/{user_id}/role")
async def role(user_id: UUID, body: RoleInput, request: Request, user: AdminUser, session: Session):
    await session.execute(text("SELECT pg_advisory_xact_lock(490122882)"))
    target = await session.get(User, str(user_id))
    if not target:
        raise HTTPException(404, "Account not found")
    if target.is_admin and not body.is_admin:
        admins = await session.scalar(select(func.count()).select_from(User).where(User.is_admin.is_(True)))
        if admins <= 1:
            raise HTTPException(409, "The final administrator cannot be demoted")
    target.is_admin = body.is_admin
    audit(session, request, user.id, "user.role", {"user_id": str(user_id), "is_admin": body.is_admin})
    await session.commit()
    return {"id": str(user_id), "is_admin": body.is_admin}


@router.get("/audit")
async def audit_history(user: AdminUser, session: Session, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    rows = (await session.execute(select(AuditLog.id, AuditLog.user_id, AuditLog.action, AuditLog.occurred_at)
                                  .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc()).offset(offset).limit(limit))).mappings().all()
    return {"items": [dict(row) for row in rows], "total": await session.scalar(select(func.count()).select_from(AuditLog))}
