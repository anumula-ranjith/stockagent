"""Load the universe seed CSV into the DuckDB warehouse.

Populates:
  - symbology       (ticker -> EODHD symbol)
  - classification  (ticker -> sector, industry)  effective_date = today, known_date = today
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import duckdb

from stock_agents.common import config as _config
from stock_agents.common.logging import get_logger

log = get_logger(__name__)


def load_universe(conn: duckdb.DuckDBPyConnection, seed_csv: Path, exchange_suffix: str) -> int:
    """Return number of tickers loaded."""
    rows = list(csv.DictReader(open(seed_csv)))
    today = date.today()
    sym_rows = [
        (r["ticker"], f"{r['ticker']}{exchange_suffix}", None, None, None, True, today)
        for r in rows
    ]
    conn.execute("BEGIN")
    conn.executemany(
        """INSERT OR REPLACE INTO symbology
           (ticker, eodhd_symbol, factset_id, isin, cusip, active, updated_at)
           VALUES (?,?,?,?,?,?,?)""",
        sym_rows,
    )
    cls_rows = [
        (r["ticker"], today, today, r.get("sector"), r.get("industry"), "seed_csv") for r in rows
    ]
    conn.executemany(
        """INSERT OR REPLACE INTO classification
           (ticker, effective_date, known_date, sector, industry, source)
           VALUES (?,?,?,?,?,?)""",
        cls_rows,
    )
    conn.execute("COMMIT")
    return len(rows)


def main() -> int:
    s = _config.load_settings()
    conn = duckdb.connect(str(s.paths.duckdb))
    from stock_agents.storage.schema import init_schema

    init_schema(conn)
    suffix = getattr(s, "exchange_suffix", ".NSE")
    seed = _config.project_root() / s.universe_seed_csv
    n = load_universe(conn, seed, suffix)
    log.info("universe loaded: %d tickers", n)
    print(f"Loaded {n} tickers into symbology + classification")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
