"""Ingest news headlines + aggregated daily sentiment from EODHD."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import date, datetime

from stock_agents.common.logging import get_logger
from stock_agents.sources.eodhd import EODHDClient
from stock_agents.storage.warehouse import Warehouse

log = get_logger(__name__)

SOURCE = "eodhd"


def _tickers(conn: Warehouse) -> list[tuple[str, str]]:
    return conn.execute(
        "SELECT ticker, eodhd_symbol FROM symbology WHERE active = TRUE AND eodhd_symbol IS NOT NULL ORDER BY ticker"
    ).fetchall()


def ingest_news(
    conn: Warehouse,
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
    failures = 0
    for ticker, symbol in univ:
        try:
            items = client.news(symbol, limit=limit_per_ticker)
        except Exception as e:
            failures += 1
            log.warning("news ingest skipped %s (%s)", ticker, type(e).__name__)
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
                """INSERT INTO news
                   (news_id, ticker, published_at, source, headline, url,
                    polarity, pos, neg, neu, known_date)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT (news_id) DO NOTHING""",
                rows,
            )
            inserted += len(rows)
    if univ and failures == len(univ):
        raise RuntimeError("All EODHD news requests failed")
    log.info("news ingested: %d rows", inserted)
    return inserted


def ingest_sentiment_daily(
    conn: Warehouse,
    client: EODHDClient,
    tickers: Iterable[str] | None = None,
) -> int:
    univ = _tickers(conn)
    if tickers:
        wanted = set(tickers)
        univ = [(t, s) for t, s in univ if t in wanted]
    today = date.today()
    inserted = 0
    failures = 0
    for ticker, symbol in univ:
        try:
            resp = client.sentiments(symbol)
        except Exception as e:
            failures += 1
            log.warning("sentiment ingest skipped %s (%s)", ticker, type(e).__name__)
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
                """INSERT INTO sentiment_daily
                   (ticker, effective_date, polarity, n_headlines, source, known_date)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT (ticker, effective_date, source) DO UPDATE SET
                       polarity = EXCLUDED.polarity, n_headlines = EXCLUDED.n_headlines,
                       known_date = EXCLUDED.known_date
                   WHERE sentiment_daily.polarity IS DISTINCT FROM EXCLUDED.polarity
                      OR sentiment_daily.n_headlines IS DISTINCT FROM EXCLUDED.n_headlines""",
                rows,
            )
            inserted += len(rows)
    if univ and failures == len(univ):
        raise RuntimeError("All EODHD sentiment requests failed")
    log.info("daily sentiment ingested: %d rows", inserted)
    return inserted
