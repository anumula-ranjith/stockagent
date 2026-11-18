"""Synchronous PostgreSQL transactions for ingestion, scoring and backtests."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, CursorResult


class Warehouse:
    """Adapt the research functions' positional SQL to SQLAlchemy bindings."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    @staticmethod
    def _statement(sql: str, values: Sequence[Any]):
        parts = sql.split("?")
        if len(parts) != len(values) + 1:
            raise ValueError("SQL parameter count does not match its arguments")
        bound = parts[0]
        for index, part in enumerate(parts[1:]):
            bound += f":p{index}" + part
        return text(bound), {f"p{index}": value for index, value in enumerate(values)}

    def execute(self, sql: str, values: Sequence[Any] = ()) -> CursorResult:
        statement, parameters = self._statement(sql, values)
        return self.connection.execute(statement, parameters)

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> CursorResult | None:
        if not rows:
            return None
        statement, _ = self._statement(sql, rows[0])
        parameters = [self._statement(sql, row)[1] for row in rows]
        return self.connection.execute(statement, parameters)


@contextmanager
def connect(*, read_only: bool = False) -> Iterator[Warehouse]:
    from stock_agents.jobs.queue import sync_engine

    with sync_engine().begin() as connection:
        if read_only:
            connection.execute(text("SET TRANSACTION READ ONLY"))
        yield Warehouse(connection)
