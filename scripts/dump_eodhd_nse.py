"""Export EODHD data and NSE stock F&O membership to CSV.

Run from the repository root: python -m scripts.dump_eodhd_nse --help
"""

from __future__ import annotations

import argparse
import csv
import sys
from contextlib import ExitStack
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from sqlalchemy.exc import SQLAlchemyError

from stock_agents.common import config
from stock_agents.sources.eodhd import EODHDClient
from stock_agents.sources.nse import parse_fo_tickers
from stock_agents.storage.warehouse import connect

NSE_LOT_SIZES = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"
IDENTITY = ("ticker", "symbol")
STATEMENT_META = ("period_type", "date", "filing_date", "currency_symbol")
MARKET_FIELDS = {
    "prices_daily": ("date", "open", "high", "low", "close", "adjusted_close", "volume"),
    "splits": ("date", "split"),
    "dividends": ("date", "value", "unadjustedValue", "currency"),
}
STATEMENTS = {
    "Income_Statement": "income_statement",
    "Balance_Sheet": "balance_sheet",
    "Cash_Flow": "cash_flow",
}
VALUATION_FIELDS = (
    "TrailingPE",
    "ForwardPE",
    "PriceSalesTTM",
    "PriceBookMRQ",
    "EnterpriseValue",
    "EnterpriseValueRevenue",
    "EnterpriseValueEbitda",
)
TABLE_FIELDS = {
    **MARKET_FIELDS,
    "company": (
        "Code",
        "Exchange",
        "Name",
        "ISIN",
        "CurrencyCode",
        "Sector",
        "Industry",
        "FiscalYearEnd",
    ),
    "income_statement": STATEMENT_META
    + (
        "totalRevenue",
        "grossProfit",
        "operatingIncome",
        "ebit",
        "ebitda",
        "netIncome",
        "interestExpense",
    ),
    "balance_sheet": STATEMENT_META
    + (
        "totalAssets",
        "totalStockholderEquity",
        "totalCurrentAssets",
        "totalCurrentLiabilities",
        "cashAndEquivalents",
        "cash",
        "shortTermDebt",
        "longTermDebt",
        "shortLongTermDebtTotal",
        "netDebt",
    ),
    "cash_flow": STATEMENT_META
    + (
        "totalCashFromOperatingActivities",
        "capitalExpenditures",
        "freeCashFlow",
        "dividendsPaid",
        "issuanceOfCapitalStock",
        "salePurchaseOfStock",
    ),
    "earnings_history": (
        "date",
        "reportDate",
        "currency",
        "epsActual",
        "epsEstimate",
        "surprisePercent",
    ),
    "shares_outstanding": ("period_type", "date", "shares"),
    "valuation_snapshot": (
        "retrieved_at_utc",
        "MarketCapitalization",
        "DilutedEpsTTM",
        "BookValue",
        "DividendYield",
    )
    + VALUATION_FIELDS,
    "errors": ("dataset", "error"),
}


def load_universe() -> dict[str, str]:
    with connect(read_only=True) as conn:
        rows = conn.execute(
            """SELECT ticker, eodhd_symbol FROM symbology
               WHERE active AND upper(eodhd_symbol) LIKE '%.NSE' ORDER BY ticker"""
        ).fetchall()
    if not rows:
        raise ValueError("No active NSE symbols in symbology. Load the project universe first.")
    return dict(rows)


def load_fo_tickers(local_csv: Path | None) -> dict[str, str]:
    if local_csv is not None:
        return parse_fo_tickers(local_csv.read_text(encoding="utf-8-sig"))
    response = requests.get(NSE_LOT_SIZES, headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
    response.raise_for_status()
    return parse_fo_tickers(response.content.decode("utf-8-sig"))


def write_fo_tickers(output_dir: Path, tickers: dict[str, str], universe: dict[str, str]) -> None:
    universe_symbols = {symbol.upper() for symbol in universe.values()}
    with (output_dir / "fo_tickers.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("ticker", "symbol", "underlying", "in_universe"))
        for ticker, underlying in sorted(tickers.items()):
            symbol = f"{ticker}.NSE"
            writer.writerow((ticker, symbol, underlying, str(symbol in universe_symbols).lower()))


def fundamental_rows(payload: dict, retrieved_at: str):
    """Yield the selected fields in separate tables at their native reporting frequencies."""
    yield "company", payload.get("General") or {}
    financials = payload["Financials"]
    for section_name, table_name in STATEMENTS.items():
        section = financials.get(section_name) or {}
        for period_type in ("quarterly", "yearly"):
            for row in (section.get(period_type) or {}).values():
                currency = row.get("currency_symbol") or section.get("currency_symbol")
                yield table_name, {**row, "period_type": period_type, "currency_symbol": currency}

    for row in ((payload.get("Earnings") or {}).get("History") or {}).values():
        yield "earnings_history", row
    shares = payload.get("outstandingShares") or {}
    for period_type in ("quarterly", "annual"):
        for row in (shares.get(period_type) or {}).values():
            yield "shares_outstanding", {**row, "period_type": period_type}

    yield (
        "valuation_snapshot",
        {
            **(payload.get("Highlights") or {}),
            **(payload.get("Valuation") or {}),
            "retrieved_at_utc": retrieved_at,
        },
    )


def dump_market_data(
    output_dir: Path, client: EODHDClient, universe: dict[str, str], start: date, end: date
) -> int:
    failures = 0
    with ExitStack() as stack:
        writers = {}
        for table, fields in TABLE_FIELDS.items():
            stream = stack.enter_context(
                (output_dir / f"{table}.csv").open("x", encoding="utf-8", newline="")
            )
            writers[table] = csv.DictWriter(stream, IDENTITY + fields, extrasaction="ignore")
            writers[table].writeheader()

        for index, (ticker, symbol) in enumerate(universe.items(), 1):
            identity = {"ticker": ticker, "symbol": symbol}
            endpoints = {
                "prices_daily": (client.eod, (symbol, start, end)),
                "splits": (client.splits, (symbol,)),
                "dividends": (client.dividends, (symbol,)),
                "fundamentals": (client.fundamentals, (symbol,)),
            }
            for dataset, (fetch, args) in endpoints.items():
                try:
                    payload = fetch(*args)
                    if dataset == "fundamentals":
                        if not isinstance(payload, dict) or not payload.get("Financials"):
                            raise ValueError("EODHD returned no financial statements")
                        rows = list(fundamental_rows(payload, datetime.now(UTC).isoformat()))
                        if any(not isinstance(row, dict) for _, row in rows):
                            raise ValueError("Unexpected EODHD financial record format")
                    else:
                        if not isinstance(payload, list) or any(
                            not isinstance(row, dict) or not row.get("date") for row in payload
                        ):
                            raise ValueError("Unexpected EODHD response format")
                        if dataset == "prices_daily" and not payload:
                            raise ValueError("EODHD returned no prices in the requested date range")
                        rows = [(dataset, row) for row in payload]
                except (RuntimeError, ValueError, AttributeError, TypeError) as exc:
                    failures += 1
                    # The client sanitizes RuntimeError. Never write arbitrary response data to logs.
                    message = (
                        str(exc) if type(exc) in (RuntimeError, ValueError) else type(exc).__name__
                    )
                    writers["errors"].writerow({**identity, "dataset": dataset, "error": message})
                    continue
                for table, row in rows:
                    writers[table].writerow({**row, **identity})
            if index % 25 == 0 or index == len(universe):
                print(f"Processed {index}/{len(universe)} EODHD symbols", flush=True)
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="New directory for the CSV files")
    parser.add_argument(
        "--from-date", type=date.fromisoformat, help="First daily price date, YYYY-MM-DD"
    )
    parser.add_argument(
        "--to-date", type=date.fromisoformat, help="Last daily price date, YYYY-MM-DD"
    )
    parser.add_argument("--ticker", action="append", help="Export one active ticker (repeatable)")
    parser.add_argument(
        "--fo-only", action="store_true", help="Export F&O membership without calling EODHD"
    )
    parser.add_argument(
        "--fo-csv", type=Path, help="Read a local copy of NSE's permitted lot-size CSV"
    )
    args = parser.parse_args(argv)
    settings = config.load_settings()
    end = args.to_date or datetime.now(ZoneInfo(settings.timezone)).date()
    years = settings.raw["data"]["price_lookback_years"]
    start = args.from_date or end - timedelta(days=365 * years)
    if start > end:
        parser.error("--from-date must be on or before --to-date")

    try:
        universe = load_universe()
        selected = universe
        if args.ticker:
            wanted = {ticker.strip().upper().removesuffix(".NSE") for ticker in args.ticker}
            if missing := wanted.difference(universe):
                parser.error(
                    f"Tickers outside the active NSE universe: {', '.join(sorted(missing))}"
                )
            selected = {ticker: symbol for ticker, symbol in universe.items() if ticker in wanted}
        client = None if args.fo_only else EODHDClient.from_env()
        fo_tickers = load_fo_tickers(args.fo_csv)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        output_dir = args.output_dir or settings.paths.raw_dir / "eodhd" / "dump" / stamp
        output_dir.mkdir(parents=True, exist_ok=False)
        write_fo_tickers(output_dir, fo_tickers, universe)
        print(
            f"Wrote {len(fo_tickers)} NSE stock F&O tickers to {output_dir / 'fo_tickers.csv'}",
            flush=True,
        )
        if client is None:
            return 0

        failures = dump_market_data(output_dir, client, selected, start, end)
    except (SQLAlchemyError, OSError, RuntimeError, ValueError, requests.RequestException) as exc:
        print(f"Export failed: {exc}", file=sys.stderr)
        return 1

    print(f"Exported data to {output_dir}")
    if failures:
        print(
            f"{failures} failed requests or responses. See {output_dir / 'errors.csv'}.",
            file=sys.stderr,
        )
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
