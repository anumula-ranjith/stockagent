"""SQLAlchemy async engine + ORM models for the production Postgres stack.

The DuckDB file remains the research / backtest store. Postgres (with the
TimescaleDB hypertable on prices_daily) is the operational DB that the API
and workers read and write.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import AsyncIterator

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# -------------------------------------------------------------- reference
class Symbology(Base):
    __tablename__ = "symbology"
    ticker = Column(String, primary_key=True)
    eodhd_symbol = Column(String)
    factset_id = Column(String)
    isin = Column(String)
    cusip = Column(String)
    active = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime(timezone=True))


class Classification(Base):
    __tablename__ = "classification"
    ticker = Column(String, ForeignKey("symbology.ticker"), nullable=False)
    effective_date = Column(Date, nullable=False)
    known_date = Column(Date, nullable=False)
    sector = Column(String)
    industry = Column(String)
    source = Column(String)
    __table_args__ = (PrimaryKeyConstraint("ticker", "effective_date", "source"),)


# ------------------------------------------------------------- market data
class PricesDaily(Base):
    __tablename__ = "prices_daily"
    ticker = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    open = Column(Double)
    high = Column(Double)
    low = Column(Double)
    close = Column(Double)
    adj_close = Column(Double)
    volume = Column(BigInteger)
    source = Column(String)
    known_date = Column(Date, nullable=False)
    __table_args__ = (PrimaryKeyConstraint("ticker", "date", "source"),)


class CorporateActions(Base):
    __tablename__ = "corporate_actions"
    ticker = Column(String, ForeignKey("symbology.ticker"), nullable=False)
    action_type = Column(String, nullable=False)
    ex_date = Column(Date, nullable=False)
    value = Column(Double)
    source = Column(String)
    known_date = Column(Date, nullable=False)
    __table_args__ = (PrimaryKeyConstraint("ticker", "action_type", "ex_date", "source"),)


# -------------------------------------------------------------- fundamentals
class FundamentalsPit(Base):
    __tablename__ = "fundamentals_pit"
    ticker = Column(String, ForeignKey("symbology.ticker"), nullable=False)
    metric = Column(String, nullable=False)
    fiscal_period = Column(String, nullable=False)
    value = Column(Double)
    effective_date = Column(Date, nullable=False)
    known_date = Column(Date, nullable=False)
    source = Column(String, nullable=False)
    __table_args__ = (PrimaryKeyConstraint("ticker", "metric", "fiscal_period", "source"),)


class EstimatesPit(Base):
    __tablename__ = "estimates_pit"
    ticker = Column(String, ForeignKey("symbology.ticker"), nullable=False)
    metric = Column(String, nullable=False)
    value = Column(Double)
    n_analysts = Column(Integer)
    effective_date = Column(Date, nullable=False)
    known_date = Column(Date, nullable=False)
    source = Column(String, nullable=False)
    __table_args__ = (PrimaryKeyConstraint("ticker", "metric", "effective_date", "source"),)


# -------------------------------------------------------------- news
class News(Base):
    __tablename__ = "news"
    news_id = Column(String, primary_key=True)
    ticker = Column(String, ForeignKey("symbology.ticker"), nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=False)
    source = Column(String)
    headline = Column(Text)
    url = Column(Text)
    polarity = Column(Double)
    pos = Column(Double)
    neg = Column(Double)
    neu = Column(Double)
    known_date = Column(Date, nullable=False)


class SentimentDaily(Base):
    __tablename__ = "sentiment_daily"
    ticker = Column(String, ForeignKey("symbology.ticker"), nullable=False)
    effective_date = Column(Date, nullable=False)
    polarity = Column(Double)
    n_headlines = Column(Integer)
    source = Column(String, nullable=False)
    known_date = Column(Date, nullable=False)
    __table_args__ = (PrimaryKeyConstraint("ticker", "effective_date", "source"),)


# -------------------------------------------------------------- scores
class AgentScores(Base):
    __tablename__ = "agent_scores"
    date = Column(Date, nullable=False)
    ticker = Column(String, ForeignKey("symbology.ticker"), nullable=False)
    agent = Column(String, nullable=False)
    score = Column(Double)
    passes = Column(Boolean)
    __table_args__ = (PrimaryKeyConstraint("date", "ticker", "agent"),)


# -------------------------------------------------------------- users & jobs
class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, server_default=text("gen_random_uuid()"))
    email = Column(String, unique=True, nullable=False)
    hashed_pwd = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=text("NOW()"))


class JobRun(Base):
    __tablename__ = "job_runs"
    id = Column(String, primary_key=True, server_default=text("gen_random_uuid()"))
    job_type = Column(String, nullable=False)
    status = Column(String, nullable=False)
    enqueued_at = Column(DateTime(timezone=True), server_default=text("NOW()"))
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    error = Column(Text)
    result_key = Column(String)
    user_id = Column(String, ForeignKey("users.id"))


# -------------------------------------------------------- engine lifecycle
@lru_cache(maxsize=1)
def _engine():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL not set; expected e.g. "
            "postgresql+asyncpg://user:pass@host:5432/stockagents"
        )
    return create_async_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)


@lru_cache(maxsize=1)
def _session_factory():
    return async_sessionmaker(_engine(), expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: `session: AsyncSession = Depends(get_session)`."""
    async with _session_factory()() as s:
        yield s


async def init_schema() -> None:
    """Create any missing tables. Production uses Alembic; this is for dev."""
    async with _engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
