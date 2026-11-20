"""PostgreSQL read connections for the API."""

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stock_agents.storage.postgres import session_factory


class ReadConnection:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def fetch(self, sql: str, **params: Any):
        return (await self.session.execute(text(sql), params)).all()


async def get_conn() -> AsyncIterator[ReadConnection]:
    async with session_factory()() as session:
        yield ReadConnection(session)
