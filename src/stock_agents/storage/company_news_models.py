"""News schema metadata for Alembic and SQLAlchemy tooling."""
from sqlalchemy import BigInteger, CheckConstraint, Column, Date, DateTime, Double, ForeignKey, Index, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from stock_agents.storage.postgres import Base


class NewsCompany(Base):
    __tablename__ = "news_companies"
    symbol = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    segment = Column(Text, nullable=False)
    isin = Column(Text)
    instrument_ticker = Column(Text, ForeignKey("symbology.ticker"))
    aliases = Column(JSONB, nullable=False, server_default=text("'[]'"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CompanyNewsItem(Base):
    __tablename__ = "news_items"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    kind = Column(Text, nullable=False)
    source = Column(Text, nullable=False)
    source_key = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    url = Column(Text, nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=False)
    ingested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint("source", "source_key"),
                      CheckConstraint("kind IN ('headline','announcement')"),
                      Index("news_items_publication", published_at.desc(), id.desc()))


class NewsItemCompany(Base):
    __tablename__ = "news_item_companies"
    news_item_id = Column(BigInteger, ForeignKey("news_items.id", ondelete="CASCADE"), primary_key=True)
    symbol = Column(Text, ForeignKey("news_companies.symbol"), primary_key=True)
    __table_args__ = (Index("news_company_filter", "symbol", "news_item_id"),)


class CompanyNewsCoverage(Base):
    __tablename__ = "company_news_coverage"
    source = Column(Text, primary_key=True)
    day = Column(Date, primary_key=True)
    status = Column(Text, nullable=False)
    checked_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_success = Column(DateTime(timezone=True))
    item_count = Column(Integer, nullable=False, server_default=text("0"))
    detail = Column(Text, nullable=False, server_default=text("''"))


class CompanyNewsSentiment(Base):
    __tablename__ = "company_news_sentiment"
    news_item_id = Column(BigInteger, ForeignKey("news_items.id", ondelete="CASCADE"), primary_key=True)
    model = Column(Text, nullable=False)
    title_hash = Column(Text, nullable=False)
    scored_at = Column(DateTime(timezone=True), nullable=False)
    positive = Column(Double, nullable=False)
    negative = Column(Double, nullable=False)
    neutral = Column(Double, nullable=False)
    polarity = Column(Double, nullable=False)
    __table_args__ = (
        CheckConstraint("positive BETWEEN 0 AND 1"), CheckConstraint("negative BETWEEN 0 AND 1"),
        CheckConstraint("neutral BETWEEN 0 AND 1"), CheckConstraint("polarity BETWEEN -1 AND 1"),
        CheckConstraint("abs(positive+negative+neutral-1)<0.001"),
    )
