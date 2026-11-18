"""Ingest news headlines + aggregated daily sentiment from EODHD."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Iterable

import duckdb

from stock_agents.common import config as _config
from stock_agents.common.logging import get_logger
from stock_agents.sources.eodhd import EODHDClient

log = get_logger(__name__)

SOURCE = "eodhd"


def _tickers(conn: duckdb.DuckDBPyConnection) -> list[tuple[str, str]]:
    return conn.execute(
        "SELECT ticker, eodhd_symbol FROM symbology WHERE active = TRUE ORDER BY ticker"
    ).fetchall()


def ingest_news(
    conn: duckdb.DuckDBPyConnection,
    client: EODHDClient,
    tickers: Iterable[str] | None = None,
    limit_per_ticker: int = 50,
) -> int:
    univ = _tickers(conn)
    if tickers:
        wanted = set(tickers)
        univ = [(t, s) for t, s in univ if t in wanted]
    today = date.today()
    inserted = 0
    for ticker, symbol in univ:
        try:
            items = client.news(symbol, limit=limit_per_ticker)
        except Exception as e:
            log.warning("news skip %s: %s", ticker, e)
            continue
        rows = []
        for n in items:
            published = n.get("date")
            if not published:
                continue
            raw_id = f"{ticker}|{published}|{n.get('title', '')[:120]}"
            news_id = hashlib.sha1(raw_id.encode()).hexdigest()[:24]
            sentiment = n.get("sentiment") or {}
            try:
                ts = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except Exception:
                try:
                    ts = datetime.fromisoformat(published[:19])
                except Exception:
                    continue
            rows.append(
                (
                    news_id,
                    ticker,
                    ts,
                    n.get("source") or "",
                    (n.get("title") or "")[:500],
                    (n.get("link") or "")[:1000],
                    sentiment.get("polarity"),
                    sentiment.get("pos"),
                    sentiment.get("neg"),
                    sentiment.get("neu"),
                    today,
                )
            )
        if rows:
            conn.executemany(
                """INSERT OR REPLACE INTO news
                   (news_id, ticker, published_at, source, headline, url,
                    polarity, pos, neg, neu, known_date)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
            inserted += len(rows)
    log.info("news ingested: %d rows", inserted)
    return inserted


def ingest_sentiment_daily(
    conn: duckdb.DuckDBPyConnection,
    client: EODHDClient,
    tickers: Iterable[str] | None = None,
) -> int:
    univ = _tickers(conn)
    if tickers:
        wanted = set(tickers)
        univ = [(t, s) for t, s in univ if t in wanted]
    today = date.today()
    inserted = 0
    for ticker, symbol in univ:
        try:
            resp = client.sentiments(symbol)
        except Exception as e:
            log.warning("sentiment skip %s: %s", ticker, e)
            continue
        # response is {"SYMBOL.NSE": [{"date":"YYYY-MM-DD","count":N,"normalized":x}, ...]}
        entries = resp.get(symbol, []) if isinstance(resp, dict) else []
        rows = []
        for e in entries:
            rows.append(
                (
                    ticker,
                    e.get("date"),
                    e.get("normalized"),
                    int(e.get("count") or 0),
                    SOURCE,
                    today,
                )
            )
        if rows:
            conn.executemany(
                """INSERT OR REPLACE INTO sentiment_daily
                   (ticker, effective_date, polarity, n_headlines, source, known_date)
                   VALUES (?,?,?,?,?,?)""",
                rows,
            )
            inserted += len(rows)
    log.info("daily sentiment ingested: %d rows", inserted)
    return inserted
