"""Endpoints for audited administrative jobs and private reports."""

import logging
from datetime import date
from typing import Annotated
from uuid import UUID, uuid4

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException, Query, Request, Response
from redis.exceptions import RedisError
from rq.job import JobStatus
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from stock_agents.api.auth import AdminUser, CurrentUser, Session, admin_rate_key, audit, limiter
from stock_agents.api.schemas import BacktestJobRef, BacktestNotice, BacktestSummary, JobStatusOut
from stock_agents.common.telemetry import trace_headers
from stock_agents.jobs.queue import dispatch, rq_status
from stock_agents.storage import s3
from stock_agents.storage.postgres import JobRun

router = APIRouter()
log = logging.getLogger(__name__)


async def _enqueue(
    request: Request, session: Session, user: AdminUser, kind: str, payload: dict
) -> BacktestJobRef:
    correlation = request.state.request_id
    context = trace_headers()
    job = JobRun(
        id=str(uuid4()), user_id=user.id, job_type=kind, status="queued", payload=payload,
        request_id=correlation, trace_context=context,
    )
    session.add(job)
    audit(session, request, user.id, request.url.path, payload)
    await session.commit()
    try:
        await run_in_threadpool(dispatch, job.id, kind, request_id=correlation, trace_context=context)
    except RedisError:
        log.warning("Job %s committed for delivery by the scheduler", job.id)
    return BacktestJobRef(job_id=job.id, status="queued")


@router.post("/backtest/run", status_code=202, response_model=BacktestJobRef)
@limiter.limit("3/hour", key_func=admin_rate_key)
async def backtest_run(
    request: Request,
    response: Response,
    user: AdminUser,
    session: Session,
    start: date,
    end: date,
    n: Annotated[int, Query(ge=3, le=30)] = 10,
):
    if start > end:
        raise HTTPException(422, "Start date must be on or before end date")
    return await _enqueue(
        request, session, user, "backtest", {"start": str(start), "end": str(end), "n": n}
    )


@router.post("/admin/ingest", status_code=202, response_model=BacktestJobRef)
async def ingest(
    request: Request, user: AdminUser, session: Session, years: int = Query(1, ge=1, le=10)
):
    return await _enqueue(request, session, user, "ingest", {"years": years})


@router.post("/admin/recompute", status_code=202, response_model=BacktestJobRef)
async def recompute(request: Request, user: AdminUser, session: Session, asof: date | None = None):
    return await _enqueue(
        request, session, user, "recompute", {"asof": str(asof) if asof else None}
    )


@router.get("/jobs/{job_id}", response_model=JobStatusOut)
async def job_status(job_id: UUID, user: CurrentUser, session: Session):
    job = await session.get(JobRun, str(job_id))
    if job is None or (not user.is_admin and job.user_id != user.id):
        raise HTTPException(404, "Job not found")
    state = job.status
    if state == "failed":
        try:
            if await run_in_threadpool(rq_status, job.id) in {JobStatus.QUEUED, JobStatus.DEFERRED}:
                state = "queued"
        except RedisError:
            pass
    result_url = None
    if job.result_key and state == "finished":
        try:
            result_url = await run_in_threadpool(s3.presigned_url, job.result_key)
        except (BotoCoreError, ClientError, RuntimeError):
            log.warning("Could not sign job %s artifact", job.id)
    return {
        "job_id": job.id,
        "status": state,
        "result": job.result_data,
        "error": job.error if state == "failed" else None,
        "result_key": job.result_key,
        "result_url": result_url,
    }


@router.get("/backtest/latest", response_model=BacktestSummary | BacktestNotice)
async def backtest_latest(_user: CurrentUser, session: Session):
    from stock_agents.engine.backtest import latest_summary

    result = await session.scalar(
        select(JobRun.result_data)
        .where(
            JobRun.job_type == "backtest",
            JobRun.status == "finished",
            JobRun.result_data.is_not(None),
        )
        .order_by(JobRun.finished_at.desc(), JobRun.id)
        .limit(1)
    )
    return result if result is not None else await run_in_threadpool(latest_summary)
