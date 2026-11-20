"""SQLAlchemy metadata for the independently audited research datasets."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column as C,
    Date,
    DateTime,
    Double,
    ForeignKey as FK,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from stock_agents.storage.postgres import Base

metadata = Base.metadata
timestamp = DateTime(timezone=True)
snapshots = Table(
    "research_universe_snapshots",
    metadata,
    C("id", Text, primary_key=True),
    C("observed_on", Date, nullable=False),
    C("retrieved_at", timestamp, nullable=False),
    C("source_url", Text, nullable=False),
    C("content_hash", Text, nullable=False),
    C("constituent_count", Integer, nullable=False),
    UniqueConstraint("observed_on", "content_hash"),
)
members = Table(
    "research_universe_members",
    metadata,
    C("snapshot_id", Text, FK("research_universe_snapshots.id"), primary_key=True),
    C("ticker", Text, FK("symbology.ticker"), primary_key=True),
    C("company_name", Text, nullable=False),
    C("isin", Text, nullable=False),
    C("series", Text, nullable=False),
)
runs = Table(
    "market_signal_runs",
    metadata,
    C("id", Text, primary_key=True),
    C("source", Text, nullable=False),
    C("ticker", Text),
    C("start_date", Date, nullable=False),
    C("end_date", Date, nullable=False),
    C("snapshot_id", Text, FK("research_universe_snapshots.id")),
    C("membership_basis", Text, nullable=False, server_default="current_snapshot_backfill"),
    C("status", Text, nullable=False),
    C("started_at", timestamp, nullable=False),
    C("finished_at", timestamp),
    C("rows_fetched", Integer, nullable=False, server_default="0"),
    C("rows_inserted", Integer, nullable=False, server_default="0"),
    C("rows_updated", Integer, nullable=False, server_default="0"),
    C("reason", Text, nullable=False, server_default=""),
    C("details", JSONB, nullable=False, server_default=text("'{}'")),
)
Index(
    "market_signal_run_lookup",
    runs.c.source,
    runs.c.start_date,
    runs.c.end_date,
    runs.c.started_at.desc(),
)
short_sales = Table(
    "short_sale_observations",
    metadata,
    C("ticker", Text, FK("symbology.ticker"), primary_key=True),
    C("trade_date", Date, primary_key=True),
    C("short_sale_shares", BigInteger, nullable=False),
    C("source", Text, nullable=False, server_default="NSE historical short selling"),
    C("retrieved_at", timestamp, nullable=False),
    C("run_id", Text, FK("market_signal_runs.id"), nullable=False),
    CheckConstraint("short_sale_shares>=0"),
)
short_interest = Table(
    "short_interest_estimates",
    metadata,
    C("ticker", Text, FK("symbology.ticker"), primary_key=True),
    C("observation_date", Date, primary_key=True),
    C("source", Text, primary_key=True, server_default="ORTEX"),
    C("short_interest_shares", Double),
    C("short_interest_pct_free_float", Double),
    C("retrieved_at", timestamp, nullable=False),
    C("run_id", Text, FK("market_signal_runs.id"), nullable=False),
    CheckConstraint("short_interest_shares>=0 AND short_interest_shares<'Infinity'::float8"),
    CheckConstraint(
        "short_interest_pct_free_float>=0 AND short_interest_pct_free_float<'Infinity'::float8"
    ),
    CheckConstraint(
        "short_interest_shares IS NOT NULL OR short_interest_pct_free_float IS NOT NULL"
    ),
)
buzz = Table(
    "publisher_buzz",
    metadata,
    C("news_item_id", BigInteger, FK("news_items.id"), primary_key=True),
    C("rule_version", Text, nullable=False),
    C("retrieved_at", timestamp, nullable=False),
    C("run_id", Text, FK("market_signal_runs.id"), nullable=False),
)
buzz_companies = Table(
    "publisher_buzz_companies",
    metadata,
    C("news_item_id", BigInteger, FK("publisher_buzz.news_item_id"), primary_key=True),
    C("ticker", Text, FK("symbology.ticker"), primary_key=True),
    Index("publisher_buzz_ticker", "ticker", "news_item_id"),
)
posts = Table(
    "public_social_posts",
    metadata,
    C("hn_item_id", BigInteger, primary_key=True, autoincrement=False),
    C("title", Text, nullable=False),
    C("discussion_url", Text, nullable=False),
    C("published_at", timestamp, nullable=False),
    C("points", Integer),
    C("comment_count", Integer),
    C("retrieved_at", timestamp, nullable=False),
    C("engagement_observed_at", timestamp, nullable=False),
    C("run_id", Text, FK("market_signal_runs.id"), nullable=False),
    CheckConstraint("points>=0"),
    CheckConstraint("comment_count>=0"),
)
Index("public_social_publication", posts.c.published_at.desc(), posts.c.hn_item_id)
post_companies = Table(
    "public_social_post_companies",
    metadata,
    C("hn_item_id", BigInteger, FK("public_social_posts.hn_item_id"), primary_key=True),
    C("ticker", Text, FK("symbology.ticker"), primary_key=True),
    Index("public_social_ticker", "ticker", "hn_item_id"),
)
