"""Import reported NSE cash-market short sales and matching exchange volume."""

import argparse
import csv
import io
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from stock_agents.common.config import load_settings
from stock_agents.jobs.queue import sync_engine
from stock_agents.sources.nse import EODNotReady, NSEClient
from stock_agents.storage.postgres import Base

ARCHIVE = "https://nsearchives.nseindia.in/archives/equities/shortSelling"
MARKET_TZ = ZoneInfo("Asia/Kolkata")


def parse_report(payload: str, report_date: date) -> dict[tuple[date, str], int]:
    report = csv.DictReader(io.StringIO(payload.lstrip("\ufeff")))
    if not {"Symbol Name", "Trade Date", "Quantity"}.issubset(report.fieldnames or ()):
        raise ValueError("Unexpected NSE short-selling CSV header")
    quantities: Counter[tuple[date, str]] = Counter()
    for row in report:
        ticker = row["Symbol Name"].strip().upper()
        date_text = row["Trade Date"].strip()
        date_format = "%d-%b-%y" if len(date_text.rsplit("-", 1)[-1]) == 2 else "%d-%b-%Y"
        trade_date = datetime.strptime(date_text, date_format).date()
        quantity = int(row["Quantity"].replace(",", "").strip())
        if not ticker or trade_date > report_date or quantity < 0:
            raise ValueError("Invalid short-selling report row")
        quantities[trade_date, ticker] += quantity
    return quantities


def _fetch_report(report_date, symbols):
    client = NSEClient()
    try:
        response = client.session.get(
            f"{ARCHIVE}/shortselling_{report_date:%d%m%Y}.csv", timeout=(6, 12)
        )
        if response.status_code == 404:
            return "unavailable", [], 0
        response.raise_for_status()
        quantities = parse_report(response.content.decode("utf-8-sig"), report_date)
        eligible = {(day, ticker): qty for (day, ticker), qty in quantities.items() if ticker in symbols}
        books = {day: client.bhavcopy(day) for day in {day for day, _ in eligible}}
        rows = []
        skipped = 0
        for (day, ticker), quantity in eligible.items():
            volume = books[day].get(ticker, {}).get("volume", 0)
            if volume <= 0 or quantity > volume:
                skipped += 1
                continue
            rows.append(dict(ticker=ticker, trade_date=day, known_date=report_date,
                             short_quantity=quantity, traded_quantity=volume))
        return "ok", rows, skipped
    except (requests.RequestException, EODNotReady, ValueError) as exc:
        return type(exc).__name__, [], 0
    finally:
        client.close()


def refresh_short_selling(start: date, end: date) -> dict:
    from stock_agents.jobs.pipelines import market_calendar
    load_settings()
    today = datetime.now(MARKET_TZ).date()
    if not start <= end <= today:
        raise ValueError("Report dates must be ordered and cannot be in the future")
    engine = sync_engine()
    table = Base.metadata.tables["nse_short_selling"]
    symbology = Base.metadata.tables["symbology"]
    with engine.connect() as connection:
        symbols = set(connection.scalars(select(symbology.c.ticker).where(symbology.c.active)))
        log = Base.metadata.tables["run_log"]
        stored = set(connection.scalars(select(log.c.run_id).where(log.c.job == "nse_short_selling", log.c.status == "ok")))
    dates = [day.date() for day in market_calendar().valid_days(start, end)]
    pending = [day for day in dates if f"short-selling-{day}" not in stored]
    counts: Counter[str] = Counter()
    counts["already_loaded"] = len(dates) - len(pending)
    counts["non_trading_days"] = (end-start).days + 1 - len(dates)
    errors = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        for day, (status, rows, skipped) in zip(
            pending, pool.map(lambda d: _fetch_report(d, symbols), pending), strict=True
        ):
            counts[status] += 1
            counts["unmatched_volume"] += skipped
            if status != "ok":
                errors[str(day)] = status
            if status == "ok":
                with engine.begin() as connection:
                    if rows:
                        statement = insert(table).values(rows)
                        counts["inserted"] += connection.execute(statement.on_conflict_do_update(
                            index_elements=list(table.primary_key.columns),
                            set_={"short_quantity": statement.excluded.short_quantity, "traded_quantity": statement.excluded.traded_quantity})).rowcount
                    if not skipped:
                        record = insert(log).values(run_id=f"short-selling-{day}", job="nse_short_selling",
                            started_at=datetime.now().replace(tzinfo=None), ended_at=datetime.now().replace(tzinfo=None),
                            status="ok", rows_written=len(rows), warnings=json.dumps({"report_date":str(day),"rows":len(rows)}))
                        connection.execute(record.on_conflict_do_update(index_elements=[log.c.run_id],
                            set_={"status":"ok", "rows_written":len(rows), "warnings":record.excluded.warnings, "ended_at":record.excluded.ended_at}))
    return {**counts, "errors": errors, "status":"partial" if errors or counts["unmatched_volume"] else "ok"}


if __name__ == "__main__":
    today = datetime.now(MARKET_TZ).date()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=today - timedelta(days=29))
    parser.add_argument("--end", type=date.fromisoformat, default=today)
    args = parser.parse_args()
    print(json.dumps(refresh_short_selling(args.start, args.end)))
