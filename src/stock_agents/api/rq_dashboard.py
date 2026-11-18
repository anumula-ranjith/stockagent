"""Mount RQ Dashboard under the application's administrator boundary."""

import re
from functools import lru_cache
from uuid import UUID

from a2wsgi import WSGIMiddleware
from fastapi import HTTPException, Request
from flask import Flask
from redis.exceptions import RedisError
from rq.exceptions import InvalidJobOperation, NoSuchJobError
from rq.serializers import JSONSerializer
from rq_dashboard import default_settings, web
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from stock_agents.api import auth
from stock_agents.jobs.queue import QUEUE_NAME, redis_url, rq_queue
from stock_agents.storage.postgres import session_factory


@lru_cache(maxsize=4)
def _dashboard(url: str) -> WSGIMiddleware:
    app = Flask("rq_dashboard")
    app.config.from_object(default_settings)
    app.config.update(RQ_DASHBOARD_REDIS_URL=url, RQ_DASHBOARD_DISABLE_DELETE=True)
    web.config.serializer = JSONSerializer
    web.setup_rq_connection(app)
    app.register_blueprint(web.blueprint)
    return WSGIMiddleware(app)


def _requeue(job_id: str | None) -> int:
    registry = rq_queue().failed_job_registry
    ids = [job_id] if job_id else registry.get_job_ids(cleanup=False)
    count = 0
    for failed_id in ids:
        try:
            registry.requeue(failed_id)
        except (NoSuchJobError, InvalidJobOperation):
            continue
        count += 1
    return count


async def admin_dashboard(scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1008})
        return
    request = Request(scope)
    bearer = await auth.credentials(request)
    origin = f"{request.url.scheme}://{request.url.netloc}"
    csrf_header = auth.CSRF_HEADER.lower().encode()
    if (
        request.method == "POST"
        and bearer is None
        and request.headers.get("X-Requested-With") == "XMLHttpRequest"
        and request.headers.get("Origin", origin) == origin
    ):
        # RQ Dashboard's same-origin AJAX uses this standard non-simple header.
        headers = [(key, value) for key, value in scope["headers"] if key != csrf_header]
        scope = dict(scope, headers=[*headers, (csrf_header, b"1")])
        request = Request(scope)

    try:
        user = await auth.get_current_user(request, bearer)
        await auth.require_admin(request, user)
        path = request.url.path.removeprefix(scope.get("root_path", ""))
        single = re.fullmatch(r"/job/([^/]+)/requeue", path)
        bulk = path == f"/requeue/{QUEUE_NAME}"
        if request.method == "POST" and (single or bulk):
            try:
                job_id = str(UUID(single[1])) if single else None
            except ValueError as exc:
                raise HTTPException(404, "Job not found") from exc
            async with session_factory().begin() as session:
                auth.audit(
                    session,
                    request,
                    user.id,
                    "/_admin/rq/requeue",
                    {"job_id": job_id, "queue": QUEUE_NAME},
                )
            count = await run_in_threadpool(_requeue, job_id)
            if single and not count:
                raise HTTPException(409, "Job is no longer in the failed registry")
            response = JSONResponse({"status": "OK", "count": count})
        elif request.method in {"GET", "HEAD"} and "/requeue/" not in path:
            await _dashboard(redis_url())(scope, receive, send)
            return
        else:
            raise HTTPException(405, "Method not allowed")
    except HTTPException as exc:
        response = JSONResponse({"detail": exc.detail}, exc.status_code, headers=exc.headers)
    except RedisError:
        response = JSONResponse({"detail": "Queue unavailable"}, 503)
    await response(scope, receive, send)
