"""Project-wide logging. One rotating file per process + stderr."""

from __future__ import annotations

import logging
import logging.handlers
import os
import re
from pathlib import Path

import structlog
from opentelemetry.trace import get_current_span
from structlog.typing import EventDict, Processor, WrappedLogger

_CONFIGURED: dict[str, bool] = {"done": False}
_service_name = "stock-agents"
_SECRET = re.compile(
    r"(?i)(\b(?:api[_-]?(?:key|token)|access[_-]?token|password|secret|"
    r"x-amz-[\w-]+|authorization)\s*[=:]\s*)(?:bearer\s+)?[^&\s,]+"
)
_URL_AUTH = re.compile(r"(://)[^/\s@]+@")


def _safe_record(_logger: WrappedLogger, _method: str, event: EventDict) -> EventDict:
    for key in ("stack", "stack_info", "exception"):
        event.pop(key, None)
    info = event.pop("exc_info", None)
    if isinstance(info, tuple) and info[0] is not None:
        event["error_type"] = info[0].__name__
    if "event" in event:
        event["event"] = _URL_AUTH.sub(r"\1[redacted]@", _SECRET.sub(r"\1[redacted]", str(event["event"])))
    span = get_current_span().get_span_context()
    if span.is_valid:
        event["trace_id"] = f"{span.trace_id:032x}"
        event["span_id"] = f"{span.span_id:016x}"
    return event


def configure(
    level: str = "INFO", log_dir: str | os.PathLike | None = None, *, service: str | None = None
) -> None:
    """Install root handlers (stderr + rotating file). Safe to call repeatedly."""
    global _service_name
    if service is not None:
        _service_name = service
    if _CONFIGURED["done"]:
        return
    common: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    def service_field(_logger: WrappedLogger, _method: str, event: EventDict) -> EventDict:
        event.setdefault("service", _service_name)
        return event

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=common,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            service_field, _safe_record, structlog.processors.JSONRenderer(),
        ],
    )
    structlog.configure(
        processors=[*common, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)
    if log_dir:
        p = Path(log_dir)
        p.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            p / f"{_service_name}.log",
            maxBytes=50 * 1024 * 1024,
            backupCount=10,
            encoding="utf-8",
        )
        fh.setFormatter(formatter)
        root.addHandler(fh)
    _CONFIGURED["done"] = True
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    # The structured HTTP middleware logs a route template, without raw paths or queries.
    logging.getLogger("uvicorn.access").disabled = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger. Lazily configures root on first call."""
    if not _CONFIGURED["done"]:
        configure()
    return logging.getLogger(name)
