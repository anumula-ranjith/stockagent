"""Request correlation, W3C trace propagation, and bounded HTTP metrics."""

import re
from time import perf_counter
from uuid import uuid4

import structlog
from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, StatusCode
from prometheus_client import Gauge, Histogram
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from stock_agents.common import config

REQUEST_ID = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")
METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
_provider: TracerProvider | None = None
log = structlog.get_logger(__name__)
request_duration = Histogram(
    "stock_agents_http_request_duration_seconds", "Request latency by route template",
    ["method", "route", "status"],
)
dependency_ready = Gauge(
    "stock_agents_dependency_ready", "Most recent readiness result (1 means ready)", ["dependency"]
)


def setup_tracing(service: str) -> None:
    global _provider
    if _provider is not None:
        return
    settings = config.load_settings()
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    if settings.env("OTEL_EXPORTER_OTLP_ENDPOINT") or settings.env("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(timeout=3)))
    _provider = provider


def tracer() -> trace.Tracer:
    provider = _provider or trace.get_tracer_provider()
    return provider.get_tracer("stock_agents")


def flush_traces() -> None:
    if _provider is not None:
        _provider.force_flush(timeout_millis=1500)


def trace_headers() -> dict[str, str]:
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return {key: value for key, value in carrier.items() if key in {"traceparent", "tracestate"}}


def request_id(value: str | None = None) -> str:
    return value if value and REQUEST_ID.fullmatch(value) else uuid4().hex


def _route_name(scope: Scope) -> str:
    matched = scope.get("route")
    return (
        getattr(matched, "path_format", None) or getattr(matched, "path", None)
        or ("/_admin/rq/*" if scope["path"].startswith("/_admin/rq/") else "/unmatched")
    )


class ObserveRequests:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = Headers(scope=scope)
        correlation = request_id(incoming.get("x-request-id"))
        scope.setdefault("state", {})["request_id"] = correlation
        method = scope["method"] if scope["method"] in METHODS else "OTHER"
        status = 500
        start = perf_counter()
        parent = propagate.extract({key: incoming[key] for key in ("traceparent", "tracestate") if key in incoming})

        async def instrumented_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = correlation
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=correlation):
            with tracer().start_as_current_span(
                method, context=parent, kind=SpanKind.SERVER,
                record_exception=False, set_status_on_exception=False,
            ) as span:
                try:
                    await self.app(scope, receive, instrumented_send)
                finally:
                    route = _route_name(scope)
                    span.update_name(f"{method} {route}")
                    span.set_attributes({
                        "http.request.method": method, "http.route": route,
                        "http.response.status_code": status, "stock_agents.request_id": correlation,
                    })
                    if status >= 500:
                        span.set_status(StatusCode.ERROR)
                    duration = perf_counter() - start
                    request_duration.labels(method, route, str(status)).observe(duration)
                    log.info("http.completed", method=method, route=route, status=status,
                             duration_ms=round(duration * 1000, 2))
