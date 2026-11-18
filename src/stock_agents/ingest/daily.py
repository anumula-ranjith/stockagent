"""Refresh Nifty 500 and NSE F&O stocks directly in PostgreSQL."""

from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Date, String, column, delete, func, or_, select, update, values
from sqlalchemy.dialects.postgresql import insert

from stock_agents.common.config import load_settings
from stock_agents.sources.eodhd import EODHDClient
from stock_agents.sources.nse import EODNotReady, NSEClient
from stock_agents.storage.postgres import Base

MARKET_TZ = ZoneInfo("Asia/Kolkata")


def _upsert(target, table_name: str, records: list[dict]) -> int:
    """Update changed values while retaining the first-known date for identical rows."""
    table = Base.metadata.tables[table_name]
    written = 0
    for offset in range(0, len(records), 1000):
        statement = insert(table).values(records[offset:offset + 1000])
        values = {c.name: statement.excluded[c.name] for c in table.columns
                  if not c.primary_key and c.name in records[0]}
        comparisons = [table.c[name].is_distinct_from(value) for name, value in values.items()
                       if name not in {"known_date", "updated_at"}]
        statement = statement.on_conflict_do_update(
            index_elements=list(table.primary_key.columns), set_=values,
            where=or_(*comparisons),
        )
        written += target.execute(statement).rowcount
    return written


def _membership(target, groups: dict[str, set[str]], observed: date) -> None:
    table = Base.metadata.tables["index_membership"]
    for index_code, members in groups.items():
        current = set(target.execute(select(table.c.ticker).where(
            table.c.index_code == index_code, table.c.left_on.is_(None)
        )).scalars())
        departed = current - members
        if departed:
            target.execute(update(table).where(
                table.c.index_code == index_code, table.c.left_on.is_(None),
                table.c.ticker.in_(departed),
            ).values(left_on=observed))
        new_rows = [dict(index_code=index_code, ticker=t, joined_on=observed, known_on=observed)
                    for t in sorted(members - current)]
        if new_rows:
            target.execute(insert(table).values(new_rows).on_conflict_do_update(
                index_elements=list(table.primary_key.columns), set_={"left_on": None},
            ))


def _vendor_data(client, ticker: str, start: date, end: date, known: date) -> tuple:
    prices, actions, errors = {}, [], []
    symbol = ticker + ".NSE"
    try:
        rows = client.eod(symbol, start=start, end=end)
        if not isinstance(rows, list):
            raise ValueError("EODHD prices are not a list")
        for row in rows:
            day = date.fromisoformat(row["date"])
            if not start <= day <= end:
                raise ValueError("EODHD returned an unexpected date")
            if row.get("volume") == 0:
                continue
            values = [row[key] for key in ("open", "high", "low", "close", "adjusted_close", "volume")]
            if not all(isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in values):
                raise ValueError("EODHD returned invalid price values")
            opening, high, low, close, adj_close, volume = values
            if not low <= min(opening, close) <= max(opening, close) <= high:
                raise ValueError("EODHD returned inconsistent OHLC")
            if day in prices:
                raise ValueError("EODHD returned duplicate dates")
            prices[day] = dict(ticker=ticker, date=day, open=opening, high=high, low=low,
                               close=close, adj_close=adj_close, volume=int(volume),
                               source="eodhd", known_date=known)
    except Exception as exc:
        prices = {}
        errors.append({"ticker": ticker, "dataset": "prices", "error": type(exc).__name__})
    for method, kind in ((client.splits, "split"), (client.dividends, "dividend")):
        try:
            rows = method(symbol)
            if not isinstance(rows, list):
                raise ValueError("EODHD actions are not a list")
            for row in rows:
                day = date.fromisoformat(row["date"])
                if day > end:
                    continue
                if kind == "split":
                    numerator, denominator = row["split"].split("/")
                    value = float(numerator) / float(denominator)
                else:
                    value = float(row["value"])
                if not math.isfinite(value) or value < 0:
                    raise ValueError("EODHD returned an invalid action")
                actions.append(dict(ticker=ticker, action_type=kind, ex_date=day,
                                    value=value, source="eodhd", known_date=known))
        except Exception as exc:
            errors.append({"ticker": ticker, "dataset": kind, "error": type(exc).__name__})
    return ticker, prices, actions, errors


def _write_prices(target, records: list[dict]) -> int:
    """A vendor backfill replaces a fallback without creating duplicate daily bars."""
    table = Base.metadata.tables["prices_daily"]
    fallback_keys = [(r["ticker"], r["date"]) for r in records if r["source"] == "nse_bhavcopy"]
    if fallback_keys:
        keys = values(column("ticker", String), column("date", Date), name="fallback").data(fallback_keys)
        existing = target.execute(select(table).where(
            table.c.ticker == keys.c.ticker, table.c.date == keys.c.date,
            table.c.source == "eodhd", table.c.adj_close.is_not(None),
        )).mappings().all()
        covered = {(r["ticker"], r["date"]): r for r in existing}
        retained = []
        for row in records:
            prior = covered.get((row["ticker"], row["date"]))
            matches = prior is not None and all(
                prior[field] is not None and abs(prior[field] - row[field]) <= 0.011
                for field in ("open", "high", "low", "close")
            )
            if row["source"] != "nse_bhavcopy" or not matches:
                retained.append(row)
        records = retained
    for offset in range(0, len(records), 1000):
        batch = records[offset:offset + 1000]
        # Join exact pairs through a values relation, avoiding a wide date/ticker cross product.
        keys = values(column("ticker", String), column("date", Date), column("source", String),
                      name="incoming").data([(r["ticker"], r["date"], r["source"]) for r in batch])
        target.execute(delete(table).where(
            table.c.ticker == keys.c.ticker, table.c.date == keys.c.date,
            table.c.source != keys.c.source, table.c.source.in_(("eodhd", "nse_bhavcopy")),
        ))
    return _upsert(target, "prices_daily", records)


def _retry_selection(target, traded: set[str], trade_date: date, final: dict, supported: set[str]) -> tuple:
    """Reuse healthy bars from a completed attempt for this exact trading date."""
    run_table = Base.metadata.tables["run_log"]
    prior = target.execute(select(run_table.c.warnings).where(
        run_table.c.run_id == f"nse-eod-{trade_date}",
        run_table.c.status.in_(("ok", "warning")), run_table.c.ended_at.is_not(None),
    )).scalar_one_or_none()
    if not prior:
        return traded, {}
    result = json.loads(prior)
    if result.get("trade_date") != trade_date.isoformat() or result.get("missing"):
        return traded, {}
    membership = Base.metadata.tables["index_membership"]
    prior_members = set(result.get("universe_symbols") or target.execute(
        select(membership.c.ticker).where(membership.c.index_code.in_(("NIFTY500", "NSE_FO")),
                                         membership.c.left_on.is_(None))
    ).scalars())
    failed = {error["ticker"] for error in result.get("vendor_errors", []) if "ticker" in error}
    prices = Base.metadata.tables["prices_daily"]
    rows = target.execute(select(prices).where(
        prices.c.ticker.in_(traded), prices.c.date == trade_date,
        prices.c.source.in_(("eodhd", "nse_bhavcopy")),
    ).order_by(prices.c.source.desc())).mappings().all()
    # EODHD sorts after the fallback during construction, so adjusted prices win.
    current = {row["ticker"]: dict(row) for row in rows}
    reusable = {}
    for ticker, row in current.items():
        if ticker not in prior_members or ticker in failed:
            continue
        if row["adj_close"] is None and ticker in supported:
            continue
        if all(row[field] is not None and abs(row[field] - final[ticker][field]) <= 0.011
               for field in ("open", "high", "low", "close")):
            reusable[ticker] = {trade_date: row}
    return traded - reusable.keys(), reusable


def refresh_eod(target, trade_date: date | None = None, *, nse=None, client=None) -> dict:
    """Run inside the caller's transaction. Raise on incomplete exchange coverage.

    NSE membership is a snapshot known today. A historical catch-up does not backdate
    membership. The caller owns commit/rollback and the shared ingestion lock.
    """
    settings = load_settings()
    known = datetime.now(MARKET_TZ).date()
    trade_date = trade_date or known
    if trade_date > known:
        raise ValueError("A future EOD date cannot be loaded")
    started = datetime.now(UTC).replace(tzinfo=None)
    own_nse = nse is None
    nse = nse or NSEClient()
    client = client or EODHDClient.from_env()
    try:
        final = nse.bhavcopy(trade_date)
        nifty = nse.nifty500()
        fo = nse.fo_stocks()
        groups = {"NIFTY500": set(nifty), "NSE_FO": set(fo)}
        members = groups["NIFTY500"] | groups["NSE_FO"]
        placeholders = {t for t in members if t.startswith("DUMMY")}
        traded = members - placeholders
        missing = sorted(traded - final.keys())
        if missing:
            raise RuntimeError("NSE final file is missing universe symbols: " + ", ".join(missing))
        for ticker in traded & nifty.keys():
            if nifty[ticker]["isin"] != final[ticker]["isin"]:
                raise RuntimeError(f"NSE membership and Bhavcopy ISIN differ for {ticker}")

        table = Base.metadata.tables["prices_daily"]
        last = dict(target.execute(select(table.c.ticker, func.max(table.c.date)).where(
            table.c.ticker.in_(traded), table.c.date <= trade_date,
        ).group_by(table.c.ticker)).all())
        history_start = trade_date - timedelta(days=365 * settings.raw.get("data", {}).get("price_lookback_years", 10))
        earliest = dict(target.execute(select(table.c.ticker, func.min(table.c.date)).where(
            table.c.ticker.in_(traded), table.c.source == "eodhd",
        ).group_by(table.c.ticker)).all())
        action_table = Base.metadata.tables["corporate_actions"]
        prior_actions = {(row.ticker, row.action_type, row.ex_date): row.value for row in target.execute(
            select(action_table).where(action_table.c.ticker.in_(traded), action_table.c.source == "eodhd")
        )}
        starts = {t: max(history_start, last[t] - timedelta(days=7)) if t in last else history_start
                  for t in traded}
        requested, prices = _retry_selection(target, traded, trade_date, final, set(earliest))
        actions, errors = [], []
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = [pool.submit(_vendor_data, client, t, starts[t], trade_date, known)
                       for t in sorted(requested)]
            for future in futures:
                ticker, rows, corporate, failures = future.result()
                prices[ticker] = rows
                actions.extend(corporate)
                errors.extend(failures)

        # Adjusted close is revised throughout history when a dividend or split
        # arrives. Re-download the retained history for only the affected stocks.
        revised = {row["ticker"] for row in actions if row["ticker"] in last and
                   prior_actions.get((row["ticker"], row["action_type"], row["ex_date"])) != row["value"]}
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = [pool.submit(_vendor_data, client, ticker,
                                   min(history_start, earliest.get(ticker, history_start)),
                                   trade_date, known) for ticker in sorted(revised)]
            for future in futures:
                ticker, rows, _, failures = future.result()
                if not rows or any(error["dataset"] == "prices" for error in failures):
                    raise RuntimeError(f"Adjusted history refresh failed for {ticker}")
                prices[ticker] = rows
                errors.extend(failures)

        vendor_supported = set(earliest) | {
            ticker for ticker, rows in prices.items()
            if any(row["source"] == "eodhd" for row in rows.values())
        }

        # Exchange files fill vendor omissions across downtime. For a newly listed
        # symbol with no vendor coverage, start with the latest 31 calendar days.
        fallback_starts = {t: last.get(t, trade_date - timedelta(days=31)) + timedelta(days=1)
                           for t in traded if trade_date not in prices[t]}
        exchange_files = {trade_date: final}
        first_gap = min(fallback_starts.values(), default=trade_date)
        day = first_gap
        while day < trade_date:
            try:
                exchange_files[day] = nse.bhavcopy(day)
            except EODNotReady:
                # Missing historical files are recorded, rather than inventing bars.
                errors.append({"date": day.isoformat(), "dataset": "nse_archive", "error": "unavailable"})
            day += timedelta(days=1)

        fallback_count = 0
        for day, rows in exchange_files.items():
            for ticker in traded:
                if ticker not in rows:
                    continue
                vendor = prices[ticker].get(day)
                exchange = rows[ticker]
                if day == trade_date and vendor is not None:
                    if any(abs(vendor[key] - exchange[key]) > 0.011 for key in ("open", "high", "low", "close")):
                        errors.append({"ticker": ticker, "dataset": "prices", "error": "NSE OHLC mismatch"})
                        vendor = None
                if vendor is None and (day == trade_date or day >= fallback_starts.get(ticker, trade_date)):
                    prices[ticker][day] = {key: value for key, value in exchange.items()
                                          if key not in {"isin", "series"}}
                    prices[ticker][day]["known_date"] = known
                    fallback_count += 1

        references = []
        for ticker in sorted(members):
            member = nifty.get(ticker, {})
            references.append(dict(ticker=ticker,
                eodhd_symbol=ticker + ".NSE" if ticker not in placeholders else None,
                isin=member.get("isin") or final.get(ticker, {}).get("isin"),
                active=ticker not in placeholders, updated_at=datetime.now(UTC)))
        _upsert(target, "symbology", references)
        _membership(target, groups, known)
        cls = Base.metadata.tables["classification"]
        sectors = dict(target.execute(select(cls.c.ticker, cls.c.sector).where(
            cls.c.ticker.in_(nifty), cls.c.sector.is_not(None), cls.c.known_date <= known,
        ).distinct(cls.c.ticker).order_by(cls.c.ticker, cls.c.effective_date.desc(), cls.c.known_date.desc())).all())
        classifications = [dict(ticker=t, effective_date=known, known_date=known,
                                sector=sectors.get(t), industry=m["industry"], source="nse_indices")
                           for t, m in nifty.items()]
        _upsert(target, "classification", classifications)
        flat_prices = [row for rows in prices.values() for row in rows.values()]
        count = _write_prices(target, flat_prices)
        action_count = _upsert(target, "corporate_actions", actions)
        adjusted = set(target.execute(select(table.c.ticker).where(
            table.c.ticker.in_(traded), table.c.date == trade_date, table.c.adj_close.is_not(None),
        )).scalars())
        missing_adjusted = sorted(traded - adjusted)
        errors.extend({"ticker": ticker, "dataset": "prices", "error": "awaiting_adjusted_close"}
                      for ticker in missing_adjusted if ticker in vendor_supported)
        historical_gaps = [error for error in errors if error["dataset"] == "nse_archive"]
        errors = [error for error in errors if error["dataset"] != "nse_archive"]
        result = dict(status="warning" if errors else "ok",
                      trade_date=trade_date.isoformat(), nifty500=len(nifty), fo_stocks=len(fo),
                      union_stocks=len(traded), covered=len(traded), rows_written=count,
                      corporate_actions_written=action_count, fallback_rows=fallback_count,
                      adjusted_history_refreshed=sorted(revised),
                      vendor_tickers_requested=sorted(requested), universe_symbols=sorted(traded),
                      placeholders=sorted(placeholders), missing=[],
                      missing_adjusted=missing_adjusted, vendor_errors=errors,
                      limitations={"unavailable_historical_files": historical_gaps,
                                   "adjusted_close_unavailable": missing_adjusted,
                                   "new_vendor_unsupported_history_days": 31})
        run_table = Base.metadata.tables["run_log"]
        statement = insert(run_table).values(
            run_id=f"nse-eod-{trade_date}", job="nse_eod", started_at=started,
            ended_at=datetime.now(UTC).replace(tzinfo=None), status=result["status"],
            rows_written=count, warnings=json.dumps(result, sort_keys=True),
        )
        target.execute(statement.on_conflict_do_update(index_elements=[run_table.c.run_id],
            set_={c.name: statement.excluded[c.name] for c in run_table.columns if not c.primary_key}))
        return result
    finally:
        if own_nse:
            nse.close()
