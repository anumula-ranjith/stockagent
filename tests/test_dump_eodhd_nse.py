import csv
import gzip
import json
from datetime import date

import pytest

FO_CSV = """UNDERLYING , SYMBOL, NOV-26
NIFTY 50, NIFTY, 65
Derivatives on Individual Securities, Symbol, NOV-26
RELIANCE INDUSTRIES, RELIANCE, 500
BAJAJ AUTO, BAJAJ-AUTO, 75
"""


def test_export_filters_universe_and_preserves_financial_history(
    tmp_path, _isolated_paths, monkeypatch, auth_database
):
    from scripts import dump_eodhd_nse as exporter
    from stock_agents.storage.warehouse import connect

    settings = _isolated_paths
    with connect() as conn:
        conn.execute("""INSERT INTO symbology(ticker, eodhd_symbol, active) VALUES
            ('RELIANCE', 'RELIANCE.NSE', TRUE), ('HAL', 'HAL.NSE', TRUE),
            ('BAJAJ-AUTO', 'BAJAJ-AUTO.NSE', FALSE), ('AAPL', 'AAPL.US', TRUE)""")

    class FixtureClient:
        def load(self, symbol, endpoint):
            if symbol == "HAL.NSE":
                raise RuntimeError("fixture unavailable")
            assert symbol == "RELIANCE.NSE"
            with gzip.open(settings.paths.fixtures_dir / f"eodhd_{endpoint}.json.gz", "rt") as f:
                return json.load(f)

        def eod(self, symbol, start, end):
            assert (start, end) == (date(2026, 10, 1), date(2026, 11, 17))
            return self.load(symbol, "eod")

        def splits(self, symbol):
            return self.load(symbol, "splits")

        def dividends(self, symbol):
            return self.load(symbol, "div")

        def fundamentals(self, symbol):
            return self.load(symbol, "fundamentals")

    monkeypatch.setattr(exporter.EODHDClient, "from_env", FixtureClient)
    fo_source = tmp_path / "fo.csv"
    fo_source.write_text(FO_CSV, encoding="utf-8")
    output = tmp_path / "dump"

    def rows(name):
        with (output / f"{name}.csv").open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    assert (
        exporter.main(
            [
                "--output-dir",
                str(output),
                "--fo-csv",
                str(fo_source),
                "--from-date",
                "2026-10-01",
                "--to-date",
                "2026-11-17",
            ]
        )
        == 1
    )
    assert [(row["ticker"], row["in_universe"]) for row in rows("fo_tickers")] == [
        ("BAJAJ-AUTO", "false"),
        ("RELIANCE", "true"),
    ]
    assert {row["symbol"] for row in rows("prices_daily")} == {"RELIANCE.NSE"}
    assert all(row["adjusted_close"] for row in rows("prices_daily"))
    statements = rows("income_statement")
    assert {row["period_type"] for row in statements} == {"quarterly", "yearly"}
    assert all(row["filing_date"] and row["currency_symbol"] == "INR" for row in statements)
    assert rows("balance_sheet") and rows("cash_flow") and rows("earnings_history")
    assert rows("dividends")[0]["unadjustedValue"] and rows("splits")[0]["split"]
    assert rows("valuation_snapshot")[0]["retrieved_at_utc"]
    assert {row["ticker"] for row in rows("errors")} == {"HAL"}


def test_lot_size_csv_requires_stock_section():
    from scripts.dump_eodhd_nse import parse_fo_tickers

    with pytest.raises(ValueError, match="Individual Securities"):
        parse_fo_tickers("UNDERLYING, SYMBOL\nNIFTY 50, NIFTY\n")
