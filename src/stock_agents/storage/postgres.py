"""SQLAlchemy async engine + ORM models for the production Postgres stack.

Postgres (with the TimescaleDB hypertable on prices_daily) stores market
data, scoring inputs and outputs, backtests and operational application state.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from stock_agents.common.config import load_settings
from stock_agents.storage.tracing import instrument_engine


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
    active = Column(Boolean, server_default=text("true"), nullable=False)
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
    id = Column(Uuid(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    email = Column(String, unique=True, nullable=False)
    hashed_pwd = Column(String)
    clerk_subject = Column(String, unique=True)
    is_admin = Column(Boolean, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), server_default=text("NOW()"))


class JobRun(Base):
    __tablename__ = "job_runs"
    id = Column(Uuid(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    job_type = Column(String, nullable=False)
    status = Column(String, nullable=False)
    enqueued_at = Column(DateTime(timezone=True), server_default=text("NOW()"))
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    error = Column(Text)
    result_key = Column(String)
    user_id = Column(Uuid(as_uuid=False), ForeignKey("users.id"))
    payload = Column(JSONB)
    result_data = Column(JSONB)
    request_id = Column(String(64))
    trace_context = Column(JSONB)


class JobMetric(Base):
    __tablename__ = "job_metrics"
    job_type = Column(String, primary_key=True)
    outcome = Column(String, primary_key=True)
    executions = Column(BigInteger, nullable=False)
    duration_seconds = Column(Double, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(BigInteger, primary_key=True)
    user_id = Column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"))
    action = Column(String, nullable=False)
    ip = Column(String)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    request_hash = Column(String(64), nullable=False)


# Other warehouse tables use Core metadata for bulk writes.
Table(
    "index_membership",
    Base.metadata,
    Column("index_code", String, nullable=False),
    Column("ticker", String, nullable=False),
    Column("joined_on", Date, nullable=False),
    Column("left_on", Date),
    Column("known_on", Date, nullable=False),
    PrimaryKeyConstraint("index_code", "ticker", "joined_on"),
)

Table(
    "analyst_pit",
    Base.metadata,
    Column("ticker", String, nullable=False),
    Column("rating_mean", Double),
    Column("target_mean", Double),
    Column("n_analysts", Integer),
    Column("effective_date", Date, nullable=False),
    Column("known_date", Date, nullable=False),
    Column("source", String, nullable=False),
    PrimaryKeyConstraint("ticker", "effective_date", "source"),
)

Table(
    "earnings_surprise",
    Base.metadata,
    Column("ticker", String, nullable=False),
    Column("fiscal_period", String, nullable=False),
    Column("eps_reported", Double),
    Column("eps_estimate", Double),
    Column("surprise_pct", Double),
    Column("report_date", Date, nullable=False),
    Column("known_date", Date, nullable=False),
    Column("source", String, nullable=False),
    PrimaryKeyConstraint("ticker", "fiscal_period", "source"),
)

Table(
    "events_calendar",
    Base.metadata,
    Column("ticker", String, nullable=False),
    Column("event_type", String, nullable=False),
    Column("event_date", Date, nullable=False),
    Column("time_of_day", String),
    Column("fiscal_period", String),
    Column("known_date", Date, nullable=False),
    Column("source", String, nullable=False),
    PrimaryKeyConstraint("ticker", "event_type", "event_date", "source"),
)

Table(
    "insider_tx",
    Base.metadata,
    Column("tx_id", String, primary_key=True),
    Column("ticker", String, nullable=False),
    Column("tx_date", Date, nullable=False),
    Column("tx_type", String),
    Column("shares", Double),
    Column("price", Double),
    Column("value_usd", Double),
    Column("insider_role", String),
    Column("known_date", Date, nullable=False),
    Column("source", String, nullable=False),
)

Table(
    "inst_ownership",
    Base.metadata,
    Column("ticker", String, nullable=False),
    Column("effective_date", Date, nullable=False),
    Column("inst_holders", Integer),
    Column("inst_pct_owned", Double),
    Column("known_date", Date, nullable=False),
    Column("source", String, nullable=False),
    PrimaryKeyConstraint("ticker", "effective_date", "source"),
)

Table(
    "short_interest",
    Base.metadata,
    Column("ticker", String, nullable=False),
    Column("settlement_date", Date, nullable=False),
    Column("short_shares", BigInteger),
    Column("short_pct_float", Double),
    Column("days_to_cover", Double),
    Column("known_date", Date, nullable=False),
    Column("source", String, nullable=False),
    PrimaryKeyConstraint("ticker", "settlement_date", "source"),
)

Table(
    "social_daily",
    Base.metadata,
    Column("ticker", String, nullable=False),
    Column("effective_date", Date, nullable=False),
    Column("mentions", Integer),
    Column("avg_sentiment", Double),
    Column("known_date", Date, nullable=False),
    Column("source", String, nullable=False),
    PrimaryKeyConstraint("ticker", "effective_date", "source"),
)

Table(
    "macro",
    Base.metadata,
    Column("series_id", String, nullable=False),
    Column("effective_date", Date, nullable=False),
    Column("value", Double),
    Column("known_date", Date, nullable=False),
    Column("source", String, nullable=False),
    PrimaryKeyConstraint("series_id", "effective_date", "source"),
)

Table(
    "factor_values",
    Base.metadata,
    Column("date", Date, nullable=False),
    Column("ticker", String, nullable=False),
    Column("agent", String, nullable=False),
    Column("factor", String, nullable=False),
    Column("raw", Double),
    Column("score", Double),
    Column("imputed", Boolean),
    PrimaryKeyConstraint("date", "ticker", "agent", "factor"),
)

Table(
    "signals",
    Base.metadata,
    Column("date", Date, nullable=False),
    Column("ticker", String, ForeignKey("symbology.ticker"), nullable=False),
    Column("side", String, nullable=False),
    Column("composite", Double),
    Column("tech", Double),
    Column("sent", Double),
    Column("mom", Double),
    Column("fund", Double),
    Column("rank", Integer),
    Column("reasons", Text),
    PrimaryKeyConstraint("date", "ticker", "side"),
)

Table(
    "target_weights",
    Base.metadata,
    Column("date", Date, nullable=False),
    Column("ticker", String, nullable=False),
    Column("weight", Double, nullable=False),
    PrimaryKeyConstraint("date", "ticker"),
)

Table(
    "orders",
    Base.metadata,
    Column("order_id", String, primary_key=True),
    Column("date", Date, nullable=False),
    Column("ticker", String, nullable=False),
    Column("side", String, nullable=False),
    Column("qty", Double, nullable=False),
    Column("type", String),
    Column("status", String),
    Column("submitted_at", DateTime),
    Column("broker", String),
)

Table(
    "fills",
    Base.metadata,
    Column("fill_id", String, primary_key=True),
    Column("order_id", String, nullable=False),
    Column("ticker", String, nullable=False),
    Column("side", String, nullable=False),
    Column("qty", Double, nullable=False),
    Column("price", Double),
    Column("filled_at", DateTime),
    Column("broker", String),
)

Table(
    "positions",
    Base.metadata,
    Column("date", Date, nullable=False),
    Column("ticker", String, nullable=False),
    Column("qty", Double),
    Column("avg_cost", Double),
    Column("market_value", Double),
    PrimaryKeyConstraint("date", "ticker"),
)

Table(
    "nav",
    Base.metadata,
    Column("date", Date, primary_key=True),
    Column("nav", Double, nullable=False),
    Column("cash", Double),
    Column("gross_long", Double),
    Column("gross_short", Double),
)

Table(
    "quality_log",
    Base.metadata,
    Column("run_id", String, nullable=False),
    Column("ts", DateTime, nullable=False),
    Column("check_name", String, nullable=False),
    Column("severity", String, nullable=False),
    Column("passed", Boolean, nullable=False),
    Column("detail", String),
)

Table(
    "run_log",
    Base.metadata,
    Column("run_id", String, primary_key=True),
    Column("job", String, nullable=False),
    Column("started_at", DateTime, nullable=False),
    Column("ended_at", DateTime),
    Column("status", String),
    Column("rows_written", Integer),
    Column("warnings", String),
)


Index("idx_prices_ticker_date", PricesDaily.ticker, PricesDaily.date.desc())
Index("prices_daily_date_idx", PricesDaily.date.desc())
Index("idx_fund_known", FundamentalsPit.ticker, FundamentalsPit.known_date)
Index("idx_news_tk_dt", News.ticker, News.published_at.desc())
Index("idx_scores_date", AgentScores.date.desc())
Index("idx_job_runs_enqueued", JobRun.enqueued_at.desc())
Index("uq_users_normalized_email", func.lower(User.email), unique=True)
Index("idx_audit_log_action", AuditLog.action)


# -------------------------------------------------------- engine lifecycle
def database_url(driver: str = "asyncpg", value: str | None = None) -> URL:
    raw = value or load_settings().env("DATABASE_URL")
    if not raw:
        raise RuntimeError("Set DATABASE_URL to a PostgreSQL connection URL")
    url = make_url(raw)
    if url.get_backend_name() not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL must point to PostgreSQL")
    return url.set(drivername=f"postgresql+{driver}")


@lru_cache(maxsize=1)
def _engine():
    engine = create_async_engine(database_url(), pool_pre_ping=True, hide_parameters=True)
    instrument_engine(engine.sync_engine)
    return engine


@lru_cache(maxsize=1)
def session_factory():
    return async_sessionmaker(_engine(), expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: `session: AsyncSession = Depends(get_session)`."""
    async with session_factory()() as s:
        yield s


async def dispose_engine() -> None:
    if _engine.cache_info().currsize:
        await _engine().dispose()
        session_factory.cache_clear()
        _engine.cache_clear()


async def init_schema() -> None:
    """Create any missing tables. Production uses Alembic; this is for dev."""
    async with _engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
