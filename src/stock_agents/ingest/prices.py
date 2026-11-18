"""Ingest NSE daily prices + corporate actions from EODHD into DuckDB.

Design:
  - First run (backfill): per-ticker /eod call for the last N years.
  - Daily refresh:        one /eod-bulk-last-day/NSE call for the whole exchange.
  - Corporate actions:    per-ticker /splits + /div (rare, small payloads).

Point-in-time:
  known_date is set to the date we ingested the row (today, UTC). For historical
  backfill that overstates lag, but since the backtest also respects known_date,
  everything shifts together and factor leak stays impossible.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

import duckdb

from stock_agents.common import config as _config
from stock_agents.common.logging import get_logger
from stock_agents.sources.eodhd import EODHDClient

log = get_logger(__name__)

SOURCE = "eodhd"


def _tickers_in_universe(conn: duckdb.DuckDBPyConnection) -> list[tuple[str, str]]:
    """Return [(ticker, eodhd_symbol)] from symbology."""
    return conn.execute(
        "SELECT ticker, eodhd_symbol FROM symbology WHERE active = TRUE ORDER BY ticker"
    ).fetchall()


def _max_date_per_ticker(conn: duckdb.DuckDBPyConnection) -> dict[str, date]:
    rows = conn.execute(
        "SELECT ticker, MAX(date) FROM prices_daily WHERE source = ? GROUP BY ticker",
        [SOURCE],
    ).fetchall()
    return {t: d for t, d in rows}


def backfill_prices(
    conn: duckdb.DuckDBPyConnection,
    client: EODHDClient,
    years: int = 5,
    tickers: Iterable[str] | None = None,
) -> int:
    """Per-ticker /eod backfill. Idempotent (PK = ticker+date+source)."""
    all_univ = _tickers_in_universe(conn)
    if tickers:
        wanted = set(tickers)
        all_univ = [(t, s) for t, s in all_univ if t in wanted]
    end = date.today()
    start = end - timedelta(days=years * 365)
    already = _max_date_per_ticker(conn)
    today = date.today()
    inserted = 0
    for i, (ticker, symbol) in enumerate(all_univ, 1):
        last = already.get(ticker)
        fetch_from = (last + timedelta(days=1)) if last else start
        if fetch_from > end:
            continue
        try:
            rows = client.eod(symbol, start=fetch_from, end=end)
        except Exception as e:
            log.warning("skip %s: %s", ticker, e)
            continue
        if not rows:
            continue
        payload = [
            (
                ticker,
                r["date"],
                r.get("open"),
                r.get("high"),
                r.get("low"),
                r.get("close"),
                r.get("adjusted_close"),
                int(r["volume"]) if r.get("volume") is not None else None,
                SOURCE,
                today,
            )
            for r in rows
        ]
        conn.executemany(
            """INSERT OR REPLACE INTO prices_daily
               (ticker, date, open, high, low, close, adj_close, volume, source, known_date)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            payload,
        )
        inserted += len(payload)
        if i % 20 == 0:
            log.info("priced %d/%d tickers (last %s: %d rows)", i, len(all_univ), ticker, len(payload))
    log.info("backfill done: %d rows inserted/replaced across %d tickers", inserted, len(all_univ))
    return inserted


def ingest_bulk_last_day(
    conn: duckdb.DuckDBPyConnection,
    client: EODHDClient,
    exchange: str,
    trade_date: date | None = None,
) -> int:
    """One API call for the whole exchange. Writes only tickers in symbology."""
    rows = client.bulk_eod(exchange, trade_date=trade_date)
    if not rows:
        return 0
    known = {t: ticker for ticker, t in _tickers_in_universe(conn)} if False else None
    # symbology rows are (ticker, eodhd_symbol). Build symbol -> ticker.
    sym_map = {s: t for t, s in _tickers_in_universe(conn)}
    today = date.today()
    payload = []
    for r in rows:
        code = r.get("code")  # e.g. 'RELIANCE'
        if not code:
            continue
        symbol = f"{code}.{exchange}"
        ticker = sym_map.get(symbol)
        if not ticker:
            continue
        payload.append(
            (
                ticker,
                r.get("date"),
                r.get("open"),
                r.get("high"),
                r.get("low"),
                r.get("close"),
                r.get("adjusted_close"),
                int(r["volume"]) if r.get("volume") is not None else None,
                SOURCE,
                today,
            )
        )
    if not payload:
        return 0
    conn.executemany(
        """INSERT OR REPLACE INTO prices_daily
           (ticker, date, open, high, low, close, adj_close, volume, source, known_date)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        payload,
    )
    log.info("bulk ingest wrote %d rows for %s on %s", len(payload), exchange, trade_date or "latest")
    return len(payload)


def ingest_corporate_actions(
    conn: duckdb.DuckDBPyConnection, client: EODHDClient, tickers: Iterable[str] | None = None
) -> int:
    univ = _tickers_in_universe(conn)
    if tickers:
        wanted = set(tickers)
        univ = [(t, s) for t, s in univ if t in wanted]
    today = date.today()
    n = 0
    for ticker, symbol in univ:
        try:
            splits = client.splits(symbol)
            divs = client.dividends(symbol)
        except Exception as e:
            log.warning("corp actions skip %s: %s", ticker, e)
            continue
        rows = []
        for sp in splits:
            ratio = sp.get("split")
            val = _parse_split_ratio(ratio) if isinstance(ratio, str) else ratio
            rows.append((ticker, "split", sp.get("date"), val, SOURCE, today))
        for dv in divs:
            rows.append((ticker, "dividend", dv.get("date"), dv.get("value"), SOURCE, today))
        if rows:
            conn.executemany(
                """INSERT OR REPLACE INTO corporate_actions
                   (ticker, action_type, ex_date, value, source, known_date)
                   VALUES (?,?,?,?,?,?)""",
                rows,
            )
            n += len(rows)
    log.info("corporate actions: %d rows written", n)
    return n


def _parse_split_ratio(s: str) -> float | None:
    """Convert a split string like '2/1' to the float 2.0."""
    try:
        a, b = s.split("/")
        return float(a) / float(b)
    except Exception:
        return None
