"""Back-adjust NSE fallback closes using verified exchange corporate actions."""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, func, select, update
from sqlalchemy.dialects.postgresql import insert

from stock_agents.storage.postgres import Base


def adjusted_closes(prices: list[dict], actions: list[dict], asof: date) -> dict[date, float]:
    """Anchor to asof close and apply subsequent cash/split factors backwards.

    Cash factor = 1 - distribution / the exchange-verified previous close.
    An ex-date's close excludes that day's adjustment, which affects older bars.
    """
    rows = sorted((row for row in prices if row["date"] <= asof), key=lambda row: row["date"])
    days = [row["date"] for row in rows]
    if not rows or len(set(days)) != len(days):
        raise ValueError("Adjustment input needs unique daily closes")
    if any(row["close"] is None or not math.isfinite(row["close"]) or row["close"] <= 0 for row in rows):
        raise ValueError("Adjustment input contains an invalid closing price")
    factors = []
    seen = set()
    for action in actions:
        ex_date = action["ex_date"]
        if not days[0] < ex_date <= asof:
            continue
        value = action["value"]
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Invalid corporate-action value")
        kind = action["action_type"]
        key = (ex_date, kind)
        if key in seen:
            raise ValueError("Duplicate corporate action")
        seen.add(key)
        kinds = {event["action_type"] for event in actions if event["ex_date"] == ex_date}
        if len(kinds & {"cash", "dividend", "distribution"}) > 1:
            raise ValueError("Multiple cash action types require a verified combined amount")
        if kinds & {"split", "bonus"} and kinds & {"cash", "dividend", "distribution"}:
            raise ValueError("Combined cash and share action requires a verified per-share basis")
        if kind in {"cash", "dividend", "distribution"}:
            previous = action.get("previous_close")
            if previous is None or not math.isfinite(previous) or previous <= 0:
                raise ValueError("Missing verified pre-ex-date close")
            factor = 1 - value / previous
        elif kind == "split":
            factor = 1 / value
        elif kind == "bonus":
            factor = 1 / (1 + value)
        else:
            raise ValueError("Unsupported corporate action")
        if not math.isfinite(factor) or factor <= 0:
            raise ValueError("Invalid adjustment factor")
        factors.append((ex_date, factor))
    result = {}
    for row in rows:
        adjustment = math.prod(factor for day, factor in factors if row["date"] < day)
        result[row["date"]] = round(row["close"] * adjustment, 8)
    return result


def refresh_adjustments(target, nse, trade_date: date, tickers: set[str]) -> dict:
    """Refresh all retained fallback history so later distributions restate it.

    The caller owns the transaction and ingestion lock. Price-source attribution
    remains NSE Bhavcopy. quality_log records the separate adjustment methodology.
    """
    table = Base.metadata.tables["prices_daily"]
    symbols = Base.metadata.tables["symbology"]
    candidates = target.execute(select(table.c.ticker, symbols.c.isin, func.min(table.c.date)).join(
        symbols, symbols.c.ticker == table.c.ticker,
    ).where(table.c.source == "nse_bhavcopy", table.c.date <= trade_date,
            table.c.ticker.in_(tickers)).group_by(table.c.ticker, symbols.c.isin)).all()
    errors, completed = [], []
    written = 0
    known = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    previous_closes = {}
    for ticker, isin, start in candidates:
        try:
            if not isin:
                raise ValueError("ISIN is required for corporate-action validation")
            prices = target.execute(select(table).where(
                table.c.ticker == ticker, table.c.date.between(start, trade_date),
                table.c.source.in_(("nse_bhavcopy", "eodhd")),
            ).order_by(table.c.date)).mappings().all()
            actions = nse.corporate_actions(ticker, start + timedelta(days=1), trade_date, isin)
            # The exchange's ex-date file provides the preceding session's close.
            # Do not infer it from potentially incomplete retained price history.
            actions = [dict(action) for action in actions]
            for action in actions:
                if action["action_type"] not in {"cash", "dividend", "distribution"}:
                    continue
                day = action["ex_date"]
                if day not in previous_closes:
                    previous_closes[day] = nse.previous_closes(day)
                reference = previous_closes[day].get(ticker)
                if not reference or reference["isin"] != isin:
                    raise ValueError("Previous-close identity does not match the corporate action")
                action["previous_close"] = reference["close"]
            calculated = adjusted_closes(prices, actions, trade_date)
        except Exception as error:
            errors.append({"ticker": ticker, "dataset": "adjustments", "error": type(error).__name__})
            continue
        replacements = [dict(price_date=row["date"], adjusted=calculated[row["date"]])
                        for row in prices if row["source"] == "nse_bhavcopy" and
                        row["adj_close"] != calculated[row["date"]]]
        if replacements:
            target.execute(update(table).where(
                table.c.ticker == ticker, table.c.source == "nse_bhavcopy",
                table.c.date == bindparam("price_date"),
            ).values(adj_close=bindparam("adjusted"), known_date=known), replacements)
        written += len(replacements)
        completed.append(ticker)
        action_table = Base.metadata.tables["corporate_actions"]
        for action in actions:
            statement = insert(action_table).values(
                ticker=ticker, action_type=action["action_type"], ex_date=action["ex_date"],
                value=action["value"], source="nse", known_date=known,
            )
            target.execute(statement.on_conflict_do_update(
                index_elements=list(action_table.primary_key.columns),
                set_={"value": statement.excluded.value, "known_date": statement.excluded.known_date},
                where=action_table.c.value.is_distinct_from(statement.excluded.value),
            ))
        target.execute(insert(Base.metadata.tables["quality_log"]).values(
            run_id=f"nse-eod-{trade_date}", ts=datetime.now(UTC).replace(tzinfo=None),
            check_name="nse_adjusted_close", severity="info", passed=True,
            detail=json.dumps(dict(ticker=ticker, isin=isin, start=str(start), asof=str(trade_date),
                method="backward_cash_split_adjustment", anchor="latest raw close",
                source="https://www.nseindia.com/api/corporates-corporateActions",
                rows_updated=len(replacements), actions=actions), default=str),
        ))
    return {"rows_written": written, "tickers": sorted(completed), "errors": errors}
