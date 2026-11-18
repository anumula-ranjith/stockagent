"""Trace DB work without statements, parameters, credentials, or row data."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import duckdb
from opentelemetry.trace import SpanKind, StatusCode
from sqlalchemy import event
from sqlalchemy.engine import Engine

from stock_agents.common.telemetry import tracer

OPERATIONS = {
    "SELECT", "INSERT", "UPDATE", "DELETE", "WITH", "BEGIN", "COMMIT",
    "ROLLBACK", "CREATE", "ALTER", "DROP", "CALL", "SHOW", "DESCRIBE", "PRAGMA",
}


def _operation(statement: str) -> str:
    first = statement.lstrip().split(maxsplit=1)
    verb = first[0].upper() if first else ""
    return verb if verb in OPERATIONS else "QUERY"


def instrument_engine(engine: Engine) -> None:
    @event.listens_for(engine, "before_cursor_execute")
    def begin(_conn: Any, _cursor: Any, statement: str, _params: Any, context: Any, _many: bool) -> None:
        operation = _operation(statement)
        context._stock_agents_span = tracer().start_span(
            f"postgresql {operation}", kind=SpanKind.CLIENT,
            attributes={"db.system.name": "postgresql", "db.operation.name": operation},
        )

    @event.listens_for(engine, "after_cursor_execute")
    def finish(_conn: Any, _cursor: Any, _statement: str, _params: Any, context: Any, _many: bool) -> None:
        span = getattr(context, "_stock_agents_span", None)
        if span is not None:
            span.end()

    @event.listens_for(engine, "handle_error")
    def fail(error: Any) -> None:
        span = getattr(error.execution_context, "_stock_agents_span", None)
        if span is not None:
            span.set_status(StatusCode.ERROR)
            span.end()


class TracedDuckDB:
    def __init__(self, connection: "duckdb.DuckDBPyConnection") -> None:
        self._connection = connection

    def __enter__(self) -> "TracedDuckDB":
        self._connection.__enter__()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._connection.__exit__(*exc)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    @contextmanager
    def _query(self, statement: str) -> Iterator[None]:
        operation = _operation(statement)
        with tracer().start_as_current_span(
            f"duckdb {operation}", kind=SpanKind.CLIENT, record_exception=False,
            set_status_on_exception=False,
            attributes={"db.system.name": "duckdb", "db.operation.name": operation},
        ) as span:
            try:
                yield
            except Exception:
                span.set_status(StatusCode.ERROR)
                raise

    def execute(self, statement: str, *args: Any, **kwargs: Any) -> "TracedDuckDB":
        with self._query(statement):
            self._connection.execute(statement, *args, **kwargs)
        return self

    def executemany(self, statement: str, *args: Any, **kwargs: Any) -> "TracedDuckDB":
        with self._query(statement):
            self._connection.executemany(statement, *args, **kwargs)
        return self


def connect_duckdb(path: str, *, read_only: bool = False) -> Any:
    import duckdb

    return TracedDuckDB(duckdb.connect(path, read_only=read_only))
