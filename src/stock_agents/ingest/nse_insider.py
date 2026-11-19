"""Backfill publicly disclosed NSE insider purchases and sales."""

import argparse
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from stock_agents.common.config import load_settings
from stock_agents.ingest.provider_values import number
from stock_agents.jobs.queue import sync_engine
from stock_agents.sources.nse import NSEClient
from stock_agents.storage.postgres import Base

SOURCE = "nse_insider"
MARKET_TZ = ZoneInfo("Asia/Kolkata")
FILINGS_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading"


class FilingFacts(HTMLParser):
    def __init__(self, document: str):
        super().__init__()
        self.facts: dict[str, dict[str, tuple[str, dict]]] = defaultdict(dict)
        self.current = None
        self.feed(document)
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag in {"ix:nonnumeric", "ix:nonfraction"}:
            fields = dict(attrs)
            self.current = (fields, [])

    def handle_data(self, data):
        if self.current is not None:
            self.current[1].append(data)

    def handle_endtag(self, tag):
        if tag in {"ix:nonnumeric", "ix:nonfraction"} and self.current is not None:
            fields, parts = self.current
            if fields.get("contextref") and fields.get("name"):
                name = fields["name"].split(":")[-1].lower()
                self.facts[fields["contextref"]][name] = ("".join(parts).strip(), fields)
            self.current = None


def parse_filing(document: str, ticker: str, app_id: str, known: date) -> list[dict]:
    facts = FilingFacts(document).facts
    if not facts or not any(fields.get("symbol", ("", {}))[0].upper() == ticker
                            for fields in facts.values()):
        raise ValueError("The filing does not identify the requested NSE symbol")
    rows = []
    for context, fields in facts.items():
        def fact(name, fields=fields):
            return fields.get(name, ("", {}))[0]

        if fact("typeofinstrument").casefold() not in {"equity", "equity shares", "shares"}:
            continue
        mode = fact("modeofacquisitionordisposal").casefold()
        kind = fact("securitiesacquiredordisposedtransactiontype").casefold()
        if "pledge" in kind or "pledge" in mode:
            continue
        direction = {"acquisition": "BUY", "buy": "BUY", "purchase": "BUY",
                     "disposal": "SELL", "sale": "SELL", "sell": "SELL"}.get(kind)
        # Transfers, grants and option exercises are excluded from the trading signal.
        if not direction or mode not in {"market purchase", "market sale", "market sell", "market buy",
                                         "market", "on market", "on-market"}:
            continue
        amount, attrs = fields.get("securitiesacquiredordisposedvalueofsecurity", ("", {}))
        amount = number(amount.replace(",", ""))
        shares = number(fact("securitiesacquiredordisposednumberofsecurity").replace(",", ""))
        if attrs.get("unitref", "").upper() != "INR" or not amount or amount <= 0 or not shares or shares <= 0:
            continue
        scale = int(attrs.get("scale", "0"))
        if not -12 <= scale <= 12:
            raise ValueError("Unexpected INR scale")
        amount = number(amount * 10 ** scale)
        if amount is None:
            raise ValueError("Invalid INR amount")
        tx_date = datetime.strptime(
            fact("dateofallotmentadviceoracquisitionofsharesorsaleofsharesspecifytodate"), "%d-%m-%Y"
        ).date()
        if tx_date > known:
            raise ValueError("Transaction date follows the exchange broadcast date")
        rows.append(dict(tx_id=f"nse:{ticker}:{app_id}:{context}", ticker=ticker, tx_date=tx_date,
                         tx_type=direction, shares=shares, price=amount / shares, value_inr=amount,
                         insider_role=fact("categoryofperson") or None, known_date=known, source=SOURCE))
    return rows


def refresh_insider_filings(days: int = 90) -> dict:
    load_settings()
    now = datetime.now(MARKET_TZ)
    start = now.date() - timedelta(days=days - 1)
    engine = sync_engine()
    table = Base.metadata.tables["insider_tx"]
    symbology = Base.metadata.tables["symbology"]
    with engine.connect() as connection:
        tickers = set(connection.scalars(select(symbology.c.ticker).where(symbology.c.active)))
    client = NSEClient()
    try:
        client.session.get(FILINGS_PAGE, timeout=15).raise_for_status()
        response = client.session.get(
            "https://www.nseindia.com/api/corporates-pit-gg",
            params={"index": "equities", "from_date": start.strftime("%d-%m-%Y"),
                    "to_date": now.strftime("%d-%m-%Y")},
            headers={"Referer": FILINGS_PAGE}, timeout=30,
        )
        response.raise_for_status()
        filings = response.json()["data"]
        if not isinstance(filings, list):
            raise ValueError("Unexpected NSE filing list")
    finally:
        client.close()

    def fetch(job):
        ticker, app_id, known, url, previous = job
        try:
            location = urlsplit(url)
            if (location.scheme != "https" or location.netloc not in
                    {"nsearchives.nseindia.in", "nsearchives.nseindia.com"}
                    or not location.path.startswith("/corporate/ixbrl/")):
                raise ValueError("Unexpected NSE filing link")
            response = requests.get(url, timeout=(6, 10), allow_redirects=False,
                                    headers={"User-Agent": "Mozilla/5.0", "Referer": FILINGS_PAGE})
            if response.status_code != 200:
                raise ValueError(f"NSE filing HTTP {response.status_code}")
            return job, parse_filing(response.text, ticker, app_id, known), None
        except (requests.RequestException, ValueError, OverflowError) as exc:
            return job, [], type(exc).__name__

    jobs = {}
    for filing in filings:
        ticker = filing.get("symbol")
        if ticker not in tickers:
            continue
        broadcast = datetime.strptime(filing["broadcastDateTime"], "%d-%b-%Y %H:%M:%S").replace(tzinfo=MARKET_TZ)
        if not start <= broadcast.date() or broadcast > now:
            continue
        app_id = str(filing["appId"])
        jobs[ticker, app_id] = (ticker, app_id, broadcast.date(), filing.get("ixbrl") or "",
                                filing.get("prevAppId"))
    superseded = {(ticker, str(previous)): known
                  for ticker, _, known, _, previous in jobs.values() if previous}
    rows = []
    failures = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for job, records, error in pool.map(fetch, jobs.values()):
            ticker, app_id, _, _, _ = job
            if error:
                failures.append({"ticker": ticker, "filing": app_id, "error": error})
            for record in records:
                record["superseded_on"] = superseded.get((ticker, app_id))
            rows.extend(records)

    with engine.begin() as connection:
        written = 0
        for offset in range(0, len(rows), 500):
            statement = insert(table).values(rows[offset:offset + 500]).on_conflict_do_nothing()
            written += connection.execute(statement).rowcount
        for (ticker, app_id), known in superseded.items():
            connection.execute(update(table).where(
                table.c.ticker == ticker, table.c.source == SOURCE,
                table.c.tx_id.startswith(f"nse:{ticker}:{app_id}:", autoescape=True),
                table.c.superseded_on.is_(None),
            ).values(superseded_on=known))
    return {"filings": len(jobs), "trade_rows": len(rows), "written": written, "failures": failures}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=90, choices=range(1, 91), metavar="1-90")
    print(json.dumps(refresh_insider_filings(parser.parse_args().days)))
