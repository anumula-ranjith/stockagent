"""Ingest news headlines + aggregated daily sentiment from EODHD."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
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
    *, report: bool = False,
) -> int | dict:
    univ = _tickers(conn)
    if tickers:
        wanted = set(tickers)
        univ = [(t, s) for t, s in univ if t in wanted]
    today = date.today()
    inserted = 0
    failures = 0
    def fetch(member):
        ticker, symbol = member
        try:
            return ticker, client.news(symbol, limit=limit_per_ticker), None
        except Exception as e:
            return ticker, [], type(e).__name__

    with ThreadPoolExecutor(max_workers=6) as pool:
      for ticker, items, error in pool.map(fetch, univ):
        if error:
            failures += 1
            log.warning("news ingest skipped %s (%s)", ticker, error)
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
    return {"status": "partial" if failures else "ok", "rows": inserted, "failures_count": failures} if report else inserted


def ingest_sentiment_daily(
    conn: Warehouse,
    client: EODHDClient,
    tickers: Iterable[str] | None = None,
    *, report: bool = False,
) -> int | dict:
    univ = _tickers(conn)
    if tickers:
        wanted = set(tickers)
        univ = [(t, s) for t, s in univ if t in wanted]
    today = date.today()
    inserted = 0
    failures = 0
    for offset in range(0, len(univ), 50):
        batch = univ[offset:offset + 50]
        try:
            resp = client.sentiments(",".join(symbol for _, symbol in batch))
            if resp and not isinstance(resp, dict):
                raise ValueError("Unexpected EODHD sentiment response")
        except Exception as e:
            failures += len(batch)
            log.warning("sentiment ingest skipped %d symbols (%s)", len(batch), type(e).__name__)
            continue
        # response is {"SYMBOL.NSE": [{"date":"YYYY-MM-DD","count":N,"normalized":x}, ...]}
        rows = [(ticker, e["date"], e["normalized"], int(e["count"]), SOURCE, today)
                for ticker, symbol in batch for e in (resp or {}).get(symbol, [])
                if e.get("normalized") is not None and e.get("count")]
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
    return {"status": "partial" if failures else "ok", "rows": inserted, "failures_count": failures} if report else inserted
