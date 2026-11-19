from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from stock_agents.storage.postgres import Base


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id = Column(String(36), primary_key=True)
    pipeline = Column(String(32), nullable=False)
    trade_date = Column(Date, nullable=False)
    status = Column(String(24), nullable=False)
    trigger = Column(String(24), nullable=False)
    dedupe_key = Column(String(160), unique=True, nullable=False)
    user_id = Column(Uuid(as_uuid=False), ForeignKey("users.id"))
    parent_id = Column(String(36))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    heartbeat_at = Column(DateTime(timezone=True))
    dispatched_at = Column(DateTime(timezone=True))
    next_attempt_at = Column(DateTime(timezone=True))
    attempt = Column(Integer, nullable=False, default=0)
    cancel_requested = Column(Boolean, nullable=False, default=False)
    stages = Column(JSONB, nullable=False, default=list)
    error = Column(Text)


class PipelineSchedule(Base):
    __tablename__ = "pipeline_schedules"
    id = Column(String(32), primary_key=True)
    label = Column(String(80), nullable=False)
    hour = Column(Integer, nullable=False)
    minute = Column(Integer, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
