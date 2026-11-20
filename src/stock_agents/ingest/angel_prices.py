"""Persist provisional raw NSE daily bars at Angel One's exchange trade timestamp."""

from __future__ import annotations

import math
from datetime import date, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from stock_agents.ingest.daily import MARKET_TZ
from stock_agents.sources.angel_market import fetch_full_quotes
from stock_agents.storage.postgres import Base

SOURCE = "angel_one"


def _bar(ticker: str, quote: dict, day: date, known: date) -> dict | None:
    try:
        # FULL.close is the previous close. Date the LTP by the last actual trade,
        # since a fresh exchange feed packet can carry a previous session's price.
        traded_at = datetime.strptime(quote["exchTradeTime"], "%d-%b-%Y %H:%M:%S")
        if traded_at.date() != day:
            return None
        prices = [quote[field] for field in ("open", "high", "low", "ltp")]
        if any(isinstance(value, bool) for value in prices):
            return None
        opening, high, low, last = map(float, prices)
        volume = int(str(quote["tradeVolume"]))
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(value) and value > 0 for value in (opening, high, low, last)):
        return None
    if not (low <= opening <= high and low <= last <= high and 0 < volume < 2**63):
        return None
    return dict(
        ticker=ticker,
        date=day,
        known_date=known,
        source=SOURCE,
        exchange_trade_at=traded_at.replace(tzinfo=MARKET_TZ),
        open=opening,
        high=high,
        low=low,
        close=last,
        volume=volume,
        adj_close=None,
    )


def refresh_angel_prices(conn: Connection, trade_date: date) -> dict:
    """Fetch the current FULL snapshot. The caller owns the write transaction."""
    known = datetime.now(MARKET_TZ).date()
    if trade_date > known:
        raise ValueError("A future Angel One trading date cannot be loaded")
    symbols = Base.metadata.tables["symbology"]
    membership = Base.metadata.tables["index_membership"]
    members = list(
        conn.scalars(
            select(symbols.c.ticker)
            .join(
                membership,
                symbols.c.ticker == membership.c.ticker,
            )
            .where(
                symbols.c.active.is_(True),
                ~symbols.c.ticker.startswith("DUMMY"),
                membership.c.index_code.in_(("NIFTY500", "NSE_FO")),
                membership.c.joined_on <= trade_date,
                membership.c.known_on <= known,
                or_(membership.c.left_on.is_(None), membership.c.left_on > trade_date),
            )
            .distinct()
            .order_by(symbols.c.ticker)
        )
    )
    if not members:
        raise ValueError("No active Nifty 500 or NSE F&O members for the requested session")

    prices = Base.metadata.tables["prices_daily"]
    bars = {}
    for instrument, quote in fetch_full_quotes(members, known):
        bar = _bar(instrument.ticker, quote, trade_date, known)
        if bar is not None:
            prior = bars.get(instrument.ticker)
            if prior is None or (bar["exchange_trade_at"], bar["volume"]) > (
                prior["exchange_trade_at"],
                prior["volume"],
            ):
                bars[instrument.ticker] = bar
    written = 0
    if bars:
        # The source is part of the PK. Keep final provider prices and reject replayed
        # or out-of-order ticks, including concurrent requests in a different worker.
        statement = insert(prices).values(list(bars.values()))
        incoming = statement.excluded
        written = conn.execute(
            statement.on_conflict_do_update(
                index_elements=list(prices.primary_key.columns),
                set_={c.name: incoming[c.name] for c in prices.columns if not c.primary_key},
                where=or_(
                    prices.c.exchange_trade_at.is_(None),
                    incoming.exchange_trade_at > prices.c.exchange_trade_at,
                    and_(
                        incoming.exchange_trade_at == prices.c.exchange_trade_at,
                        incoming.volume > prices.c.volume,
                    ),
                ),
            )
        ).rowcount
    # Count the union of valid rows from this session, including prior partial retries.
    stored = dict(
        conn.execute(
            select(prices.c.ticker, prices.c.exchange_trade_at).where(
                prices.c.source == SOURCE,
                prices.c.date == trade_date,
                prices.c.ticker.in_(members),
                prices.c.exchange_trade_at.is_not(None),
            )
        ).all()
    )
    missing = sorted(set(members) - stored.keys())
    latest = max(stored.values(), default=None)
    return {
        "status": "partial" if missing else "ok",
        "trade_date": trade_date.isoformat(),
        "members": len(members),
        "priced": len(stored),
        "written": written,
        "missing": missing,
        "latest_trade_at": latest.astimezone(MARKET_TZ).isoformat() if latest else None,
    }
